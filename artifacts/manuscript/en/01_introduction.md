# 1 Introduction

## 1.1 Background

In the cheap-VPS market, sellers survive by packing many low-utilization customer VMs onto a small number of physical cores. We observed two real production hosts (anonymized): one carries 64 running customer VMs (70 vCPUs configured) on 4 physical cores / 8 logical threads; another (50 cores) configures 285 VMs with 276 running (8.3x vCPU, 2.0x memory oversubscription). For small providers oversubscription is not an optional optimization but the business model: "1 core, 2 GB" is cheap precisely because most tenants are idle most of the time. The hard part is not "whether to oversubscribe" but three ordered technical problems: **can we see it (identify), can we predict it (predict), can we push it (actuate)**.

## 1.2 Three Problems

- **Identify: demand is censored, and aggregates cannot fully recover it.** CPU quotas are standard; once a tenant hits its cap, its "usage" no longer represents demand — a tenant throttled at 50% while wanting 100% looks like an idle one. We further formalize this: from aggregate (usage, throttle-fraction) counters alone, **no estimator that sees only these counters can be correct for all workloads** (exact non-identifiability — identical observations, different demand; stronger than statistical unbiasedness; construction in Section 3.3.1); what can be certified is a point estimate of the running-stretch mean plus a shape-free floor $q(1+t)$. The honest posture is to write down the identifiability boundary rather than pretend exact recovery.
- **Predict: capacity is set by phase structure, not average utilization.** With the same per-tenant duty (20%), 64 tenants in random phase safely sell 28 seats (P5 ≥ 70% bar; fine-scanned boundary [28,32)) while fully aligned tenants sell only 8 (boundary [8,10)); and a 35%-busy synchronized set collapses while a 98%-busy random set stays safe — **safety is not identifiable from utilization**. Phase structure is measurable from one-second per-tenant history (phase profiles) and can even be arranged at provisioning time (phase scattering).
- **Actuate: efficiency levers must be split into invisible gains and tenant-visible regressions.** Core isolation, KSM dedup, and free-page reporting are invisible to tenants; quotas, IO caps, and zram carry explicit prices. The product space of a small provider is exactly "how far density can be pushed without reducing tenant-visible resources".

> Organizing thesis: the three problems tighten into **observation necessity** — three capabilities (censoring identification / phase resolution / time resolution) are each necessary (Section 3.6) and jointly sufficient for our target workload family (an empirical statement); the Section 7 showdown attributes each baseline's failure to exactly the capability it lacks.

## 1.3 Approach Overview

Two self-built testbeds make the problems verifiable: a **nested PVE bed** (4 vCPU / 19.5 GiB, 16 tenants) and a **bare-metal bed** (2x Xeon 8259CL, 96 threads / 991 GiB, 64-VM fleet; isolation claim verified against SMT/NUMA topology), anchored by read-only telemetry from two production hosts. Around the three pillars:

1. **Identify** — the censoring identifiability analysis (Section 3.3.1), a 90-cycle paired validation, and a mixed-occupancy three-estimator ablation (naive / quota-scaled / throttle-corrected).
2. **Predict** — the density law $N^* = C/(\varphi + (1-\varphi)\rho) = C/(\rho\kappa)$; three-point mixed-phase validation, the anti-phase arrangement experiment, and threshold-qualified capacity curves (primary bar P5 ≥ 70%).
3. **Actuate** — risk-calibrated admission (pseudocode and calibration protocol in Section 5.3.1) landing on the capacity oracle in an online head-to-head showdown; no-regression controls (KSM/FPR/zram, adaptive IO; micro-period quotas re-measured — the earlier +35% claim is withdrawn, Section 9.1) raising density per resource.

## 1.4 Headline Findings

- **Identify**: five pegged tenants at 30% quota show 1.50 cores on the usage panel against 5.00 cores of true demand (3.3x, 7/7 rounds); in the v2 repeat (50% quota), throttle-corrected estimates hit the truth in all 90 cycles and naive "release" decisions violate in **90/90**; the v3 rework (30% quota, 90 cycles) replicates the direction (naive 3.6x under-report; corrected median |err| 0.55 cores, 88/90 within ±20%); a mixed-occupancy ablation (3 pegged + 3 idle @30%, truth 3.3) yields aggregate errors — naive -2.31 (unsafe), quota-scaling +0.01 (smallest *in this sample* because bursty peaks saturate the quota), throttle correction -0.20, full-vCPU +2.70, uncapped -0.16 — while per tenant, saturated tenants are exact under both methods and the window-averaged throttle fraction is diluted by idle time for bursty tenants (0.033 vs true 0.10); estimator choice must rest on per-tenant correctness, with multi-resolution throttle sequences (Ch. 9) fixing the dilution.
- **Predict**: the density law hits three mixed-phase break points on the physical host — $\varphi$=0.50 predicted 13.3 (13 pass, 16 fail), $\varphi$=0.75 predicted 10.0 (10 pass, 13 fail), $\varphi$=0.25 predicted 20.0 (20–24 pass, 28 fail); random-vs-aligned safe capacity ratio 3.5× at the primary bar (3.5×–4× across bars); the utilization-impossibility counterexample (35% vs 98%).
- **Actuate**: isolation is the only lever surviving every storm (physical-core verified); the fixed phase-aware admission stops **inside the fine-scanned synchronized bracket (8 seats; 10 = first fail)**; KSM reclaims **21.9 GB (33.4% of fleet RAM)** with service P99 0.73→0.76 ms, and idle "1 GB" VMs hold only 156–315 MB of host memory (free-page reporting already returning free pages) — the key enabler of memory density.
- **Evidence strength**: 100-round knee (v2/v3), 180-cycle censoring (two batches), 30-round triple storm (4+26), 4-round fine scan, 3-round sync; explicit statistics (round-clustered, binomial bounds, P99 primary), anomalies (OOM-offline VMs, degraded rounds, batch drift) archived and merged via the v3 rework.

## 1.5 Contributions

**Primary contributions (the paper's spine: Identify + Actuate)**

1. **Identify (censoring identifiability + cross-batch validation)**: the running-stretch-mean estimator with exactness conditions, a conditional floor, an aggregate non-identifiability construction, and validation across 180 cycles / 60 independent rounds (two batches).
2. **Actuate (phase-aware admission + intervention evidence)**: the complete risk-calibrated admission specification (pseudocode, parameters, calibration protocol), the complete 14-round showdown (both-bar final), the C5 anti-phase intervention (same tenants; phase arrangement alone changes capacity x2/x4), and fine-scan boundary pinning (sync [8,10), rand [28,32)).

**Supporting contributions (serve the spine; not standalone claims)**

3. **Predict (approximation model + three-artifact PPC)**: the assumption-explicit safe-capacity approximation and the PPC (parametric / empirical forward prediction / online actuator), with honestly reported prediction quality (4/5 zero over-admission; the optimistic sync case is vetoed by the online peak gate) — prediction is step advice and risk ranking; the online gate carries safety.
4. **Efficiency ledger (supports the density ceiling, Chapter 9)**: the per-resource no-regression ledger for CPU/memory/IO (KSM/FPR zero-visible-regression; zram/quota/IO caps explicitly priced).

**Platform + artifacts**: two testbeds, production telemetry, all scripts and raw data.

## 1.6 Structure

Section 2 related work; Section 3 system model and problem definition (incl. 3.3.1 identifiability); Section 4 measurement study; Section 5 design (risk-calibrated admission and the no-regression control stack, with algorithm pseudocode); Section 6 implementation and testbed; Section 7 evaluation (showdown, triple storm, estimator characterization); Section 8 physical-host validation and the density law; Section 9 resource-efficiency modules (KSM/FPR/zram/adaptive IO, incl. the micro-period self-audit correction); Section 10 discussion and limitations; Section 11 conclusion.
