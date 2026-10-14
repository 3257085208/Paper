#!/bin/bash
# Extras chain: after C5 finishes -> showdown2b (worstcase + ours_p x 2 phases)
# -> mixed-quota estimator ablation. Then EXTRAS_DONE.
set -u
cd /root/tb
echo "[$(date '+%F %T')] extras waiting for C5_DONE"
while ! grep -q 'C5_DONE' /root/tb/c5.log 2>/dev/null; do sleep 60; done
echo "[$(date '+%F %T')] showdown2b start" | tee -a /root/tb/extras.log
for phase in rand sync; do
  for policy in worstcase ours_p; do
    python3 tb_admit.py --round show_${phase}_${policy} --mode $phase --policy $policy --step 2 --max 40 \
      2>&1 | tee -a /root/tb/extras.log
    echo "=== $phase $policy done ===" | tee -a /root/tb/extras.log
  done
done
echo "[$(date '+%F %T')] mixedq start" | tee -a /root/tb/extras.log
python3 tb_mixedq.py --round mixedq1 2>&1 | tee -a /root/tb/extras.log
echo "[$(date '+%F %T')] EXTRAS_DONE" | tee -a /root/tb/extras.log
