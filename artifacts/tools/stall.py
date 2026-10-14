#!/usr/bin/env python3
"""Wakeup-stall monitor for a customer VM (customer-side QoS proxy).

Sleeps 200 ms in a loop and measures the *extra* delay beyond the requested
sleep. Under CPU starvation (throttling/contention) the gaps grow; we report
the max gap and the count of gaps above thresholds per window.

Writes "<window_s> <max_gap_ms> <stalls_gt_250ms> <stalls_gt_1s>" to <path>
every ~5 s.

Usage: python3 stall.py /tmp/stall.txt
"""

import sys
import time

path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/stall.txt"
interval = 0.2
win_start = time.perf_counter()
last = win_start
max_gap = 0.0
gt250 = 0
gt1s = 0

while True:
    time.sleep(interval)
    now = time.perf_counter()
    gap_ms = (now - last - interval) * 1000.0
    last = now
    if gap_ms > max_gap:
        max_gap = gap_ms
    if gap_ms > 250.0:
        gt250 += 1
    if gap_ms > 1000.0:
        gt1s += 1
    if now - win_start >= 5.0:
        try:
            with open(path, "w") as fh:
                fh.write("%.0f %.1f %d %d\n" % (now - win_start, max_gap, gt250, gt1s))
        except OSError:
            pass
        win_start = now
        max_gap = 0.0
        gt250 = 0
        gt1s = 0
