#!/bin/bash
# Master chain (replaces the four waiting screens): after Phase C ->
# qp2b (fixed micro-period sweep) -> fpr2 (400 MB) -> showdown v2 (7 policies x 2
# phases) -> c5 -> mixedq -> canary -> MASTER_DONE.
set -u
cd /root/tb
echo "[$(date '+%F %T')] master waiting for PHASE_C_DONE"
while ! grep -q 'PHASE_C_DONE' /root/tb/phasec.log 2>/dev/null; do sleep 60; done
echo "[$(date '+%F %T')] master start" | tee -a /root/tb/master.log
python3 tb_qp2.py --round qp2b 2>&1 | tee -a /root/tb/master.log
python3 tb_fpr.py --round fpr2 --mb 400 2>&1 | tee -a /root/tb/master.log
for phase in rand sync; do
  for policy in fixed worstcase util80 quantile audible ours ours_p; do
    python3 tb_admit.py --round show_${phase}_${policy} --mode $phase --policy $policy --step 2 --max 40 \
      2>&1 | tee -a /root/tb/master.log
    echo "=== $phase $policy done ===" | tee -a /root/tb/master.log
  done
done
python3 tb_c5.py --all 2>&1 | tee -a /root/tb/master.log
python3 tb_mixedq.py --round mixedq1 2>&1 | tee -a /root/tb/master.log
python3 tb_canary.py --round canary1 2>&1 | tee -a /root/tb/master.log
echo "[$(date '+%F %T')] MASTER_DONE" | tee -a /root/tb/master.log
