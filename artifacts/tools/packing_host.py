#!/usr/bin/env python3
"""Mixed-workload packing pilot (runs ON the PVE test host).

Starts a mixed set of "customers" (neighbor VMs) each with a workload class,
settles, records host busy%, every customer's work-phase rate/state, and probes
svc-http + svc-redis (open-loop). One JSON record per run is appended to
/root/packing_<round>.jsonl.

Usage:
  python3 packing_host.py --round p1 --profile "idle:7,bursty:2,pegged:1" --probe-seconds 60

Profile assigns classes to neighbors 1..N in order (neighbor-1..neighbor-10).
Classes: pegged (100%), bursty (33%/60s), idle (10%/60s), syncidle (10%/60s aligned),
sync20 (20%/60s aligned).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time

KEY = "/root/.ssh/sci2_key"
PROBE_VM = "10.10.10.20"
SVC = {"http": "10.10.10.11", "redis": "10.10.10.12"}
NEIGHBOR_IP = {k: "10.10.10.%d" % (20 + k) for k in range(1, 11)}
SLO_P99_MS = 10.0
SSH_BASE = ["-n", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10",
            "-o", "LogLevel=ERROR"]

CLASS_ARGS = {
    "pegged": "",
    "bursty": "--duty 0.33 --period 60",
    "idle": "--duty 0.10 --period 60",
    "syncidle": "--duty 0.10 --period 60 --aligned",
    "sync20": "--duty 0.20 --period 60 --aligned",
    "idleR": "--duty 0.10 --period 60 --randphase",
    "burstyR": "--duty 0.33 --period 60 --randphase",
}


def vm_cmd(ip, cmd, timeout=150):
    res = subprocess.run(["ssh"] + SSH_BASE + ["debian@" + ip, cmd],
                         capture_output=True, text=True, timeout=timeout)
    return res.stdout


def stop_all():
    for k in NEIGHBOR_IP:
        vm_cmd(NEIGHBOR_IP[k], 'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; true',
               timeout=40)


def start(k, cls):
    cmd = ('pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; rm -f /tmp/burn_rate.txt; '
           'nohup python3 /home/debian/burner.py /tmp/burn_rate.txt 3600 %s >/dev/null 2>&1 & echo ok'
           % CLASS_ARGS[cls])
    return vm_cmd(NEIGHBOR_IP[k], cmd, timeout=40)


def status(k):
    out = vm_cmd(NEIGHBOR_IP[k], "cat /tmp/burn_rate.txt 2>/dev/null", timeout=40)
    parts = out.strip().split()
    if len(parts) == 2:
        try:
            return {"rate": float(parts[0]), "state": int(parts[1])}
        except ValueError:
            pass
    if len(parts) == 1:
        try:
            return {"rate": float(parts[0]), "state": 1}
        except ValueError:
            pass
    return None


def sample_busy():
    res = subprocess.run(["/tmp/busy3.sh"], capture_output=True, text=True, timeout=30)
    for line in res.stdout.splitlines():
        if "host_busy_pct=" in line:
            return float(line.split("=", 1)[1])
    return None


def run_probes(round_name, seconds, rate):
    cmds = []
    for mode in ("http", "redis"):
        cmds.append("python3 /home/debian/probe.py --mode %s --host %s --rate %d "
                    "--duration %d --tag pack-%s-%s --raw /home/debian/pack_%s_%s.raw" %
                    (mode, SVC[mode], rate, seconds, round_name, mode, round_name, mode))
    out = vm_cmd(PROBE_VM, " ; ".join(cmds), timeout=2 * seconds + 120)
    found = {}
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                obj = json.loads(line)
                found[obj.get("mode")] = obj
            except ValueError:
                pass
    return found.get("http"), found.get("redis")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", required=True)
    ap.add_argument("--profile", required=True,
                    help='e.g. "idle:7,bursty:2,pegged:1"')
    ap.add_argument("--settle", type=float, default=15.0)
    ap.add_argument("--probe-seconds", type=float, default=60.0)
    ap.add_argument("--rate", type=float, default=100.0)
    args = ap.parse_args()

    classes = []
    for part in args.profile.split(","):
        name, count = part.split(":")
        classes.extend([name.strip()] * int(count))
    if len(classes) > 10:
        raise SystemExit("profile exceeds 10 neighbors")

    path = "/root/packing_%s.jsonl" % args.round
    sink = open(path, "a", encoding="utf-8")
    try:
        stop_all()
        time.sleep(2)
        for k, cls in enumerate(classes, start=1):
            start(k, cls)
        for k in range(len(classes) + 1, 11):
            pass  # neighbors not in the profile are already stopped
        time.sleep(args.settle)
        busy = sample_busy()
        statuses = [status(k) for k in range(1, len(classes) + 1)]
        http_stats, redis_stats = run_probes(args.round, args.probe_seconds, args.rate)
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "round": args.round,
               "profile": args.profile, "busy_pct": busy, "statuses": statuses,
               "windows": {}}
        for mode, stats in (("http", http_stats), ("redis", redis_stats)):
            if not stats:
                print("   %s: MISSING" % mode, flush=True)
                continue
            viol = bool(stats.get("p99_ms") is not None and stats["p99_ms"] > SLO_P99_MS)
            rec["windows"][mode] = {
                "p50_ms": stats.get("p50_ms"), "p99_ms": stats.get("p99_ms"),
                "p999_ms": stats.get("p999_ms"), "max_ms": stats.get("max_ms"),
                "schedule_lag_p99_ms": stats.get("schedule_lag_p99_ms"),
                "timeouts": stats.get("timeouts"), "violation": viol}
            print("   %s: p50=%s p99=%s p999=%s viol=%s" %
                  (mode, stats.get("p50_ms"), stats.get("p99_ms"),
                   stats.get("p999_ms"), viol), flush=True)
        sink.write(json.dumps(rec, ensure_ascii=False) + "\n")
        sink.flush()
        print("PACKING %s DONE busy=%s statuses=%s" %
              (args.round, busy, [("%.0f/%d" % (s["rate"], s["state"])) if s else "?" for s in statuses]),
              flush=True)
    finally:
        stop_all()
        sink.close()


if __name__ == "__main__":
    main()
