# Bootstrap / exact intervals for the core claims (frozen set)

Customer-level bootstrap (B=10000) of the pooled P5 estimator; the pooled per-customer values are resampled within each level. Small-round-count ranges are in Section 8.4.
| config | level | n | P5 | 95% CI (bootstrap) |
|---|---|---|---|---|
| sync | 8 | 40 | 98.8 | [98.6, 99.0] |
| sync | 10 | 30 | 62.2 | [61.0, 68.6] |
| sync | 16 | 80 | 48.6 | [47.1, 48.9] |
| rand | 28 | 56 | 90.6 | [82.5, 99.3] |
| rand | 32 | 120 | 69.1 | [62.2, 75.5] |
| mix25 | 24 | 53 | 71.5 | [61.0, 85.1] |
| mix50 | 13 | 28 | 94.3 | [90.5, 99.6] |
| mix75 | 10 | 28 | 99.6 | [98.7, 100.5] |

Knee rework (v3, 50 rounds/level), exact Clopper-Pearson 95% intervals for the violation probability (P99 > 10 ms):

- L3 (3 neighbors): 45/50 = 90% [78%, 97%]
- L4 (4 neighbors): 50/50 = 100% [93%, 100%]

Triple-storm rework: 25/26 rounds within SLO; one-sided 95% upper bound on the violation rate ~17.0% (26-round set); combined 29/30 passes -> ~14.9% (see Section 7.5).
