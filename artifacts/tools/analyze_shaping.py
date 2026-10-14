#!/usr/bin/env python3
"""Summarize the shaping pilot results (research_data/berohost_pilot/shaping_*.jsonl).

Prints, per scheme and level: host busy%, candidate burn rates (iterations/s),
service p50/p99/p999 and SLO violations; then a per-scheme summary (last safe
level, first violating level, rates at the last safe level).

Usage: python3 tools/analyze_shaping.py [data_dir]
"""

from __future__ import annotations

import glob
import json
import os
import sys

SCHEME_ORDER = ["unlimited", "q75", "q50", "pin"]


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "research_data/berohost_pilot"
    records = {}
    for path in sorted(glob.glob(os.path.join(base, "shaping_*.jsonl"))):
        for line in open(path, encoding="utf-8"):
            rec = json.loads(line)
            records[(rec["scheme"], rec["level"])] = rec

    print("scheme    lvl busy%  rates(it/s)                http(p50/p99/p999)      redis(p50/p99/p999)     viol")
    print("-" * 118)
    for scheme in SCHEME_ORDER:
        levels = sorted(lv for (sc, lv) in records if sc == scheme)
        for lv in levels:
            rec = records[(scheme, lv)]
            rates = ",".join("%.0f" % r if r else "?" for r in rec.get("burn_rates", [])) or "-"
            http = rec["windows"].get("http") or {}
            redis = rec["windows"].get("redis") or {}
            def fmt(w):
                if not w:
                    return "MISSING"
                return "%8.2f/%8.2f/%8.2f" % (w.get("p50_ms") or 0, w.get("p99_ms") or 0,
                                              w.get("p999_ms") or 0)
            viol = (http.get("violation") or redis.get("violation"))
            print("%-9s %3d %5s  %-24s  %-21s  %-21s  %s" % (
                scheme, lv,
                "%.1f" % rec["busy_pct"] if rec.get("busy_pct") is not None else "?",
                rates, fmt(http), fmt(redis), "YES" if viol else ""))
        safe = [lv for lv in levels
                if records[(scheme, lv)]["windows"].get("http", {}).get("violation") is False
                and records[(scheme, lv)]["windows"].get("redis", {}).get("violation") is False]
        viol_levels = [lv for lv in levels
                       if records[(scheme, lv)]["windows"].get("http", {}).get("violation")
                       or records[(scheme, lv)]["windows"].get("redis", {}).get("violation")]
        last_safe = max(safe) if safe else None
        first_bad = min(viol_levels) if viol_levels else None
        rates_txt = "-"
        if last_safe is not None:
            rates = records[(scheme, last_safe)].get("burn_rates", [])
            rates_txt = ",".join("%.0f" % r if r else "?" for r in rates) or "-"
        print(">> %-9s last_safe_level=%s first_violation_level=%s rates_at_last_safe=[%s]" %
              (scheme, last_safe, first_bad, rates_txt))
        print()


if __name__ == "__main__":
    main()
