# Appendix A — Formal Statements and Executable Checks

> Companion to Sections 3.3.1 (Proposition A) and 3.6 (Propositions B1/B2/C). All constructions are
> numerically re-checked by `tools/theory_tests.py` (output archived in `research_data/theory_checks.txt`;
> reruns in seconds, no external dependencies).

## A.1 Proposition A (censoring impossibility)

**Model.** A single cgroup with bandwidth quota (period $P$, budget $qP$), observation window $W = P$;
observed quantities $(u, t)$.

**Construction.** $q = 0.2$. Process A: $d \equiv 5/9$; process B: $d = 1.0$ for 84% of the period,
0 otherwise.
*A:* the budget exhausts after $(q/d)P = 0.36P$; $t = 1 - q/d = 0.64$, $u = q = 0.2$, mean $5/9$.
*B:* inside the active stretch the budget exhausts after $0.2P$; throttling continues until the active
stretch ends ($0.84P$); $t = 0.64$, $u = 0.2$, mean $0.84$.
Hence $(u,t) = (0.2, 0.64)$ for **both** processes while the means differ by $0.284$: no estimator that
sees only the aggregate counters can be correct for both. This is an **identifiability** impossibility —
it holds for any deterministic function of the observations — and is stronger than statistical
unbiasedness. ∎

## A.2 Proposition B1 (capacity is not determined by marginals)

**Construction.** $N$ tenants, each active for $w$ seconds per period (identical per-tenant marginals),
pool $C = 8$, $\rho = w/P$.
Aligned: peak concurrency $= N$, so the capacity is exactly $C$. Random: the mean concurrency is
$\rho N$, and any reasonable safety bar requires the time-average not to overload, i.e. $\rho N \le C$;
hence $N \le C/\rho$ is an **upper bound** (peak constraints only tighten it).
Therefore the capacity ratio is **at most** $1/\rho$ (i.e. 5 at $\rho = 0.2$). The measured
primary-bar capacities are 28 vs 8 (3.5x) — inside that bound (~70% of it); stricter tail bars shrink
the ratio further. ∎

## A.3 Proposition B2 (threshold impossibility; theorem, any window length)

**Theorem.** For an aligned fleet, the window-mean delivered utilization over any window of length $L$
(possibly spanning multiple periods) is at most
$U(L) = \big[w\lfloor L/P \rfloor + \min(L \bmod P, w)\big]/L$.

**Proof.** The activity set is periodic with period $P$ and $w$ active seconds per period. Any
$L$-second window contains $\lfloor L/P \rfloor$ full periods (each contributing $w$ seconds of
overlap) plus one residual window of length $r = L \bmod P$ (overlap at most $\min(r, w)$). Delivery
rate is at most $C$, so the window utilization is at most $U(L)$. ∎

**Special cases and corollary.** For $L \le P$, $U(L) = \min(w,L)/L$ (the 30-s rolling window used by
util80: $12/30 = 40\%$); for $L$ an integer multiple of $P$, $U = \rho$; for $L = kP + r$ with $r > 0$,
$U$ can slightly exceed $\rho$ (e.g. $L = 90$ s: $24/90 = 26.7\%$). Any rule "admit while windowed
utilization $< \theta$" with $\theta > U(L)$ admits unbounded $N$ on aligned fleets whose safe capacity
is only $C$ (util80: $40\% < \theta = 80\%$; it sold to the experiment cap of 40 — Section 7.4b).

**Executable checks.** T-B3 (single-period caps) and T-B4 (multi-period formula verified numerically by
sliding windows; the earlier single-period formula is demonstrably wrong for $L \in \{90, 120, 150\}$).

## A.4 Proposition C (sampling insufficiency)

**Construction.** Sampler interval $\Delta$, burst width $w < \Delta$, burst window placed between two
samples (e.g. $\Delta = 30$ s, sample phase 3 s, burst $[15, 27)$): the bursty fleet and a benign
(all-idle) fleet produce **identical** all-zero sample sequences. Positive control: at $\Delta = 10$ s a
sample necessarily lands inside the burst. ∎
**Corollary.** The sampling rate must be at least $1/w$ (this paper's online history uses 1 s for
12-s bursts — a 12x margin).

## A.5 What is not provable here (honest statement)

The **sufficiency** of the minimal observation set is an empirical statement over the target workload
family (the 14-round showdown plus the C5 intervention), not a theorem; its direct checks (aligned-phase
customer evidence, anti-aliasing sampling comparison) are reported where available, with the
anti-aliasing experiment listed as future work.
