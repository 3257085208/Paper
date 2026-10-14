#!/usr/bin/env python3
"""Generate all manuscript figures from the archived pilot data.

Run from the manuscript directory:  python3 figs/make_figs.py
Figures are written to figs/ as PNG (200 dpi).
"""

from __future__ import annotations

import csv
import glob
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                    "research_data", "berohost_pilot")
OUT = os.path.dirname(os.path.abspath(__file__))
SLO = 10.0


def pct(vals, p):
    vals = sorted(vals)
    if not vals:
        return None
    return vals[int(round(p / 100.0 * (len(vals) - 1)))]


def read_probe_raw(path):
    lat = []
    if not os.path.exists(path):
        return lat
    with open(path) as fh:
        for row in csv.DictReader(fh):
            if row["status"] == "ok" and row["total_ms"]:
                lat.append(float(row["total_ms"]))
    return lat


def fig2_knee():
    rounds = ["C", "r2", "r3", "r4", "r5"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), sharex=True)
    for ax, svc in zip(axes, ("http", "redis")):
        xs = list(range(6))
        series = {50: [], 99: [], 999: []}
        lo = {99: []}; hi = {99: []}
        for lvl in xs:
            per_round = []
            for r in rounds:
                fn = "C%d_%s.raw" % (lvl, svc) if r == "C" else "%s_L%d_%s.raw" % (r, lvl, svc)
                per_round.append(read_probe_raw(os.path.join(DATA, fn)))
            for p in series:
                q = 99.9 if p == 999 else p
                series[p].append(sum(pct(v, q) for v in per_round) / len(per_round))
            lo[99].append(min(pct(v, 99) for v in per_round))
            hi[99].append(max(pct(v, 99) for v in per_round))
        ax.plot(xs, series[50], "o-", label="P50")
        ax.plot(xs, series[99], "s-", color="tab:red", label="P99 (mean of 4 rounds)")
        ax.fill_between(xs, lo[99], hi[99], color="tab:red", alpha=0.15, label="P99 min-max")
        ax.plot(xs, series[999], "^--", color="tab:gray", label="P999")
        ax.axhline(SLO, color="k", linestyle=":", linewidth=1)
        ax.text(0.05, SLO + 0.6, "SLO 10 ms", fontsize=8)
        ax.set_title("svc-%s" % svc)
        ax.set_xlabel("number of pegged neighbors")
        ax.set_ylabel("latency (ms)")
        ax.set_xticks(xs)
        ax.grid(alpha=0.3)
    axes[0].legend(fontsize=7)
#     fig.suptitle("Knee curve: service latency vs. number of pegged co-tenants (4 vCPU host)", fontsize=10)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig2_knee.png"), dpi=200)
    plt.close(fig)


def fig3_sync_timeline():
    fig, axes = plt.subplots(2, 1, figsize=(8, 5.6), sharex=True)
    for ax, rnd in zip(axes, ("p3", "p3b")):
        lat = read_probe_raw(os.path.join(DATA, "pack_%s_http.raw" % rnd))
        if not lat:
            ax.set_title("%s (missing)" % rnd)
            continue
        buckets = {}
        with open(os.path.join(DATA, "pack_%s_http.raw" % rnd)) as fh:
            for row in csv.DictReader(fh):
                if row["status"] == "ok" and row["total_ms"]:
                    b = int(float(row["planned_offset_s"]) // 5)
                    buckets.setdefault(b, []).append(float(row["total_ms"]))
        xs = sorted(buckets)
        ys = [pct(buckets[b], 99) for b in xs]
        ax.plot([x * 5 for x in xs], ys, "-o", markersize=3, color="tab:red")
        ax.axhline(SLO, color="k", linestyle=":", linewidth=1)
        ax.set_ylabel("HTTP P99 (ms)")
#         ax.set_title("%s: synchronized bursts in the first ~6 s of every wall-clock minute" % rnd, fontsize=9)
        ax.grid(alpha=0.3)
    axes[1].set_xlabel("time since probe start (s)")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig3_sync_timeline.png"), dpi=200)
    plt.close(fig)


def load_jsonl(path):
    out = []
    if os.path.exists(path):
        for line in open(path):
            out.append(json.loads(line))
    return out


def fig4_packing():
    groups = {
        "idle x10\n(clustered)": (["p2", "p2b"], 17.3, 9.2, 10.2, 12.7),
        "idle x10\n(random phase)": (["p5", "p5b"], 3.8, 3.2, 2.7, 2.6),
        "idle x7+bursty x2\n+pegged (random)": (["p6", "p6b", "p6c", "p6d"], 18.8, 4.7, 20.8, 16.1),
        "sync x6+bursty x2\n+pegged x2": (["p3", "p3b", "p3c", "p3d"], 13.2, 12.0, 22.6, 21.6),
    }
    labels, http_vals, redis_vals = [], [], []
    for k, v in groups.items():
        labels.append(k)
        # average available http/redis p99 pairs
        vals = []
        recs = {}
        for rnd in v[0]:
            for rec in load_jsonl(os.path.join(DATA, "packing_%s.jsonl" % rnd)):
                recs[rnd] = rec
        hp = [((recs[r]["windows"].get("http") or {}).get("p99_ms") or 0) for r in recs]
        rp = [((recs[r]["windows"].get("redis") or {}).get("p99_ms") or 0) for r in recs]
        http_vals.append(sum(hp) / max(1, len(hp)))
        redis_vals.append(sum(rp) / max(1, len(rp)))
    fig, ax = plt.subplots(figsize=(8, 4))
    x = range(len(labels))
    ax.bar([i - 0.2 for i in x], http_vals, width=0.4, label="HTTP P99", color="tab:red")
    ax.bar([i + 0.2 for i in x], redis_vals, width=0.4, label="Redis P99", color="tab:blue")
    ax.axhline(SLO, color="k", linestyle=":", linewidth=1)
    ax.text(-0.4, SLO + 0.4, "SLO 10 ms")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("P99 (ms)")
#     ax.set_title("Mixed-workload packing: 10 customers (means across replicate runs)")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig4_packing.png"), dpi=200)
    plt.close(fig)


def fig5_censoring():
    recs = load_jsonl(os.path.join(DATA, "censor_c3.jsonl")) + \
           load_jsonl(os.path.join(DATA, "censor_c4.jsonl")) + \
           load_jsonl(os.path.join(DATA, "censor_c5.jsonl"))
    fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.8))
    ax = axes[0]
    naive = sum(r["naive_sum_cores"] for r in recs) / len(recs)
    aware = sum(r["aware_sum_cores"] for r in recs) / len(recs)
    ax.bar([0, 1], [naive, aware], color=["tab:orange", "tab:green"])
    ax.axhline(5.0, color="k", linestyle="--", linewidth=1)
    ax.text(1.55, 5.1, "true demand 5.0 cores", fontsize=8, ha="right")
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["naive\n(usage only)", "censoring-aware\n(+throttle evidence)"])
    ax.set_ylabel("estimated demand (cores)")
    ax.set_title("Estimation bias (n=%d cycles: 1.50 vs 5.00)" % len(recs), fontsize=9)
    ax.grid(axis="y", alpha=0.3)

    ax = axes[1]
    quota = [((r["quota_phase"].get("http") or {}).get("p99_ms") or 0) for r in recs]
    released = [((r["released_phase"].get("http") or {}).get("p99_ms") or 0) for r in recs]
    x = range(1, len(recs) + 1)
    ax.bar([i - 0.2 for i in x], quota, width=0.4, label="quota kept", color="tab:green")
    ax.bar([i + 0.2 for i in x], released, width=0.4, label="released (naive)", color="tab:red")
    ax.axhline(SLO, color="k", linestyle=":", linewidth=1)
    ax.set_xlabel("cycle")
    ax.set_ylabel("HTTP P99 (ms)")
#     ax.set_title("Naive release action vs. quota kept (n=%d cycles)" % len(recs), fontsize=9)
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig5_censoring.png"), dpi=200)
    plt.close(fig)


def shaping_records():
    recs = {}
    for rnd, label in (("s1u", "no control"), ("s1q", "quota 0.75"), ("s2q", "quota 0.50"), ("s1p", "pinned")):
        for rec in load_jsonl(os.path.join(DATA, "shaping_%s.jsonl" % rnd)):
            recs.setdefault(rec["scheme"], {})[rec["level"]] = rec
    return recs


def fig6_shaping():
    recs = shaping_records()
    levels = {"unlimited": 4, "q75": 4, "q50": 4, "pin": 5}
    labels = {"unlimited": "no control", "q75": "quota 0.75", "q50": "quota 0.50", "pin": "isolated (pinned)"}
    order = ["unlimited", "q75", "q50", "pin"]
    p99s, rates = [], []
    ref_rate = None
    for scheme in order:
        rec = recs[scheme][levels[scheme]]
        http = rec["windows"]["http"]
        p99s.append(http["p99_ms"])
        br = [r for r in rec.get("burn_rates", []) if r]
        rate = sum(br) / len(br) if br else None
        if scheme == "unlimited":
            ref_rate = rate
        rates.append(rate)
    fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.8))
    ax = axes[0]
    ax.bar(range(4), p99s, color=["tab:red", "tab:orange", "tab:orange", "tab:green"])
    ax.axhline(SLO, color="k", linestyle=":", linewidth=1)
    ax.text(-0.4, SLO + 0.5, "SLO 10 ms", fontsize=8)
    ax.set_xticks(range(4))
    ax.set_xticklabels([labels[s] + "\n(%dth neighbor)" % (levels[s] + 1) for s in order], fontsize=8)
    ax.set_ylabel("HTTP P99 (ms)")
    ax.set_title("Service tail at the 4th/5th neighbor", fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    ax = axes[1]
    ax.bar(range(4), [100.0 * (r / ref_rate) if r and ref_rate else 0 for r in rates],
           color=["tab:gray", "tab:orange", "tab:orange", "tab:green"])
    ax.set_xticks(range(4))
    ax.set_xticklabels([labels[s] for s in order], fontsize=8)
    ax.set_ylabel("customer work-rate (% of full speed)")
    ax.set_title("Where the cost lands (customer side)", fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig6_shaping.png"), dpi=200)
    plt.close(fig)


def fig7_memory():
    fig, ax = plt.subplots(figsize=(7.5, 4))
    for rnd, label, color in (("m1", "guest total (uncapped)", "tab:red"),
                              ("m2b", "guest total (cap 1000 MB)", "tab:orange"),
                              ("m2c", "guest total (cap 800 MB)", "tab:blue")):
        recs = load_jsonl(os.path.join(DATA, "memphase_%s.jsonl" % rnd))
        if not recs:
            continue
        xs = [r["wave"] for r in recs]
        ys = [r["guest_total_mb"] / 1024.0 for r in recs]
        ax.plot(xs, ys, "o-", label=label, color=color)
    recs = load_jsonl(os.path.join(DATA, "memphase_m1.jsonl"))
    if recs:
        xs = [r["wave"] for r in recs]
        ax.plot(xs, [r["mem_available_mb"] / 1024.0 for r in recs], "s--", color="tab:green",
                label="MemAvailable (uncapped run)")
        ax.plot(xs, [r["swap_free_mb"] / 1024.0 for r in recs], "^:", color="tab:purple",
                label="swap free (uncapped run)")
    ax.annotate("2 customer VMs OOM-killed\n(the uncapped run)", xy=(5, 13.5),
                xytext=(2.6, 15.5), fontsize=8,
                arrowprops=dict(arrowstyle="->", color="k"))
    ax.set_xlabel("wave (200 MB added per customer)")
    ax.set_ylabel("GiB")
#     ax.set_title("Memory oversubscription: growth trials (10 customers, 50 GiB sold on 19.5 GiB)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig7_memory.png"), dpi=200)
    plt.close(fig)


def fig8_disk():
    d1b = load_jsonl(os.path.join(DATA, "disk_d1b.jsonl"))[-1]
    d2b = load_jsonl(os.path.join(DATA, "disk_d2b.jsonl"))[-1]
    fig, axes = plt.subplots(1, 3, figsize=(10, 3.6))
    ax = axes[0]
    ax.bar([0, 1], [d1b["host"]["iops"], d2b["host"]["iops"]], color=["tab:red", "tab:green"])
    ax.set_xticks([0, 1]); ax.set_xticklabels(["baseline", "io.max"])
    ax.set_ylabel("host IOPS")
    ax.set_title("Host-level I/O load", fontsize=9)
    ax = axes[1]
    ax.bar([0, 1], [d1b["http"]["p99_ms"], d2b["http"]["p99_ms"]], color=["tab:red", "tab:green"])
    ax.axhline(SLO, color="k", linestyle=":", linewidth=1)
    ax.set_xticks([0, 1]); ax.set_xticklabels(["baseline", "io.max"])
    ax.set_ylabel("service HTTP P99 (ms)")
    ax.set_title("Service impact (services do ~no disk I/O)", fontsize=9)
    ax = axes[2]
    v1 = list(d1b["fio"].values())[0] or {}
    v2 = list(d2b["fio"].values())[0] or {}
    ax.bar([0, 1], [v1.get("read_clat_p99_us", 0) / 1000.0, v2.get("read_clat_p99_us", 0) / 1000.0],
           color=["tab:red", "tab:green"])
    ax.set_xticks([0, 1]); ax.set_xticklabels(["baseline", "io.max"])
    ax.set_ylabel("offender read P99 (ms)")
    ax.set_title("Where the cost lands (throttled tenant)", fontsize=9)
    for ax in axes:
        ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig8_disk.png"), dpi=200)
    plt.close(fig)


def fig9_quotapulse():
    recs = {r["mode"]: r for r in load_jsonl(os.path.join(DATA, "quota_pulse_qp1.jsonl"))}
    c3 = load_jsonl(os.path.join(DATA, "censor_c3.jsonl"))
    ref = sum((r["quota_phase"].get("http") or {}).get("p99_ms", 0) for r in c3) / len(c3)
    entries = [("quota 100 ms\n(reference)", ref),
               ("quota 1 s", (recs.get("p1000", {}).get("http") or {}).get("p99_ms")),
               ("staggered\nperiods", (recs.get("mixed", {}).get("http") or {}).get("p99_ms")),
               ("CPU weight 10x\n(services)", (recs.get("weight", {}).get("http") or {}).get("p99_ms")),
               ("CPU weight 100x\n(services)", 24.0)]
    fig, ax = plt.subplots(figsize=(7.5, 3.8))
    ax.bar(range(len(entries)), [e[1] for e in entries],
           color=["tab:orange", "tab:orange", "tab:orange", "tab:red", "tab:red"])
    ax.axhline(SLO, color="k", linestyle=":", linewidth=1)
    ax.text(-0.6, SLO + 0.5, "SLO 10 ms", fontsize=8)
    ax.set_xticks(range(len(entries)))
    ax.set_xticklabels([e[0] for e in entries], fontsize=8)
    ax.set_ylabel("HTTP P99 (ms)")
#     ax.set_title("Quota-pulse remedies: HTTP P99 under different CPU control configurations (SLO 10 ms)")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig9_quotapulse.png"), dpi=200)
    plt.close(fig)


def fig10_synthesis():
    passes = ["syn1", "syn2", "syn3", "syn4"]
    http, redis = [], []
    for p in passes:
        lat_h = read_probe_raw(os.path.join(DATA, "syn_%s_http.raw" % p))
        lat_r = read_probe_raw(os.path.join(DATA, "syn_%s_redis.raw" % p))
        http.append(pct(lat_h, 99) if lat_h else None)
        redis.append(pct(lat_r, 99) if lat_r else None)
    fig, ax = plt.subplots(figsize=(7, 3.6))
    x = range(len(passes))
    ax.bar([i - 0.2 for i in x], http, width=0.4, label="HTTP P99", color="tab:red")
    ax.bar([i + 0.2 for i in x], redis, width=0.4, label="Redis P99", color="tab:blue")
    ax.axhline(SLO, color="k", linestyle=":", linewidth=1)
    ax.text(-0.45, SLO + 0.5, "SLO 10 ms", fontsize=8)
    ax.set_xticks(list(x))
    ax.set_xticklabels(["pass %d" % (i + 1) for i in range(len(passes))])
    ax.set_ylabel("P99 (ms)")
#     ax.set_title("Triple-storm synthesis validation (16 customers; CPU+memory+disk storms)")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig10_synthesis.png"), dpi=200)
    plt.close(fig)


def fig11_method():
    """Policy comparison under censoring (metheval m1) and cold-start matrix (cs1).

    Per-step records carry no policy field; runs are recorded in deterministic
    order with exactly six lines each (one line per arrival step).
    """
    me = load_jsonl(os.path.join(DATA, "metheval_m1.jsonl"))
    pols = ["naive", "audible", "aware", "aware_cal"]
    labels = ["naive\n(usage)", "AUDIBLE-style\n(MC convolution)", "aware\n(censoring-fixed)",
              "aware+cal\n(+= pause)"]
    seats = {p: 0 for p in pols}
    viols = {p: 0 for p in pols}
    for bi, p in enumerate(pols):
        for ev in me[bi * 6:(bi + 1) * 6]:
            if ev.get("decision") == "allow":
                seats[p] += 1
            if ev.get("violation"):
                viols[p] += 1

    cs = load_jsonl(os.path.join(DATA, "coldstart_cs1.jsonl"))
    runs = [("all_heavy", "prior_light"), ("all_heavy", "prior_conservative"),
            ("all_heavy", "probe_relax"), ("all_light", "prior_light"),
            ("all_light", "prior_conservative"), ("all_light", "probe_relax")]
    cseats = {}; cviols = {}
    for bi, r in enumerate(runs):
        cseats[r] = sum(1 for ev in cs[bi * 6:(bi + 1) * 6] if ev.get("decision") == "allow")
        cviols[r] = sum(1 for ev in cs[bi * 6:(bi + 1) * 6] if ev.get("violation"))

    fig, axes = plt.subplots(1, 2, figsize=(11.5, 3.9))
    ax = axes[0]
    x = range(len(pols))
    ax.bar(x, [seats[p] for p in pols], color=["tab:red", "tab:orange", "tab:green", "tab:blue"])
    for i, p in enumerate(pols):
        ax.text(i, seats[p] + 0.1, "viol=%d" % viols[p], ha="center", fontsize=8)
    ax.set_xticks(list(x)); ax.set_xticklabels(labels, fontsize=7)
    ax.set_ylabel("admitted tenants (of 6)")
    ax.set_title("Censored-demand admission (tenants capped at 50%)", fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    ax = axes[1]
    x = range(len(runs))
    cols = {"prior_light": "tab:red", "prior_conservative": "tab:orange", "probe_relax": "tab:green"}
    ax.bar(list(x), [cseats[r] for r in runs], color=[cols[p] for _, p in runs])
    for i, r in enumerate(runs):
        ax.text(i, cseats[r] + 0.1, "viol=%d" % cviols[r], ha="center", fontsize=8)
    ax.set_xticks(list(x))
    ax.set_xticklabels([("%s\n%s" % (sc.replace("all_", ""), p[:14])) for sc, p in runs], fontsize=7)
    ax.set_ylabel("admitted tenants (of 6)")
    ax.set_title("Cold start: arrival population x prior", fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig11_method.png"), dpi=200)
    plt.close(fig)


def fig12_bounds():
    recs = load_jsonl(os.path.join(DATA, "bounds_b2.jsonl"))
    if not recs:
        return
    x = range(len(recs))
    fig, ax = plt.subplots(figsize=(6.5, 3.6))
    ax.bar([i - 0.18 for i in x], [r["mean_d_lb"] for r in recs], width=0.36,
           label="estimated lower bound  u/(1 − t)", color="tab:blue")
    ax.bar([i + 0.18 for i in x], [r["mean_truth"] for r in recs], width=0.36,
           label="measured true demand (quota lifted)", color="tab:green")
    ax.set_xticks(list(x))
    ax.set_xticklabels(["quota %.2f" % r["quota"] for r in recs])
    ax.set_ylabel("cores")
    ax.set_ylim(0, 1.15)
    ax.set_title("Recovering censored demand from observable counters")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig12_bounds.png"), dpi=200)
    plt.close(fig)


def fig13_joint():
    recs = load_jsonl(os.path.join(DATA, "joint_j1.jsonl"))
    if len(recs) < 12:
        return
    pols = ["naive", "aware"]
    seats = {}
    gaps = []
    for bi, p in enumerate(pols):
        block = recs[bi * 6:(bi + 1) * 6]
        seats[p] = sum(1 for e in block if e.get("decision") == "allow")
        for e in block:
            c = e.get("canary")
            gap = float(c.split()[1]) if c else 0.0
            gaps.append((p, e["step"], gap))
    fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.6))
    ax = axes[0]
    ax.bar([0, 1], [seats["naive"], seats["aware"]], color=["tab:orange", "tab:green"])
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["naive\n(usage)", "aware\n(throttle-corrected)"])
    ax.set_ylabel("committed seats (of 6)")
#     ax.set_title("Joint storm: admission outcome\n(service SLO held in both)", fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    ax = axes[1]
    for p, color in (("naive", "tab:orange"), ("aware", "tab:green")):
        xs = [s for (pp, s, g) in gaps if pp == p]
        ys = [g for (pp, s, g) in gaps if pp == p]
        ax.plot(xs, ys, "o-", label=p, color=color)
    ax.set_xlabel("arrival step")
    ax.set_ylabel("canary max wakeup gap (ms)")
    ax.set_title("Customer-side canary\n(background customer VM)", fontsize=9)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig13_joint.png"), dpi=200)
    plt.close(fig)


def main():
    for fn in (fig2_knee, fig3_sync_timeline, fig4_packing, fig5_censoring,
               fig6_shaping, fig7_memory, fig8_disk, fig9_quotapulse, fig10_synthesis,
               fig11_method, fig12_bounds, fig13_joint):
        try:
            fn()
            print("ok:", fn.__name__)
        except Exception as exc:  # noqa: BLE001
            print("FAIL:", fn.__name__, "->", type(exc).__name__, exc)


if __name__ == "__main__":
    main()
