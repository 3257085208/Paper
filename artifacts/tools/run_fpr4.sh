#!/bin/bash
# Clean FPR rerun (300 MB, stderr-captured, self-deploying), after the replay.
set -u
cd /root/tb
echo "[$(date '+%F %T')] fpr4 waiting for REPLAY_DONE"
while ! grep -q 'REPLAY_DONE' /root/tb/replay.log 2>/dev/null; do sleep 60; done
echo "[$(date '+%F %T')] fpr4 start" | tee -a /root/tb/fpr4.log
python3 tb_fpr.py --round fpr4 --mb 300 2>&1 | tee -a /root/tb/fpr4.log
echo "[$(date '+%F %T')] FPR4_DONE" | tee -a /root/tb/fpr4.log
