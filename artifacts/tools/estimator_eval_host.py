#!/usr/bin/env python3
"""Estimator characterization (P0-1, host-side).

Goal: characterize the throttle-corrected demand estimator as an *empirical*
estimator (not a guaranteed bound) across workload patterns, quotas, quota
periods and vCPU counts, and compare it against (a) naive usage, (b) windowed
variants, (c) the saturated-demand rule, and (d) a direct relaxation probe.

Per cell (pattern x quota x period) with N VMs (default 111-115, 1 vCPU):
  1. passive phase: quota active; sample cpu.stat every 1 s for 60 s; per-VM
     per-window (u_i, t_i) series (kept in the record for re-analysis).
  2. probe phase: each VM in turn gets quota=max for 2 s; the usage delta is a
     direct instantaneous demand sample (staggered, one VM at a time).
  3. truth phase: quota=max; for saturated demand sequentially (avoid host
     contention); for intermittent patterns all at once over a full period
     window (62 s, or 122 s for random/jit patterns).

Multi-vCPU cells (--vmids 116-120 --vcpus 2) use sat2p/duty2p patterns that
start two burner processes per VM; the cap in all estimators becomes vCPUs.

Estimators (computed from the passive windows; capped at vCPUs):
  naive    = mean(u)
  agg      = mean(u) / (1 - mean(t))          (the current paper formula)
  win95    = p95 of per-window u_i/(1-t_i)
  winmax   = max of per-window u_i/(1-t_i)
  sat      = vCPUs if any throttling else mean(u)   (method_eval "aware" rule)
  probe    = usage observed during the 2 s relaxation probe

Records one line per VM per cell -> /root/estimator_<round>.jsonl
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time

KEY = "/root/.ssh/sci2_key"
SSH_BASE = ["-n", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10",
            "-o", "LogLevel=ERROR"]
BURN_FILE = "/tmp/burn_rate.txt"
FIO_CMD = ("fio --name=io --filename=/tmp/fio_io --size=128M --rw=randrw "
           "--rwmixread=70 --bs=4k --direct=1 --iodepth=1 --ioengine=libaio "
           "--runtime=3600 --time_based --rate_iops=300 --output=/tmp/fio_io.out")

# pattern -> (burner args, truth style, processes per VM)
PATTERNS = {
    "saturated": ("", "seq", 1),
    "duty33": ("--duty 0.33 --period 60", "simul62", 1),
    "rand33": ("--duty 0.33 --period 60 --randphase", "simul122", 1),
    "jit": ("--period 60 --jit 0.1,0.5,1.0", "simul122", 1),
    "iowait": ("FIO", "simul62", 1),
    "sat2p": ("", "seq", 2),
    "duty2p": ("--duty 0.5 --period 60 --randphase", "simul122", 2),
}
# (pattern, quota in cores, quota period ms)
CELLS = [
    ("saturated", 0.4, 100), ("duty33", 0.4, 100), ("rand33", 0.4, 100),
    ("jit", 0.4, 100), ("iowait", 0.4, 100),
    ("saturated", 0.2, 100), ("saturated", 0.6, 100),
    ("saturated", 0.4, 50), ("saturated", 0.4, 250),
]
CELLS_2P = [("sat2p", 0.8, 100), ("sat2p", 1.2, 100), ("duty2p", 0.8, 100)]


def sh_local(cmd, timeout=30):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout).stdout


def vm_cmd(ip, cmd, timeout=90):
    res = subprocess.run(["ssh"] + SSH_BASE + ["debian@" + ip, cmd],
                         capture_output=True, text=True, timeout=timeout)
    return res.stdout


def vm_cmd_safe(ip, cmd, timeout=90):
    try:
        return vm_cmd(ip, cmd, timeout=timeout)
    except subprocess.TimeoutExpired:
        return ""


def ip_of(vmid):
    return "10.10.10.%d" % (vmid - 90)


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


def start_workload(ip, pattern):
    args, _, procs = PATTERNS[pattern]
    if args == "FIO":
        vm_cmd_safe(ip, "pkill -f '^fio ' 2>/dev/null; rm -f /tmp/fio_io*; "
                        "nohup %s >/dev/null 2>&1 & echo ok" % FIO_CMD, timeout=40)
        return
    vm_cmd_safe(ip,
                'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; '
                'rm -f /tmp/burn_rate*.txt; true', timeout=40)
    for i in range(procs):
        path = BURN_FILE if i == 0 else "/tmp/burn_rate_%d.txt" % i
        vm_cmd_safe(ip,
                    'nohup python3 /home/debian/burner.py %s 3600 %s >/dev/null 2>&1 & echo ok'
                    % (path, args), timeout=40)


def stop_workloads(vmids):
    for vmid in vmids:
        vm_cmd_safe(ip_of(vmid),
                    'pkill -9 -f "^python3 /home/debian/burner.py" 2>/dev/null; '
                    'pkill -9 -f "^fio " 2>/dev/null; true', timeout=40)


def burn_rate(ip):
    out = vm_cmd_safe(ip, "cat /tmp/burn_rate.txt /tmp/burn_rate_1.txt 2>/dev/null", timeout=40)
    rates = []
    for line in out.splitlines():
        try:
            rates.append(float(line.split()[0]))
        except (IndexError, ValueError):
            pass
    return round(sum(rates), 1) if rates else None


def usage_cores(a, b, dt):
    return (b.get("usage_usec", 0) - a.get("usage_usec", 0)) / (dt * 1e6)


def throttled_frac(a, b, dt):
    return (b.get("throttled_usec", 0) - a.get("throttled_usec", 0)) / (dt * 1e6)


def est_from_windows(u, t, vcpus=1):
    """Pure estimator math (importable for offline unit tests)."""
    n = max(1, len(u))
    mean_u = sum(u) / n
    mean_t = sum(t) / n
    caps = float(vcpus)

    def perwin(ui, ti):
        d = ui / (1.0 - ti) if ti > 0.01 else ui
        return min(caps, d)

    win = sorted(perwin(a, b) for a, b in zip(u, t))
    return {
        "mean_u": round(mean_u, 4),
        "mean_t": round(mean_t, 4),
        "max_t": round(max(t), 4) if t else 0.0,
        "est_naive": round(mean_u, 4),
        "est_agg": round(min(caps, mean_u / max(1e-6, 1.0 - mean_t)), 4),
        "est_win95": round(win[int(0.95 * (n - 1))], 4),
        "est_winmax": round(win[-1], 4),
        "est_sat": round(caps if (t and max(t) > 0.01) else mean_u, 4),
    }


def passive_phase(vmids, seconds=60):
    series = {v: {"u": [], "t": []} for v in vmids}
    prev = {v: cpu_stat(v) for v in vmids}
    t_prev = time.time()
    while time.time() - t_prev < seconds:
        time.sleep(1.0)
        now = time.time()
        dt = max(0.5, now - t_prev)
        for v in vmids:
            cur = cpu_stat(v)
            series[v]["u"].append(usage_cores(prev[v], cur, dt))
            series[v]["t"].append(throttled_frac(prev[v], cur, dt))
            prev[v] = cur
        t_prev = now
    return series


def probe_phase(vmids, spec, probe_seconds=2.0):
    out = {}
    for vmid in vmids:
        set_quota(vmid, "max 100000")
        time.sleep(0.3)
        a = cpu_stat(vmid)
        t0 = time.time()
        time.sleep(probe_seconds)
        b = cpu_stat(vmid)
        dt = max(0.5, time.time() - t0)
        out[vmid] = round(usage_cores(a, b, dt), 4)
        set_quota(vmid, spec)
        time.sleep(2.0)
    return out


def truth_phase(vmids, spec, pattern):
    style = PATTERNS[pattern][1]
    truth = {}
    if style == "seq":
        for vmid in vmids:
            set_quota(vmid, "max 100000")
            time.sleep(4)
            a = cpu_stat(vmid)
            t0 = time.time()
            time.sleep(8)
            b = cpu_stat(vmid)
            dt = max(1.0, time.time() - t0)
            truth[vmid] = round(usage_cores(a, b, dt), 4)
            set_quota(vmid, spec)
            time.sleep(2)
    else:
        win = 122.0 if style == "simul122" else 62.0
        for vmid in vmids:
            set_quota(vmid, "max 100000")
        time.sleep(4)
        a = {v: cpu_stat(v) for v in vmids}
        t0 = time.time()
        time.sleep(win)
        b = {v: cpu_stat(v) for v in vmids}
        dt = max(1.0, time.time() - t0)
        for vmid in vmids:
            truth[vmid] = round(usage_cores(a[vmid], b[vmid], dt), 4)
        for vmid in vmids:
            set_quota(vmid, spec)
    return truth


def run_cell(args, sink, vmids, pattern, quota_cores, period_ms):
    period_us = period_ms * 1000
    quota_us = int(quota_cores * period_us)
    spec = "%d %d" % (quota_us, period_us)
    stop_workloads(vmids)
    for vmid in vmids:
        set_quota(vmid, spec)
    for vmid in vmids:
        start_workload(ip_of(vmid), pattern)
    time.sleep(10)

    series = passive_phase(vmids)
    rates_quota = {v: burn_rate(ip_of(v)) for v in vmids}
    probes = probe_phase(vmids, spec)
    truth = truth_phase(vmids, spec, pattern)
    rates_truth = {v: burn_rate(ip_of(v)) for v in vmids}
    stop_workloads(vmids)

    summary = []
    for vmid in vmids:
        est = est_from_windows(series[vmid]["u"], series[vmid]["t"], vcpus=args.vcpus)
        rec = {"round": args.round, "pattern": pattern, "quota_cores": float(quota_cores),
               "period_ms": period_ms, "vm": vmid, "vcpus": args.vcpus,
               "windows": {"u": [round(x, 4) for x in series[vmid]["u"]],
                           "t": [round(x, 4) for x in series[vmid]["t"]]},
               "estimates": est, "probe": probes[vmid], "truth": truth[vmid],
               "rate_quota": rates_quota[vmid], "rate_truth": rates_truth[vmid]}
        sink.write(json.dumps(rec) + "\n")
        sink.flush()
        summary.append((est["est_agg"], probes[vmid], truth[vmid], est["est_naive"]))
    m = lambda i: sum(s[i] for s in summary) / len(summary)
    print("cell %-9s q=%.2f p=%3d ms | naive=%.3f agg=%.3f probe=%.3f truth=%.3f" %
          (pattern, float(quota_cores), period_ms, m(3), m(0), m(1), m(2)), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", required=True)
    ap.add_argument("--vmids", default="111,112,113,114,115")
    ap.add_argument("--vcpus", type=int, default=1)
    ap.add_argument("--cells", default=None,
                    help="optional subset: 'pattern:quota_cores:period_ms,...'")
    args = ap.parse_args()
    vmids = [int(x) for x in args.vmids.split(",")]

    cells = CELLS if args.vcpus == 1 else CELLS_2P
    if args.cells:
        cells = []
        for spec in args.cells.split(","):
            p, q, per = spec.split(":")
            cells.append((p, float(q), int(per)))

    sink = open("/root/estimator_%s.jsonl" % args.round, "a", encoding="utf-8")
    try:
        for pattern, quota_cores, period_ms in cells:
            run_cell(args, sink, vmids, pattern, quota_cores, period_ms)
    finally:
        stop_workloads(vmids)
        for vmid in vmids:
            set_quota(vmid, "max 100000")
        sink.close()
        print("ESTIMATOR %s DONE" % args.round, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
