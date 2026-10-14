#!/usr/bin/env python3
"""Censoring experiment (runs ON the PVE test host).

Core hypothesis: CPU usage observed under a quota understates true demand
(a throttled VM looks "small" on a usage dashboard). Decisions based on that
naive estimate (e.g. trusting the phantom spare capacity and lifting limits)
blow up under the real demand; throttle-counter-based (censoring-aware)
estimation sees the true demand boundary.

Cycle protocol:
  1. quota phase: 5 customer VMs run steady burners, each capped at 50% CPU.
     Measure per-VM host-side cpu.stat deltas: usage cores (naive demand) and
     throttled_usec (censoring evidence). Probe services (expect healthy).
     naive_sum vs aware_sum (throttled VMs -> at least their full vCPU).
  2. released phase: quotas removed (the "trust usage" decision). Re-probe:
     the released demand (5 burned cores on 4 cores) degrades the services.
  3. restore quotas, stop burners.

One JSON record per cycle -> /root/censor_<round>.jsonl
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
OTHER_VMIDS = list(range(116, 127))
QUOTA = "50000 100000"
SSH_BASE = ["-n", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10",
            "-o", "LogLevel=ERROR"]


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


def set_quota(vmid, spec):
    sh_local('echo "%s" > /sys/fs/cgroup/qemu.slice/%d.scope/cpu.max' % (spec, vmid))


def cpu_stat(vmid):
    d = {}
    try:
        with open("/sys/fs/cgroup/qemu.slice/%d.scope/cpu.stat" % vmid) as fh:
            for line in fh:
                k, v = line.split()
                d[k] = int(v)
    except (OSError, ValueError):
        pass
    return d


def start_burner(k):
    vm_cmd_safe(CUST_IP[k],
                'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; rm -f /tmp/burn_rate.txt; '
                'nohup python3 /home/debian/burner.py /tmp/burn_rate.txt 3600 >/dev/null 2>&1 & echo ok',
                timeout=40)


def stop_burners():
    for k in range(1, 17):
        vm_cmd_safe("10.10.10.%d" % (20 + k),
                    'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; true', timeout=40)


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


def run_probes(round_name, phase, seconds=30):
    cmds = []
    for mode in ("http", "redis"):
        cmds.append("python3 /home/debian/probe.py --mode %s --host %s --rate 100 "
                    "--duration %d --tag cen-%s-%s-%s --raw /home/debian/cen_%s_%s_%s.raw" %
                    (mode, SVC[mode], seconds, round_name, phase, mode, round_name, phase, mode))
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
    return {k: stats.get(k) for k in ("p50_ms", "p99_ms", "p999_ms", "timeouts")}


def one_cycle(args, i):
    quota = "%d 100000" % (args.quota_pct * 1000)
    stop_burners()
    for k in CUST_K:
        set_quota(CUST_VMID[k], quota)
    for vmid in OTHER_VMIDS:
        set_quota(vmid, "max 100000")
    time.sleep(2)

    # ---- quota phase ----
    for k in CUST_K:
        start_burner(k)
    time.sleep(15)
    cs0 = {k: cpu_stat(CUST_VMID[k]) for k in CUST_K}
    t0 = time.time()
    busy1 = sample_busy()
    http1, redis1 = run_probes(args.round, "quota")
    dt = time.time() - t0
    cs1 = {k: cpu_stat(CUST_VMID[k]) for k in CUST_K}
    rates1 = {k: burn_rate(k) for k in CUST_K}

    per_vm = {}
    naive_sum = 0.0
    aware_sum = 0.0
    for k in CUST_K:
        a, b = cs0[k], cs1[k]
        usage_cores = (b.get("usage_usec", 0) - a.get("usage_usec", 0)) / (dt * 1e6)
        thr_cores = (b.get("throttled_usec", 0) - a.get("throttled_usec", 0)) / (dt * 1e6)
        thr_cnt = b.get("nr_throttled", 0) - a.get("nr_throttled", 0)
        est_aware = 1.0 if (thr_cnt > 0 or thr_cores > 0.01) else usage_cores
        per_vm[k] = {"usage_cores": round(usage_cores, 3), "throttled_frac": round(thr_cores, 3),
                     "nr_throttled": thr_cnt, "aware_est": round(est_aware, 3),
                     "rate": rates1[k]}
        naive_sum += usage_cores
        aware_sum += est_aware

    # ---- released phase (naive decision) ----
    for k in CUST_K:
        set_quota(CUST_VMID[k], "max 100000")
    time.sleep(15)
    busy2 = sample_busy()
    http2, redis2 = run_probes(args.round, "released")
    rates2 = {k: burn_rate(k) for k in CUST_K}

    # ---- restore ----
    for k in CUST_K:
        set_quota(CUST_VMID[k], quota)
    stop_burners()

    def viol(stats):
        return bool(stats and stats.get("p99_ms") is not None and stats["p99_ms"] > 10.0)
    vq = viol(http1) or viol(redis1)
    vr = viol(http2) or viol(redis2)
    rec = {"round": args.round, "cycle": i, "dt_s": round(dt, 1),
           "busy_quota": busy1, "busy_released": busy2,
           "naive_sum_cores": round(naive_sum, 2), "aware_sum_cores": round(aware_sum, 2),
           "per_vm": per_vm, "rates_released": rates2,
           "quota_phase": {"http": sm(http1), "redis": sm(redis1), "viol": vq},
           "released_phase": {"http": sm(http2), "redis": sm(redis2), "viol": vr}}
    sink = open("/root/censor_%s.jsonl" % args.round, "a", encoding="utf-8")
    sink.write(json.dumps(rec) + "\n")
    sink.close()
    print("cycle %d: naive=%.2f cores vs aware=%.2f cores (truth=5.00)" %
          (i, naive_sum, aware_sum), flush=True)
    print("  quota phase:    http p99=%s redis p99=%s | busy=%s | viol=%s" %
          ((http1 or {}).get("p99_ms"), (redis1 or {}).get("p99_ms"), busy1, vq), flush=True)
    print("  released phase: http p99=%s redis p99=%s | busy=%s | rates=%s | viol=%s" %
          ((http2 or {}).get("p99_ms"), (redis2 or {}).get("p99_ms"), busy2,
           [("%.0fM" % (v / 1e6)) if v else "?" for v in rates2.values()], vr), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", required=True)
    ap.add_argument("--cycles", type=int, default=2)
    ap.add_argument("--quota-pct", type=int, default=50)
    args = ap.parse_args()
    try:
        for i in range(1, args.cycles + 1):
            one_cycle(args, i)
    finally:
        for k in CUST_K:
            set_quota(CUST_VMID[k], "max 100000")
        stop_burners()
        print("CENSOR %s DONE" % args.round, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
