# 5 Design: Risk-Calibrated Admission and a Shaping Playbook

> This chapter organizes the measurement findings into an executable decision framework for small providers. Two principles: **(i) never rely on mechanisms our measurements falsified** (soft priorities, average utilization, uncorrected usage); **(ii) separate protection from business** — the service SLO is guarded by isolation, while density is bought with evidence.

## 5.1 Overview

The framework has two layers corresponding to two operational actions:

- **Shaping** decides the competitive form of each admitted tenant and thereby defines the host's **protection envelope** — which resources are held, under what conditions, to what degree. Section 4 condenses to one sentence: **isolation first, hard caps second, soft priorities never.**
- **Admission** decides whether an arriving tenant may enter. It estimates headroom inside the protection envelope using **censoring-corrected demand evidence** and outputs allow/defer with reasons.

Both layers share one set of monitors (service tail latency, host pressure, per-VM throttle/censoring evidence, data quality), which also serve as admission's pause trigger.

## 5.2 The Shaping Playbook

**CPU.** Step one — and the only step validated under every storm on this testbed — is **carving out dedicated cores for sensitive services**: pin service and probe threads to $c_{\text{svc}}$ logical cores (2 on our testbed) and tenants to the rest (`taskset`/cpuset; on Proxmox, `taskset -apc` on the qemu process). The lighter the services, the cheaper this step. Step two (optional): per-tenant `cpu.max` quotas — understood as **business tiering and cost control** (what each tier sells), *not* as a way to admit more: quotas do not move the safe knee (Section 4.4.1), only the tenant's own speed. **Do not use `cpu.weight` as a protection mechanism** (Section 4.4.2: 100× weight fails). Monitors: service P99/P999 and scheduling delay where available.

**Memory.** Double gate plus reserve: per tenant, set `memory.high` (hot-memory budget with $\sum \text{high} \le M_{\text{hot}}$, where $M_{\text{hot}}$ leaves host and service reserves) and `memory.swap.max = 0` (forbid over-users from consuming host swap). Host swap is reserved for services or disabled — Section 4.4.4 shows swap is the amplifier of the reclaim tax; the double gate converts overuse into in-place throttling. If the product promises "no compression", the sales language must also state that, with ballooning off, touched tenant memory is not returned until VM restart (dynamic return and no-compression are mutually exclusive); the hot-memory budget is then the true deliverable memory.

**Block IO.** Per-tenant `io.max` (riops/wiops or bandwidth per sold tier) is the only measured remedy against "IO explosion": host IOPS and business latency snap back immediately, with the cost landing on the throttled tenant's own queueing delay (Section 4.4.5). Two implementation notes: cgroup accounting keys to the whole-disk device (partition numbers may be inert); `io.weight`/`io.latency` depend on an IO scheduler honoring them (the default `none` makes weights no-ops), so do not rely on weights before enabling BFQ. (`io.cost`/iocost offers a scheduler-independent cost model; we did not evaluate it here and draw no conclusions about it.)

**Envelope language.** "Selling 16 vCPU / 48 GiB / 400 GiB" is the **nominal sales envelope**; the protection envelope is: the SLO commitment on $c_{\text{svc}}$ dedicated cores for services + each tenant's $\text{high}$ bytes of hot memory + each tenant's IO cap. The difference between the two envelopes *is* the economy-tier product space — the basis for tiered pricing.

## 5.3 Risk-Calibrated Admission

**Inputs (visible at decision time).** Per-VM history (usage series); censoring evidence (`nr_throttled`/`throttled_usec` deltas); cohort priors from same-configuration tenants; host state (busy fraction, pressure signals, latest full service-tail window); arrival batch size.

**Demand estimation (empirical censoring correction).** For each admitted tenant: if censoring evidence is present, compute $\hat d_i = \min(\text{vCPU},\, u_i/(1-t_i))$ from the observable throttle fraction $t_i$ ($\Delta$`throttled_usec` / window) — an **empirical estimator**: near-unbiased for saturated demand (≤9% on the three cells of Section 7.3.2), over-estimating bursty demand and possibly under-estimating intermittent saturation (assumptions and boundaries in Section 3.3); "at least full vCPU" remains the fallback. Without censoring evidence, use a windowed history quantile (P95 over per-window $u/(1-t)$). An optional **staggered relaxation probe** (bounded 2 s quota release, one tenant at a time) provides direct demand samples. For an arriving tenant ($T_{\text{hist}} = 0$), use the censoring-corrected estimate of same-configuration tenants as prior; when the cohort is too small, degrade to "full vCPU" — cold-start risk is priced at worst case first and relaxed after an observation window.

**Decision rule (time-aligned aggregation).** Maintain 1 s per-VM history; for the admitted set, predict the aggregate demand over the decision horizon from **wall-clock phase profiles** (per-second demand envelopes preserving synchronization) and reserve capacity at a quantile of the measured aggregate demand; charge each new candidate the **class prior pi** (median of the admitted tenants' mean rates; 0.2 when no history). The quota is only a *period-average* bound: `cpu.max` limits the CPU-time budget per quota period, not the instantaneous rate — a throttled tenant can still reach a full vCPU until its period budget exhausts, so the per-second envelopes are built from measured usage and capped at one full vCPU (min(vCPU, u*f)), which doubles as the full-vCPU fallback for continuously saturated tenants (Section 3.3.1). Admit only if reserve + candidate caps ≤ effective tenant-core capacity (× utilization budget). Batch arrivals first reserve capacity; the same spare must not be promised twice.

**Calibration and pausing.** The safety margin is calibrated on independent validation windows against a measured violation budget (empirical calibration; report measured coverage rather than distribution-free guarantees). The following trigger pauses new admission (with hysteresis on resume): service-tail monitor breach; customer-side canary (wakeup stall / work rate) breach; excessive estimation uncertainty (history too short / interval too wide); data-quality events (missing data, counter resets, refresh-period changes); drift (distribution shift, new configuration classes); sustained host pressure. Resumption requires consecutive stable windows, and thresholds are fixed on training/validation sets only.

**Decision horizon.** Default 5 minutes; sensitivity at 1/15 minutes. The horizon is a controller refresh cadence, not a long-term service commitment.

### 5.3.1 Admission Algorithm: Pseudocode and Parameters

```
Algorithm A (risk-calibrated admission; runs on arrival or every Delta minutes)
Input: admitted set S with 1-s usage history u_s(t) (last 120 s), throttle evidence t_s,
       host busy counters, capacity C (tenant cores), utilization budget 0.9
1  for each s in S:
     f_s <- min(2.5, 1/(1 - t_s)) if t_s > 0.02 else 1.0   # censoring correction (no-censor arm: f_s = 1)
     p_s[b] <- max over the last 120 s of min(vCPU_s, u_s(t) * f_s), bucket b = t mod 60
2  peak <- max_b sum_{s in S} p_s[b]                       # phase-profile aggregate peak
   residual <- host-busy cores (independent counter) - sum_s mean30(u_s)
   bg <- max(0, Q95(last 20 residuals) - 0.2)              # measured background reserve (no double counting)
3  pi <- median of admitted tenants' mean rates (0.2 if no history)   # class prior for new candidates
   low-history guard: if more than a third of the admitted tenants (minimum 2) have < 30 samples: defer
4  if peak + |B| * pi + bg <= 0.9 * C: allow; else defer (log which term binds)
Guardrail (parallel): service P99 window violation OR canary wakeup stall > 250 ms OR customer P5 < 70%
   => pause admission; hysteretic recovery after 3 stable windows
Calibration: 0.9 and the hysteresis are fixed on a validation split; report one-sided Clopper-Pearson
bounds and the trials required for a target bound (zero-failure: <=10% needs >=29 trials, <=1% needs
>=299); present as an "empirical safety envelope", never as a 1% guarantee.
```

**Accounting scale and residual risk.** Capacity reservation works at the **1-second scale** (per-second envelopes, quota bounds the 1-s mean); **sub-second quota pulses** are outside the accounting and are covered by isolation plus the service-side guardrail, which triggers independently of prediction error. The two layers make no stacked promises.

### 5.3.2 Certification Protocol for Safety Statements (statistical scope)

**Goal.** For any configuration/workload family, report a one-sided 95% Clopper-Pearson upper bound on the round-level violation rate and the minimum number of independent rounds required for the claimed bound.

**Table 6.** Zero-failure budget: Clopper-Pearson upper bound vs independent rounds.

| Independent rounds n | Violation-rate upper bound |
|---|---|
| 10 | 25.9% |
| 30 | 9.5% |
| 50 | 5.8% |
| 90 | 3.3% |
| 299 | 1.0% |

**Correlation correction.** Rounds share host state (long-run drift, caches, same-batch VM state), so independence is an optimistic bound; the protocol requires (i) effective sample size computed by time-block/round clustering, reporting effective < nominal rounds; (ii) block-level worst-window sensitivity; (iii) every "zero-violation" statement carries its round count and bound.

**Scope of the protocol.** This protocol defines how safety statements must be phrased and what evidence they carry; it is not itself a guarantee. The experiments reported in this paper state their round counts and measured bounds explicitly (e.g., 29/30 envelope passes carry an optimistic one-sided bound of ~14.9%) and do not constitute a 1% risk certificate.

## 5.4 Contrast with Naive Policies

**Table 7.** Naive policies: what each cannot see and the measured consequence

| Policy | What it cannot see | Consequence (measured) |
|---|---|---|
| Fixed oversubscription ratio | Any host/tenant state | Admits 5/5, four violation windows (Section 7.2) |
| Average-utilization threshold | Instantaneous overlap; censoring | Signs off under phase-clustered/synchronized load (Sections 4.1–4.2) |
| Uncorrected historical quantile | Censoring; synchronization | Throttled tenants read as "idle" (Section 4.3) |
| This design | — (manages both explicitly; pauses on uncertainty) | See Section 6 |

## 5.5 Assumptions and Limitations

- No distribution-free risk guarantees; under arbitrary drift or adversarial load we promise monitoring and conservative behavior only.
- The demand estimator is **empirical**: a cross-pattern characterization (5 workload patterns × 3 quotas × 3 quota periods × multi-vCPU, 10 rounds each) is a v2 study; this paper commits only to empirical boundaries on the primary (saturated-heavy) workload family.
- Calibration/pause ablations are re-measured in v2 as a four-policy fair comparison (naive / AUDIBLE-style / aware / time-aligned taligned; ×10 rounds, with an 800/1920 MB memory-gate A/B).
- The CPU quota remains optional: providers without tiering needs can run "isolation + memory double gate + IO caps" alone.
