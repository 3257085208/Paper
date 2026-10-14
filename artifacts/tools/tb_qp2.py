#!/usr/bin/env python3
"""CPU micro-period quota sweep (host-side, runs on the PVE host).

Five pegged tenants (pool cores), each quota = 50% at periods
1000/5000/10000/100000/1000000 us, plus an uncapped baseline. Measures
service probe P99 and tenant burner rates per configuration.

Usage: python3 tb_qp2.py --round qp2
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
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
PERIODS = [0, 2000, 4000, 10000, 100000, 1000000]  # quota>=1ms => 50% needs period>=2ms


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


def set_quota(vmid, quota_us, period_us):
    val = "max 100000" if quota_us == 0 else "%d %d" % (quota_us, period_us)
    path = "/sys/fs/cgroup/qemu.slice/%d.scope/cpu.max" % vmid
    if os.path.exists(path):
        with open(path, "w") as fh:
            fh.write(val + "\n")
    return val


def throttled_usec(vmid):
    try:
        for line in open("/sys/fs/cgroup/qemu.slice/%d.scope/cpu.stat" % vmid):
            if line.startswith("throttled_usec"):
                return int(line.split()[1])
    except OSError:
        pass
    return 0


def cpu_busy(cpus, secs=2.0):
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


def start_burners(vmids):
    def one(vmid):
        vm_cmd(CUSTOMERS[vmid],
               'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; '
               'rm -f /tmp/burn_rate.txt; '
               'nohup python3 /home/debian/burner.py /tmp/burn_rate.txt 3600 '
               '--duty 1.0 --period 60 --randphase >/dev/null 2>&1 < /dev/null & echo on',
               timeout=30)

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(one, vmids))


def kill_burners(vmids):
    def one(vmid):
        vm_cmd(CUSTOMERS[vmid], 'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; true', timeout=30)

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(one, vmids))


def read_rates(vmids):
    def one(vmid):
        out = vm_cmd(CUSTOMERS[vmid], "cat /tmp/burn_rate.txt 2>/dev/null", timeout=20)
        try:
            parts = out.strip().split()
            return vmid, float(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            return vmid, None, None

    with ThreadPoolExecutor(max_workers=8) as ex:
        return list(ex.map(one, vmids))


def probe(round_name, tag, seconds=15, rate=100):
    out = vm_cmd(PROBE_VM,
                 "python3 /home/debian/probe.py --mode http --host %s --rate %d "
                 "--duration %d --tag %s-%s --raw /home/debian/%s_%s.raw" %
                 (SVC["http"], rate, seconds, round_name, tag, round_name, tag),
                 timeout=2 * seconds + 90)
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
    ap.add_argument("--round", default="qp2")
    ap.add_argument("--pool", default="8-15")
    ap.add_argument("--tenants", type=int, default=5)
    ap.add_argument("--settle", type=float, default=15.0)
    args = ap.parse_args()

    pool = parse_cpus(args.pool)
    pool_spec = ",".join(str(c) for c in pool)
    for name, (vmid, cpus) in SERVICE_PIN.items():
        pin(vmid, cpus)
    for vmid in CUSTOMERS:
        pin(vmid, pool_spec)

    vmids = sorted(CUSTOMERS)[:args.tenants]
    sink = open("/root/tb/qp2_%s.jsonl" % args.round, "a", encoding="utf-8")
    try:
        kill_burners(list(CUSTOMERS))
        time.sleep(3)
        start_burners(vmids)
        time.sleep(20)
        for period_us in PERIODS:
            quota = 0 if period_us == 0 else period_us // 2
            for vmid in vmids:
                set_quota(vmid, quota, max(period_us, 1000))
            time.sleep(args.settle)
            thr0 = {v: throttled_usec(v) for v in vmids}
            http = probe(args.round, "p%d" % period_us if period_us else "base")
            busy = cpu_busy(pool, 2.0)
            rates = read_rates(vmids)
            thr1 = {v: throttled_usec(v) for v in vmids}
            active = [(v, r) for v, r, s in rates if r and s == 1]
            thr_total = sum(thr1[v] - thr0[v] for v in vmids)
            rec = {"round": args.round, "period_us": period_us, "quota_us": quota,
                   "tenants": len(vmids), "busy_pct": busy,
                   "http": http,
                   "rates": [{"vmid": v, "rate": r} for v, r in active],
                   "throttled_usec_delta": thr_total,
                   "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
            sink.write(json.dumps(rec) + "\n")
            sink.flush()
            print("QP2 period=%7d us: http_p99=%s busy=%s thr_delta=%dus rates_med=%s" %
                  (period_us, (http or {}).get("p99_ms"), busy, thr_total,
                   sorted(round(r / 1e6, 1) for _, r in active)), flush=True)
        for vmid in vmids:
            set_quota(vmid, 0, 100000)
    finally:
        kill_burners(list(CUSTOMERS))
        sink.close()
        print("QP2 %s DONE" % args.round, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
