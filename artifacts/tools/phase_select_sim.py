#!/usr/bin/env python3
"""Phase-selective admission — deepened zero-machine-time study.

Questions:
  Q1  How large is the selection gain across load types (aligned -> random)?
  Q2  Does it grow monotonically with phase diversity (and vanish at alignment)?
  Q3  Which selection variant is realistic and effective
      (FIFO / FIFO+retry / best-of-k window)?
  Q4  Is it robust to measurement noise (gate sees jittered profiles, truth does not)?
  Q5  Fairness: does FIFO+retry starve deferred candidates?

Model: candidates carry 60-bucket phase profiles (active duty*60 s at a fixed
offset). Gate = predicted joint peak <= 0.9 C (the paper's envelope rule).
Output: research_data/PHASE_SELECT_SIM.md
"""

from __future__ import annotations

import io
import json
import os
import random
import statistics

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
MATRIX = os.path.join(BASE, "research_data", "vps2_readonly", "replay_sched", "matrix.json")
OUT = os.path.join(BASE, "research_data", "PHASE_SELECT_SIM.md")
C = 8
LIMIT = 0.9 * C
PERIOD = 60
QUEUE_N = 40
TRIALS = 300
random.seed(11)


def mk_profile(duty, offset):
    on = int(round(duty * PERIOD))
    prof = [0] * PERIOD
    for s in range(on):
        prof[(offset + s) % PERIOD] = 1
    return prof


def peak(profs):
    return max(sum(p[i] for p in profs) for i in range(PERIOD)) if profs else 0


def peak_with(profs, cand):
    return max(sum(p[i] for p in profs) + cand[i] for i in range(PERIOD))


def over_frac(profs, seconds=1800):
    series = [0] * seconds
    for p in profs:
        for k in range(seconds // PERIOD):
            for i in range(PERIOD):
                if p[i]:
                    series[k * PERIOD + i] += 1
    return sum(1 for x in series if x > C) / seconds


def gen_fleet(kind, n, spread):
    """Return list of (duty, offset); kind: rand | mix | aligned | syn."""
    out = []
    for i in range(n):
        duty = random.choice([0.05, 0.1, 0.15, 0.2, 0.2, 0.25, 0.33, 0.5])
        if kind == "aligned":
            off = 0
        elif kind == "mix":
            off = 0 if i % 2 == 0 else random.randrange(max(1, spread))
        else:  # rand / syn
            off = random.randrange(max(1, spread))
        out.append((duty, off))
    return out


def run_gate(order, profiles, measured, variant, k=3):
    """Admit candidates (indices into profiles) under the gate.

    variant: fifo (stop at first fail) | retry (two passes) | bestk (window reorder).
    measured: profiles the GATE sees (may be jittered); profiles = truth.
    Returns admitted truth-profiles and a starvation flag.
    """
    admitted = []
    admitted_m = []
    if variant == "fifo":
        for i in order:
            if peak_with(admitted_m, measured[i]) <= LIMIT:
                admitted.append(i)
                admitted_m.append(measured[i])
            else:
                break
        return admitted, False
    if variant == "retry":
        admitted_set = set()
        changed = True
        while changed:  # fixpoint: keep re-checking deferred until no progress
            changed = False
            for i in order:
                if i in admitted_set:
                    continue
                if peak_with(admitted_m, measured[i]) <= LIMIT:
                    admitted.append(i)
                    admitted_m.append(measured[i])
                    admitted_set.add(i)
                    changed = True
        # by fixpoint construction every leftover is genuinely non-fitting
        starved = [i for i in order if i not in admitted_set
                   and peak_with(admitted_m, measured[i]) <= LIMIT]
        return admitted, len(starved) > 0
    if variant == "bestk":
        pending = list(order)
        while pending:
            window = pending[:k]
            best_i, best_peak = None, None
            for i in window:
                pk = peak_with(admitted_m, measured[i])
                if best_peak is None or pk < best_peak:
                    best_i, best_peak = i, pk
            if best_peak is not None and best_peak <= LIMIT:
                admitted.append(best_i)
                admitted_m.append(measured[best_i])
                pending.remove(best_i)
            else:
                break
        return admitted, len(pending) > 0
    raise ValueError(variant)


def jitter(profs, frac=0.1):
    out = []
    for p in profs:
        on = sum(p)
        off = p.index(1) if 1 in p else 0
        on2 = max(1, int(round(on * (1 + random.uniform(-frac, frac)))))
        out.append(mk_profile(on2 / PERIOD, off))
    return out


def trial(kind, variant, spread=60, k=3, noise=False):
    if kind == "prod":
        m = json.load(open(MATRIX))
        keys = sorted(m["vms"])
        pool = []
        for key in keys:
            duty = min(1.0, max(0.0, statistics.mean(map(float, m["vms"][key]))))
            pool.append((duty, random.randrange(PERIOD)))
        queue = random.sample(pool, min(QUEUE_N, len(pool)))
    else:
        pool = gen_fleet(kind, 64, spread)
        queue = random.sample(pool, QUEUE_N)
    profiles = [mk_profile(d, o) for (d, o) in queue]
    measured = jitter(profiles) if noise else profiles
    order = list(range(len(queue)))
    random.shuffle(order)
    admitted, starved = run_gate(order, profiles, measured, variant, k)
    return len(admitted), peak([profiles[i] for i in admitted]), \
        over_frac([profiles[i] for i in admitted]), starved


def agg(kind, variant, spread=60, k=3, noise=False):
    counts, peaks, overs, starv = [], [], [], 0
    for _ in range(TRIALS):
        c, pk, ov, st = trial(kind, variant, spread, k, noise)
        counts.append(c)
        peaks.append(pk)
        overs.append(ov)
        starv += st
    counts.sort()
    return {
        "mean": statistics.mean(counts),
        "p5": counts[int(0.05 * (len(counts) - 1))],
        "worst": counts[0],
        "peak": statistics.mean(peaks),
        "over": 100 * statistics.mean(overs),
        "starv": starv,
    }


def main():
    lines = ["# 相位选择性准入：深化仿真（零机时）", ""]
    lines.append("队列=40 随机候选（池 64）；门禁=预测联合峰值 ≤ 0.9×8=7.2 核；每格 %d 次试验。" % TRIALS)

    # Q1/Q3: load types x variants
    lines.append("")
    lines.append("## Q1/Q3 负载类型 × 选择变体（平均接入 / P5 / 最差序）")
    lines.append("")
    lines.append("| 负载 | FIFO | FIFO+重试 | 窗口最优 k=3 | 窗口最优 k=6 |")
    lines.append("|---|---|---|---|---|")
    for kind, label in (("prod", "生产日程（漂移）"), ("rand", "全随机相位"),
                        ("mix", "半对齐混合"), ("aligned", "全对齐")):
        cells = []
        for variant, k in (("fifo", 0), ("retry", 0), ("bestk", 3), ("bestk", 6)):
            r = agg(kind, variant, spread=60, k=k)
            cells.append("%.1f / %d / %d" % (r["mean"], r["p5"], r["worst"]))
        lines.append("| %s | %s | %s | %s | %s |" % (label, *cells))
        print(kind, "done")

    # Q2: diversity sweep (offset spread), prod + synthetic
    lines.append("")
    lines.append("## Q2 选择红利 vs 相位多样性（FIFO → 窗口最优 k=3 的均值增益）")
    lines.append("")
    lines.append("| offset 散布 | FIFO 均值 | 选择均值 | 增益 |")
    lines.append("|---|---|---|---|")
    for spread in (1, 6, 15, 30, 60):
        rf = agg("syn", "fifo", spread=spread)
        rs = agg("syn", "bestk", spread=spread, k=3)
        lines.append("| %d s | %.1f | %.1f | %+.1f |" % (spread, rf["mean"], rs["mean"], rs["mean"] - rf["mean"]))
        print("spread", spread, "done")

    # Q4: noise robustness
    lines.append("")
    lines.append("## Q4 测量噪声（门禁看抖动剖面，真值不抖）")
    lines.append("")
    lines.append("| 负载 | FIFO 超池% | FIFO 接入 | 选择 超池% | 选择 接入 |")
    lines.append("|---|---|---|---|---|")
    for kind in ("prod", "rand"):
        rf = agg(kind, "fifo", noise=True)
        rs = agg(kind, "bestk", noise=True, k=3)
        lines.append("| %s | %.2f%% | %.1f | %.2f%% | %.1f |" % (kind, rf["over"], rf["mean"], rs["over"], rs["mean"]))
        print("noise", kind, "done")

    # Q5: fairness (starvation) under retry
    lines.append("")
    lines.append("## Q5 公平性（定点重试：\"还能装下却被拒\"的候选）")
    lines.append("")
    lines.append("定点重试保证：循环重检被拒候选直到无进展 ⇒ 剩余候选都是**真的装不下**。")
    lines.append("")
    lines.append("| 负载 | 真饥饿（应恒为 0） |")
    lines.append("|---|---|")
    for kind in ("prod", "rand", "aligned"):
        r = agg(kind, "retry")
        lines.append("| %s | %d/%d |" % (kind, r["starv"], TRIALS))
        print("starv", kind, "done")

    with io.open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print("saved:", OUT)


if __name__ == "__main__":
    main()
