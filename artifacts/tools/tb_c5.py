#!/usr/bin/env python3
"""C5: phase arrangement as a capacity lever (host-side, runs on the PVE host).

Same tenants, same duty (20% / 60 s), only the *arrangement* of aligned burst
windows differs. Configs (groups = (count, phase offset seconds)):
  c5_same_16    [(16, 0)]                expected ~50% (anchor: sell_sync L16)
  c5_anti2_16   [(8, 0), (8, 30)]        expected ~100%  -> 2x vs same-phase
  c5_anti4_32   [(8,0),(8,15),(8,30),(8,45)]  expected ~100% -> 4x
  c5_anti2_32   [(16, 0), (16, 30)]      expected ~50%
  c5_anti4_64   [(16,0),(16,15),(16,30),(16,45)] expected ~50%

Per config: deploy burner.py (with --phase-offset) to guests if needed, start
burners, sample the per-VM rate series (single ssh per VM, timestamped), the
pool busy series, and a service probe. Writes /root/tb/c5_<name>.jsonl.

Usage: python3 tb_c5.py --only c5_anti2_16   (or --all)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
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
BASE_RATE = 25.9e6

CONFIGS = [
    ("c5_same_16", [(16, 0.0)]),
    ("c5_anti2_16", [(8, 0.0), (8, 30.0)]),
    ("c5_anti4_32", [(8, 0.0), (8, 15.0), (8, 30.0), (8, 45.0)]),
    ("c5_anti2_32", [(16, 0.0), (16, 30.0)]),
    ("c5_anti4_64", [(16, 0.0), (16, 15.0), (16, 30.0), (16, 45.0)]),
]


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


def deploy_burner():
    src = "/root/tb/burner.py"

    def one(vmid):
        subprocess.run(["scp", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                        "-o", "LogLevel=ERROR", src,
                        "debian@%s:/home/debian/burner.py" % CUSTOMERS[vmid]],
                       capture_output=True)
        return vmid

    with ThreadPoolExecutor(max_workers=16) as ex:
        list(ex.map(one, list(CUSTOMERS)))


def kill_burners_all():
    def one(vmid):
        vm_cmd(CUSTOMERS[vmid], 'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; true', timeout=30)

    with ThreadPoolExecutor(max_workers=12) as ex:
        list(ex.map(one, list(CUSTOMERS)))


def start_group(vmids, offset, duty=0.20, period=60.0):
    def one(vmid):
        vm_cmd(CUSTOMERS[vmid],
               'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; rm -f /tmp/burn_rate.txt; '
               'nohup python3 /home/debian/burner.py /tmp/burn_rate.txt 7200 '
               '--duty %.2f --period %d --aligned --phase-offset %.1f '
               '>/dev/null 2>&1 < /dev/null & echo on' % (duty, period, offset), timeout=30)

    with ThreadPoolExecutor(max_workers=12) as ex:
        list(ex.map(one, vmids))


def rate_series(vmids, n=25, gap=3.6):
    cmd = ("for i in $(seq 1 %d); do date +%%s.%%N; cat /tmp/burn_rate.txt 2>/dev/null; "
           "echo @@; sleep %.2f; done" % (n, gap))

    def one(vmid):
        out = vm_cmd(CUSTOMERS[vmid], cmd, timeout=int(n * gap) + 40)
        samples = []
        ts = None
        for chunk in out.split("@@"):
            lines = [x for x in chunk.strip().splitlines() if x.strip()]
            if len(lines) >= 2:
                try:
                    ts = float(lines[0])
                    r, s = lines[1].split()
                    samples.append([ts, float(r), int(s)])
                except (ValueError, IndexError):
                    pass
        return vmid, samples

    with ThreadPoolExecutor(max_workers=16) as ex:
        return dict(ex.map(one, vmids))


def busy_series(cpus, seconds=90, step=2.0):
    out = []
    prev = pool_busy_snapshot(cpus)
    t_end = time.time() + seconds
    while time.time() < t_end:
        time.sleep(step)
        cur = pool_busy_snapshot(cpus)
        busy = idle = 0
        for c in cpus:
            if c in prev and c in cur:
                busy += cur[c][0] - prev[c][0]
                idle += cur[c][1] - prev[c][1]
        out.append({"t": round(time.time(), 3),
                    "busy": round(100.0 * (1.0 - idle / busy), 1) if busy else None})
        prev = cur
    return out


def run_probe(round_name, n, seconds=20, rate=100):
    raw = "/home/debian/%s_http.raw" % round_name
    out = vm_cmd(PROBE_VM,
                 "python3 /home/debian/probe.py --mode http --host %s --rate %d "
                 "--duration %d --tag %s --raw %s" % (SVC["http"], rate, seconds, round_name, raw),
                 timeout=2 * seconds + 120)
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                pass
    return None


def run_config(name, groups, pool):
    pool_spec = ",".join(str(c) for c in pool)
    for _, (vmid, cpus) in SERVICE_PIN.items():
        pin(vmid, cpus)
    vmids = sorted(CUSTOMERS)
    assigned = []
    idx = 0
    for cnt, off in groups:
        assigned.append((vmids[idx:idx + cnt], off))
        idx += cnt
    total = idx
    for vmid in vmids[:total]:
        pin(vmid, pool_spec)

    kill_burners_all()
    time.sleep(3)
    for group_vmids, off in assigned:
        start_group(group_vmids, off)
    time.sleep(35)  # let the pattern settle (>= half a cycle)

    # sample a full 90 s cycle of rates (timestamped) and busy
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_busy = ex.submit(busy_series, pool, 90, 2.0)
        f_rates = ex.submit(rate_series, vmids[:total], 25, 3.6)
        busy = f_busy.result()
        rates = f_rates.result()
    http = run_probe(name, total, seconds=20)

    # per-VM: max rate and the window phase (host clock) where it was active
    per_vm = {}
    for vmid, samples in rates.items():
        best = 0.0
        best_t = None
        for ts, r, s in samples:
            if r > best:
                best, best_t = r, ts
        active_phases = [ts % 60 for ts, r, s in samples if s == 1 and r > 0]
        per_vm[vmid] = {"max_rate": best,
                        "max_rate_phase": round(best_t % 60, 1) if best_t else None,
                        "active_phases": [round(p, 1) for p in active_phases]}
    vals = sorted(v["max_rate"] / BASE_RATE * 100 for v in per_vm.values() if v["max_rate"])
    p50 = statistics.median(vals) if vals else None
    p5 = vals[int(0.05 * (len(vals) - 1))] if vals else None
    # group window check: fraction of VMs whose active phase falls near the target
    group_ok = {}
    for gi, (group_vmids, off) in enumerate(assigned):
        near = 0
        for vmid in group_vmids:
            phases = per_vm[vmid]["active_phases"]
            if phases and any(min(abs((p - off) % 60), 60 - abs((p - off) % 60)) <= 4.0 for p in phases):
                near += 1
        group_ok["g%d_off%.0f" % (gi, off)] = "%d/%d" % (near, len(group_vmids))

    rec = {"round": name, "groups": [{"count": c, "offset": o} for c, o in groups],
           "total": total, "p50_pct": p50, "p5_pct": p5,
           "busy": busy, "per_vm": per_vm, "group_window_ok": group_ok,
           "http_p99": (http or {}).get("p99_ms"),
           "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    with open("/root/tb/c5_%s.jsonl" % name, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    print("C5 %-14s total=%2d p50=%s%% p5=%s%% http=%s win=%s" % (
        name, total, "%.0f" % p50 if p50 else "-", "%.0f" % p5 if p5 else "-",
        (http or {}).get("p99_ms"), group_ok), flush=True)
    kill_burners_all()
    time.sleep(3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default="8-15")
    ap.add_argument("--only", default=None)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    deploy_burner()
    pool = parse_cpus(args.pool)
    todo = CONFIGS if args.all or not args.only else [(n, g) for n, g in CONFIGS if n == args.only]
    for name, groups in todo:
        run_config(name, groups, pool)
    print("C5 DONE", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
