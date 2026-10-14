#!/usr/bin/env python3
"""Pooled sell-ladder analysis (Mac-side).

Pools all CLEAN ladder rounds per phase, filtering the void shuffled-order
series (add-only defect) by sanity-checking active counts per level.

Sync clean series: r1 (coarse 4-32), tonight fine r2 (4-16), fine r3 (4-16),
fine r4 (4-16, 90 s collect).
Rand clean series: coarse r1 + r2 (8-64), fine r4 + r5 (16-32).

Prints per-level p50/p5/n and the values needed for the Section 7.4b table
(customer P5 at the sync stop points 8 and 16).
"""

from __future__ import annotations

import json
import os
import statistics

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                    "research_data", "phys8269_pilot")
BASE_RATE = 25.9e6

SYNC_FILES = ["sell_sell_sync.jsonl", "sell_sell_sync_r2.jsonl",
              "sell_sell_sync_r3.jsonl", "sell_sell_sync_r4.jsonl"]
RAND_FILES = ["sell_sell_rand.jsonl", "sell_sell_rand_r2.jsonl",
              "sell_sell_rand_r4.jsonl", "sell_sell_rand_r5.jsonl"]


VOID_SKIP = {"sell_sell_sync_r3.jsonl": 6}  # first 6 records = void shuffled series


def pool(files):
    out = {}
    for fn in files:
        skip = VOID_SKIP.get(fn, 0)
        for idx, line in enumerate(open(os.path.join(BASE, fn))):
            if idx < skip:
                continue
            o = json.loads(line)
            per = {}
            active = set()
            for rnd in o.get("rate_rounds") or []:
                for vmid, rate, state in rnd:
                    if state == 1:
                        active.add(vmid)
                    if rate and state == 1:
                        per[vmid] = max(per.get(vmid, 0), rate)
            lvl = o["level"]
            # sanity filter: void add-only records show active >> level
            if len(active) > lvl + 2:
                continue
            if not per:
                continue
            out.setdefault(lvl, []).extend(x / BASE_RATE * 100 for x in per.values())
    return out


def table(d):
    print("  level   n    p50     p5")
    for lvl in sorted(d):
        vals = sorted(d[lvl])
        p50 = statistics.median(vals)
        p5 = vals[int(0.05 * (len(vals) - 1))]
        print("  %5d  %3d  %6.1f  %6.1f" % (lvl, len(vals), p50, p5))
    return d


def p5_at(d, lvl):
    vals = sorted(d[lvl])
    return vals[int(0.05 * (len(vals) - 1))]


if __name__ == "__main__":
    print("== SYNC pooled (clean rounds: r1 coarse + fine r2/r3/r4) ==")
    s = table(pool(SYNC_FILES))
    print("== RAND pooled (clean rounds: coarse r1/r2 + fine r4/r5) ==")
    r = table(pool(RAND_FILES))
    print()
    print("Section 7.4b needs:")
    print("  sync customer P5 at N=8 : %.1f%%  (n=%d)" % (p5_at(s, 8), len(s[8])))
    print("  sync customer P5 at N=16: %.1f%%  (n=%d)" % (p5_at(s, 16), len(s[16])))
    if 10 in s:
        print("  sync customer P5 at N=10: %.1f%% (n=%d)" % (p5_at(s, 10), len(s[10])))
    if 12 in s:
        print("  sync customer P5 at N=12: %.1f%% (n=%d)" % (p5_at(s, 12), len(s[12])))
