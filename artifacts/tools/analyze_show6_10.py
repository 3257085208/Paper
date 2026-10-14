#!/usr/bin/env python3
"""Analysis of the completed show6-show10 batches (runs on the Mac).

Covers: show6 order-seed repeat (12 runs), show7 ours_full end-to-end,
show8 quota/no-censor/no-phase ablations, show9 dense-sampling sell ladders,
show10 guard-metric sensitivity. Reference stops come from the local show5
(sync) and show2/admit (rand) files.

Primary QoS bar (pre-declared): service P99 <= 10 ms AND customer rate P5 >= 70%
of solo baseline. Writes research_data/phys8269_pilot/SHOW6_10_SUMMARY.md.
"""

from __future__ import annotations

import glob
import json
import os
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "..", "research_data", "phys8269_pilot")
BASE_RATE = 25.9e6
SLO = 10.0
PRIMARY = 70.0
lines = []


def log(s):
    print(s)
    lines.append(s)


def load(fn):
    return [json.loads(l) for l in open(fn)]


def rate_of(r):
    return r.get("max_rate", r.get("rate"))


def p5_time(rec):
    """Per-customer time-P5 then cross-customer P5 (median convention)."""
    vals = []
    for r in rec.get("rates", []):
        rs = [v for v in (r.get("series") or []) if v]
        if not rs and rate_of(r):
            rs = [rate_of(r)]
        if rs:
            rs = sorted(rs)
            vals.append(rs[int(0.05 * (len(rs) - 1))])
    if not vals:
        return None
    vals = sorted(vals)
    return vals[int(0.05 * (len(vals) - 1))] / BASE_RATE * 100.0


def ok(rec):
    svc = not rec.get("svc_viol", False)
    p5 = p5_time(rec)
    if p5 is None:
        return svc and not rec.get("cust_viol_main", rec.get("cust_viol", False)), None
    return svc and p5 >= PRIMARY, p5


def stops(fn):
    """(stop_n, first_violating_n, p5_at_stop, svc_at_stop)."""
    recs = sorted(load(fn), key=lambda r: r["n"])
    stop = 0
    p5s = None
    first_bad = None
    for rec in recs:
        good, p5 = ok(rec)
        if good:
            stop = rec["n"]
            p5s = p5
        elif first_bad is None:
            first_bad = rec["n"]
            break
    return stop, first_bad, p5s


def table_stops(title, files):
    log("")
    log("### " + title)
    log("")
    log("| run | stop N | first violating N | P5 at stop |")
    log("|---|---|---|---|")
    for label, fn in files:
        s, fb, p5 = stops(fn)
        log("| %s | %d | %s | %s |" % (label, s, fb if fb else "-",
                                        ("%.1f%%" % p5) if p5 is not None else "-"))


def main():
    log("# show6-show10 batch analysis (primary bar: service P99 <= 10 ms, customer P5 >= 70%)")

    # ---------- show6: order-seed repeat ----------
    log("")
    log("## show6: arrival-order repeat (order-seed 42, 12 runs)")
    files = []
    for fn in sorted(glob.glob(os.path.join(BASE, "admit_show6_sync_*.jsonl"))):
        pol = os.path.basename(fn).replace("admit_show6_sync_", "").replace(".jsonl", "")
        files.append(("sync %s" % pol, fn))
    for fn in sorted(glob.glob(os.path.join(BASE, "admit_show6_rand_*.jsonl"))):
        pol = os.path.basename(fn).replace("admit_show6_rand_", "").replace(".jsonl", "")
        files.append(("rand %s" % pol, fn))
    table_stops("show6 stops (seed 42)", files)

    # reference: show5 sync + show2/admit rand
    ref = []
    for fn in sorted(glob.glob(os.path.join(BASE, "show5", "admit_show5_sync_*.jsonl"))):
        pol = os.path.basename(fn).replace("admit_show5_sync_", "").replace(".jsonl", "")
        ref.append(("sync %s (show5)" % pol, fn))
    rand_seen = set()
    for pat in ("admit_show2_rand_*.jsonl", "admit_admit_rand_*.jsonl"):
        for fn in sorted(glob.glob(os.path.join(BASE, pat))):
            pol = os.path.basename(fn).split("_rand_", 1)[1].replace(".jsonl", "")
            if pol in rand_seen:
                continue
            rand_seen.add(pol)
            ref.append(("rand %s (ref)" % pol, fn))
    table_stops("reference stops (show5 sync, show2/admit rand)", ref)

    # ---------- show7: ours_full ----------
    log("")
    log("## show7: full-chain controller (ours_full)")
    files = []
    for fn in sorted(glob.glob(os.path.join(BASE, "admit_show7_*.jsonl"))):
        nm = os.path.basename(fn).replace("admit_show7_", "").replace(".jsonl", "")
        files.append((nm, fn))
    table_stops("show7 stops", files)

    # ---------- show8: ablations ----------
    log("")
    log("## show8: component ablations (quota 80% / no-censor / no-phase)")
    files = []
    for fn in sorted(glob.glob(os.path.join(BASE, "admit_show8_*.jsonl"))):
        nm = os.path.basename(fn).replace("admit_show8_", "").replace(".jsonl", "")
        files.append((nm, fn))
    table_stops("show8 stops", files)

    # ---------- show9: dense ladders ----------
    log("")
    log("## show9: dense-sampling sell ladders (1 s sampling)")
    for fn in ("sell_sell_sync_dense.jsonl", "sell_sell_rand_dense.jsonl"):
        path = os.path.join(BASE, fn)
        if not os.path.exists(path):
            continue
        recs = load(path)
        log("")
        log("| %s | level | svc P99 (ms) | customer P5 | customer P5 (max-rate conv.) |" % fn)
        log("|---|---|---|---|---|")
        for rec in sorted(recs, key=lambda r: r["level"]):
            http_p99 = rec["http"]["p99_ms"]
            # dense convention: per-customer time-P5 over 1-s series, cross-customer P5
            cust = {}
            for rnd in rec.get("rate_rounds", []):
                for vmid, rate, st in rnd:
                    if st and rate:
                        cust.setdefault(vmid, []).append(rate)
            p5s = []
            maxs = []
            for vmid, rs in cust.items():
                rs = sorted(rs)
                p5s.append(rs[int(0.05 * (len(rs) - 1))])
                maxs.append(rs[-1])
            p5s.sort()
            maxs.sort()
            p5 = p5s[int(0.05 * (len(p5s) - 1))] / BASE_RATE * 100 if p5s else None
            p5max = maxs[int(0.05 * (len(maxs) - 1))] / BASE_RATE * 100 if maxs else None
            log("| | %d | %.3f | %s | %s |" % (
                rec["level"], http_p99,
                ("%.1f%%" % p5) if p5 is not None else "-",
                ("%.1f%%" % p5max) if p5max is not None else "-"))

    # ---------- show10: guard metric ----------
    log("")
    log("## show10: guard-metric sensitivity (median guard)")
    files = []
    for fn in sorted(glob.glob(os.path.join(BASE, "admit_show10_*.jsonl"))):
        nm = os.path.basename(fn).replace("admit_show10_", "").replace(".jsonl", "")
        files.append((nm, fn))
    table_stops("show10 stops", files)

    out = os.path.join(BASE, "SHOW6_10_SUMMARY.md")
    with open(out, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("saved:", out)


if __name__ == "__main__":
    main()
