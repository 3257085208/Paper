#!/usr/bin/env python3
"""Joint admission + shaping validation: four-policy fair comparison (host-side).

Protection envelope: services+probe pinned to cores 0-1; customers (111-120)
pinned to cores 2-3; background customers (k7-k10: 3 idleR + 1 burstyR, random
phase) run under the memory gate (memory.high, swap.max) and io caps. A
wakeup-stall monitor (stall.py) runs in background customer k7 as a
customer-side QoS canary.

Six candidates (k1-k6) arrive one at a time; each is shaped with cpu.max=50% and
runs a pegged workload (true demand 1.0, observed 0.5). Policies:
  naive    : est = background usage now + candidate observed usage + prior 0.5
  audible  : AUDIBLE-style per-VM usage distributions, MC convolution (bg +
             admitted), q99 of sum + 0.5 <= 1.6
  aware    : throttle evidence -> 1.0 per candidate; prior 1.0
  taligned : time-aligned admission. Background reserve = p90 of the measured
             per-second aggregate background demand over 240 s (phases
             preserved); candidates counted at their quota cap (consumption-side
             accounting, 0.5 each); candidate admitted while
             reserve + 0.5*(admitted+1) <= 0.95 * tenant cores, with a
             closed-loop canary guard (defer while canary max gap exceeds
             --canary-max-ms; resumes automatically once it clears).

A pre-roll (--preroll, default 75 s) gives the 1 s history sampler a full cycle
of the 60 s background pattern before the first candidate arrives.

Records per step to /root/joint_<round>.jsonl; summary per policy.
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import time

import talign

KEY = "/root/.ssh/sci2_key"
PROBE_VM = "10.10.10.20"
SVC = {"http": "10.10.10.11", "redis": "10.10.10.12"}
CAND_K = [1, 2, 3, 4, 5, 6]
BG_K = [7, 8, 9, 10]
BG_CLASSES = {7: "idleR", 8: "idleR", 9: "idleR", 10: "burstyR"}
CLASS_ARGS = {"idleR": "--duty 0.10 --period 60 --randphase",
              "burstyR": "--duty 0.33 --period 60 --randphase",
              "pegged": ""}
QUOTA = "50000 100000"
QUOTA_CORES = 0.5
TENANT_CORES = 2.0
BUDGET = 0.8 * TENANT_CORES
TALIGNED_CAP = 0.95 * TENANT_CORES
RESERVE_WINDOW = 240.0
RESERVE_Q = 90.0
SLO = 10.0
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


def ip_of(k):
    return "10.10.10.%d" % (20 + k)


def set_quota(vmid, spec):
    sh_local('echo "%s" > /sys/fs/cgroup/qemu.slice/%d.scope/cpu.max' % (spec, vmid))


def set_affinity(vmid, mask):
    sh_local('pid=$(cat /run/qemu-server/%d.pid); taskset -apc %s $pid >/dev/null 2>&1' % (vmid, mask))


def set_mem(vmid, high_mb, swap_max):
    hi = "max" if high_mb is None else str(high_mb * 1024 * 1024)
    sw = "max" if swap_max is None else str(swap_max)
    sh_local('echo "%s" > /sys/fs/cgroup/qemu.slice/%d.scope/memory.high' % (hi, vmid))
    sh_local('echo "%s" > /sys/fs/cgroup/qemu.slice/%d.scope/memory.swap.max' % (sw, vmid))


def set_io(vmid, on):
    spec = "8:0 rbps=max wbps=max riops=200 wiops=100" if on else "8:0 rbps=max wbps=max riops=max wiops=max"
    sh_local('echo "%s" > /sys/fs/cgroup/qemu.slice/%d.scope/io.max' % (spec, vmid))


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


def start_burner(k, cls):
    vm_cmd_safe(ip_of(k),
                'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; rm -f /tmp/burn_rate.txt; '
                'nohup python3 /home/debian/burner.py /tmp/burn_rate.txt 3600 %s >/dev/null 2>&1 & echo ok'
                % CLASS_ARGS[cls], timeout=40)


def stop_all_burners():
    for k in range(1, 17):
        vm_cmd_safe(ip_of(k), 'pkill -9 -f "^python3 /home/debian/burner.py" 2>/dev/null; true', timeout=40)


def burn_rate(k):
    out = vm_cmd_safe(ip_of(k), "cat /tmp/burn_rate.txt 2>/dev/null", timeout=40)
    try:
        return float(out.strip().split()[0])
    except (ValueError, IndexError):
        return None


def canary_stall():
    out = vm_cmd_safe(ip_of(7), "cat /tmp/stall.txt 2>/dev/null", timeout=15)
    return out.strip() or None


def canary_gap_ms():
    s = canary_stall()
    if not s:
        return None
    try:
        return float(s.split()[1])
    except (IndexError, ValueError):
        return None


def run_probes(round_name, policy, step, seconds=12):
    cmds = []
    for svc in ("http", "redis"):
        cmds.append("python3 /home/debian/probe.py --mode %s --host %s --rate 100 "
                    "--duration %d --tag joint-%s-%s-s%d-%s --raw /home/debian/joint_%s_%s_s%d_%s.raw" %
                    (svc, SVC[svc], seconds, round_name, policy, step, svc,
                     round_name, policy, step, svc))
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


def sample(keys):
    a = {k: cpu_stat(110 + k) for k in keys}
    t0 = time.time()
    time.sleep(3)
    b = {k: cpu_stat(110 + k) for k in keys}
    dt = max(0.5, time.time() - t0)
    out = {}
    for k in keys:
        du = (b[k].get("usage_usec", 0) - a[k].get("usage_usec", 0)) / (dt * 1e6)
        thr = b[k].get("nr_throttled", 0) - a[k].get("nr_throttled", 0)
        out[k] = {"usage": du, "throttle_inc": thr}
    return out


def decide_naive(obs, admitted, prior):
    est = sum(obs[k]["usage"] for k in BG_K)
    for k in admitted:
        est += obs[k]["usage"]
    return (est + prior <= BUDGET), "naive est=%.2f+%.2f<=%.1f" % (est, prior, BUDGET)


def decide_aware(obs, admitted, prior):
    est = sum(obs[k]["usage"] for k in BG_K)
    for k in admitted:
        last = obs[k]
        est += 1.0 if last["throttle_inc"] > 0 else last["usage"]
    return (est + prior <= BUDGET), "aware est=%.2f+%.2f<=%.1f" % (est, prior, BUDGET)


def decide_audible(snap, admitted, prior):
    series = []
    for k in BG_K + admitted:
        us = [u for (_, u, _) in snap[110 + k][-int(RESERVE_WINDOW):]]
        if us:
            series.append(us)
    if not series:
        return False, "audible: no history yet"
    reps = 400
    sums = []
    for _ in range(reps):
        sums.append(sum(random.choice(us) for us in series))
    sums.sort()
    total_q = sums[int(0.99 * (len(sums) - 1))]
    return (total_q + prior <= BUDGET), "audible mc_q99=%.2f+%.2f<=%.1f" % (total_q, prior, BUDGET)


def decide_taligned(snap, admitted, canary_ms, canary_max_ms):
    n = min((len(snap[110 + k]) for k in BG_K), default=0)
    agg = [sum(snap[110 + k][j][1] for k in BG_K) for j in range(n)]
    if agg:
        reserve = talign.quantile(agg[-int(RESERVE_WINDOW):], RESERVE_Q)
    else:
        reserve = None
    if reserve is None:
        return False, "taligned: no background history yet"
    cand_total = QUOTA_CORES * (len(admitted) + 1)
    profiles = {}
    for k in BG_K:
        profiles[k] = talign.phase_profile(snap[110 + k], 60, RESERVE_WINDOW, 1.0, None)
    for k in admitted:
        profiles[k] = talign.phase_profile(snap[110 + k], 60, RESERVE_WINDOW, 1.0, QUOTA_CORES)
    peak, at = talign.future_peak(profiles, time.time(), 60)
    if canary_ms is not None and canary_ms > canary_max_ms:
        return False, "taligned pause: canary_gap=%.0fms>%dms" % (canary_ms, canary_max_ms)
    allow = reserve + cand_total <= TALIGNED_CAP
    return allow, "taligned reserve=%.2f+cap=%.2f<=%.2f peak=%.2f@%ds canary=%sms" % (
        reserve, cand_total, TALIGNED_CAP, peak, at, "%.0f" % canary_ms if canary_ms is not None else "?")


def run_policy(args, policy):
    admitted = []
    sink = open("/root/joint_%s.jsonl" % args.round, "a", encoding="utf-8")
    sampler = None
    try:
        stop_all_burners()
        for vmid in (101, 102, 110):
            set_affinity(vmid, "0,1")
        for k in CAND_K + BG_K:
            set_affinity(110 + k, "2,3")
            set_mem(110 + k, args.mem_high_mb, args.swap_max)
            set_io(110 + k, True)
        for k in CAND_K:
            set_quota(110 + k, "max 100000")
        vm_cmd_safe(ip_of(7), "rm -f /tmp/stall.txt; pkill -f '^python3 /home/debian/stall.py' 2>/dev/null; "
                              "nohup python3 /home/debian/stall.py /tmp/stall.txt >/dev/null 2>&1 & echo ok", timeout=30)
        for k in BG_K:
            start_burner(k, BG_CLASSES[k])
        sampler = talign.HistorySampler([110 + k for k in CAND_K + BG_K], cpu_stat)
        sampler.start()
        print("[%s %s] background started; pre-roll %.0f s" % (args.round, policy, args.preroll), flush=True)
        time.sleep(args.preroll)

        summary = {"round": args.round, "policy": policy, "admitted": 0, "defers": 0,
                   "violations": 0, "steps": [], "mem_high_mb": args.mem_high_mb,
                   "preroll_s": args.preroll}
        for step, k in enumerate(CAND_K, start=1):
            obs_all = sample(CAND_K + BG_K)
            canary_ms = canary_gap_ms()
            if policy == "naive":
                allow, reason = decide_naive(obs_all, admitted, 0.5)
            elif policy == "aware":
                allow, reason = decide_aware(obs_all, admitted, 1.0)
            elif policy == "audible":
                allow, reason = decide_audible(sampler.snapshot(), admitted, 0.5)
            else:
                allow, reason = decide_taligned(sampler.snapshot(), admitted, canary_ms, args.canary_max_ms)
            ev = {"round": args.round, "policy": policy, "step": step, "candidate": k,
                  "decision": "allow" if allow else "defer", "reason": reason,
                  "admitted_before": len(admitted), "canary_gap_ms": canary_ms,
                  "bg_instant": {str(kk): round(obs_all[kk]["usage"], 3) for kk in BG_K}}
            print("[%s %s] step %d -> %s (%s)" % (args.round, policy, step, ev["decision"], reason),
                  flush=True)
            if not allow:
                summary["defers"] += 1
            else:
                set_quota(110 + k, QUOTA)
                start_burner(k, "pegged")
                admitted.append(k)
                summary["admitted"] = len(admitted)
                time.sleep(8)
                http, redis = run_probes(args.round, policy, step)
                viol = bool(http and http.get("p99_ms") is not None and http["p99_ms"] > SLO) or \
                       bool(redis and redis.get("p99_ms") is not None and redis["p99_ms"] > SLO)
                if viol:
                    summary["violations"] += 1
                ev.update({"admitted_after": len(admitted),
                           "http_p99": (http or {}).get("p99_ms"),
                           "redis_p99": (redis or {}).get("p99_ms"),
                           "violation": viol,
                           "canary_gap_ms_after": canary_gap_ms(),
                           "bg_rates": {str(kk): burn_rate(kk) for kk in BG_K},
                           "cand_rates": {str(kk): burn_rate(kk) for kk in admitted}})
                print("   window: http p99=%s redis p99=%s viol=%s canary=%s ms" %
                      (ev["http_p99"], ev["redis_p99"], viol, ev["canary_gap_ms_after"]), flush=True)
            summary["steps"].append(ev)
            sink.write(json.dumps(ev) + "\n")
            sink.flush()
        print("SUMMARY joint %s %s: admitted=%d defers=%d violations=%d" %
              (args.round, policy, summary["admitted"], summary["defers"], summary["violations"]),
              flush=True)
    finally:
        if sampler is not None:
            sampler.stop()
        stop_all_burners()
        vm_cmd_safe(ip_of(7), "pkill -f '^python3 /home/debian/stall.py' 2>/dev/null; true", timeout=30)
        for k in CAND_K:
            set_quota(110 + k, "max 100000")
        for k in CAND_K + BG_K:
            set_mem(110 + k, None, None)
            set_io(110 + k, False)
        for vmid in list(range(111, 121)) + [101, 102, 110]:
            set_affinity(vmid, "0-3")
        sink.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", required=True)
    ap.add_argument("--policies", default="naive,audible,aware,taligned")
    ap.add_argument("--mem-high-mb", type=int, default=800)
    ap.add_argument("--swap-max", type=int, default=0)
    ap.add_argument("--preroll", type=float, default=75.0)
    ap.add_argument("--canary-max-ms", type=float, default=2000.0)
    args = ap.parse_args()
    for policy in args.policies.split(","):
        policy = policy.strip()
        print("========== joint %s / %s ==========" % (args.round, policy), flush=True)
        run_policy(args, policy)
    print("JOINT %s DONE" % args.round, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
