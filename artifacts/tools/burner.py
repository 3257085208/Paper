#!/usr/bin/env python3
"""CPU-bound burner with duty-cycle pattern and progress report (VPS customer simulation).

Burns one core during its work phase and writes "<rate> <state>" to <path> every ~2 s:
  rate  = iterations/s measured over the current work phase
  state = 1 when working, 0 when idling
With --duty 1.0 (default) it is a constant busy loop (original behaviour).

Patterns:
  --duty D --period P     fixed duty cycle (work P*D s, idle the rest)
  --aligned               align the work phase to wall-clock period boundaries
  --randphase             start with a random phase offset
  --jit d1,d2,...         draw a new duty from the list at every period
                          (intermittent saturation / random bursts)

Usage:
  python3 burner.py /tmp/burn_rate.txt [seconds] [--duty 0.1] [--period 60] [--aligned]
"""

import argparse
import random
import time

CHUNK = 20000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="/tmp/burn_rate.txt")
    ap.add_argument("duration", nargs="?", type=float, default=3600.0)
    ap.add_argument("--duty", type=float, default=1.0)
    ap.add_argument("--period", type=float, default=60.0)
    ap.add_argument("--aligned", action="store_true")
    ap.add_argument("--phase-offset", type=float, default=0.0,
                    help="with --aligned: shift the work window by N seconds within the period")
    ap.add_argument("--randphase", action="store_true")
    ap.add_argument("--jit", default=None, help="comma list of duties to draw from")
    ap.add_argument("--schedule", default=None,
                    help="file with one duty per line; consumed in order, looping")
    args = ap.parse_args()

    sched = None
    if args.schedule:
        try:
            sched = [min(max(float(x), 0.0), 1.0) for x in open(args.schedule).read().split() if x.strip()]
            if not sched:
                sched = None
        except OSError:
            sched = None
    sched_i = 0
    duties = None
    if args.jit:
        duties = [min(max(float(x), 0.01), 1.0) for x in args.jit.split(",") if x.strip()]
        if not duties:
            duties = None
    duty = min(max(args.duty, 0.01), 1.0)
    period = max(args.period, 1.0)
    t_end = time.time() + args.duration

    def write(rate, state):
        try:
            with open(args.path, "w") as fh:
                fh.write("%.0f %d\n" % (rate, state))
        except OSError:
            pass

    if args.randphase and not args.aligned and (duties or duty < 1.0):
        time.sleep(random.random() * period)

    while time.time() < t_end:
        if sched:
            duty = sched[sched_i % len(sched)]
            sched_i += 1
        elif duties:
            duty = random.choice(duties)
        if duty >= 1.0 and not duties:
            work_end = t_end
        elif args.aligned:
            on_len = period * duty
            phase = (time.time() - args.phase_offset) % period
            if phase >= on_len:
                write(0.0, 0)
                time.sleep(min(1.0, period - phase))
                continue
            work_end = time.time() + (on_len - phase)
        else:
            work_end = min(t_end, time.time() + period * duty)
        wt0 = time.time()
        n = 0
        last = wt0
        while time.time() < work_end and time.time() < t_end:
            for _ in range(CHUNK):
                n += 1
            if time.time() - last >= 2.0:
                write(n / max(0.001, time.time() - wt0), 1)
                last = time.time()
        if duty >= 1.0 and not duties:
            break
        write(n / max(0.001, time.time() - wt0), 1)
        if not args.aligned:
            write(0.0, 0)
            time.sleep(max(0.0, period - (time.time() - wt0)))
    write(0.0, 0)


if __name__ == "__main__":
    main()
