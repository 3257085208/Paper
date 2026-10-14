#!/usr/bin/env python3
"""Aggregate sweep raw files into per-level latency stats (mean and range over rounds).

Reads the per-request raw files written by tools/probe.py on the probe VM:
  C<L>_<svc>.raw          (round 1, tag "C")
  r<r>_L<L>_<svc>.raw     (rounds r2/r3/r4)
and prints per (service, level) the mean and min-max of p50/p99/p999 across rounds.

Usage: python3 tools/analyze_curve.py research_data/berohost_pilot
"""

from __future__ import annotations

import os
import statistics as st
import sys

ROUNDS = ["C", "r2", "r3", "r4", "r5"]
SERVICES = ["http", "redis"]
LEVELS = range(6)


def pct(vals, p):
    vals = sorted(vals)
    if not vals:
        return None
    k = int(round((p / 100.0) * (len(vals) - 1)))
    return vals[k]


def stats_for(path):
    lat = []
    ok = timeouts = errors = 0
    with open(path) as fh:
        next(fh)
        for line in fh:
            parts = line.rstrip("\n").split(",")
            if len(parts) != 5:
                continue
            status = parts[4]
            if status == "ok":
                ok += 1
                lat.append(float(parts[3]))
            elif status == "timeout":
                timeouts += 1
            else:
                errors += 1
    return {
        "n": ok + timeouts + errors,
        "ok": ok,
        "timeouts": timeouts,
        "errors": errors,
        "p50": pct(lat, 50),
        "p99": pct(lat, 99),
        "p999": pct(lat, 99.9),
    }


def mean_range(rows, key):
    vals = [s[key] for _, s in rows]
    return st.mean(vals), min(vals), max(vals)


def main():
    d = sys.argv[1]
    print("svc   lvl runs | p50 mean        range | p99 mean        range | p999 mean       range | timeouts")
    print("-" * 108)
    for svc in SERVICES:
        for lvl in LEVELS:
            rows = []
            for r in ROUNDS:
                fn = f"C{lvl}_{svc}.raw" if r == "C" else f"{r}_L{lvl}_{svc}.raw"
                path = os.path.join(d, fn)
                if os.path.exists(path):
                    rows.append((r, stats_for(path)))
            if not rows:
                continue
            p50 = mean_range(rows, "p50")
            p99 = mean_range(rows, "p99")
            p999 = mean_range(rows, "p999")
            tos = sum(s["timeouts"] for _, s in rows)
            print(
                f"{svc:5} {lvl:3} {len(rows):4} | "
                f"{p50[0]:7.2f} {p50[1]:6.2f}-{p50[2]:5.2f} | "
                f"{p99[0]:7.2f} {p99[1]:6.2f}-{p99[2]:5.2f} | "
                f"{p999[0]:7.2f} {p999[1]:6.2f}-{p999[2]:6.2f} | "
                f"{tos}"
            )


if __name__ == "__main__":
    main()
