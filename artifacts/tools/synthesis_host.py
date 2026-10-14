#!/usr/bin/env python3
"""Final synthesis validation (runs ON the PVE test host).

Plan under test: "sell 4 vCPU / ~20 GiB as 16 vCPU / ~48 GiB / shared disk":
  - 16 customer VMs (1 vCPU, 3072 MiB each), services+probe pinned to cores 0-1,
    customers pinned to cores 2-3 (economy tier shares two cores)
  - customer memory: memory.high = 800 MiB, memory.swap.max = 0
  - customer io: io.max = 8:0 riops=200 wiops=100
Workload (all three resource dimensions at once):
  - CPU: 8x idleR + 6x idleR/burstyR mix + 2x pegged  (see CLASSES below)
  - memory: ballast 600 MiB in every customer
  - disk: fio 4k randrw 70/30, 40 s, O_DIRECT, in every customer
Services (svc-http, svc-redis) are probed (60 s each) during the storm.

Record appended to /root/synthesis_<round>.jsonl; summary printed.
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
INFRA_VMIDS = [101, 102, 110]
CUSTOMER_VMIDS = list(range(111, 127))
CUSTOMER_IP = {k: "10.10.10.%d" % (20 + k) for k in range(1, 17)}
DEV = "8:0"
MEM_HIGH_MB = 800
MEM_SWAP_MAX = 0
IO_R = 200
IO_W = 100
FIO_RUNTIME = 40
SSH_BASE = ["-n", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10",
            "-o", "LogLevel=ERROR"]

CLASSES = {1: "idleR", 2: "idleR", 3: "idleR", 4: "idleR", 5: "idleR", 6: "idleR",
           7: "idleR", 8: "idleR", 9: "burstyR", 10: "burstyR", 11: "burstyR",
           12: "burstyR", 13: "pegged", 14: "pegged", 15: "idleR", 16: "idleR"}
CLASS_ARGS = {
    "pegged": "",
    "burstyR": "--duty 0.33 --period 60 --randphase",
    "idleR": "--duty 0.10 --period 60 --randphase",
}


def sh_local(cmd, timeout=30):
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return res.stdout


def vm_cmd(ip, cmd, timeout=150):
    res = subprocess.run(["ssh"] + SSH_BASE + ["debian@" + ip, cmd],
                         capture_output=True, text=True, timeout=timeout)
    return res.stdout


def vm_cmd_safe(ip, cmd, timeout=90):
    try:
        return vm_cmd(ip, cmd, timeout=timeout)
    except subprocess.TimeoutExpired:
        return ""


def set_affinity(vmid, mask):
    sh_local('pid=$(cat /run/qemu-server/%d.pid); taskset -apc %s $pid >/dev/null 2>&1' % (vmid, mask))


def set_mem_controls(vmid, high_mb, swap_max):
    hi = "max" if high_mb is None else str(high_mb * 1024 * 1024)
    sw = "max" if swap_max is None else str(swap_max)
    sh_local('echo "%s" > /sys/fs/cgroup/qemu.slice/%d.scope/memory.high' % (hi, vmid))
    sh_local('echo "%s" > /sys/fs/cgroup/qemu.slice/%d.scope/memory.swap.max' % (sw, vmid))


def set_iomax(vmid, riops, wiops):
    spec = ("%s rbps=max wbps=max riops=max wiops=max" % DEV) if riops is None else \
           ("%s rbps=max wbps=max riops=%d wiops=%d" % (DEV, riops, wiops))
    sh_local('echo "%s" > /sys/fs/cgroup/qemu.slice/%d.scope/io.max' % (spec, vmid))


def start_burner(k, cls):
    vm_cmd_safe(CUSTOMER_IP[k],
                'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; rm -f /tmp/burn_rate.txt; '
                'nohup python3 /home/debian/burner.py /tmp/burn_rate.txt 3600 %s >/dev/null 2>&1 & echo ok'
                % CLASS_ARGS[cls], timeout=40)


def start_ballast(k):
    vm_cmd_safe(CUSTOMER_IP[k],
                'pkill -f "^python3 /home/debian/ballast.py" 2>/dev/null; '
                'nohup python3 /home/debian/ballast.py /tmp/ballast_s.txt --target-mb 600 --step-mb 100 '
                '>/dev/null 2>&1 & echo ok', timeout=40)


def start_fio(round_name, k):
    vm_cmd_safe(CUSTOMER_IP[k],
                'pkill -f "^fio " 2>/dev/null; nohup fio --name=job --directory=/home/debian/fio-test '
                '--size=256M --rw=randrw --rwmixread=70 --bs=4k --iodepth=16 --numjobs=2 --direct=1 '
                '--time_based --runtime=%d --group_reporting --output-format=json '
                '--output=/tmp/fio_s_%s_%d.json >/dev/null 2>&1 & echo ok' % (FIO_RUNTIME, round_name, k),
                timeout=45)


def stop_workloads():
    for k in CUSTOMER_IP:
        vm_cmd_safe(CUSTOMER_IP[k],
                    "pkill -f '^python3 /home/debian/burner.py' 2>/dev/null; "
                    "pkill -f '^python3 /home/debian/ballast.py' 2>/dev/null; "
                    "pkill -f '^fio ' 2>/dev/null; true", timeout=45)


def sample_busy():
    res = subprocess.run(["/tmp/busy3.sh"], capture_output=True, text=True, timeout=30)
    for line in res.stdout.splitlines():
        if "host_busy_pct=" in line:
            return float(line.split("=", 1)[1])
    return None


def host_mem():
    info = {}
    for line in open("/proc/meminfo"):
        p = line.split()
        if p[0] in ("MemAvailable:", "SwapFree:"):
            info[p[0][:-1]] = int(p[1]) // 1024
    return info


def diskstats():
    for line in open("/proc/diskstats"):
        f = line.split()
        if len(f) > 13 and f[2] == "sda1":
            return {"reads": int(f[3]), "rsec": int(f[5]), "writes": int(f[7]), "wsec": int(f[9])}
    return {}


def iostat_scope(vmid):
    try:
        with open("/sys/fs/cgroup/qemu.slice/%d.scope/io.stat" % vmid) as fh:
            for line in fh:
                parts = line.split()
                if parts[0] == DEV:
                    return {k: int(v) for k, v in (p.split("=") for p in parts[1:])}
    except (OSError, ValueError):
        pass
    return {}


def status(k):
    out = vm_cmd_safe(CUSTOMER_IP[k], "cat /tmp/burn_rate.txt 2>/dev/null", timeout=15)
    parts = out.strip().split()
    if len(parts) == 2:
        try:
            return {"rate": float(parts[0]), "state": int(parts[1])}
        except ValueError:
            pass
    return None


def run_probes(round_name, seconds):
    cmds = []
    for mode in ("http", "redis"):
        cmds.append("python3 /home/debian/probe.py --mode %s --host %s --rate 100 "
                    "--duration %d --tag syn-%s-%s --raw /home/debian/syn_%s_%s.raw" %
                    (mode, SVC[mode], seconds, round_name, mode, round_name, mode))
    out = vm_cmd_safe(PROBE_VM, " ; ".join(cmds), timeout=2 * seconds + 150)
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


def collect_fio(round_name):
    out = {}
    for k in CUSTOMER_IP:
        txt = vm_cmd_safe(CUSTOMER_IP[k], "cat /tmp/fio_s_%s_%d.json 2>/dev/null" % (round_name, k),
                          timeout=15)
        try:
            j = json.loads(txt)["jobs"][0]
            out[k] = {"read_iops": round(j["read"].get("iops", 0), 1),
                      "write_iops": round(j["write"].get("iops", 0), 1)}
        except (ValueError, KeyError, TypeError):
            out[k] = None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", required=True)
    ap.add_argument("--probe-seconds", type=float, default=60.0)
    args = ap.parse_args()

    path = "/root/synthesis_%s.jsonl" % args.round
    sink = open(path, "a", encoding="utf-8")
    try:
        # ---- plan controls ----
        for vmid in INFRA_VMIDS:
            set_affinity(vmid, "0,1")
        swap_files = 0
        for vmid in CUSTOMER_VMIDS:
            set_affinity(vmid, "2,3")
            if os.path.exists("/sys/fs/cgroup/qemu.slice/%d.scope/memory.swap.max" % vmid):
                swap_files += 1
            set_mem_controls(vmid, MEM_HIGH_MB, MEM_SWAP_MAX)
            set_iomax(vmid, IO_R, IO_W)
        print("controls set; swap.max files present=%d" % swap_files, flush=True)

        stop_workloads()
        time.sleep(3)

        # ---- stage A: CPU + memory ----
        for k, cls in CLASSES.items():
            start_burner(k, cls)
            start_ballast(k)
        time.sleep(25)
        busy = sample_busy()
        mem = host_mem()
        states = {k: status(k) for k in CUSTOMER_IP}
        print("stage A: busy=%s avail=%sMB swapfree=%sMB" %
              (busy, mem.get("MemAvailable"), mem.get("SwapFree")), flush=True)

        # ---- stage B: + disk storm, probe services ----
        ds0 = diskstats()
        io0 = {v: iostat_scope(v) for v in CUSTOMER_VMIDS}
        t_io0 = time.time()
        for k in CUSTOMER_IP:
            start_fio(args.round, k)
        time.sleep(12)
        http, redis = run_probes(args.round, args.probe_seconds)
        for _ in range(24):  # wait for fio to finish (bounded)
            time.sleep(5)
            out = vm_cmd_safe(CUSTOMER_IP[1], "pgrep -f '^fio ' >/dev/null && echo RUN || echo IDLE",
                              timeout=30)
            if "IDLE" in out:
                break
        ds1 = diskstats()
        dt_io = max(1.0, time.time() - t_io0)
        io1 = {v: iostat_scope(v) for v in CUSTOMER_VMIDS}
        busy2 = sample_busy()
        mem2 = host_mem()
        fio = collect_fio(args.round)

        host = {
            "iops": round(((ds1["reads"] - ds0["reads"]) + (ds1["writes"] - ds0["writes"])) / dt_io, 0),
            "mbps": round((((ds1["rsec"] - ds0["rsec"]) + (ds1["wsec"] - ds0["wsec"])) * 512.0)
                          / (dt_io * 1e6), 1),
            "seconds": round(dt_io, 1),
        }
        per_vm_io = {str(v): {"rios": io1[v].get("rios", 0) - io0[v].get("rios", 0),
                              "wios": io1[v].get("wios", 0) - io0[v].get("wios", 0)}
                     for v in CUSTOMER_VMIDS if io1[v]}
        def sm(s):
            return None if not s else {k: s.get(k) for k in ("p50_ms", "p99_ms", "p999_ms", "timeouts")}
        rec = {"round": args.round, "busy_a": busy, "busy_b": busy2,
               "mem_a": mem, "mem_b": mem2, "states": states, "host_io": host,
               "fio": fio, "per_vm_io": per_vm_io,
               "http": sm(http), "redis": sm(redis)}
        sink.write(json.dumps(rec, ensure_ascii=False) + "\n")
        sink.flush()
        print("SYNTHESIS: http p99=%s redis p99=%s | host_io iops=%s mbps=%s | avail=%sMB swapfree=%sMB" % (
            (http or {}).get("p99_ms"), (redis or {}).get("p99_ms"),
            host["iops"], host["mbps"], mem2.get("MemAvailable"), mem2.get("SwapFree")), flush=True)
        alive = [k for k in CUSTOMER_IP if states.get(k)]
        print("customer states recorded: %d/16" % len(alive), flush=True)
    finally:
        stop_workloads()
        for vmid in CUSTOMER_VMIDS:
            set_mem_controls(vmid, None, None)
            set_iomax(vmid, None, None)
            set_affinity(vmid, "0-3")
        for vmid in INFRA_VMIDS:
            set_affinity(vmid, "0-3")
        sink.close()
        print("SYNTHESIS %s DONE" % args.round, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
