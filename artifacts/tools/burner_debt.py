#!/usr/bin/env python3
"""CPU workload with two work-preservation semantics (control-history pilot, guest side).

v2 measurement: process_time is unreliable under vCPU throttling on this testbed
(it advances with wall time, over-reading delivered CPU). Delivered CPU is
therefore estimated from ITERATION COUNT against a calibration constant
CAL = iterations per CPU-second, measured during an initial UNTHROTTLED window
(pass --cal-s < match-phase length; the pilot driver guarantees this).

Arrival: a CPU-seconds of work per period (default 0.8 per 1 s), aligned to
wall-clock boundaries. Semantics:
  replaceable : uncompleted work at the period boundary is discarded
  persistent  : uncompleted work stays queued (FIFO backlog) and is drained later

Writes JSONL, one line per period:
  {"t": unix, "k": k, "arrived": a, "delivered": cpu-s, "backlog": cpu-s,
   "state": 0|1, "iters": n, "cal": CAL or null}
"""

import argparse
import json
import time

CHUNK = 20000


def burn_chunk():
    n = 0
    for _ in range(CHUNK):
        n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--mode", required=True, choices=["replaceable", "persistent"])
    ap.add_argument("--duration", type=float, default=1500.0)
    ap.add_argument("--period", type=float, default=1.0)
    ap.add_argument("--demand", type=float, default=0.8)
    ap.add_argument("--cal-s", type=float, default=60.0)
    args = ap.parse_args()

    P = max(args.period, 0.1)
    a = min(max(args.demand, 0.0), P)
    t0 = time.time()
    t_end = t0 + args.duration
    fh = open(args.path, "a")
    k = 0
    backlog = a if args.mode == "persistent" else 0.0
    cal = None
    cal_iters = 0
    cal_cpu0 = time.process_time()
    pt_mark = time.process_time()

    def emit(kk, arrived, delivered, backlog_now, state, iters):
        fh.write(json.dumps({"t": round(time.time(), 3), "k": kk,
                             "arrived": round(arrived, 4), "delivered": round(delivered, 4),
                             "backlog": round(backlog_now, 4), "state": state,
                             "iters": iters, "cal": cal}) + "\n")
        fh.flush()

    next_boundary = t0 + P
    period_iters = 0

    while time.time() < t_end:
        while time.time() < next_boundary and time.time() < t_end:
            if args.mode == "persistent" and backlog <= 0.0:
                time.sleep(0.05)
                continue
            if args.mode == "replaceable":
                if cal is not None:
                    if period_iters >= a * cal:
                        break
                elif time.process_time() - pt_mark >= a:
                    break
            burn_chunk()
            period_iters += CHUNK

        pt = time.process_time()
        period_pt = pt - pt_mark
        pt_mark = pt

        if cal is None:
            cal_iters += period_iters
            if time.time() - t0 >= args.cal_s:
                cpu_used = pt - cal_cpu0
                if cpu_used > 1.0 and cal_iters > 0:
                    cal = cal_iters / cpu_used
            delivered = min(period_pt, a) if args.mode == "replaceable" else period_pt
        else:
            delivered = period_iters / cal

        k += 1
        if args.mode == "persistent":
            backlog += a
            d = min(backlog, delivered)
            backlog -= d
            if backlog < 1e-6:
                backlog = 0.0
        else:
            d = min(delivered, a)
            backlog = 0.0
        emit(k, a, d, backlog, 1 if period_iters > 0 else 0, period_iters)
        period_iters = 0

        now = time.time()
        if now < next_boundary:
            time.sleep(next_boundary - now)
        next_boundary += P

    emit(k + 1, 0.0, 0.0, backlog, 0, 0)
    fh.close()


if __name__ == "__main__":
    main()
