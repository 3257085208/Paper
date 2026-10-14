#!/usr/bin/env python3
"""fig31: 39-hour light-window production anchor (host busy, mem available, PSI)."""
import json, os, statistics
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from datetime import datetime

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SRC = os.path.join(BASE, "research_data", "vps2_readonly", "pve_host_light.jsonl")
OUT = os.path.join(BASE, "manuscript", "figs", "fig31_light_window.png")

rows = [json.loads(l) for l in open(SRC)]
t0 = datetime.fromisoformat(rows[0]["timestamp_utc"])
T, busy, mem, psi = [], [], [], []
prev_ts = None
for a, b in zip(rows, rows[1:]):
    ca, cb = a["host_cpu_counters"], b["host_cpu_counters"]
    dt = cb["total"] - ca["total"]
    if dt <= 0:
        continue
    ts = datetime.fromisoformat(b["timestamp_utc"])
    if prev_ts is not None and (ts - prev_ts).total_seconds() > 900:
        T.append((ts - t0).total_seconds() / 3600.0)
        busy.append(None); mem.append(None); psi.append(None)
    prev_ts = ts
    t = (ts - t0).total_seconds() / 3600.0
    T.append(t)
    busy.append(100.0 * (1 - (cb["idle"] - ca["idle"]) / dt))
    mem.append(b["mem_available_bytes"] / 2**30)
    psi.append(b["host_cpu_pressure"]["some"]["avg300"])

fig, axes = plt.subplots(1, 2, figsize=(11, 3.6))
ax = axes[0]
ax.plot(T, busy, "-", color="tab:blue", linewidth=1.2)
ax.axhline(statistics.mean([x for x in busy if x is not None]), color="tab:blue", linestyle=":", linewidth=0.9)
ax.text(1, statistics.mean([x for x in busy if x is not None]) + 1.5, "mean %.1f%%" % statistics.mean([x for x in busy if x is not None]), fontsize=8)
# dense 3h window: 2026-10-11 13:03-16:05 UTC -> hours 25.0-28.0
ax.axvspan(25.0, 28.0, color="tab:orange", alpha=0.25)
ax.text(25.2, 62, "dense 3 h\nexcerpt (night)", fontsize=8, color="tab:orange")
ax.set_xlabel("hours since window start (2026-10-12 12:05 UTC)")
ax.set_ylabel("host busy (%)")
ax.set_title("39-h light anchor: host busy (mean %.1f%%, peak %.0f%%)" % (
    statistics.mean([x for x in busy if x is not None]), max(x for x in busy if x is not None)), fontsize=9.5)
ax.grid(alpha=0.25)
ax2 = axes[1]
ax2.plot(T, mem, "-", color="tab:green", linewidth=1.2, label="mem available (GB)")
ax2.set_ylabel("mem available (GB)", color="tab:green")
ax2.tick_params(axis="y", labelcolor="tab:green")
ax2.set_xlabel("hours since window start")
ax3 = ax2.twinx()
ax3.plot(T, psi, "-", color="tab:red", linewidth=1.0, alpha=0.7, label="CPU PSI some avg300")
ax3.set_ylabel("CPU PSI some avg300 (%)", color="tab:red")
ax3.tick_params(axis="y", labelcolor="tab:red")
ax2.set_title("memory never stressed (min %.0f GB); CPU PSI mean %.1f%%" % (
    min([x for x in mem if x is not None]), statistics.mean([x for x in psi if x is not None])), fontsize=9.5)
ax2.grid(alpha=0.25)
fig.suptitle("Production anchor (LEC-HK-1): 39-h light window vs the 3-h dense excerpt", fontsize=10)
fig.tight_layout()
fig.savefig(OUT, dpi=200)
print("fig31 ok; busy mean %.1f p95 %.1f max %.1f | mem min %.1f | psi mean %.1f max %.1f" % (
    statistics.mean([x for x in busy if x is not None]), sorted([x for x in busy if x is not None])[int(0.95*(len([x for x in busy if x is not None])-1))], max([x for x in busy if x is not None]),
    min([x for x in mem if x is not None]), statistics.mean([x for x in psi if x is not None]), max([x for x in psi if x is not None])))
