#!/usr/bin/env python3
"""Customer-P5 metric-convention robustness check (zero machine time).

Recomputes the ladder results under four per-customer aggregation conventions,
all using the FULL stored sampling series (rate_rounds):
  max    : per-customer max over active samples (the current paper convention)
  median : per-customer median over active samples (typical sustained rate)
  t5     : per-customer 5th percentile over active samples (time-domain P5)
  min    : per-customer min over active samples (worst observed instant)
Cross-customer statistic: 5th percentile across customers (the paper's P5).

Outputs: research_data/P5_CONVENTION_CHECK.md
"""

from __future__ import annotations

import io
import json
import os
import statistics

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                    "research_data", "phys8269_pilot")
OUT = os.path.join(BASE, "P5_CONVENTION_CHECK.md")
BR = 25.9e6

FILES = {
    "sync": ["sell_sell_sync.jsonl", "sell_sell_sync_r2.jsonl",
             "sell_sell_sync_r3.jsonl", "sell_sell_sync_r4.jsonl"],
    "rand": ["sell_sell_rand.jsonl", "sell_sell_rand_r2.jsonl",
             "sell_sell_rand_r4.jsonl", "sell_sell_rand_r5.jsonl"],
    "mix25": ["sell_capmix_f25.jsonl", "sell_capmix_f25_r2.jsonl", "sell_capmix_f25_r3.jsonl"],
    "mix50": ["sell_capmix_f50.jsonl", "sell_capmix_f50_r2.jsonl", "sell_capmix_f50_r3.jsonl"],
    "mix75": ["sell_capmix_f75.jsonl", "sell_capmix_f75_r2.jsonl", "sell_capmix_f75_r3.jsonl"],
}


def pct(vals, p):
    v = sorted(vals)
    return v[int(p / 100 * (len(v) - 1))] if v else None


def per_round_vm_series(cfg, level):
    """Yield per-round {vmid: [active rates]} (matches the paper's per-round structure)."""
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
                    if state == 1 and rate and rate > 0:
                        per.setdefault(vmid, []).append(rate / BR * 100)
            if per:
                yield per


def per_vm_aggregates(cfg, level):
    """Pooled per-round aggregates: {convention: [per-round per-VM values]}."""
    out = {"max": [], "median": [], "t5": [], "min": []}
    for per in per_round_vm_series(cfg, level):
        for v in per.values():
            out["max"].append(max(v))
            out["median"].append(statistics.median(v))
            out["t5"].append(pct(v, 5))
            out["min"].append(min(v))
    return out


def conventions(pooled):
    """Cross-customer P5 of each pooled convention."""
    return {name: pct(vals, 5) for name, vals in pooled.items()}


def main():
    lines = ["# 客户 P5 口径稳健性重算（零机时）", ""]
    lines.append("逐台按活跃样本聚合（max / median / min / 时间 P5），再取**跨客户第 5 百分位**。"
                 "数据：全部阶梯轮（含 18 点/台时间序列）。")
    key = {"sync": [4, 8, 10, 12, 14, 16], "rand": [16, 24, 28, 32, 40],
           "mix25": [20, 24, 28], "mix50": [13, 16], "mix75": [10, 13]}
    for cfg, levels in key.items():
        lines.append("")
        lines.append("## %s" % cfg)
        lines.append("")
        lines.append("| N | 轮数(池化) | max | median | t5 | min |")
        lines.append("|---|---|---|---|---|---|")
        for lvl in levels:
            pooled = per_vm_aggregates(cfg, lvl)
            if not pooled["max"]:
                continue
            nrounds = sum(1 for _ in per_round_vm_series(cfg, lvl))
            nsamp = nrounds
            c = conventions(pooled)
            fmt = lambda x: ("%.1f" % x) if x is not None else "—"
            lines.append("| %d | %d | %s | %s | %s | %s |" % (
                lvl, nsamp, fmt(c["max"]), fmt(c["median"]), fmt(c["t5"]), fmt(c["min"])))
    # boundaries at the 70% bar per convention
    lines.append("")
    lines.append("## 安全容量边界（P5 ≥ 70%，按各口径）")
    lines.append("")
    lines.append("| 配置 | max（现行） | median | t5 | min |")
    lines.append("|---|---|---|---|---|")
    for cfg in ("sync", "rand", "mix25", "mix50", "mix75"):
        all_lv = sorted({o["level"] for fn in FILES[cfg]
                         for idx, line in enumerate(open(os.path.join(BASE, fn)))
                         if not (fn == "sell_sell_sync_r3.jsonl" and idx < 6)
                         for o in [json.loads(line)]})
        row = []
        for conv in ("max", "median", "t5", "min"):
            lp = None
            for lvl in all_lv:
                pooled = per_vm_aggregates(cfg, lvl)
                if not pooled["max"]:
                    continue
                c = conventions(pooled)
                if c[conv] is not None and c[conv] >= 70:
                    lp = lvl
                else:
                    break
            row.append(str(lp) if lp is not None else "—")
        lines.append("| %s | %s | %s | %s | %s |" % (cfg, *row))
    with io.open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print("saved:", OUT)


if __name__ == "__main__":
    main()
