#!/bin/bash
# Phase 2 prep: deploy the new burner (--jit support) to all customer VMs.
# Keeps a one-time backup of the previous file as /home/debian/burner_v1.py.
set -u
KEY=/root/.ssh/sci2_key
OPTS="-o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -o LogLevel=ERROR"
for ip in 10.10.10.21 10.10.10.22 10.10.10.23 10.10.10.24 10.10.10.25 10.10.10.26 10.10.10.27 10.10.10.28 10.10.10.29 10.10.10.30 10.10.10.31 10.10.10.32 10.10.10.33 10.10.10.34 10.10.10.35 10.10.10.36; do
  ssh -n -i "$KEY" $OPTS debian@"$ip" 'cp -n /home/debian/burner.py /home/debian/burner_v1.py 2>/dev/null; true'
  scp -q -i "$KEY" $OPTS /root/burner_phase2.py debian@"$ip":/home/debian/burner.py
  echo "$ip ok"
done
echo "BURNER_PHASE2_ACTIVATED"
