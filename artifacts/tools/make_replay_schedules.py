#!/usr/bin/env python3
"""Extract production replay schedules from HK telemetry (pve_metrics.jsonl).

Selects 64 running VMs (mix of idle/light/heavy), takes a common 30-minute
excerpt (so cross-VM correlation is preserved), and writes per-VM duty files
(one duty per 60 s period) plus the excerpt matrix for offline PPC prediction.
"""
from __future__ import annotations
import json, os, statistics

SRC = "research_data/vps2_readonly/pve_metrics.jsonl"
OUT = "research_data/vps2_readonly/replay_sched"
EXCERPT_START, EXCERPT_MIN = 60, 30

def main():
    rows = [json.loads(l) for l in open(SRC)]
    series = {}
    for r in rows:
        for g in r.get("guests") or []:
            if g.get("status") != "running":
                continue
            v = g.get("cpu_fraction_raw")
            if v is None:
                continue
            series.setdefault(g["guest_hash"], []).append(v)
    full = {k: v for k, v in series.items() if len(v) >= EXCERPT_START + EXCERPT_MIN}
    # selection: keep the mixture (helpers first, then fill by diversity)
    def band(m):
        return 0 if m < 0.05 else (1 if m < 0.30 else 2)
    by_band = {0: [], 1: [], 2: []}
    for k, v in full.items():
        by_band[band(statistics.mean(v))].append((k, statistics.mean(v)))
    picked = []
    for b in (2, 1, 0):
        by_band[b].sort(key=lambda x: -x[1])
        picked += [k for k, _ in by_band[b]]
    picked = picked[:64]
    os.makedirs(OUT, exist_ok=True)
    matrix = {}
    for k in picked:
        seg = full[k][EXCERPT_START:EXCERPT_START + EXCERPT_MIN]
        seg = [min(1.0, max(0.0, x)) for x in seg]
        with open(os.path.join(OUT, "%s.txt" % k), "w") as fh:
            fh.write("\n".join("%.3f" % x for x in seg) + "\n")
        matrix[k] = seg
    with open(os.path.join(OUT, "matrix.json"), "w") as fh:
        json.dump({"start_min": EXCERPT_START, "minutes": EXCERPT_MIN, "vms": matrix}, fh)
    ms = [statistics.mean(v) for v in matrix.values()]
    print("schedules:", len(matrix), "| mean duties: min=%.3f med=%.3f max=%.3f" % (
        min(ms), statistics.median(ms), max(ms)))

if __name__ == "__main__":
    main()
