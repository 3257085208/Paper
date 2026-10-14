#!/usr/bin/env python3
"""Adaptive per-tenant io.max vs static cap vs uncontrolled (host-side).

Eight storm tenants run a 4K random 70/30 O_DIRECT storm for 60 s per arm:
  none      no caps
  static    io.max = 300/150 riops/wiops per tenant
  adaptive  AIMD on io.max driven by host io PSI (some avg10):
            bake | >12 -> x0.6 (floor 80/40); <4 -> x1.3 (ceil 2000/1000)
Metrics: host IOPS (diskstats), service probe P99 mid-storm, aggregate tenant
IOPS and per-op P99 from the guest-side iostorm reports.

Usage: python3 tb_ioctl.py --round ioc1
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

KEY = "/root/.ssh/tb_key"
CUSTOMERS = {vmid: "10.10.0.%d" % (vmid - 290) for vmid in range(311, 375)}
STORM_VMIDS = [311, 312, 313, 314, 315, 316, 317, 318]
SSH = ["-n", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
       "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=8",
       "-o", "LogLevel=ERROR"]
STATIC_CAP = (300, 150)
START_CAP = (800, 400)
FLOOR_CAP = (80, 40)
CEIL_CAP = (2000, 1000)


def vm_cmd(ip, cmd, timeout=120):
    try:
        res = subprocess.run(["ssh"] + SSH + ["debian@" + ip, cmd],
                             capture_output=True, text=True, timeout=timeout)
        return res.stdout
    except subprocess.TimeoutExpired:
        return ""


def dev_id():
    out = subprocess.run(["lsblk", "-ndo", "MAJ:MIN", "/dev/md0"],
                         capture_output=True, text=True).stdout.strip()
    return out or "9:0"


def set_iomax(vmid, dev, riops, wiops):
    path = "/sys/fs/cgroup/qemu.slice/%d.scope/io.max" % vmid
    val = "%s riops=%d wiops=%d" % (dev, riops, wiops)
    try:
        with open(path, "w") as fh:
            fh.write(val + "\n")
        return True
    except OSError:
        return False


def clear_iomax(vmid, dev):
    try:
        with open("/sys/fs/cgroup/qemu.slice/%d.scope/io.max" % vmid, "w") as fh:
            fh.write("%s riops=max wiops=max\n" % dev)
    except OSError:
        pass


def disk_iops():
    tot = 0
    for line in open("/proc/diskstats"):
        p = line.split()
        if len(p) > 7 and p[2] in ("md0", "nvme0n1", "nvme1n1"):
            tot += int(p[3]) + int(p[7])
    return tot


def psi_io_some10():
    for line in open("/proc/pressure/io"):
        if line.startswith("some"):
            for f in line.split()[1:]:
                if f.startswith("avg10"):
                    return float(f.split("=")[1])
    return 0.0


def probe(tag, seconds=30, rate=100):
    cmd = ("python3 /home/debian/probe.py --mode http --host 10.10.0.11 "
           "--rate %d --duration %d --tag %s --raw /home/debian/%s.raw" % (rate, seconds, tag, tag))
    try:
        out = subprocess.run(["ssh"] + SSH + ["debian@10.10.0.20", cmd],
                             capture_output=True, text=True, timeout=2 * seconds + 90).stdout
    except subprocess.TimeoutExpired:
        return None
    for line in reversed(out.splitlines()):
        if line.strip().startswith("{"):
            try:
                return json.loads(line.strip())
            except ValueError:
                pass
    return None


def start_storm(vmid, seconds):
    vm_cmd(CUSTOMERS[vmid],
           "rm -f /tmp/iostorm.out /home/debian/iofile.bin; "
           "nohup python3 /home/debian/iostorm.py %d /home/debian/iofile.bin 4 "
           "> /tmp/iostorm.out 2>&1 < /dev/null & echo on" % seconds, timeout=30)


def collect_storm(vmid):
    out = vm_cmd(CUSTOMERS[vmid], "cat /tmp/iostorm.out 2>/dev/null", timeout=30)
    for line in reversed(out.splitlines()):
        if line.strip().startswith("{"):
            try:
                return json.loads(line.strip())
            except ValueError:
                pass
    return None


def run_arm(name, dev, sink, round_name, adaptive=False):
    for vmid in STORM_VMIDS:
        clear_iomax(vmid, dev)
    if name == "static":
        for vmid in STORM_VMIDS:
            set_iomax(vmid, dev, *STATIC_CAP)
    cap = list(START_CAP)
    if adaptive:
        for vmid in STORM_VMIDS:
            set_iomax(vmid, dev, *cap)

    stop_evt = threading.Event()
    traj = []

    def controller():
        nonlocal cap
        while not stop_evt.is_set():
            p = psi_io_some10()
            if name == "adaptive":
                if p > 12 and cap[0] > FLOOR_CAP[0]:
                    cap = [max(FLOOR_CAP[0], int(cap[0] * 0.6)),
                           max(FLOOR_CAP[1], int(cap[1] * 0.6))]
                elif p < 4 and cap[0] < CEIL_CAP[0]:
                    cap = [min(CEIL_CAP[0], int(cap[0] * 1.3)),
                           min(CEIL_CAP[1], int(cap[1] * 1.3))]
                for vmid in STORM_VMIDS:
                    set_iomax(vmid, dev, *cap)
            traj.append({"t": round(time.time(), 2), "psi_io10": p, "cap": list(cap)})
            time.sleep(2)

    iops0 = disk_iops()
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda v: start_storm(v, 75), STORM_VMIDS))
    ctl = threading.Thread(target=controller, daemon=True)
    ctl.start()
    time.sleep(8)
    mid = probe("%s_%s" % (round_name, name), seconds=30)
    time.sleep(37)
    stop_evt.set()
    time.sleep(2)
    iops1 = disk_iops()
    host_iops = int((iops1 - iops0) / max(1.0, time.time() - t0 - 30))
    results = [collect_storm(v) for v in STORM_VMIDS]
    ok = [r for r in results if r]
    total_iops = sum(r["iops"] for r in ok)
    p99s = sorted(r["p99_ms"] for r in ok if r.get("p99_ms"))
    rec = {"round": round_name, "arm": name, "host_iops_est": host_iops,
           "tenant_iops_total": total_iops, "tenants_ok": len(ok),
           "tenant_p99_ms_max": p99s[-1] if p99s else None,
           "mid_http_p99": (mid or {}).get("p99_ms"),
           "cap_traj": traj[::5],
           "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    sink.write(json.dumps(rec) + "\n")
    sink.flush()
    print("IOCTL %-8s: host_iops=%d tenant_iops=%d (n=%d) tenant_p99_max=%s http_p99=%s" %
          (name, host_iops, total_iops, len(ok), rec["tenant_p99_ms_max"],
           rec["mid_http_p99"]), flush=True)
    for vmid in STORM_VMIDS:
        clear_iomax(vmid, dev)
    time.sleep(10)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", default="ioc1")
    args = ap.parse_args()
    dev = dev_id()
    print("io.max device:", dev, flush=True)

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda v: vm_cmd(CUSTOMERS[v],
                                     "pkill -f iostorm.py 2>/dev/null; true", timeout=30),
                    STORM_VMIDS))
    # ship the storm helper
    for vmid in STORM_VMIDS:
        subprocess.run(["scp", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                        "-o", "LogLevel=ERROR", "/root/tb/iostorm.py",
                        "debian@%s:/home/debian/iostorm.py" % CUSTOMERS[vmid]],
                       capture_output=True)

    sink = open("/root/tb/ioctl_%s.jsonl" % args.round, "a", encoding="utf-8")
    run_arm("none", dev, sink, args.round, adaptive=False)
    run_arm("static", dev, sink, args.round, adaptive=False)
    run_arm("adaptive", dev, sink, args.round, adaptive=True)
    sink.close()
    print("IOCTL %s DONE" % args.round, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
