#!/usr/bin/env python3
"""Time-aligned admission toolkit (shared by method_eval_host.py / joint_host.py).

Implements:
  * HistorySampler        - background 1 s cpu.stat sampler for a VMID set
  * demand_from_windows() - empirical censoring-corrected demand estimate
  * phase_profile()       - per-VM demand profile anchored to wall-clock time
  * future_sums()/future_quantile()/future_peak() - predicted aggregate demand
    over the next horizon under each VM's own (stationary) phase
  * decide helpers are kept in the caller; this module stays pure.

Design notes (P0-1/P0-2):
  - The estimator is *empirical*: exact for saturated demand, deliberately
    conservative (upper envelope) for intermittent demand; not a guaranteed
    bound.
  - Admission compares a prediction quantile of the future aggregate demand
    (per-VM phases preserved, candidate VMs capped at their quota) against the
    tenant budget; independence-based baselines (AUDIBLE-style Monte Carlo)
    break under aligned bursts.
  - Consumption-side accounting: shaped VMs contribute min(demand, quota).
"""

from __future__ import annotations

import threading
import time


def _d(u, t, vcpus=1.0):
    """Per-window censoring-corrected demand (empirical estimator)."""
    if t > 0.01:
        return min(vcpus, u / (1.0 - t))
    return min(vcpus, u)


def _recent(series, hist_s):
    if not series:
        return []
    t1 = series[-1][0]
    return [x for x in series if x[0] >= t1 - hist_s]


def demand_from_windows(series, vcpus=1.0, hist_s=300.0, pct=95.0):
    vals = sorted(_d(u, t, vcpus) for (_, u, t) in _recent(series, hist_s))
    if not vals:
        return None
    return vals[min(len(vals) - 1, int(pct / 100.0 * (len(vals) - 1)))]


def phase_profile(series, period_s=60, hist_s=300.0, vcpus=1.0, cap=None):
    """Worst-observed demand per second-of-period bin (anchored to wall clock)."""
    n = int(period_s)
    prof = [0.0] * n
    for ts, u, t in _recent(series, hist_s):
        d = _d(u, t, vcpus)
        if cap is not None:
            d = min(d, cap)
        b = int(ts) % n
        if d > prof[b]:
            prof[b] = d
    return prof


def future_sums(profiles, t0, horizon_s=60):
    """Aggregate demand for each of the next horizon_s seconds."""
    if not profiles:
        return []
    out = []
    for h in range(int(horizon_s)):
        t = int(t0) + h
        out.append(sum(p[t % len(p)] for p in profiles.values()))
    return out


def quantile(vals, q):
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, int(q / 100.0 * (len(s) - 1)))]


def future_quantile(profiles, t0, horizon_s=60, q=90.0):
    return quantile(future_sums(profiles, t0, horizon_s), q)


def future_peak(profiles, t0, horizon_s=60):
    vals = future_sums(profiles, t0, horizon_s)
    return (max(vals), vals.index(max(vals))) if vals else (0.0, 0)


class HistorySampler:
    """Background sampler: one (t, usage_cores, throttled_frac) per second per VMID."""

    def __init__(self, vmids, stat_fn, period=1.0):
        self.vmids = list(vmids)
        self.stat_fn = stat_fn
        self.period = period
        self.series = {v: [] for v in self.vmids}
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        prev = {v: self.stat_fn(v) for v in self.vmids}
        t_prev = time.time()
        while not self._stop.wait(self.period):
            now = time.time()
            dt = max(0.2, now - t_prev)
            for v in self.vmids:
                cur = self.stat_fn(v)
                du = cur.get("usage_usec", 0) - prev[v].get("usage_usec", 0)
                dt_thr = cur.get("throttled_usec", 0) - prev[v].get("throttled_usec", 0)
                u = du / (dt * 1e6)
                th = min(1.0, max(0.0, dt_thr / (dt * 1e6)))
                self.series[v].append((now, u, th))
                prev[v] = cur
            t_prev = now

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def snapshot(self):
        return {v: list(s) for v, s in self.series.items()}

    def history_seconds(self):
        for s in self.series.values():
            if s:
                return s[-1][0] - s[0][0]
        return 0.0
