#!/usr/bin/env python3
"""Guest-side ballast: allocate, touch, hold, free; print guest MemAvailable.

usage: balloc.py <MB> <hold_seconds>
"""

import sys
import time


def memavail_mb():
    for line in open("/proc/meminfo"):
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) // 1024
    return -1


def main():
    mb = int(sys.argv[1])
    hold = float(sys.argv[2])
    before = memavail_mb()
    chunk = b"x" * (1 << 20)
    buf = []
    for i in range(mb):
        buf.append(bytearray(chunk))
        if i % 64 == 0:
            for j in range(0, 1 << 20, 4096):
                buf[-1][j] = (i + j) & 0xFF
    held = memavail_mb()
    print("ALLOCATED %d MB free_before=%d free_during=%d" % (mb, before, held), flush=True)
    time.sleep(hold)
    del buf
    time.sleep(2)
    print("FREED free_after=%d" % memavail_mb(), flush=True)


if __name__ == "__main__":
    main()
