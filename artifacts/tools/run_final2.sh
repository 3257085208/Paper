#!/bin/bash
# Chain v2: rerun the 8 crash-affected showdown rounds (fix: last_p5 init),
# then continue the remaining chain and write FINAL_DONE (replay/fpr4 wake).
set -u
cd /root/tb
echo "[$(date '+%F %T')] FINAL2 start (rerun rand_ours_p + sync x7)" | tee -a /root/tb/final.log

python3 tb_admit.py --round show2_rand_ours_p --mode rand --policy ours_p --step 2 --max 40 2>&1 | tee -a /root/tb/final.log
for policy in fixed worstcase util80 quantile audible ours ours_p; do
  python3 tb_admit.py --round show2_sync_${policy} --mode sync --policy $policy --step 2 --max 40 2>&1 | tee -a /root/tb/final.log
  echo "=== sync $policy done ===" | tee -a /root/tb/final.log
done

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
