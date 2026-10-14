# Paper — Safe Oversubscription for Small VPS Hosts (research draft v1.0)

This repository hosts the rendered paper site **and the full research artifacts**.

## Read the paper
- `index.html` — the paper, Chinese edition (with figures)
- `index-en` — the paper, English edition (same figures, English captions; linked from both pages)
- `changelog` / `changelog.html` — version history (current: v1.0)
- `report.html`, `report.pptx`, `paper.pptx` — talk slides (HTML / PPT)

## Reproduce the research (artifacts/)
- **`REPRODUCE.md`** — one-minute checks and figure regeneration guide
- **`artifacts/tools/`** — every experiment driver and analysis script, including:
  - `theory_tests.py` — executable counterexamples for the Appendix-A propositions (Propositions A/B1/B2/C)
  - `p5_convention_check.py` — customer-P5 metric-convention robustness (the sync-8 boundary is convention-invariant; the random end is 28→26 under the strictest)
  - `ppc_bootstrap.py`, `ppc_multiwindow.py`, `ppc_sim.py` — the three PPC artifacts (empirical forward prediction / parametric / online actuator)
  - `tb_*.py` — testbed drivers: admission showdown (including `ours_full`, the full Algorithm-A chain, with `--no-censor`/`--no-phase`/`--quota-pct`/`--guard-metric` ablation switches), sell ladders, censoring campaigns, quota self-audit (`tb_qp2v.py`), zram/FPR/KSM/ioctl/canary/replay
  - `analyze_*.py`, `certify.py`, `bootstrap_ci.py` — statistics (round-level pools, bootstrap CIs, Clopper–Pearson bounds)
- **`artifacts/research_data/`** — raw run outputs (JSONL + per-request probe raw files, ~62 MB) and derived reports, organized by testbed
- **`artifacts/figs/`** — the figure-generation scripts (they read only `artifacts/research_data/`)

## Status (v1.0, 2026-10-14)
- All core campaigns complete and merged (physical host: sell ladders, showdown 14 rounds + repeat batches, boundary fine scans, replay; second testbed: v3 rework batches; production telemetry analysis).
- Self-audit corrections are documented: the micro-period "+35%" throughput claim was a measurement artifact and is withdrawn (Section 9.1).
- A queued batch of strengthening experiments (full-chain `ours_full` runs, censoring/quota ablations, dense 1-second customer-rate sampling, strict-metric guard arm) is executing on the physical testbed; results will be merged as they land.
- Positioning: a measurement-driven applied-systems study; the strongest claims rest on the two testbeds, the production replay, and the round-level statistics reported in the paper.

## Layout of this repository
- Site files (`index.html`, `changelog.html`, `report.*`, `figs/`) are auto-generated from the paper sources by the deployment script.
- The paper sources (chapters, figure scripts, build scripts) live in the private working tree; everything needed to verify the reported results is published here under `artifacts/`.
