#!/usr/bin/env python3
"""Sequential, resumable experiment campaign runner (runs ON the PVE test host).

Reads a JSON plan (list of jobs: {round, cmd, out, timeout, kind}) and runs the
jobs one at a time with:

  * per-job timeout (process-group kill),
  * full output log per job (/root/campaign_logs/<round>.log),
  * before/after cleanup (burners/ballast/fio off; cpu.max, memory.high,
    memory.swap.max, io.max, cpu.weight, io.weight, affinity restored on
    customer VMs 111-126),
  * raw probe files copied from the probe VM to /root/campaign_raw/<round>/,
  * resume: a job is skipped when its output file exists and no failure marker
    exists; failed jobs are retried once, then marked in /root/campaign_failed/.

Usage: screen -dmS campaign bash -c 'python3 /root/campaign_host.py --plan /root/campaign_phase1.json'
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import signal
import subprocess
import time

LOG = "/root/campaign_log.txt"
LOGDIR = "/root/campaign_logs"
FAILDIR = "/root/campaign_failed"
RAWDIR = "/root/campaign_raw"
KEY = "/root/.ssh/sci2_key"
PROBE_VM = "10.10.10.20"
CUSTOMER_VMIDS = list(range(111, 127))
CUST_IPS = ["10.10.10.%d" % (20 + k) for k in range(1, 17)]
NEEDED_VMIDS = [101, 102, 110] + CUSTOMER_VMIDS
SSH_BASE = ["-n", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10",
            "-o", "LogLevel=ERROR"]
BUSY3 = ("#!/bin/bash\npython3 - <<PY\nimport time\n"
         "def snap():\n"
         "    f = open(\"/proc/stat\").readline().split()[1:]\n"
         "    v = [int(x) for x in f]\n"
         "    return sum(v), v[3] + v[4]\n"
         "t1, i1 = snap(); time.sleep(3); t2, i2 = snap()\n"
         "print(\"host_busy_pct=%.1f\" % (100.0 * (1.0 - (i2 - i1) / float(t2 - t1))))\n"
         "PY\n")


def ts():
    return dt.datetime.now().strftime("%F %T")


def log(msg):
    line = "[%s] %s" % (ts(), msg)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    print(line, flush=True)


def vm_cmd(ip, cmd, timeout=60):
    try:
        res = subprocess.run(["ssh"] + SSH_BASE + ["debian@" + ip, cmd],
                             capture_output=True, text=True, timeout=timeout)
        return res.stdout
    except subprocess.TimeoutExpired:
        return ""


def w(path, value):
    try:
        with open(path, "w") as fh:
            fh.write(value)
    except OSError:
        pass


def vm_ssh_up(vmid, tries=20):
    ip = "10.10.10.%d" % (vmid - 90)
    for _ in range(tries):
        try:
            res = subprocess.run(["ssh"] + SSH_BASE + ["debian@" + ip, "true"],
                                 capture_output=True, timeout=8)
            if res.returncode == 0:
                return True
        except subprocess.TimeoutExpired:
            pass
        time.sleep(5)
    return False


def heal_and_flush():
    """Auto-heal OOM-killed VMs and relieve host memory pressure (between jobs)."""
    try:
        out = subprocess.run(["qm", "list"], capture_output=True, text=True, timeout=60).stdout
        states = {}
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 3 and parts[0].isdigit():
                states[int(parts[0])] = parts[2]
        restarted = []
        for vmid in NEEDED_VMIDS:
            if states.get(vmid) != "running":
                subprocess.run(["qm", "start", str(vmid)], capture_output=True, timeout=60)
                restarted.append(vmid)
        for vmid in restarted:
            log("heal: restarted VM %d" % vmid)
            vm_ssh_up(vmid)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log("heal failed: %s" % exc)

    # memory flush if host is tight
    try:
        avail_kb = 0
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    avail_kb = int(line.split()[1])
                    break
        if 0 < avail_kb < 1_800_000:   # < 1.8 GB
            sizes = []
            for vmid in CUSTOMER_VMIDS:
                try:
                    with open("/sys/fs/cgroup/qemu.slice/%d.scope/memory.current" % vmid) as fh:
                        sizes.append((int(fh.read().strip()), vmid))
                except (OSError, ValueError):
                    pass
            sizes.sort(reverse=True)
            log("flush: MemAvailable=%.1fGB, cycling %d fattest guests" %
                (avail_kb / 1e6, min(3, len(sizes))))
            for _, vmid in sizes[:3]:
                subprocess.run(["qm", "stop", str(vmid)], capture_output=True, timeout=90)
                time.sleep(3)
                subprocess.run(["qm", "start", str(vmid)], capture_output=True, timeout=60)
                vm_ssh_up(vmid)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log("flush failed: %s" % exc)


def cleanup(tag):
    log("cleanup (%s)" % tag)
    for ip in CUST_IPS:
        vm_cmd(ip, "pkill -f 'burner.py' 2>/dev/null; pkill -f 'ballast.py' 2>/dev/null; "
                   "pkill -f '^fio ' 2>/dev/null; true", timeout=40)
    for vmid in CUSTOMER_VMIDS:
        base = "/sys/fs/cgroup/qemu.slice/%d.scope" % vmid
        w(base + "/cpu.max", "max 100000")
        w(base + "/memory.high", "max")
        w(base + "/memory.swap.max", "max")
        w(base + "/io.max", "rbps=max wbps=max riops=max wiops=max")
        w(base + "/cpu.weight", "100")
        w(base + "/io.weight", "default 100")
        pidf = "/run/qemu-server/%d.pid" % vmid
        try:
            with open(pidf) as fh:
                pid = fh.read().strip()
            if pid:
                subprocess.run(["taskset", "-apc", "0-3", pid],
                               capture_output=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            pass
    heal_and_flush()


def preflight():
    if not os.path.exists("/tmp/busy3.sh"):
        with open("/tmp/busy3.sh", "w") as fh:
            fh.write(BUSY3)
        os.chmod("/tmp/busy3.sh", 0o755)
        log("recreated /tmp/busy3.sh")
    out = subprocess.run(["qm", "list"], capture_output=True, text=True, timeout=60).stdout
    states = {}
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 3 and parts[0].isdigit():
            states[int(parts[0])] = parts[2]
    started = []
    for vmid in NEEDED_VMIDS:
        if states.get(vmid) != "running":
            subprocess.run(["qm", "start", str(vmid)], capture_output=True, timeout=60)
            started.append(vmid)
    if started:
        log("started VMs: %s ; waiting 25 s" % started)
        time.sleep(25)
    else:
        log("preflight: all needed VMs running")


def copy_raws(round_name):
    dest = os.path.join(RAWDIR, round_name)
    os.makedirs(dest, exist_ok=True)
    remote = ('cd /home/debian && find . -maxdepth 1 -name "*%s*.raw" -print0 '
              '| tar -cf - --null -T -' % round_name)
    cmd = "ssh " + " ".join(SSH_BASE) + " debian@%s '%s' | tar -C %s -xf -" % (PROBE_VM, remote, dest)
    subprocess.run(["bash", "-lc", cmd], timeout=300)
    n = len([f for f in os.listdir(dest) if f.endswith(".raw")])
    return n


def run_job(job):
    round_name = job["round"]
    outfile = job["out"]
    failmark = os.path.join(FAILDIR, round_name)
    if os.path.exists(outfile) and not os.path.exists(failmark):
        log("SKIP %s (output exists)" % round_name)
        return "skip"
    attempt = 0
    while attempt < 2:
        attempt += 1
        try:
            os.remove(failmark)
        except OSError:
            pass
        try:
            os.remove(outfile)
        except OSError:
            pass
        log("START %s (attempt %d) kind=%s" % (round_name, attempt, job.get("kind", "?")))
        t0 = time.time()
        logfile = os.path.join(LOGDIR, round_name + ".log")
        with open(logfile, "w", encoding="utf-8") as sink:
            proc = subprocess.Popen(["bash", "-lc", job["cmd"]],
                                    stdout=sink, stderr=subprocess.STDOUT,
                                    start_new_session=True)
            try:
                rc = proc.wait(timeout=job.get("timeout", 1800))
                timed_out = False
            except subprocess.TimeoutExpired:
                timed_out = True
                rc = -1
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except OSError:
                    pass
                proc.wait(timeout=60)
        dur = time.time() - t0
        ok = (not timed_out and rc == 0 and os.path.exists(outfile))
        if ok:
            nraw = 0
            try:
                nraw = copy_raws(round_name)
            except Exception as exc:  # noqa: BLE001
                log("raw copy failed for %s: %s" % (round_name, exc))
            log("OK %s in %.0f s (raw files copied: %d)" % (round_name, dur, nraw))
            return "ok"
        log("FAIL %s rc=%s timeout=%s dur=%.0f s" % (round_name, rc, timed_out, dur))
        cleanup("after failure " + round_name)
        time.sleep(5)
    os.makedirs(FAILDIR, exist_ok=True)
    with open(failmark, "w") as fh:
        fh.write("failed after retry at %s\n" % ts())
    return "fail"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--only", default=None, help="only run jobs whose kind matches (comma list)")
    ap.add_argument("--limit", type=int, default=0, help="max jobs this invocation (0 = all)")
    args = ap.parse_args()

    for d in (LOGDIR, FAILDIR, RAWDIR):
        os.makedirs(d, exist_ok=True)
    plan = json.load(open(args.plan, encoding="utf-8"))
    kinds = set(args.only.split(",")) if args.only else None
    preflight()
    cleanup("campaign start")
    ok = skip = fail = 0
    processed = 0
    for job in plan:
        if kinds and job.get("kind") not in kinds:
            continue
        if args.limit and processed >= args.limit:
            break
        res = run_job(job)
        processed += 1
        cleanup("between jobs")
        ok += res == "ok"
        skip += res == "skip"
        fail += res == "fail"
    log("CAMPAIGN DONE: ok=%d skip=%d fail=%d (processed=%d)" % (ok, skip, fail, processed))


if __name__ == "__main__":
    raise SystemExit(main())
