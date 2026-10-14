#!/bin/bash
# Second repetition for the key policies (rand phase), after canary2.
set -u
cd /root/tb
echo "[$(date '+%F %T')] show4 waiting for CANARY2_DONE"
while ! grep -q 'CANARY2_DONE' /root/tb/canary2.log 2>/dev/null; do sleep 60; done
echo "[$(date '+%F %T')] show4 start" | tee -a /root/tb/show4.log
for policy in worstcase audible ours ours_p util80; do
  python3 tb_admit.py --round show4_rand_${policy} --mode rand --policy $policy --step 2 --max 40 2>&1 | tee -a /root/tb/show4.log
  echo "=== show4 rand $policy done ===" | tee -a /root/tb/show4.log
done
echo "[$(date '+%F %T')] SHOW4_DONE" | tee -a /root/tb/show4.log
