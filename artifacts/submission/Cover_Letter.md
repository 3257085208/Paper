# Cover Letter

Dear Editor-in-Chief,

We submit for consideration in the *Journal of Network and Systems Management* the manuscript
"Identify, Predict, Actuate: Safe Density Maximization for Small VPS Hosts under Censored Demand, Phase
Structure and Domain-Scoped No-Regression" by Kaixiang Nie.

Small VPS providers oversubscribe by necessity: many cheap, mostly-idle tenants on a few physical
cores. Yet the prevailing capacity practices — usage panels, average-utilization thresholds,
independence-based convolutions — silently fail in this regime for three structural reasons that
large-cloud research does not face: quotas censor demand, tenant bursts share phase structure, and
short histories force sampling decisions. The manuscript turns these three failure modes into an
organizing principle (observation necessity), backs each with constructive counterexamples (with
executable checks), and delivers the controller that follows from them: a minimal observation set
(censoring evidence + joint phase profiles + one-second resolution) realized as a risk-calibrated
admission controller.

The evidence is unusually direct for this problem class: two self-built testbeds (a 4-vCPU nested
host and a 96-thread bare-metal host with a 64-VM fleet), a complete seven-policy, fourteen-round
admission showdown under identical arrival streams, a phase-arrangement intervention that changes
sellable capacity 2–4x with identical tenants, and read-only telemetry from two production hosts we
operate (285 VMs configured; 8.3x vCPU oversubscription). Every claim carries round-level statistics
and explicit boundary statements, and all code, schedules and raw traces are released for
reproduction.

We believe the work fits the journal's scope at the intersection of measurement-driven systems
research and network/service management: it offers actionable, validated design rules for the
underserved small-host segment and connects to JNSM's ongoing conversation on resource management
for virtualized and cloud infrastructure.

The manuscript is original, has not been published elsewhere, and is not under consideration by
another journal. The author declares no competing interests. All production telemetry was collected
read-only on infrastructure we operate, anonymized, and is released only in aggregate form; no
user-identifying data is included. Suggested reviewers:
1. Prof. Thomas Ledoux, IMT Atlantique (France) — Thomas.Ledoux@imt-atlantique.fr — cloud resource
   management and VM oversubscription.
2. Dr. Pierre Jacquet, Inria (France) — pierre.jacquet@inria.fr — oversubscribed cloud infrastructures.
3. Prof. Romain Rouvoy, Universite de Lille / Inria (France) — romain.rouvoy@univ-lille.fr —
   adaptive cloud systems and resource management.
(The author is not aware of any conflicts of interest with the suggested reviewers.)

Thank you for your consideration.

Sincerely,
Kaixiang Nie
Fujian Chuanzheng Communications College
