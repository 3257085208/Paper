#!/usr/bin/env python3
"""Fig 20: online admission showdown (7 policies x 2 phases).

Reads admit_show2_<phase>_<policy>.jsonl (the clean rerun); falls back to
admit_show_*_zramcontam.jsonl only if the clean files are absent (marked).
Plots in one panel: seats stopped per policy (bars) with over-admission
markers; horizontal oracle line at the measured primary-bar capacity
(rand 24 / sync 8, brackets from the sell ladders).
Run: python3 manuscript/figs/make_showdown_fig.py
"""
from __future__ import annotations
import glob, json, os, re
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "research_data", "phys8269_pilot")
OUT = os.path.dirname(os.path.abspath(__file__))
POLICIES = ["worstcase", "quantile", "audible", "fixed", "ours_p", "ours", "util80"]
ORACLE = {"rand": (24, 32), "sync": (8, 12)}

def load(phase, policy):
    pats = [os.path.join(BASE, "admit_show5_%s_%s*.jsonl" % (phase, policy)),
            os.path.join(BASE, "admit_show2_%s_%s*.jsonl" % (phase, policy)),
            os.path.join(BASE, "admit_show_%s_%s_zramcontam.jsonl" % (phase, policy))]
    for pat in pats:
        files = sorted(glob.glob(pat))
        if files:
            rows = [json.loads(l) for l in open(files[0])]
            return rows, ("zramcontam" in files[0])
    return None, None

def main():
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 3.9), sharey=True)
    for ax, phase in zip(axes, ("rand", "sync")):
        lo, hi = ORACLE[phase]
        ax.axhspan(lo, hi, color="tab:blue", alpha=0.12, label="measured bracket [%d,%d)" % (lo, hi))
        ax.axhline(lo, color="tab:blue", linestyle="--", linewidth=1)
        stops, flags = [], []
        for p in POLICIES:
            rows, contaminated = load(phase, p)
            if rows:
                stops.append(rows[-1]["n"])
                flags.append(contaminated)
            else:
                stops.append(0); flags.append(False)
        colors = ["tab:gray" if f else "tab:green" for f in flags]
        if any(stops):
            ax.bar(range(len(POLICIES)), stops, color=colors, alpha=0.85)
            for i, (p, s) in enumerate(zip(POLICIES, stops)):
                if s:
                    ax.text(i, s + 0.3, str(s), ha="center", fontsize=8)
        else:
            ax.text(0.5, 0.5, "sync phase running — first rounds landing",
                    transform=ax.transAxes, ha="center", color="gray")
        ax.set_xticks(range(len(POLICIES)))
        ax.set_xticklabels(POLICIES, rotation=25, ha="right", fontsize=8.5)
        ax.set_title("phase = %s" % phase, fontsize=10)
        ax.grid(alpha=0.3, axis="y")

    axes[0].set_ylabel("seats admitted at stop")
    axes[0].legend(fontsize=7.5, loc="upper left")
    fig.suptitle("Online admission comparison: seats sold vs measured safe-capacity bracket "
                 "(green = clean run; gray = zram-contaminated, archived)", fontsize=10)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig20_showdown.png"), dpi=200)
    plt.close(fig)
    print("fig20 ok")

if __name__ == "__main__":
    main()
