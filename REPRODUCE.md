# Reproduction Guide

This repository contains the full research artifacts for the paper on safe oversubscription for
small VPS hosts, alongside the rendered paper site (index.html).

## Layout

- `artifacts/tools/` — every experiment driver and analysis script (pure Python 3; the testbed drivers
  target Debian 12 VMs and PVE hosts, the analysis scripts run anywhere):
  - `theory_tests.py` — executable counterexamples for Propositions A/B1/B2/C (Appendix A checks);
  - `ppc_bootstrap.py`, `ppc_multiwindow.py` — empirical PPC forward-prediction protocols;
  - `ppc_sim.py` — parametric PPC simulation (Figure 28);
  - `tb_*.py` — testbed drivers (admission showdown, sell ladders, capmix, qp2/qp2v quota
    verification, zram/FPR/KSM/ioctl/canary/replay);
  - `analyze_*.py`, `certify.py` — statistics (round-level pools, Clopper–Pearson bounds).
- `artifacts/research_data/` — raw run outputs (JSONL, per-request probe raw files) and derived
  reports (PPC_BOOTSTRAP.md, PPC_MULTIWINDOW.md, PRODUCTION_ANALYSIS.md, theory_checks.txt), organized
  by testbed (`phys8269_pilot/`, `berohost_pilot/`, `v2_analysis/`, `vps2_readonly/`, `azure/`).

## One-minute checks

```bash
python3 artifacts/tools/theory_tests.py          # Appendix A constructions (seconds)
python3 artifacts/tools/analyze_sell_pool.py     # pooled ladder P5 table (Section 8.4)
python3 artifacts/tools/ppc_multiwindow.py       # 5-window forward prediction (Section 8.6)
```

## Regenerating the figures

The figure scripts live in the paper source (`manuscript/figs/`, included in the deployment source,
not duplicated here). They read only files under `artifacts/research_data/` and write PNGs:

```bash
python3 manuscript/figs/make_figs.py        # Figures 2-9
python3 manuscript/figs/make_v2_figs.py     # Figures 17-19, 29
python3 manuscript/figs/make_phys_figs.py   # Figures 14-16
python3 manuscript/figs/make_law_figs.py    # Figure 21
python3 manuscript/figs/make_showdown_fig.py# Figure 20
python3 manuscript/figs/make_phasec_figs.py # Figures 22-26, 30
```

## Data notes

- Testbed experiments ran on two self-operated hosts (a 4-vCPU nested PVE host and a 96-thread
  bare-metal host with a 64-VM fleet); drivers are included for inspection, and their outputs are the
  archived JSONL/raw files.
- Production telemetry (host-side, read-only) is anonymized (HMAC'd identifiers); only aggregate
  statistics are released.
- Measurement-window discipline: throughput comparisons restart the measurement window per config and
  cross-check cgroup delivery (`tb_qp2v.py` documents the fixed protocol; see Section 9.1 for the
  self-audit that motivated it).
