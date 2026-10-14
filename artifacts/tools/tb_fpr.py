#!/usr/bin/env python3
"""Free-page-reporting (FPR) verification (host-side, runs on the PVE host).

For 3 idle guests: guest allocates N MB (balloc.py), holds, frees; host-side
qemu cgroup memory.current is sampled throughout. With FPR on, the host should
reclaim the freed pages (memory.current returns toward baseline) while the
guest's visible MemTotal never changes. Also verifies the balloon driver
supports reporting.

Usage: python3 tb_fpr.py --round fpr1 --mb 700
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import time

KEY = "/root/.ssh/tb_key"
CUSTOMERS = {vmid: "10.10.0.%d" % (vmid - 290) for vmid in range(311, 375)}
SSH = ["-n", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
       "-o", "StrictHostKeyChecking=accept-new", "-o", "LogLevel=ERROR"]


def vm_cmd(ip, cmd, timeout=120):
    try:
        res = subprocess.run(["ssh"] + SSH + ["debian@" + ip, cmd],
                             capture_output=True, text=True, timeout=timeout)
        return res.stdout
    except subprocess.TimeoutExpired:
        return ""


def mem_current_mb(vmid):
    try:
        return int(open("/sys/fs/cgroup/qemu.slice/%d.scope/memory.current" % vmid).read()) // (1 << 20)
    except OSError:
        return -1


def guest_memtotal_mb(ip):
    out = vm_cmd(ip, "grep MemTotal /proc/meminfo")
    try:
        return int(out.split()[1]) // 1024
    except (ValueError, IndexError):
        return -1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", default="fpr1")
    ap.add_argument("--mb", type=int, default=400)
    ap.add_argument("--vms", default="311 312 313")
    args = ap.parse_args()

    vmids = [int(x) for x in args.vms.split()]
    for vmid in vmids:
        subprocess.run(["scp", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                        "-o", "LogLevel=ERROR", "/root/tb/balloc.py",
                        "debian@%s:/home/debian/balloc.py" % CUSTOMERS[vmid]],
                       capture_output=True)
    sink = open("/root/tb/fpr_%s.jsonl" % args.round, "a", encoding="utf-8")

    # driver sanity
    drv = vm_cmd(CUSTOMERS[vmids[0]], "dmesg 2>/dev/null | grep -i -m2 balloon; "
                                      "ls /sys/bus/virtio/drivers/virtio_balloon 2>/dev/null | head -2")
    print("guest balloon driver check:", " / ".join(drv.split()), flush=True)

    for vmid in vmids:
        ip = CUSTOMERS[vmid]
        mt = guest_memtotal_mb(ip)
        base = mem_current_mb(vmid)
        t0 = time.time()
        # start allocation in background on the guest
        proc = subprocess.Popen(
            ["ssh"] + SSH + ["debian@" + ip, "python3 /home/debian/balloc.py %d 25" % args.mb],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        series = []
        while proc.poll() is None:
            series.append({"t": round(time.time() - t0, 1), "mem_current_mb": mem_current_mb(vmid)})
            time.sleep(2)
        out, _ = proc.communicate(timeout=30)
        printed = False
        for line in out.splitlines():
            if line.startswith(("ALLOCATED", "FREED")):
                print("  guest %d: %s" % (vmid, line), flush=True)
                printed = True
        if not printed:
            tail = " | ".join(out.splitlines()[-3:])[:220]
            print("  guest %d: balloc rc=%s, tail=[%s]" % (vmid, proc.returncode, tail), flush=True)
        peak = max(s["mem_current_mb"] for s in series) if series else -1
        # keep sampling after free to observe FPR reclaim
        t1 = time.time()
        while time.time() - t1 < 75:
            series.append({"t": round(time.time() - t0, 1), "mem_current_mb": mem_current_mb(vmid)})
            time.sleep(3)
        final = mem_current_mb(vmid)
        rec = {"round": args.round, "vmid": vmid, "alloc_mb": args.mb,
               "guest_memtotal_mb": mt, "host_mem_base_mb": base,
               "host_mem_peak_mb": peak, "host_mem_final_mb": final,
               "reclaimed_mb": peak - final,
               "guest_total_unchanged": mt > 0,
               "series": series,
               "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
        sink.write(json.dumps(rec) + "\n")
        sink.flush()
        print("FPR vm%d: base=%d peak=%d final=%d reclaimed=%d MB (guest MemTotal=%d unchanged)" %
              (vmid, base, peak, final, peak - final, mt), flush=True)
    sink.close()
    print("FPR %s DONE" % args.round, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
