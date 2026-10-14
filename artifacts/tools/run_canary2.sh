#!/bin/bash
# Canary rerun (stall readings were missing in canary1), after fpr4.
set -u
cd /root/tb
echo "[$(date '+%F %T')] canary2 waiting for FPR4_DONE"
while ! grep -q 'FPR4_DONE' /root/tb/fpr4.log 2>/dev/null; do sleep 60; done
echo "[$(date '+%F %T')] canary2 start" | tee -a /root/tb/canary2.log
python3 tb_canary.py --round canary2 2>&1 | tee -a /root/tb/canary2.log
echo "[$(date '+%F %T')] CANARY2_DONE" | tee -a /root/tb/canary2.log
