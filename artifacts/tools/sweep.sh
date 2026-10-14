#!/bin/bash
# Repeat sweep for the neighbor-load latency curve (BeroHost pilot testbed).
#
# Usage: bash tools/sweep.sh <round> "<level order, space separated>"
#   e.g. bash tools/sweep.sh r2 "2 5 0 3 1 4"
#
# Levels = number of neighbor VMs running one busy CPU loop each.
# For each level in the given (pre-shuffled) order this script:
#   1. stops all burners and starts exactly <level> burners,
#   2. waits 10 s to settle,
#   3. records host busy% (3 s /proc/stat window),
#   4. runs the open-loop probe (100 req/s, 20 s) against svc-http and svc-redis.
# The requested per-level order is recorded in the tool call; use a fresh
# round name per repetition so raw files (round_L<level>_<svc>.raw) stay apart.
set -u

KEY="$HOME/.ssh/sci2_key"
HOST="45.82.120.52"
PORT="2828"
PROBEVM="10.10.10.20"
NEIGHBORS=(21 22 23 24 25)

ROUND="${1:?usage: sweep.sh <round> <level order>}"
ORDER="${2:?usage: sweep.sh <round> <level order>}"

host() {
  ssh -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
      -p "$PORT" -o ConnectTimeout=15 "root@$HOST" "$1" 2>&1
}

proxy() {
  ssh -o "ProxyCommand=ssh -i $KEY -o IdentitiesOnly=yes -o BatchMode=yes -p $PORT root@$HOST -W %h:%p" \
      -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
      -o ConnectTimeout=12 "debian@$1" "$2" 2>&1
}

set_burners() {
  local count="$1" idx=0 ip
  for ip in "${NEIGHBORS[@]}"; do
    idx=$((idx + 1))
    if [ "$idx" -le "$count" ]; then
      proxy "10.10.10.$ip" 'pkill -x yes 2>/dev/null; sleep 1; nohup yes > /dev/null 2>&1 & echo burner_on' >/dev/null 2>&1
    else
      proxy "10.10.10.$ip" 'pkill -x yes 2>/dev/null; true' >/dev/null 2>&1
    fi
  done
}

for L in $ORDER; do
  echo "===== ${ROUND} LEVEL ${L} ====="
  set_burners "$L"
  sleep 10
  host '/tmp/busy3.sh'
  proxy "$PROBEVM" "python3 /home/debian/probe.py --mode http --host 10.10.10.11 --rate 100 --duration 20 --tag ${ROUND}-L${L}-http --raw /home/debian/${ROUND}_L${L}_http.raw"
  proxy "$PROBEVM" "python3 /home/debian/probe.py --mode redis --host 10.10.10.12 --rate 100 --duration 20 --tag ${ROUND}-L${L}-redis --raw /home/debian/${ROUND}_L${L}_redis.raw"
done

echo '=== cleanup: burners off ==='
set_burners 0
echo "ROUND ${ROUND} DONE"
