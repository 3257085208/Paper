#!/usr/bin/env python3
"""Generate the Phase 1 mega-campaign plan (fix-independent experiments).

Writes tools/campaign_phase1.json next to this script. Round counts are the
6-10x scale-up targets over the pilot rounds (knee 5 -> 50, censor 7 records ->
90, synthesis 4 -> 40, packing 14 -> 60, shaping 4 -> 32, memory 4 -> 25,
disk 5 -> 37, quota-pulse 1 -> 30)."""

from __future__ import annotations

import json
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "campaign_phase1.json")
PY = "python3 /root"


def main():
    rng = random.Random(20261012)
    jobs = []

    # ---- knee sweep: 50 rounds ----
    for i in range(1, 51):
        r = "v2knee_r%02d" % i
        levels = [0, 1, 2, 3, 4, 5]
        rng.shuffle(levels)
        jobs.append({
            "round": r, "kind": "knee", "timeout": 1800,
            "cmd": "%s/sweep_host.py --round %s --levels '%s'" % (PY, r, " ".join(map(str, levels))),
            "out": "/root/knee_%s.jsonl" % r,
        })

    # ---- censoring: 30 rounds x 3 cycles = 90 cycle records ----
    for i in range(1, 31):
        r = "v2cen_r%02d" % i
        jobs.append({
            "round": r, "kind": "censor", "timeout": 2400,
            "cmd": "%s/censor_phase_host.py --round %s --cycles 3" % (PY, r),
            "out": "/root/censor_%s.jsonl" % r,
        })

    # ---- synthesis (CPU+mem+IO storm): 40 rounds ----
    for i in range(1, 41):
        r = "v2syn_r%02d" % i
        jobs.append({
            "round": r, "kind": "syn", "timeout": 3600,
            "cmd": "%s/synthesis_host.py --round %s" % (PY, r),
            "out": "/root/synthesis_%s.jsonl" % r,
        })

    # ---- mixed packing: 10 profiles x 6 reps = 60 rounds ----
    profiles = [
        "idle:8,bursty:2",
        "idle:6,bursty:2,syncidle:2",
        "pegged:1,bursty:2,idle:7",
        "pegged:2,bursty:2,idle:6",
        "sync20:3,idle:7",
        "syncidle:4,bursty:2,idle:4",
        "bursty:4,idle:6",
        "sync20:2,syncidle:2,bursty:2,idle:4",
        "pegged:2,syncidle:3,idle:5",
        "bursty:3,pegged:2,idle:5",
    ]
    idx = 0
    for rep in range(6):
        order = list(range(len(profiles)))
        rng.shuffle(order)
        for p in order:
            idx += 1
            r = "v2pack_r%02d" % idx
            jobs.append({
                "round": r, "kind": "packing", "timeout": 1800,
                "cmd": '%s/packing_host.py --round %s --profile "%s"' % (PY, r, profiles[p]),
                "out": "/root/packing_%s.jsonl" % r,
            })

    # ---- shaping: 4 schemes x 8 rounds = 32 ----
    for scheme, short in [("unlimited", "unl"), ("q75", "q75"), ("q50", "q50"), ("pin", "pin")]:
        for i in range(1, 9):
            r = "v2shp_%s_r%02d" % (short, i)
            jobs.append({
                "round": r, "kind": "shaping", "timeout": 1800,
                "cmd": "%s/shaping_host.py --round %s --scheme %s" % (PY, r, scheme),
                "out": "/root/shaping_%s.jsonl" % r,
            })

    # ---- memory: grow x10 + capped x15 ----
    for i in range(1, 11):
        r = "v2mem_g_r%02d" % i
        jobs.append({
            "round": r, "kind": "mem", "timeout": 3000,
            "cmd": "%s/mem_phase_host.py --mode grow --round %s" % (PY, r),
            "out": "/root/memphase_%s.jsonl" % r,
        })
    for i in range(1, 16):
        r = "v2mem_c_r%02d" % i
        jobs.append({
            "round": r, "kind": "mem", "timeout": 3000,
            "cmd": "%s/mem_phase_host.py --mode capped --round %s" % (PY, r),
            "out": "/root/memphase_%s.jsonl" % r,
        })

    # ---- disk: baseline x10 + capped x15 + weighted x12 ----
    for mode, short, n in [("baseline", "base", 10), ("capped", "cap", 15), ("weighted", "wt", 12)]:
        for i in range(1, n + 1):
            r = "v2disk_%s_r%02d" % (short, i)
            jobs.append({
                "round": r, "kind": "disk", "timeout": 3000,
                "cmd": "%s/disk_phase_host.py --mode %s --round %s" % (PY, mode, r),
                "out": "/root/disk_%s.jsonl" % r,
            })

    # ---- quota pulse: 30 rounds ----
    for i in range(1, 31):
        r = "v2qp_r%02d" % i
        jobs.append({
            "round": r, "kind": "qp", "timeout": 3600,
            "cmd": "%s/quota_pulse_host.py --round %s" % (PY, r),
            "out": "/root/quota_pulse_%s.jsonl" % r,
        })

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(jobs, fh, indent=1)
    kinds = {}
    for job in jobs:
        kinds[job["kind"]] = kinds.get(job["kind"], 0) + 1
    print("wrote %s: %d jobs" % (OUT, len(jobs)))
    print("kinds:", kinds)
    est_min = {"knee": 6, "censor": 9, "syn": 6, "packing": 3.5,
               "shaping": 4.5, "mem": 11, "disk": 8, "qp": 10}
    total = sum(est_min[j["kind"]] for j in jobs)
    print("rough estimated serial time: %.1f h" % (total / 60.0))


if __name__ == "__main__":
    main()
