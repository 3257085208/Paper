#!/usr/bin/env python3
"""Mass-repeat figures from the BeroHost v2 campaign (50/90/24 rounds).

Reads research_data/v2_analysis/, writes PNGs into manuscript/figs/:
  fig17_knee_repeat.png, fig18_censor_repeat.png, fig19_syn_repeat.png
Run:  python3 manuscript/figs/make_v2_figs.py
"""

from __future__ import annotations

import glob
import json
import os
import random
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                    "research_data", "v2_analysis")
OUT = os.path.dirname(os.path.abspath(__file__))
SLO = 10.0

random.seed(7)


def load_knee():
    rounds = {}
    for fn in sorted(glob.glob(os.path.join(BASE, "knee_v2knee_r*.jsonl"))):
        for line in open(fn):
            o = json.loads(line)
            rid = int(o["round"].split("_r")[1])
            rounds.setdefault(o["level"], []).append((rid, o))
    return rounds


def fig17_knee_repeat():
    rounds = load_knee()

    def series(lvl, rid_min=None):
        out = []
        for rid, o in rounds[lvl]:
            if rid_min and rid < rid_min:
                continue
            out.append(o)
        return out

    eff = [
        ("0", series(0)), ("1", series(1)), ("2", series(2)),
        ("3", series(3) + series(4, rid_min=3)), ("4", series(5, rid_min=3)),
    ]

    fig, axes = plt.subplots(1, 2, figsize=(10, 3.9), sharey=True)
    for ax, svc in zip(axes, ("http", "redis")):
        data = [[o[svc]["p99_ms"] for o in recs if o[svc]] for _, recs in eff]
        bp = ax.boxplot(data, positions=range(len(eff)), widths=0.5,
                        patch_artist=True, showfliers=False,
                        medianprops=dict(color="black"))
        for patch in bp["boxes"]:
            patch.set_facecolor("#cfe0f5")
            patch.set_alpha(0.85)
        for i, (_, recs) in enumerate(eff):
            vals = [o[svc]["p99_ms"] for o in recs if o[svc]]
            xs = [i + random.uniform(-0.16, 0.16) for _ in vals]
            ax.scatter(xs, vals, s=7, color="#2458a6", alpha=0.45, zorder=3)
        ax.axhline(SLO, color="k", linestyle=":", linewidth=1)
        ax.text(len(eff) - 1.45, SLO + 0.8, "SLO 10 ms", fontsize=8)
        ax.set_xticks(range(len(eff)))
        ax.set_xticklabels([lbl for lbl, _ in eff])
        ax.set_xlabel("pegged neighbors actually running")
        ax.set_title("svc-%s" % svc, fontsize=10)
        ax.grid(alpha=0.3, axis="y")
    axes[0].set_ylabel("service P99 per round (ms)")
    n3 = len(series(3)) + len(series(4, rid_min=3))
    n4 = len(series(5, rid_min=3))
    axes[0].text(0.02, 0.93, "n per point: 50 / 50 / 50 / %d / %d rounds" % (n3, n4),
                 transform=axes[0].transAxes, fontsize=8)
#     fig.suptitle("BeroHost v2: 50-round knee repeat — every 4-neighbor round violates "
#                  "(P99 > 20 ms), 3-neighbor stays at ~7 ms", fontsize=10)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig17_knee_repeat.png"), dpi=400)
    plt.close(fig)
    print("fig17 ok")


def fig18_censor_repeat():
    qp, rp = [], []
    for fn in sorted(glob.glob(os.path.join(BASE, "censor_v2cen_r*.jsonl"))):
        for line in open(fn):
            o = json.loads(line)
            qp.append(o["quota_phase"]["http"]["p99_ms"])
            rp.append(o["released_phase"]["http"]["p99_ms"])

    fig, axes = plt.subplots(1, 2, figsize=(10, 3.9))
    ax = axes[0]
    data = [qp, rp]
    bp = ax.boxplot(data, positions=[0, 1], widths=0.5, patch_artist=True,
                    showfliers=False, medianprops=dict(color="black"))
    for patch, col in zip(bp["boxes"], ("#cfe0f5", "#f5cfcf")):
        patch.set_facecolor(col)
        patch.set_alpha(0.85)
    for i, vals in enumerate(data):
        xs = [i + random.uniform(-0.16, 0.16) for _ in vals]
        ax.scatter(xs, vals, s=7, color="#2458a6", alpha=0.3, zorder=3)
    ax.axhline(SLO, color="k", linestyle=":", linewidth=1)
    ax.text(1.35, SLO + 0.6, "SLO 10 ms", fontsize=8)
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["quota phase\n(4 tenants @50%)", "released phase\n(quota lifted)"])
    ax.set_ylabel("service HTTP P99 per cycle (ms)")
    ax.set_title("n=%d cycles: released phase violates 100%%" % len(qp), fontsize=10)
    ax.grid(alpha=0.3, axis="y")

    ax = axes[1]
    ax.bar([0, 1, 2], [2.0, 4.0, 4.0], width=0.5,
           color=["#b8b8b8", "#2458a6", "#2e8b57"])
    ax.axhline(4.0, color="k", linestyle=":", linewidth=1)
    ax.text(0.02, 4.3, "true demand = 4 x 1.0 cores", fontsize=8, va="bottom", ha="left")
    ax.set_xticks([0, 1, 2])
    ax.set_xticklabels(["naive sum\n(usage panel)", "censoring-aware\nestimate", "truth"])
    ax.set_ylabel("aggregate demand estimate (cores)")
#     ax.set_title("Usage panel under-reports by 2x; throttle evidence recovers truth",
#                  fontsize=10)
    ax.set_ylim(0, 5)
    ax.grid(alpha=0.3, axis="y")
    for x, v in zip([0, 1, 2], [2.0, 4.0, 4.0]):
        ax.text(x, v + 0.08, "%.2f" % v, ha="center", fontsize=9)

#     fig.suptitle("BeroHost v2: censoring repeat, 30 rounds x 3 cycles = 90 (identical "
#                  "verdict every cycle)", fontsize=10)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig18_censor_repeat.png"), dpi=400)
    plt.close(fig)
    print("fig18 ok")


V3 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                  "research_data", "phys8269_pilot", "v3")


def fig19_syn_repeat():
    http, redis, to = [], [], 0
    for fn in sorted(glob.glob(os.path.join(V3, "synthesis_v3syn_r*.jsonl"))):
        for line in open(fn):
            o = json.loads(line)
            if o.get("http"):
                http.append(o["http"]["p99_ms"])
                to += o["http"]["timeouts"]
            if o.get("redis"):
                redis.append(o["redis"]["p99_ms"])

    fig, ax = plt.subplots(figsize=(9, 3.6))
    xs = list(range(1, len(http) + 1))
    bad = [x for x, v in zip(xs, http) if v > SLO]
    ax.plot(xs, http, "o-", color="tab:blue", markersize=5, label="HTTP P99")
    for b in bad:
        ax.annotate("degraded round\n(8 tenants missing)", xy=(b, http[b - 1]),
                    xytext=(b - 6.5, http[b - 1] + 1.5), fontsize=8, color="tab:red",
                    arrowprops=dict(arrowstyle="->", color="tab:red", lw=0.9))
    ax.plot(xs, redis, "s--", color="tab:orange", markersize=5, alpha=0.8,
            label="Redis P99")
    ax.axhline(SLO, color="k", linestyle=":", linewidth=1)
    ax.text(1, 9.45, "SLO 10 ms", fontsize=8)
    ax.axhline(statistics.mean(http), color="tab:blue", linewidth=0.8, alpha=0.4,
               linestyle="--")
    ax.axhline(statistics.mean(redis), color="tab:orange", linewidth=0.8, alpha=0.4,
               linestyle="--")
    ax.set_xlabel("repeat round (16 tenants, three storms at once)")
    ax.set_ylabel("service P99 (ms)")
#     ax.set_title("BeroHost rework: %d-round combined-stress repeat — HTTP mean %.2f ms "
#                  "[%.2f-%.2f], %d/%d below SLO, zero timeouts" % (
#                      len(http), statistics.mean(http), min(http), max(http),
#                      sum(1 for x in http if x <= SLO), len(http)), fontsize=10)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig19_syn_repeat.png"), dpi=400)
    plt.close(fig)
    print("fig19 ok")



def fig29_knee_v3():
    import collections
    per = collections.defaultdict(list)
    per_r = collections.defaultdict(list)
    for fn in sorted(glob.glob(os.path.join(V3, "knee_v3knee_r*.jsonl"))):
        for line in open(fn):
            o = json.loads(line)
            per[o["level"]].append(o["http"]["p99_ms"])
            per_r[o["level"]].append(o["redis"]["p99_ms"])
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.9), sharey=True)
    for ax, d, svc in zip(axes, (per, per_r), ("http", "redis")):
        levels = sorted(d)
        data = [d[l] for l in levels]
        bp = ax.boxplot(data, positions=range(len(levels)), widths=0.5,
                        patch_artist=True, showfliers=False,
                        medianprops=dict(color="black"))
        for patch in bp["boxes"]:
            patch.set_facecolor("#f5d8c8")
            patch.set_alpha(0.9)
        for i, l in enumerate(levels):
            vals = d[l]
            xs = [i + random.uniform(-0.16, 0.16) for _ in vals]
            ax.scatter(xs, vals, s=7, color="#b6552a", alpha=0.45, zorder=3)
        ax.axhline(SLO, color="k", linestyle=":", linewidth=1)
        ax.text(0.05, SLO + 0.8, "SLO 10 ms", fontsize=8)
        ax.set_xticks(range(len(levels)))
        ax.set_xticklabels([str(l) for l in levels])
        ax.set_xlabel("commanded pegged neighbors (all 5 online throughout)")
        ax.set_title("svc-%s" % svc, fontsize=10)
        ax.grid(alpha=0.3, axis="y")
    axes[0].set_ylabel("service P99 per round (ms)")
    axes[0].text(0.02, 0.93, "n = 50 rounds per level", transform=axes[0].transAxes, fontsize=8)
#     fig.suptitle("BeroHost v3 knee rework (all neighbors online): L2 clean (<=8.0 ms), "
#                  "L3 already violates in 45/50 rounds", fontsize=10)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig29_knee_v3.png"), dpi=400)
    plt.close(fig)
    print("fig29 ok")


if __name__ == "__main__":
    fig17_knee_repeat()
    fig18_censor_repeat()
    fig19_syn_repeat()
    fig29_knee_v3()
    print("v2 repeat figures written to", OUT)
