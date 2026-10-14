#!/usr/bin/env python3
"""Physical-host (8259CL) figures: multi-scale knee, sync-vs-random, sell capacity.

Reads research_data/phys8269_pilot/, writes PNGs into manuscript/figs/:
  fig14_phys_knee.png, fig15_phys_sync.png, fig16_phys_sell.png
Run:  python3 manuscript/figs/make_phys_figs.py
"""

from __future__ import annotations

import csv
import json
import os
import random
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

random.seed(7)

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                    "research_data", "phys8269_pilot")
OUT = os.path.dirname(os.path.abspath(__file__))
SLO = 10.0


def collect(fns, key="http"):
    """Dict level -> list of p99 values (across files, in given order)."""
    out = {}
    for fn in fns:
        p = os.path.join(BASE, fn)
        if not os.path.exists(p):
            continue
        for line in open(p):
            o = json.loads(line)
            rec = o.get(key) or {}
            v = rec.get("p99_ms")
            if v is None:
                continue
            out.setdefault(o["level"], []).append(v)
    return out


def avg(d):
    return {k: sum(v) / len(v) for k, v in d.items()}


def fig14_knee():
    isolated = [
        ("2-core pool", ["sweep_qa2a.jsonl"], 2),
        ("4-core pool", ["sweep_qa4i.jsonl"], 4),
        ("8-core pool", ["sweep_qa8i.jsonl"], 8),
        ("16-core pool", ["sweep_qb16i.jsonl"], 16),
        ("32-core pool", ["sweep_qb32i.jsonl"], 32),
    ]
    shared = [
        ("2-core pool", ["sweep_qa2c.jsonl"], 2),
        ("4-core pool", ["sweep_qa4c.jsonl", "sweep_qa4c2.jsonl"], 4),
        ("16-core pool", ["sweep_qb16c.jsonl"], 16),
        ("16-core pool (fine, 4 rounds)", ["sweep_qc16f1.jsonl", "sweep_qc16f2.jsonl",
                                           "sweep_qc16f3.jsonl", "sweep_qc16f4.jsonl"], 16),
    ]

    fig, axes = plt.subplots(1, 2, figsize=(10.5, 3.9), sharey=True)
    for ax, group, title in ((axes[0], isolated, "Isolated services (dedicated cores)"),
                             (axes[1], shared, "Shared pool (services inside)")):
        for label, fns, pool in group:
            d = avg(collect(fns))
            xs = sorted(d)
            ys = [d[x] for x in xs]
            ax.plot([x / pool for x in xs], ys, "o-", markersize=4, label=label)
        ax.axhline(SLO, color="k", linestyle=":", linewidth=1)
        ax.axvline(1.0, color="tab:red", linestyle="--", linewidth=0.8, alpha=0.6)
        ax.text(1.02, 0.9, "pool saturated", color="tab:red", fontsize=7.5)
        ax.set_yscale("log")
        ax.set_xlabel("oversubscription ratio (pegged tenants / pool cores)")
        ax.set_title(title, fontsize=10)
        ax.grid(alpha=0.3, which="both")
        ax.legend(fontsize=7.5, loc="upper left")
    axes[0].set_ylabel("HTTP P99 (ms, log)")
    axes[0].text(0.03, SLO * 1.15, "SLO 10 ms", fontsize=7.5)
#     fig.suptitle("Physical host (2x 8259CL, 64-VM fleet): service P99 vs peak-neighbor "
#                  "oversubscription, isolated vs shared", fontsize=10)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig14_phys_knee.png"), dpi=200)
    plt.close(fig)
    print("fig14 ok")


def read_raw(path):
    rows = []
    with open(path) as fh:
        for row in csv.DictReader(fh):
            if row["status"] == "ok" and row["total_ms"]:
                rows.append((float(row["planned_offset_s"]), float(row["total_ms"])))
    return rows


def p99(v):
    v = sorted(v)
    return v[int(round(0.99 * (len(v) - 1)))]


def fig15_sync():
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.6), gridspec_kw={"width_ratios": [1.6, 1]})

    ax = axes[0]
    for fn, label, color in (
            ("qc_sync_rand_http.raw", "random phase (64 tenants, 20%/60 s)", "tab:blue"),
            ("qc_sync_alig_http.raw", "aligned phase (64 tenants, 20%/60 s)", "tab:red")):
        rows = read_raw(os.path.join(BASE, fn))
        buckets = {}
        for t, lat in rows:
            buckets.setdefault(int(t // 5) * 5, []).append(lat)
        xs = sorted(buckets)
        ys = [p99(buckets[b]) for b in xs]
        ax.plot(xs, ys, "-o", markersize=3.5, linewidth=1.2, color=color, label=label)
    ax.axhline(SLO, color="k", linestyle=":", linewidth=1)
    ax.text(2, SLO + 1.2, "SLO 10 ms", fontsize=8)
    ax.set_xlabel("time since probe start (s)")
    ax.set_ylabel("HTTP P99 per 5 s (ms)")
    ax.set_title("burst timeline (round 1)", fontsize=10)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)

    ax = axes[1]
    for i, phase in enumerate(("rand", "alig")):
        color = "tab:blue" if phase == "rand" else "tab:red"
        for rnd, fname in enumerate(("qc_sync_%s_http.raw" % phase,
                                     "qc_sync_%s_r2_http.raw" % phase,
                                     "qc_sync_%s_r3_http.raw" % phase), start=1):
            rows = read_raw(os.path.join(BASE, fname))
            buckets = {}
            for t, lat in rows:
                buckets.setdefault(int(t // 5) * 5, []).append(lat)
            hot = sorted(b for b, v in buckets.items() if p99(v) > 4.0)
            clusters = []
            for b in hot:
                if clusters and b - clusters[-1][-1] <= 10:
                    clusters[-1].append(b)
                else:
                    clusters.append([b])
            gaps = [clusters[k + 1][0] - clusters[k][0] for k in range(len(clusters) - 1)]
            xs = [rnd + (i - 0.5) * 0.24 + random.uniform(-0.05, 0.05) for _ in gaps]
            ax.scatter(xs, gaps, s=22, color=color, alpha=0.75,
                       label="random" if (i == 0 and rnd == 1) else
                             ("aligned" if (i == 1 and rnd == 1) else None))
    ax.axhline(60, color="k", linestyle=":", linewidth=1)
    ax.text(0.6, 61, "60 s", fontsize=8)
    ax.set_xticks([1, 2, 3])
    ax.set_xticklabels(["round 1", "round 2", "round 3"])
    ax.set_ylabel("gap between hot clusters (s)")
    ax.set_title("cluster gap per repeat", fontsize=10)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
#     fig.suptitle("Physical host: synchronized vs randomized bursts, all 64 tenants "
#                  "sharing one 16-core pool (busy-loop duty 20% / 60 s)", fontsize=10)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig15_phys_sync.png"), dpi=200)
    plt.close(fig)
    print("fig15 ok")


def fig16_sell():
    base = 25.9e6

    def per_level_rates(fns):
        if isinstance(fns, str):
            fns = [fns]
        out = {}
        for fn in fns:
            skip = 6 if fn == "sell_sell_sync_r3.jsonl" else 0  # void shuffled series
            for idx, line in enumerate(open(os.path.join(BASE, fn))):
                if idx < skip:
                    continue
                o = json.loads(line)
                per = {}
                for rnd in o.get("rate_rounds") or []:
                    for vmid, rate, state in rnd:
                        if rate and state == 1:
                            per[vmid] = max(per.get(vmid, 0), rate)
                if per:
                    vals = sorted(x / base * 100 for x in per.values())
                    prev = out.get(o["level"], ([], [], 0))
                    out[o["level"]] = (prev[0] + vals, prev[1], prev[2] + len(vals))
        final = {}
        for lvl, (vals, _, n) in out.items():
            vals = sorted(vals)
            p50 = statistics.median(vals)
            p5 = vals[int(0.05 * (len(vals) - 1))]
            final[lvl] = (p50, p5, len(vals))
        return final

    rand = per_level_rates(["sell_sell_rand.jsonl", "sell_sell_rand_r2.jsonl",
                              "sell_sell_rand_r4.jsonl", "sell_sell_rand_r5.jsonl"])
    sync = per_level_rates(["sell_sell_sync.jsonl", "sell_sell_sync_r2.jsonl",
                            "sell_sell_sync_r3.jsonl", "sell_sell_sync_r4.jsonl"])

    fig, axes = plt.subplots(1, 2, figsize=(10.5, 3.9))
    ax = axes[0]
    for d, color, label in ((rand, "tab:blue", "random phase, 4 rounds"), (sync, "tab:red", "aligned phase, 4 rounds")):
        xs = sorted(d)
        ax.plot(xs, [d[x][0] for x in xs], "o-", color=color, label="%s: p50" % label)
        ax.plot(xs, [d[x][1] for x in xs], "s--", color=color, alpha=0.7,
                label="%s: p5" % label)
    ax.axhline(90, color="k", linestyle=":", linewidth=1)
    ax.text(0.5, 91, "90%", fontsize=8)
    ax.axhline(70, color="k", linestyle="-.", linewidth=1)
    ax.text(0.5, 71, "70% (primary QoS bar)", fontsize=8)
    ax.axhline(50, color="k", linestyle=":", linewidth=1)
    ax.text(0.5, 51, "50%", fontsize=8)
    ax.set_xlabel("admitted 1-vCPU tenants (8-core pool, duty 20%/60 s)")
    ax.set_ylabel("customer workout rate (% of solo baseline)")
    ax.set_title("Customer experience vs. sold density", fontsize=10)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="lower left")

    ax = axes[1]
    for fn, color, label in (("sell_sell_rand.jsonl", "tab:blue", "random phase"),
                             ("sell_sell_sync.jsonl", "tab:red", "aligned phase")):
        lv, http, redis = [], [], []
        for line in open(os.path.join(BASE, fn)):
            o = json.loads(line)
            lv.append(o["level"])
            http.append((o.get("http") or {}).get("p99_ms"))
            redis.append((o.get("redis") or {}).get("p99_ms"))
        ax.plot(lv, http, "o-", color=color, label="%s: HTTP" % label)
        ax.plot(lv, redis, "^--", color=color, alpha=0.7, label="%s: Redis" % label)
    ax.axhline(SLO, color="k", linestyle=":", linewidth=1)
    ax.text(0.5, SLO * 1.1, "SLO 10 ms", fontsize=8)
    ax.set_xlabel("admitted 1-vCPU tenants")
    ax.set_ylabel("service P99 (ms)")
    ax.set_title("Service latency stays flat (services isolated)", fontsize=10)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
#     fig.suptitle("Sell capacity on the physical host: same average load, capacity "
#                  "determined by burst phase structure", fontsize=10)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig16_phys_sell.png"), dpi=200)
    plt.close(fig)
    print("fig16 ok")


if __name__ == "__main__":
    fig14_knee()
    fig15_sync()
    fig16_sell()
    print("all phys figures written to", OUT)
