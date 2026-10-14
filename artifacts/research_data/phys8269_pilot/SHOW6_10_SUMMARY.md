# show6-show10 batch analysis (primary bar: service P99 <= 10 ms, customer P5 >= 70%)

## show6: arrival-order repeat (order-seed 42, 12 runs)

### show6 stops (seed 42)

| run | stop N | first violating N | P5 at stop |
|---|---|---|---|
| sync audible | 32 | 34 | - |
| sync fixed | 16 | - | - |
| sync ours | 8 | - | - |
| sync ours_p | 8 | - | - |
| sync quantile | 8 | - | - |
| sync util80 | 32 | 34 | - |
| sync worstcase | 8 | - | - |
| rand audible | 16 | - | 102.2% |
| rand ours | 18 | - | 102.7% |
| rand ours_p | 20 | - | 102.3% |
| rand util80 | 32 | 34 | 87.7% |
| rand worstcase | 8 | - | 102.6% |

### reference stops (show5 sync, show2/admit rand)

| run | stop N | first violating N | P5 at stop |
|---|---|---|---|
| sync audible (show5) | 32 | 34 | - |
| sync fixed (show5) | 16 | - | - |
| sync ours (show5) | 8 | - | - |
| sync ours_p (show5) | 8 | - | - |
| sync quantile (show5) | 8 | - | - |
| sync util80 (show5) | 32 | 34 | - |
| sync worstcase (show5) | 8 | - | - |
| rand audible (ref) | 16 | - | 102.6% |
| rand fixed (ref) | 16 | - | 100.6% |
| rand ours (ref) | 16 | - | 102.6% |
| rand ours_p (ref) | 20 | - | 102.7% |
| rand quantile (ref) | 8 | - | 102.0% |
| rand util80 (ref) | 28 | - | 77.6% |
| rand worstcase (ref) | 8 | - | 103.6% |

## show7: full-chain controller (ours_full)

### show7 stops

| run | stop N | first violating N | P5 at stop |
|---|---|---|---|
| rand_ours_full | 16 | - | 100.2% |
| smoke | 8 | - | - |
| sync_ours_full | 8 | - | - |

## show8: component ablations (quota 80% / no-censor / no-phase)

### show8 stops

| run | stop N | first violating N | P5 at stop |
|---|---|---|---|
| rand_nophase | 28 | - | 99.0% |
| rand_q80 | 18 | - | 79.3% |
| rand_q80_nocensor | 14 | - | 79.4% |
| sync_nophase | 32 | 34 | - |
| sync_q80 | 10 | - | - |
| sync_q80_nocensor | 10 | - | - |

## show9: dense-sampling sell ladders (1 s sampling)

| sell_sell_sync_dense.jsonl | level | svc P99 (ms) | customer P5 | customer P5 (max-rate conv.) |
|---|---|---|---|---|
| | 8 | 0.716 | 97.3% | 99.2% |
| | 10 | 0.745 | 47.8% | 86.2% |
| | 12 | 0.702 | 47.2% | 75.4% |

| sell_sell_rand_dense.jsonl | level | svc P99 (ms) | customer P5 | customer P5 (max-rate conv.) |
|---|---|---|---|---|
| | 24 | 0.726 | 84.5% | 98.8% |
| | 26 | 0.716 | 81.3% | 97.0% |
| | 28 | 0.697 | 75.7% | 95.1% |
| | 30 | 0.741 | 58.3% | 94.3% |
| | 32 | 0.728 | 55.9% | 90.6% |

## show10: guard-metric sensitivity (median guard)

### show10 stops

| run | stop N | first violating N | P5 at stop |
|---|---|---|---|
| rand_guardmed | 4 | - | 101.9% |
| sync_guardmed | 8 | - | - |
