#!/usr/bin/env python3
"""Scale sync-burst experiment on the physical host (runs ON the PVE host).

All services, probe, and all 64 customer VMs are pinned into ONE shared pool
(no isolation). All customers run duty-cycle burners with either aligned or
randomized phase. The probe records a long latency window; raw files allow a
per-5s timeline analysis.

Usage:
  python3 tb_sync.py --round qcsync_rand --mode rand    --pool 8-23 --duty 0.20 --duration 150
  python3 tb_sync.py --round qcsync_alig --mode aligned --pool 8-23 --duty 0.20 --duration 150
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time

KEY = "/root/.ssh/tb_key"
PROBE_VM = "10.10.0.20"
SVC = {"http": "10.10.0.11", "redis": "10.10.0.12"}
CUSTOMERS = {vmid: "10.10.0.%d" % (vmid - 290) for vmid in range(311, 375)}
SERVICE_PIN = {"svc-http": (301, "2"), "svc-redis": (302, "3"), "probe": (310, "4")}
SSH = ["-n", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
       "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10",
       "-o", "LogLevel=ERROR"]


def vm_cmd(ip, cmd, timeout=90):
    try:
        res = subprocess.run(["ssh"] + SSH + ["debian@" + ip, cmd],
                             capture_output=True, text=True, timeout=timeout)
        return res.stdout
    except subprocess.TimeoutExpired:
        return ""


def parse_cpus(spec):
    cpus = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            cpus.extend(range(int(a), int(b) + 1))
        else:
            cpus.append(int(part))
    return cpus


def pin(vmid, cpu_spec):
    subprocess.run(
        'pid=$(cat /run/qemu-server/%d.pid 2>/dev/null) && [ -n "$pid" ] && '
        'taskset -apc %s $pid >/dev/null 2>&1; true' % (vmid, cpu_spec),
        shell=True, capture_output=True, timeout=15)


def cpu_busy(cpus, secs=3.0):
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


def start_all(mode, duty, period, run_seconds):
    extra = "--aligned" if mode == "aligned" else "--randphase"
    for vmid, ip in sorted(CUSTOMERS.items()):
        vm_cmd(ip, 'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; '
                   'rm -f /tmp/burn_rate.txt; '
                   'nohup python3 /home/debian/burner.py /tmp/burn_rate.txt %d '
                   '--duty %.2f --period %d %s >/dev/null 2>&1 < /dev/null & echo on'
                   % (run_seconds, duty, period, extra), timeout=30)


def stop_all():
    for vmid, ip in sorted(CUSTOMERS.items()):
        vm_cmd(ip, 'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; true', timeout=30)


def run_probe(round_name, mode, seconds, rate=100):
    raw = "/home/debian/%s_%s.raw" % (round_name, mode)
    out = vm_cmd(PROBE_VM,
                 "python3 /home/debian/probe.py --mode %s --host %s --rate %d "
                 "--duration %d --tag %s-%s --raw %s" %
                 (mode, SVC[mode], rate, seconds, round_name, mode, raw),
                 timeout=2 * seconds + 150)
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
    ap.add_argument("--mode", required=True, choices=["rand", "aligned"])
    ap.add_argument("--pool", required=True)
    ap.add_argument("--duty", type=float, default=0.20)
    ap.add_argument("--period", type=float, default=60.0)
    ap.add_argument("--duration", type=float, default=150.0)
    ap.add_argument("--settle", type=float, default=10.0)
    args = ap.parse_args()

    pool = parse_cpus(args.pool)
    pool_spec = ",".join(str(c) for c in pool)

    # no isolation: everything into the shared pool
    for name, (vmid, _) in SERVICE_PIN.items():
        pin(vmid, pool_spec)
    for vmid in CUSTOMERS:
        pin(vmid, pool_spec)

    sink = open("/root/tb/sync_%s.jsonl" % args.round, "a", encoding="utf-8")
    try:
        start_all(args.mode, args.duty, args.period, int(args.duration + 120))
        time.sleep(args.settle)
        busy = cpu_busy(pool)
        http = run_probe(args.round, "http", args.duration)
        redis = run_probe(args.round, "redis", args.duration)
        rec = {"round": args.round, "mode": args.mode, "pool": args.pool,
               "duty": args.duty, "period": args.period, "duration": args.duration,
               "busy_pct": busy, "http": http, "redis": redis}
        sink.write(json.dumps(rec) + "\n")
        sink.flush()
        print("SYNC %s (%s): busy=%s http_p99=%s redis_p99=%s" %
              (args.round, args.mode, busy,
               (http or {}).get("p99_ms"), (redis or {}).get("p99_ms")), flush=True)
    finally:
        stop_all()
        sink.close()
        print("SYNC %s DONE" % args.round, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
