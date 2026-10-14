#!/usr/bin/env python3
"""Quick knee sweep for the physical test host (runs ON the PVE host).

Pins services/probe to dedicated cores, pins customer VMs to a tenant pool,
then sweeps the number of pegged (100%) customers and records service latency
from the probe VM.

Customer VMIDs 311-326 map to 10.10.0.21-36. Probe VM: 310 (10.10.0.20).

Usage:
  python3 sweep.py --round qa4 --pool 8,9,10,11 --levels 0 1 2 3 4 5 6 7 8
  python3 sweep.py --round qa8 --pool 8-15 --levels 0 2 4 6 8 10 12 16
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
                if not line.startswith("cpu"):
                    break
                parts = line.split()
                if parts[0] == "cpu" or not parts[0][3:].isdigit():
                    continue
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


def set_burners(count):
    for idx, (vmid, ip) in enumerate(sorted(CUSTOMERS.items()), 1):
        if idx <= count:
            vm_cmd(ip, 'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; '
                       'rm -f /tmp/burn_rate.txt; '
                       'nohup python3 /home/debian/burner.py /tmp/burn_rate.txt 3600 >/dev/null 2>&1 < /dev/null & echo on',
                   timeout=30)
        else:
            vm_cmd(ip, 'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; true', timeout=30)


def run_probe(round_name, level, mode, seconds=20, rate=100):
    raw = "/home/debian/%s_L%02d_%s.raw" % (round_name, level, mode)
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
    ap.add_argument("--pool", required=True, help="tenant CPU pool, e.g. 8,9,10,11 or 8-15")
    ap.add_argument("--levels", default="0 1 2 3 4 5 6 7 8")
    ap.add_argument("--probe-seconds", type=float, default=20.0)
    ap.add_argument("--confine", action="store_true",
                    help="pin services+probe into the same pool (no isolation)")
    args = ap.parse_args()

    pool = parse_cpus(args.pool)
    levels = [int(x) for x in args.levels.split()]

    # pin services and probe
    pool_spec = ",".join(str(c) for c in pool)
    for name, (vmid, cpus) in SERVICE_PIN.items():
        pin(vmid, pool_spec if args.confine else cpus)
    # pin all customers to the tenant pool
    for vmid in CUSTOMERS:
        pin(vmid, ",".join(str(c) for c in pool))

    sink = open("/root/tb/sweep_%s.jsonl" % args.round, "a", encoding="utf-8")
    try:
        for level in levels:
            set_burners(level)
            time.sleep(10)
            busy = cpu_busy(pool)
            http = run_probe(args.round, level, "http", args.probe_seconds)
            redis = run_probe(args.round, level, "redis", args.probe_seconds)
            rec = {"round": args.round, "pool": args.pool, "level": level, "busy_pct": busy,
                   "http": http, "redis": redis}
            sink.write(json.dumps(rec) + "\n")
            sink.flush()
            print("L%02d busy=%s http_p99=%s redis_p99=%s" %
                  (level, busy, (http or {}).get("p99_ms"), (redis or {}).get("p99_ms")),
                  flush=True)
    finally:
        set_burners(0)
        sink.close()
        print("SWEEP %s DONE" % args.round, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
