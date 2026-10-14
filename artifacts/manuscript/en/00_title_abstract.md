# Title Page & Abstract

## Authors

Kaixiang Nie — Fujian Chuanzheng Communications College

## Title

**Identify, Predict, Actuate: Safe VPS Density Maximization under Censored Demand, Phase Structure, and Domain-Scoped No-Regression Constraints**

(alternate): *No-Regression Resource Efficiency for Small VPS Hosts: Censoring Identifiability, the Density Law, and Precision Control*

## Abstract

Small VPS providers pack many cheap, mostly-idle, occasionally-bursty tenants onto few physical
cores; oversubscription is their business model. We recast safe oversubscription as three ordered
problems. **Identify**: demand behind quota censoring is unobservable, because a usage dashboard shows
the quota, not the demand. The point estimate equals the mean over the running stretch, exact when the
running and throttled stretch means agree; a conditional floor q(1+t) holds under continuous
saturation; and from aggregate counters alone no estimator can be correct for all workloads, since two
processes can produce identical observations with different demand. Across 180 cycles in two batches,
throttle-corrected estimates track the truth while naive quota-release decisions violate the SLO in
all 30 independent rounds. **Predict**: capacity is set by phase structure, not average utilization. At
the same 20% duty, random-phase and aligned fleets differ 3.5x in safe capacity: 28 versus 8 seats at
the primary bar of customer P5 >= 70%, with fine-scan boundaries [28,32) and [8,10). The aligned
boundary is invariant across aggregation conventions, the random end tightens to 26 under the
strictest, and the median bar gives 40 versus 10. A 35%-busy set collapsing while a 98%-busy set stays
safe shows that safety cannot be read off utilization. On top of an assumption-explicit approximation
N* = C/(rho*kappa) we build the Phase-Profile Convolution (PPC): convolving on the joint phase
structure separates five phase configurations (two edge-exact, two conservative, one optimistic step
blocked by the online gate), whereas iid convolution returns one prediction for all - a provable blind
spot we call the marginal illusion. **Organizing thesis**: the bottleneck of safe-capacity decisions is
observational capability. Censoring identification, phase resolution and time resolution are each
necessary (three constructive counterexamples, Section 3.6) and jointly sufficient for our target
workload family, an empirical statement; the admission controller implements that observation set and
is the only policy in the complete 14-round showdown that combines competitive random-phase capacity
(16-20 seats) with the conservative aligned-phase stop at 8 seats, whose customer P5 is about 99% over
four ladder rounds. **Actuate**: domain-scoped no-regression control. The showdown ran seven policies
under identical arrival streams; the audible-style and busy-threshold baselines sell 40 seats in the
aligned phase and collapse customer P5 to 16%, while fixed 2x stops at 16 with P5 only 48.6%.
Isolation is verified at physical-core level against SMT/NUMA topology; on the memory axis,
balloon-free reclaim (KSM dedup 21.9 GB, 33.4% of fleet RAM; free-page reporting; zram) raises density
without shrinking tenant-visible resources. All claims rest on mass repeats (100/180/30-round
campaigns), two testbeds, and read-only telemetry from two production hosts we operate (285 VMs
configured, 8.3x vCPU oversubscription), with released artifacts and a statistical certification
protocol.

## What This Paper Solves (problem → approach → quantified result)

| # | Problem | Why common practice fails (measured) | Our approach | Quantified result |
|---|---|---|---|---|
| 1 | Quotas censor demand: the usage panel != demand | "Release/oversell on visible headroom" violates in 7/7 → 90/90 runs (30 independent rounds) | Throttle-evidence point estimate + identifiability boundary (3 propositions) + saturated backstop | Estimates match truth (<=9% → exact); release decisions correctly refused; mixed-occupancy ablation (aggregate error): naive -2.31 (unsafe), quota-scaling +0.01 (smallest here only because bursty peaks saturate the quota), throttle correction -0.20, full-vCPU +2.70; per-tenant, saturated tenants are exact under both while window-averaged throttling dilutes for bursty tenants (multi-resolution fix in Ch. 9) |
| 2 | Instantaneous overlap / synchronized bursts break the tail | Average utilization is blind to phase: a 35%-busy set collapses while a 98%-busy set is safe | Phase-profile aggregation + safe-capacity approximation + PPC (joint-phase convolution) | Random 28 vs aligned 8 seats (primary bar P5>=70%, 4 rounds); PPC 4/5 zero over-admission (1 optimistic case vetoed by the online gate); iid convolution provably blind |
| 3 | No evidence for choosing control levers | Soft priorities are relied upon: 100x CPU weight still 24 ms; io.weight inert | Controlled comparisons → shaping playbook (isolation first, hard caps, memory double-gate) | Isolation: 29 of 30 storm rounds with zero service violations (1 degraded round at 25.3 ms); io.max: service P99 12.1→2.7 ms |
| 4 | Memory oversubscription vs "no visible shrink" | Ballooning shrinks guest-visible memory; without it the host never reclaims; swap amplifies reclaim tax | Balloon-free trio (KSM / free-page reporting / zram) + double gate | KSM reclaims 33.4% of fleet RAM (21.9 GB); an idle "1 GB" VM holds only 156-315 MB of host RAM, invisible to the guest |
| 5 | Rate is period-independent (self-audit correction) | We had reported "micro-period quotas +35%" — a clean-window re-measurement (qp2v1) proves it was a windowing artifact | Fresh burner window per config + guest `cpu.stat` delivery as ground truth | At 50% quota, 2 ms and 1 s deliver identically (0.500 cores each, ~52% of baseline); the +35% claim is withdrawn; services unaffected |
| 6 | Admission lacks fair validation and risk semantics | "Zero violations" is treated as a guarantee (the one-sided bound after 29/30 clean rounds is still ~14.9%) | Seven-policy, same-arrival-stream showdown + Clopper-Pearson certification protocol | Complete 14-round showdown: ours/ours_p both-bar safe (aligned 8, random 16-20); util80 sells 28 (safe) in random but collapses at 40 in sync (P5 16%); fine-scan boundaries sync [8,10), rand [28,32) |

**Keywords:** virtualization; oversubscription; admission control; censored demand; identifiability; cgroup v2; tail latency; density

**Status & honest gaps:** all campaigns, rework batches and Phase C modules are complete and merged (Sections 4/7/8/9); round-level ranges are reported throughout. Remaining before submission: formal round-level bootstrap intervals (post data-freeze) and a direct anti-aliasing sampling experiment (future work); five minor reference fields are being completed at packaging time.
