# Control-history pilot (2026-10-14) — preliminary, single pair, one run

Question: with matched baseline telemetry and the same control action, do replaceable
(latest-state) and persistent (FIFO backlog) workloads diverge after release while
their throttled-phase host telemetry stays indistinguishable?

Design: VM 311 = replaceable, VM 312 = persistent; same wall clock.
match 4 min (no quota) -> throttle 3 min (20% via qemu.slice/<vmid>.scope/cpu.max)
-> release 12 min (max). Host trace: cgroup cpu.stat every 2 s. Guest: burner_debt v2
(delivered = iterations / CAL, CAL calibrated in the first 60 s unthrottled window;
raw process_time over-reads under vCPU throttling on this testbed).

Results (host-side, authoritative):
| stage | A replaceable | B persistent |
|---|---|---|
| baseline cores | 0.799 | 0.829 |
| throttle cores | 0.200 | 0.200 |
| throttled time in window | 143.2 s | 143.2 s |
| release cores | 0.799 | 0.956 |
| D (deficit) | 106.6 CPU-s | 112.0 CPU-s |
| E (recovery extra) | 0.4 CPU-s | 109.2 CPU-s |
| kappa = E/D | 0.004 | 0.975 |
| drain after release | 0 s | 719 s (~12 min, fully drained) |

Reading: throttled-phase host telemetry is indistinguishable between the two semantics,
yet the post-release futures differ sharply (kappa 0.004 vs 0.975). Historical evidence
collected before a control action cannot predict the post-action load for both semantics.

Caveats: one pair, one run, one workload family; the drain time depends on the release
level (1.0 core) and arrival rate; guest-side delivered is iters/CAL (cross-checked
against host: 0.248/0.246 throttle, 0.787/0.938 release). Executable model-level
counterexamples: tools/control_history_tests.py (T-CH1..T-CH4 all PASS).
