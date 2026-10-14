#!/usr/bin/env python3
"""Mixed-occupancy censoring experiment (host-side, runs on the PVE host).

Six tenants on the pool, each `cpu.max = 30%`, mixed occupancy:
3 pegged (true demand 1.0) + 3 idle-class (duty 10%/60 s, true mean 0.10).
Per 60 s cycle we read usage/throttle counters per tenant and evaluate three
estimators against the truth (3.30 cores):

  naive      sum(u)
  quota-scale sum(u / quota_fraction)        ("knows the quotas" baseline)
  throttle   sum(u / (1 - t)) with clamp     (censoring-aware)

Writes /root/tb/mixedq_<round>.jsonl and prints a summary.
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
VMIDS = [311, 312, 313, 314, 315, 316]
PEGGED = VMIDS[:3]
IDLE = VMIDS[3:]
QUOTA_FRAC = 0.30
TRUTH = 3 * 1.0 + 3 * 0.10


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


def set_quota(vmid, quota_us, period_us):
    val = "%d %d" % (quota_us, period_us)
    with open("/sys/fs/cgroup/qemu.slice/%d.scope/cpu.max" % vmid, "w") as fh:
        fh.write(val + "\n")


def clear_quota(vmid):
    with open("/sys/fs/cgroup/qemu.slice/%d.scope/cpu.max" % vmid, "w") as fh:
        fh.write("max 100000\n")


def cpu_stat(vmid):
    d = {}
    try:
        for line in open("/sys/fs/cgroup/qemu.slice/%d.scope/cpu.stat" % vmid):
            k, v = line.split()
            d[k] = int(v)
    except OSError:
        pass
    return d


def start_burners():
    def one(vmid):
        duty = "1.0" if vmid in PEGGED else "0.10"
        extra = "" if vmid in PEGGED else "--randphase"
        vm_cmd(CUSTOMERS[vmid],
               'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; rm -f /tmp/burn_rate.txt; '
               'nohup python3 /home/debian/burner.py /tmp/burn_rate.txt 3600 '
               '--duty %s --period 60 %s >/dev/null 2>&1 < /dev/null & echo on' % (duty, extra),
               timeout=30)

    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(one, VMIDS))


def kill_burners():
    def one(vmid):
        vm_cmd(CUSTOMERS[vmid], 'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; true', timeout=30)

    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(one, VMIDS))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", default="mixedq1")
    ap.add_argument("--pool", default="8-15")
    ap.add_argument("--cycles", type=int, default=3)
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()

    pool = [int(x) for x in args.pool.replace("-", " ").split()] if "-" not in args.pool else \
        list(range(int(args.pool.split("-")[0]), int(args.pool.split("-")[1]) + 1))
    spec = ",".join(str(c) for c in pool)
    for vmid in VMIDS:
        pin(vmid, spec)

    sink = open("/root/tb/mixedq_%s.jsonl" % args.round, "a", encoding="utf-8")
    try:
        kill_burners()
        time.sleep(3)
        for vmid in VMIDS:
            set_quota(vmid, 30000, 100000)
        start_burners()
        time.sleep(30)
        for rep in range(args.repeats):
            a = {v: cpu_stat(v) for v in VMIDS}
            ta = time.time()
            time.sleep(60)
            b = {v: cpu_stat(v) for v in VMIDS}
            tb = time.time()
            dur = max(1.0, tb - ta)
            per = {}
            naive = scale = aware = clamp = noclamp = 0.0
            for v in VMIDS:
                du = (b[v].get("usage_usec", 0) - a[v].get("usage_usec", 0)) / (dur * 1e6)
                dt_ = (b[v].get("throttled_usec", 0) - a[v].get("throttled_usec", 0)) / (dur * 1e6)
                u = max(0.0, du)
                t = min(0.999, max(0.0, dt_))
                est_thr = min(1.0, u / (1.0 - t)) if (t > 0.01 or
                                                      (b[v].get("nr_throttled", 0) - a[v].get("nr_throttled", 0)) > 0) else u
                per[v] = {"usage": round(u, 3), "throttled_frac": round(t, 3),
                          "idle_class": v in IDLE}
                naive += u
                scale += u / QUOTA_FRAC
                aware += est_thr
                clamp += 1.0 if (t > 0.01 or (b[v].get("nr_throttled", 0) - a[v].get("nr_throttled", 0)) > 0) else u
                noclamp += u / (1.0 - t) if t < 0.999 else u
            rec = {"round": args.round, "rep": rep, "cycle_s": round(dur, 1),
                   "per_vm": per, "naive": round(naive, 2),
                   "quota_scale": round(scale, 2), "throttle_aware": round(aware, 2),
                   "clamp_fullvcpu": round(clamp, 2), "throttle_noclamp": round(noclamp, 2),
                   "truth": TRUTH,
                   "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
            sink.write(json.dumps(rec) + "\n")
            sink.flush()
            print("MIXEDQ rep=%d naive=%.2f scale=%.2f aware=%.2f clamp=%.2f noclamp=%.2f truth=%.2f" %
                  (rep, naive, scale, aware, clamp, noclamp, TRUTH), flush=True)
        for vmid in VMIDS:
            clear_quota(vmid)
    finally:
        kill_burners()
        sink.close()
        print("MIXEDQ %s DONE" % args.round, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
