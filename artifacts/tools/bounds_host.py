#!/usr/bin/env python3
"""Demand-bound validation: recover true demand from (quota, throttle fraction).

For a 1-vCPU tenant whose demand D exceeds its quota q:
  run fraction per period r = q / D, throttled fraction t = 1 - r
  =>  D = q / (1 - t),  estimated from observable counters alone.

Six (duty, quota) cells run five burners each: measure usage cores u and the
throttled time fraction t from cpu.stat deltas, compute D_lb = u / (1 - t)
capped at the vCPU count, compare against the measured truth (usage after the
quota is lifted). Records to /root/bounds_<round>.jsonl.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time

KEY = "/root/.ssh/sci2_key"
CUST_K = [1, 2, 3, 4, 5]
CUST_VMID = {k: 110 + k for k in CUST_K}
CUST_IP = {k: "10.10.10.%d" % (20 + k) for k in CUST_K}
CELLS = [(1.0, 20000), (1.0, 40000), (1.0, 60000)]
SSH_BASE = ["-n", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10",
            "-o", "LogLevel=ERROR"]


def sh_local(cmd, timeout=30):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout).stdout


def vm_cmd(ip, cmd, timeout=90):
    res = subprocess.run(["ssh"] + SSH_BASE + ["debian@" + ip, cmd],
                         capture_output=True, text=True, timeout=timeout)
    return res.stdout


def vm_cmd_safe(ip, cmd, timeout=90):
    try:
        return vm_cmd(ip, cmd, timeout=timeout)
    except subprocess.TimeoutExpired:
        return ""


def set_quota(vmid, spec):
    sh_local('echo "%s" > /sys/fs/cgroup/qemu.slice/%d.scope/cpu.max' % (spec, vmid))


def cpu_stat(vmid):
    d = {}
    try:
        with open("/sys/fs/cgroup/qemu.slice/%d.scope/cpu.stat" % vmid) as fh:
            for line in fh:
                k, v = line.split()
                d[k] = int(v)
    except (OSError, ValueError):
        pass
    return d


def start_burner(k, duty):
    args = "" if duty >= 1.0 else "--duty %.2f --period 60" % duty
    vm_cmd_safe(CUST_IP[k],
                'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; rm -f /tmp/burn_rate.txt; '
                'nohup python3 /home/debian/burner.py /tmp/burn_rate.txt 3600 %s >/dev/null 2>&1 & echo ok' % args,
                timeout=40)


def stop_burners():
    for k in range(1, 17):
        vm_cmd_safe("10.10.10.%d" % (20 + k),
                    'pkill -9 -f "^python3 /home/debian/burner.py" 2>/dev/null; true', timeout=40)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", required=True)
    args = ap.parse_args()
    sink = open("/root/bounds_%s.jsonl" % args.round, "a", encoding="utf-8")
    try:
        stop_burners()
        for duty, quota_us in CELLS:
            quota = "%d 100000" % quota_us
            for k in CUST_K:
                set_quota(CUST_VMID[k], quota)
            for k in CUST_K:
                start_burner(k, duty)
            time.sleep(10)
            a = {k: cpu_stat(CUST_VMID[k]) for k in CUST_K}
            t0 = time.time()
            time.sleep(20)
            b = {k: cpu_stat(CUST_VMID[k]) for k in CUST_K}
            dt = max(1.0, time.time() - t0)
            measured = {}
            for k in CUST_K:
                u = (b[k].get("usage_usec", 0) - a[k].get("usage_usec", 0)) / (dt * 1e6)
                th = (b[k].get("throttled_usec", 0) - a[k].get("throttled_usec", 0)) / (dt * 1e6)
                t = min(0.95, max(0.0, th))
                d_lb = min(1.0, u / (1.0 - t)) if t > 0.01 else u
                measured[k] = {"usage": round(u, 3), "t": round(t, 3), "d_lb": round(d_lb, 3)}
            # measure truth per VM: lift ONE quota at a time (host has room)
            truth = {}
            for kk in CUST_K:
                set_quota(CUST_VMID[kk], "max 100000")
                time.sleep(4)
                a = {kk: cpu_stat(CUST_VMID[kk])}
                t0 = time.time()
                time.sleep(8)
                b = {kk: cpu_stat(CUST_VMID[kk])}
                dt = max(1.0, time.time() - t0)
                truth[kk] = round((b[kk].get("usage_usec", 0) - a[kk].get("usage_usec", 0)) / (dt * 1e6), 3)
                set_quota(CUST_VMID[kk], quota)
                time.sleep(2)
            mean_lb = sum(v["d_lb"] for v in measured.values()) / len(measured)
            mean_truth = sum(truth.values()) / len(truth)
            rec = {"round": args.round, "duty": duty, "quota": quota_us / 100000.0,
                   "per_vm": measured, "truth": truth,
                   "mean_d_lb": round(mean_lb, 3), "mean_truth": round(mean_truth, 3)}
            sink.write(json.dumps(rec) + "\n")
            sink.flush()
            print("duty=%.2f quota=%.2f: D_lb=%.3f truth=%.3f (per-VM t=%s)" %
                  (duty, quota_us / 100000.0, mean_lb, mean_truth,
                   ["%.2f" % v["t"] for v in measured.values()]), flush=True)
    finally:
        stop_burners()
        for k in CUST_K:
            set_quota(CUST_VMID[k], "max 100000")
        sink.close()
        print("BOUNDS %s DONE" % args.round, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
