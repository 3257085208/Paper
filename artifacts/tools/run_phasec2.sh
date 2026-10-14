#!/bin/bash
# Phase C completion: zram/disk arms (floor 2 GB, incremental samples) -> adaptive
# IO -> PHASE_C_DONE (unblocks the master chain).
set -u
cd /root/tb
echo "[$(date '+%F %T')] phase C retry start (zram fixed; none-arm envelope already recorded)" | tee -a /root/tb/phasec.log
python3 tb_zram.py --round zram1 2>&1 | tee -a /root/tb/phasec.log
python3 tb_ioctl.py --round ioc1 2>&1 | tee -a /root/tb/phasec.log
echo "[$(date '+%F %T')] PHASE_C_DONE" | tee -a /root/tb/phasec.log
