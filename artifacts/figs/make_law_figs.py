#!/usr/bin/env python3
"""Density-law figure (fig21): predicted N*(phi) vs measured safe capacity.

Left: the law N* = C / (phi + (1-phi)*rho) with measured points from the
mixed-phase ladders (capmix; safety = P5 >= 70% bar) plus the same-phase/sync
anchors from the sell ladders. Right: P5 vs admitted N for each phi with the
70% bar and the predicted N* marked (shows both the law and the noise).

Missing files are skipped gracefully (f75 arrives later).

Run: python3 manuscript/figs/make_law_figs.py
"""

from __future__ import annotations

import json
import os
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                    "research_data", "phys8269_pilot")
OUT = os.path.dirname(os.path.abspath(__file__))
BASE_RATE = 25.9e6
C = 8
RHO = 0.20
BAR = 70.0


def per_level(fn):
    out = {}
    p = os.path.join(BASE, fn)
    if not os.path.exists(p):
        return out
    for line in open(p):
        o = json.loads(line)
        per = {}
        for rnd in o.get("rate_rounds") or []:
            for vmid, rate, state in rnd:
                if rate and state == 1:
                    per[vmid] = max(per.get(vmid, 0), rate)
        if per:
            vals = sorted(x / BASE_RATE * 100 for x in per.values())
            out[o["level"]] = (statistics.median(vals), vals[int(0.05 * (len(vals) - 1))], len(vals))
    return out


def law(phi):
    return C / (phi + (1 - phi) * RHO)


def last_pass(d):
    ok = None
    for lvl in sorted(d):
        if d[lvl][1] >= BAR:
            ok = lvl
        else:
            break
    return ok


def main():
    phi_files = [
        (0.00, ["sell_sell_rand.jsonl", "sell_sell_rand_r2.jsonl",
                "sell_sell_rand_r4.jsonl", "sell_sell_rand_r5.jsonl"]),
        (0.25, ["sell_capmix_f25.jsonl", "sell_capmix_f25_r2.jsonl", "sell_capmix_f25_r3.jsonl"]),
        (0.50, ["sell_capmix_f50.jsonl", "sell_capmix_f50_r2.jsonl", "sell_capmix_f50_r3.jsonl"]),
        (0.75, ["sell_capmix_f75.jsonl", "sell_capmix_f75_r2.jsonl", "sell_capmix_f75_r3.jsonl"]),
        (1.00, ["sell_sell_sync.jsonl", "sell_sell_sync_r2.jsonl",
                "sell_sell_sync_r3_clean.jsonl", "sell_sell_sync_r4.jsonl"]),
    ]
    merged = {}
    for phi, files in phi_files:
        d = {}
        for fn in files:
            for lvl, (p50, p5, n) in per_level(fn).items():
                prev = d.setdefault(lvl, ([], []))
                prev[0].append(p50)
                prev[1].append(p5)
        if d:
            merged[phi] = {lvl: (statistics.mean(a), statistics.mean(b))
                           for lvl, (a, b) in d.items()}

    fig, axes = plt.subplots(1, 2, figsize=(10.5, 3.9))
    ax = axes[0]
    xs = [i / 100.0 for i in range(0, 101)]
    ax.plot(xs, [law(x) for x in xs], "-", color="tab:red", linewidth=1.6,
            label=r"law  $N^* = C\,/\,(\varphi + (1-\varphi)\rho)$")
    for phi, d in merged.items():
        cap = last_pass(d)
        if cap is None:
            continue
        ax.scatter([phi], [cap], s=55, zorder=4, color="tab:blue",
                   label="measured safe N (P5 >= 70% bar)" if phi == 0.0 else None)
        # median-bar capacity (P50 >= 90%) — relevant for the random anchor
        mcap = None
        for lvl in sorted(d):
            if d[lvl][0] >= 90:
                mcap = lvl
            else:
                break
        if mcap is not None and phi == 0.0:
            ax.scatter([phi], [mcap], s=55, zorder=4, facecolors="none",
                       edgecolors="tab:blue", linestyle="--",
                       label="same data at median bar (P50 >= 90%)")
            ax.annotate("random: P5 bar is tail-limited;\nlaw tracks the median-bar limit",
                        xy=(0.02, mcap), xytext=(0.10, 36),
                        fontsize=7.5, arrowprops=dict(arrowstyle="->", lw=0.8))
    ax.set_xlabel(r"aligned fraction $\varphi$ (duty $\rho$ = 0.20, pool C = 8)")
    ax.set_ylabel("safe tenants")
    ax.set_title("capacity law vs measurement", fontsize=10)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7.5, loc="upper right")

    ax = axes[1]
    colors = {0.25: "tab:green", 0.50: "tab:orange", 0.75: "tab:purple"}
    for phi, d in merged.items():
        if phi not in colors:
            continue
        lvls = sorted(d)
        ax.plot(lvls, [d[l][1] for l in lvls], "o-", color=colors[phi],
                markersize=5, label=r"$\varphi$=%.2f" % phi)
        ax.axvline(law(phi), color=colors[phi], linestyle=":", linewidth=1)
    ax.axhline(BAR, color="k", linestyle="--", linewidth=1)
    ax.text(8.5, BAR + 1.5, "primary bar P5 >= 70%", fontsize=8)
    ax.set_xlabel("admitted tenants N")
    ax.set_ylabel("customer P5 (% of solo baseline)")
    ax.set_title("per-level P5 with predicted N* (dotted, per phi)", fontsize=10)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="lower left")

#     fig.suptitle("Density law on the physical host: same duty, arrangement sets capacity "
#                  "(mixed-phase ladders + anchors)", fontsize=10)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig21_density_law.png"), dpi=400)
    plt.close(fig)
    print("fig21 ok; phis measured:", sorted(merged))


if __name__ == "__main__":
    main()
