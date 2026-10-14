#!/bin/bash
# Sync-phase rerun with the fixed sampling order (rates captured inside the
# burst window), after show4.
set -u
cd /root/tb
echo "[$(date '+%F %T')] show5 waiting for SHOW4_DONE"
while ! grep -q 'SHOW4_DONE' /root/tb/show4.log 2>/dev/null; do sleep 60; done
echo "[$(date '+%F %T')] show5 start" | tee -a /root/tb/show5.log
for policy in worstcase quantile fixed audible ours ours_p util80; do
  python3 tb_admit.py --round show5_sync_${policy} --mode sync --policy $policy --step 2 --max 40 2>&1 | tee -a /root/tb/show5.log
  echo "=== show5 sync $policy done ===" | tee -a /root/tb/show5.log
done
echo "[$(date '+%F %T')] SHOW5_DONE" | tee -a /root/tb/show5.log
