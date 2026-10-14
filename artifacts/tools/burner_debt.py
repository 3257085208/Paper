#!/usr/bin/env python3
"""CPU workload with two work-preservation semantics (control-history pilot, guest side).

One CPU-bound thread. Arrival: a CPU-seconds of work per period (default 0.8 per 1 s),
aligned to wall-clock boundaries. Delivered CPU is measured with time.process_time(),
so under a cgroup quota the un-delivered part is visible as the wall/CPU time gap.

Semantics:
  replaceable : uncompleted work at the period boundary is discarded (latest-state
                computation: only the newest result matters)
  persistent  : uncompleted work stays queued (FIFO backlog) and is drained later

Writes JSONL, one line per period:
  {"t": unix, "k": period index, "arrived": a, "delivered": cpu-s, "backlog": cpu-s, "state": 0|1}

Usage:
  python3 burner_debt.py out.jsonl --mode replaceable --duration 1500
  python3 burner_debt.py out.jsonl --mode persistent  --duration 1500
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
    ap.add_argument("--demand", type=float, default=0.8, help="arrival CPU-s per period")
    args = ap.parse_args()

    P = max(args.period, 0.1)
    a = min(max(args.demand, 0.0), P)
    t0 = time.time()
    t_end = t0 + args.duration
    fh = open(args.path, "a")
    k = 0
    backlog = 0.0

    def emit(kk, arrived, delivered, backlog_now, state):
        fh.write(json.dumps({"t": round(time.time(), 3), "k": kk, "arrived": round(arrived, 4),
                             "delivered": round(delivered, 4), "backlog": round(backlog_now, 4),
                             "state": state}) + "\n")
        fh.flush()

    next_boundary = t0 + P
    cpu_mark = time.process_time()

    if args.mode == "replaceable":
        while time.time() < t_end:
            while (time.time() < next_boundary and time.time() < t_end
                   and (time.process_time() - cpu_mark) < a):
                burn_chunk()
            delivered = time.process_time() - cpu_mark
            cpu_mark = time.process_time()
            k += 1
            emit(k, a, min(delivered, a), 0.0, 1 if delivered > 0.01 else 0)
            now = time.time()
            if now < next_boundary:
                time.sleep(next_boundary - now)
            next_boundary += P
    else:
        backlog = a
        while time.time() < t_end:
            while time.time() < next_boundary and time.time() < t_end:
                if backlog > 0.0:
                    burn_chunk()
                else:
                    time.sleep(0.05)
            delivered = time.process_time() - cpu_mark
            cpu_mark = time.process_time()
            k += 1
            backlog += a
            d = min(backlog, delivered)
            backlog -= d
            if backlog < 1e-6:
                backlog = 0.0
            emit(k, a, d, backlog, 1 if d > 0.01 else 0)
            next_boundary += P

    emit(k + 1, 0.0, 0.0, backlog, 0)
    fh.close()


if __name__ == "__main__":
    main()
