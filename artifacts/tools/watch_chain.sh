#!/bin/bash
# Auto-chain watcher (runs in its own screen on the test host):
#   1. if the Phase 1 campaign screen is gone but the campaign did not finish,
#      resume Phase 1 (the runner skips finished rounds);
#   2. once Phase 1 is done, launch Phase 2 in screen `campaign2`;
#   3. if Phase 2 dies, relaunch it; exit when Phase 2 completes.
LOG=/root/watcher.log
log() { echo "[$(date '+%F %T')] $*" >>"$LOG"; }

log "watcher started"
while true; do
  sleep 60
  if screen -ls 2>/dev/null | grep -q '\.campaign[^0-9]'; then
    continue
  fi
  if ! grep -q 'CAMPAIGN DONE' /root/campaign_log.txt 2>/dev/null; then
    log "phase1 screen missing and phase1 not done; resuming phase1"
    screen -dmS campaign bash -c 'cd /root && exec python3 /root/campaign_host.py --plan /root/campaign_phase1.json >> /root/campaign_console.log 2>&1'
    sleep 30
    continue
  fi
  if screen -ls 2>/dev/null | grep -q '\.campaign2[^0-9]'; then
    continue
  fi
  if grep -q 'CAMPAIGN DONE' /root/campaign2_console.log 2>/dev/null; then
    log "phase2 complete; watcher exiting"
    exit 0
  fi
  log "launching phase2"
  screen -dmS campaign2 bash -c 'cd /root && exec python3 /root/campaign_host.py --plan /root/campaign_phase2.json >> /root/campaign2_console.log 2>&1'
  sleep 60
done
