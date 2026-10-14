# 4 Measurement Study

> This is the paper's empirical core (Figures 2–9, 17–18). All numbers come from the archived pilot data plus the v2 mass-repeat campaign; each subsection ends with explicit boundaries. Common settings: service SLO = P99 ≤ 10 ms; probes inject 100 req/s in open loop and log per-request planned/actual send and completion times; host busy fraction from 3-second `/proc/stat` windows; customer rate = busy-loop iterations/s (full-speed baseline ≈ 55–75 M it/s).

## 4.1 Knee and Instantaneous Overlap (Figure 2)

**Setup.** Services (one HTTP, one Redis, 1 vCPU each) are held constant; pegged neighbors (1 vCPU busy loops) are added from 0 to 5; each level is probed for 20 s per service at 100 req/s after a 10 s settle; five rounds run in randomized order.

**Results.** Cross-round means (ms):

| Neighbors | HTTP P50 | HTTP P99 | HTTP P999 | Redis P99 | Host busy |
|---|---|---|---|---|---|
| 0 | 1.39 | 2.57 | 4.0 | 2.40 | ~3% |
| 1 | 1.44 | 3.00 | 6.3 | 2.68 | ~42% |
| 2 | 1.59 | 3.38 | 13.7 | 3.19 | ~67% |
| 3 | 1.92 | 4.86 | 26.8 | 4.95 | ~86% |
| 4 | 11.0 | 23.8 | 27.4 | 20.8 | 100% |
| 5 | 6.9 | 21.5 | 25.9 | 18.5 | 100% |

**Observations.** (i) The knee is stable at 3→4: with the fourth pegged neighbor, P50 jumps from 1.9 to 11.0 ms and P99 from 4.9 to 23.8 ms, tightly across five rounds. (ii) Tail-percentile warning precedes the median collapse: P999 already fluctuates at 2–3 neighbors (14–27 ms), one or two levels earlier. (iii) The 4-vs-5 comparison is non-monotonic in P50 (11.0 vs 6.9) — reading averages alone would rank 5 neighbors "better". (iv) Zero timeouts throughout: the service "looks healthy" by error rate or mean.

**Interpretation.** Once the runnable set persistently exceeds the logical core count (C = 4; the fourth pegged tenant plus service and probe threads), short requests begin queueing for scheduling shares; collapse is an event of **instantaneous concurrency crossing the capacity line**, not of average utilization reaching a threshold (at 3 neighbors the host is already 86% busy yet healthy). This explains why fixed-utilization thresholds fail here and motivates managing instantaneous concurrency in the design.

**Boundaries.** One host, 4 logical cores; neighbors are continuously pegged (worst case); no quotas or isolation; absolute numbers do not extrapolate to other core counts, but the mechanism does not depend on the count.

### 4.1b Repeat: 50-Round Amplification (Figure 17)

**Setup.** The automated engine reran the Section 4.1 procedure **50 times** (v2 campaign; randomized order, settle between levels, two 20 s probes per round). During the campaign the fourth pegged neighbor was OOM-killed by the host in round 2 and stayed down; from then on the nominal 4-neighbor level in fact ran 3 neighbors and the nominal 5-neighbor level ran 4. We therefore merge by **neighbors actually running**: 3 neighbors = all of L3 + L4-from-round-3 (n = 98); 4 neighbors = L5-from-round-3 (n = 48).

**Results (HTTP P99, ms; Figure 17 left).**

| Neighbors running | n | mean | median | range | > 10 ms |
|---|---|---|---|---|---|
| 0 | 50 | 2.92 | 2.84 | 2.45–4.17 | 0 |
| 1 | 50 | 3.42 | 3.31 | 2.74–4.82 | 0 |
| 2 | 50 | 4.47 | 4.47 | 3.19–5.95 | 0 |
| 3 | 98 | 7.36 | 7.10 | 4.71–13.50 | 7 (7%) |
| 4 | 48 | 24.44 | 24.42 | 20.66–28.48 | 48 (100%, all > 20 ms) |

Redis mirrors this (6.8 ms → 21.4 ms). The round-1 L4 sample (when the fourth neighbor was still up, i.e. exactly 4 running) reads 22.99 ms — inside the four-neighbor band.

**Rework batch (all five neighbors online throughout, 50 rounds; Figure 29).**

| Neighbors running | n | mean | median | range | > 10 ms |
|---|---|---|---|---|---|
| 0 (v3) | 50 | 3.14 | 3.1 | 2.6–4.1 | 0 (0%) |
| 1 (v3) | 50 | 3.62 | 3.6 | 2.9–4.6 | 0 (0%) |
| 2 (v3) | 50 | 5.35 | 5.3 | 3.9–8.0 | 0 (0%) |
| 3 (v3) | 50 | 15.41 | 16.0 | 7.4–23.4 | 45 (90%) |
| 4 (v3) | 50 | 24.45 | 24.1 | 19.9–30.6 | 50 (100%) |
| 5 (v3) | 50 | 21.62 | 21.1 | 18.5–25.5 | 50 (100%) |


**Observations.** (i) The 3→4 cliff reproduces **round after round**: 48/48 four-neighbor rounds sit at P99 ≥ 20.7 ms while 93/98 three-neighbor rounds stay ≤ 12 ms — the two distributions do not overlap (Figure 17 right). (ii) Absolute levels run slightly higher than the first 5-round batch (3n 4.9, 4n 23.8 ms → 7.4/24.4 ms here); the ordering and the cliff position are unchanged. We record the drift; plausible causes include host state after ~40 days online and cache/fragmentation differences between batches. (iii) The verdict is threshold-insensitive: even at a 13.5 ms bar only 7% of three-neighbor rounds would be flagged, while the four-neighbor minimum is 20.7 ms. (iv) **v3 rework:** L2 stays clean (all ≤ 8.0 ms; the eps=0 capacity remains 2), but **L3's violation rate moves up sharply — 45/50 rounds (median P99 16.0 ms)** — diverging from the v2 reconstruction (eps~7%; exact Clopper-Pearson 95% interval [78%, 97%] for L3); both batches agree that L4 collapses 100% ([93%, 100%]). So **the eps=0 capacity and the L4 collapse replicate; only L3's risk budget drifts with the host environment** (same protocol, same 87% busy; absolute drift recorded) — the conservative statement uses the eps=0 capacity of 2.

**Boundaries.** The batch baseline differs from the first batch (absolute drift); the post-mortem level merging uses run logs and is automated in `make_v2_figs.py`. The v3 rework shows the L3 risk budget is batch-sensitive (7% vs 90% violation across batches at the same busy) — capacity claims use the eps=0 bar (2 neighbors) and per-batch eps values are reported explicitly.

## 4.2 Synchronized Bursts (Figures 3 and 4)

**Setup.** With "6 synchronized (working during the first ~6 s of every wall-clock minute) + 2 bursty + 2 pegged" tenants, a 120 s probe records per-second latency. Two phase controls follow: ten idle-class customers with clustered phases (near-simultaneous starts) versus fully randomized phases (`--randphase`); and randomized phases mixed with a single pegged tenant.

**Results.** (i) The synchronized scenario has a strict periodic timeline (Figure 3):

```
quiet:    P99 ≈ 2–3 ms
burst:    P50 rises to 4–8 ms, P99 14–22 ms (max 33 ms)
after:    back to 2–3 ms; repeats every 60 s
```

Four replicates (p3, p3b, p3c, p3d): aggregate P99 13.1–22.6 ms, all violating. (ii) Phase control (Figure 4): ten idle tenants cluster-phased → P99 10.2–17.3 ms (violating); fully randomized → 2.7–3.8 ms (two clean rounds). (iii) Randomized phases plus one pegged tenant: P99 14.0–20.8 ms (four rounds p6/p6b/p6c/p6d, all violating).

**Interpretation.** "Mostly idle" and "clean tail" are different properties: an idle population still has a nonzero probability of several members being awake simultaneously; synchronization (intentional alignment or incidental co-start) turns that probability into a regular event. The realistic production mix is closer to "randomized phases + a few persistent heavy tenants", and the mix of Section 4.1's knee with this result shows that **one persistently pegged tenant plus random overlaps already breaks a strict SLO**. This motivates the cold-start problem: at arrival time one cannot know whether a newcomer is idle or that pegged tenant.

**Boundaries.** Aligned bursts are synthetic; clustered phases arise from simultaneous first-boot (production tenants boot at dispersed times, so the fully randomized case is the optimistic, realistic one); loads are synthetic duty-cycle loops rather than real applications.

## 4.3 Demand Censoring under CPU Quotas (Figure 5)

**Setup.** Five tenants are all pegged (true demand 1.0 core each) and capped at `cpu.max = 30000/100000` (30% on average). Two phases are measured: **quota** (caps in effect) and **released** (caps lifted, simulating the operator trusting the usage dashboard). Seven cycles (three in c3, two each in c4 and c5); each phase probes both services for 30 s at 100 req/s and reads per-VM `cpu.stat` deltas.

**Results.** (i) Estimation: the observed combined usage under quota is **1.50 cores** (0.30 each), while throttle evidence (`nr_throttled` growing by ~440–450 per 63 s window; throttled time fraction ≈ 0.3–0.7) reveals a true demand of **5.00 cores** — a **3.3× underestimate, identical in 7/7 runs**. (ii) Services (ms):

| Phase | HTTP P99 (range over 5 runs) | Redis P99 | Host busy |
|---|---|---|---|
| quota | 9.2 – 14.0 | 8.8 – 13.8 | ~57% |
| released | 16.7 – 25.0 | 15.0 – 20.9 | 100% |

After release, customer rates fall to about 27–32 M it/s (about half of full speed), the host is instantaneously saturated, and service P99 violates in 7/7 runs, degrading 5–10 ms beyond the quota phase. (iii) The quota phase itself is not "gentle": quotas slice load into pulses and hold service P99 near, sometimes across, the SLO line (9–14 ms).

**Interpretation.** Censoring has two stacked consequences. First, **estimation bias**: the dashboard shows "2.5 cores of headroom" while the host is already 25% over capacity; decisions based on it (release, expand, sell more) turn the hidden gap into a public incident. Second, a **pulse tax**: quotas protect averages while manufacturing periodic bursts that hurt tails by themselves (consistent with the quota comparisons in Section 4.4). The censoring-aware estimate (throttle evidence plus the throttle fraction → the empirical estimate u/(1−t) (near-exact for saturated demand, ≤9% in Section 7.3c; known bias for bursty patterns — see Section 3.3)) yields 5.00 cores and correctly reports "no headroom; capacity action required", avoiding the self-inflicted release.

**Rework (v3cen, 30 rounds x 3 cycles = 90 cycles, five tenants @30%).** Naive mean 1.54 cores vs truth 5.59 cores (**3.6x under-report**); throttle-corrected |error| median 0.55 cores, **88/90 cycles within +-20%**; naive below 70% of truth in **90/90 cycles** — direction and magnitude replicate in an independent batch; the correction is not exact (which is why Section 3.3.1 frames it as an empirical heuristic).

**Boundaries.** One quota level (30%); synthetic pegged tenants; the quota-phase SLO outcome fluctuates around the line and should be read as "this host already sits at the overload boundary"; the correct next action (migrate/upgrade/refuse) is beyond the scope of online decision-making here.

### 4.3b Repeat: 90 Cycles (Figure 18)

**Setup.** The v2 campaign reran the Section 4.3 procedure **30 rounds × 3 cycles = 90 cycles** (50% quota; 4 tenants actually running — the fourth was offline early in the batch; tenants remain pegged, true demand 1.0 core each). Each cycle probes both phases for 30 s.

**Results (Figure 18).** (i) **Estimation**: in 90/90 cycles the usage panel reports 2.00 cores (4 × 0.50) while throttle evidence recovers 4.00 cores — exactly the truth. A half-size quota halves the reported demand, every cycle. (ii) **Service**: quota-phase HTTP P99 averages 11.4 ms (range 9.1–14.6; 98% of cycles already across the 10 ms line); released-phase averages 24.7 ms (range 20.6–28.9) with **90/90 (100%) violations** — the lowest released-phase cycle is still above the quota phase's 95th percentile.

**Causal clarification.** Two statements must be distinguished: the quota-kept phase already fluctuates around the SLO line (mean 11.4 ms; ~98% of cycles violate), so a release decision **significantly worsens an existing overload condition** rather than transitioning from compliant to first violation; the causal claim here is estimation error -> wrong release -> worse latency.

**Interpretation.** Same direction as the 7-cycle pilot (5 tenants @30%: naive 1.50 vs aware 5.00), but far harder evidence: the underestimate factor equals the quota fraction exactly, throttle evidence restores the truth, and the naive release decision fails in 30 independent rounds (90 time-correlated cycles, clustered by round). The failure is independent of the quota level (30% and 50% variants agree).

**Boundaries.** As in 4.3; this batch runs 4 tenants (one offline).

## 4.4 Reliability of Control Levers (Figures 6–9)

Five candidate levers are each asked to protect the service tail: CPU quotas, CPU weights, core isolation, memory double-gates, and IO caps (with an IO-weight counterexample).

### 4.4.1 CPU quotas: bound averages, not boost safe packing (Figure 6)

Re-running the neighbor sweep with newcomers capped at 0.75 and 0.50 cores: **neither improves the safe knee** (the fourth tenant violates regardless — P99 14.0/11.2 and 15.2/11.3 ms; see Section 4.1 for the eps=0 bar and batch drift), while customers really do slow down (~72–78% and ~48–53% of full speed). Quota-pulse comparison (qp1): extending the period from 100 ms to 1 s changes nothing (P99 12.0 ms); staggered periods (100–300 ms) help marginally (10.7 ms) but stay non-compliant. **Quotas buy no additional safe seats; they only slow customers and sharpen peaks.**

### 4.4.2 CPU weights: 100× priority still fails (Figure 9)

Raising the service VMs' `cpu.weight` to 1000 (10×) and 10000 (100×, a verification run) against default-100 tenants under five pegged tenants yields service P99 25.4/22.8 and 24.0/22.7 ms — **worse than no weights at all** (historic five-pegged P99 21.6/19.5 ms) and opposite to the intuition that weights favor the service. IO weights (`io.weight` 50 vs 500) are equally inert. **Soft priorities are not tail-latency protections; isolation is.**

### 4.4.3 Core isolation: the only lever that survives storms on our testbed (Figures 6, 10)

Pinning services and probe to cores 0–1 and tenants to cores 2–3 yields zero violations at 1–5 pegged neighbors (P99 2.9–3.2 ms); tenants share the remaining two cores as expected (about 44% of full speed each at five tenants). The combined-stress synthesis (Section 4.5 / 6.5) reproduces this four times. The cost is explicitly relocated to the "economy tier" — protected services no longer compete.

### 4.4.4 Memory: the double gate (Figure 7)

Unbounded growth (10 tenants, progressive ballast): at about 13.8 GB of combined tenant residency the host's 1 GB swap is exhausted and **two customer VMs are OOM-killed**, with several tenants' SSH unresponsive; services, being small, survive. Adding `memory.high` (1000/800 MB) eliminates deaths and stabilizes the host, but the reclaim triggered by capped tenants lands almost entirely on anonymous-page swap-out — the small swap drains within seconds and becomes a global bottleneck, with tenants experiencing brief unresponsiveness. Setting `memory.swap.max = 0` alongside (the double gate) stops swap pollution: oversubscription is throttled in place. Note also: with ballooning disabled, memory a tenant "has touched" returns to the host only on VM restart — dynamic return and the "no compression" stance are an explicit tradeoff.

### 4.4.5 Block IO: hard caps work, the offender pays (Figure 8)

Ten tenants running 4K 70/30 random read/write (O_DIRECT) push the host to about 16.5k IOPS and **drag service P99 to 12.1 ms (violating) although services perform almost no disk IO** (a storm hitting "over the mountain"). Applying `io.max = 300 riops / 150 wiops` per tenant caps exactly as configured, drops the host to 2.6k IOPS, and returns service P99 to 2.7 ms; the cost is that **capped tenants' read completion P99 rises to ~96 ms** (queueing at the throttle). Two operational details: cgroup IO accounting keys to the whole-disk device (8:0), not the partition; `io.weight` is a no-op because the host's IO scheduler is `none` (no BFQ).

**Section boundaries.** Service VMs being lightweight is a precondition of "isolation works"; the mechanism behind weight failure (host-side packet path / scheduling-credit dynamics) is left as an open question; memory numbers are tied to the 1 GB swap environment.

---
