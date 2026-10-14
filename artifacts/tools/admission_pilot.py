#!/usr/bin/env python3
"""Admission-policy comparison pilot on the BeroHost testbed.

Protocol (per policy run):
  Five candidate VMs (neighbor-1..5) arrive one at a time. At each arrival the
  policy observes the host busy% (3 s window), per-VM CPU usage from the PVE
  API, the service latency windows measured after earlier admissions, and the
  admitted count; it decides allow/defer and logs a reason. An allowed
  candidate is started (steady 1-vCPU busy loop), the system settles for
  --settle seconds, then svc-http and svc-redis are probed (open-loop,
  --rate req/s for --probe-seconds each) and the window p50/p99/p999 are
  recorded. A window with p99 > SLO_P99_MS (10 ms) counts as an SLO violation.
  Deferred candidates are not started; later arrivals still arrive.

Policies (all see the same observations):
  fixed_ratio    allow while INFRA_VCPU + k <= R * CAPACITY_VCPU (R = 2.0)
  utilization    allow while last host busy% < 80
  hist_quantile  allow while sum(est cores of admitted VMs) + prior <= 0.8*capacity
                 (per-VM estimate = max observed PVE cpu fraction; prior = 1.0)
  calibrated     same demand budget, plus defer when the latest window p999 >
                 12 ms (tail degradation) or host busy% >= 95 (stress guard)

Usage:
  python3 tools/admission_pilot.py --round a --policies fixed_ratio,utilization
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

KEY = os.path.expanduser("~/.ssh/sci2_key")
HOST = "45.82.120.52"
PORT = "2828"
PROBE_VM = "10.10.10.20"
SVC = {"http": "10.10.10.11", "redis": "10.10.10.12"}
NEIGHBOR = {
    1: ("111", "10.10.10.21"),
    2: ("112", "10.10.10.22"),
    3: ("113", "10.10.10.23"),
    4: ("114", "10.10.10.24"),
    5: ("115", "10.10.10.25"),
}
CAPACITY_VCPU = 4.0
INFRA_VCPU = 3
SLO_P99_MS = 10.0
TAIL_LIMIT_MS = 12.0
BUSY_LIMIT = 80.0
BUSY_GUARD = 95.0
QUANT_BUDGET = 0.8 * CAPACITY_VCPU

PROXY = ("ssh -i %s -o IdentitiesOnly=yes -o BatchMode=yes -p %s root@%s -W %%h:%%p"
         % (KEY, PORT, HOST))
SSH_BASE = ["-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new"]


def host_cmd(cmd, timeout=60):
    res = subprocess.run(["ssh"] + SSH_BASE + ["-p", PORT, "-o", "ConnectTimeout=15",
                                               "root@" + HOST, cmd],
                         capture_output=True, text=True, timeout=timeout)
    return res.stdout


def vm_cmd(ip, cmd, timeout=90):
    res = subprocess.run(["ssh", "-o", "ProxyCommand=" + PROXY] + SSH_BASE +
                         ["-o", "ConnectTimeout=12", "debian@" + ip, cmd],
                         capture_output=True, text=True, timeout=timeout)
    return res.stdout


def sample_busy():
    out = host_cmd("/tmp/busy3.sh", timeout=30)
    for line in out.splitlines():
        if "host_busy_pct=" in line:
            return float(line.split("=", 1)[1])
    return None


def sample_per_vm():
    out = host_cmd("pvesh get /cluster/resources --type vm --output-format json", timeout=40)
    try:
        data = json.loads(out)
    except ValueError:
        return {}
    cores = {}
    for item in data:
        vmid = int(item.get("vmid", 0))
        if 111 <= vmid <= 115:
            cpu = float(item.get("cpu") or 0.0)
            maxcpu = float(item.get("maxcpu") or 1.0)
            cores[vmid] = min(cpu, maxcpu)
    return cores


def start_burner(k):
    _, ip = NEIGHBOR[k]
    vm_cmd(ip, "nohup yes > /dev/null 2>&1 & echo ok", timeout=30)


def stop_all_burners():
    for k in NEIGHBOR:
        _, ip = NEIGHBOR[k]
        vm_cmd(ip, "pkill -x yes 2>/dev/null; true", timeout=30)


def run_probe(round_name, policy, k, mode, seconds, rate):
    cmd = ("python3 /home/debian/probe.py --mode %s --host %s --rate %d "
           "--duration %d --tag adm-%s-%s-k%d --raw /home/debian/adm_%s_%s_k%d_%s.raw" %
           (mode, SVC[mode], rate, seconds, round_name, policy, k, round_name, policy, k, mode))
    out = vm_cmd(PROBE_VM, cmd, timeout=seconds + 60)
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return None


def per_vm_estimate(samples, fallback):
    return max(samples) if samples else fallback


def decide_fixed_ratio(ctx):
    total = INFRA_VCPU + ctx["arrival"]
    limit = 2.0 * CAPACITY_VCPU
    return total <= limit, "configured_vcpu=%d<=%.0f (ratio 2.0)" % (total, limit), {}


def decide_utilization(ctx):
    busy = ctx["busy_pct"]
    ok = (busy is not None) and (busy < BUSY_LIMIT)
    return ok, "host_busy=%s%% limit=%.0f%%" % (busy, BUSY_LIMIT), {}


def _demand_summary(ctx):
    ests = []
    for adm_k, samples in ctx["vm_samples"].items():
        ests.append(per_vm_estimate(samples, 1.0))
    prior = max(ests) if ests else 1.0
    return ests, prior, sum(ests) + prior


def decide_hist_quantile(ctx):
    ests, prior, total = _demand_summary(ctx)
    ok = total <= QUANT_BUDGET
    return ok, "demand_sum=%.2f+%.2f<=%.2f cores" % (sum(ests), prior, QUANT_BUDGET), {"est": ests}


def decide_calibrated(ctx):
    busy = ctx["busy_pct"]
    if busy is not None and busy >= BUSY_GUARD:
        return False, "stress_guard host_busy=%.1f%%" % busy, {}
    tail = ctx.get("last_p999")
    if tail is not None and tail > TAIL_LIMIT_MS:
        return False, "tail_pause last_p999=%.2fms>%.0fms" % (tail, TAIL_LIMIT_MS), {}
    ests, prior, total = _demand_summary(ctx)
    ok = total <= QUANT_BUDGET
    return ok, "demand_sum=%.2f+%.2f<=%.2f cores" % (sum(ests), prior, QUANT_BUDGET), {"est": ests}


POLICIES = {
    "fixed_ratio": decide_fixed_ratio,
    "utilization": decide_utilization,
    "hist_quantile": decide_hist_quantile,
    "calibrated": decide_calibrated,
}


def run_policy(args, policy, round_name, outdir):
    path = os.path.join(outdir, "admission_%s.jsonl" % round_name)
    sink = open(path, "a", encoding="utf-8")
    state = {"admitted": 0, "defers": 0, "violations": 0, "windows": []}
    try:
        stop_all_burners()
        time.sleep(3)
        admitted = 0
        vm_samples = {}
        last_p999 = None
        for k in range(1, args.arrivals + 1):
            busy = sample_busy()
            per_vm = sample_per_vm()
            for adm_k in vm_samples:
                vmid = int(NEIGHBOR[adm_k][0])
                if vmid in per_vm:
                    vm_samples[adm_k].append(per_vm[vmid])
            ctx = {"arrival": k, "busy_pct": busy, "admitted": admitted,
                   "vm_samples": vm_samples, "last_p999": last_p999}
            allow, reason, _feats = POLICIES[policy](ctx)
            ev = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "round": round_name,
                  "policy": policy, "arrival": k,
                  "decision": "allow" if allow else "defer",
                  "reason": reason, "busy_pct": busy, "admitted_before": admitted}
            sink.write(json.dumps(ev, ensure_ascii=False) + "\n")
            sink.flush()
            print("[%s %s] arrival %d -> %s (%s)" % (round_name, policy, k, ev["decision"], reason),
                  flush=True)
            if not allow:
                state["defers"] += 1
                continue
            start_burner(k)
            admitted += 1
            vm_samples.setdefault(k, [])
            time.sleep(args.settle)
            per_vm2 = sample_per_vm()
            vmid = int(NEIGHBOR[k][0])
            if vmid in per_vm2:
                vm_samples[k].append(per_vm2[vmid])
            window_p999 = []
            for mode in ("http", "redis"):
                stats = run_probe(round_name, policy, k, mode, args.probe_seconds, args.rate)
                if not stats:
                    print("   window %s: MISSING" % mode, flush=True)
                    continue
                viol = bool(stats.get("p99_ms") is not None and stats["p99_ms"] > SLO_P99_MS)
                win = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "round": round_name,
                       "policy": policy, "arrival": k, "admitted_after": admitted, "mode": mode,
                       "p50_ms": stats.get("p50_ms"), "p99_ms": stats.get("p99_ms"),
                       "p999_ms": stats.get("p999_ms"), "max_ms": stats.get("max_ms"),
                       "schedule_lag_p99_ms": stats.get("schedule_lag_p99_ms"),
                       "timeouts": stats.get("timeouts"), "violation": viol}
                state["windows"].append(win)
                if viol:
                    state["violations"] += 1
                if stats.get("p999_ms"):
                    window_p999.append(stats["p999_ms"])
                sink.write(json.dumps(win, ensure_ascii=False) + "\n")
                sink.flush()
                print("   window %s: p50=%s p99=%s p999=%s viol=%s" %
                      (mode, stats.get("p50_ms"), stats.get("p99_ms"),
                       stats.get("p999_ms"), viol), flush=True)
            if window_p999:
                last_p999 = max(window_p999)
        state["admitted"] = admitted
    finally:
        stop_all_burners()
        sink.close()
    return state


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", required=True)
    ap.add_argument("--policies", required=True,
                    help="comma-separated policy names, run in this order")
    ap.add_argument("--arrivals", type=int, default=5)
    ap.add_argument("--settle", type=float, default=10.0)
    ap.add_argument("--probe-seconds", type=float, default=12.0)
    ap.add_argument("--rate", type=float, default=100.0)
    ap.add_argument("--outdir", default="research_data/berohost_pilot")
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)

    for policy in args.policies.split(","):
        policy = policy.strip()
        if policy not in POLICIES:
            print("unknown policy: %s" % policy, file=sys.stderr)
            return 2
        print("========== round %s / policy %s ==========" % (args.round, policy), flush=True)
        state = run_policy(args, policy, args.round, args.outdir)
        summary = {"round": args.round, "policy": policy,
                   "admitted": state["admitted"], "defers": state["defers"],
                   "violations": state["violations"]}
        print("SUMMARY " + json.dumps(summary, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
