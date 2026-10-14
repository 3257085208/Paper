#!/usr/bin/env python3
"""Summarize packing rounds and print per-5s latency timelines for sync rounds.

Usage: python3 tools/analyze_packing.py [data_dir]
"""

from __future__ import annotations

import glob
import json
import os
import sys


def pct(vals, p):
    if not vals:
        return None
    vals = sorted(vals)
    k = int(round((p / 100.0) * (len(vals) - 1)))
    return vals[k]


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "research_data/berohost_pilot"
    print("== packing rounds ==")
    for path in sorted(glob.glob(os.path.join(base, "packing_*.jsonl"))):
        for line in open(path, encoding="utf-8"):
            rec = json.loads(line)
            http = rec["windows"].get("http") or {}
            redis = rec["windows"].get("redis") or {}

            def fmt(w):
                if not w:
                    return "MISSING"
                return "%5.1f/%6.1f/%6.1f" % (w.get("p50_ms") or 0, w.get("p99_ms") or 0,
                                              w.get("p999_ms") or 0)
            viol = http.get("violation") or redis.get("violation")
            print("%-4s %-28s busy=%5s http=%s redis=%s %s" % (
                rec["round"], rec["profile"],
                ("%.1f" % rec["busy_pct"]) if rec.get("busy_pct") is not None else "?",
                fmt(http), fmt(redis), "VIOL" if viol else ""))

    for round_name in ("p3", "p3b"):
        fp = os.path.join(base, "pack_%s_http.raw" % round_name)
        if not os.path.exists(fp):
            continue
        print("\n== %s http latency per 5 s (bursts aligned to minute start) ==" % round_name)
        buckets = {}
        with open(fp) as fh:
            next(fh)
            for line in fh:
                parts = line.rstrip("\n").split(",")
                if len(parts) != 5 or parts[4] != "ok" or not parts[3]:
                    continue
                b = int(float(parts[0]) // 5)
                buckets.setdefault(b, []).append(float(parts[3]))
        for b in sorted(buckets):
            vals = buckets[b]
            print("t=%3ds n=%4d p50=%6.2f p99=%7.2f max=%7.2f" % (
                b * 5, len(vals), pct(vals, 50), pct(vals, 99), max(vals)))


if __name__ == "__main__":
    main()
