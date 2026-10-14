#!/bin/bash
# Phase B retry: the original phaseb aborted on a bad log-marker check
# (it waited for admitq.log, which chain_admit.sh never created). admitq
# did complete all 10 runs (verified). This retry runs the mixed-phase
# capacity ladder and writes PHASE_B_DONE, unblocking phasec.
set -u
cd /root/tb
echo "[$(date '+%F %T')] phase B retry start (admitq completed 10/10; marker bug fixed)" | tee -a /root/tb/phaseb.log
python3 tb_capmix.py --round capmix_f25 --align-frac 0.25 --levels "16 20 24 28" 2>&1 | tee -a /root/tb/phaseb.log
python3 tb_capmix.py --round capmix_f50 --align-frac 0.50 --levels "10 13 16 20" 2>&1 | tee -a /root/tb/phaseb.log
python3 tb_capmix.py --round capmix_f75 --align-frac 0.75 --levels "8 10 13 16" 2>&1 | tee -a /root/tb/phaseb.log
echo "[$(date '+%F %T')] PHASE_B_DONE" | tee -a /root/tb/phaseb.log
