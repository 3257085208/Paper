#!/usr/bin/env python3
"""Mixed-phase capacity ladder (runs ON the PVE host).

Validates the capacity law  N_safe(phi) = C / (phi + (1-phi) * duty)
on an 8-core pool (cores 8-15): a fraction phi of the admitted 1-vCPU
tenants is phase-aligned (wall-clock 60 s period), the rest random.
For each level we collect pool busy, per-tenant burner rates, and service
probe windows, exactly like tb_sell.py (same settle/collect parameters).

Usage:
  python3 tb_capmix.py --round capmix_f50 --align-frac 0.50 --levels "10 13 16 20"
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

KEY = "/root/.ssh/tb_key"
PROBE_VM = "10.10.0.20"
SVC = {"http": "10.10.0.11", "redis": "10.10.0.12"}
CUSTOMERS = {vmid: "10.10.0.%d" % (vmid - 290) for vmid in range(311, 375)}
SERVICE_PIN = {"svc-http": (301, "2"), "svc-redis": (302, "3"), "probe": (310, "4")}
SSH = ["-n", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
       "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=8",
       "-o", "LogLevel=ERROR"]


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
    cpus = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            cpus.extend(range(int(a), int(b) + 1))
        else:
            cpus.append(int(part))
    return cpus


def cpu_busy(cpus, secs=1.0):
    def snap():
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

    a = snap()
    time.sleep(secs)
    b = snap()
    busy = idle = 0
    for c in cpus:
        if c in a and c in b:
            busy += b[c][0] - a[c][0]
            idle += b[c][1] - a[c][1]
    return round(100.0 * (1.0 - idle / busy), 1) if busy else None


def start_burners(vmids_aligned, vmids_random, duty, period):
    def one(vmid, aligned):
        extra = "--aligned" if aligned else "--randphase"
        vm_cmd(CUSTOMERS[vmid],
               'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; '
               'rm -f /tmp/burn_rate.txt; '
               'nohup python3 /home/debian/burner.py /tmp/burn_rate.txt 7200 '
               '--duty %.2f --period %d %s >/dev/null 2>&1 < /dev/null & echo on'
               % (duty, period, extra), timeout=30)

    jobs = [(v, True) for v in vmids_aligned] + [(v, False) for v in vmids_random]
    with ThreadPoolExecutor(max_workers=12) as ex:
        list(ex.map(lambda vt: one(*vt), jobs))


def kill_burners_all():
    def one(vmid):
        vm_cmd(CUSTOMERS[vmid], 'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; true', timeout=30)

    with ThreadPoolExecutor(max_workers=12) as ex:
        list(ex.map(one, list(CUSTOMERS)))


def read_rates(vmids):
    def one(vmid):
        out = vm_cmd(CUSTOMERS[vmid], "cat /tmp/burn_rate.txt 2>/dev/null", timeout=20)
        try:
            parts = out.strip().split()
            return vmid, float(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            return vmid, None, None

    with ThreadPoolExecutor(max_workers=16) as ex:
        return list(ex.map(one, vmids))


def run_probe(round_name, level, mode, seconds=10, rate=100):
    raw = "/home/debian/%s_L%03d_%s.raw" % (round_name, level, mode)
    out = vm_cmd(PROBE_VM,
                 "python3 /home/debian/probe.py --mode %s --host %s --rate %d "
                 "--duration %d --tag %s-L%d-%s --raw %s" %
                 (mode, SVC[mode], rate, seconds, round_name, level, mode, raw),
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", required=True)
    ap.add_argument("--align-frac", type=float, required=True)
    ap.add_argument("--pool", default="8-15")
    ap.add_argument("--levels", required=True)
    ap.add_argument("--duty", type=float, default=0.20)
    ap.add_argument("--period", type=float, default=60.0)
    ap.add_argument("--settle", type=float, default=40.0)
    ap.add_argument("--collect", type=float, default=60.0)
    args = ap.parse_args()
    phi = args.align_frac

    pool = parse_cpus(args.pool)
    pool_spec = ",".join(str(c) for c in pool)
    for name, (vmid, cpus) in SERVICE_PIN.items():
        pin(vmid, cpus)
    for vmid in CUSTOMERS:
        pin(vmid, pool_spec)

    levels = [int(x) for x in args.levels.split()]
    vmids_sorted = sorted(CUSTOMERS)
    started = []
    aligned_started = []
    sink = open("/root/tb/sell_%s.jsonl" % args.round, "a", encoding="utf-8")
    try:
        kill_burners_all()
        time.sleep(3)
        for n in levels:
            if n < len(started):
                extra = started[n:]

                def _off(vmid):
                    vm_cmd(CUSTOMERS[vmid],
                           'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; true',
                           timeout=30)

                with ThreadPoolExecutor(max_workers=8) as ex:
                    list(ex.map(_off, extra))
                started = started[:n]
                aligned_started = [v for v in aligned_started if v in started]
            new = [v for v in vmids_sorted if v not in started][:max(0, n - len(started))]
            new_aligned, new_random = [], []
            if new:
                need = max(0, round(phi * n) - len(aligned_started))
                new_aligned = new[:need]
                new_random = new[need:]
                start_burners(new_aligned, new_random, args.duty, args.period)
                started.extend(new)
                aligned_started.extend(new_aligned)
            time.sleep(args.settle)
            busy_samples = []
            rate_rounds = []
            t0 = time.time()
            n_rounds = max(1, int(args.collect / 10.0))
            for i in range(n_rounds):
                busy_samples.append(cpu_busy(pool, 2.0))
                rate_rounds.append(read_rates(started))
                time.sleep(max(0.0, 10.0 - 2.0 - 3.0))
            t1 = time.time()
            http = run_probe(args.round, n, "http")
            redis = run_probe(args.round, n, "redis")
            rec = {"round": args.round, "mode": "mix", "align_frac": phi,
                   "level": n, "duty": args.duty, "period": args.period,
                   "pool": args.pool,
                   "aligned_vmids": sorted(aligned_started),
                   "collect_s": round(t1 - t0, 1),
                   "busy_samples": busy_samples,
                   "rate_rounds": [[list(x) for x in rnd] for rnd in rate_rounds],
                   "http": http, "redis": redis,
                   "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
            sink.write(json.dumps(rec) + "\n")
            sink.flush()
            print("CAPMIX %s phi=%.2f level=%d: busy_mean=%.1f%% http_p99=%s redis_p99=%s" %
                  (args.round, phi, n, sum(busy_samples) / len(busy_samples),
                   (http or {}).get("p99_ms"), (redis or {}).get("p99_ms")), flush=True)
    finally:
        kill_burners_all()
        sink.close()
        print("CAPMIX %s DONE" % args.round, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
