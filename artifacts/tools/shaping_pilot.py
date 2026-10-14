#!/usr/bin/env python3
"""Shaping pilot: how many candidate VMs can be added under different schemes?

Schemes (all measured with the same protocol):
  unlimited  no CPU limits anywhere (reference: the knee itself)
  q75        every candidate VM capped at 0.75 core (cgroup v2 cpu.max)
  q50        every candidate VM capped at 0.50 core
  pin        services + probe pinned to cores 0-1, candidates pinned to cores 2-3

Protocol per scheme run: for each level k in --levels, exactly k neighbors run
tools/burner.py (measurable CPU-bound loop; iterations/s in /tmp/burn_rate.txt).
After a settle period the host busy% and the active burn rates are sampled, then
svc-http and svc-redis are probed (open-loop, --rate req/s for --probe-seconds
each). Results are appended as JSONL to <outdir>/shaping_<round>.jsonl.

Usage:
  python3 tools/shaping_pilot.py --round s1u --scheme unlimited
  python3 tools/shaping_pilot.py --round s1q --scheme q75
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

KEY = os.path.expanduser("~/.ssh/sci2_key")
HOST = "45.82.120.52"
PORT = "2828"
PROBE_VM = "10.10.10.20"
SVC = {"http": "10.10.10.11", "redis": "10.10.10.12"}
NEIGHBOR_VMID = {1: 111, 2: 112, 3: 113, 4: 114, 5: 115}
NEIGHBOR_IP = {1: "10.10.10.21", 2: "10.10.10.22", 3: "10.10.10.23",
               4: "10.10.10.24", 5: "10.10.10.25"}
INFRA_VMIDS = [101, 102, 110]
ALL_VMIDS = INFRA_VMIDS + [111, 112, 113, 114, 115]
SLO_P99_MS = 10.0

PROXY = ("ssh -i %s -o IdentitiesOnly=yes -o BatchMode=yes -p %s root@%s -W %%h:%%p"
         % (KEY, PORT, HOST))
SSH_BASE = ["-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new"]


def host_cmd(cmd, timeout=60):
    res = subprocess.run(["ssh"] + SSH_BASE + ["-p", PORT, "-o", "ConnectTimeout=15",
                                               "root@" + HOST, cmd],
                         capture_output=True, text=True, timeout=timeout)
    return res.stdout


def vm_cmd(ip, cmd, timeout=90):
    res = subprocess.run(["ssh", "-o", "ProxyCommand=" + PROXY] + SSH_BASE +
                         ["-o", "ConnectTimeout=12", "debian@" + ip, cmd],
                         capture_output=True, text=True, timeout=timeout)
    return res.stdout


def sync_resources(quota_by_vmid, affinity_by_vmid):
    parts = []
    for vmid, spec in sorted(quota_by_vmid.items()):
        parts.append('echo "%s" > /sys/fs/cgroup/qemu.slice/%d.scope/cpu.max' % (spec, vmid))
    for vmid, mask in sorted(affinity_by_vmid.items()):
        parts.append('pid=$(cat /run/qemu-server/%d.pid); taskset -apc %s $pid >/dev/null 2>&1' % (vmid, mask))
    parts.append("echo resources_synced")
    return host_cmd("; ".join(parts), timeout=90)


def burner_start(k):
    vm_cmd(NEIGHBOR_IP[k],
           'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; rm -f /tmp/burn_rate.txt; '
           'nohup python3 /home/debian/burner.py /tmp/burn_rate.txt 600 >/dev/null 2>&1 & echo ok',
           timeout=30)


def burner_stop(k):
    vm_cmd(NEIGHBOR_IP[k], 'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; true', timeout=30)


def burn_rate(k):
    out = vm_cmd(NEIGHBOR_IP[k], 'cat /tmp/burn_rate.txt 2>/dev/null', timeout=30)
    try:
        return float(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def sample_busy():
    out = host_cmd('/tmp/busy3.sh', timeout=30)
    for line in out.splitlines():
        if "host_busy_pct=" in line:
            return float(line.split("=", 1)[1])
    return None


def run_probes(round_name, scheme, level, seconds, rate):
    cmds = []
    for mode in ("http", "redis"):
        cmds.append("python3 /home/debian/probe.py --mode %s --host %s --rate %d "
                    "--duration %d --tag shp-%s-%s-L%d --raw /home/debian/shp_%s_%s_L%d_%s.raw" %
                    (mode, SVC[mode], rate, seconds, round_name, scheme, level,
                     round_name, scheme, level, mode))
    out = vm_cmd(PROBE_VM, " ; ".join(cmds), timeout=2 * seconds + 90)
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


def scheme_prep(scheme):
    for k in range(1, 6):
        burner_stop(k)
    quotas = {v: "max 100000" for v in ALL_VMIDS}
    affinity = {v: "0-3" for v in ALL_VMIDS}
    if scheme == "q75":
        for v in NEIGHBOR_VMID.values():
            quotas[v] = "75000 100000"
    elif scheme == "q50":
        for v in NEIGHBOR_VMID.values():
            quotas[v] = "50000 100000"
    elif scheme == "pin":
        for v in INFRA_VMIDS:
            affinity[v] = "0,1"
        for v in NEIGHBOR_VMID.values():
            affinity[v] = "2,3"
    sync_resources(quotas, affinity)


def scheme_cleanup(scheme):
    for k in range(1, 6):
        burner_stop(k)
    sync_resources({v: "max 100000" for v in ALL_VMIDS},
                   {v: "0-3" for v in ALL_VMIDS})


def run_scheme(args):
    path = os.path.join(args.outdir, "shaping_%s.jsonl" % args.round)
    sink = open(path, "a", encoding="utf-8")
    try:
        scheme_prep(args.scheme)
        time.sleep(4)
        active = set()
        levels = [int(x) for x in args.levels.split(",")]
        for level in levels:
            print("===== %s / %s / level %d =====" % (args.round, args.scheme, level), flush=True)
            for k in range(1, 6):
                if k <= level and k not in active:
                    burner_start(k)
                    active.add(k)
                elif k > level and k in active:
                    burner_stop(k)
                    active.discard(k)
            time.sleep(args.settle)
            busy = sample_busy()
            rates = [burn_rate(k) for k in range(1, level + 1)]
            rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "round": args.round,
                   "scheme": args.scheme, "level": level, "busy_pct": busy,
                   "burn_rates": rates, "windows": {}}
            http_stats, redis_stats = run_probes(args.round, args.scheme, level,
                                                 args.probe_seconds, args.rate)
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
        print("SCHEME %s DONE" % args.scheme, flush=True)
    finally:
        scheme_cleanup(args.scheme)
        sink.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", required=True)
    ap.add_argument("--scheme", required=True,
                    choices=["unlimited", "q75", "q50", "pin"])
    ap.add_argument("--levels", default="0,1,2,3,4,5")
    ap.add_argument("--settle", type=float, default=12.0)
    ap.add_argument("--probe-seconds", type=float, default=15.0)
    ap.add_argument("--rate", type=float, default=100.0)
    ap.add_argument("--outdir", default="research_data/berohost_pilot")
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    run_scheme(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
