#!/usr/bin/env python3
"""fig1: study pipeline (Identify -> Predict -> Actuate) with the observation set."""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                   "manuscript", "figs", "fig1_pipeline.png")

fig, ax = plt.subplots(figsize=(9.6, 3.4))
ax.set_xlim(0, 10)
ax.set_ylim(0, 3.6)
ax.axis("off")

boxes = [
    (0.25, "Identify", "censored demand", "quota + throttle counters\npoint estimate + conditional floor"),
    (3.60, "Predict", "phase-structured capacity", "joint 1-s phase profiles\napproximation + PPC + online gate"),
    (6.95, "Actuate", "risk-calibrated admission", "reserve accounting + pause guards\n14-round comparison"),
]
w, h, y0 = 2.8, 1.7, 1.55
for x, t, sub, body in boxes:
    ax.add_patch(FancyBboxPatch((x, y0), w, h, boxstyle="round,pad=0.08",
                                linewidth=1.1, edgecolor="#2b4a6f", facecolor="#eef2f7"))
    ax.text(x + w / 2, y0 + h - 0.32, t, ha="center", va="center", fontsize=13,
            fontweight="bold", color="#1c3a5e")
    ax.text(x + w / 2, y0 + h - 0.72, sub, ha="center", va="center", fontsize=9.5,
            style="italic", color="#333")
    ax.text(x + w / 2, y0 + 0.42, body, ha="center", va="center", fontsize=8.4, color="#222")

for x in (3.05, 6.40):
    ax.add_patch(FancyArrowPatch((x + 0.06, y0 + h / 2), (x + 0.49, y0 + h / 2),
                                 arrowstyle="-|>", mutation_scale=16, linewidth=1.4,
                                 color="#2b4a6f"))

# title text removed per JNSM figure policy
ax.text(5.0, 1.12, "minimal observation set   |   quota+throttle evidence   |   joint phase profiles (>=1 s)   |   "
        "sampling >= burst width",
        ha="center", fontsize=8.6, color="#555")
ax.add_patch(FancyBboxPatch((0.25, 0.35), 9.5, 0.55, boxstyle="round,pad=0.06",
                            linewidth=0.8, edgecolor="#8aa2bd", facecolor="#f7f9fc"))
ax.text(5.0, 0.625, "failures if missing:  wrong demand -> bad release (90/90 violations)   |   "
        "phase-blind -> oversell 40 in sync (P5 16%)   |   coarse sampling -> stop drift 28<->40",
        ha="center", fontsize=8.4, color="#333")
fig.tight_layout()
fig.savefig(OUT, dpi=400)
print("fig1 ok")
