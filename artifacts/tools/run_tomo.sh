#!/bin/bash
# Throttle tomography (multi-resolution estimator ablation), queued after capmix2.
set -u
cd /root/tb
echo "[$(date '+%F %T')] tomo waiting for CAPMIX2_DONE"
while ! grep -q 'CAPMIX2_DONE' /root/tb/capmix2.log 2>/dev/null; do sleep 60; done
echo "[$(date '+%F %T')] tomo start" | tee -a /root/tb/tomo.log
python3 tb_throttle_tomo.py --round tomo1 2>&1 | tee -a /root/tb/tomo.log
echo "[$(date '+%F %T')] TOMO_DONE" | tee -a /root/tb/tomo.log
