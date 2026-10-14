#!/bin/bash
# Mixed-phase repeat rounds (multi-round prediction-error validation for the
# capacity model): two more rounds per phi, waited behind the master chain.
set -u
cd /root/tb
echo "[$(date '+%F %T')] capmix2 waiting for MASTER_DONE"
while ! grep -q 'MASTER_DONE' /root/tb/master.log 2>/dev/null; do sleep 60; done
echo "[$(date '+%F %T')] capmix2 start" | tee -a /root/tb/capmix2.log
for r in r2 r3; do
  python3 tb_capmix.py --round capmix_f25_$r --align-frac 0.25 --levels "16 20 24 28" 2>&1 | tee -a /root/tb/capmix2.log
  python3 tb_capmix.py --round capmix_f50_$r --align-frac 0.50 --levels "10 13 16 20" 2>&1 | tee -a /root/tb/capmix2.log
  python3 tb_capmix.py --round capmix_f75_$r --align-frac 0.75 --levels "8 10 13 16" 2>&1 | tee -a /root/tb/capmix2.log
done
echo "[$(date '+%F %T')] CAPMIX2_DONE" | tee -a /root/tb/capmix2.log
