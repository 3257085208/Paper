#!/usr/bin/env python3
"""Executable counterexamples: control history creates hidden work state (research notes).

Ideal-model checks for the "same telemetry, same true demand, different future" claim:
  T-CH1 debt invisibility   : under any probe budget q' < a, replaceable (latest-state)
                              and persistent (FIFO backlog) workloads have identical
                              delivered/throttle traces although the persistent one
                              accumulates hidden debt K*(a-q)
  T-CH2 probe amplitude     : distinguishing the two semantics requires probe budget
                              q' > a; if the safe cap q_safe < a, no allowed probe
                              distinguishes them (identifiability vs safe margin)
  T-CH3 recovery drain time : after release to q_rel = 1.0, the persistent workload
                              stays saturated for ~3K periods (drain 0.2/period)
  T-CH4 same demand,        : with no quota from t=0 both semantics deliver identical
        different future      0.8-duty traces; after the same quota history and the
                              same release action, their future activity differs

These are model-level statements for the workload family defined here; they are not
claims about arbitrary applications or real P99 behaviour (that needs the testbed).
"""

from __future__ import annotations

import io
import math
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                   "research_data", "control_history_checks.txt")
lines = []
TOL = 1e-9


def log(s):
    print(s)
    lines.append(s)


def sim(a, q_seq, K_debt=0):
    """Discrete per-period model. a: arrival CPU-s/period; q_seq: budget per period.
    Returns (delivered_A, delivered_B, backlog_B_trace). B starts with hidden debt K_debt."""
    dA, dB, B = [], [], float(K_debt)
    for q in q_seq:
        dA.append(min(a, q))
        B += a
        d = min(B, q)
        dB.append(d)
        B -= d
    return dA, dB, B


def close(x, y):
    return abs(x - y) < 1e-9


# ---------- T-CH1: debt invisibility ----------
def test_debt_invisibility(a=0.8, q=0.2, K=10):
    dA, dB, B_end = sim(a, [q] * K)
    identical = all(close(x, y) for x, y in zip(dA, dB))
    debt = K * (a - q)
    ok = identical and close(B_end, debt)
    log("T-CH1 debt invisibility: q=%.2f K=%d  delivered A==B: %s  hidden debt=%.2f CPU-s  -> %s"
        % (q, K, identical, debt, "PASS" if ok else "FAIL"))
    assert ok


# ---------- T-CH2: probe amplitude boundary ----------
def test_probe_amplitude(a=0.8, q=0.2, K=10, q_safe=0.5):
    hist = [q] * K
    probes = [0.2, 0.5, 0.79, 0.9, 1.0]
    rows = []
    for qp in probes:
        # hidden state: A has none; B carries the debt from the same history
        dA, dB, _ = sim(a, hist + [qp])
        rows.append((qp, dA[-1], dB[-1], not close(dA[-1], dB[-1])))
    # separation only when the probe budget exceeds the arrival rate
    sep_lo = all(not r[3] for r in rows if r[0] < a)
    sep_hi = all(r[3] for r in rows if r[0] > a)
    ok = sep_lo and sep_hi
    for qp, da, db, sep in rows:
        log("T-CH2 probe q'=%.2f: delivered A=%.2f B=%.2f  distinguishable=%s"
            % (qp, da, db, sep))
    log("T-CH2 boundary: no probe with q'<a separates; q'>a separates (min amplitude = a = %.2f)  -> %s"
        % (a, "PASS" if ok else "FAIL"))
    log("T-CH2 safe-margin corollary: if the safe cap is %.2f < a = %.2f, no allowed probe is informative  -> %s"
        % (q_safe, a, "PASS" if q_safe < a else "FAIL"))
    assert ok and q_safe < a


# ---------- T-CH3: recovery drain time ----------
def test_drain_time(a=0.8, q=0.2, K=10, q_rel=1.0, horizon=60):
    dA, dB, _ = sim(a, [q] * K + [q_rel] * horizon)
    tailA = dA[K:]
    tailB = dB[K:]
    # A returns to a immediately; B saturated (q_rel) until the debt is drained
    drain = 0
    for d in tailB:
        if d > a + TOL:
            drain += 1
        else:
            break
    debt = K * (a - q)
    expected = int(math.ceil(round(debt / (q_rel - a), 6)))
    ok = close(tailA[0], a) and drain == expected
    log("T-CH3 drain: debt=%.1f CPU-s  drain periods B=%d (expected %d = 3K)  A first released period=%.2f  -> %s"
        % (debt, drain, expected, tailA[0], "PASS" if ok else "FAIL"))
    assert ok


# ---------- T-CH4: same true demand, different future ----------
def test_same_demand_different_future(a=0.8, q=0.2, K=10, horizon=40):
    # no quota from t=0: both semantics deliver identical duty-a traces
    free_A, free_B, _ = sim(a, [1.0] * horizon)
    same_free = all(close(x, y) for x, y in zip(free_A, free_B))
    # same quota history, same release action: futures differ
    dA, dB, _ = sim(a, [q] * K + [1.0] * horizon)
    futA = dA[K:]
    futB = dB[K:]
    diff = sum(1 for x, y in zip(futA, futB) if not close(x, y))
    dutyA = sum(1 for x in futA if close(x, a))
    satB = sum(1 for x in futB if x > a + TOL)
    ok = same_free and diff > 0 and dutyA >= horizon - 1 and satB >= 20
    log("T-CH4 no-quota traces identical: %s; after identical history+release, futures differ in %d/%d periods"
        % (same_free, diff, horizon))
    log("T-CH4 released future: A duty-%.1f periods=%d, B saturated periods=%d  -> %s"
        % (a, dutyA, satB, "PASS" if ok else "FAIL"))
    assert ok


def main():
    log("control-history executable counterexamples (ideal model, P=1 s, a=0.8 CPU-s/period)")
    test_debt_invisibility()
    test_probe_amplitude()
    test_drain_time()
    test_same_demand_different_future()
    with io.open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("saved:", OUT)


if __name__ == "__main__":
    main()
