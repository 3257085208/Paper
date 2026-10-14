#!/bin/bash
# Production-profile replay, queued after the FINAL chain.
set -u
cd /root/tb
echo "[$(date '+%F %T')] replay waiting for FINAL_DONE"
while ! grep -q 'FINAL_DONE' /root/tb/final.log 2>/dev/null; do sleep 60; done
echo "[$(date '+%F %T')] replay start" | tee -a /root/tb/replay.log
python3 tb_replay.py --round replay1 2>&1 | tee -a /root/tb/replay.log
echo "[$(date '+%F %T')] REPLAY_DONE" | tee -a /root/tb/replay.log
