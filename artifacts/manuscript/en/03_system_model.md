# 3 System Model and Problem Definition

> This chapter formalizes only what the later experiments actually use; no assumptions are introduced without evaluation.

## 3.1 Platform and Tenant Model

Consider a single multi-tenant host (the typical small-provider setup) with $C$ logical CPUs, $M$ bytes of physical memory, and one shared block device (throttling and accounting keyed to the whole-disk device). Two classes of workloads run on it:

- **Sensitive services**: $s$ lightweight service VMs , e.g., status monitoring, gateway, static serving whose end-to-end latency must meet a service-level objective. We instrument one HTTP and one Redis service.
- **Customer VMs (tenants)**: $n$ oversubscribed customer machines (typically 1 vCPU, a few GiB of memory) — the revenue source. Tenant load is characterized by a class: duty cycle $\rho$ (fraction of time working), period $P$, phase $\phi$ (aligned or randomized), resident memory, and IO intensity. We cover four classes: pegged ($\rho{=}1$), bursty ($\rho{\approx}1/3$), idle ($\rho{\approx}1/10$), and synchronized (aligned phase).

Each tenant VM $i$ can be constrained by a control vector $a_i = (\mathrm{pin}_i, q_i, w_i, g_i, b_i, \mathrm{swapmax}_i)$, all through the cgroup v2 interface [15]: core set, CPU quota (`cpu.max`), CPU weight (`cpu.weight`), memory soft limit (`memory.high`), block-IO cap (`io.max`), and per-cgroup swap limit (`memory.swap.max`). Controls never change the sold configuration (no migration, no down-sizing), matching the operational envelope of small providers.

## 3.2 Service-Level Objective and Metrics

**Service SLO.** Within an evaluation window of length $W$, the $P_{99}$ of request completion latency must satisfy $P_{99} \le L$. We use $W \in [30, 120]$ s depending on scenario and $L = 10$ ms; thresholds are fixed before and never adjusted after results. A window that violates is counted as a **violation window**. Requests are injected at a fixed rate by an open-loop generator that records planned send time, actual send time, and completion; timeouts (>2 s) and errors are counted separately and excluded from latency quantiles.

**Customer-side experience.** The work rate of a tenant is its measurable busy-loop iteration rate (it/s), compared against the unconstrained full-speed baseline (roughly 55–75 M it/s depending on load shape); this metric expresses **where the cost lands**.

**Host-side evidence.** Per-cgroup `cpu.stat` (`usage_usec`, `nr_throttled`, `throttled_usec`), `memory.current`/`memory.events`, `io.stat`, plus host-level `MemAvailable`/swap, 3-second CPU busy fraction and PSI pressure counters [16].

## 3.3 Demand, Censoring, and the Observation Model

The **true demand** $d_i(t)$ of tenant $i$ is the CPU it would consume without quota and without contention truncation. The **observable usage** satisfies

$$u_i(t) \;\le\; \min\big(d_i(t),\; q_i\big),$$

truncated either by an explicit quota ($q_i$ binding) or by contention (all tenants shrink proportionally when the host saturates). Both hide demand from a usage dashboard; we focus on quota censoring and detect it via **throttle evidence**:

$$\text{censored}_i(t) \;=\; \mathbf{1}\big[\Delta\,\mathrm{throttled\_usec}_i(t) > \epsilon \;\vee\; \Delta\,\mathrm{nr\_throttled}_i(t) > 0 \big],$$

i.e., the tenant was actually throttled in the window. Two estimators follow:

- **naive**: $\hat d_i^{\text{naive}} = u_i$ (dashboards take usage as demand);
- **censoring-aware (empirical estimator)**: if $\text{censored}_i = 1$, with throttle fraction $t_i$ over the window, take $\hat d_i = \min(\text{vCPU},\, u_i/(1-t_i))$. This formula assumes the tenant would keep burning at its unthrottled rate during throttled time: it is near-unbiased for **saturated** demand (our primary workload family; ground-truth error ≤9% in Section 7.3c), **over-estimates bursty demand** (counterexample in the unit tests: true demand 0.3, quota 0.2 → estimate 1.0), and may under-estimate intermittent saturation. It is therefore an **empirical estimator to be characterized per workload family, not a distribution-free bound**; "at least its full vCPU" remains the conservative fallback. If $\text{censored}_i = 0$, use $u_i$ — note $u_i$ is always a (weak) lower bound on demand; the absence of throttling only rules out quota censoring, not contention shrinkage.

**History length** enters the same way: a newly arrived tenant has $T_{\text{hist}} = 0$ and admits only class priors or conservative bounds; the cold-start discussion builds on this (a dedicated experiment is listed as future work).

### 3.3.1 Identifiability of Censoring: What Counters Can and Cannot Recover

**Observation model and assumptions.** Window $W$ spanning several quota periods $P$; quota $q$ (cores); budget $qP$ per period. Let $u$ = mean usage, $t$ = throttled-time fraction, $\bar d$ = window-mean demand, $\overline{d}_{\text{run}}/\overline{d}_{\text{thr}}$ = mean demand inside the running / throttled stretches. Assumptions: (A1) single cgroup, work-conserving, no external steal; (A2) the budget is exhausted within the window (else no throttle evidence); (A3) $W \gg P$, ignoring period-boundary effects. **Caveat:** `throttled_usec` counts the cgroup's throttled state in real CFS and may include slack inside throttled windows; the identities below are a bandwidth (budget-exhaustion) model, and the residual versus the implementation is reported at the end.

**Proposition 1 (what the point estimate really is, and when it is exact).** When the budget is exhausted, total delivery in the window is $uW = qW$, all of it inside the unthrottled stretch; hence
$$\hat d := \frac{q}{1-t} \;=\; \overline{d}_{\text{run}}\qquad(\text{mean demand over the running stretch}),$$
and under $d(t)\ge q$ throughout (no idle slack) we have the **bias identity**
$$\bar d - \hat d \;=\; t\,\big(\overline{d}_{\text{thr}} - \overline{d}_{\text{run}}\big).$$
The **exactness condition is $\overline{d}_{\text{thr}} = \overline{d}_{\text{run}}$** (equal means over the throttled and running stretches) — **constant demand is sufficient but not necessary**. *Non-constant example:* $q{=}0.3$, one 1 s period, demand 0.6 (first 0.5 s) / 0.4 (0.25 s) / 0.8 (0.25 s): the budget is exhausted at 0.5 s, $t{=}0.5$, and $\hat d = 0.3/0.5 = 0.6 = \bar d$ although demand is plainly not constant. In general: peaks inside the running stretch followed by decay (the typical burst) produce **over-estimation**; demand rising during throttle (low-then-high) produces **under-estimation**; the sign is shape-dependent and not identifiable from aggregates.

*Counterexamples in both directions (idealized model).* **Over:** $q{=}0.5$, $P{=}1$ s, demand 1.0 for the first 0.5 s then 0.5; budget is exhausted at 0.5 s, $t{=}0.5$, $\hat d = 1.0 > \bar d = 0.75$. **Under:** $q{=}0.5$, demand 0.5 for 0.9 s then 1.0; budget exhausts at 0.95 s, $t{=}0.05$, $\hat d = 0.526 < \bar d = 0.55$.

**Proposition 2 (conditional lower bound, under $d \ge q$).** If $d(t) \ge q$ throughout the window (continuous saturation, no slack), then
$$\bar d \;\ge\; q\,(1+t).$$
*(Proof: the running stretch accumulates exactly $qW$; the throttled stretch contributes at least $q\,tW$ because $d \ge q$ there; add and divide by $W$. Equality iff $d \equiv q$ while throttled. $\square$)* **Boundary:** the precondition "$d \ge q$ throughout" **cannot be verified from aggregate counters** — it is a property of the target workload family (continuous saturation), not a per-tenant certification. In the system this floor is used only for tenants with continuous throttle evidence (the conservative backstop of Section 3.3); for everyone else we report the point estimate plus uncertainty and claim no bound.

**Boundary (counterexample):** "continuous throttling" and "d>=q throughout" are **not equivalent** — e.g. q=0.2 with demand 1.0 for the first 20% of each period and 0.1 for the rest: the budget still exhausts every period (t=0.8, constant throttle evidence) yet the true mean is 0.28, *below* q(1+t)=0.36. The engineering trigger is therefore an **empirical conservative policy** (its bias direction is over-estimation, i.e. more conservative admission; it cannot cause over-admission) — not a certified bound, whose status remains conditional on d>=q per Proposition 2.

**Proposition 3 (aggregate non-identifiability).** There exist two demand processes with identical $(u,t,q)$ but different window means; no function of $(u,t,q)$ can be correct for all processes (an identifiability impossibility), and the bias sign is not identifiable. *Construction (throttle time explicitly accounted).* $q{=}0.2$, vCPU$=1$, window = one period. Process A: $d \equiv 5/9 \approx 0.556$ (never slack; $5/9$ makes $t$ exactly 0.64) → budget exhausts at $0.36W$, $t=0.64$, $u=0.2$, mean $5/9 \approx 0.556$. Process B: $d=1.0$ for 84% of the duration, 0 otherwise → budget exhausts at $0.2W$, throttled until $0.84W$, $t=0.64$, $u=0.2$, mean $0.84$. Identical observation $(u,t)=(0.2,0.64)$, means differ by $0.284$; any estimator errs by $\ge 0.142$ on one of them. $\square$

**Practical consequences.** (i) Aggregate unbiasedness is unattainable — estimators are characterized per workload family; (ii) recovering demand *structure* requires *time resolution* (a per-window $t$ sequence or 1-s history) — the motivation for the phase-profiled aggregation in Section 5: **amplitude from throttle evidence (with a conservative floor), structure from time history**; (iii) under-estimation (the unsafe direction) needs an explicit backstop: for continuously saturated tenants the design uses $\hat d = \mathrm{vCPU}$.

**Empirical characterization.** Saturated family: ≤9% across three quota levels (6.3c); the v2 batch (90 cycles = 450 tenant-windows incl. 90 offline): throttle detection + vCPU backstop gives exactly 1.00; the 360 online windows average $t = 0.470$ and the bare formula gives 0.943 (−5.7%) — precisely the residual between Proposition 1's model and real CFS accounting (period boundaries, throttled-state timing including slack), removed by the backstop. The bursty family exposes the other side (backstop reports 1.0 for a true 0.3 — Section 3.3), deliberately conservative; the intermittent family's under-estimation is covered by the no-double-promise + pause monitors.

## 3.4 Decision Problems

The system makes two kinds of decisions over an arrival sequence:

1. **Admission**: for each arriving tenant, use the currently visible evidence (history, throttle evidence, host pressure, latest service-tail windows) to output allow/defer with a reason; batch arrivals require reservation accounting so the same spare capacity is not promised twice.
2. **Shaping**: choose control parameters $a_i$ for admitted tenants, and decide on "release/expand" requests from capped tenants.

The objective is to maximize admitted volume (count, VM-hours, or configuration-weighted) subject to the service SLO, while reporting costs (customer work-rate loss, throttled-tenant queueing) separately and without hiding them.

## 3.5 Assumptions and Scope

- Tenant load is not adversarial: our "pegged tenant" is legitimate but extreme (mining, compilation); malicious behavior is out of scope.
- No live migration, no killing of tenants, no re-configuring of already-sold resources — these change the service model and are deferred.
- The testbed is a nested virtualization environment (Proxmox inside a KVM guest); results reflect the behavior of a topology isomorphic to small-provider production but do not substitute for bare-metal extrapolation.
- The 10 ms SLO is our strict default; the evaluation chapter discusses sensitivity across thresholds.

## 3.6 Observation Necessity: Three Constructive Counterexamples and the Minimal Observation Set

For the decision problems studied in this paper, **the binding constraint is observational capability rather than the capacity algorithm.** Three constructive results (formal proofs and executable counterexamples in Appendix A), each with measured counterparts here:

**Proposition A (censoring impossibility).** Given only aggregate counters (usage, throttle fraction, quota), no estimator that sees only these counters can be correct for all workloads — two processes can produce **identical observations** with different demand (construction in Section 3.3.1, Prop. 3). This is an **identifiability** impossibility (it holds for any deterministic function of the observations) and is stronger than statistical unbiasedness. *Corollary:* dashboard-driven release/oversell decisions are unfixably dangerous — 90/90 independent-round judgments violate (Section 4.3b).

**Proposition B1 (capacity is not determined by marginals; construction).** N tenants each work w seconds per
period P (identical per-tenant marginals). Aligned phases give peak concurrency N; random phases give an overlap
distribution with mean rho N (rho = w/P). With pool capacity C, the aligned fleet is safe iff N <= C, while
the random fleet's capacity is bounded above by C/rho (mean-concurrency necessary condition rho*N <= C) — a **capacity ratio of at most 1/rho = 5** at rho = 0.2 , i.e., random/aligned <= 5. Physical realization
(Section 8.4): primary-bar capacities 28 vs 8 (fine-scan brackets [28,32)/[8,10)), with the unsafe fleet reporting *lower* utilization
(30.4% vs 66.4–68.0%).

**Proposition B2 (threshold impossibility; theorem).** Let the monitoring window be L seconds. An aligned fleet's windowed delivered utilization is capped at **U(L) = [w*floor(L/P) + min(L mod P, w)] / L**: the total overlap of an L-second window with the burst windows is at most w*floor(L/P) + min(L mod P, w), so delivery is at most C times that overlap. Special cases: for L <= P, U(L) = min(w,L)/L (the 30-s rolling window of the sync experiments: 12/30 = 40%); for L an integer multiple of P, U = rho; for L = kP + r with r > 0, U can slightly exceed rho (e.g. L = 90 s: 24/90 = 26.7%). **Hence any rule "admit while windowed utilization < theta" with theta > U(L) admits unbounded N** on aligned fleets whose safe capacity is only C. *Measured counterpart:* util80 (L=30 s, theta=80% > 40%) sells to the experiment cap (40) in the aligned phase while its criterion reads ~20-40% (Section 7.4b); the "35%-busy collapse vs 98%-busy safe" inversion is a field instance of this theorem.

**Proposition C (sampling insufficiency).** Let a monitor sample utilization at fixed interval Delta with burst width w < Delta. There exist benign and dangerous fleets whose **sample sequences are identical** , e.g., all zeros while safe capacities differ — place the bursts between samples. *Evidence level:* formal construction plus indirect measurement (util80's stop alternates 28 vs 40 across identical runs — sampling-moment sensitive, Section 7.4b); the **direct experiment** (fixed phases, sampling interval varied) is listed as future work; this proposition is cited as a construction with indirect evidence only. *Corollary:* the sampling rate must resolve the burst shape of interest (our online history uses **1 second**; a 12-s aligned burst is one phase-bucket wide).

**Minimal sufficient observation set (this paper's design implements it):**

| Capability | Failure axis it covers | Mechanism | Measured consequence when missing |
|---|---|---|---|
| (1) Censoring identification (quota + throttle evidence) | hidden demand | point estimate + conservative heuristic | naive/quantile: 90/90 release violations |
| (2) Phase resolution (joint structure, >= 1 s history) | overlap averaged away | phase profiles + PPC | iid/marginal methods: 40 seats in sync, P5 = 16% |
| (3) Time resolution (sampling rate >= burst width) | bursts sampled away | 1-s history + aligned sampling | single-point busy: 28/40 stop drift across identical runs |

**Evidence levels and boundaries:** A, B1, B2 and C are all formal constructions/theorems (B2 is provable) each with measured counterparts (A: 90/90; B1/B2: Section 8.4 and the util80 sync record; C: construction plus the util80 drift as indirect evidence, direct runs queued). Executable re-checks: Appendix A (`tools/theory_tests.py`, output archived in `research_data/theory_checks.txt`). "Jointly sufficient" is an **empirical statement for our target workload family and quality bars** (in the 14 rounds, the policy with all three is the only one with no service-side violation in either phase and random-phase customer compliance), not a theorem; the aligned-phase customer evidence (show5) is merged, and the anti-aliasing direct experiment remains future work.
