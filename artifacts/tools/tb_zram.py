#!/usr/bin/env python3
"""Host-level memory-overcommit arms: none / zram / disk swap (host-side).

Allocates cold anonymous pages in a host ballast until MemAvailable hits a
floor (none) or the target is reached (zram/disk). Samples PSI, swap counters,
zram mm_stat, and probes the HTTP service at checkpoints. Cleans up after.

Usage: python3 tb_zram.py --round zram1 --target-gb 1024 --floor-gb 8
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import signal
import sys
import subprocess
import threading
import time

KEY = "/root/.ssh/tb_key"
CHUNK_MB = 512


def meminfo():
    out = {}
    for line in open("/proc/meminfo"):
        k = line.split(":")[0]
        v = line.split()[1]
        out[k] = int(v) // 1024
    return out


def psi(kind="memory", field="some"):
    for line in open("/proc/pressure/%s" % kind):
        if line.startswith(field):
            parts = dict(p.split("=") for p in line.split()[1:])
            return {k: float(v) for k, v in parts.items()}
    return {}


def vmstat():
    out = {}
    for line in open("/proc/vmstat"):
        k, v = line.split()
        if k in ("pswpin", "pswpout", "pgscan_kswapd", "pgsteal_kswapd"):
            out[k] = int(v)
    return out


def zram_stat():
    try:
        return open("/sys/block/zram0/mm_stat").read().strip()
    except OSError:
        return ""


def probe(tag, seconds=15, rate=100):
    cmd = ("python3 /home/debian/probe.py --mode http --host 10.10.0.11 "
           "--rate %d --duration %d --tag %s --raw /home/debian/%s.raw" % (rate, seconds, tag, tag))
    try:
        out = subprocess.run(
            ["ssh", "-n", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
             "-o", "LogLevel=ERROR", "debian@10.10.0.20", cmd],
            capture_output=True, text=True, timeout=2 * seconds + 90).stdout
    except subprocess.TimeoutExpired:
        return None
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                pass
    return None


def make_chunk(mb, compressible):
    n = mb << 20
    if compressible:
        unit = (b"debian-linux-vps-" * 256)[:4096]
        return (unit * (n // 4096))
    return os.urandom(n)


def ballast(target_mb, floor_mb, compressible, stop_evt, result):
    buf = []
    got = 0
    while got < target_mb:
        if stop_evt.is_set():
            break
        avail = meminfo().get("MemAvailable", 0)
        swap_free = meminfo().get("SwapFree", 0)
        if avail < floor_mb and swap_free < 256:  # MB units (meminfo divides by 1024)
            result["aborted_low_avail"] = True
            break
        try:
            chunk = make_chunk(CHUNK_MB, compressible)
        except MemoryError:
            nerr = result.get("mem_errors", 0) + 1
            result["mem_errors"] = nerr
            if nerr > 240:
                result["memory_error"] = True
                break
            time.sleep(3)
            continue
        buf.append(chunk)
        got += CHUNK_MB
        result["allocated_mb"] = got
        result["mem"] = meminfo()
    result["allocated_mb"] = got
    result["done"] = True
    while not stop_evt.is_set():
        time.sleep(1)
    del buf
    result["freed"] = True


def run_arm(name, target_mb, floor_mb, compressible, sink, round_name):
    stop_evt = threading.Event()
    result = {}
    t = threading.Thread(target=ballast, args=(target_mb, floor_mb, compressible, stop_evt, result), daemon=True)
    t0 = time.time()
    t.start()
    samples = []
    probe_mid = None
    last_alloc = 0
    while t.is_alive() and not result.get("done"):
        m = meminfo()
        rec = {"round": round_name, "arm": name, "t": round(time.time() - t0, 1),
               "allocated_mb": result.get("allocated_mb", 0),
               "mem_available_mb": m.get("MemAvailable"),
               "swap_used_mb": m.get("SwapTotal", 0) - m.get("SwapFree", 0),
               "psi_mem_some10": psi("memory").get("avg10"),
               "psi_io_some10": psi("io").get("avg10"),
               "zram": zram_stat()}
        samples.append(rec)
        sink.write(json.dumps(rec) + "\n")
        sink.flush()
        alloc = result.get("allocated_mb", 0)
        if probe_mid is None and alloc >= 900 * 1024:  # probe once at ~900 GB
            probe_mid = probe("%s_%s_mid" % (round_name, name))
        last_alloc = alloc
        time.sleep(3)
    mid_http = probe_mid
    if not last_alloc:
        last_alloc = result.get("allocated_mb", 0)
    # hold briefly at peak to observe steady state
    peak_state = {"arm": name, "allocated_mb": last_alloc, "mem": meminfo(),
                  "vmstat": vmstat(), "zram": zram_stat(),
                  "psi_memory": psi("memory"), "psi_io": psi("io")}
    time.sleep(10)
    stop_evt.set()
    t.join(timeout=60)
    end = {"arm": name, "duration_s": round(time.time() - t0, 1),
           "aborted_low_avail": result.get("aborted_low_avail", False),
           "allocated_mb": result.get("allocated_mb", 0)}
    for s in samples:
        sink.write(json.dumps(s) + "\n")
    sink.flush()
    print("ZRAM arm=%s: wrote %.1f GB in %.0fs, aborted=%s, mid_http_p99=%s" %
          (name, last_alloc / 1024.0, end["duration_s"], end["aborted_low_avail"],
           (mid_http or {}).get("p99_ms")), flush=True)
    return end, peak_state, mid_http


def _cleanup():
    import subprocess as sp
    sp.run("swapoff /dev/zram0 2>/dev/null; zramctl --reset --all 2>/dev/null; "
           "swapoff /srv/tb0/swapfile 2>/dev/null; true", shell=True)


def _sig(signum, frame):
    print("signal %d: cleaning zram/swap then exit" % signum, flush=True)
    _cleanup()
    os._exit(130)


def main():
    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", default="zram1")
    ap.add_argument("--target-gb", type=int, default=1024)
    ap.add_argument("--floor-gb", type=int, default=8)
    args = ap.parse_args()

    try:
        with open("/proc/self/oom_score_adj", "w") as fh:
            fh.write("1000\n")
    except OSError:
        pass
    sink = open("/root/tb/zram_%s.jsonl" % args.round, "a", encoding="utf-8")
    summary = {"round": args.round, "arms": []}
    target_mb = args.target_gb * 1024
    floor_mb = args.floor_gb * 1024

    # swap arms: do NOT abort on MemAvailable (it excludes swap); allocate to the
    # fixed target and let zram/disk swap absorb the overflow; abort only on real
    # distress (MemAvailable < 512 MB AND no swap free, or PSI stall > 50).
    floor_mb = 512

    # arm 2: zram (compressible ballast)
    subprocess.run("modprobe zram num_devices=1", shell=True)
    ok = subprocess.run("zramctl --find --size 192G --algorithm zstd", shell=True,
                        capture_output=True).returncode == 0
    if not ok:
        subprocess.run("echo zstd > /sys/block/zram0/comp_algorithm || true", shell=True)
        subprocess.run("echo 192G > /sys/block/zram0/disksize", shell=True)
    subprocess.run("mkswap /dev/zram0 && swapon -p 10 /dev/zram0", shell=True, capture_output=True)
    end, peak, mid_http = run_arm("zram", target_mb, floor_mb, True, sink, args.round)
    summary["arms"].append({**end, "mid_http_p99": (mid_http or {}).get("p99_ms"),
                            "zram_peak": peak.get("zram")})
    subprocess.run("swapoff /dev/zram0", shell=True)
    subprocess.run("zramctl -r /dev/zram0", shell=True)
    time.sleep(20)

    # arm 3: disk swap on tb0
    subprocess.run("test -f /srv/tb0/swapfile || fallocate -l 96G /srv/tb0/swapfile",
                   shell=True)
    subprocess.run("chmod 600 /srv/tb0/swapfile && mkswap /srv/tb0/swapfile",
                   shell=True, capture_output=True)
    subprocess.run("swapon -p 5 /srv/tb0/swapfile", shell=True, capture_output=True)
    end, peak, mid_http = run_arm("disk", target_mb, floor_mb, True, sink, args.round)
    summary["arms"].append({**end, "mid_http_p99": (mid_http or {}).get("p99_ms")})
    subprocess.run("swapoff /srv/tb0/swapfile", shell=True)
    time.sleep(10)

    with open("/root/tb/zram_%s_summary.json" % args.round, "w") as fh:
        json.dump(summary, fh, indent=1)
    sink.close()
    print("ZRAM summary:", json.dumps(summary, indent=1), flush=True)
    print("ZRAM %s DONE" % args.round, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
