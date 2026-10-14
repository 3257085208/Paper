# 6 Implementation and Testbed

## 6.1 Testbed

The testbed is a nested host isomorphic to small-provider production: Proxmox VE 8.4.21 (Debian 12 base) running inside a KVM guest (`systemd-detect-virt = kvm`; `/dev/kvm` and `vmx/svm` both available), reporting 4 vCPUs (AMD EPYC 9575F), 19.5 GiB of RAM, one 200 GB virtual disk (cgroup accounting device 8:0), and 1 GB of swap. Ballooning is disabled by default (the return-vs-no-compression tradeoff, Section 4.4.4). The host's idle baseline is 2–4% busy; all background noise is removed during experiments (a local monitoring agent and per-VM apt/man-db/fstrim timers are disabled).

Load topology: 2 service VMs (HTTP/nginx, Redis; 1 vCPU / 1 GiB each), 1 probe VM, and 16 customer VMs (1 vCPU, 3072 MiB; some earlier experiments used 1024/5120 MiB, noted per section). All VMs are clones of one Debian 12 cloud template (cloud-init injects networking and keys); customer VMs carry no persistent agents.

## 6.2 Toolchain (all scripts submitted with the paper)

| Script | Purpose |
|---|---|
| `tools/probe.py` | Open-loop fixed-rate probe: per-request planned/actual send times, connect and total latency, timeouts/errors; JSON summary + raw CSV |
| `tools/burner.py` | Programmable tenant load: duty cycle / period / phase (random, wall-clock aligned); writes rate/state locally |
| `tools/ballast.py` | Progressive memory allocation (step/interval/target), reports residency |
| `tools/sweep.sh` | Neighbor sweep (0–5, randomized order, host busy + dual-service probes) |
| `tools/analyze_curve.py` / `analyze_packing.py` / `analyze_admission.py` / `analyze_shaping.py` | Per-experiment summaries and timelines |
| `tools/admission_pilot.py` | Admission closed loop (arrivals, decisions, execution, measured windows) |
| `tools/shaping_pilot.py` / `shaping_host.py` | Shaping comparison (quota/pin/weight; host-side direct version for robustness under load) |
| `tools/packing_host.py` | Mixed-group packing (class/phase combinations) |
| `tools/mem_phase_host.py` | Memory ballast trials (wave growth, guards, double gate) |
| `tools/disk_phase_host.py` | Disk storm (fio 4K random; io.max / io.weight) |
| `tools/quota_pulse_host.py` | Quota-pulse remedies (period / staggering / weights) |
| `tools/censor_phase_host.py` | Censoring experiment (quota/released phases; cpu.stat evidence) |
| `tools/synthesis_host.py` | Triple-storm synthesis (full protection envelope) |

All control-plane operations use cgroup v2 primitives (`cpu.max`/`cpu.weight`, `memory.high`/`memory.swap.max`, `io.max`/`io.weight` on `qemu.slice/<vmid>.scope`); pinning applies `taskset -apc` to all threads of the qemu process. Host busy/memory come from `/proc/stat` and `/proc/meminfo`; per-VM service volume and throttle evidence come from each scope's `cpu.stat` (`usage_usec`, `nr_throttled`, `throttled_usec`).

## 6.3 Use of AI-Assisted Tools

AI assistants were used for language editing, code review and manuscript organization during preparation. All experiment design and execution, data verification and scientific claims are the author's own; every reported number was checked against the archived raw logs (see Statements and Declarations).

## 6.4 Read-Only Production Telemetry

The two production hosts are monitored read-only and anonymously: PVE read-only interfaces (`pvesh get /nodes`, `/nodes/{node}/status`, `/cluster/resources`) plus `/proc` provide CPU service volume, throttle counters, pressure signals, memory, and lifecycle events at 60-second granularity for a 7-day target. The remote collector HMAC-pseudonymizes VM/node IDs in memory; it never collects VM names, IPs, business content, or disk data; it installs nothing, changes no customer quota, and applies no stress. Credentials are used once for key exchange and discarded; keys live only on the researcher's workstation.

## 6.4 Reproducibility

Testbed scripts, all raw data (219 raw files, 34 JSONL logs, analysis scripts), and the experimental protocol are archived with the paper; the data dictionary (fields, units, semantics, quality flags) and an execution log (every environment change and anomaly) are included. All violation determinations use the pre-registered SLO and window definitions; rejected candidates are never started, and evaluation inputs retain their planned demand — there is no post-hoc selection of runs.
