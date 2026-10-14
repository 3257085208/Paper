#!/usr/bin/env python3
"""KSM fleet dedup scan (host-side, runs on the PVE host).

Phases: baseline (KSM off) -> scan with use_zero_pages=0 -> use_zero_pages=1.
Samples KSM stats, host MemAvailable, ksmd CPU ticks; probes the service
before/after. Restores run=0 at the end.

Usage: python3 tb_ksm.py --round ksm1 --scan1 600 --scan2 300
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time

KSM = "/sys/kernel/mm/ksm"
KEY = "/root/.ssh/tb_key"
FLEET_MB = 64 * 1024  # 64 VMs x 1 GiB


def r(f):
    try:
        return open("%s/%s" % (KSM, f)).read().strip()
    except OSError:
        return ""


def w(f, v):
    try:
        with open("%s/%s" % (KSM, f), "w") as fh:
            fh.write(str(v) + "\n")
    except OSError as e:
        print("KSM write %s failed: %s" % (f, e), flush=True)


def memavail_mb():
    for line in open("/proc/meminfo"):
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) // 1024
    return -1


def ksmd_cpu_ticks():
    try:
        pid = subprocess.check_output(["pgrep", "-x", "ksmd"]).decode().split()[0]
        p = open("/proc/%s/stat" % pid).read().split()
        return int(p[13]) + int(p[14])
    except Exception:
        return 0


def probe(round_name, tag, seconds=20, rate=100):
    cmd = ("python3 /home/debian/probe.py --mode http --host 10.10.0.11 "
           "--rate %d --duration %d --tag %s-%s --raw /home/debian/%s_%s.raw" %
           (rate, seconds, round_name, tag, round_name, tag))
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", default="ksm1")
    ap.add_argument("--scan1", type=float, default=600)
    ap.add_argument("--scan2", type=float, default=300)
    ap.add_argument("--interval", type=float, default=10)
    args = ap.parse_args()

    sink = open("/root/tb/ksm_%s.jsonl" % args.round, "a", encoding="utf-8")
    start = time.time()

    def sample(phase):
        rec = {"round": args.round, "phase": phase,
               "t": round(time.time() - start, 1),
               "pages_shared": int(r("pages_shared") or 0),
               "pages_sharing": int(r("pages_sharing") or 0),
               "pages_scanned": int(r("pages_scanned") or 0),
               "full_scans": int(r("full_scans") or 0),
               "mem_available_mb": memavail_mb(),
               "ksmd_cpu_ticks": ksmd_cpu_ticks(),
               "run": r("run"), "use_zero_pages": r("use_zero_pages")}
        rec["sharing_mb"] = round(rec["pages_sharing"] * 4.0 / 1024, 1)
        sink.write(json.dumps(rec) + "\n")
        sink.flush()
        return rec

    base = probe(args.round, "before")
    for _ in range(6):
        sample("baseline")
        time.sleep(args.interval)
    w("pages_to_scan", 2000)
    w("sleep_millisecs", 20)
    w("use_zero_pages", 0)
    w("run", 1)
    t0 = time.time()
    while time.time() - t0 < args.scan1:
        sample("scan_zero0")
        time.sleep(args.interval)
    w("use_zero_pages", 1)
    t0 = time.time()
    while time.time() - t0 < args.scan2:
        sample("scan_zero1")
        time.sleep(args.interval)
    after = probe(args.round, "after")
    w("run", 0)
    fin = sample("final")
    sink.close()
    print("KSM done: sharing=%.1f MB (%.1f%% of fleet RAM) | http before=%s after=%s" %
          (fin["sharing_mb"], 100.0 * fin["sharing_mb"] / FLEET_MB,
           (base or {}).get("p99_ms"), (after or {}).get("p99_ms")), flush=True)
    print("KSM %s DONE" % args.round, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
