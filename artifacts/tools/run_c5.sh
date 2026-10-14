#!/bin/bash
# C5: phase-arrangement capacity lever. Waits for showdown2, then runs the
# 5 configs (same-phase anchor, anti-2, anti-4, two denser anti configs).
set -u
cd /root/tb
echo "[$(date '+%F %T')] C5 waiting for SHOWDOWN2_DONE"
while ! grep -q 'SHOWDOWN2_DONE' /root/tb/showdown2.log 2>/dev/null; do sleep 60; done
echo "[$(date '+%F %T')] C5 start" | tee -a /root/tb/c5.log
python3 tb_c5.py --all 2>&1 | tee -a /root/tb/c5.log
echo "[$(date '+%F %T')] C5_DONE" | tee -a /root/tb/c5.log
