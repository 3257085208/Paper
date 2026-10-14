#!/usr/bin/env python3
"""Throttle tomography: multi-resolution throttle sequences across censoring shapes.

Six tenants on the pool, each `cpu.max = 30%`, one per demand shape:
  S1 const 1.0 | S2 duty .5/60 | S3 duty .1/60 | S4 jit {0.1,1.0}/60
  S5 duty .2/10 (fast cycle) | S6 duty .2/60
Per-second per-VM (usage, throttled) read from the host cgroup for 600 s.
Estimators compared against known truths:
  naive     mean usage
  scale     usage / 0.30          (quota-aware scaling)
  formula   u / (1 - t)           (window aggregate)
  tomo      multi-resolution taxonomy: sustained (>80% seconds throttled) ->
            formula; bursty (5-80%) -> min(vCPU, formula); rare (<5%) -> naive

Writes /root/tb/tomo_<round>.jsonl + prints an error table.
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
CUSTOMERS = {vmid: "10.10.0.%d" % (vmid - 290) for vmid in range(311, 375)}
SSH = ["-n", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
       "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=8",
       "-o", "LogLevel=ERROR"]
SHAPES = [
    (311, "S1_const", "--duty 1.0", 1.00),
    (312, "S2_d50", "--duty 0.5 --period 60 --randphase", 0.50),
    (313, "S3_d10", "--duty 0.1 --period 60 --randphase", 0.10),
    (314, "S4_jit", "--jit 0.1,1.0 --period 60 --randphase", 0.55),
    (315, "S5_d20p10", "--duty 0.2 --period 10 --randphase", 0.20),
    (316, "S6_d20", "--duty 0.2 --period 60 --randphase", 0.20),
]
VMIDS = [v for v, _, _, _ in SHAPES]


def vm_cmd(ip, cmd, timeout=60):
    try:
        res = subprocess.run(["ssh"] + SSH + ["debian@" + ip, cmd],
                             capture_output=True, text=True, timeout=timeout)
        return res.stdout
    except subprocess.TimeoutExpired:
        return ""


def pin(vmid, spec):
    subprocess.run(
        'pid=$(cat /run/qemu-server/%d.pid 2>/dev/null) && [ -n "$pid" ] && '
        'taskset -apc %s $pid >/dev/null 2>&1; true' % (vmid, spec),
        shell=True, capture_output=True, timeout=15)


def set_quota(vmid, quota_us=30000, period_us=100000):
    with open("/sys/fs/cgroup/qemu.slice/%d.scope/cpu.max" % vmid, "w") as fh:
        fh.write("%d %d\n" % (quota_us, period_us))


def clear_quota(vmid):
    with open("/sys/fs/cgroup/qemu.slice/%d.scope/cpu.max" % vmid, "w") as fh:
        fh.write("max 100000\n")


def stat(vmid):
    d = {}
    try:
        for line in open("/sys/fs/cgroup/qemu.slice/%d.scope/cpu.stat" % vmid):
            k, v = line.split()
            d[k] = int(v)
    except OSError:
        pass
    return d


def start_all():
    for vmid, _, args, _ in SHAPES:
        vm_cmd(CUSTOMERS[vmid],
               'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; rm -f /tmp/burn_rate.txt; '
               'nohup python3 /home/debian/burner.py /tmp/burn_rate.txt 3600 %s '
               '>/dev/null 2>&1 < /dev/null & echo on' % args, timeout=30)


def kill_all():
    for vmid in VMIDS:
        vm_cmd(CUSTOMERS[vmid], 'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; true', timeout=30)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", default="tomo1")
    ap.add_argument("--pool", default="8-15")
    ap.add_argument("--seconds", type=int, default=600)
    args = ap.parse_args()
    pool = list(range(int(args.pool.split("-")[0]), int(args.pool.split("-")[1]) + 1))
    spec = ",".join(str(c) for c in pool)
    for v in VMIDS:
        pin(v, spec)

    sink = open("/root/tb/tomo_%s.jsonl" % args.round, "a", encoding="utf-8")
    try:
        kill_all()
        time.sleep(3)
        for v in VMIDS:
            set_quota(v)
        start_all()
        time.sleep(30)
        prev = {v: stat(v) for v in VMIDS}
        t_prev = time.time()
        per = {v: [] for v in VMIDS}
        for _ in range(args.seconds):
            time.sleep(1.0)
            now = time.time()
            dtn = max(0.5, now - t_prev)
            for v in VMIDS:
                cur = stat(v)
                du = (cur.get("usage_usec", 0) - prev[v].get("usage_usec", 0)) / (dtn * 1e6)
                dthr = (cur.get("throttled_usec", 0) - prev[v].get("throttled_usec", 0)) / (dtn * 1e6)
                per[v].append((max(0.0, du), max(0.0, min(1.0, dthr))))
                prev[v] = cur
            t_prev = now

        summary = []
        for vmid, name, _, truth in SHAPES:
            u = statistics.mean(x for x, _ in per[vmid])
            t = statistics.mean(y for _, y in per[vmid])
            thr_seconds = sum(1 for _, y in per[vmid] if y > 0.01) / len(per[vmid])
            naive = u
            scale = u / 0.30
            formula = min(1.0, u / (1 - t)) if t < 0.999 else 1.0
            noclamp = u / (1 - t) if t < 0.999 else u
            clamp = 1.0 if thr_seconds > 0.05 else u
            if thr_seconds > 0.8:
                tomo = formula
                cls = "sustained"
            elif thr_seconds >= 0.05:
                tomo = min(1.0, formula)
                cls = "bursty"
            else:
                tomo = naive
                cls = "rare"
            rec = {"round": args.round, "vmid": vmid, "shape": name, "truth": truth,
                   "usage": round(u, 3), "t": round(t, 3), "throttled_seconds_frac": round(thr_seconds, 3),
                   "class": cls, "naive": round(naive, 3), "scale": round(scale, 3),
                   "formula": round(formula, 3), "noclamp": round(noclamp, 3),
                   "clamp": round(clamp, 3), "tomo": round(tomo, 3)}
            summary.append(rec)
            sink.write(json.dumps(rec) + "\n")
        sink.flush()
        print("%-10s truth  naive  scale  form.  noclmp clamp  tomo  (cls, thr_sec%%)" % "shape")
        errs = {"naive": [], "scale": [], "formula": [], "noclamp": [], "clamp": [], "tomo": []}
        for r in summary:
            print("%-10s %5.2f  %5.2f  %5.2f  %5.2f  %5.2f  %5.2f  %5.2f  (%s, %.0f%%)" % (
                r["shape"], r["truth"], r["naive"], r["scale"], r["formula"], r["noclamp"],
                r["clamp"], r["tomo"], r["class"], 100 * r["throttled_seconds_frac"]))
            for k in errs:
                errs[k].append(abs(r[k] - r["truth"]))
        print("MAE:", {k: round(statistics.mean(v), 3) for k, v in errs.items()})
    finally:
        for v in VMIDS:
            clear_quota(v)
        kill_all()
        sink.close()
        print("TOMO %s DONE" % args.round, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
