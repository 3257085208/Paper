#!/usr/bin/env python3
"""Method evaluation: censoring-aware admission vs. naive and AUDIBLE-style baselines.

Scenario: six candidate tenants arrive one at a time. Every admitted tenant is
*shaped* with cpu.max = 50% and runs a pegged workload (true demand 1.0 core,
observed usage 0.5 core). Services run unpinned, so over-admission shows up in
their tail latency. At each step the policy sees only decision-time evidence:
per-VM usage cores and throttle-counter deltas (from host cgroup files), the
latest service-tail window, and the admitted set.

Policies (each run is a full sequence):
  naive      demand = observed usage; class prior 0.5; budget 3.2
  audible    AUDIBLE-style: per-VM empirical usage distributions, Monte-Carlo
             convolution under independence; q99 of the sum + prior q99 <= 3.2
  aware      throttle evidence -> demand = max(usage, 1.0 core); prior 1.0
  aware_cal  aware + 10% budget margin + tail pause (last window p999 > 12 ms)

Record per step to /root/metheval_<round>.jsonl, print a summary per policy.
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import time

KEY = "/root/.ssh/sci2_key"
PROBE_VM = "10.10.10.20"
SVC = {"http": "10.10.10.11", "redis": "10.10.10.12"}
CAND_K = [1, 2, 3, 4, 5, 6]
CAND_VMID = {k: 110 + k for k in CAND_K}
CAND_IP = {k: "10.10.10.%d" % (20 + k) for k in CAND_K}
QUOTA = "50000 100000"
BUDGET = 0.8 * 4.0
PRIOR_NAIVE = 0.5
PRIOR_AWARE = 1.0
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


def set_quota(vmid, spec):
    sh_local('echo "%s" > /sys/fs/cgroup/qemu.slice/%d.scope/cpu.max' % (spec, vmid))


def set_affinity(vmid, mask):
    sh_local('pid=$(cat /run/qemu-server/%d.pid); taskset -apc %s $pid >/dev/null 2>&1' % (vmid, mask))


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
    vm_cmd_safe(CAND_IP[k],
                'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; rm -f /tmp/burn_rate.txt; '
                'nohup python3 /home/debian/burner.py /tmp/burn_rate.txt 3600 >/dev/null 2>&1 & echo ok',
                timeout=40)


def stop_all_burners():
    for k in range(1, 17):
        vm_cmd_safe("10.10.10.%d" % (20 + k),
                    'pkill -9 -f "^python3 /home/debian/burner.py" 2>/dev/null; true', timeout=40)


def run_probes(round_name, policy, step, seconds=15):
    cmds = []
    for svc in ("http", "redis"):
        cmds.append("python3 /home/debian/probe.py --mode %s --host %s --rate 100 "
                    "--duration %d --tag me-%s-%s-s%d-%s --raw /home/debian/me_%s_%s_s%d_%s.raw" %
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


def sample_demand(admitted):
    """Per-VM usage cores and throttle deltas over a 3 s window."""
    a = {k: cpu_stat(CAND_VMID[k]) for k in admitted}
    t0 = time.time()
    time.sleep(3)
    b = {k: cpu_stat(CAND_VMID[k]) for k in admitted}
    dt = max(0.5, time.time() - t0)
    out = {}
    for k in admitted:
        du = (b[k].get("usage_usec", 0) - a[k].get("usage_usec", 0)) / (dt * 1e6)
        dt_thr = b[k].get("nr_throttled", 0) - a[k].get("nr_throttled", 0)
        out[k] = {"usage": du, "throttle_inc": dt_thr}
    return out


def decide_naive(samples, admitted, prior):
    est = sum(samples[k][-1]["usage"] for k in admitted)
    return (est + prior <= BUDGET), "usage_sum=%.2f+%.2f<=%.1f" % (est, prior, BUDGET)


def decide_audible(samples, admitted, prior):
    if not admitted:
        total_q = 0.0
    else:
        per_vm = [samples[k] for k in admitted]
        reps = 400
        sums = []
        for _ in range(reps):
            s = 0.0
            for series in per_vm:
                s += random.choice(series)["usage"]
            sums.append(s)
        sums.sort()
        total_q = sums[int(0.99 * (len(sums) - 1))]
    return (total_q + prior <= BUDGET), "mc_q99_sum=%.2f+%.2f<=%.1f" % (total_q, prior, BUDGET)


def decide_aware(samples, admitted, prior):
    est = 0.0
    for k in admitted:
        last = samples[k][-1]
        est += 1.0 if last["throttle_inc"] > 0 else last["usage"]
    return (est + prior <= BUDGET), "aware_sum=%.2f+%.2f<=%.1f" % (est, prior, BUDGET)


def decide_aware_cal(samples, admitted, prior, last_p999):
    if last_p999 is not None and last_p999 > 12.0:
        return False, "tail_pause last_p999=%.1f>12" % last_p999
    est = 0.0
    for k in admitted:
        last = samples[k][-1]
        est += 1.0 if last["throttle_inc"] > 0 else last["usage"]
    budget = 0.9 * BUDGET
    return (est + prior <= budget), "aware_sum=%.2f+%.2f<=%.2f" % (est, prior, budget)


def run_policy(args, policy):
    admitted = []
    samples = {}
    sink = open("/root/metheval_%s.jsonl" % args.round, "a", encoding="utf-8")
    last_p999 = None
    try:
        stop_all_burners()
        for k in CAND_K:
            set_quota(CAND_VMID[k], "max 100000")
        for k in CAND_K:
            set_affinity(CAND_VMID[k], "0-3")
        time.sleep(2)
        summary = {"round": args.round, "policy": policy, "admitted": 0, "defers": 0,
                   "violations": 0, "steps": []}
        for step, k in enumerate(CAND_K, start=1):
            obs = sample_demand(admitted) if admitted else {}
            for kk, v in obs.items():
                samples.setdefault(kk, []).append(v)
            prior = PRIOR_NAIVE if policy in ("naive", "audible") else PRIOR_AWARE
            if policy == "naive":
                allow, reason = decide_naive(samples, admitted, prior)
            elif policy == "audible":
                allow, reason = decide_audible(samples, admitted, prior)
            elif policy == "aware":
                allow, reason = decide_aware(samples, admitted, prior)
            else:
                allow, reason = decide_aware_cal(samples, admitted, prior, last_p999)
            ev = {"step": step, "candidate": k, "decision": "allow" if allow else "defer",
                  "reason": reason, "admitted_before": len(admitted)}
            print("[%s %s] step %d -> %s (%s)" % (args.round, policy, step, ev["decision"], reason),
                  flush=True)
            if not allow:
                summary["defers"] += 1
                summary["steps"].append(ev)
                sink.write(json.dumps(ev) + "\n")
                sink.flush()
                continue
            set_quota(CAND_VMID[k], QUOTA)
            start_burner(k)
            admitted.append(k)
            summary["admitted"] = len(admitted)
            time.sleep(10)
            http, redis = run_probes(args.round, policy, step)
            viol = bool(http and http.get("p99_ms") is not None and http["p99_ms"] > SLO) or \
                   bool(redis and redis.get("p99_ms") is not None and redis["p99_ms"] > SLO)
            if viol:
                summary["violations"] += 1
            if http and http.get("p999_ms"):
                last_p999 = http["p999_ms"]
            win = {"step": step, "candidate": k, "decision": "allow", "reason": reason,
                   "admitted_after": len(admitted),
                   "http_p99": (http or {}).get("p99_ms"), "redis_p99": (redis or {}).get("p99_ms"),
                   "http_p999": (http or {}).get("p999_ms"), "violation": viol}
            summary["steps"].append(win)
            sink.write(json.dumps(win) + "\n")
            sink.flush()
            print("   window: http p99=%s redis p99=%s viol=%s" %
                  (win["http_p99"], win["redis_p99"], viol), flush=True)
        print("SUMMARY %s %s: admitted=%d defers=%d violations=%d" %
              (args.round, policy, summary["admitted"], summary["defers"], summary["violations"]),
              flush=True)
    finally:
        stop_all_burners()
        for k in CAND_K:
            set_quota(CAND_VMID[k], "max 100000")
        sink.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", required=True)
    ap.add_argument("--policies", default="naive,audible,aware,aware_cal")
    args = ap.parse_args()
    for policy in args.policies.split(","):
        policy = policy.strip()
        print("========== %s / %s ==========" % (args.round, policy), flush=True)
        run_policy(args, policy)
    print("METHEVAL %s DONE" % args.round, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
