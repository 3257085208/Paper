#!/usr/bin/env python3
"""Disk contention pilot (runs ON the PVE test host).

All 10 customer VMs run fio (4k random rw 70/30, iodepth 16, 2 jobs, 60 s,
O_DIRECT) against files inside their own disks (qcow2 files on host disk 8:1).
Service latency is probed during each run; per-VM and host-level IO deltas are
read from cgroup io.stat and /proc/diskstats.

Modes:
  baseline  no io controls
  capped    io.max per customer scope (--riops/--wiops, DEV 8:1)
  weighted  io.weight: neighbors 1-5 -> 50, 6-10 -> 500

One JSON record per run appended to /root/disk_<round>.jsonl.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time

KEY = "/root/.ssh/sci2_key"
PROBE_VM = "10.10.10.20"
SVC = {"http": "10.10.10.11", "redis": "10.10.10.12"}
NEIGHBOR_VMID = {k: 110 + k for k in range(1, 11)}
NEIGHBOR_IP = {k: "10.10.10.%d" % (20 + k) for k in range(1, 11)}
DEV = "8:0"
FIO_RUNTIME = 60
SSH_BASE = ["-n", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10",
            "-o", "LogLevel=ERROR"]


def sh_local(cmd, timeout=30):
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return res.stdout


def vm_cmd(ip, cmd, timeout=120):
    res = subprocess.run(["ssh"] + SSH_BASE + ["debian@" + ip, cmd],
                         capture_output=True, text=True, timeout=timeout)
    return res.stdout


def vm_cmd_safe(ip, cmd, timeout=90):
    try:
        return vm_cmd(ip, cmd, timeout=timeout)
    except subprocess.TimeoutExpired:
        return ""


def set_iomax(vmid, riops, wiops):
    if riops is None:
        spec = "%s rbps=max wbps=max riops=max wiops=max" % DEV
    else:
        spec = "%s rbps=max wbps=max riops=%d wiops=%d" % (DEV, riops, wiops)
    sh_local('echo "%s" > /sys/fs/cgroup/qemu.slice/%d.scope/io.max' % (spec, vmid))


def set_ioweight(vmid, weight):
    sh_local('echo "%s %d" > /sys/fs/cgroup/qemu.slice/%d.scope/io.weight' % (DEV, weight, vmid))


def diskstats():
    for line in open("/proc/diskstats"):
        f = line.split()
        if len(f) > 13 and f[2] == "sda1":
            return {"reads": int(f[3]), "rsec": int(f[5]),
                    "writes": int(f[7]), "wsec": int(f[9])}
    return {}


def iostat_scope(vmid):
    try:
        with open("/sys/fs/cgroup/qemu.slice/%d.scope/io.stat" % vmid) as fh:
            for line in fh:
                parts = line.split()
                if parts[0] == DEV:
                    kv = dict(p.split("=") for p in parts[1:])
                    return {k: int(v) for k, v in kv.items()}
    except (OSError, ValueError):
        pass
    return {}


def start_fio(round_name):
    for k in NEIGHBOR_IP:
        cmd = ("pkill -f '^fio ' 2>/dev/null; nohup fio --name=job --directory=/home/debian/fio-test "
               "--size=512M --rw=randrw --rwmixread=70 --bs=4k --iodepth=16 --numjobs=2 --direct=1 "
               "--time_based --runtime=%d --group_reporting --output-format=json "
               "--output=/tmp/fio_%s_%d.json >/dev/null 2>&1 & echo ok" % (FIO_RUNTIME, round_name, k))
        vm_cmd_safe(NEIGHBOR_IP[k], cmd, timeout=45)


def stop_fio():
    for k in NEIGHBOR_IP:
        vm_cmd_safe(NEIGHBOR_IP[k], "pkill -f '^fio ' 2>/dev/null; true", timeout=45)


def collect_fio(round_name):
    out = {}
    for k in NEIGHBOR_IP:
        txt = vm_cmd_safe(NEIGHBOR_IP[k], "cat /tmp/fio_%s_%d.json 2>/dev/null" % (round_name, k),
                          timeout=60)
        try:
            obj = json.loads(txt)
            j = obj["jobs"][0]
            res = {"read_iops": round(j["read"].get("iops", 0), 1),
                   "write_iops": round(j["write"].get("iops", 0), 1),
                   "read_bw_kib": round(j["read"].get("bw", 0), 1),
                   "write_bw_kib": round(j["write"].get("bw", 0), 1)}
            for mode in ("read", "write"):
                pct = j[mode].get("clat_ns", {}).get("percentile", {})
                res[mode + "_clat_p99_us"] = round(pct.get("99.000000", 0) / 1000.0, 1)
            out[k] = res
        except (ValueError, KeyError, TypeError):
            out[k] = None
    return out


def run_probes(round_name, seconds=10):
    cmds = []
    for mode in ("http", "redis"):
        cmds.append("python3 /home/debian/probe.py --mode %s --host %s --rate 100 "
                    "--duration %d --tag disk-%s-%s --raw /home/debian/disk_%s_%s.raw" %
                    (mode, SVC[mode], seconds, round_name, mode, round_name, mode))
    out = vm_cmd_safe(PROBE_VM, " ; ".join(cmds), timeout=2 * seconds + 120)
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


def summarize(stats):
    if not stats:
        return None
    return {k: stats.get(k) for k in ("p50_ms", "p99_ms", "p999_ms", "max_ms", "timeouts")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=["baseline", "capped", "weighted"])
    ap.add_argument("--round", required=True)
    ap.add_argument("--riops", type=int, default=300)
    ap.add_argument("--wiops", type=int, default=150)
    args = ap.parse_args()

    if args.mode == "baseline":
        for vmid in NEIGHBOR_VMID.values():
            set_iomax(vmid, None, None)
            set_ioweight(vmid, 100)
    elif args.mode == "capped":
        for vmid in NEIGHBOR_VMID.values():
            set_iomax(vmid, args.riops, args.wiops)
    else:
        for k, vmid in NEIGHBOR_VMID.items():
            set_iomax(vmid, None, None)
            set_ioweight(vmid, 50 if k <= 5 else 500)

    path = "/root/disk_%s.jsonl" % args.round
    sink = open(path, "a", encoding="utf-8")
    try:
        stop_fio()
        time.sleep(3)
        ds0 = diskstats()
        io0 = {k: iostat_scope(v) for k, v in NEIGHBOR_VMID.items()}
        t0 = time.time()
        start_fio(args.round)
        time.sleep(12)
        http, redis = run_probes(args.round)
        # wait for fio to finish (start loop + runtime) plus a margin
        while time.time() - t0 < FIO_RUNTIME + 35:
            time.sleep(5)
        dt = time.time() - t0
        ds1 = diskstats()
        io1 = {k: iostat_scope(v) for k, v in NEIGHBOR_VMID.items()}

        per_vm_io = {}
        for k in NEIGHBOR_VMID:
            a, b = io0.get(k, {}), io1.get(k, {})
            if b:
                per_vm_io[k] = {
                    "rios": b.get("rios", 0) - a.get("rios", 0),
                    "wios": b.get("wios", 0) - a.get("wios", 0),
                    "rbytes": b.get("rbytes", 0) - a.get("rbytes", 0),
                    "wbytes": b.get("wbytes", 0) - a.get("wbytes", 0),
                }
        host = {
            "iops": round(((ds1["reads"] - ds0["reads"]) + (ds1["writes"] - ds0["writes"])) / dt, 0),
            "mbps": round((((ds1["rsec"] - ds0["rsec"]) + (ds1["wsec"] - ds0["wsec"])) * 512.0)
                          / (dt * 1e6), 1),
            "seconds": round(dt, 1),
        }
        rec = {"round": args.round, "mode": args.mode, "host": host,
               "fio": collect_fio(args.round), "per_vm_io": per_vm_io,
               "http": summarize(http), "redis": summarize(redis)}
        sink.write(json.dumps(rec) + "\n")
        sink.flush()
        print("MODE %s: host_iops=%s host_mbps=%s http_p99=%s redis_p99=%s" % (
            args.mode, host["iops"], host["mbps"],
            (http or {}).get("p99_ms"), (redis or {}).get("p99_ms")), flush=True)
        for k in sorted(rec["fio"]):
            f = rec["fio"][k]
            if f:
                print("  vm%d: read=%.0f write=%.0f iops (p99 %.0f/%.0f us)" % (
                    k, f["read_iops"], f["write_iops"],
                    f.get("read_clat_p99_us", 0), f.get("write_clat_p99_us", 0)), flush=True)
    finally:
        stop_fio()
        sink.close()
        print("DISKPHASE %s DONE" % args.round, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
