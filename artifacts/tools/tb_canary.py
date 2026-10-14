#!/usr/bin/env python3
"""Canary wakeup-stall vs density/phase (host-side, runs on the PVE host).

Two canary VMs (373/374, outside the load sets) run stall.py continuously;
we sample their 5 s windows under four background configurations:

  baseline   no burners
  rand40     40 tenants, random phase (duty 20%/60 s)
  sync32     32 tenants, wall-clock aligned
  mix50_40   20 aligned @0 s + 20 random phase

For each config: 65 s sampling of the canary stall file + a service probe +
pool busy. Writes /root/tb/canary_<round>.jsonl and prints a summary.
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
PROBE_VM = "10.10.0.20"
SVC = {"http": "10.10.0.11", "redis": "10.10.0.12"}
CUSTOMERS = {vmid: "10.10.0.%d" % (vmid - 290) for vmid in range(311, 375)}
CANARIES = [373, 374]
SSH = ["-n", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
       "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=8",
       "-o", "LogLevel=ERROR"]

CONFIGS = [
    ("baseline", []),
    ("rand40", [(40, "rand")]),
    ("sync32", [(32, "sync")]),
    ("mix50_40", [(20, "aligned0"), (20, "rand")]),
]


def vm_cmd(ip, cmd, timeout=90):
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


def kill_burners():
    def one(vmid):
        vm_cmd(CUSTOMERS[vmid], 'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; true', timeout=30)

    with ThreadPoolExecutor(max_workers=12) as ex:
        list(ex.map(one, list(CUSTOMERS)))


def start_group(vmids, mode, duty=0.20, period=60.0):
    if mode == "rand":
        extra = "--randphase"
    elif mode == "aligned0":
        extra = "--aligned --phase-offset 0"
    else:
        extra = "--aligned --phase-offset 0"

    def one(vmid):
        vm_cmd(CUSTOMERS[vmid],
               'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; rm -f /tmp/burn_rate.txt; '
               'nohup python3 /home/debian/burner.py /tmp/burn_rate.txt 7200 '
               '--duty %.2f --period %d %s >/dev/null 2>&1 < /dev/null & echo on' % (duty, period, extra),
               timeout=30)

    with ThreadPoolExecutor(max_workers=12) as ex:
        list(ex.map(one, vmids))


def deploy():
    for tool in ("burner.py", "stall.py"):
        def one(vmid):
            subprocess.run(["scp", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                            "-o", "LogLevel=ERROR", "/root/tb/%s" % tool,
                            "debian@%s:/home/debian/%s" % (CUSTOMERS[vmid], tool)],
                           capture_output=True)
        with ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(one, CANARIES + list(CUSTOMERS)[:64]))


def stall_snapshot(vmid):
    out = vm_cmd(CUSTOMERS[vmid], "cat /tmp/stall.txt 2>/dev/null")
    try:
        parts = out.split()
        return {"window_s": float(parts[0]), "max_gap_ms": float(parts[1]),
                "gt250": int(parts[2]), "gt1s": int(parts[3])}
    except (ValueError, IndexError):
        return None


def run_probe(tag, seconds=15, rate=100):
    out = vm_cmd(PROBE_VM,
                 "python3 /home/debian/probe.py --mode http --host %s --rate %d "
                 "--duration %d --tag %s --raw /home/debian/%s.raw" % (SVC["http"], rate, seconds, tag, tag),
                 timeout=2 * seconds + 90)
    for line in reversed(out.splitlines()):
        if line.strip().startswith("{"):
            try:
                return json.loads(line.strip())
            except ValueError:
                pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", default="canary1")
    ap.add_argument("--pool", default="8-15")
    ap.add_argument("--only", default=None)
    args = ap.parse_args()

    pool = list(range(int(args.pool.split("-")[0]), int(args.pool.split("-")[1]) + 1))
    spec = ",".join(str(c) for c in pool)
    for vmid in CUSTOMERS:
        pin(vmid, spec)
    deploy()
    # verify deployment, then start canaries
    for vmid in CANARIES:
        chk = vm_cmd(CUSTOMERS[vmid], "ls /home/debian/stall.py 2>/dev/null | wc -l")
        print("canary %d stall.py present: %s" % (vmid, chk.strip()), flush=True)
        vm_cmd(CUSTOMERS[vmid], "pkill -f 'stall[.]py' 2>/dev/null; rm -f /tmp/stall.txt; "
                                "nohup python3 /home/debian/stall.py /tmp/stall.txt "
                                ">/dev/null 2>&1 < /dev/null & echo on", timeout=30)
    time.sleep(8)
    for vmid in CANARIES:
        probe = vm_cmd(CUSTOMERS[vmid], "cat /tmp/stall.txt 2>/dev/null")
        print("canary %d first reading: [%s]" % (vmid, probe.strip()), flush=True)

    sink = open("/root/tb/canary_%s.jsonl" % args.round, "a", encoding="utf-8")
    vmids = sorted(CUSTOMERS)
    try:
        for name, groups in CONFIGS:
            if args.only and name != args.only:
                continue
            kill_burners()
            time.sleep(3)
            idx = 0
            started = []
            for cnt, mode in groups:
                group = vmids[idx:idx + cnt]
                # canaries must never join the load
                group = [v for v in group if v not in CANARIES]
                start_group(group, mode)
                started.extend(group)
                idx += cnt
            time.sleep(25)
            snaps = {v: [] for v in CANARIES}
            t0 = time.time()
            while time.time() - t0 < 65:
                for v in CANARIES:
                    s = stall_snapshot(v)
                    if s:
                        snaps[v].append(s)
                time.sleep(5)
            http = run_probe("%s_%s" % (args.round, name))
            rec = {"round": args.round, "config": name, "tenants": len(started),
                   "canary": {str(v): {
                       "max_gap_ms": max((s["max_gap_ms"] for s in snaps[v]), default=None),
                       "mean_gap_ms": round(statistics.mean([s["max_gap_ms"] for s in snaps[v]]), 1)
                                       if snaps[v] else None,
                       "gt250_total": sum(s["gt250"] for s in snaps[v]),
                       "gt1s_total": sum(s["gt1s"] for s in snaps[v]),
                       "windows": len(snaps[v])} for v in CANARIES},
                   "http_p99": (http or {}).get("p99_ms"),
                   "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
            sink.write(json.dumps(rec) + "\n")
            sink.flush()
            print("CANARY %-10s tenants=%2d canary_max_gap=%s ms (gt250=%s gt1s=%s) http=%s" % (
                name, len(started),
                max((s["max_gap_ms"] for v in CANARIES for s in snaps[v]), default=None),
                sum(s["gt250"] for v in CANARIES for s in snaps[v]),
                sum(s["gt1s"] for v in CANARIES for s in snaps[v]),
                (http or {}).get("p99_ms")), flush=True)
    finally:
        kill_burners()
        for vmid in CANARIES:
            vm_cmd(CUSTOMERS[vmid], "pkill -f 'stall[.]py' 2>/dev/null; true", timeout=30)
        sink.close()
        print("CANARY %s DONE" % args.round, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
