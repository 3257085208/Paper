#!/usr/bin/env python3
"""Production-profile replay (host-side, runs on the physical host).

Drives 64 tenants from *real* per-minute duty schedules extracted from the
production telemetry (research_data/vps2_readonly/replay_sched). Burner
`--schedule` consumes duties in order (60 s periods, drifting phase — faithful
to the drifting bursts observed in production), preserving the cross-tenant
correlation of the original excerpt.

During the ~32-minute replay: pool busy (10 s), per-tenant rate batch (60 s),
service probes every 5 minutes. Output: /root/tb/replay_replay1.jsonl.
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
SCHED_DIR = "/root/tb/replay_sched"
PERIODS = 30  # 30-minute excerpt


def vm_cmd(ip, cmd, timeout=90):
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


def pool_busy_snapshot(cpus):
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


def busy_delta(a, b):
    busy = idle = 0
    for c in a:
        if c in b:
            busy += b[c][0] - a[c][0]
            idle += b[c][1] - a[c][1]
    return round(100.0 * (1.0 - idle / busy), 1) if busy else None


def read_rates(vmids):
    def one(vmid):
        out = vm_cmd(CUSTOMERS[vmid], "cat /tmp/burn_rate.txt 2>/dev/null", timeout=20)
        try:
            parts = out.strip().split()
            return vmid, float(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            return vmid, None, None

    with ThreadPoolExecutor(max_workers=16) as ex:
        return [[v, r, s] for v, r, s in ex.map(one, vmids)]


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
    ap.add_argument("--round", default="replay1")
    ap.add_argument("--pool", default="8-15")
    args = ap.parse_args()
    pool = list(range(int(args.pool.split("-")[0]), int(args.pool.split("-")[1]) + 1))
    spec = ",".join(str(c) for c in pool)

    # assign schedules to customers (sorted deterministic order)
    sched_files = sorted(f for f in os.listdir(SCHED_DIR) if f.endswith(".txt"))
    vmids = sorted(CUSTOMERS)[:len(sched_files)]
    for vmid in CUSTOMERS:
        pin(vmid, spec)
    for _, (v, c) in SERVICE_PIN.items():
        pin(v, c)

    # deploy burner + schedules
    def deploy(vmid, sfile):
        subprocess.run(["scp", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                        "-o", "LogLevel=ERROR", os.path.join(SCHED_DIR, sfile),
                        "debian@%s:/home/debian/replay_sched.txt" % CUSTOMERS[vmid]],
                       capture_output=True)
        subprocess.run(["scp", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                        "-o", "LogLevel=ERROR", "/root/tb/burner.py",
                        "debian@%s:/home/debian/burner.py" % CUSTOMERS[vmid]],
                       capture_output=True)
    with ThreadPoolExecutor(max_workers=16) as ex:
        list(ex.map(lambda t: deploy(*t), zip(vmids, sched_files)))

    def start(vmid):
        vm_cmd(CUSTOMERS[vmid],
               'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; rm -f /tmp/burn_rate.txt; '
               'nohup python3 /home/debian/burner.py /tmp/burn_rate.txt 3600 '
               '--duty 1.0 --period 60 --schedule /home/debian/replay_sched.txt '
               '>/dev/null 2>&1 < /dev/null & echo on', timeout=30)
    with ThreadPoolExecutor(max_workers=12) as ex:
        list(ex.map(start, vmids))

    sink = open("/root/tb/replay_%s.jsonl" % args.round, "a", encoding="utf-8")
    t0 = time.time()
    prev = pool_busy_snapshot(pool)
    probes = []
    last_probe = 0
    next_rate = t0 + 30
    try:
        while time.time() - t0 < PERIODS * 60 + 30:
            time.sleep(10)
            cur = pool_busy_snapshot(pool)
            rec = {"round": args.round, "t": round(time.time() - t0, 1),
                   "busy": busy_delta(prev, cur)}
            prev = cur
            if time.time() >= next_rate:
                rec["rates"] = read_rates(vmids)
                next_rate += 60
            sink.write(json.dumps(rec) + "\n")
            sink.flush()
            if time.time() - t0 - last_probe > 300:
                p = probe(args.round, "p%d" % int(time.time() - t0))
                probes.append({"t": round(time.time() - t0, 1), "http": p})
                last_probe = time.time() - t0
                print("probe@%ds http_p99=%s" % (int(last_probe), (p or {}).get("p99_ms")), flush=True)
    finally:
        def stop(vmid):
            vm_cmd(CUSTOMERS[vmid], 'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; true', timeout=30)
        with ThreadPoolExecutor(max_workers=12) as ex:
            list(ex.map(stop, vmids))
        sink.close()
        with open("/root/tb/replay_%s_probes.json" % args.round, "w") as fh:
            json.dump(probes, fh, indent=1)
        print("REPLAY %s DONE (%d minutes, %d probes)" % (args.round, PERIODS, len(probes)), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
