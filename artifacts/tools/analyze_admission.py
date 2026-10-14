#!/usr/bin/env python3
"""Admission showdown analysis (runs on the Mac).

Reads research_data/phys8269_pilot/admit_<phase>_<policy>*.jsonl and the
sell-capacity ladders, and reports — under the pre-declared primary QoS bar
(service P99 <= 10 ms AND customer rate P5 >= 70% of solo baseline):

  * per policy x phase: stopped N, first violating N, safety at stop
  * oracle capacity from the sell ladders at 50/70/90% bars
  * efficiency vs oracle (seats left on the table / oversold)
  * matched-density table (P5 and service status for N in 8..40)

Usage: python3 analyze_admission.py
"""

from __future__ import annotations

import glob
import json
import os
import statistics

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                    "research_data", "phys8269_pilot")
BASE_RATE = 25.9e6
SLO = 10.0
POLICIES = ["fixed", "util80", "quantile", "audible", "ours"]
PHASES = ["rand", "sync"]
PRIMARY = 70.0


def load_admit(phase, policy):
    """Prefer the rich-metric v2 runs (show_*) over the legacy ones."""
    patterns = ["admit_show2_%s_%s*.jsonl" % (phase, policy),
                "admit_show_%s_%s*.jsonl" % (phase, policy),
                "admit_admit_%s_%s*.jsonl" % (phase, policy)]
    for pat in patterns:
        files = [f for f in sorted(glob.glob(os.path.join(BASE, pat)))
                 if "zramcontam" not in f]
        if files:
            rows = []
            for fn in files:
                for line in open(fn):
                    o = json.loads(line)
                    o["_file"] = os.path.basename(fn)
                    rows.append(o)
            return rows
    return []


def _rate(r):
    return r.get("max_rate", r.get("rate"))


def step_p5(rec):
    rates = rec.get("rates")
    if not rates:
        return None
    vals = sorted(_rate(r) / BASE_RATE * 100 for r in rates if _rate(r))
    if not vals:
        return None
    return vals[int(0.05 * (len(vals) - 1))]


def step_p50(rec):
    rates = rec.get("rates")
    if not rates:
        return None
    vals = sorted(_rate(r) / BASE_RATE * 100 for r in rates if _rate(r))
    if not vals:
        return None
    return statistics.median(vals)


def step_summary(rec):
    p5 = step_p5(rec)
    p50 = step_p50(rec)
    svc_ok = not rec.get("svc_viol")
    if p5 is not None:
        primary_ok = svc_ok and p5 >= PRIMARY
    else:
        # legacy records: only the 50% floor was recorded
        primary_ok = svc_ok and (rec.get("cust_slow", 0) == 0)
    return {"n": rec["n"], "svc_p99": rec.get("http_p99"),
            "svc_ok": svc_ok, "p5": p5, "p50": p50,
            "primary_ok": primary_ok, "busy": rec.get("busy_pct"),
            "legacy": p5 is None,
            "cust_slow": rec.get("cust_slow"), "cust_active": rec.get("cust_active")}


def sell_ladder(files):
    merged = {}
    for fn in files:
        p = os.path.join(BASE, fn)
        if not os.path.exists(p):
            continue
        for line in open(p):
            o = json.loads(line)
            per = {}
            for rnd in o.get("rate_rounds") or []:
                for vmid, rate, state in rnd:
                    if rate and state == 1:
                        per[vmid] = max(per.get(vmid, 0), rate)
            if per:
                merged.setdefault(o["level"], []).extend(x / BASE_RATE * 100 for x in per.values())
    out = {}
    for lvl, vals in merged.items():
        vals = sorted(vals)
        out[lvl] = {"p50": statistics.median(vals),
                    "p5": vals[int(0.05 * (len(vals) - 1))], "n": len(vals)}
    return out


def oracle(ladder, bar):
    ok = None
    for lvl in sorted(ladder):
        if ladder[lvl]["p5"] >= bar:
            ok = lvl
        else:
            break
    return ok


def main():
    # NOTE: sell_sell_rand_r3 used descending level labels but tb_sell only adds
    # tenants, so all its labels after the first are invalid; it is kept out of the
    # ladder (usable as a long-dwell-at-64 sample).
    rand_ladder = sell_ladder(["sell_sell_rand.jsonl", "sell_sell_rand_r2.jsonl"])
    sync_ladder = sell_ladder(["sell_sell_sync.jsonl", "sell_sell_sync_r2.jsonl"])
    oracles = {p: {bar: oracle(l, bar) for bar in (50, 70, 90)}
               for p, l in (("rand", rand_ladder), ("sync", sync_ladder))}

    print("== Oracles (sell ladders, P5 bars) ==")
    for p, l in (("rand", rand_ladder), ("sync", sync_ladder)):
        print("  %s: levels=%s oracle(P5>=50)=%s oracle(P5>=70)=%s oracle(P5>=90)=%s" %
              (p, sorted(l), oracles[p][50], oracles[p][70], oracles[p][90]))

    print()
    print("== Showdown (primary bar: service P99<=10 ms AND customer P5>=%d%%) ==" % PRIMARY)
    hdr = "%-9s %-5s %5s %6s %6s %8s %8s  %s" % (
        "policy", "phase", "stop", "1stBad", "clean", "p5@stop", "svc@stop", "note")
    print(hdr)
    results = {}
    for phase in PHASES:
        for policy in POLICIES:
            rows = load_admit(phase, policy)
            if not rows:
                continue
            steps = [step_summary(r) for r in rows]
            stop = steps[-1]["n"]
            first_bad = next((s["n"] for s in steps if not s["primary_ok"]), None)
            clean = first_bad is None
            last = steps[-1]
            note = ""
            if last["legacy"]:
                note = "legacy(no rates)"
            elif any(s["legacy"] for s in steps):
                note = "mixedFormat"
            if stop >= 40:
                note = (note + " cap40").strip()
            results[(phase, policy)] = {"stop": stop, "first_bad": first_bad,
                                        "clean": clean, "steps": steps}
            print("%-9s %-5s %5d %6s %6s %8s %8s  %s" % (
                policy, phase, stop, first_bad if first_bad else "-",
                "yes" if clean else "NO",
                "%.0f%%" % last["p5"] if last["p5"] else "-",
                last["svc_p99"], note))

    print()
    print("== Efficiency vs oracle (P5>=70%% bar) ==")
    for phase in PHASES:
        o = oracles[phase][70]
        for policy in POLICIES:
            r = results.get((phase, policy))
            if not r:
                continue
            verdict = "safe-stop" if r["clean"] else "violated"
            delta = (r["stop"] - o) if o else None
            print("  %-5s %-9s stop=%d oracle=%s delta=%s (%s)" %
                  (phase, policy, r["stop"], o, delta, verdict))

    print()
    print("== Matched density (where data exists) ==")
    for phase in PHASES:
        print("  phase=%s" % phase)
        for n in (8, 16, 24, 32, 40):
            cells = []
            for policy in POLICIES:
                r = results.get((phase, policy))
                if not r:
                    continue
                s = next((s for s in r["steps"] if s["n"] == n), None)
                if s is None:
                    continue
                if s["p5"] is not None:
                    cells.append("%s:p5=%.0f%s" % (policy, s["p5"],
                                                   "" if s["primary_ok"] else "!"))
                else:
                    cells.append("%s:slow=%s/%s" % (policy, s["cust_slow"], s["cust_active"]))
            if cells:
                print("    n=%2d  %s" % (n, "  ".join(cells)))

    with open(os.path.join(BASE, "admit_summary.json"), "w") as fh:
        json.dump({("%s_%s" % k): {kk: vv for kk, vv in v.items() if kk != "steps"}
                   for k, v in results.items()}, fh, indent=1)
    print("\nsummary written to admit_summary.json")


if __name__ == "__main__":
    main()
