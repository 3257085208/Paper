#!/usr/bin/env python3
"""Generate the Phase 2 campaign plan (estimator + controller + QoS work).

Writes tools/campaign_phase2.json next to this script.

Order:
  v2prep        activate Phase 2 burner (--jit) on all customer VMs
  v2est_r01..10 estimator characterization, 9 cells (111-115, 1 vCPU)
  v2me_r01..10  method_eval four-policy admission ablation
  v2cs_r01..10  cold start (2 scenarios x 3 policies)
  v2jm8_r01..5  joint four-policy comparison, memory gate 800 MB (legacy A/B)
  v2jm9_r01..5  joint four-policy comparison, memory gate 1920 MB (recalibrated)
  v2prep2       reconfigure 116-120 to 2 vCPU (multi-vCPU estimator cells)
  v2est2p_r01..10  estimator multi-vCPU cells (sat2p/duty2p, 2 vCPU)
  v2rest2       restore 116-120 to 1 vCPU
"""

from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "campaign_phase2.json")
PY = "python3 /root"


def main():
    jobs = []

    jobs.append({
        "round": "v2prep", "kind": "prep", "timeout": 900,
        "cmd": "bash /root/activate_phase2_burner.sh && echo ok > /root/phase2_prep.done",
        "out": "/root/phase2_prep.done",
    })

    for i in range(1, 11):
        r = "v2est_r%02d" % i
        jobs.append({
            "round": r, "kind": "est", "timeout": 3600,
            "cmd": "%s/estimator_eval_host.py --round %s" % (PY, r),
            "out": "/root/estimator_%s.jsonl" % r,
        })

    for i in range(1, 11):
        r = "v2me_r%02d" % i
        jobs.append({
            "round": r, "kind": "me", "timeout": 3600,
            "cmd": "%s/method_eval_host.py --round %s" % (PY, r),
            "out": "/root/metheval_%s.jsonl" % r,
        })

    for i in range(1, 11):
        r = "v2cs_r%02d" % i
        jobs.append({
            "round": r, "kind": "cs", "timeout": 3600,
            "cmd": "%s/coldstart_host.py --round %s" % (PY, r),
            "out": "/root/coldstart_%s.jsonl" % r,
        })

    for i in range(1, 6):
        r = "v2jm8_r%02d" % i
        jobs.append({
            "round": r, "kind": "joint", "timeout": 3900,
            "cmd": "%s/joint_host.py --round %s --mem-high-mb 800 --canary-max-ms 5500" % (PY, r),
            "out": "/root/joint_%s.jsonl" % r,
        })
    for i in range(1, 6):
        r = "v2jm9_r%02d" % i
        jobs.append({
            "round": r, "kind": "joint", "timeout": 3900,
            "cmd": "%s/joint_host.py --round %s --mem-high-mb 1920 --canary-max-ms 2000" % (PY, r),
            "out": "/root/joint_%s.jsonl" % r,
        })

    jobs.append({
        "round": "v2prep2", "kind": "prep2", "timeout": 1200,
        "cmd": ("for v in 116 117 118 119 120; do qm stop $v; done; sleep 3; "
                "for v in 116 117 118 119 120; do qm set $v --cores 2 >/dev/null; done; "
                "for v in 116 117 118 119 120; do qm start $v; done; sleep 25; "
                "echo ok > /root/phase2_2p.done"),
        "out": "/root/phase2_2p.done",
    })

    for i in range(1, 11):
        r = "v2est2p_r%02d" % i
        jobs.append({
            "round": r, "kind": "est2p", "timeout": 2700,
            "cmd": "%s/estimator_eval_host.py --round %s --vmids 116,117,118,119,120 --vcpus 2" % (PY, r),
            "out": "/root/estimator_%s.jsonl" % r,
        })

    jobs.append({
        "round": "v2rest2", "kind": "restore2", "timeout": 1200,
        "cmd": ("for v in 116 117 118 119 120; do qm stop $v; done; sleep 3; "
                "for v in 116 117 118 119 120; do qm set $v --cores 1 >/dev/null; done; "
                "for v in 116 117 118 119 120; do qm start $v; done; sleep 25; "
                "echo ok > /root/phase2_2p_restored.done"),
        "out": "/root/phase2_2p_restored.done",
    })

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(jobs, fh, indent=1)
    kinds = {}
    for job in jobs:
        kinds[job["kind"]] = kinds.get(job["kind"], 0) + 1
    print("wrote %s: %d jobs" % (OUT, len(jobs)))
    print("kinds:", kinds)
    est_min = {"prep": 1, "est": 32, "me": 18, "cs": 18, "joint": 26,
               "prep2": 1, "est2p": 12, "restore2": 1}
    total = sum(est_min[j["kind"]] for j in jobs)
    print("rough estimated serial time: %.1f h" % (total / 60.0))


if __name__ == "__main__":
    main()
