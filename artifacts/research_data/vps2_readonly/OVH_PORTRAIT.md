# OVH ns503701 production portrait (6-h dense window, 60 s samples)

window: 2026-10-14T04:25:30+00:00 .. 2026-10-14T10:25:30+00:00  (344 samples)
host: 4 physical cores / 8 threads, RAM total 62.7 GiB

| metric | mean | peak |
|---|---|---|
| host busy (delta counters) | 30.9% | 44.6% |
| CPU PSI some avg300 | 7.2 | 8.2 |
| CPU PSI full avg300 | 0.0 | 0.0 |
| running guests | 66.0 | 66 (min 66) |
| sum vCPU configured (running) | 73.0 (9.12x of 8 threads) | 73 |
| guest memory used | 48.8 GiB | 49.2 GiB |
| guest CPU (sum of fractions, cores) | 1.84 | 2.64 |
| heavy share (>=30% of a vCPU) | 2.2% | 4.5% |

node memory used (window mean): 43.3 GiB of 62.7 GiB total

notes: ids are HMAC'd; no business content read; the host runs a mixed VPS +
container workload (nkx-game-* containers included in the guest list only if
they appear as qemu guests; lxc guests are excluded by the qemu filter).
