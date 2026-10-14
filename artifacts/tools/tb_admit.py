#!/usr/bin/env python3
"""Admission showdown driver v2 (runs ON the physical PVE host).

Improvements over v1:
  * persistent per-round log with tracebacks (no more silent stops)
  * rich per-step sampling: busy series + per-VM rate series (single ssh per
    VM, N samples per step) — sync mode positions the series to start inside
    the wall-clock burst window (burners run `--aligned`, duty<1)
  * decisions unchanged; an exception during decide() degrades to defer
    with reason "error:..." instead of killing the run

Usage:
  python3 tb_admit.py --round show_rand_fixed --mode rand --policy fixed --step 2 --max 40
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import statistics
import subprocess
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

KEY = "/root/.ssh/tb_key"
PROBE_VM = "10.10.0.20"
SVC = {"http": "10.10.0.11", "redis": "10.10.0.12"}
CUSTOMERS = {vmid: "10.10.0.%d" % (vmid - 290) for vmid in range(311, 375)}
SERVICE_PIN = {"svc-http": (301, "2"), "svc-redis": (302, "3"), "probe": (310, "4")}
SSH = ["-n", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
       "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=8",
       "-o", "LogLevel=ERROR"]
BASE_RATE = 25.9e6
VIOL_FRAC = 0.50
SLO = 10.0

LOGF = None


def log(msg):
    line = "[%s] %s" % (dt.datetime.now().strftime("%F %T"), msg)
    print(line, flush=True)
    if LOGF:
        try:
            LOGF.write(line + "\n")
            LOGF.flush()
        except OSError:
            pass


def vm_cmd(ip, cmd, timeout=60):
    try:
        res = subprocess.run(["ssh"] + SSH + ["debian@" + ip, cmd],
                             capture_output=True, text=True, timeout=timeout)
        return res.stdout
    except subprocess.TimeoutExpired:
        return ""


def pin(vmid, cpu_spec):
    subprocess.run(
        'pid=$(cat /run/qemu-server/%d.pid 2>/dev/null) && [ -n "$pid" ] && '
        'taskset -apc %s $pid >/dev/null 2>&1; true' % (vmid, cpu_spec),
        shell=True, capture_output=True, timeout=15)


def parse_cpus(spec):
    out = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def cgroup_stat(vmid):
    d = {}
    try:
        with open("/sys/fs/cgroup/qemu.slice/%d.scope/cpu.stat" % vmid) as fh:
            for line in fh:
                k, v = line.split()
                d[k] = int(v)
    except (OSError, ValueError):
        pass
    return d


def pool_busy_snapshot(cpus):
    tot = {}
    with open("/proc/stat") as fh:
        for line in fh:
            if not line.startswith("cpu") or line.startswith("cpu "):
                continue
            parts = line.split()
            if not parts[0][3:].isdigit():
                break
            c = int(parts[0][3:])
            if c in cpus:
                v = [int(x) for x in parts[1:11]]
                tot[c] = (sum(v), v[3] + v[4])
    return tot


def pool_busy(cpus, secs=2.0):
    a = pool_busy_snapshot(cpus)
    time.sleep(secs)
    b = pool_busy_snapshot(cpus)
    busy = idle = 0
    for c in cpus:
        if c in a and c in b:
            busy += b[c][0] - a[c][0]
            idle += b[c][1] - a[c][1]
    return round(100.0 * (1.0 - idle / busy), 1) if busy else None


class UsageSampler(threading.Thread):
    """1 s per-VM usage (cores) history from local cgroup files."""

    def __init__(self):
        super().__init__(daemon=True)
        self.stop = threading.Event()
        self.hist = {}
        self.admitted = []
        self.lock = threading.Lock()

    def run(self):
        prev = {}
        t_prev = time.time()
        while not self.stop.wait(1.0):
            now = time.time()
            dt_ = max(0.3, now - t_prev)
            for vmid in list(self.admitted):
                cur = cgroup_stat(vmid)
                p = prev.get(vmid)
                if p is not None:
                    u = (cur.get("usage_usec", 0) - p.get("usage_usec", 0)) / (dt_ * 1e6)
                    with self.lock:
                        self.hist.setdefault(vmid, []).append((now, max(0.0, u)))
                prev[vmid] = cur
            t_prev = now

    def snapshot(self):
        with self.lock:
            return {v: list(s) for v, s in self.hist.items()}


def recent_busy(sampler, seconds=30.0):
    snap = sampler.snapshot()
    if not snap:
        return 0.0
    t1 = time.time()
    vals = []
    for vmid, s in snap.items():
        recent = [u for (t, u) in s if t >= t1 - seconds]
        if recent:
            vals.append(sum(recent) / len(recent))
    return sum(vals)


def p95(vals):
    if not vals:
        return None
    v = sorted(vals)
    return v[int(round(0.95 * (len(v) - 1)))]


def decide(policy, sampler, admitted, new_count, pool_cores):
    if policy == "worstcase":
        n = len(admitted) + new_count
        return n <= pool_cores, "worstcase n=%d<=%d" % (n, pool_cores)
    if policy == "fixed":
        n = len(admitted) + new_count
        return n <= 2 * pool_cores, "fixed2x n=%d<=%d" % (n, 2 * pool_cores)
    snap = sampler.snapshot()
    if policy == "util80":
        busy = recent_busy(sampler, 30.0)   # cores
        return busy < 0.8 * pool_cores, "util80 busy=%.1f%%" % (busy / pool_cores * 100.0)
    samples = {}
    for vmid in admitted:
        vals = [(t, u) for (t, u) in snap.get(vmid, [])][-120:]
        if len(vals) >= 30:
            samples[vmid] = vals
    class_prior = 0.2
    if samples:
        avg = [statistics.mean(u for _, u in v) for v in samples.values()]
        class_prior = sorted(avg)[len(avg) // 2]
    if policy == "quantile":
        est = 0.0
        for vmid, vals in samples.items():
            est += p95([u for _, u in vals]) or 0.0
        est += new_count * class_prior
        return est <= 0.9 * pool_cores, "quantile est=%.2f<=%.2f prior=%.2f" % (est, 0.9 * pool_cores, class_prior)
    if policy == "audible":
        reps = 400
        series = [[u for _, u in v] for v in samples.values()] or [[class_prior]]
        sums = []
        for _ in range(reps):
            s = sum(random.choice(us) for us in series)
            s += sum(class_prior for _ in range(new_count))
            sums.append(s)
        sums.sort()
        q99 = sums[int(0.99 * (len(sums) - 1))]
        return q99 <= 0.9 * pool_cores, "audible mc_q99=%.2f<=%.2f prior=%.2f" % (q99, 0.9 * pool_cores, class_prior)
    if policy == "ours":
        profiles = []
        for vmid, vals in samples.items():
            prof = [0.0] * 60
            for (t, u) in vals:
                b = int(t) % 60
                if u > prof[b]:
                    prof[b] = u
            profiles.append(prof)
        peak = 0.0
        for phase in range(60):
            s = sum(p[phase] for p in profiles)
            if s > peak:
                peak = s
        pred = peak + new_count * class_prior
        return pred <= 0.9 * pool_cores, "ours peak=%.2f+%.1f<=%.2f" % (peak, new_count * class_prior, 0.9 * pool_cores)
    raise ValueError(policy)


def start_burners(vmids, mode, duty=0.20, period=60.0):
    extra = "--aligned" if mode == "sync" else "--randphase"

    def one(vmid):
        vm_cmd(CUSTOMERS[vmid],
               'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; '
               'rm -f /tmp/burn_rate.txt; '
               'nohup python3 /home/debian/burner.py /tmp/burn_rate.txt 7200 '
               '--duty %.2f --period %d %s >/dev/null 2>&1 < /dev/null & echo on'
               % (duty, period, extra), timeout=30)

    with ThreadPoolExecutor(max_workers=12) as ex:
        list(ex.map(one, vmids))


def kill_burners_all():
    def one(vmid):
        vm_cmd(CUSTOMERS[vmid], 'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; true', timeout=30)

    with ThreadPoolExecutor(max_workers=12) as ex:
        list(ex.map(one, list(CUSTOMERS)))


def read_rates_series(vmids, n=6, gap=3.0):
    """One ssh per VM: sample /tmp/burn_rate.txt n times spaced by gap."""
    cmd = "for i in $(seq 1 %d); do cat /tmp/burn_rate.txt 2>/dev/null; echo @@; sleep %.1f; done" % (n, gap)

    def one(vmid):
        out = vm_cmd(CUSTOMERS[vmid], cmd, timeout=int(n * gap) + 30)
        vals = []
        for chunk in out.split("@@"):
            parts = chunk.split()
            if len(parts) >= 2:
                try:
                    vals.append((float(parts[0]), int(parts[1])))
                except ValueError:
                    pass
        return vmid, vals

    with ThreadPoolExecutor(max_workers=16) as ex:
        return dict(ex.map(one, vmids))


def busy_series(cpus, n=6, gap=3.0):
    out = []
    prev = pool_busy_snapshot(cpus)
    for i in range(n):
        time.sleep(gap)
        cur = pool_busy_snapshot(cpus)
        busy = idle = 0
        for c in cpus:
            if c in prev and c in cur:
                busy += cur[c][0] - prev[c][0]
                idle += cur[c][1] - prev[c][1]
        out.append(round(100.0 * (1.0 - idle / busy), 1) if busy else None)
        prev = cur
    return out


def wait_for_phase(target=2.0, period=60.0):
    """Sleep until epoch % period is just past `target` (burst window start)."""
    now = time.time() % period
    wait = (target - now) % period
    if wait > 0.1:
        time.sleep(wait)


def run_probe(round_name, n, mode, seconds=15.0, rate=100):
    raw = "/home/debian/%s_L%04d_%s.raw" % (round_name, n, mode)
    out = vm_cmd(PROBE_VM,
                 "python3 /home/debian/probe.py --mode %s --host %s --rate %d "
                 "--duration %g --tag %s-L%d-%s --raw %s" %
                 (mode, SVC[mode], rate, seconds, round_name, n, mode, raw),
                 timeout=2 * seconds + 120)
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                pass
    return None


def main():
    global LOGF
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", required=True)
    ap.add_argument("--mode", required=True, choices=["rand", "sync"])
    ap.add_argument("--policy", required=True,
                    choices=["worstcase", "fixed", "util80", "quantile", "audible", "ours", "ours_p"])
    ap.add_argument("--pool", default="8-15")
    ap.add_argument("--step", type=int, default=2)
    ap.add_argument("--max", type=int, default=40)
    ap.add_argument("--settle", type=float, default=25.0)
    ap.add_argument("--probe-seconds", type=float, default=15.0)
    ap.add_argument("--series", type=int, default=6)
    ap.add_argument("--series-gap", type=float, default=3.0)
    ap.add_argument("--order-seed", type=int, default=None,
                    help="shuffle the candidate arrival order deterministically (repeat runs)")
    args = ap.parse_args()

    LOGF = open("/root/tb/admit_%s.log" % args.round, "a", encoding="utf-8")
    log("start round=%s mode=%s policy=%s" % (args.round, args.mode, args.policy))

    pool = parse_cpus(args.pool)
    pool_spec = ",".join(str(c) for c in pool)
    for name, (vmid, cpus) in SERVICE_PIN.items():
        pin(vmid, cpus)
    for vmid in CUSTOMERS:
        pin(vmid, pool_spec)

    sampler = UsageSampler()
    sampler.start()
    vmids_sorted = sorted(CUSTOMERS)
    if args.order_seed is not None:
        import random as _random
        _random.Random(args.order_seed).shuffle(vmids_sorted)
    admitted = []
    sink = open("/root/tb/admit_%s.jsonl" % args.round, "a", encoding="utf-8")
    try:
        kill_burners_all()
        time.sleep(3)
        n = 0
        last_p5 = None
        while n + args.step <= min(args.max, len(vmids_sorted)):
            base_policy = "ours" if args.policy == "ours_p" else args.policy
            try:
                if args.policy == "ours_p" and last_p5 is not None and last_p5 < 70.0:
                    allow, reason = False, "pause p5=%.0f%%<70%%" % last_p5
                else:
                    allow, reason = decide(base_policy, sampler, admitted, args.step, len(pool))
            except Exception:
                log("decide() raised:\n" + traceback.format_exc())
                allow, reason = False, "error:see log"
            log("n=%d -> %s (%s)" % (n + args.step, "allow" if allow else "defer", reason))
            if not allow:
                break
            new = vmids_sorted[n:n + args.step]
            n += args.step
            sampler.admitted = list(admitted + new)
            start_burners(new, args.mode)
            admitted.extend(new)
            time.sleep(args.settle)
            if args.mode == "sync":
                wait_for_phase(2.0)
            # rate series FIRST so burst windows are captured before probes push us out
            rates_series = read_rates_series(admitted, n=args.series, gap=args.series_gap)
            bseries = busy_series(pool, n=args.series, gap=args.series_gap)
            probes = {}
            for svc in ("http", "redis"):
                probes[svc] = run_probe(args.round, n, svc, args.probe_seconds)
            per_vm = {}
            for vmid, samples in rates_series.items():
                rs = [r for r, s in samples if r is not None]
                if rs:
                    per_vm[vmid] = {"max_rate": max(rs),
                                    "max_state": max((s for _, s in samples), default=0)}
            active_max = sorted(v["max_rate"] for v in per_vm.values() if v["max_state"] == 1 and v["max_rate"])
            last_p5 = ((active_max[int(0.05 * (len(active_max) - 1))] / BASE_RATE * 100.0)
                       if active_max else last_p5)
            slow = sum(1 for r in active_max if r < VIOL_FRAC * BASE_RATE)
            http, redis = probes.get("http"), probes.get("redis")
            svc_viol = bool(http and http.get("p99_ms") and http["p99_ms"] > SLO) or \
                       bool(redis and redis.get("p99_ms") and redis["p99_ms"] > SLO)
            rec = {"round": args.round, "mode": args.mode, "policy": args.policy,
                   "n": n, "reason": reason,
                   "busy_samples": bseries,
                   "busy_mean": round(statistics.mean([b for b in bseries if b is not None]), 1)
                                if any(b is not None for b in bseries) else None,
                   "busy_max": max([b for b in bseries if b is not None], default=None),
                   "http_p99": (http or {}).get("p99_ms"),
                   "redis_p99": (redis or {}).get("p99_ms"),
                   "rates": [{"vmid": vmid, "max_rate": v["max_rate"], "state": v["max_state"]}
                             for vmid, v in sorted(per_vm.items())],
                   "rate_series_phase": int(time.time()) % 60,
                   "cust_active": len(active_max), "cust_slow": slow,
                   "svc_viol": svc_viol, "cust_viol": slow > 0,
                   "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
            sink.write(json.dumps(rec) + "\n")
            sink.flush()
            log("   n=%d busy_mean=%s busy_max=%s http=%s redis=%s active=%d slow=%d svc_viol=%s" % (
                n, rec["busy_mean"], rec["busy_max"], rec["http_p99"], rec["redis_p99"],
                len(active_max), slow, svc_viol))
    except Exception:
        log("main loop raised:\n" + traceback.format_exc())
    finally:
        kill_burners_all()
        sampler.stop.set()
        sink.close()
        log("ADMIT %s DONE" % args.round)
        if LOGF:
            LOGF.close()


if __name__ == "__main__":
    raise SystemExit(main())
