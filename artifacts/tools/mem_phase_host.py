#!/usr/bin/env python3
"""Memory oversubscription pilot (runs ON the PVE test host).

The 10 customer VMs are configured with 5 GiB each (50 GiB "sold" on ~20 GiB
physical, the 2.5x plan). Ballast runs inside the customers; host-side memory
(current per VM, MemAvailable, swap) and service latency are sampled after each
bounded "wave" (WAVE_MB added per VM).

Modes:
  grow    no per-VM cap: grow until the MemAvailable guard trips (dry-up point)
  capped  memory.high=HIGH_MB per customer cgroup: same growth, expect per-VM
          host memory to plateau at the cap while services stay healthy

One JSON record per wave is appended to /root/memphase_<round>.jsonl.
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
WAVE_MB = 200
GUARD_MB = 800
START_GUARD_MB = 1500
HIGH_MB = 800
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


def host_mem():
    info = {}
    for line in open("/proc/meminfo"):
        parts = line.split()
        if parts[0] in ("MemTotal:", "MemAvailable:", "SwapFree:", "SwapTotal:"):
            info[parts[0][:-1]] = int(parts[1])
    cur = {}
    for k, vmid in NEIGHBOR_VMID.items():
        try:
            with open("/sys/fs/cgroup/qemu.slice/%d.scope/memory.current" % vmid) as fh:
                cur[k] = int(fh.read().strip()) // (1024 * 1024)
        except OSError:
            cur[k] = None
    info["guest_current_mb"] = cur
    return info


def guest_events(vmid):
    try:
        with open("/sys/fs/cgroup/qemu.slice/%d.scope/memory.events" % vmid) as fh:
            ev = {}
            for line in fh:
                name, val = line.split()
                ev[name] = int(val)
            return ev
    except OSError:
        return {}


def set_high(vmid, value_mb):
    val = "max" if value_mb is None else str(value_mb * 1024 * 1024)
    sh_local('echo "%s" > /sys/fs/cgroup/qemu.slice/%d.scope/memory.high' % (val, vmid))


def vm_cmd_safe(ip, cmd, timeout=90):
    try:
        return vm_cmd(ip, cmd, timeout=timeout)
    except subprocess.TimeoutExpired:
        return ""


def responsive():
    bad = []
    for k, ip in NEIGHBOR_IP.items():
        try:
            out = vm_cmd(ip, "echo OK", timeout=25)
            if "OK" not in out:
                bad.append(k)
        except subprocess.TimeoutExpired:
            bad.append(k)
    return bad


def start_wave(k):
    for i in NEIGHBOR_IP:
        vm_cmd_safe(NEIGHBOR_IP[i],
                    'nohup python3 /home/debian/ballast.py /tmp/ballast_w%d.txt --target-mb %d '
                    '--step-mb 50 >/dev/null 2>&1 & echo ok' % (k, WAVE_MB),
                    timeout=90)


def stop_all():
    for i in NEIGHBOR_IP:
        vm_cmd_safe(NEIGHBOR_IP[i], 'pkill -f "^python3 /home/debian/ballast.py" 2>/dev/null; true',
                    timeout=45)


def ballast_state(k):
    out = vm_cmd(NEIGHBOR_IP[k], "cat /tmp/ballast_w%s.txt 2>/dev/null" % k, timeout=30)
    return out.strip() or None


def run_probes(round_name, wave, seconds=10):
    cmds = []
    for mode in ("http", "redis"):
        cmds.append("python3 /home/debian/probe.py --mode %s --host %s --rate 100 "
                    "--duration %d --tag mem-%s-w%d-%s --raw /home/debian/mem_%s_w%d_%s.raw" %
                    (mode, SVC[mode], seconds, round_name, wave, mode,
                     round_name, wave, mode))
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


def summarize(stats):
    if not stats:
        return None
    return {k: stats.get(k) for k in ("p50_ms", "p99_ms", "p999_ms", "max_ms",
                                      "timeouts", "schedule_lag_p99_ms")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=["grow", "capped"])
    ap.add_argument("--round", required=True)
    ap.add_argument("--waves", type=int, default=6)
    ap.add_argument("--settle", type=float, default=25.0)
    args = ap.parse_args()

    path = "/root/memphase_%s.jsonl" % args.round
    sink = open(path, "a", encoding="utf-8")
    try:
        if args.mode == "capped":
            for vmid in NEIGHBOR_VMID.values():
                set_high(vmid, HIGH_MB)
        else:
            for vmid in NEIGHBOR_VMID.values():
                set_high(vmid, None)
        stop_all()
        time.sleep(3)

        wave = 0
        while wave < args.waves:
            mem_pre = host_mem()
            if mem_pre["MemAvailable"] < START_GUARD_MB * 1024:
                print("stop early: MemAvailable=%d MB < start guard" %
                      (mem_pre["MemAvailable"] // 1024), flush=True)
                break
            wave += 1
            t0 = time.time()
            start_wave(wave)
            time.sleep(args.settle)
            mem = host_mem()
            http, redis = run_probes(args.round, wave)
            rec = {
                "round": args.round, "mode": args.mode, "wave": wave,
                "wave_seconds": round(time.time() - t0, 1),
                "mem_available_mb": mem["MemAvailable"] // 1024,
                "swap_free_mb": mem["SwapFree"] // 1024,
                "guest_current_mb": mem["guest_current_mb"],
                "guest_total_mb": sum(v or 0 for v in mem["guest_current_mb"].values()),
                "http": summarize(http), "redis": summarize(redis),
            }
            if args.mode == "capped":
                rec["events"] = {str(k): guest_events(v) for k, v in NEIGHBOR_VMID.items()}
            bad = responsive()
            rec["unresponsive"] = bad
            sink.write(json.dumps(rec) + "\n")
            sink.flush()
            print("wave %d: guest_total=%d MB avail=%d MB swapfree=%d MB http_p99=%s redis_p99=%s" % (
                wave, rec["guest_total_mb"], rec["mem_available_mb"], rec["swap_free_mb"],
                (http or {}).get("p99_ms"), (redis or {}).get("p99_ms")), flush=True)
            if bad:
                print("BREAK: unresponsive guests %s" % bad, flush=True)
                break
            if mem["MemAvailable"] < GUARD_MB * 1024:
                print("GUARD TRIP at wave %d: MemAvailable=%d MB" %
                      (wave, mem["MemAvailable"] // 1024), flush=True)
                break

        time.sleep(10)
        mem = host_mem()
        print("final: avail=%d MB swap_free=%d MB guest_total=%d MB" %
              (mem["MemAvailable"] // 1024, mem["SwapFree"] // 1024,
               sum(v or 0 for v in mem["guest_current_mb"].values())), flush=True)
    finally:
        stop_all()
        for vmid in NEIGHBOR_VMID.values():
            set_high(vmid, None)
        sink.close()
        print("MEMPHASE %s DONE" % args.round, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
