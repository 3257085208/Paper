#!/usr/bin/env python3
"""Memory ballast for the memory-oversubscription experiments.

Allocates and touches <target_mb> of memory in <step_mb> chunks, then keeps
holding it (with optional periodic re-touch so pages stay resident). Writes
"<held_mb> <state>" to <path> every ~2 s:
  state 1 = growing, 2 = allocation failed (hit VM limit), 3 = holding.

Usage: python3 ballast.py /tmp/ballast.txt --target-mb 4000 [--step-mb 256] [--retouch-sec 10]
"""

import argparse
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="/tmp/ballast.txt")
    ap.add_argument("--target-mb", type=int, default=1024)
    ap.add_argument("--step-mb", type=int, default=256)
    ap.add_argument("--retouch-sec", type=float, default=0.0)
    ap.add_argument("--step-sleep", type=float, default=0.0)
    args = ap.parse_args()

    def write(held, state):
        try:
            with open(args.path, "w") as fh:
                fh.write("%d %d\n" % (held, state))
        except OSError:
            pass

    step = max(1, args.step_mb) * 1024 * 1024
    chunks = []
    held_mb = 0
    failed = False
    while held_mb < args.target_mb:
        try:
            chunk = bytearray(step)
        except MemoryError:
            failed = True
            break
        try:
            for i in range(0, len(chunk), 4096):
                chunk[i] = 1
        except MemoryError:
            failed = True
            break
        chunks.append(chunk)
        held_mb += args.step_mb
        write(held_mb, 1)
        if args.step_sleep > 0:
            time.sleep(args.step_sleep)

    write(held_mb, 2 if failed else 3)

    while True:
        if args.retouch_sec > 0 and chunks:
            n = max(1, len(chunks) // 10)
            for c in chunks[::n]:
                for i in range(0, len(c), 65536):
                    c[i] = (c[i] + 1) & 0xFF
            write(held_mb, 3)
            time.sleep(args.retouch_sec)
        else:
            time.sleep(60)
            write(held_mb, 3)


if __name__ == "__main__":
    main()
