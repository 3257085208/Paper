# 8 Physical-Host Validation and the Density Law

> This chapter answers the "single nested testbed, too small to generalize" concern: on a **bare-metal host**
> (2x Xeon Platinum 8259CL, 48 cores / 96 threads, 991 GiB, PVE 9.2.20, non-nested) we replicate the core
> conclusions of Chapters 4–6 with a **64-VM customer fleet**, and upgrade "safe sell capacity" from a
> qualitative statement into **quantified curves and a law** (§8.5: N* ≈ C/(ρκ)).

---

## 8.1 Testbed

Host: 2x Xeon Platinum 8259CL (48 physical cores / 96 threads, dual NUMA), 8x128 GB DCPMM (Memory Mode,
991 GiB usable, 520+520 GiB per node), 3x NVMe + 2x SATA SSD, PVE 9.2.20 (kernel 7.0.14-19-pve,
`systemd-detect-virt=none`), internal `vmbr0` 10.10.0.0/24 with NAT.

Fleet: one HTTP (nginx), one Redis, one probe (open loop, 100 req/s), **64 customer VMs** (1 vCPU / 1 GiB,
Debian 12 cloud template). Tenant load uses the Chapter 4 duty-cycle burner (`burner.py`); per-tenant rate
logs provide **per-customer experience metrics**. Services and probe are core-isolated (cores 2/3/4); the
tenant pool is pinned with `taskset -apc` (2–32 cores configurable). **The isolation claim is
topology-verified**: the SMT siblings of the service cores (50/51/52) do not intersect the sibling set of
the tenant pool 8–23 (56–71), and all live on NUMA node 0 — physical-core isolation, not merely disjoint
logical numbering.

> Incident (recorded honestly): during setup the host suffered one kernel panic (`Attempted to kill init!
> exitcode=0x9`, log stops near a batch VM start); at the time its memory subsystem was degraded (only 7 of
> 8 DCPMM online). After a cold boot fixed memory (8/8 online, 991 GiB), batched starts of 48 VMs plus
> hours of saturated experiments ran clean. Not part of the method, but evidence that production hardware
> also runs sick — monitoring and conservative design matter more, not less.

## 8.2 Multi-Scale Knee Replication (Figure 14)

The Section 4.1 knee experiment scaled to five pool sizes (2/4/8/16/32 physical cores), with services
either **isolated** (dedicated cores) or **shared** (inside the pool); pegged neighbors (1 core each) are
added step by step; service P99 is recorded (Figure 14; x-axis = pegged tenants / pool cores).

**Results.**

- **Isolated**: P99 stays at 0.68–0.78 ms across all five scales and oversubscription ratios 0–2.5x — even
  48 pegged neighbors on a 32-core pool. "Isolation protects the tail" survives the jump from a 4-vCPU
  nested bed to a 96-thread physical host.
- **Shared**: every scale cliffs exactly at the **pool saturation point (ratio = 1.0)** — 2-core L2→L4
  (4.1→10.2 ms), 4-core L3→L4 (1.5→10.2 ms), 16-core L13→L16 (1.0→12.0 ms). The **4-round fine scan** of
  the 16-core pool: L15 = 2.13 ms [2.00–2.29] (still flat), L16 = 10.95 ms [9.97–12.02], **4/4 rounds jump
  at L15→L16**; beyond saturation (L17–L18) P99 plateaus at 9.8–10.6 ms. Same shape as BeroHost's 3→4.

**Reading.** Scale changes the ticks, not the shape: the shared-pool knee always sits where peak demand
meets pool capacity; isolation flattens the whole curve. This answers the external-validity concern
directly: on a 96-thread machine the phenomenon, its magnitude (0.7 ms → 10–12 ms) and the isolation result
all replicate item by item.

## 8.3 Phase Structure: Synchronized vs Randomized (Figure 15)

The Section 4.2 synchronized-burst experiment scaled to 64 tenants (20% duty / 60 s), half randomized,
half aligned, all inside one 16-core pool (no isolation).

**Results.**

| Metric | Random phase | Aligned phase |
|---|---|---|
| Service P99 | 8.8 ms | 3.6 ms (mean) |
| Hot-spot timing | scattered (gaps 20–40 s) | strict 60 s period |
| Customer rate | slow erosion | cliff during bursts (quantified in §8.4) |

**Replication (Figure 15 right):** three rounds each (r1–r3). All five hot-cluster gaps of the aligned
rounds hit exactly 60 s; random gaps scatter over 20–40 s with no fixed beat. The two "damage signatures"
(periodic spikes vs baseline lift) reproduce across repeats.

**Reading.** The two phases hurt differently: synchronization is a *predictable periodic spike* (the whole
group contending inside each 60 s window); randomization *lifts the baseline*. This refines Section 4.2
(spikes are the signature of synchronization, not a monotone "sync is worse" ordering) and motivates
time-aligned admission: periodic structure can be measured, exploited (avoid peaks) or treated
(anti-phase arrangement), while random structure can only be absorbed by headroom.

## 8.4 Safe Sell Capacity (Figure 16, core result)

**Safety definition (unified, pre-declared, applies to all chapters).** Every capacity statement is a triple of resource, quality constraint and risk budget epsilon. (i) Service side: with window W in [30,120] s, a violation is window P99 > 10 ms **or** any timeout/error; failures are not excluded, and statements read "violation-window rate <= epsilon" with independent-round counts and Clopper-Pearson bounds (Section 5.3.2). (ii) Customer side: the primary bar is customer work-rate P5 >= 70% of the solo baseline, a lower-tail quantile, not a "worst decile". (iii) Capacity oracle: the largest step satisfying both at a given epsilon. Knee (mean cliff), zero-violation capacity (epsilon = 0) and risk-budgeted capacity (epsilon > 0) are three distinct notions, and every mention says which. Timeouts and errors always count as violations, never excluded to polish the successful-request P99.

**Question.** On an 8-core tenant pool with isolated services, under "service P99 ≤ 10 ms AND customer
experience not degraded", how many 1-vCPU VPS can be sold?

**Quality bars (pre-declared, to prevent post-hoc selection).** Primary bar = **service P99 ≤ 10 ms AND
customer workout P5 ≥ 70% of the solo baseline** , i.e., the low tail — the 5th percentile customer keeps
≥70% of solo; note P5 is a lower-tail quantile, not "the worst decile". Sensitivity bars P5 ≥ 90% /
P5 ≥ 50% / median P50 ≥ 90% are reported side by side on the same data. Statistics: quantiles are
estimated after aggregating per customer and per round (no pooling of per-customer-per-time samples as iid);
round-level uncertainty is resampled by round.

**Method.** Step ladder: L8→L64 (random group) / L4→L32 (aligned group); each step collects 60 s: pool
busy (2 s), **per-customer burner rate** (10 s), both service probes. Rates are normalized by the solo
single-core baseline (25.9 M it/s); the random group pools 2 rounds (r1+r2, 13–117 per-customer samples),
the aligned group **2 rounds (r1+r2; the shuffled-order r3 is void due to a level-labeling defect and kept for
the record)**.

**Results (Figure 16; left customer experience, right services).**

- **Services (right)**: P99 0.56–0.78 ms at every step in both groups — under the isolation envelope even
  "8x oversubscription" leaves the services untouched.
- **Customers (left)**: same load (20% per tenant), same pool; **safe capacity moves with the quality bar
  from 3.5x to 4x**:

| Quality bar | Random safe N | Aligned safe N | Ratio |
|---|---|---|---|
| P5 ≥ 90% (strict) | 28 | 8 | 3.5x |
| P5 ≥ 70% (primary) | 28 | 8 | 3.5x |
| P5 ≥ 50% (floor) | 56 | 14 | 4x |
| P50 ≥ 90% (median) | 40 | 10 | 4x |

Random per-step P5 declines gradually from 99.7% at L16 to 42.8% at L64: L24 93.8%, L28 90.6%, L32 69.1%, L40 64.5%, L48 50.6%, L56 50.0%. The aligned group is a cliff: L8 98.8%, L10 62.2%, L12 53.5%, L14 54.2%, L16 48.6%. Four-round pools agree with Figure 16, and the fine-scan boundary scans completed, giving sync [8,10) and rand [28,32).

Round-level ranges of the per-round P5: sync N=8 98.6–101.8% (4 rounds), N=10 61.0–70.8% (3), N=16 47.0–49.6% (4); rand N=28 88.7–99.4% (2), N=32 62.2–90.8% (4, wide spread; the boundary statement takes the conservative round, 28). Formal intervals use a customer-level bootstrap on the pooled samples (B=10,000, 95% CI): sync N=8 [98.6, 99.0], N=10 [61.0, 68.6], N=16 [47.1, 48.9]; rand N=28 [82.5, 99.3], N=32 [62.2, 75.5]; mix50 N=13 [90.5, 99.6], mix75 N=10 [98.7, 100.5]. Artifacts: `tools/bootstrap_ci.py` and `BOOTSTRAP_CI.md`.

**Convention robustness.** The customer bar "P5 >= 70%" depends on the per-customer aggregation. Recomputing with the full 18-sample-per-VM series under four conventions — per-customer max, median, time-P5 or min, then cross-customer P5 — structurally identical to the paper's per-round pooling: the sync boundary is identical under all four conventions at 8 seats; rand is 28/28/26/26; mix25 24/20/20/20; mix50 and mix75 unchanged at 13 and 10. The aligned-end conclusion is convention-invariant (all conventions give 98.8% at N=8), while the random end tightens by one fine-scan step under the strictest time-domain convention. Artifacts: `tools/p5_convention_check.py` and `P5_CONVENTION_CHECK.md`. **Capacity-risk curves (Figure 30):** with the round-level violation frequency as the risk measure (a round counts when its customer P5 < 70%), safe capacity rises monotonically with the budget — at eps=0: rand 28 / sync 8 / mix25 20 / mix50 13 / mix75 10; at eps=0.5: rand 40; at eps=1: rand 64 / sync 32. All safe policy stops sit on the eps=0 edge (ours/ours_p: sync 8, rand 16-20), while the util80/audible sync stop (40) exceeds the curve's ceiling at any budget (only 32 even at eps=1) — no risk budget legitimizes it. **Scope note:** this curve is the workload-side empirical capacity-risk frontier; complete per-policy frontiers at matched risk budgets (each policy x many N x multiple seeds) are future work; the eps=1 endpoint is merely the curve's terminal point and carries no safe-admission meaning.)

**Four conclusions.**

1. **Average utilization alone catastrophically oversells**: the aligned group at 32 tenants is only ~35%
   busy on average ("the pool looks empty") while customers already collapse to 25% during every burst.
2. **At equal average load, capacity is set by phase structure**: 28 vs 8 at the primary bar (3.5x); the ratio
   moves between 3.5x and 4x with the quality bar. Capacity *must* be reported together with its quality bar — "not degraded" must be measured at the tail (P5), which is exactly why this
   section re-calibrates.
3. **The two failure modes have different shapes**: random is gradual (warning available to a controller);
   aligned is a cliff (99%→49%) with no warning window — explaining why average/median monitors fail
   against synchronized workloads.
4. **Isolation decouples the two damage channels**: services stay flat (0.7 ms); the entire cost lands
   explicitly on customer rates — consistent with the Chapter 5 "cost pricing" framework; the economy tier
   literally sells this degradation budget.

## 8.5 A Safe-Capacity Approximation: Mixed-Phase Validation (Figure 21)

**The model (an approximation under explicit assumptions, not a universal law).** Assumptions: (A1) tenant
phases are stable within the decision span; (A2) the aligned group's bursts coincide, and overlap with
random tenants follows duty. Under these, the aggregate concurrency peak is ≈ aligned group $\varphi N$ +
random group $\rho(1-\varphi)N$, giving the median-bar capacity

$$N^*_{\text{mid}} \;\approx\; \frac{C}{\varphi + (1-\varphi)\,\rho},$$

i.e., the concentration form $N^*_{\text{mid}} = C/(\rho\kappa)$. **The model describes the mean/median bar;
at the pure-random end it is markedly optimistic for the P5 tail bar** (model 40 vs measured 28). The
random-end tail is naturally governed by the upper quantile of overlap counts: require
$Q_p(\varphi N + \mathrm{Bin}((1-\varphi)N, \rho)) \le C/\theta$; numerically this sits below the median
bar. In practice the safe value is taken directly from the **measured** bar-qualified capacity (§8.4), and
the model is used only for cross-configuration extrapolation and as the admission prior.

**Validation (Figure 21; 8-core pool, $\rho$ = 0.20, capmix pools of 3 rounds each):**

| Configuration | Model prediction N*_mid | Measured (primary P5 ≥ 70% bar) | Deviation |
|---|---|---|---|
| $\varphi=0.25$ | 20.0 | 24 passes (73%), 28 fails (54%) | conservative (half-step) |
| $\varphi=0.50$ | 13.3 | 13 passes (90%), 16 fails (49%) | break point hit |
| $\varphi=0.75$ | 10.0 | 10 passes (99%), 13 fails (52%) | break point hit |

Structural phases ($\varphi \ge 0.5$) hit the break point; the $\varphi=0.25$ prediction lands inside the
passing region (conservative), the pure-random end is optimistic — the error directions match the
tail-vs-median bar expectation.

**Boundaries (honest).** (i) One round per configuration: per-level P5 carries non-monotone sampling noise
, e.g., $\varphi=0.25$ L24 > L20; round repeats (multiple rounds/seeds) and a prediction-error distribution
are queued, after which this section reports round-level intervals and an error band. (ii) The C5 anti-phase
arrangement experiment (same tenants, two groups offset by 30 s, capacity x2) upgrades "phase is
arrangeable" from observation to intervention. (iii) The positioning is a **capacity approximation with
explicit assumptions** — used for extrapolation and admission priors under structural phases, with safe
values taken from measured bars; no universal law is claimed.

## 8.6 Phase-Profile Convolution and the Marginal Illusion (Figure 28)

**Proposition (marginal illusion).** The two experiments of Section 8.4 are a *constructive proof*: two
fleets with **identical per-tenant demand marginals** (same burner, same 20%/60 s duty and window shape)
differ in safe capacity by 3.5x at the primary bar (28 vs 8; 40 vs 10 at the median bar). Hence **any capacity
method that consumes only per-tenant marginals (plus an independence assumption) cannot distinguish the two
fleets** — for AUDIBLE-style independent convolution of marginals this is a provable blind spot: the input
is non-identifiable on exactly the axis that matters. This is the capacity-side analogue of the Section
3.3.1 estimation non-identifiability.

**Method (PPC).** Inputs are per-tenant phase profiles at one-second or one-minute resolution. PPC has three modes, each tied to a concrete artifact. The first is parametric simulation (`ppc_sim.py`): synthetic (phi, duty) configurations in which the joint structure holds by construction, used for mixed-phase validation and extrapolation. The second is the empirical joint block bootstrap (`ppc_bootstrap.py`) on real traces with a strict three-way split: the first third trains, the middle third selects the block length by KS distance (B=1), and the last third is used for scoring only. Predictive blocks are drawn from the training third alone, never from validation or test, so this is not a self-resampling of the test segment. Blocks are resampled jointly across tenants to preserve co-occurrence, with an iid-shuffle control that keeps marginals and destroys the joint. Forward prediction scored against the test third: joint predicted peaks P50/P95/max = 14/14/14 with P(peak>8)=99%, iid predicted 12/13/16 with P=100%, and the observed test peak is 12 with 8% of seconds above the pool. On this production schedule both predictors get the risk direction right, and the minute-level joint-vs-iid gap is small, consistent with the fleet's drifting-phase profile; the extreme-phase evidence lives in the synthetic experiments. **Scope:** inputs are one-minute production duties plus an in-period activity model and contain no sub-minute phase structure; this supports a minute-granularity replay model, not measured sub-minute structure. Real-trace measurements over the 64-VM x 30-min replay schedules: joint peak 14 cores (P50=P95=max=14) versus iid peaks 12-15. On this low-correlation drifting fleet the two differ little, and the iid risk grows with phase alignment (extremes in C5 and the synchronized sells). Block-length selection chose B=1 with KS~0.16; the spread across B in {1,2,5,10,15} is 0.16-0.21, weakly resolvable and reported honestly. The online replay (replay1) drove the 64-tenant schedule for 30 minutes on the 8-core pool: mean pool busy 42.0% (3.4 cores), peak saturation 100% (>=8 cores concurrent), service P99 0.706-0.729 ms across five probes with one 1.599 ms tail. The predicted over-pool risk materializes at peak while the isolation envelope keeps the service flat. The multi-window recheck sliced the same telemetry into five non-overlapping 30-minute windows, each with an independent forward prediction: direction hit 5/5 (predicted P(peak>8)=98-100% versus observed over-pool 3.5-8.3%), peak magnitudes of the same order (predicted P50 11-19 versus observed 12-16; per-window offsets +5/±1/-2/-1/0, variance reported honestly). **Scope:** the second-level series is reconstructed from minute-level duties plus a within-period phase model; this validates model-replay consistency, not independently measured second-level production truth. Both methods predict over-pool on this deliberately low-correlation fleet, so the discrimination evidence lives in the synthetic configurations (iid blind versus PPC separating five structures) and the online showdown (util80/audible collapsing in sync); independent second-level truth, false-positive/negative rates and multi-threshold behavior are future work. The third mode is the online actuator: a Taligned-style peak envelope (60 one-second phase buckets plus a class prior), a low-cost online approximation of PPC rather than a resampler; its showdown behavior (Section 7.4b) is the evidence for that approximation. All three share one principle — accounting on the joint phase structure — at different resolutions and for different purposes, and the paper labels them separately.

**Results (Figure 28).** With identical parameters: iid convolution predicts **the same 24 for all five
structures** (total blindness); PPC predicts **24 / 16 / 13 / 12 / 10** for rand / mix25 / mix50 / mix75 /
sync, with 4/5 falling inside the measured *coarse* brackets. **Caveat:** falling inside a bracket is not
hitting the exact oracle — e.g. the sync prediction of 10 now sits exactly at the fine-scan first-fail step (boundary [8,10): 8 seats
P5=98.8%, 10 seats P5=62.2%) — the online peak gate, not the offline prediction, is what stops at 8;
rand 24 is conservative by 4 after the fine scan pinned the bracket at [28,32). The random-end tail optimism matches
Section 8.5 and is corrected by the measured bar.

**Prediction-quality metrics (stricter than "inside the bracket").** Per configuration: **over-admission**
(prediction >= first-fail; a safety veto, must be 0), **unverified stretch** (prediction - last-pass; >0 means
the prediction reaches into unsurveyed steps), **fail margin** (first-fail - prediction), **conservatism**
(last-pass - prediction). Multi-round values: rand 24 vs [28,32) — over 0, conservative 4; mix25 16 vs [24,28) — over 0, conservative
8; mix50 13 vs [13,16) — over 0, margin 3; mix75 12 vs [10,13) — over 0, stretch +2, margin 1; sync 10 vs
[8,10) — **over 1 (first-fail), vetoed online**. **4/5 zero over-admission**; the sync case is exactly why the
online peak gate — not the offline predictor — carries the safety argument.

**Boundaries.** PPC needs phase history (cold start degrades to priors/observation windows); the random
end still needs the measured bar; validation is offline forward prediction (train-only resampling scored on the held-out third) plus the online showdown (the `ours`
policy *is* the PPC actuator and stops on the synchronized oracle).

## 8.7 Consistency with BeroHost

| Result | BeroHost (4-vCPU nested) | Physical host (96 threads) |
|---|---|---|
| Knee at shared-pool saturation | 3→4 tenants (2-core pool) | all pools at saturation (fine scan L15→L16) |
| Isolation protects the tail | P99 ≈ 2.9–3.2 ms | P99 0.68–0.78 ms (0–2.5x oversubscription) |
| Sync → periodic spikes | 60 s period (6 tenants) | 60 s period (64 tenants, 3 rounds, gaps exactly 60 s) |
| Soft levers fail / hard caps work | verified | (runs on the physical host planned) |
| Safe sell capacity | qualitative (3 seats in budget) | quantified: 3.5x primary bar (28 vs 8), 3.5x–4x across bars |
| Density law predicts N*(φ) | — (nested bed) | three points hit (Figure 21) |

## 8.8 Chapter Data and Artifacts

- Data: `research_data/phys8269_pilot/` (multi-scale sweeps, 4-round fine scan, 3-round sync raw, sell
  ladders, mixed-phase ladders, analysis docs).
- Figures: `figs/fig14_phys_knee.png`, `fig15_phys_sync.png` (with 3-round gap panel),
  `fig16_phys_sell.png`, `fig21_density_law.png` (one-click: `figs/make_phys_figs.py`, `figs/make_law_figs.py`).
- Tools: `tools/tb_sweep.py` (knee), `tools/tb_sync.py` (phase), `tools/tb_sell.py` (sell ladder),
  `tools/tb_capmix.py` (mixed-phase), `tools/tb_c5.py` (anti-phase arrangement); all host-side.
