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


def analyze(recs, trace, letter, t0, t_match, t_thr, t_rel, a):
    """Host-trace D/E/kappa (authoritative) + guest-side drain and cross-check."""
    def rates(lo, hi):
        pts = [r for r in trace if lo <= r["t"] < hi and r.get(letter)]
        out = []
        for p, q in zip(pts, pts[1:]):
            du = q[letter].get("usage_usec", 0) - p[letter].get("usage_usec", 0)
            dt = q["t"] - p["t"]
            if dt > 0:
                out.append((p["t"], q["t"], du / 1e6 / dt))
        return out
    def stage(lo, hi):
        return [r for r in recs if lo <= r["t"] < hi]
    match_r = rates(t0, t_match)
    thr_r = rates(t_match, t_thr)
    rel_r = rates(t_thr, t_rel)
    base_rate = (sum(r for _, _, r in match_r) / len(match_r)) if match_r else None
    D = sum(max(0.0, base_rate - r) * (b - aa) for aa, b, r in thr_r) if base_rate else 0.0
    E = sum(max(0.0, r - base_rate) * (b - aa) for aa, b, r in rel_r) if base_rate else 0.0
    kappa = (E / D) if D > 1e-9 else None
    thr_mean = (sum(r for _, _, r in thr_r) / len(thr_r)) if thr_r else None
    rel_mean = (sum(r for _, _, r in rel_r) / len(rel_r)) if rel_r else None
    thr = stage(t_match, t_thr)
    rel = stage(t_thr, t_rel)
    g_thr = (sum(r["delivered"] for r in thr) / len(thr)) if thr else None
    g_rel = (sum(r["delivered"] for r in rel) / len(rel)) if rel else None
    drain_end = None
    for r in rel:
        if r["backlog"] > 1e-3:
            drain_end = r["t"]
    drain_s = (drain_end - t_thr) if drain_end else 0.0
    return {"host_baseline_cores": round(base_rate, 3) if base_rate else None,
            "host_throttle_cores": round(thr_mean, 3) if thr_mean else None,
            "host_release_cores": round(rel_mean, 3) if rel_mean else None,
            "guest_throttle_delivered": round(g_thr, 3) if g_thr else None,
            "guest_release_delivered": round(g_rel, 3) if g_rel else None,
            "D_cpu_s": round(D, 2), "E_cpu_s": round(E, 2),
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

    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "burner_debt.py")
    for ip in (ipa, ipb):
        ok = False
        for attempt in range(3):
            r = subprocess.run(["scp", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                                "-o", "StrictHostKeyChecking=accept-new",
                                src, "debian@%s:/home/debian/burner_debt.py" % ip],
                               capture_output=True, text=True, timeout=30)
            chk = vm_cmd(ip, "test -f /home/debian/burner_debt.py && echo DEPLOYED", timeout=15)
            if r.returncode == 0 and "DEPLOYED" in chk:
                ok = True
                break
            print("scp attempt %d to %s failed rc=%s err=%s" % (attempt + 1, ip, r.returncode, (r.stderr or "")[:120]))
            time.sleep(2)
        if not ok:
            raise RuntimeError("burner deployment failed on %s" % ip)

    total_s = (args.match_min + args.throttle_min + args.release_min) * 60
    trace = []
    try:
        for vmid in (args.vm_a, args.vm_b):
            set_quota(vmid, None)
        for ip in (ipa, ipb):
            vm_cmd(ip, 'pkill -f "[b]urner_debt" 2>/dev/null; rm -f /tmp/debt_a.jsonl /tmp/debt_b.jsonl; true', timeout=20)

        t0 = time.time()
        t_match = t0 + args.match_min * 60
        t_thr = t_match + args.throttle_min * 60
        t_rel = t_thr + args.release_min * 60

        vm_cmd(ipa, 'nohup python3 /home/debian/burner_debt.py /tmp/debt_a.jsonl '
                    '--mode replaceable --duration %d --cal-s 60 >/tmp/debt_a.err 2>&1 &' % (total_s + 60))
        vm_cmd(ipb, 'nohup python3 /home/debian/burner_debt.py /tmp/debt_b.jsonl '
                    '--mode persistent --duration %d --cal-s 60 >/tmp/debt_b.err 2>&1 &' % (total_s + 60))
        time.sleep(4)
        for ip, tag in ((ipa, "A"), (ipb, "B")):
            pg = vm_cmd(ip, "pgrep -f '[b]urner_debt' | head -1", timeout=15).strip()
            err = vm_cmd(ip, "cat /tmp/debt_%s.err 2>/dev/null | head -5" % tag.lower(), timeout=15)
            if not pg or "Traceback" in err:
                raise RuntimeError("burner %s failed on %s: pid=%s err=%s" % (tag, ip, pg, err))
            print("burner %s running on %s (pid %s)" % (tag, ip, pg))

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
            vm_cmd(ip, 'pkill -f "[b]urner_debt" 2>/dev/null; true', timeout=20)
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
           "A_replaceable": analyze(ga, trace, "a", t0, t_match, t_thr, t_rel, args.demand),
           "B_persistent": analyze(gb, trace, "b", t0, t_match, t_thr, t_rel, args.demand)}
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
