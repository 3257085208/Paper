#!/usr/bin/env python3
"""Guest-side small IO storm: 4K random 70/30 read/write with O_DIRECT.

usage: iostorm.py <seconds> <filename> [workers]
Prints a JSON line: {"iops":..., "read_iops":..., "write_iops":...,
"p99_ms":..., "mbps":...}
"""

import json
import mmap
import os
import random
import sys
import threading
import time

SIZE_MB = 512
BLK = 4096


def worker(fd, seconds, size, stats, idx):
    rnd = random.Random(1234 + idx)
    lat = []
    reads = writes = 0
    t_end = time.time() + seconds
    while time.time() < t_end:
        off = rnd.randrange(0, size - BLK) & ~(BLK - 1)
        t0 = time.time()
        try:
            if rnd.random() < 0.7:
                os.pread(fd, BLK, off)
                reads += 1
            else:
                os.pwrite(fd, b"y" * BLK, off)
                writes += 1
            lat.append((time.time() - t0) * 1000.0)
        except OSError:
            break
    stats[idx] = (reads, writes, lat)


def main():
    seconds = float(sys.argv[1])
    fn = sys.argv[2]
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    size = SIZE_MB << 20
    if not os.path.exists(fn):
        with open(fn, "wb") as fh:
            fh.truncate(size)
    fd = os.open(fn, os.O_RDWR | os.O_DIRECT)
    try:
        os.posix_fallocate(fd, 0, size)
    except OSError:
        pass
    stats = {}
    threads = [threading.Thread(target=worker, args=(fd, seconds, size, stats, i))
               for i in range(workers)]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    dur = time.time() - t0
    os.close(fd)
    reads = sum(r for r, _, _ in stats.values())
    writes = sum(w for _, w, _ in stats.values())
    lat = sorted(x for _, _, ls in stats.values() for x in ls)
    p99 = lat[int(0.99 * (len(lat) - 1))] if lat else None
    out = {"iops": int((reads + writes) / dur), "read_iops": int(reads / dur),
           "write_iops": int(writes / dur), "p99_ms": round(p99, 2) if p99 else None,
           "mbps": round((reads + writes) * BLK / dur / (1 << 20), 1)}
    print(json.dumps(out), flush=True)


if __name__ == "__main__":
    main()
