#!/bin/bash
# Boundary fine scans + multi-cycle (180 s/step, 2 rounds each) for the
# 24-vs-8 capacity claims, queued after the throttle tomography.
set -u
cd /root/tb
echo "[$(date '+%F %T')] boundary waiting for TOMO_DONE"
while ! grep -q 'TOMO_DONE' /root/tb/tomo.log 2>/dev/null; do sleep 60; done
echo "[$(date '+%F %T')] boundary start" | tee -a /root/tb/boundary.log
python3 tb_sell.py --round sell_sync_r2 --mode sync --levels "4 8 10 12 14 16" --collect 180 2>&1 | tee -a /root/tb/boundary.log
python3 tb_sell.py --round sell_sync_r3 --mode sync --levels "4 8 10 12 14 16" --collect 180 2>&1 | tee -a /root/tb/boundary.log
python3 tb_sell.py --round sell_rand_r4 --mode rand --levels "16 20 22 24 26 28 32" --collect 180 2>&1 | tee -a /root/tb/boundary.log
python3 tb_sell.py --round sell_rand_r5 --mode rand --levels "16 20 22 24 26 28 32" --collect 180 2>&1 | tee -a /root/tb/boundary.log
echo "[$(date '+%F %T')] BOUNDARY_DONE" | tee -a /root/tb/boundary.log
