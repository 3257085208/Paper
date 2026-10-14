#!/usr/bin/env python3
"""Portrait of the second production host (OVH ns503701) from the 6-h dense window.

Reads research_data/vps2_readonly/pve_metrics_ovh.jsonl (60 s samples, HMAC'd ids)
and writes research_data/vps2_readonly/OVH_PORTRAIT.md.
"""

from __future__ import annotations

import json
import os
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "research_data", "vps2_readonly", "pve_metrics_ovh.jsonl")
OUT = os.path.join(HERE, "..", "research_data", "vps2_readonly", "OVH_PORTRAIT.md")
lines = []


def log(s):
    print(s)
    lines.append(s)


def main():
    recs = [json.loads(l) for l in open(DATA) if l.strip()]
    log("# OVH ns503701 production portrait (6-h dense window, 60 s samples)")
    log("")
    log("window: %s .. %s  (%d samples)" % (recs[0]["timestamp_utc"], recs[-1]["timestamp_utc"], len(recs)))

    node = recs[0]["nodes"][0]
    cpus = node["logical_cpus"]
    log("host: %d physical cores / %d threads, RAM total %.1f GiB" % (
        node["physical_cores"], cpus, node["memory_total_bytes"] / 2**30))

    busy, psome, pfull, nrun, svcpu, smem, guest_cpu = [], [], [], [], [], [], []
    heavy_share = []
    for i, r in enumerate(recs):
        if i:
            c0, c1 = recs[i - 1]["host_cpu_counters"], r["host_cpu_counters"]
            dtot = c1["total"] - c0["total"]
            didle = c1["idle"] - c0["idle"]
            if dtot > 0:
                busy.append(100.0 * (1.0 - didle / dtot))
        pr = r.get("host_cpu_pressure") or {}
        for key, arr in (("some", psome), ("full", pfull)):
            v = (pr.get(key) or {}).get("avg300")
            if v is not None:
                arr.append(v)
        g = [x for x in r.get("guests", []) if x.get("status") == "running"]
        nrun.append(len(g))
        svcpu.append(sum(x.get("vcpus_configured") or 0 for x in g))
        smem.append(sum(x.get("memory_used_bytes") or 0 for x in g))
        frac = [x.get("cpu_fraction_raw") or 0.0 for x in g]
        guest_cpu.append(sum(frac))
        if frac:
            heavy_share.append(100.0 * sum(1 for f in frac if f >= 0.30) / len(frac))

    def st(a):
        return (statistics.mean(a), max(a), min(a)) if a else (0, 0, 0)

    bm, bmax, _ = st(busy)
    pm, pmax, _ = st(psome)
    fm, fmax, _ = st(pfull)
    nm, nmax, nmin = st(nrun)
    vm, vmax, _ = st(svcpu)
    mm, mmax, _ = st(smem)
    cm, cmax, _ = st(guest_cpu)
    hs, hsmax, _ = st(heavy_share)

    log("")
    log("| metric | mean | peak |")
    log("|---|---|---|")
    log("| host busy (delta counters) | %.1f%% | %.1f%% |" % (bm, bmax))
    log("| CPU PSI some avg300 | %.1f | %.1f |" % (pm, pmax))
    log("| CPU PSI full avg300 | %.1f | %.1f |" % (fm, fmax))
    log("| running guests | %.1f | %d (min %d) |" % (nm, nmax, nmin))
    log("| sum vCPU configured (running) | %.1f (%.2fx of %d threads) | %d |" % (vm, vm / cpus, cpus, vmax))
    log("| guest memory used | %.1f GiB | %.1f GiB |" % (mm / 2**30, mmax / 2**30))
    log("| guest CPU (sum of fractions, cores) | %.2f | %.2f |" % (cm, cmax))
    log("| heavy share (>=30%% of a vCPU) | %.1f%% | %.1f%% |" % (hs, hsmax))
    log("")
    log("node memory used (window mean): %.1f GiB of %.1f GiB total" % (
        statistics.mean([r["nodes"][0]["memory_used_bytes"] for r in recs]) / 2**30,
        node["memory_total_bytes"] / 2**30))
    log("")
    log("notes: ids are HMAC'd; no business content read; the host runs a mixed VPS +")
    log("container workload (nkx-game-* containers included in the guest list only if")
    log("they appear as qemu guests; lxc guests are excluded by the qemu filter).")

    with open(OUT, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("saved:", OUT)


if __name__ == "__main__":
    main()
