#!/bin/bash
# Anti-aliasing / period-variation runs (after the boundary scans):
#  - sync ladder with 7 s rate stride (vs 10 s default) and 90 s per step
#  - sync ladder with period 30 s (duty 0.4) to test period invariance
#  - rand ladder with period 30 s
set -u
cd /root/tb
echo "[$(date '+%F %T')] aliasing waiting for BOUNDARY_DONE"
while ! grep -q 'BOUNDARY_DONE' /root/tb/boundary.log 2>/dev/null; do sleep 60; done
echo "[$(date '+%F %T')] aliasing start" | tee -a /root/tb/aliasing.log
python3 tb_sell.py --round sell_sync_r4 --mode sync --levels "4 8 10 12 16" --collect 90 --rate-gap 7 2>&1 | tee -a /root/tb/aliasing.log
python3 tb_sell.py --round sell_sync_p30 --mode sync --levels "4 8 12 16" --collect 90 --rate-gap 7 --period 30 --duty 0.4 2>&1 | tee -a /root/tb/aliasing.log
python3 tb_sell.py --round sell_rand_p30 --mode rand --levels "16 24 32" --collect 90 --rate-gap 7 --period 30 --duty 0.4 2>&1 | tee -a /root/tb/aliasing.log
echo "[$(date '+%F %T')] ALIASING_DONE" | tee -a /root/tb/aliasing.log
