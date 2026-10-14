#!/usr/bin/env python3
"""Round-level interval summary for key conclusions (Metior-style: uncertainty at
the independent-run level, not per-request). Writes manuscript/interval_summary.txt.

Note: with 4-7 independent rounds the percentile bootstrap is indicative only;
it is reported as such in the manuscript.
"""

from __future__ import annotations

import csv
import json
import os
import random

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "..", "research_data", "berohost_pilot")
OUT = os.path.join(BASE, "..", "manuscript", "interval_summary.txt")


def pct(vals, p):
    vals = sorted(vals)
    return vals[int(round(p / 100.0 * (len(vals) - 1)))]


def boot_ci(vals, reps=5000):
    n = len(vals)
    means = []
    for _ in range(reps):
        s = sum(random.choice(vals) for _ in range(n)) / n
        means.append(s)
    means.sort()
    return means[int(0.025 * (reps - 1))], means[int(0.975 * (reps - 1))]


def raw_p99(path, p=99):
    lat = []
    with open(path) as fh:
        for row in csv.DictReader(fh):
            if row["status"] == "ok" and row["total_ms"]:
                lat.append(float(row["total_ms"]))
    return pct(lat, p)


def main():
    out = []

    def add(line):
        out.append(line)

    add("== Round-level summary (independent runs; percentile bootstrap 95% CI, indicative) ==\n")

    # Knee: HTTP P99 at L3 / L4 across five sweep rounds
    rounds = ["C", "r2", "r3", "r4", "r5"]
    for lvl in (3, 4):
        vals = []
        for r in rounds:
            fn = "C%d_http.raw" % lvl if r == "C" else "%s_L%d_http.raw" % (r, lvl)
            vals.append(raw_p99(os.path.join(DATA, fn)))
        lo, hi = boot_ci(vals)
        add("knee L%d HTTP P99: runs=%s mean=%.2f CI95=[%.2f, %.2f] range=[%.2f, %.2f]" %
            (lvl, ["%.2f" % v for v in vals], sum(vals) / len(vals), lo, hi, min(vals), max(vals)))

    # Censoring: seven cycles
    recs = []
    for f in ("censor_c3.jsonl", "censor_c4.jsonl", "censor_c5.jsonl"):
        recs += [json.loads(l) for l in open(os.path.join(DATA, f))]
    naive = [r["naive_sum_cores"] for r in recs]
    aware = [r["aware_sum_cores"] for r in recs]
    rel = [(r["released_phase"].get("http") or {}).get("p99_ms", 0) for r in recs]
    q = [(r["quota_phase"].get("http") or {}).get("p99_ms", 0) for r in recs]
    add("censoring naive estimate: n=%d mean=%.2f CI95=[%.2f, %.2f]" %
        (len(naive), sum(naive) / len(naive), *boot_ci(naive)))
    add("censoring aware estimate: n=%d mean=%.2f CI95=[%.2f, %.2f]" %
        (len(aware), sum(aware) / len(aware), *boot_ci(aware)))
    add("censoring released HTTP P99: n=%d mean=%.2f CI95=[%.2f, %.2f] range=[%.2f, %.2f]" %
        (len(rel), sum(rel) / len(rel), *boot_ci(rel), min(rel), max(rel)))
    add("censoring quota   HTTP P99: n=%d mean=%.2f CI95=[%.2f, %.2f] range=[%.2f, %.2f]" %
        (len(q), sum(q) / len(q), *boot_ci(q), min(q), max(q)))

    # Synthesis passes
    http, redis = [], []
    for p in ("syn1", "syn2", "syn3", "syn4"):
        http.append(raw_p99(os.path.join(DATA, "syn_%s_http.raw" % p)))
        redis.append(raw_p99(os.path.join(DATA, "syn_%s_redis.raw" % p)))
    add("synthesis HTTP P99: passes=%s mean=%.2f CI95=[%.2f, %.2f]" %
        (["%.2f" % v for v in http], sum(http) / len(http), *boot_ci(http)))
    add("synthesis Redis P99: passes=%s mean=%.2f CI95=[%.2f, %.2f]" %
        (["%.2f" % v for v in redis], sum(redis) / len(redis), *boot_ci(redis)))

    with open(OUT, "w") as fh:
        fh.write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
