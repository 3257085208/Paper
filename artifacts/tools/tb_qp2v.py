#!/usr/bin/env python3
"""qp2 verification (P0): delivered CPU (guest cpu.stat) vs the burner rate
metric, per quota config, with fresh burner windows per config.

For each config: set quota -> restart burners (fresh cumulative rate window)
-> settle -> measure 60 s: guest usage_usec / throttled_usec deltas (delivered
cores), burner rate at window end, host busy.

Usage: python3 tb_qp2v.py --round qp2v1
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time

KEY = "/root/.ssh/tb_key"
SSH = ["-n", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
       "-o", "ConnectTimeout=10", "-o", "LogLevel=ERROR"]
CUSTOMERS = {v: "10.10.0.%d" % (v - 290) for v in range(311, 316)}
POOL = list(range(8, 16))
WIN = 60.0


def vm_cmd(ip, cmd, timeout=60):
    try:
        return subprocess.run(["ssh"] + SSH + ["debian@" + ip, cmd],
                              capture_output=True, text=True, timeout=timeout).stdout
    except subprocess.TimeoutExpired:
        return ""


def set_quota(vmid, q, p):
    val = "max 100000" if q == 0 else "%d %d" % (q, p)
    subprocess.run('echo "%s" > /sys/fs/cgroup/qemu.slice/%d.scope/cpu.max' % (val, vmid),
                   shell=True, capture_output=True)


def cpu_stat(vmid):
    d = {}
    for line in open("/sys/fs/cgroup/qemu.slice/%d.scope/cpu.stat" % vmid):
        k, v = line.split()
        d[k] = int(v)
    return d


def busy_snap():
    tot = {}
    with open("/proc/stat") as fh:
        for line in fh:
            if not line.startswith("cpu") or line.startswith("cpu "):
                continue
            parts = line.split()
            if not parts[0][3:].isdigit():
                break
            c = int(parts[0][3:])
            if c in POOL:
                v = [int(x) for x in parts[1:11]]
                tot[c] = (sum(v), v[3] + v[4])
    return tot


def busy_delta(a, b):
    busy = idle = 0
    for c in a:
        busy += b[c][0] - a[c][0]
        idle += b[c][1] - a[c][1]
    return round(100.0 * (1.0 - idle / busy), 1) if busy else None


def start_burners(vmids):
    for v in vmids:
        vm_cmd(CUSTOMERS[v],
               'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; '
               'rm -f /tmp/burn_rate.txt; '
               'nohup python3 /home/debian/burner.py /tmp/burn_rate.txt 3600 '
               '--duty 1.0 >/dev/null 2>&1 < /dev/null & echo on', timeout=30)


def read_rate(vmid):
    out = vm_cmd(CUSTOMERS[vmid], "cat /tmp/burn_rate.txt")
    try:
        return float(out.split()[0])
    except (ValueError, IndexError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", default="qp2v1")
    args = ap.parse_args()
    vmids = sorted(CUSTOMERS)
    configs = [(0, 0, "uncapped"), (1000, 2000, "2ms"), (500000, 1000000, "1s")]
    sink = open("/root/tb/qp2v_%s.jsonl" % args.round, "a", encoding="utf-8")
    for q, p, tag in configs:
        for v in vmids:
            set_quota(v, q, p)
        start_burners(vmids)
        time.sleep(8)
        a = {v: cpu_stat(v) for v in vmids}
        b0 = busy_snap()
        t0 = time.time()
        time.sleep(WIN)
        dt = time.time() - t0
        b1 = busy_snap()
        b = {v: cpu_stat(v) for v in vmids}
        rows = []
        for v in vmids:
            usage = (b[v]["usage_usec"] - a[v]["usage_usec"]) / (dt * 1e6)
            thr = (b[v].get("throttled_usec", 0) - a[v].get("throttled_usec", 0)) / (dt * 1e6)
            rate = read_rate(v)
            rows.append({"vmid": v, "delivered_cores": round(usage, 3),
                         "throttled_frac": round(thr, 3), "rate_M": round(rate / 1e6, 2) if rate else None,
                         "rate_per_core_M": round(rate / 1e6 / usage, 2) if rate and usage > 0.01 else None})
        rec = {"round": args.round, "config": tag, "quota": "%d/%d" % (q, p),
               "win_s": round(dt, 1), "host_busy_pct": busy_delta(b0, b1), "rows": rows}
        sink.write(json.dumps(rec) + "\n")
        sink.flush()
        print("== %s (%s) ==" % (tag, rec["quota"]))
        for r in rows:
            print("  vm%d delivered=%.3f cores thr=%.2f rate=%sM rate/core=%sM" % (
                r["vmid"], r["delivered_cores"], r["throttled_frac"], r["rate_M"], r["rate_per_core_M"]))
    for v in vmids:
        set_quota(v, 0, 0)
    print("QP2V %s DONE" % args.round, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
