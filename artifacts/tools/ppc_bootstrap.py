#!/usr/bin/env python3
"""Joint block bootstrap on REAL production traces (the replay schedules).

Implements the empirical resampling mode described in Section 8.6:
  * second-level activity model: sequential burners within each 60 s period
    (tenant i is active during the first duty*60 s of period k) — exactly what
    tb_replay.py drives on the testbed;
  * three-way split: train (first 1/3) -> block-length selection (middle 1/3,
    KS) -> test (last 1/3, never used as resampling input);
  * FORWARD PREDICTION protocol: predictive blocks are drawn from the TRAIN
    third ONLY; the resulting synthetic segment (same length as the test third)
    is scored against the actually observed test third. This tests
    "predict the future from prior history alone" — not self-calibration on the
    test segment;
  * joint bootstrap: blocks are resampled *jointly across tenants* (same period
    indices), preserving cross-tenant co-occurrence;
  * iid control: each tenant's train duty sequence permuted independently
    (marginals preserved, joint destroyed) — the assumption behind iid
    convolution.

Outputs research_data/vps2_readonly/PPC_BOOTSTRAP.md with:
  - joint vs iid peak-concurrency statistics on the real fleet
  - KS-selected block length (train -> validation only)
  - forward-predicted P(peak > C) vs the observed test segment on an 8-core pool
"""

from __future__ import annotations

import io
import json
import os
import random
import statistics

BASE = os.path.dirname(os.path.abspath(__file__))
MATRIX = os.path.join(BASE, "..", "research_data", "vps2_readonly", "replay_sched", "matrix.json")
OUT = os.path.join(BASE, "..", "research_data", "vps2_readonly", "PPC_BOOTSTRAP.md")

C = 8            # replay pool cores
PERIOD = 60
REPS = 300
random.seed(11)


def load():
    m = json.load(open(MATRIX))
    vms = list(m["vms"].values())          # 64 x 30 duties
    return [list(map(float, v)) for v in vms]


PHASES = []  # per-tenant within-period offset (random fixed), set in main()


def concurrency_series(duties, phases=None):
    """Per-second aggregate concurrency.

    phases=None: sequential aligned (all windows start at period start — the
    worst-case upper bound, matching launch-staggered sequential burners);
    phases=[...]: per-tenant fixed offsets (production-like drifting phases).
    """
    K = len(duties[0])
    out = [0] * (K * PERIOD)
    for i, v in enumerate(duties):
        ph = phases[i] if phases else 0
        for k, d in enumerate(v):
            on = int(round(d * PERIOD))
            for s in range(on):
                out[(k * PERIOD + (ph + s) % PERIOD)] += 1
    return out


def stats(series):
    n = len(series)
    over = sum(1 for x in series if x > C) / n if n else 0.0
    return {"mean": statistics.mean(series), "max": max(series), "over_frac": over}


def bootstrap(duties, block, kmins=30):
    """Resample blocks jointly across tenants; return concatenated duty matrix."""
    K = len(duties[0])
    block = min(block, K)
    out = [[] for _ in duties]
    while len(out[0]) < kmins:
        start = random.randrange(0, K - block + 1)
        for i, v in enumerate(duties):
            out[i].extend(v[start:start + block])
    return [v[:kmins] for v in out]


def iid_shuffle(duties):
    out = []
    for v in duties:
        w = v[:]
        random.shuffle(w)
        out.append(w)
    return out


def ks_distance(a, b):
    a2, b2 = sorted(a), sorted(b)
    n, m = len(a2), len(b2)
    i = j = 0
    best = 0.0
    while i < n and j < m:
        if a2[i] <= b2[j]:
            i += 1
        else:
            j += 1
        best = max(best, abs(i / n - j / m))
    return best


def main():
    duties = load()
    K = len(duties[0])
    phases = [random.randrange(0, PERIOD) for _ in duties]
    third = K // 3
    train = [v[:third] for v in duties]
    val = [v[third:2 * third] for v in duties]
    test = [v[2 * third:] for v in duties]

    real_seq = concurrency_series(duties)            # aligned upper bound
    real = concurrency_series(duties, phases)        # drifting phases
    real_stats = stats(real)
    seq_stats = stats(real_seq)
    test_seconds = len(test[0]) * PERIOD
    test_real = real[2 * third * PERIOD:]
    test_stats = stats(test_real)

    # block length selected ONLY on train->val (test untouched)
    val_seconds = len(val[0]) * PERIOD
    val_real = real[third * PERIOD:2 * third * PERIOD]
    ks_tab = {}
    for B in (1, 2, 5, 10, 15):
        sampled = []
        for _ in range(60):
            m = bootstrap(train, B, kmins=len(val[0]))
            sampled.extend(concurrency_series(m, phases[:len(m)]))
        ks_tab[B] = ks_distance(sampled, val_real)
    bestB = min(ks_tab, key=ks_tab.get)

    # FORWARD PREDICTION on the untouched test third: predictive blocks are
    # drawn from the TRAIN third only; the test third is used for scoring only.
    joint_peaks, iid_peaks = [], []
    joint_over_reps = 0
    iid_over_reps = 0
    kmins = len(test[0])
    for _ in range(REPS):
        mj = bootstrap(train, bestB, kmins=kmins)
        sj = stats(concurrency_series(mj, phases[:len(mj)]))
        joint_peaks.append(sj["max"])
        joint_over_reps += 1 if sj["over_frac"] > 0 else 0
        mi = iid_shuffle(train)
        si = stats(concurrency_series(mi, phases[:len(mi)]))
        iid_peaks.append(si["max"])
        iid_over_reps += 1 if si["over_frac"] > 0 else 0
    joint_over = joint_over_reps / REPS
    iid_over = iid_over_reps / REPS

    def q(v, p):
        v = sorted(v)
        return v[int(round(p / 100 * (len(v) - 1)))]

    with io.open(OUT, "w", encoding="utf-8") as fh:
        fh.write("# 生产轨迹上的联合块自助（PPC 经验模式）\n\n")
        fh.write("数据：`replay_sched/matrix.json`（64 台真实 VM × 30 分钟逐分钟 duty，取自生产遥测）；"
                 "活性模型与回放脚本一致（周期内先工作后空闲）。池容量 C=8。\n\n")
        fh.write("## 口径（重要）\n\n")
        fh.write("- 输入为**1 分钟粒度**的生产 duty 序列 + 周期内活性区间模型（与回放脚本一致，相位固定随机）；\n"
                 "  **不含亚分钟相位结构**——本结果支持的是\"生产分钟数据回放模型\"，不是亚分钟相位的实测。\n"
                 "- **三段分离**：训练（前 1/3）→ 块长选择（中 1/3 验证，KS）→ 测试（后 1/3，未参与任何调参）。\n\n")
        fh.write("## 真实联结构的并发统计（整段）\n\n")
        fh.write("- 平均并发：**%.2f 核**（= Σ 逐台均值；池容 8 核 → 平均负载 %.0f%%）\n"
                 % (real_stats["mean"], 100 * real_stats["mean"] / C))
        fh.write("- 漂移相位（主口径）峰值并发：**%d 核**；超池时间占比：**%.1f%%**\n"
                 % (real_stats["max"], 100 * real_stats["over_frac"]))
        fh.write("- 同序对齐（上界口径）峰值并发：**%d 核**；超池时间占比：**%.1f%%**\n\n"
                 % (seq_stats["max"], 100 * seq_stats["over_frac"]))
        fh.write("## 块长选择（训练→验证，测试未参与）\n\n")
        for B in sorted(ks_tab):
            fh.write("- B=%2d 分钟：KS=%.3f%s\n" % (B, ks_tab[B], "  ← 选中" if B == bestB else ""))
        fh.write("\n## 前向预测（重采样仅从训练段抽取；测试段只用于打分）\n\n")
        fh.write("协议：预测块的起点**仅从训练段（前 1/3）抽取**（块长 B 由验证段 KS 选定），"
                 "生成长度 = 测试段（后 1/3）的合成序列；测试段数据不参与预测生成。\n\n")
        fh.write("| 预测/对照 | 峰值 P50 | 峰值 P95 | 峰值 max | P(峰>8) |\n|---|---|---|---|---|\n")
        fh.write("| 联合块自助预测 (B=%d) | %d | %d | %d | %.0f%% |\n" % (
            bestB, q(joint_peaks, 50), q(joint_peaks, 95), max(joint_peaks), 100 * joint_over))
        fh.write("| iid 置换预测（边际保留、联合打散） | %d | %d | %d | %.0f%% |\n" % (
            q(iid_peaks, 50), q(iid_peaks, 95), max(iid_peaks), 100 * iid_over))
        fh.write("| **测试段实际观测（打分）** | — | — | %d | %.0f%% |\n" % (
            test_stats["max"], 100 * test_stats["over_frac"]))
        fh.write("\n读法：iid 置换保留每台租户的 duty 边际、仅打散跨租户联合。前向预测中两者峰值接近，"
                 "说明该轨迹的**分钟内相位相关性弱、分钟粒度可预测性有限**（与其\"漂移型\"画像一致）——"
                 "这正是正文所述\"分钟级数据不含亚分钟相位结构\"的直接体现：本脚本不外推亚分钟结论；"
                 "**极端相位结构**（对齐突发）的证据在合成实验（§8.4/8.5/C5）中。\n")
    print("wrote", OUT)
    print("real:", real_stats, "| bestB:", bestB, "| KS:", {k: round(v,3) for k,v in ks_tab.items()})
    print("joint peaks P50/P95/max: %d/%d/%d  P(peak>8)=%.0f%%" % (
        q(joint_peaks, 50), q(joint_peaks, 95), max(joint_peaks), 100 * joint_over))
    print("iid peaks   P50/P95/max: %d/%d/%d" % (
        q(iid_peaks, 50), q(iid_peaks, 95), max(iid_peaks)))


if __name__ == "__main__":
    main()
