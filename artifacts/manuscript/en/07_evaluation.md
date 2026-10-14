# 7 Evaluation

> Three evaluation groups: (A) admission-policy comparison; (B) shaping and protection-envelope comparison; (C) combined-stress synthesis validation, followed by the production-telemetry usage and an explicit gap list. Common SLO: service P99 ≤ 10 ms.

## 7.1 Setup Recap

Testbed and metrics: Sections 3–4 and 7. Admission comparisons use a closed loop: five candidate tenants arrive one at a time, a policy decides allow/defer from evidence visible at that moment, and allowed candidates are actually started and measured. Shaping comparisons use the neighbor sweep (0–5 tenants) plus the full combined-stress. Every key conclusion replicates at least twice (knee: 5 rounds; censoring: 7 cycles; synthesis: 4 passes).

## 7.2 Admission-Policy Comparison (companion to Figure 4)

Four policies run over the same arrival sequence with the same evidence surface (two rounds in different orders):

**Table 9.** Two-round admission pilot: seats admitted and violation windows per policy

| Policy | Evidence | Admitted (round A / B) | Violation windows | Worst P99 (HTTP/Redis) |
|---|---|---|---|---|
| Fixed ratio (2.0×) | Configuration only | 5 / 5 | 4 / 4 | 23.7 / 25.8 |
| Busy threshold (80%) | Host busy fraction | 3 / 3 | 0 / 0 | 7.8 / 5.7 |
| Historical demand budget | Per-VM usage quantile + budget | 3 / 3 | 0 / 0 | 6.1 / 4.8 |
| Calibrated + tail pause (candidate) | Demand budget + single-window P999 pause | 3 / 2 | 0 / 0 | 4.3 / 3.3 |

**Reading.** The fixed-ratio policy ignores all state and walks straight past the knee (Section 4), producing four violation windows — the cleanest counterexample. The three state-aware policies all stop at the knee (3 tenants) with zero violations, showing the knee is reachable from evidence. The candidate is more conservative but exposes an implementation flaw: single-window P999 (n ≈ 2 samples) is noisy, and round B was falsely paused by one 16.3 ms spike, giving up one safe tenant. **This is direct evidence that pause mechanisms need smoothing/hysteresis/longer windows** (already on the improvement list). Fairness note: every policy used only decision-time-visible information; allowed/rejected candidates were actually started or withheld (no post-hoc cherry-picking).

## 7.3 Censoring-Corrected Decisions (Direct Comparison of the Core Claim)

The scenario of Section 4.3 becomes a decision comparison (7 cycles): the same state (5 tenants capped at 30%, true demand 5.0 cores) is handed to two estimators:

**Table 10.** Censoring-corrected decisions: evidence, action, outcome

| Decision | Evidence used | Action | Outcome |
|---|---|---|---|
| Naive (trust usage) | 1.50 cores used, "2.5 cores spare" | Release the caps (believed to be an optimization) | P99 16.7–25.0 ms, 7/7 violating |
| Censoring-aware | Throttle evidence → ≥ 5.00 cores | Refuse the release; report "no headroom, capacity action required" | No new load introduced; quota state holds (P99 9–14 ms, near the SLO line) |

**Reading.** Both decisions consume the same data and differ only in estimation: naive takes censored usage as demand and hallucinates half the host as empty; aware pins the demand lower bound above the quota using throttle evidence. The former action pushes the host into instantaneous saturation (tenants at 27–32 M it/s, host at 100%); the latter avoids the self-inflicted wound and emits the correct capacity signal. We keep the detail that the quota state itself sits near the SLO line: **this host is already at the overload boundary, and the upper action (migrate/upgrade) is out of scope here.**

## 7.3.1 Method Ablation and Cold Start (Preliminary, Figure 11)

**Ablation (censoring scenario).** Six candidates arrive one at a time, each shaped with a 50% cap on admission; four estimators/decisions run the same sequence:

**Table 11.** Cold-start pilot: seats admitted out of 6 candidates

| Policy | Admitted (of 6) | Violation windows | Notes |
|---|---|---|---|
| naive (usage) | 6 | 3 | P99 17.8/15.6/20.7 ms from the 4th tenant |
| AUDIBLE-style (MC convolution, uncorrected) | 6 | 4 | likewise sees only the 50%-censored usage; 10.5 ms already at tenant 3 |
| aware (censoring-fixed) | 3 | 0 | stops exactly at the knee (9.8 ms brushes the line) |
| aware + calibration + tail pause | 1 | 0 | a single window with P999 = 12.2 ms falsely paused it with no recovery — another instance of "pausing needs smoothing/hysteresis" |

**Cold start (no history).** Two arrival populations x three priors:

**Table 12.** Cold-start estimator: all-heavy vs all-light arrivals

| Prior | All-heavy arrivals | All-light arrivals |
|---|---|---|
| optimistic (0.2 core) | 6 admitted, 4 violation windows (11.7–17.2 ms) | 6 admitted, 0 violations (but a wrong bet breaks the SLO) |
| conservative (charge configured 1.0 core) | 3 admitted, 1 violation window (at the line) | only 3 admitted — 3 seats lost |
| probe-and-relax (conservative first, relax after observation) | 3 admitted, 0 violations | 6 admitted, 0 violations — safe and full-seat |

Reading: the optimistic prior is unsafe under heavy arrivals; a static conservative prior is safe but halves the seats; "probe first, relax on evidence" wins both sides. Together the two panels support the design principle of Section 5: priors are evidence-driven and must be cost-aware.

## 7.3.2 Empirical Validation of the Censoring-Corrected Estimator (b2, Figure 12)

Five pegged tenants are measured at quotas 20/40/60%: the estimate $\hat d = \min(1, u/(1-t))$ uses only observable counters (quota + throttled time fraction t); the ground truth is then measured by lifting one tenant's quota at a time (the rest stay capped) so five-way contention cannot pollute the reference:

**Table 13.** Estimator validation (b2): quota, throttled fraction, estimate vs truth, error

| quota | mean t | estimate | truth | error |
|---|---|---|---|---|
| 0.20 | 0.80 | 0.998 | 0.989 | +0.9% |
| 0.40 | 0.58 | 0.955 | 0.988 | −3.3% |
| 0.60 | 0.32 | 0.886 | 0.971 | −8.6% |

**Reading (empirical boundaries).** This table validates the estimator on the **saturated-demand** family: host-side counters (quota + throttle counters) recover the censored demand within 9%. This is **not a general guarantee**: the same counters over-estimate bursty demand (counterexample in the unit tests: true 0.3, quota 0.2 → estimate 1.0) and may under-estimate intermittent saturation; the "conservative direction" holds only on the saturated family. We therefore position it as an **empirical censoring-corrected estimator** (assumptions and boundaries in Section 3.3), with a cross-pattern characterization (5 patterns × 3 quotas × 3 periods × multi-vCPU) as a v2 study; it is integrated into the design (Section 5.3).

## 7.4 Shaping Comparison: Safe Packing Limit and Cost (Figure 6)

Under the same knee protocol and service-SLO criterion:

**Table 14.** Shaping comparison: measured safe limit and customer cost per configuration

| Shaping | Safe limit (measured) | 4th tenant violates? | Customer rate (of full speed) |
|---|---|---|---|
| No controls | 3 | yes (22.7/20.7 ms) | 100% |
| Quota 0.75 core | 3 | yes (14.0/11.2 ms) | ~72–78% |
| Quota 0.50 core | 3 | yes (15.2/11.3 ms) | ~48–53% |
| Core isolation | ≥5 (tested to 5) | no violations 1–5 (P99 2.9–3.2 ms) | shares remaining cores (~44% at five) |

**Reading.** Only isolation raises the safe limit (to ≥5); quotas change tenant speed, not the limit (Section 4.4.1). The cost relocation is visible: isolation moves the cost from "service SLO" to "economy-tier customers", while quotas satisfy neither side. The remaining defenses — memory double gate and IO caps — do not raise the CPU knee but stop their own storms from dragging the service under (they are necessary parts of the synthesis configuration).

## 7.4.1 Online Admission Comparison (Figure 20)

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
AUDIBLE system**); its synchronized failure therefore indicts the independence assumption of that core,
not the complete original method - a faithful re-implementation against the full system is future work.

**Table 15.** Online admission comparison: stops per policy and phase, with violation evidence

| policy | rand stop | sync stop | sync violation evidence |
|---|---|---|---|
| worstcase | 8 OK | 8 OK (both bars: service + customer P5~99% at N=8) | — (vCPU-ceiling only) |
| quantile | 8 OK | 8 OK (both bars: same as above) | — |
| fixed 2x | 16 OK | 16 VIOL (service OK; customer P5=48.6% < 70%) | beyond fine-scan bracket [8,10); 4-round ladder P5=48.6% at N=16 |
| audible-style | 16 OK | 40 (cap) VIOL | independence erases phase; P5=16% from n=18; show5 rerun: 8/8 active customers <70% at 40 |
| ours (PPC) | 16 OK | 8 OK (both bars: customer P5~99%) | stops inside the fine-scan bracket [8,10) |
| ours_p | 20 OK | 8 OK (both bars: same as above) | same |
| util80 | 28 OK (P5=78%) | 40 (cap) VIOL | P5=16% from n=18; show5 rerun: 8/8 active customers <70% at 40 |

**Implementation scope.** The `ours` policy in this table implements the **phase-resolution gate** of Algorithm A (one-second history -> 60 phase buckets, peak counting, fixed 10% margin, plus the `ours_p` customer-P5 pause). The full Algorithm A chain (**censoring-aware demand correction + background-residual Q95 reserve + dual service/customer pause guards**) is implemented as `ours_full` (`tb_admit.py`); the table's conclusions correspond to the gate; the full-chain end-to-end run and the component ablations are reported in Section 7.4.2.

**Observation-axis attribution (measured counterparts of Section 3.6):**

**Table 16.** Observation-axis attribution: missing capability vs measured failure per policy

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
quantile verify the other two corners. Safe VM-hours and round-level intervals from the show4/show5
repeats are reported above where available.

**Sampling caveat:** the earlier sync rounds have a probe-before-rates ordering defect that pushed rate
sampling out of the burst window (audible/util80 happen to have valid violation evidence via phase drift;
fixed etc. lack the p5 column); the corrected seven-round rerun (show5) was completed and the sync customer columns are reported via the four-round ladder.

## 7.4.2 Repeat, Ablation, and Sensitivity Checks (show6-show12)

**Arrival-order repeat (show6 seed 42 + show12 seeds 101/202; 24 runs).** show6 re-ran all seven policies under a second order and reproduced the aligned-phase stop column exactly (audible-style 32, first violation 34; fixed 16; ours 8; ours_p 8; quantile 8; util80 32, first violation 34; worstcase 8), with random-phase stops in a narrow band (ours 18 vs 16; ours_p 20; audible-style 16; util80 32 vs 28; worstcase 8). show12 then re-ran the core three policies under two further orders: **worstcase/ours/ours_p stop at 8 in the aligned phase in every order**, while random-phase stops vary within a band rather than a point - ours 16/18/18/24 and ours_p 20/20/18/14 across the four orders, worstcase exactly 8 in all of them. The band (~+/-25%) is the honest uncertainty of the random-phase operating point under arrival-order variation; the aligned safety stop is order-invariant.

**Full-chain end-to-end (show7).** The complete Algorithm A chain (`ours_full`: censoring correction + background-residual Q95 reserve + dual pause guards) stops at **8 (aligned)** and **16 (random; customer P5 = 100.2% at stop)**, matching the gate-only profiles: on this workload the corrections preserve the operating point and close the chain end-to-end.

**Component ablations (show8, one round per cell).**

**Table 17.** Component ablations: aligned and random stops with evidence per arm

| arm | aligned stop | random stop | evidence |
|---|---|---|---|
| admission under an 80% quota cap | 10 | 18 | mild aligned oversell (10 = first-fail level of the fine scan); random P5 = 79.3% at stop |
| 80% cap without censoring correction | 10 | 14 | capacity bracket binds at n = 16 (peak 5.86 + prior + reserve 1.20 > 7.20); 14-seat stop within the run-to-run phase-placement band |
| phase gate removed (full quota) | 32 -> 34 VIOL | 28 | phase blindness reproduces the aligned failure of audible/util80; random phases forgive it (P5 = 99.0% at stop) |

**Reading.** The phase gate is the aligned-phase safety-critical component (removing it re-creates the 32-seat failure). The two 80%-cap arms differ by four random-phase seats (18 vs 14); **both stops were capacity-bracket deferrals, not guard triggers** (verified in the decision logs: n = 20 and n = 16 respectively), and each round re-randomizes tenant phases independently, so the difference is dominated by run-to-run phase placement (the show12 band is about +/-25%) - the censoring correction's systematic effect is not separable at one round per arm. Capping admitted tenants at 80% mildly oversells the aligned bracket (8 -> 10, the first failing level).

**Dense-sampling confirmation of the boundary (show9, 1 s sampling).** Re-running the sell ladders at one-second resolution confirms the aligned boundary: level 8 holds customer P5 at **97.3%** (per-customer time-P5, median convention) while level 10 collapses to **47.8%**; random 28 holds **75.7%** and 30 falls to **58.3%**, tightening the dense random boundary to [28,30) (the max-rate convention still reads 90.6% at 32 - the convention sensitivity quantified in Section 8.4). Service P99 stays at 0.70-0.75 ms at every level: the binding constraint is the customer rate, not the service tail.

**Guard-metric sensitivity (show10).** Switching the guard metric from max to median keeps the aligned stop at 8 but pulls the random stop down to **4** (pause-monitor triggers on 6/6 checks; P5 = 101.9% at stop): the metric trades random-phase efficiency for conservatism. **Guard semantics (precise):** the customer guard consumes one number per admitted tenant - the tenant's rate series (six samples, ordered before the service probes so work phases are captured) summarized per tenant by max (largest observed work-phase rate), med or min - and the guard value is the cross-customer 5th percentile of that summary (p5_max / p5_med / p5_min); admission pauses when it falls below 70% (or the service/canary thresholds fire). The primary bar uses p5_max because idle samples are not evidence of denial: a tenant's work capability is evidenced by its work-phase rate, and sustained contention lowers the max too - a full-speed burst cannot survive sustained overload. Median/min conflate design-idle with contention-throttling and false-alarm: in the show10 median arm every pause check in the random phase tripped (6/6 windows; idle samples dilute each tenant's median), stopping at 4 seats, while the aligned phase keeps tenants active and still stops at 8. The 70% and service thresholds are the pre-declared constants of Section 8.4; the 0.9 budget and hysteresis are fixed on validation splits.

**Phase-selective admission (show11, `ours_sel`).** The probation mechanism (candidates observed at 5% quota for 40 s before the admission decision) keeps the aligned stop at 8 and raises the random stop to **24 with no violation** - the highest safe random-phase stop in the comparison (`ours_full` 16, `ours_p` 20), showing that phase evidence acquired before the decision converts into measurable random-phase capacity at equal safety. The 24-seat figure comes from the probation variant as a **separate configuration**; integration is design-compatible (probation observations are ordinary usage/throttle samples feeding the same envelope, censoring correction and reserve accounting), but the combined configuration must be re-validated end-to-end, which is future work.

## 7.5 Triple-Storm Synthesis (Figure 10)

**Configuration.** Services + probe pinned to cores 0–1; 16 tenants pinned to 2–3; per tenant `memory.high = 800 MiB`, `memory.swap.max = 0`, `io.max = 200/100` IOPS; admission per censoring-aware rules (this validation focuses on the protection envelope; admission does not intervene). **Storm composition.** CPU mix (8 idle + 6 idle/bursty + 2 pegged), memory ballast, and 4K random-write fio, all simultaneously; service probes at 100 req/s for 60 s each.

**Table 18.** Triple-storm synthesis: service percentiles, errors and host state per pass

| Pass | HTTP P50/P99/P999 | Redis P50/P99/P999 | Timeouts/errors | Host state |
|---|---|---|---|---|
| syn1 | 1.38 / 2.54 / 4.90 | 1.09 / 2.07 / 3.92 | 0 / 0 | avail ≥ 3.0 GB, swap stable |
| syn2 | 1.51 / 2.82 / 5.37 | 1.21 / 7.55 / 27.45 | 0 / 0 | same (pegged tenants survive the whole run) |
| syn3 | — / 3.01 / — | — / 2.70 / — | 0 / 0 | completed cleanly (customer-side 13/16 collected) |
| syn4 | — / 3.46 / — | — / 3.35 / — | 0 / 0 | same (pegged tenants alive throughout) |

**Reading.** All four passes hold "service P99 ≤ 10 ms" (HTTP margin ≈ 3–4×); Redis in syn2 shows a heavier tail (p999 27.5 ms, max 74 ms at single-response level, no timeouts), reported as measured. Compared with the unprotected cases of Section 4 (CPU storm 21–23 ms; disk storm 12 ms; memory storm killing two customer VMs), the suite defuses all three storms at once. The customer-side cost matches design expectations: memory and IO caps throttle over-users first (some tenants briefly unresponsive over SSH) — the normal operating state of the economy tier.

**Collection note.** Customer-side detail under hard throttling collects incompletely (13/16 in syn3); service-side metrics carry the protection conclusion, with customer-side work rates and throttle counters as corroborating evidence.

**Rework repeat (Figure 19).** The rework reran the same storm end-to-end (20 s probes, fresh state per round): **25 of 26 rounds pass** — HTTP P99 mean **4.82 ms** (median 4.02, range 2.95–25.26), Redis mean **3.34 ms** (2.53–4.13, always compliant); **one round (r24) violates at 25.3 ms** — in that round 8 tenants returned no rate samples (degraded state). The envelope has held across **29 of 30 passes (4 pilot + 26 rework)**. **Statistical note:** the optimistic independent-binomial one-sided 95% bound for 29/30 is ~**14.9%** (the earlier 11.7% for 24/24 was an optimistic pre-rework estimate; rounds share host state and are time-correlated, so the bound is indicative — "near-zero violations" is not a long-term guarantee).

## 7.5.1 Joint Admission + Shaping Validation (j1, Figure 13)

The protection envelope is fully active (services/probe pinned to cores 0–1; customers to 2–3; per-customer memory double gate at 800 MB with swap.max=0; IO caps), with a background load of four tenants (3 idle + 1 bursty); six candidates arrive one at a time, each capped at 50% on admission. Two admission policies decide within the same envelope:

**Table 19.** Joint admission + shaping (j1): committed seats and canary behavior

| policy | committed seats | service violations | customer-side canary (background idle VM) |
|---|---|---|---|
| naive (usage) | 3 | 0 | max wakeup stall 3.8–4.4 s per 5 s window |
| aware (throttle-corrected) | 1 | 0 | 3.8 s (same source) |

**Reading.** (i) Pinning and caps keep the service safe: zero violations under both policies — in joint operation the admission policy decides *how many seats are committed*, not service safety. (ii) The dominant customer-side pain comes from the tight memory gate: the canary's multi-second stalls are nearly identical at 1 and 3 seats, showing that `memory.high = 800 MB` is too tight for a 3 GB guest (cf. the soft-threshold semantics of Section 4.4.4); the economy tier's experience ceiling is a product parameter, not a policy defect. (iii) Throttle-corrected estimation carries a phase bias: with bursty background, instant sampling at decision time underestimates demand (estimates oscillated between 0.01 and 1.90 cores), making the aware policy over-conservative (1 seat vs naive's 3) — the design-to-implementation gap versus the time-aligned aggregate upper quantile of Section 5.3, tracked as an improvement item. The revision implements the time-aligned aggregation; it is re-measured as a four-policy comparison on the second testbed, with results merged as supplementary material.

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

**Portrait (Figure 27).** Classes: idle (<5%) 71.9%, light (5–30%) 27.1%, heavy (>30%) 1.0%, matching the "mostly idle, a few heavy" modeling premise. Oversubscription anchors: 5.76x vCPU oversubscription (configured vCPUs over 50 cores), 1.12x memory-limit oversubscription, and about 95 GiB of actual memory in use — the testbed's 5x scale comes from real practice, not inflation. Burst structure: 4268 active runs (>=5% consecutive), median 1 minute, 3550 of them single-minute, short bursts dominate; value-level autocorrelation is ~0 across 1–30 min, so there is no minute-scale persistence and no clock period, while the state layer persists (Markov self-transitions 0.85/0.37/0.26) — real bursts are runs of varying length with drifting phase, neither i.i.d. nor clocked. Saturated instances (>=95% vCPU) occupy 0.046% of VM-samples: genuinely heavy tenants are rare but present.

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
night-time quiet segment (busy 30.1%), while the 42-h light window covers day and night (busy 37.3%,
peak 66.1%) - the "mostly idle" portrait is a per-VM statement; host-level load follows a day/night
rhythm, and capacity-model anchors taken from the quiet segment are labeled as such (the controlled
experiments here align with that segment; day/night peak regimes are future work).

**Second production host (OVH ns503701).** A 6-hour dense window (60 s samples, 344 points) on a second, independent production host: Xeon E5-1630 v4 (4 cores / 8 threads, 62.7 GiB RAM; swap nearly full at inventory time) with **66 running guests, sum vCPU 73 (9.1x)**; host busy mean **30.9%** (peak 44.6%); CPU PSI (some) avg300 7.2 mean / 8.2 peak, PSI (full) 0.0 throughout; guest CPU consumption 1.84 of 8 threads (23%); node memory in use 43.3 of 62.7 GiB (69%); heavy share (>=30% of a vCPU) 2.2%. The portrait reproduces the HK structure at similar density: **9-12x vCPU oversubscription coexisting with a mostly-idle host and zero full-stall pressure**, corroborating that the testbed's scale and the "mostly idle, a few heavy" premise are drawn from field practice.

**Boundaries and the two-state anchor (Figure 31).** The dense window is only 170 minutes and is a
**night-time quiet segment** (host busy 30.1%, peak 47.2%); the light stream has accumulated **42
hours of day/night coverage** (as of 2026-10-14; 305 points at 5-minute intervals, ~39% of samples
missing to relay jitter): host busy mean **37.3%**, P95 55.3%, peak **66.1%**; guests consume 14.8%
of host CPU on average; memory available never drops below **63.7 GB**; CPU PSI avg300 mean 5.2, peak
14.0; no reboot in the window. The two-state anchor holds: the quiet/night dense segment (to which the
controlled testbed experiments align) and the full day/night light segment together bracket the real
load range. 1-minute granularity cannot resolve sub-minute synchrony.
