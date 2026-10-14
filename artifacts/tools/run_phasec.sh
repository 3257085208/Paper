#!/bin/bash
# Phase C chain (physical host): precision-control modules for the
# resource-efficiency reframing. Waits for Phase B, then runs:
#   C3 CPU micro-period sweep -> M1 KSM fleet scan -> M2 free-page-reporting
#   -> M3 zram/disk overcommit arms -> C4 adaptive IO showdown.
set -u
cd /root/tb
echo "[$(date '+%F %T')] phase C waiting for PHASE_B_DONE"
while ! grep -q 'PHASE_B_DONE' /root/tb/phaseb.log 2>/dev/null; do sleep 60; done
echo "[$(date '+%F %T')] phase C start" | tee -a /root/tb/phasec.log
python3 tb_qp2.py --round qp2 2>&1 | tee -a /root/tb/phasec.log
python3 tb_ksm.py --round ksm1 --scan1 600 --scan2 300 2>&1 | tee -a /root/tb/phasec.log
python3 tb_fpr.py --round fpr1 --mb 700 2>&1 | tee -a /root/tb/phasec.log
python3 tb_zram.py --round zram1 2>&1 | tee -a /root/tb/phasec.log
python3 tb_ioctl.py --round ioc1 2>&1 | tee -a /root/tb/phasec.log
echo "[$(date '+%F %T')] PHASE_C_DONE" | tee -a /root/tb/phasec.log
