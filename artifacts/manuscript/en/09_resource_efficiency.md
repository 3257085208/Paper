# 9 Resource-Efficiency Modules

> This chapter carries the "no-regression resource-efficiency" pillar (skeleton §9): per-resource
> precision control measured under three no-regression constraints — service P99 ≤ 10 ms, no customer-rate
> degradation, and no reduction of tenant-visible memory. Phase C experiments are complete (zram3b/ioctl2/
> FPR/canary3) and the sections below are filled (Figures 22–26). **Positioning: this chapter is a supporting
> extension** — the main line is the Identify/Predict/Actuate chain of Sections 3/5/7/8; this chapter
> verifies that the no-regression principle extends across resources and provides density-ceiling context.

---

## 9.1 CPU: Micro-Period Quotas — a Self-Audit Correction (Figure 22)

**Background.** An early batch (qp2c: five pegged tenants at 50% quota, periods 2/4/10/100 ms/1 s)
reported that shrinking the period raised the tenant rate from 59% to 80% (+35%), and this number
entered the summary table.

**Audit and correction (qp2v1).** A pre-submission measurement audit found that qp2c's rate readings
come from the burner's **cumulative average within the current work phase** (rewritten every ~2 s),
while configs were only ~30 s apart — so **later configs read windows contaminated by earlier,
faster ones** (the uncapped segment at 25.6M inflated early readings). Clean re-measurement: fresh
burner window per config + synchronized 60 s windows + guest `cpu.stat` delivery as ground truth:

| Config | Delivered CPU | Throttled | Rate | Rate/core |
|---|---|---|---|---|
| uncapped | 1.000 cores | 0% | 25.8M | 25.8M |
| 2 ms (50% quota) | 0.500 cores | 50% | 13.2–13.4M | 26.4–26.8M |
| 1 s (50% quota) | 0.500 cores | ~50% | 13.3M | 26.6M |

**Corrected conclusion.** At 50% quota, **2 ms and 1 s deliver identically** (0.500 cores each, ~52%
of baseline, difference <1%); **the +35% claim is withdrawn** (summary table corrected in step).
Services are unaffected by the period (0.73–0.75 ms; the qp2c service data remain valid). **Lessons,
fixed in `tb_qp2v.py`:** throughput comparisons must (i) reset the cumulative window per config
and (ii) cross-check against cgroup delivery rather than the rate file.

**Boundaries.** Pure CPU-pegged busy loops; period effects on latency-sensitive/mixed workloads are
untested (future work).

## 9.2 Memory: Balloon-Free Reclaim Trio (Figures 23–25) — partial

**Done so far.** (i) **KSM fleet dedup (ksm1; see the kernel documentation [21])**: 64 same-image VMs share **21.9 GB = 33.4% of fleet RAM**;
ksmd ≈ 0.16 core; service P99 0.73→0.76 ms (zero regression). Cost boundaries: write-CoW latency untested;
cross-tenant dedup carries known side-channel concerns — enable per trust domain in production.
(ii) **Free-page reporting (manual verification, 300 MB)**: host `memory.current` 315→629 MB with the guest
allocation and returns 6–12 s after free; guest `MemTotal` stays 973 MB throughout. Side finding: an idle
"1 GB" VM holds only 156–315 MB of host RAM (FPR has been returning free pages all along).
(iii) Automated FPR (fpr5, 300 MB): host `memory.current` 571→875→570 MB (vm312) and 581→878→575 MB
(vm313), **303 MB reclaimed**, guest `MemTotal` unchanged at 973 MB — matching the manual result (fpr4 had
failed because the balloc call lacked the `debian@` user prefix; fixed and rerun). (iv) **zram absorption
(zram3b, after a unit fix)**: allocation reached the **1120 GB target**, with **176.8 GB of overflow fully
absorbed by zram** (3.1 GB physical memory after compression, `mem_used` 3.5 GB; compressible cold pages —
real workloads would compress less); mid-storm service P99 stayed flat at **0.745 ms**. The disk-swap arm
**aborted at 1044 GB** (the 96 GB swapfile exhausted first) — the "zram absorbs / disk insufficient"
contrast holds. (v) **QoE canary (canary3)**: two independent canary VMs running a 200 ms wakeup loop show
max gap **0.1 ms** (zero >250 ms stalls) across baseline / rand40 / sync32 / mix50_40 — no scheduling stalls
under either density or phase arrangement.

## 9.3 IO: Tenant Storms vs Service (Figure 26)

**Completed (ioc2, after fixing deployment).** Eight storm tenants running 4K random 70/30 O_DIRECT for
60 s per arm: host **~98k IOPS**, aggregate tenant **~66k IOPS** (n=8), tenant per-op P99max **8.3 ms**;
across the three arms (none / static / adaptive) the service HTTP P99 stays at **0.743–0.756 ms** — the
tenant storm does not touch the service (isolation envelope); arm differences <1% (adaptive shows no
advantage under this load).

## 9.4 Relation to the (Domain-Scoped) No-Regression Constraint

Per-mechanism ledger (density gain / hidden cost / tenant-visible regression): **KSM, FPR and isolation
are zero-visible-regression** (customer rate distribution and visible configuration unchanged); **zram's
cost is host-side compression work** (service unaffected; the compression ratio is reported for
compressible cold pages); **quotas and IO caps are explicitly priced on the throttled tenants**
(rate, queueing) — closing the loop with Chapter 5's "economy tier = a priced degradation budget".
Data sources: ksm1 (21.9 GB = 33.4% dedup, ksmd ~0.16 core, service P99 0.73→0.76 ms); fpr1/fpr5 (idle
"1 GB" VMs hold 156–315 MB; a 300 MB allocation reclaims 303 MB with the guest-visible memory unchanged);
zram3b (three arms: none aborts ~940 GB without swap / zram reaches 1120 GB with 176.8 GB absorbed and a
flat P99 / disk swapfile exhausts at 96 GB and aborts).
