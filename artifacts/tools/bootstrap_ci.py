#!/usr/bin/env python3
"""Formal bootstrap / exact intervals for the core claims (data-frozen set).

Two interval families, each labeled for what it is:
  * customer-level bootstrap CI of the pooled P5 at key ladder levels
    (resamples the pooled per-customer values; sampling variability of the P5
    estimator conditional on the round pool);
  * round-level range (already in the paper) plus Clopper-Pearson intervals
    for violation probabilities (knee rework, storm).

Output: research_data/phys8269_pilot/BOOTSTRAP_CI.md
"""

from __future__ import annotations

import io
import json
import os
import random
import statistics

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                    "research_data", "phys8269_pilot")
OUT = os.path.join(BASE, "BOOTSTRAP_CI.md")
BR = 25.9e6
B = 10000
random.seed(7)

FILES = {
    "sync": ["sell_sell_sync.jsonl", "sell_sell_sync_r2.jsonl",
             "sell_sell_sync_r3.jsonl", "sell_sell_sync_r4.jsonl"],
    "rand": ["sell_sell_rand.jsonl", "sell_sell_rand_r2.jsonl",
             "sell_sell_rand_r4.jsonl", "sell_sell_rand_r5.jsonl"],
    "mix25": ["sell_capmix_f25.jsonl", "sell_capmix_f25_r2.jsonl", "sell_capmix_f25_r3.jsonl"],
    "mix50": ["sell_capmix_f50.jsonl", "sell_capmix_f50_r2.jsonl", "sell_capmix_f50_r3.jsonl"],
    "mix75": ["sell_capmix_f75.jsonl", "sell_capmix_f75_r2.jsonl", "sell_capmix_f75_r3.jsonl"],
}


def pooled_values(cfg, level):
    vals = []
    for fn in FILES[cfg]:
        skip = 6 if fn == "sell_sell_sync_r3.jsonl" else 0
        for idx, line in enumerate(open(os.path.join(BASE, fn))):
            if idx < skip:
                continue
            o = json.loads(line)
            if o["level"] != level:
                continue
            per = {}
            for rnd in o.get("rate_rounds") or []:
                for vmid, rate, state in rnd:
                    if rate and state == 1:
                        per[vmid] = max(per.get(vmid, 0), rate)
            vals.extend(x / BR * 100 for x in per.values())
    return vals


def p5(vals):
    v = sorted(vals)
    return v[int(0.05 * (len(v) - 1))] if v else None


def boot_ci(vals):
    n = len(vals)
    stats = []
    for _ in range(B):
        s = [vals[random.randrange(n)] for _ in range(n)]
        stats.append(p5(s))
    stats.sort()
    return stats[int(0.025 * B)], stats[int(0.975 * B)]


def cp_interval(k, n, alpha=0.05):
    """Clopper-Pearson two-sided interval for k/n."""
    import math
    lo, hi = 0.0, 1.0
    if k > 0:
        # solve P(X>=k | lo) = alpha/2
        a, b = 0.0, 1.0
        for _ in range(80):
            m = (a + b) / 2
            tail = sum(math.comb(n, i) * m ** i * (1 - m) ** (n - i) for i in range(k, n + 1))
            if tail < alpha / 2:
                a = m
            else:
                b = m
        lo = (a + b) / 2
    if k < n:
        a, b = 0.0, 1.0
        for _ in range(80):
            m = (a + b) / 2
            tail = sum(math.comb(n, i) * m ** i * (1 - m) ** (n - i) for i in range(0, k + 1))
            if tail < alpha / 2:
                b = m
            else:
                a = m
        hi = (a + b) / 2
    return lo, hi


def main():
    lines = ["# Bootstrap / exact intervals for the core claims (frozen set)", ""]
    lines.append("Customer-level bootstrap (B=10000) of the pooled P5 estimator; "
                 "the pooled per-customer values are resampled within each level. "
                 "Small-round-count ranges are in Section 8.4.")
    lines.append("| config | level | n | P5 | 95% CI (bootstrap) |")
    lines.append("|---|---|---|---|---|")
    key_levels = {"sync": [8, 10, 16], "rand": [28, 32], "mix25": [24], "mix50": [13], "mix75": [10]}
    for cfg, levels in key_levels.items():
        for lvl in levels:
            vals = pooled_values(cfg, lvl)
            if not vals:
                continue
            lo, hi = boot_ci(vals)
            lines.append("| %s | %d | %d | %.1f | [%.1f, %.1f] |" % (
                cfg, lvl, len(vals), p5(vals), lo, hi))
    # knee v3 violation rates
    import glob
    viol3 = viol4 = n3 = n4 = 0
    for fn in sorted(glob.glob(os.path.join(BASE, "v3", "knee_v3knee_r*.jsonl"))):
        for line in open(fn):
            o = json.loads(line)
            if o["level"] == 3:
                n3 += 1
                viol3 += 1 if o["http"]["p99_ms"] > 10 else 0
            if o["level"] == 4:
                n4 += 1
                viol4 += 1 if o["http"]["p99_ms"] > 10 else 0
    lo3, hi3 = cp_interval(viol3, n3)
    lines.append("")
    lines.append("Knee rework (v3, 50 rounds/level), exact Clopper-Pearson 95% intervals for the "
                 "violation probability (P99 > 10 ms):")
    lines.append("")
    lines.append("- L3 (3 neighbors): %d/%d = %.0f%% [%.0f%%, %.0f%%]" % (
        viol3, n3, 100 * viol3 / n3, 100 * lo3, 100 * hi3))
    lines.append("- L4 (4 neighbors): %d/%d = 100%% [%.0f%%, 100%%]" % (
        viol4, n4, 100 * (cp_interval(viol4, n4)[0])))
    lines.append("")
    lines.append("Triple-storm rework: 25/26 rounds within SLO; one-sided 95% upper bound on the "
                 "violation rate ~17.0% (26-round set); combined 29/30 passes -> ~14.9% "
                 "(see Section 7.5).")
    with io.open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print("saved:", OUT)


if __name__ == "__main__":
    main()
