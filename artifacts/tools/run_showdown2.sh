#!/bin/bash
# Showdown v2: full 5-policy x 2-phase admission showdown with the rich-metric
# driver, run after Phase C finishes. Rounds are named show_<phase>_<policy>.
set -u
cd /root/tb
echo "[$(date '+%F %T')] showdown2 waiting for PHASE_C_DONE"
while ! grep -q 'PHASE_C_DONE' /root/tb/phasec.log 2>/dev/null; do sleep 60; done
echo "[$(date '+%F %T')] showdown2 start" | tee -a /root/tb/showdown2.log
for phase in rand sync; do
  for policy in fixed util80 quantile audible ours; do
    python3 tb_admit.py --round show_${phase}_${policy} --mode $phase --policy $policy --step 2 --max 40 \
      2>&1 | tee -a /root/tb/showdown2.log
    echo "=== $phase $policy done ===" | tee -a /root/tb/showdown2.log
  done
done
echo "[$(date '+%F %T')] SHOWDOWN2_DONE" | tee -a /root/tb/showdown2.log
