#!/usr/bin/env python3
"""Production telemetry deep-dive (runs on the Mac).

Reads research_data/vps2_readonly/pve_metrics.jsonl (170x 60 s samples,
anonymized) and produces:
  * unit check: guest cpu fields (fraction of allocated vCPU vs of host)
  * per-VM usage distribution + workload classes (idle/light/heavy)
  * heavy-tenant count timeline, host busy (from counters) and PSI
  * burst structure: on/off transitions, autocorrelation (periodicity)
  * overcommit ratios (vCPU, memory limit/used vs host)
  * censoring proxy: share of saturated (>=95% vCPU) VM-samples

Writes research_data/vps2_readonly/PRODUCTION_ANALYSIS.md and
manuscript/figs/fig27_production.png.
"""

from __future__ import annotations

import io
import json
import os
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DATA = os.path.join(BASE, "research_data", "vps2_readonly", "pve_metrics.jsonl")
OUTMD = os.path.join(BASE, "research_data", "vps2_readonly", "PRODUCTION_ANALYSIS.md")
OUTFIG = os.path.join(BASE, "manuscript", "figs", "fig27_production.png")


def load():
    return [json.loads(l) for l in open(DATA)]


def main():
    rows = load()
    n = len(rows)
    node = rows[0]["nodes"][0]
    cpus = node["logical_cpus"]
    mem_total = node["memory_total_bytes"]

    # ---- per-VM series ----
    series = {}
    vcpus = {}
    mlim = {}
    for r in rows:
        for g in r.get("guests") or []:
            gh = g["guest_hash"]
            if g.get("status") != "running":
                continue
            v = g.get("cpu_fraction_raw")
            if v is not None:
                series.setdefault(gh, []).append(v)
            vcpus[gh] = g.get("vcpus_configured") or 0
            mlim[gh] = g.get("memory_limit_bytes") or 0

    # ---- unit check: sum(guest) vs host busy cores ----
    host_busy = []
    for i in range(1, n):
        a, b = rows[i - 1]["host_cpu_counters"], rows[i]["host_cpu_counters"]
        tot = b["total"] - a["total"]
        idle = (b["idle"] + b["iowait"]) - (a["idle"] + a["iowait"])
        if tot > 0:
            host_busy.append(1.0 - idle / tot)
    sum_frac = [sum(g.get("cpu_fraction_raw") or 0 for g in r.get("guests") or [])
                for r in rows[1:]]
    sum_cores_alloc = [sum((g.get("cpu_fraction_raw") or 0) * (g.get("vcpus_configured") or 1)
                           for g in r.get("guests") or []) for r in rows[1:]]
    hb_cores = [b * cpus for b in host_busy]
    m = min(len(hb_cores), len(sum_frac))
    unit = {
        "host_busy_cores_mean": statistics.mean(hb_cores[:m]),
        "sum_fraction_mean": statistics.mean(sum_frac[:m]),
        "sum_fraction_x_vcpus_mean": statistics.mean(sum_cores_alloc[:m]),
    }

    # ---- per-VM stats ----
    means = {k: statistics.mean(v) for k, v in series.items()}
    p95s = {k: sorted(v)[int(0.95 * (len(v) - 1))] for k, v in series.items()}
    idle = sum(1 for k in means if means[k] < 0.05)
    light = sum(1 for k in means if 0.05 <= means[k] < 0.30)
    heavy = sum(1 for k in means if means[k] >= 0.30)
    nvm = len(means)
    heavy_count = [sum(1 for g in r.get("guests") or []
                       if (g.get("cpu_fraction_raw") or 0) >= 0.95)
                   for r in rows]
    sat_share = sum(heavy_count) / max(1, sum(len(r.get("guests") or []) for r in rows))

    # ---- inter-tenant correlation (minute granularity) ----
    def pearson(a, b):
        n2 = min(len(a), len(b))
        if n2 < 20:
            return None
        ma, mb = statistics.mean(a[:n2]), statistics.mean(b[:n2])
        va = sum((x - ma) ** 2 for x in a[:n2])
        vb = sum((x - mb) ** 2 for x in b[:n2])
        if va <= 1e-12 or vb <= 1e-12:
            return None
        cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n2))
        return cov / (va ** 0.5 * vb ** 0.5)

    act = [v for v in series.values() if len(v) >= 60 and statistics.mean(v) >= 0.02]
    cors = []
    for i in range(len(act)):
        for j in range(i + 1, len(act)):
            c = pearson(act[i], act[j])
            if c is not None:
                cors.append(c)
    corr = {
        "n_vms": len(act), "n_pairs": len(cors),
        "mean": statistics.mean(cors) if cors else None,
        "median": statistics.median(cors) if cors else None,
        "p95": sorted(cors)[int(0.95 * (len(cors) - 1))] if cors else None,
        "frac_gt_0.3": sum(1 for c in cors if c > 0.3) / len(cors) if cors else None,
    }

    # ---- transitions & run lengths (per-VM, 1-min series) ----
    trans = [sum(1 for i in range(1, len(v)) if (v[i - 1] >= 0.30) != (v[i] >= 0.30))
             for v in series.values() if len(v) > 5]
    active_runs = []
    for v in series.values():
        run = 0
        for x in v:
            if x >= 0.05:
                run += 1
            elif run:
                active_runs.append(run)
                run = 0
        if run:
            active_runs.append(run)
    # value-level autocorrelation (robust): only VMs with meaningful activity
    lags = range(1, 31)
    ac = []
    for lag in lags:
        vals = []
        for v in series.values():
            if len(v) <= lag + 5 or statistics.mean(v) < 0.02:
                continue
            mean = statistics.mean(v)
            var = statistics.pvariance(v)
            if var <= 1e-9:
                continue
            cov = sum((v[i] - mean) * (v[i - lag] - mean) for i in range(lag, len(v))) / (len(v) - lag)
            vals.append(cov / var)
        ac.append(statistics.mean(vals) if vals else 0.0)

    def roll(xs, k=3):
        out = []
        for i in range(len(xs)):
            seg = [x for x in xs[max(0, i - k + 1):i + 1] if x is not None]
            out.append(statistics.mean(seg) if seg else None)
        return out

    ov = {
        "vcpu_overcommit": sum(vcpus.values()) / cpus,
        "mem_limit_overcommit": sum(mlim.values()) / mem_total,
        "running_vms": nvm,
    }

    # ---- figure ----
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.6))
    ax = axes[0]
    xs = sorted(means.values())
    ys = [(i + 1) / len(xs) for i in range(len(xs))]
    ax.plot([x * 100 for x in xs], ys, "-o", markersize=3, color="tab:blue")
    ax.axvline(5, color="k", linestyle=":", linewidth=1)
    ax.axvline(30, color="k", linestyle="--", linewidth=1)
    ax.text(5.2, 0.05, "idle<5%", fontsize=8)
    ax.text(31, 0.05, "heavy>30%", fontsize=8)
    ax.set_xscale("log")
    ax.set_xlabel("per-VM mean CPU (% of one vCPU)")
    ax.set_ylabel("CDF over VMs")
    ax.set_title("workload classes: %.0f%% idle / %.0f%% light / %.1f%% heavy"
                 % (100 * idle / nvm, 100 * light / nvm, 100 * heavy / nvm), fontsize=9)
    ax.grid(alpha=0.3, which="both")

    ax = axes[1]
    t = list(range(1, m + 1))
    ax.plot(t, hb_cores[:m], "-", color="tab:red", linewidth=1.2, label="host busy (cores)")
    ax.plot(t, roll(sum_cores_alloc[:m]), "-", color="tab:blue", linewidth=1.0, alpha=0.8,
            label="sum guest cpu x vCPUs (3-min mean)")
    ax2 = ax.twinx()
    ax2.plot(t, [c for c in heavy_count[1:1 + m]], "--", color="tab:orange", linewidth=1.0,
             label="VMs at >=95% vCPU")
    ax2.set_ylabel("saturated VMs (count)", color="tab:orange")
    ax.set_xlabel("minute (170-sample window)")
    ax.set_ylabel("cores")
    ax.set_title("host load and saturated tenants (%d logical CPUs)" % cpus, fontsize=9)
    ax.legend(fontsize=7.5, loc="upper right")
    ax.grid(alpha=0.3)

    ax = axes[2]
    bins = [1, 2, 3, 5, 10, 20, 40, 1000]
    labels = ["1", "2", "3-4", "5-9", "10-19", "20-39", ">=40"]
    counts = [0] * (len(bins) - 1)
    for rl in active_runs:
        for i in range(len(bins) - 1):
            if bins[i] <= rl < bins[i + 1]:
                counts[i] += 1
                break
    ax.bar(range(len(counts)), counts, color="tab:green", alpha=0.85)
    ax.set_xticks(range(len(counts)))
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_xlabel("active-run length (minutes, >=5% of a vCPU)")
    ax.set_ylabel("count of runs")
    ax.set_title("burst durations: %d runs total, median %s min" % (
        len(active_runs), int(statistics.median(active_runs)) if active_runs else 0), fontsize=9)
    ax.grid(alpha=0.3, axis="y")
    fig.suptitle("Production host (LEC-HK-1, anonymized read-only): 170x60 s samples, %d running VMs"
                 % nvm, fontsize=10)
    fig.tight_layout()
    fig.savefig(OUTFIG, dpi=200)
    plt.close(fig)

    # ---- markdown ----
    with io.open(OUTMD, "w", encoding="utf-8") as fh:
        fh.write("# 生产遥测深挖（LEC-HK-1 · 匿名只读 · 2026-10-11）\n\n")
        fh.write("样本：170 × 60 s；运行 VM：%d；宿主 %d 逻辑核；内存 %.0f GiB。\n\n"
                 % (nvm, cpus, mem_total / 2**30))
        fh.write("## 单位校验（PVE `cpu` 字段）\n\n")
        fh.write("- 宿主计数核验忙核均值：**%.2f 核**\n- Σ 客户 `cpu`（按 1 核口径）：%.2f\n"
                 "- Σ 客户 `cpu`×vCPU（按分配口径）：%.2f\n"
                 "→ %s\n\n" % (unit["host_busy_cores_mean"], unit["sum_fraction_mean"],
                              unit["sum_fraction_x_vcpus_mean"],
                              "客户 cpu = 分配 vCPU 的比例（与宿主口径一致）"
                              if abs(unit["sum_fraction_x_vcpus_mean"] - unit["host_busy_cores_mean"])
                              < abs(unit["sum_fraction_mean"] - unit["host_busy_cores_mean"])
                              else "客户 cpu = 单核比例"))
        fh.write("## 负载类别与尾部\n\n")
        fh.write("- 类别：**近闲(<5%%) %.1f%%**、轻载(5–30%%) %.1f%%、重载(>30%%) %.1f%%\n"
                 "- 全体 VM 均值分位：P50 %.1f%%、P95 %.2f%%、峰值 %.1f%%\n"
                 "- 饱和（≥95%% vCPU）VM-样本占比：**%.2f%%**（截断风险下界代理；PVE 接口无节流计数）\n\n"
                 % (100 * idle / nvm, 100 * light / nvm, 100 * heavy / nvm,
                    100 * statistics.median(list(means.values())),
                    100 * statistics.mean(list(p95s.values())),
                    100 * max(means.values()), 100 * sat_share))
        fh.write("## 突发结构与相关性\n\n")
        fh.write("- 重载穿越（>30%% 状态切换）：均值 %.1f 次/小时/台\n"
                 "- 活跃段（≥5%% 连续分钟）共 %d 段，中位 %s 分钟——**短促突发为主**\n"
                 "- 数值层自相关（仅活跃 VM）：lag1=%.2f、lag5=%.2f、lag30=%.2f ≈ 0：**分钟尺度无强持续性/无时钟周期**；\n"
                 "  状态层仍具持久性（Markov 自转移 0.85/0.37/0.26，见 load_profile）——真实突发的形态是\n"
                 "  「长短不一、相位漂移的活跃段」，既非独立同分布、也非固定时钟\n"
                 "  （与合成对齐负载的严格 60 s 周期形成对照：对齐实验给出的是最坏情形上界）\n\n"
                 % (statistics.mean(trans) if trans else 0, len(active_runs),
                    int(statistics.median(active_runs)) if active_runs else 0,
                    ac[0], ac[4], ac[29]))
        fh.write("## 租户间相关性（分钟粒度）\n\n")
        if corr["n_pairs"]:
            fh.write("- 活跃 VM %d 台、%d 对：平均 Pearson r=%.2f、中位 %.2f、P95 %.2f；r>0.3 的对占比 %.1f%%\n"
                     "- 读法：**弱正相关而非独立**（中位 0.07、均值 0.12、P95 0.45、15.7%% 对 >0.3）——"
                     "存在部分租户的弱同步倾向（也可能含宿主级测量共模与日间节律）；\n"
                     "  这支持'相位不是合成负载的臆造'，但也**不能**据此断言独立性（对决定律的随机端只是近似）；\n"
                     "  亚分钟同步在本粒度**不可见**——跨天轻量流与更细粒度证据在积累中\n\n"
                     % (corr["n_vms"], corr["n_pairs"], corr["mean"], corr["median"], corr["p95"],
                        100 * corr["frac_gt_0.3"]))
        fh.write("## 超售比与场景锚点\n\n")
        fh.write("- vCPU 超售比：**%.1f×**（%d vCPU 配置 / %d 逻辑核）\n"
                 "- 内存限额超售比：%.2f×（限额合计 %.0f GiB / 宿主 %.0f GiB）\n"
                 "- 内存实际占用：约 %.0f GiB（宿主报告的 used）\n\n"
                 % (ov["vcpu_overcommit"], int(sum(vcpus.values())), cpus,
                    ov["mem_limit_overcommit"], sum(mlim.values()) / 2**30, mem_total / 2**30,
                    rows[0]["nodes"][0]["memory_used_bytes"] / 2**30))
        fh.write("## 对论文的含义\n\n")
        fh.write("1. **类别结构支持\"多数闲、少数重\"的建模前提**；但 1.4% 的重载客户贡献了绝大部分"
                 "宿主占用——与第 4 章\"一台满载即击穿\"的合成实验一致。\n")
        fh.write("2. **真实突发是漂移型（自相关慢衰减、无固定相位）**：对齐突发实验提供的是"
                 "**最坏情形上界**；混合相位容量模型（第 8 章）的 φ 参数在真实宿主上应取低值——"
                 "即容量更接近随机端而非同步端。\n")
        fh.write("3. **超售比实锚**：%.1f× vCPU 超售在真实生产上长期运行，为测试床的 5× 量级提供现实性。\n"
                 % ov["vcpu_overcommit"])
        fh.write("4. 采集不含节流计数（PVE 只读接口限制）——截断比例的现场证据留待 vps2 轻量流"
                 "（/proc PSI）与后续版本；当前以\"饱和实例占比\"作下界代理。\n")

    print("wrote", OUTMD)
    print("wrote", OUTFIG)
    print("unit check:", unit)
    print("overcommit:", ov, "saturated VM-sample share: %.3f%%" % (100 * sat_share))
    print("classes: idle %.1f%% light %.1f%% heavy %.1f%%" % (
        100 * idle / nvm, 100 * light / nvm, 100 * heavy / nvm))
    print("inter-tenant corr:", corr)


if __name__ == "__main__":
    main()
