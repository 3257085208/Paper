#!/bin/bash
# Canary QoE module: waits for EXTRAS_DONE, then measures wakeup stalls under
# four density/phase configs. Writes CANARY_DONE.
set -u
cd /root/tb
echo "[$(date '+%F %T')] canary waiting for EXTRAS_DONE"
while ! grep -q 'EXTRAS_DONE' /root/tb/extras.log 2>/dev/null; do sleep 60; done
echo "[$(date '+%F %T')] canary start" | tee -a /root/tb/canary.log
python3 tb_canary.py --round canary1 2>&1 | tee -a /root/tb/canary.log
echo "[$(date '+%F %T')] CANARY_DONE" | tee -a /root/tb/canary.log
