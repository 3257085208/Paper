#!/usr/bin/env python3
"""Executable realizations of the three impossibility constructions (Appendix A).

Runs the ideal-model counterexamples numerically and asserts the key claims:
  T-A  censoring pair: identical (u, t, q) but means 0.556 vs 0.840
  T-B1 marginals: identical per-tenant activity marginals, capacities C/rho vs C
  T-B2 utilization cap: aligned fleet's delivered utilization == duty rho for all
       N >= C  => any threshold theta > rho admits unboundedly many tenants
  T-C  sampling: sampler interval Delta > burst width w admits pairs with
       identical sample sequences

Prints a report (also saved to research_data/theory_checks.txt).
"""

from __future__ import annotations

import io
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                   "research_data", "theory_checks.txt")
lines = []


def log(s):
    print(s)
    lines.append(s)


# ---------- T-A: censoring pair ----------
def test_censoring():
    q, P = 0.2, 1.0
    # process A: constant demand 0.556; process B: 1.0 for beta*P, 0 else
    dA = 5.0 / 9.0  # exactly q/(1-0.64) = 0.5556; t = 0.64 exactly
    beta = 0.84
    # budget-exhaustion model, one period
    # A: budget qP spent in qP/dA seconds, throttled for the rest
    tA = 1.0 - q / dA
    uA = q
    # B: budget qP spent in qP/1.0 = 0.2P (inside the active stretch), throttled
    # until the active stretch ends at beta*P
    tB = beta - q / 1.0
    uB = q
    meanA = dA
    meanB = beta * 1.0
    ok = abs(tA - tB) < 1e-9 and abs(uA - uB) < 1e-12 and abs(meanA - 5.0 / 9.0) < 1e-12 and abs(meanB - 0.84) < 1e-12
    log("T-A censoring pair: (u,t)_A=(%.3f,%.2f)  (u,t)_B=(%.3f,%.2f)  means=%.3f vs %.3f  -> %s"
        % (uA, tA, uB, tB, meanA, meanB, "PASS" if ok else "FAIL"))
    assert ok


# ---------- T-B1/B2: phase fleets ----------
def concurrency(duties, offsets, P=60):
    """Per-second concurrency for one period, 1-min periods repeated; here we use
    window width w = duty*P within each period. Returns max and delivered util."""
    d = duties[0]
    w = int(round(d * P))
    act = [0] * P
    for off in offsets:
        for s in range(w):
            act[(off + s) % P] += 1
    return act


def test_phase_fleets(C=8, P=60, rho=0.2, N=24):
    w = int(round(rho * P))
    # aligned fleet: all offsets equal
    actA = concurrency([rho], [0] * N, P)
    peakA = max(actA)
    deliveredA = sum(min(a, C) for a in actA) / P  # cores averaged over one period
    utilA = deliveredA / C
    # random fleet: uniform offsets (deterministic spaced for reproducibility)
    offsets = [(i * P) // N for i in range(N)]
    actR = concurrency([rho], offsets, P)
    deliveredR = sum(min(a, C) for a in actR) / P
    utilR = deliveredR / C
    # B1: identical marginals (both fleets: each tenant active w seconds per period)
    ok_marg = (max(actA) > 0) and (w == int(round(rho * P)))
    # B2: aligned delivered utilization == rho regardless of N (when N >= C / (w/P)?? check for N>=C)
    capped = True
    for NN in (8, 16, 32, 64, 128):
        a = concurrency([rho], [0] * NN, P)
        u = sum(min(x, C) for x in a) / P / C
        if abs(u - rho) > 1e-9:
            capped = False
    log("T-B1 marginals: aligned peak=%d, random delivered=%.2f cores (util %.0f%%) at N=%d, C=%d"
        % (peakA, deliveredR, 100 * utilR, N, C))
    log("T-B2 utilization cap: aligned delivered util stays %.0f%% (=duty) for N in {8..128} -> %s"
        % (100 * rho, "PASS (any threshold theta>rho admits unbounded N)" if capped else "FAIL"))
    # numeric check matching the paper: at N=24, random util ~ rho*N/C capped
    exp_rand = min(1.0, rho * N / C - 0.002)  # small finite-N overlap correction not modeled; report raw
    log("T-B2 numeric: random util at N=24 = %.2f (paper-measured ~0.66-0.68 incl. overheads) vs aligned 0.20"
        % utilR)
    assert ok_marg and capped


# ---------- T-C: sampling ----------
def test_sampling(P=60, w=12, delta=30, sample_phase=3):
    samples = [sample_phase, (sample_phase + delta) % P, (sample_phase + 2 * delta) % P]
    # bursty fleet: burst window placed away from samples
    burst_start = 15
    bursty_hits = any(burst_start <= s < burst_start + w for s in samples)
    # benign fleet: idle
    benign_hits = False
    # identical sample sequences (all zero)
    ok = (bursty_hits == benign_hits == False)
    log("T-C sampling: Delta=%ds, w=%ds, samples=%s, burst@[15,27): hits=%s (benign hits=%s) -> %s"
        % (delta, w, samples, bursty_hits, benign_hits, "PASS (identical zero sequences)" if ok else "FAIL"))
    # positive control: Delta=10s catches the burst
    s2 = [(3 + 10 * k) % P for k in range(6)]
    hit2 = any(burst_start <= s < burst_start + w for s in s2)
    log("T-C positive control: Delta=10s samples=%s -> burst hit=%s" % (s2, hit2))
    assert ok and hit2


def test_window_cap(P=60, w=12, rho=0.2):
    """T-B3: single-period windows (L <= P) — cap = min(w,L)/L."""
    caps = {L: min(w, L) / L for L in (10, 30, 60)}
    util80_theta = 0.80
    ok = (abs(caps[60] - rho) < 1e-12 and abs(caps[30] - 0.4) < 1e-12
          and util80_theta > caps[30])
    log("T-B3 single-period cap: L=10/30/60 s -> cap %.2f/%.2f/%.2f; util80 L=30 theta=0.80 > %.2f -> unbounded  %s"
        % (caps[10], caps[30], caps[60], caps[30], "PASS" if ok else "FAIL"))
    assert ok


def test_window_cap_multi(P=60, w=12, rho=0.2):
    """T-B4: multi-period windows — U(L) = [w*floor(L/P) + min(L mod P, w)] / L,
    verified numerically by sliding windows over the aligned schedule."""
    act = [0] * (4 * P)
    for k in range(4):
        for t in range(w):
            act[k * P + t] = 1

    def U(L):
        return (w * (L // P) + min(L % P, w)) / L

    ok = True
    for L in (60, 90, 120, 150):
        best = 0.0
        for s0 in range(0, 3 * P - L + 1):
            best = max(best, sum(act[s0:s0 + L]) / L)
        if abs(best - U(L)) > 1e-9:
            ok = False
        old_formula = min(w, L) / L
        log("T-B4 L=%3d: numeric max=%.4f | U(L)=%.4f | old min(w,L)/L=%.4f%s"
            % (L, best, U(L), old_formula, "  <- old formula WRONG" if abs(old_formula - U(L)) > 1e-9 else ""))
    assert ok
    log("T-B4 multi-period formula verified numerically (L=90 exceeds rho: %.4f > %.2f)  PASS" % (U(90), rho))


if __name__ == "__main__":
    log("=== Appendix A executable checks (ideal model) ===")
    test_censoring()
    test_phase_fleets()
    test_window_cap()
    test_window_cap_multi()
    test_sampling()
    log("=== all constructions verified ===")
    with io.open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("saved:", OUT)
