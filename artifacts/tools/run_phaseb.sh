#!/bin/bash
# Phase B chain (runs on the physical host): wait for the admission showdown
# to finish, then run the mixed-phase capacity ladder at phi = 0.25 / 0.50 / 0.75
# (8-core pool; validated against N_safe(phi) = C / (phi + (1-phi) * duty)).
set -u
cd /root/tb
echo "[$(date '+%F %T')] phase B waiting for admitq to finish"
while screen -ls 2>/dev/null | grep -q '\.admitq'; do sleep 60; done
if ! grep -q 'ADMIT_ALL_DONE' /root/tb/admitq.log 2>/dev/null; then
  echo "[$(date '+%F %T')] admitq gone without ADMIT_ALL_DONE; aborting phase B" | tee -a /root/tb/phaseb.log
  exit 1
fi
echo "[$(date '+%F %T')] phase B start" | tee -a /root/tb/phaseb.log
python3 tb_capmix.py --round capmix_f25 --align-frac 0.25 --levels "16 20 24 28" 2>&1 | tee -a /root/tb/phaseb.log
python3 tb_capmix.py --round capmix_f50 --align-frac 0.50 --levels "10 13 16 20" 2>&1 | tee -a /root/tb/phaseb.log
python3 tb_capmix.py --round capmix_f75 --align-frac 0.75 --levels "8 10 13 16" 2>&1 | tee -a /root/tb/phaseb.log
echo "[$(date '+%F %T')] PHASE_B_DONE" | tee -a /root/tb/phaseb.log
