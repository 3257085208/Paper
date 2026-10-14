#!/usr/bin/env python3
"""Quota-pulse experiments (runs ON the PVE test host).

Five customers each effectively consume ~30% CPU on average. Compare how the
control mechanism shapes service tail latency:

  p100    cpu.max = 30000/100000  (default 100 ms period; reference)
  p1000   cpu.max = 300000/1000000 (1 s period)
  mixed   staggered periods 100/150/200/250/300 ms at 30% duty (phase diversity)
  weight  no caps; services cpu.weight=1000, customers cpu.weight=100
          (priority protection instead of hard caps)

Each mode: start steady burners (fixed version), settle, sample host busy and
burner rates, probe svc-http + svc-redis (30 s each), then clean up.
One JSON record per mode -> /root/quota_pulse_<round>.jsonl
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time

KEY = "/root/.ssh/sci2_key"
PROBE_VM = "10.10.10.20"
SVC = {"http": "10.10.10.11", "redis": "10.10.10.12"}
CUST_K = [1, 2, 3, 4, 5]
CUST_VMID = {k: 110 + k for k in CUST_K}
CUST_IP = {k: "10.10.10.%d" % (20 + k) for k in CUST_K}
SERVICE_VMIDS = [101, 102, 110]
ALL_VMIDS = SERVICE_VMIDS + list(CUST_VMID.values())
SLO = 10.0
SSH_BASE = ["-n", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10",
            "-o", "LogLevel=ERROR"]

MODE_SPECS = {
    "p100": [("30000", "100000")] * 5,
    "p1000": [("300000", "1000000")] * 5,
    "mixed": [("30000", "100000"), ("45000", "150000"), ("60000", "200000"),
              ("75000", "250000"), ("90000", "300000")],
}


def sh_local(cmd, timeout=30):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout).stdout


def vm_cmd(ip, cmd, timeout=120):
    res = subprocess.run(["ssh"] + SSH_BASE + ["debian@" + ip, cmd],
                         capture_output=True, text=True, timeout=timeout)
    return res.stdout


def vm_cmd_safe(ip, cmd, timeout=90):
    try:
        return vm_cmd(ip, cmd, timeout=timeout)
    except subprocess.TimeoutExpired:
        return ""


def set_cpumax(vmid, spec):
    if spec is None:
        sh_local('echo "max 100000" > /sys/fs/cgroup/qemu.slice/%d.scope/cpu.max' % vmid)
    else:
        sh_local('echo "%s %s" > /sys/fs/cgroup/qemu.slice/%d.scope/cpu.max' % (spec[0], spec[1], vmid))


def set_cpuweight(vmid, weight):
    sh_local('echo "%d" > /sys/fs/cgroup/qemu.slice/%d.scope/cpu.weight' % (weight, vmid))


def start_burner(k):
    vm_cmd_safe(CUST_IP[k],
                'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; rm -f /tmp/burn_rate.txt; '
                'nohup python3 /home/debian/burner.py /tmp/burn_rate.txt 3600 >/dev/null 2>&1 & echo ok',
                timeout=40)


def stop_burners():
    for k in range(1, 17):
        vm_cmd_safe("10.10.10.%d" % (20 + k),
                    'pkill -9 -f "^python3 /home/debian/burner.py" 2>/dev/null; true', timeout=40)


def burn_rate(k):
    out = vm_cmd_safe(CUST_IP[k], "cat /tmp/burn_rate.txt 2>/dev/null", timeout=40)
    try:
        return float(out.strip().split()[0])
    except (ValueError, IndexError):
        return None


def sample_busy():
    res = subprocess.run(["/tmp/busy3.sh"], capture_output=True, text=True, timeout=30)
    for line in res.stdout.splitlines():
        if "host_busy_pct=" in line:
            return float(line.split("=", 1)[1])
    return None


def run_probes(round_name, mode, seconds=30):
    cmds = []
    for svc in ("http", "redis"):
        cmds.append("python3 /home/debian/probe.py --mode %s --host %s --rate 100 "
                    "--duration %d --tag qp-%s-%s-%s --raw /home/debian/qp_%s_%s_%s.raw" %
                    (svc, SVC[svc], seconds, round_name, mode, svc, round_name, mode, svc))
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


def sm(stats):
    if not stats:
        return None
    return {k: stats.get(k) for k in ("p50_ms", "p99_ms", "p999_ms", "max_ms", "timeouts")}


def prep(mode):
    stop_burners()
    for vmid in ALL_VMIDS:
        set_cpumax(vmid, None)
        set_cpuweight(vmid, 100)
    if mode == "weight":
        for vmid in SERVICE_VMIDS:
            set_cpuweight(vmid, 1000)
        for vmid in CUST_VMID.values():
            set_cpuweight(vmid, 100)
    else:
        for k, spec in zip(CUST_K, MODE_SPECS[mode]):
            set_cpumax(CUST_VMID[k], spec)


def cleanup():
    stop_burners()
    for vmid in ALL_VMIDS:
        set_cpumax(vmid, None)
        set_cpuweight(vmid, 100)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", required=True)
    ap.add_argument("--modes", default="p1000,mixed,weight")
    ap.add_argument("--probe-seconds", type=float, default=30.0)
    args = ap.parse_args()
    sink = open("/root/quota_pulse_%s.jsonl" % args.round, "a", encoding="utf-8")
    try:
        for mode in args.modes.split(","):
            mode = mode.strip()
            print("===== %s / %s =====" % (args.round, mode), flush=True)
            prep(mode)
            for k in CUST_K:
                start_burner(k)
            time.sleep(15)
            busy = sample_busy()
            http, redis = run_probes(args.round, mode, args.probe_seconds)
            rates = {k: burn_rate(k) for k in CUST_K}
            rec = {"round": args.round, "mode": mode, "busy_pct": busy,
                   "rates": rates, "http": sm(http), "redis": sm(redis)}
            def viol(s):
                return bool(s and s.get("p99_ms") is not None and s["p99_ms"] > SLO)
            rec["viol"] = viol(http) or viol(redis)
            sink.write(json.dumps(rec) + "\n")
            sink.flush()
            print("  busy=%s rates=%s | http p99=%s redis p99=%s | viol=%s" %
                  (busy, [("%.0fM" % (v / 1e6)) if v else "?" for v in rates.values()],
                   (http or {}).get("p99_ms"), (redis or {}).get("p99_ms"), rec["viol"]),
                  flush=True)
    finally:
        cleanup()
        sink.close()
        print("QUOTA_PULSE %s DONE" % args.round, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
