#!/bin/bash
# FINAL serial chain (single writer, unique marker). Replaces all previous
# waiters after the stale-marker collision incident (2026-10-13 13:12):
# qp2c -> fpr3 -> showdown2 (7 policies x 2 phases, clean host) -> c5 ->
# mixedq -> canary -> zram2 (fixed) -> ioctl -> capmix repeats -> tomo ->
# boundary -> aliasing -> FINAL_DONE.
set -u
cd /root/tb
echo "[$(date '+%F %T')] FINAL chain start" | tee -a /root/tb/final.log

python3 tb_qp2.py --round qp2c 2>&1 | tee -a /root/tb/final.log
python3 tb_fpr.py --round fpr3 --mb 400 2>&1 | tee -a /root/tb/final.log

for phase in rand sync; do
  for policy in fixed worstcase util80 quantile audible ours ours_p; do
    python3 tb_admit.py --round show2_${phase}_${policy} --mode $phase --policy $policy --step 2 --max 40 \
      2>&1 | tee -a /root/tb/final.log
    echo "=== $phase $policy done ===" | tee -a /root/tb/final.log
  done
done

python3 tb_c5.py --all 2>&1 | tee -a /root/tb/final.log
python3 tb_mixedq.py --round mixedq1 2>&1 | tee -a /root/tb/final.log
python3 tb_canary.py --round canary1 2>&1 | tee -a /root/tb/final.log
python3 tb_zram.py --round zram2 2>&1 | tee -a /root/tb/final.log
python3 tb_ioctl.py --round ioc1 2>&1 | tee -a /root/tb/final.log

for r in r2 r3; do
  python3 tb_capmix.py --round capmix_f25_$r --align-frac 0.25 --levels "16 20 24 28" 2>&1 | tee -a /root/tb/final.log
  python3 tb_capmix.py --round capmix_f50_$r --align-frac 0.50 --levels "10 13 16 20" 2>&1 | tee -a /root/tb/final.log
  python3 tb_capmix.py --round capmix_f75_$r --align-frac 0.75 --levels "8 10 13 16" 2>&1 | tee -a /root/tb/final.log
done

python3 tb_throttle_tomo.py --round tomo1 2>&1 | tee -a /root/tb/final.log
python3 tb_sell.py --round sell_sync_r2 --mode sync --levels "4 8 10 12 14 16" --collect 180 2>&1 | tee -a /root/tb/final.log
python3 tb_sell.py --round sell_sync_r3 --mode sync --levels "4 8 10 12 14 16" --collect 180 2>&1 | tee -a /root/tb/final.log
python3 tb_sell.py --round sell_rand_r4 --mode rand --levels "16 20 22 24 26 28 32" --collect 180 2>&1 | tee -a /root/tb/final.log
python3 tb_sell.py --round sell_rand_r5 --mode rand --levels "16 20 22 24 26 28 32" --collect 180 2>&1 | tee -a /root/tb/final.log
python3 tb_sell.py --round sell_sync_r4 --mode sync --levels "4 8 10 12 16" --collect 90 --rate-gap 7 2>&1 | tee -a /root/tb/final.log
python3 tb_sell.py --round sell_sync_p30 --mode sync --levels "4 8 12 16" --collect 90 --rate-gap 7 --period 30 --duty 0.4 2>&1 | tee -a /root/tb/final.log
python3 tb_sell.py --round sell_rand_p30 --mode rand --levels "16 24 32" --collect 90 --rate-gap 7 --period 30 --duty 0.4 2>&1 | tee -a /root/tb/final.log

echo "[$(date '+%F %T')] FINAL_DONE" | tee -a /root/tb/final.log
