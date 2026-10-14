# 11 Conclusion

This paper targets an operating regime overlooked by large-scale cloud research — small VPS hosts that pack
cheap, mostly-idle, occasionally-bursty tenants into a few physical cores — and, using **two self-built
testbeds** (a 4-vCPU nested bed and a 96-thread bare-metal host whose 64-VM fleet reproduces the core results,
with isolation verified against SMT/NUMA topology), **mass repeats at the 50/90/24-round scale** and read-only
telemetry from two production hosts we operate ourselves, recasts "safe oversubscription" as three ordered
problems whose organizing thesis is **observation necessity** (Section 3.6): censoring identification, phase
resolution and time resolution are each necessary — with (1)(2) directly measured and (3) currently a
construction plus indirect evidence — and jointly sufficient as an empirical statement for our target workload
family (the policy with all three is the only one in the 14-round comparison combining random-phase capacity
(16–20 seats) with the aligned-phase 8-seat stop and random-phase customer compliance; aligned-phase customer P5 ~99% at 8 seats, 4-round ladder).

**Identify.** Quota censoring makes demand unobservable in aggregate counters: the point estimate equals the
running-stretch mean (exact iff the two stretch means agree; constant demand is sufficient but not necessary),
the floor q(1+t) is conditional (and, following the counterexample above, explicitly an empirical conservative
heuristic rather than a certified bound), and aggregate non-identifiability is constructed. Validation across
90 cycles (30 independent rounds, clustered) shows throttle-corrected estimates match the truth while naive
release decisions violate in 90/90; the mixed-occupancy ablation quantifies all five estimators (naive -2.31,
quota-scaling +0.01 by coincidence, throttle correction -0.20, full-vCPU +2.70, uncapped -0.16) and isolates
the window-dilution effect that multi-resolution throttle sequences will fix.

**Predict.** Capacity is set by phase structure, not average utilization: random vs aligned safe capacity 28 vs
8 (primary bar P5 ≥ 70%; 3.5x–4x across bars), with the utilization-impossibility counterexample — and the
measured inversion (safe fleet reports 66.4-68.0% busy, the collapsing fleet 30.4%). The safe-capacity
approximation N* = C/(phi + (1-phi) rho) is stated with explicit assumptions and measured error directions. The
Phase-Profile Convolution (PPC) has three artifact-backed modes (parametric simulation, strict three-way
joint block bootstrap with a held-out test third, online peak-envelope approximation); iid convolution is
provably blind to exactly the axis that decides safety (the marginal illusion), and the C5 intervention shows
the axis is controllable (capacity x2/x4 by phase arrangement alone).

**Actuate.** In the complete 14-round comparison (identical arrival streams and evidence), the phase-aware
admission is the only policy combining the verified aligned-phase bracket (8 seats, customer P5 ~99%) with competitive
random-phase capacity (16–20); the audible-style and busy-threshold baselines sell 40 in the aligned phase and
collapse customer P5 to 16%, and the fixed-oversubscription baseline violates the primary bar at 16 — the
phase-blindness of independence assumptions and of utilization criteria, quantified end to end. On the resource-efficiency side (supporting extension, Chapter 9), balloon-free reclaim (KSM 33.4% of fleet
RAM; free-page reporting reclaiming 303 MB; zram absorbing 176.8 GB of overflow) raises density without
shrinking tenant-visible resources under the **domain-scoped** no-regression definition; micro-period quotas,
IO storms and the QoE canary each carry a gain / hidden-cost / visible-regression ledger.

**Limitations.** Two testbeds, one bare-metal host; synthetic duty-cycle loads dominate until the
production-schedule replay completes; round-level intervals, boundary fine scans, show4/show5 repeats and
Phase C modules are labeled in progress rather than concluded; "jointly sufficient" remains an empirical
statement until the anti-aliasing runs and show5 land. We hope this provides small VPS providers with a
reproducible "observation design + capacity model + controller" starting point, and adds "identifiability
boundaries and phase structure" to the oversubscription research agenda.
