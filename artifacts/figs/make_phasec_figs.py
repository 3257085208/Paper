#!/usr/bin/env python3
"""Phase C resource-efficiency figures (fig22-26).

fig22: micro-period quota precision (qp2c)
fig23: KSM fleet dedup timeline (ksm1)
fig24: free-page reporting reclaim (fpr5)
fig25: swap arms — zram absorbs, disk insufficient (zram3b)
fig26: tenant IO storm vs service (ioc2)

Run: python3 manuscript/figs/make_phasec_figs.py
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
SLO = 10.0


def load(fn):
    return [json.loads(l) for l in open(os.path.join(BASE, fn))]


def fig22():
    rows = load("qp2v_qp2v1.jsonl")
    order = {"uncapped": 0, "2ms": 1, "1s": 2}
    rows = sorted(rows, key=lambda r: order[r["config"]])
    xs, ys, svc = [], [], []
    for r in rows:
        xs.append(1)
        ys.append(statistics.mean(x["rate_M"] for x in r["rows"]) / (25.8 / 100.0))
        svc.append(None)
    labels = [("uncapped" if r["config"] == "uncapped" else r["config"]) for r in rows]
    fig, ax = plt.subplots(figsize=(6.6, 3.6))
    bars = ax.bar(range(len(xs)), ys, color="tab:blue", alpha=0.85, width=0.55)
    for i, b in enumerate(bars):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 1.2, "%.0f%%" % ys[i],
                ha="center", fontsize=9)
    ax.axhline(50, color="tab:red", linestyle=":", linewidth=1)
    ax.text(0.02, 52, "quota (50%)", fontsize=8, color="tab:red")
    ax.set_xticks(range(len(xs)))
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_xlabel("50% quota: period 2 ms vs 1 s (clean re-measurement, qp2v1)")
    ax.set_ylabel("tenant rate (% of uncapped)")
    ax.set_ylim(0, 118)
#     ax.set_title("Self-audit correction: 2 ms and 1 s deliver identically (~52%)\n"
#                  "the earlier \"+35%\" claim was a windowing artifact and is withdrawn",
#                  fontsize=9.5)
    ax.grid(alpha=0.25, axis="y")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig22_microperiod.png"), dpi=200)
    plt.close(fig)
    print("fig22 ok")


def fig23():
    rows = load("ksm_ksm1.jsonl")
    rows = sorted(rows, key=lambda r: r["t"])
    t = [r["t"] for r in rows]
    share = [r.get("sharing_mb", 0) / 1024.0 for r in rows]
    ticks = [r.get("ksmd_cpu_ticks", 0) for r in rows]
    cores = []
    for i in range(len(rows)):
        if i == 0:
            cores.append(0.0)
        else:
            dt = max(0.1, t[i] - t[i - 1])
            cores.append((ticks[i] - ticks[i - 1]) / 100.0 / dt)
    fig, ax = plt.subplots(figsize=(6.6, 3.6))
    ax.plot(t, share, "-", color="tab:green", linewidth=1.8, label="shared memory (GB)")
    peak = max(share)
    ax.axhline(peak, color="tab:green", linestyle=":", linewidth=1)
    ax.annotate("peak %.1f GB = 33.4%% of fleet RAM" % peak, xy=(t[-1] * 0.55, peak),
                xytext=(t[-1] * 0.12, peak * 0.72), fontsize=8.5,
                arrowprops=dict(arrowstyle="->", lw=0.8))
    ax.set_xlabel("time (s)")
    ax.set_ylabel("KSM shared memory (GB)", color="tab:green")
    ax.tick_params(axis="y", labelcolor="tab:green")
    ax2 = ax.twinx()
    ax2.plot(t, cores, "-", color="tab:orange", linewidth=1.2, alpha=0.8,
             label="ksmd CPU (cores)")
    ax2.set_ylabel("ksmd CPU (cores)", color="tab:orange")
    ax2.tick_params(axis="y", labelcolor="tab:orange")
    ax2.set_ylim(0, 1.0)
#     ax.set_title("KSM fleet dedup: 64 same-image VMs share %.1f GB (33.4%%) at ~0.16 core;\n"
#                  "service P99 0.73 -> 0.76 ms" % peak, fontsize=9.5)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig23_ksm.png"), dpi=200)
    plt.close(fig)
    print("fig23 ok")


def fig24():
    rows = load("fpr_fpr5.jsonl")
    fig, ax = plt.subplots(figsize=(6.6, 3.6))
    colors = {311: "tab:blue", 312: "tab:orange", 313: "tab:green"}
    for r in rows:
        s = r["series"]
        t = [x["t"] for x in s]
        m = [x["mem_current_mb"] for x in s]
        ax.plot(t, m, "-", color=colors.get(r["vmid"], "gray"), linewidth=1.4,
                label="vm%d host RSS (base %d -> peak %d MB)" % (r["vmid"], r["host_mem_base_mb"], r["host_mem_peak_mb"]))
    ax.axhline(rows[0]["guest_memtotal_mb"], color="k", linestyle=":", linewidth=1)
    ax.text(1, rows[0]["guest_memtotal_mb"] + 6, "guest MemTotal (unchanged)", fontsize=8)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("host memory.current (MB)")
#     ax.set_title("Free-page reporting: 300 MB guest allocation fully reclaimed\n"
#                  "(289-305 MB back; guest-visible memory constant)", fontsize=9.5)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=7.5, loc="center right")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig24_fpr.png"), dpi=200)
    plt.close(fig)
    print("fig24 ok")


def fig25():
    rows = load("zram_zram3b.jsonl")
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 3.8))
    ax = axes[0]
    for arm, color in (("zram", "tab:green"), ("disk", "tab:red")):
        s = [r for r in rows if r["arm"] == arm]
        t = [r["t"] / 60.0 for r in s]
        a = [r["allocated_mb"] / 1024.0 for r in s]
        ax.plot(t, a, "-", color=color, linewidth=1.5, label="%s arm" % arm)
    ax.axhline(1120, color="k", linestyle=":", linewidth=1)
    ax.text(1, 1124, "target 1120 GB", fontsize=8)
    ax.set_xlabel("time (min)")
    ax.set_ylabel("allocated memory (GB)")
    ax.set_title("ballast allocation", fontsize=9.5)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8)
    ax = axes[1]
    for arm, color in (("zram", "tab:green"), ("disk", "tab:red")):
        s = [r for r in rows if r["arm"] == arm]
        t = [r["t"] / 60.0 for r in s]
        sw = [r["swap_used_mb"] / 1024.0 for r in s]
        ax.plot(t, sw, "-", color=color, linewidth=1.5, label="%s: swap used" % arm)
    ax.set_xlabel("time (min)")
    ax.set_ylabel("swap used (GB)")
    ax.set_title("overflow absorbed by swap", fontsize=9.5)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8)
    ax.annotate("zram absorbs 176.8 GB\n(3.1 GB physical)", xy=(20, 150), fontsize=8,
                color="tab:green")
    ax.annotate("disk: 96 GB swapfile\nexhausts -> abort", xy=(12, 60), fontsize=8,
                color="tab:red")
#     fig.suptitle("Swap arms: zram absorbs the overflow (P99 flat 0.745 ms); "
#                  "disk swapfile insufficient (abort at 1044 GB)", fontsize=10)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig25_zram.png"), dpi=200)
    plt.close(fig)
    print("fig25 ok")


def fig26():
    rows = load("ioctl_ioc2.jsonl")
    arms = [r["arm"] for r in rows]
    host = [r["host_iops_est"] for r in rows]
    ten = [r["tenant_iops_total"] for r in rows]
    svc = [r["mid_http_p99"] for r in rows]
    xs = range(len(arms))
    fig, ax = plt.subplots(figsize=(6.6, 3.6))
    ax.bar([x - 0.18 for x in xs], host, width=0.36, color="tab:gray", label="host IOPS (all)")
    ax.bar([x + 0.18 for x in xs], ten, width=0.36, color="tab:blue", label="tenant IOPS (8 storms)")
    ax.set_xticks(list(xs))
    ax.set_xticklabels(arms, fontsize=9)
    ax.set_ylabel("IOPS")
    ax.set_ylim(0, 115000)
    for x, v in zip(xs, ten):
        ax.text(x + 0.18, v + 1500, "%.0fk" % (v / 1000.0), ha="center", fontsize=8)
    ax2 = ax.twinx()
    ax2.plot(list(xs), svc, "o-", color="tab:red", linewidth=1.4)
    ax2.set_ylabel("service HTTP P99 (ms)", color="tab:red")
    ax2.tick_params(axis="y", labelcolor="tab:red")
    ax2.set_ylim(0, 2.0)
#     ax.set_title("4K random O_DIRECT storm (8 tenants): ~66k tenant IOPS,\n"
#                  "tenant P99max 8.3 ms — service untouched (0.74-0.76 ms)", fontsize=9.5)
    ax.grid(alpha=0.25, axis="y")
    ax.legend(fontsize=8, loc="upper right")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig26_ioctl.png"), dpi=200)
    plt.close(fig)
    print("fig26 ok")




def fig30_capacity_risk():
    import json as _json
    d = _json.load(open(os.path.join(BASE, "capacity_risk.json")))
    order = ["rand", "mix25", "mix50", "mix75", "sync"]
    colors = {"rand": "tab:blue", "mix25": "tab:cyan", "mix50": "tab:orange",
              "mix75": "tab:purple", "sync": "tab:red"}
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    for name in order:
        lv = d[name]
        levels = sorted(int(k) for k in lv)
        risks = [lv[str(l)] for l in levels]
        # N*(eps) step curve
        eps_grid = [0.0, 0.1, 0.2, 0.33, 0.5, 0.67, 0.8, 0.9, 1.0]
        xs, ys = [], []
        for e in eps_grid:
            n = max([l for l, r in zip(levels, risks) if r <= e], default=0)
            xs.append(e); ys.append(n)
        ax.step(xs, ys, where="post", color=colors[name], linewidth=1.8, label=name)
        ax.plot(xs, ys, "o", color=colors[name], markersize=3.5)
    ax.axvline(0.0, color="gray", linewidth=0.8, linestyle=":")
    ax.set_xlabel("risk budget eps  (allowed fraction of rounds with customer P5 < 70%)")
    ax.set_ylabel("safe capacity N*(eps)  (largest tested step)")
#     ax.set_title("Capacity-risk curves from the sell ladders (empirical round-level violation frequency; n = rounds per level);\n"
#                  "online policy stops (ours/ours_p: sync 8, rand 16-20) sit on the eps=0 edge",
#                  fontsize=9.5)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8.5)
    ax.set_xticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig30_capacity_risk.png"), dpi=200)
    plt.close(fig)
    print("fig30 ok")


if __name__ == "__main__":
    fig22()
    fig23()
    fig24()
    fig25()
    fig26()
    fig30_capacity_risk()
    print("all phase-c figures written to", OUT)
