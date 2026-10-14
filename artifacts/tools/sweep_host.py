#!/usr/bin/env python3
"""Knee sweep (runs ON the PVE test host).

One round = the given level order (levels 0..5 = number of neighbor VMs each
running one busy `yes` loop). For each level: set burners, settle, record host
busy%, run open-loop probes (100 req/s, 20 s) against svc-http and svc-redis.

Per-level records -> /root/knee_<round>.jsonl
Raw per-request files -> probe VM /home/debian/<round>_L<lvl>_<svc>.raw
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time

KEY = "/root/.ssh/sci2_key"
NEIGHBOR_IPS = ["10.10.10.%d" % (20 + k) for k in range(1, 6)]
PROBE_VM = "10.10.10.20"
SVC = {"http": "10.10.10.11", "redis": "10.10.10.12"}
SSH_BASE = ["-n", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10",
            "-o", "LogLevel=ERROR"]


def vm_cmd(ip, cmd, timeout=120):
    try:
        res = subprocess.run(["ssh"] + SSH_BASE + ["debian@" + ip, cmd],
                             capture_output=True, text=True, timeout=timeout)
        return res.stdout
    except subprocess.TimeoutExpired:
        return ""


def set_burners(count):
    for idx, ip in enumerate(NEIGHBOR_IPS, 1):
        if idx <= count:
            vm_cmd(ip, "pkill -x yes 2>/dev/null; sleep 1; nohup yes > /dev/null 2>&1 & echo on",
                   timeout=40)
        else:
            vm_cmd(ip, "pkill -x yes 2>/dev/null; true", timeout=40)


def sample_busy():
    res = subprocess.run(["/tmp/busy3.sh"], capture_output=True, text=True, timeout=30)
    for line in res.stdout.splitlines():
        if "host_busy_pct=" in line:
            return float(line.split("=", 1)[1])
    return None


def run_probe(round_name, level, mode, seconds=20, rate=100.0):
    tag = "%s-L%d-%s" % (round_name, level, mode)
    raw = "/home/debian/%s_L%d_%s.raw" % (round_name, level, mode)
    out = vm_cmd(PROBE_VM,
                 "python3 /home/debian/probe.py --mode %s --host %s --rate %s "
                 "--duration %d --tag %s --raw %s" %
                 (mode, SVC[mode], rate, seconds, tag, raw),
                 timeout=int(2 * seconds) + 120)
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                return None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", required=True)
    ap.add_argument("--levels", default="0 1 2 3 4 5",
                    help="space-separated level order for this round")
    ap.add_argument("--probe-seconds", type=float, default=20.0)
    args = ap.parse_args()

    path = "/root/knee_%s.jsonl" % args.round
    sink = open(path, "a", encoding="utf-8")
    try:
        for lvl in [int(x) for x in args.levels.split()]:
            set_burners(lvl)
            time.sleep(10)
            busy = sample_busy()
            http = run_probe(args.round, lvl, "http", args.probe_seconds)
            redis = run_probe(args.round, lvl, "redis", args.probe_seconds)
            rec = {"round": args.round, "level": lvl, "busy_pct": busy, "http": http, "redis": redis}
            sink.write(json.dumps(rec) + "\n")
            sink.flush()
            print("L%d: busy=%s http_p99=%s redis_p99=%s" %
                  (lvl, busy, (http or {}).get("p99_ms"), (redis or {}).get("p99_ms")),
                  flush=True)
    finally:
        set_burners(0)
        sink.close()
        print("KNEE %s DONE" % args.round, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
