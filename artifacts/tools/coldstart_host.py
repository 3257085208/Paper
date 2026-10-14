#!/usr/bin/env python3
"""Cold-start experiment: admitting tenants with no history (host-side).

Two arrival populations (six candidates each, quota 50% applied on admission):
  all_heavy : every candidate is pegged (true demand 1.0, observed 0.5 core)
  all_light : every candidate is idle (true demand ~0.1)

Three cold-start priors decide without any history for the candidate:
  prior_light        assume new tenants are light (0.2); existing demand from usage
  prior_conservative always assume a new tenant needs a full vCPU (1.0)
  probe_relax        conservative first; after an admitted tenant's observed window
                     shows low usage (no throttling, usage < 0.3 for 2 checks),
                     classify it light and use the light prior for later arrivals

Records per step to /root/coldstart_<round>.jsonl; prints a summary per run.
"""

from __future__ import annotations

import argparse
import json
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
    args = "" if cls == "heavy" else "--duty 0.10 --period 60"
    vm_cmd_safe(CAND_IP[k],
                'pkill -f "^python3 /home/debian/burner.py" 2>/dev/null; rm -f /tmp/burn_rate.txt; '
                'nohup python3 /home/debian/burner.py /tmp/burn_rate.txt 3600 %s >/dev/null 2>&1 & echo ok' % args,
                timeout=40)


def stop_all_burners():
    for k in range(1, 17):
        vm_cmd_safe("10.10.10.%d" % (20 + k),
                    'pkill -9 -f "^python3 /home/debian/burner.py" 2>/dev/null; true', timeout=40)


def run_probes(round_name, policy, scenario, step, seconds=12):
    cmds = []
    for svc in ("http", "redis"):
        cmds.append("python3 /home/debian/probe.py --mode %s --host %s --rate 100 "
                    "--duration %d --tag cs-%s-%s-%s-s%d-%s --raw /home/debian/cs_%s_%s_%s_s%d_%s.raw" %
                    (svc, SVC[svc], seconds, round_name, policy, scenario, step, svc,
                     round_name, policy, scenario, step, svc))
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


def sample(admitted):
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


def run_policy(args, policy, scenario):
    cls = "heavy" if scenario == "all_heavy" else "light"
    admitted = []
    samples = {}
    light_tenants = set()
    sink = open("/root/coldstart_%s.jsonl" % args.round, "a", encoding="utf-8")
    try:
        stop_all_burners()
        for k in CAND_K:
            set_quota(CAND_VMID[k], "max 100000")
        time.sleep(2)
        summary = {"round": args.round, "policy": policy, "scenario": scenario,
                   "admitted": 0, "defers": 0, "violations": 0, "steps": []}
        for step, k in enumerate(CAND_K, start=1):
            obs = sample(admitted) if admitted else {}
            for kk, v in obs.items():
                samples.setdefault(kk, []).append(v)
            # classify admitted tenants (probe_relax only)
            if policy == "probe_relax":
                for kk in admitted:
                    series = samples.get(kk, [])
                    if len(series) >= 2 and all(s["throttle_inc"] == 0 and s["usage"] < 0.3
                                                for s in series[-2:]):
                        light_tenants.add(kk)
            # existing-demand estimate
            est = 0.0
            for kk in admitted:
                last = samples[kk][-1]
                if policy == "prior_light" or kk in light_tenants:
                    est += last["usage"]
                else:
                    est += 1.0
            if policy == "prior_light":
                prior = 0.2
            elif policy == "prior_conservative":
                prior = 1.0
            else:
                prior = 0.2 if light_tenants else 1.0
            allow = est + prior <= BUDGET
            reason = "est=%.2f+prior=%.2f<=%.1f" % (est, prior, BUDGET)
            ev = {"step": step, "candidate": k, "decision": "allow" if allow else "defer",
                  "reason": reason, "admitted_before": len(admitted),
                  "light_known": sorted(light_tenants)}
            print("[%s %s %s] step %d -> %s (%s)" % (args.round, policy, scenario, step,
                                                     ev["decision"], reason), flush=True)
            if not allow:
                summary["defers"] += 1
            else:
                set_quota(CAND_VMID[k], QUOTA)
                start_burner(k, cls)
                admitted.append(k)
                summary["admitted"] = len(admitted)
                time.sleep(8)
                http, redis = run_probes(args.round, policy, scenario, step)
                viol = bool(http and http.get("p99_ms") is not None and http["p99_ms"] > SLO) or \
                       bool(redis and redis.get("p99_ms") is not None and redis["p99_ms"] > SLO)
                if viol:
                    summary["violations"] += 1
                ev.update({"admitted_after": len(admitted),
                           "http_p99": (http or {}).get("p99_ms"),
                           "redis_p99": (redis or {}).get("p99_ms"),
                           "violation": viol})
                print("   window: http p99=%s redis p99=%s viol=%s" %
                      (ev["http_p99"], ev["redis_p99"], viol), flush=True)
            summary["steps"].append(ev)
            sink.write(json.dumps(ev) + "\n")
            sink.flush()
        print("SUMMARY %s %s %s: admitted=%d defers=%d violations=%d" %
              (args.round, policy, scenario, summary["admitted"], summary["defers"],
               summary["violations"]), flush=True)
    finally:
        stop_all_burners()
        for k in CAND_K:
            set_quota(CAND_VMID[k], "max 100000")
        sink.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", required=True)
    ap.add_argument("--scenarios", default="all_heavy,all_light")
    ap.add_argument("--policies", default="prior_light,prior_conservative,probe_relax")
    args = ap.parse_args()
    for scenario in args.scenarios.split(","):
        for policy in args.policies.split(","):
            scenario = scenario.strip()
            policy = policy.strip()
            print("========== %s / %s / %s ==========" % (args.round, scenario, policy), flush=True)
            run_policy(args, policy, scenario)
    print("COLDSTART %s DONE" % args.round, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
