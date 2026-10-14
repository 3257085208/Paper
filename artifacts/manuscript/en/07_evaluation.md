# 7 Evaluation

> Three evaluation groups: (A) admission-policy comparison; (B) shaping and protection-envelope comparison; (C) triple-storm synthesis validation, followed by the production-telemetry usage and an explicit gap list. Common SLO: service P99 ≤ 10 ms.

## 7.1 Setup Recap

Testbed and metrics: Sections 3–4 and 7. Admission comparisons use a closed loop: five candidate tenants arrive one at a time, a policy decides allow/defer from evidence visible at that moment, and allowed candidates are actually started and measured. Shaping comparisons use the neighbor sweep (0–5 tenants) plus the full triple storm. Every key conclusion replicates at least twice (knee: 5 rounds; censoring: 7 cycles; synthesis: 4 passes).

## 7.2 Admission-Policy Comparison (companion to Figure 4)

Four policies run over the same arrival sequence with the same evidence surface (two rounds in different orders):

| Policy | Evidence | Admitted (round A / B) | Violation windows | Worst P99 (HTTP/Redis) |
|---|---|---|---|---|
| Fixed ratio (2.0×) | Configuration only | 5 / 5 | 4 / 4 | 23.7 / 25.8 |
| Busy threshold (80%) | Host busy fraction | 3 / 3 | 0 / 0 | 7.8 / 5.7 |
| Historical demand budget | Per-VM usage quantile + budget | 3 / 3 | 0 / 0 | 6.1 / 4.8 |
| Calibrated + tail pause (candidate) | Demand budget + single-window P999 pause | 3 / 2 | 0 / 0 | 4.3 / 3.3 |

**Reading.** The fixed-ratio policy ignores all state and walks straight past the knee (Section 4), producing four violation windows — the cleanest counterexample. The three state-aware policies all stop at the knee (3 tenants) with zero violations, showing the knee is reachable from evidence. The candidate is more conservative but exposes an implementation flaw: single-window P999 (n ≈ 2 samples) is noisy, and round B was falsely paused by one 16.3 ms spike, giving up one safe tenant. **This is direct evidence that pause mechanisms need smoothing/hysteresis/longer windows** (already on the improvement list). Fairness note: every policy used only decision-time-visible information; allowed/rejected candidates were actually started or withheld (no post-hoc cherry-picking).

## 7.3 Censoring-Corrected Decisions (Direct Comparison of the Core Claim)

The scenario of Section 4.3 becomes a decision comparison (7 cycles): the same state (5 tenants capped at 30%, true demand 5.0 cores) is handed to two estimators:

| Decision | Evidence used | Action | Outcome |
|---|---|---|---|
| Naive (trust usage) | 1.50 cores used, "2.5 cores spare" | Release the caps (believed to be an optimization) | P99 16.7–25.0 ms, 7/7 violating |
| Censoring-aware | Throttle evidence → ≥ 5.00 cores | Refuse the release; report "no headroom, capacity action required" | No new load introduced; quota state holds (P99 9–14 ms, near the SLO line) |

**Reading.** Both decisions consume the same data and differ only in estimation: naive takes censored usage as demand and hallucinates half the host as empty; aware pins the demand lower bound above the quota using throttle evidence. The former action pushes the host into instantaneous saturation (tenants at 27–32 M it/s, host at 100%); the latter avoids the self-inflicted wound and emits the correct capacity signal. We keep the detail that the quota state itself sits near the SLO line: **this host is already at the overload boundary, and the upper action (migrate/upgrade) is out of scope here.**

## 7.3b Method Ablation and Cold Start (Preliminary, Figure 11)

**Ablation (censoring scenario).** Six candidates arrive one at a time, each shaped with a 50% cap on admission; four estimators/decisions run the same sequence:

| Policy | Admitted (of 6) | Violation windows | Notes |
|---|---|---|---|
| naive (usage) | 6 | 3 | P99 17.8/15.6/20.7 ms from the 4th tenant |
| AUDIBLE-style (MC convolution, uncorrected) | 6 | 4 | likewise sees only the 50%-censored usage; 10.5 ms already at tenant 3 |
| aware (censoring-fixed) | 3 | 0 | stops exactly at the knee (9.8 ms brushes the line) |
| aware + calibration + tail pause | 1 | 0 | a single window with P999 = 12.2 ms falsely paused it with no recovery — another instance of "pausing needs smoothing/hysteresis" |

**Cold start (no history).** Two arrival populations x three priors:

| Prior | All-heavy arrivals | All-light arrivals |
|---|---|---|
| optimistic (0.2 core) | 6 admitted, 4 violation windows (11.7–17.2 ms) | 6 admitted, 0 violations (but a wrong bet breaks the SLO) |
| conservative (charge configured 1.0 core) | 3 admitted, 1 violation window (at the line) | only 3 admitted — 3 seats lost |
| probe-and-relax (conservative first, relax after observation) | 3 admitted, 0 violations | 6 admitted, 0 violations — safe and full-seat |

Reading: the optimistic prior is unsafe under heavy arrivals; a static conservative prior is safe but halves the seats; "probe first, relax on evidence" wins both sides. Together the two panels support the design principle of Section 5: priors are evidence-driven and must be cost-aware.

## 7.3c Empirical Validation of the Censoring-Corrected Estimator (b2, Figure 12)

Five pegged tenants are measured at quotas 20/40/60%: the estimate $\hat d = \min(1, u/(1-t))$ uses only observable counters (quota + throttled time fraction t); the ground truth is then measured by lifting one tenant's quota at a time (the rest stay capped) so five-way contention cannot pollute the reference:

| quota | mean t | estimate | truth | error |
|---|---|---|---|---|
| 0.20 | 0.80 | 0.998 | 0.989 | +0.9% |
| 0.40 | 0.58 | 0.955 | 0.988 | −3.3% |
| 0.60 | 0.32 | 0.886 | 0.971 | −8.6% |

**Reading (empirical boundaries).** This table validates the estimator on the **saturated-demand** family: host-side counters (quota + throttle counters) recover the censored demand within 9%. This is **not a general guarantee**: the same counters over-estimate bursty demand (counterexample now in unit tests: true 0.3, quota 0.2 → estimate 1.0) and may under-estimate intermittent saturation; the "conservative direction" holds only on the saturated family. We therefore position it as an **empirical censoring-corrected estimator** (assumptions and boundaries in Section 3.3), with a cross-pattern characterization (5 patterns × 3 quotas × 3 periods × multi-vCPU) as a v2 study; it is integrated into the design (Section 5.3).

## 7.4 Shaping Comparison: Safe Packing Limit and Cost (Figure 6)

Under the same knee protocol and service-SLO criterion:

| Shaping | Safe limit (measured) | 4th tenant violates? | Customer rate (of full speed) |
|---|---|---|---|
| No controls | 3 | yes (22.7/20.7 ms) | 100% |
| Quota 0.75 core | 3 | yes (14.0/11.2 ms) | ~72–78% |
| Quota 0.50 core | 3 | yes (15.2/11.3 ms) | ~48–53% |
| Core isolation | ≥5 (tested to 5) | no violations 1–5 (P99 2.9–3.2 ms) | shares remaining cores (~44% at five) |

**Reading.** Only isolation raises the safe limit (to ≥5); quotas change tenant speed, not the limit (Section 4.4.1). The cost relocation is visible: isolation moves the cost from "service SLO" to "economy-tier customers", while quotas satisfy neither side. The remaining defenses — memory double gate and IO caps — do not raise the CPU knee but stop their own storms from dragging the service under (they are necessary parts of the synthesis configuration).

## 7.4b Online Admission Showdown (Figure 20)

**Protocol.** On the 8-core tenant pool, seven policies (`worstcase` quota-conservative / `fixed` 2x /
`util80` busy-80% / `quantile` history-quantile / `audible`-style MC convolution / `ours` phase-profile /
`ours_p` phase-profile + pause guardrail) x two phases (random / aligned), on an **identical arrival stream**
(+2 tenants per step, 25 s settle, 15 s dual-service probes) and **identical available evidence**; tenant duty
20%/60 s. The quality bar is the primary bar of Section 8.4 (service P99 <= 10 ms AND customer P5 ≥ 70%);
the capacity oracle is the measured bar-qualified capacity (random 28 / aligned 8; fine-scan brackets [28,32)/[8,10)). **Metrics:** seats at
stop, first violating step, **safe VM-hours** (integral of n before the first violation), and the gap to the
oracle.

**v1 preliminary (10 rounds, legacy sampling; labeled).** `fixed` stops at 16, `quantile` at 8, `util80` never
stops (runs to the 40 experiment cap; at the 50% floor bar slow customers appear from n = 30), `audible` opens
to 40 in the aligned phase (the independence assumption erases phase correlation — its known failure mode);
the fixed `ours` stops at **8 in the aligned phase** (profile peak counts 0 → 2.0 → 4.0 → 6.0, refusing the
10th tenant at 8.4 > 7.2). First four random-phase rounds used the legacy format (no per-customer rates).

**v2 complete: all 14 rounds (Figure 20).** Identical arrival streams, evidence and primary bar
(service P99 <= 10 ms AND customer P5 ≥ 70%). **Scope:** 14 rounds = 7 policies x 2 phases (one round
per cell; the show4/show5 repeat batches and the show6 arrival-order repeat are separate); "audible-style"
is a simplified Monte-Carlo re-implementation of the independence-convolution core (**not the full
AUDIBLE system**).

| policy | rand stop | sync stop | sync violation evidence |
|---|---|---|---|
| worstcase | 8 OK | 8 OK (both bars: service + customer P5~99% at N=8) | — (vCPU-ceiling only) |
| quantile | 8 OK | 8 OK (both bars: same as above) | — |
| fixed 2x | 16 OK | 16 VIOL (service OK; customer P5=48.6% < 70%) | beyond fine-scan bracket [8,10); 4-round ladder P5=48.6% at N=16 |
| audible-style | 16 OK | 40 (cap) VIOL | independence erases phase; P5=16% from n=18; show5 rerun: 8/8 active customers <70% at 40 |
| ours (PPC) | 16 OK | 8 OK (both bars: customer P5~99%) | stops inside the fine-scan bracket [8,10) |
| ours_p | 20 OK | 8 OK (both bars: same as above) | same |
| util80 | 28 OK (P5=78%) | 40 (cap) VIOL | P5=16% from n=18; show5 rerun: 8/8 active customers <70% at 40 |

**Implementation scope.** The `ours` policy in this table implements the **phase-resolution gate** of Algorithm A (one-second history -> 60 phase buckets, peak counting, fixed 10% margin, plus the `ours_p` customer-P5 pause). The full Algorithm A chain (**censoring-aware demand correction + background-residual Q95 reserve + dual service/customer pause guards**) is implemented as `ours_full` (`tb_admit.py`); its online batch (show7) is running and will be merged as supplementary material — the table's conclusions correspond to the gate, and the full-chain end-to-end ablation follows with show7.

**Observation-axis attribution (measured counterparts of Section 3.6):**

| Policy | Missing capability | Measured failure |
|---|---|---|
| naive / quota-scaling (7.3) | (1) censoring identification | 90/90 release violations; 2–3x underestimate |
| audible-style | (2) phase resolution (iid convolution) | sells 40 in sync (P5 = 16%) |
| util80 | (3) time resolution (single-point busy) | 28 vs 40 stop drift across identical runs; sells 40 in sync |
| worstcase | (1)(2)(3), all-conservative | always 8 (wastes 2–3x in rand) |
| ours / ours_p | none (all three) | the only policies safe on both bars with rand 16-20 and aligned 8 (customer P5 ≈ 99% at N=8) |

**Three conclusions.** (i) the phase-aware controller is the only one combining the aligned-phase 8-seat
bracket with competitive random-phase capacity (16–20; worstcase/quantile stop at 8 in *both* phases, fixed
at 16 in both; the fine scan pins the aligned boundary at [8,10): 10 seats give customer P5=62.2%, first fail); (ii) utilization-based criteria are quantified as
phase-dependent: util80 sells 28 (safe) under random and 40 (customer P5 collapses to 16%) under aligned —
same policy, same hardware, opposite risk; audible-style collapses likewise; (iii) fixed and worstcase/
quantile verify the other two corners. Safe VM-hours and round-level intervals arrive with the show4/show5
repeats (queued at the chain tail).

**Sampling caveat (honest):** v2 sync rounds have a probe-before-rates ordering defect that pushed rate
sampling out of the burst window (audible/util80 happen to have valid violation evidence via phase drift;
fixed etc. lack the p5 column); the corrected seven-round rerun (show5) is queued.

## 7.5 Triple-Storm Synthesis (Figure 10)

**Configuration.** Services + probe pinned to cores 0–1; 16 tenants pinned to 2–3; per tenant `memory.high = 800 MiB`, `memory.swap.max = 0`, `io.max = 200/100` IOPS; admission per censoring-aware rules (this validation focuses on the protection envelope; admission does not intervene). **Storm composition.** CPU mix (8 idle + 6 idle/bursty + 2 pegged), memory ballast, and 4K random-write fio, all simultaneously; service probes at 100 req/s for 60 s each.

| Pass | HTTP P50/P99/P999 | Redis P50/P99/P999 | Timeouts/errors | Host state |
|---|---|---|---|---|
| syn1 | 1.38 / 2.54 / 4.90 | 1.09 / 2.07 / 3.92 | 0 / 0 | avail ≥ 3.0 GB, swap stable |
| syn2 | 1.51 / 2.82 / 5.37 | 1.21 / 7.55 / 27.45 | 0 / 0 | same (pegged tenants survive the whole run) |
| syn3 | — / 3.01 / — | — / 2.70 / — | 0 / 0 | completed cleanly (customer-side 13/16 collected) |
| syn4 | — / 3.46 / — | — / 3.35 / — | 0 / 0 | same (pegged tenants alive throughout) |

**Reading.** All four passes hold "service P99 ≤ 10 ms" (HTTP margin ≈ 3–4×); Redis in syn2 shows a heavier tail (p999 27.5 ms, max 74 ms at single-response level, no timeouts), reported as measured. Compared with the unprotected cases of Section 4 (CPU storm 21–23 ms; disk storm 12 ms; memory storm killing two customer VMs), the suite defuses all three storms at once. The customer-side cost matches design expectations: memory and IO caps throttle over-users first (some tenants briefly unresponsive over SSH) — the normal operating state of the economy tier.

**Collection note.** Customer-side detail under hard throttling collects incompletely (13/16 in syn3); service-side metrics carry the protection conclusion, with customer-side work rates and throttle counters as corroborating evidence.

**v3 rework repeat (Figure 19).** The rework reran the same storm end-to-end (20 s probes, fresh state per round): **25 of 26 rounds pass** — HTTP P99 mean **4.82 ms** (median 4.02, range 2.95–25.26), Redis mean **3.34 ms** (2.53–4.13, always compliant); **one round (r24) violates at 25.3 ms** — in that round 8 tenants returned no rate samples (degraded state). The envelope has held across **29 of 30 passes (4 pilot + 26 rework)**. **Statistical honesty:** the optimistic independent-binomial one-sided 95% bound for 29/30 is ~**14.9%** (the earlier 11.7% for 24/24 was an optimistic pre-rework estimate; rounds share host state and are time-correlated, so the bound is indicative — "near-zero violations" is not a long-term guarantee).

## 7.5b Joint Admission + Shaping Validation (j1, Figure 13)

The protection envelope is fully active (services/probe pinned to cores 0–1; customers to 2–3; per-customer memory double gate at 800 MB with swap.max=0; IO caps), with a background load of four tenants (3 idle + 1 bursty); six candidates arrive one at a time, each capped at 50% on admission. Two admission policies decide within the same envelope:

| policy | committed seats | service violations | customer-side canary (background idle VM) |
|---|---|---|---|
| naive (usage) | 3 | 0 | max wakeup stall 3.8–4.4 s per 5 s window |
| aware (throttle-corrected) | 1 | 0 | 3.8 s (same source) |

**Reading (three honest points).** (i) **Pinning and caps keep the service safe**: zero violations under both policies — in joint operation the admission policy decides *how many seats are committed*, not service safety. (ii) **The dominant customer-side pain comes from the tight memory gate**: the canary's multi-second stalls are nearly identical at 1 and 3 seats, showing that `memory.high = 800 MB` is too tight for a 3 GB guest (cf. the soft-threshold semantics of Section 4.4.4) — the economy tier's experience ceiling is a product parameter (gate sizing), not a policy defect. (iii) **Throttle-corrected estimation carries a phase bias**: with bursty background, instant sampling at decision time underestimates demand (estimates oscillated between 0.01 and 1.90 cores), making the aware policy over-conservative (1 seat vs naive's 3) — precisely the design-to-implementation gap versus the time-aligned aggregate upper quantile of Section 5.3, tracked as an improvement item. **v2 revision (joint-comparison batch running on the second testbed)**: the time-aligned aggregation is now fully implemented (1 s history sampling + phase-profile prediction + quota-cap consumption accounting + closed-loop canary guard); the four-policy fair comparison (naive / AUDIBLE-style / aware / taligned) ×10 rounds with an 800/1920 MB memory-gate A/B runs automatically; results will be merged as supplementary material.

## 7.6 Production Telemetry: Workload Portrait (Figure 27)

Both production hosts are **infrastructure we operate ourselves, offered as free VPS to external users**;
telemetry runs on our own facility, read-only, with anonymized user VMs (no names/IPs/business content).
This section quantifies the portrait from one of them (LEC-HK-1): Xeon Gold 6248 (50 cores, no SMT, single
NUMA), 251.7 GiB RAM + 64 GiB swap, one 1.1 TB SSD (393 GB used), PVE 9.2.21. A one-shot read-only
inventory (procfs + `*.conf` files; no PVE API) gives **285 VMs configured / 276 running**,
**sum vCPU = 417 (8.3x)**, **sum RAM = 500 GB (2.0x)**, **sum disk = 5.38 TB thin-allocated on a 1.1 TB
volume (4.9x, 36% actually used)**; disks are qcow2 thin clones sharing base template images. The 60 s
telemetry window saw 210 running VMs (sum vCPU = 288, 5.8x) — running counts fluctuate 210–276 over the
lifecycle. Usage boundary: no training, no scheduling feedback, no active experiments.

**Unit check.** Sum of guest `cpu` x vCPUs = 15.3 cores ~ host counter busy = 14.8 cores; the
single-core reading gives only 10.2 cores — the guest `cpu` field is confirmed as **fraction of allocated
vCPU**, consistent at host level.

**Portrait (Figure 27).** (i) Classes: **idle (<5%) 71.9%, light (5–30%) 27.1%, heavy (>30%) 1.0%** —
matching the "mostly idle, a few heavy" modeling premise. (ii) Oversubscription anchors: **5.76x vCPU
oversubscription** (configured vCPUs / 50 cores), memory-limit oversubscription 1.12x, actual memory ~95 GiB
— the testbed's 5x scale comes from real practice, not inflation. (iii) Burst structure: 4268 active runs
(>=5% consecutive), **median 1 minute** (3550 single-minute runs) — short bursts dominate; value-level
autocorrelation is ~0 across 1–30 min (no minute-scale persistence, no clock period), while the state layer
persists (Markov self-transitions 0.85/0.37/0.26) — real bursts are "runs of varying length with drifting
phase", neither i.i.d. nor clocked. (iv) Saturated instances (>=95% vCPU) occupy 0.046% of VM-samples —
genuinely heavy tenants are rare but present.

**Implications.** (i) A 1% heavy class plus instantaneous overlap is the entire risk source — echoing the
Chapter 4 result that a single pegged neighbor collapses the tail; (ii) real bursts drift rather than tick:
the synthetic "strict 60 s alignment" is a **worst-case upper bound**, so the mixed-phase model's $\varphi$
should be read low on production hosts and safe capacity sits near the random end — consistent with 5.76x
oversubscription running in the field; (iii) the read-only interface lacks throttle counters, so the censoring share is proxied by the
saturated-instance fraction as a lower bound; (iv) **inter-tenant correlation (minute granularity)**:
204 active VMs, 20706 pairs, mean Pearson r = 0.12, median 0.07, P95 0.45, 15.7% of pairs above 0.3 —
*weakly positive, not independent*: phase structure is not an artifact of synthetic loads, while the
random-end assumption of the capacity model is only an approximation; sub-minute synchrony stays
invisible at this granularity. (v) **Two-window representativeness:** the 3-h dense excerpt is a
night-time quiet segment (busy 30.1%), while the 39-h light window covers day and night (busy 37.7%,
peak 66.1%) - the "mostly idle" portrait is a per-VM statement; host-level load follows a day/night
rhythm, and capacity-model anchors taken from the quiet segment are labeled as such (the controlled
experiments here align with that segment; day/night peak regimes are future work).

**Boundaries and the two-state anchor (Figure 31).** The dense window is only 170 minutes and is a
**night-time quiet segment** (host busy 30.1%, peak 47.2%); the light stream has now accumulated **39
hours of day/night coverage** (274 points at 5-minute intervals; ~40% of samples missing to relay
jitter): host busy mean **37.7%**, P95 55.5%, peak **66.1%**; guests consume 14.8%
of host CPU on average; memory available never drops below **87.8 GB**; CPU PSI avg300 mean 5.3, peak
14.0; no reboot in the window. The two-state anchor holds: the quiet/night dense segment (to which the
controlled testbed experiments align) and the full day/night light segment together bracket the real
load range. 1-minute granularity cannot resolve sub-minute synchrony.

## 7.7 Gap List (Pre-Submission Plan)

1. An AUDIBLE-adapted baseline: preliminary evaluation complete (Section 7.3b, Figure 11); a full implementation remains.
2. Cold start / short history: preliminary evaluation complete (Section 7.3b); more arrival populations and replicates remain.
3. Key conclusions now carry mass repeats: v2 Phase 1 complete (knee 50 rounds, censoring 90 cycles, triple storm 24 rounds — Sections 4.1b/4.3b/6.5, Figures 17–19); the rework batch (v3knee 50 + v3cen 30 + v3syn 26) and Phase 2 (53 rounds, incl. admission showdown and memory-gate A/B) are queued; round-level bootstrap intervals refresh after they land.
4. Ablations: preliminary evaluation complete (naive / AUDIBLE-style / aware / aware+cal in Section 7.3b); the isolation ablation is in Section 4.4.3.
5. Figure scripts and data cross-check for Figures 2–19 (skeleton list; pilot 2–13, physical host 14–16, v2 repeats 17–19 all reproduce with one command).
