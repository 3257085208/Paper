#!/usr/bin/env python3
"""Control-history pilot (host side): paired work-preservation experiment.

Question: with matched baseline telemetry and the same control action, do
"replaceable" (latest-state) and "persistent" (FIFO backlog) workloads diverge
after release, while their throttled-phase telemetry stays indistinguishable?

Timeline (defaults): match 4 min (no quota) -> throttle 3 min (20%) -> release 12 min (max).
Two VMs run the two semantics in parallel on the same wall clock:
  vm-a: burner_debt.py --mode replaceable
  vm-b: burner_debt.py --mode persistent
Host side samples cgroup cpu.stat every 2 s; guest JSONL is pulled afterwards.

Predicted (to verify): kappa_A = E/D ~ 0, kappa_B ~ 1, drain ~ 3 x throttle length;
host usage/throttle traces during the throttled phase are near-identical.

Failure condition (honest): if kappa_A ~ kappa_B and post-release activity does not
separate, the mechanism does not hold at this granularity -> report as negative.

Run on the physical host (needs qemu.slice cgroups). Deploy: scp tools/burner_debt.py
and this file to /root/tb/, then:  python3 tb_debt_pilot.py
"""

import argparse
import json
import os
import subprocess
import time

KEY = "/root/.ssh/tb_key"
VM_IP = {vmid: "10.10.0.%d" % (vmid - 290) for vmid in range(311, 375)}
SSH = ["-n", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
       "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=8",
       "-o", "LogLevel=ERROR"]


def vm_cmd(ip, cmd, timeout=60):
    try:
        res = subprocess.run(["ssh"] + SSH + ["debian@" + ip, cmd],
                             capture_output=True, text=True, timeout=timeout)
        return res.stdout
    except subprocess.TimeoutExpired:
        return ""


def set_quota(vmid, pct):
    val = "max 100000" if pct is None else "%d 100000" % int(pct / 100.0 * 100000)
    subprocess.run('echo "%s" > /sys/fs/cgroup/qemu.slice/%d.scope/cpu.max' % (val, vmid),
                   shell=True, capture_output=True)
    rb = subprocess.run('cat /sys/fs/cgroup/qemu.slice/%d.scope/cpu.max' % vmid,
                        shell=True, capture_output=True, text=True).stdout.strip()
    return rb == val


def cgstat(vmid):
    out = {}
    try:
        for line in open("/sys/fs/cgroup/qemu.slice/%d.scope/cpu.stat" % vmid):
            parts = line.split()
            if len(parts) == 2:
                out[parts[0]] = int(parts[1])
    except OSError:
        pass
    return out


def parse_jsonl(text):
    recs = []
    for line in text.splitlines():
        try:
            recs.append(json.loads(line))
        except ValueError:
            pass
    return recs


def analyze(recs, t0, t_match, t_thr, t_rel, a):
    """D/E/kappa and drain from guest records; times are unix seconds."""
    def stage(lo, hi):
        return [r for r in recs if lo <= r["t"] < hi]
    base = stage(t0, t_match)
    thr = stage(t_match, t_thr)
    rel = stage(t_thr, t_rel)
    base_rate = sum(r["delivered"] for r in base) / max(1e-9, len(base))
    D = sum(max(0.0, a - r["delivered"]) for r in thr)
    E = sum(max(0.0, r["delivered"] - a) for r in rel)
    kappa = (E / D) if D > 1e-9 else None
    drain_end = None
    for r in rel:
        if r["backlog"] > 1e-3:
            drain_end = r["t"]
    drain_s = (drain_end - t_thr) if drain_end else 0.0
    return {"baseline_rate": round(base_rate, 3), "throttle_periods": len(thr),
            "release_periods": len(rel), "D": round(D, 2), "E": round(E, 2),
            "kappa": round(kappa, 3) if kappa is not None else None,
            "drain_s": round(drain_s, 1),
            "final_backlog": recs[-1]["backlog"] if recs else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vm-a", type=int, default=311)
    ap.add_argument("--vm-b", type=int, default=312)
    ap.add_argument("--match-min", type=float, default=4)
    ap.add_argument("--throttle-min", type=float, default=3)
    ap.add_argument("--release-min", type=float, default=12)
    ap.add_argument("--quota", type=float, default=20.0)
    ap.add_argument("--demand", type=float, default=0.8)
    ap.add_argument("--outdir", default=None)
    args = ap.parse_args()

    ts = time.strftime("%m%d_%H%M")
    outdir = args.outdir or "/root/tb/debt_pilot_%s" % ts
    os.makedirs(outdir, exist_ok=True)
    ipa, ipb = VM_IP[args.vm_a], VM_IP[args.vm_b]

    for ip in (ipa, ipb):
        subprocess.run(["scp", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                        "-o", "StrictHostKeyChecking=accept-new",
                        os.path.join(os.path.dirname(os.path.abspath(__file__)), "burner_debt.py"),
                        "debian@%s:/home/debian/burner_debt.py"],
                       capture_output=True, timeout=30)

    total_s = (args.match_min + args.throttle_min + args.release_min) * 60
    trace = []
    try:
        for vmid in (args.vm_a, args.vm_b):
            set_quota(vmid, None)
        for ip in (ipa, ipb):
            vm_cmd(ip, 'pkill -f burner_debt.py 2>/dev/null; true', timeout=20)

        t0 = time.time()
        t_match = t0 + args.match_min * 60
        t_thr = t_match + args.throttle_min * 60
        t_rel = t_thr + args.release_min * 60

        vm_cmd(ipa, 'nohup python3 /home/debian/burner_debt.py /tmp/debt_a.jsonl '
                    '--mode replaceable --duration %d >/tmp/debt_a.err 2>&1 &' % (total_s + 60))
        vm_cmd(ipb, 'nohup python3 /home/debian/burner_debt.py /tmp/debt_b.jsonl '
                    '--mode persistent --duration %d >/tmp/debt_b.err 2>&1 &' % (total_s + 60))

        throttled = released = False
        while time.time() < t_rel:
            now = time.time()
            if not throttled and now >= t_match:
                for vmid in (args.vm_a, args.vm_b):
                    ok = set_quota(vmid, args.quota)
                print("[%s] throttle %s%% applied (ok=%s)" % (time.strftime("%H:%M:%S"), args.quota, ok))
                throttled = True
            if not released and now >= t_thr:
                for vmid in (args.vm_a, args.vm_b):
                    set_quota(vmid, None)
                print("[%s] release (quota=max)" % time.strftime("%H:%M:%S"))
                released = True
            trace.append({"t": round(now, 3),
                          "a": cgstat(args.vm_a), "b": cgstat(args.vm_b)})
            time.sleep(2.0)

        for ip in (ipa, ipb):
            vm_cmd(ip, 'pkill -f burner_debt.py 2>/dev/null; true', timeout=20)
        time.sleep(1)
        ga = parse_jsonl(vm_cmd(ipa, "cat /tmp/debt_a.jsonl", timeout=60))
        gb = parse_jsonl(vm_cmd(ipb, "cat /tmp/debt_b.jsonl", timeout=60))
    finally:
        for vmid in (args.vm_a, args.vm_b):
            set_quota(vmid, None)

    with open(os.path.join(outdir, "host_trace.jsonl"), "w") as fh:
        for r in trace:
            fh.write(json.dumps(r) + "\n")
    with open(os.path.join(outdir, "guest_a.jsonl"), "w") as fh:
        for r in ga:
            fh.write(json.dumps(r) + "\n")
    with open(os.path.join(outdir, "guest_b.jsonl"), "w") as fh:
        for r in gb:
            fh.write(json.dumps(r) + "\n")

    res = {"vm_a": args.vm_a, "vm_b": args.vm_b, "t0": t0, "t_match": t_match,
           "t_thr": t_thr, "t_rel": t_rel, "quota_pct": args.quota,
           "A_replaceable": analyze(ga, t0, t_match, t_thr, t_rel, args.demand),
           "B_persistent": analyze(gb, t0, t_match, t_thr, t_rel, args.demand)}
    # host-side invisibility check during the throttled phase
    def rate(letter, key, lo, hi):
        pts = [r[letter] for r in trace if lo <= r["t"] < hi and r.get(letter)]
        if len(pts) < 2:
            return None
        d = pts[-1].get(key, 0) - pts[0].get(key, 0)
        return round(d / 1e6, 3)
    res["host_throttle_usage_cpu_s"] = {"A": rate("a", "usage_usec", t_match, t_thr),
                                        "B": rate("b", "usage_usec", t_match, t_thr)}
    res["host_throttle_throttled_s"] = {"A": rate("a", "throttled_usec", t_match, t_thr),
                                        "B": rate("b", "throttled_usec", t_match, t_thr)}
    with open(os.path.join(outdir, "summary.json"), "w") as fh:
        json.dump(res, fh, indent=2)

    print(json.dumps(res, indent=2))
    print("outdir:", outdir)


if __name__ == "__main__":
    main()
