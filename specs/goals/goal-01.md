---
id: goal-01
name: Be the memory layer across repositories
status: active
created: 2026-08-19
horizon: 1-year
measurable_outcome: A majority of active features carry at least one indexed source, cross-project prior art surfaces a relevant hit from another repo, and `meridian next` answers "what should I work on" across every tracked project without opening a repo.
---

The two capabilities nothing else offers are the cross-repo portfolio view and
the spec-bound research corpus. Everything else Meridian does — lifecycle,
appetite, cycles, drift — is available in some form elsewhere, and exists here to
give those two something to attach to.

Today both are real but thin. The corpus holds 178 chunks across 61 features, so
most work carries no evidence at all, and `meridian status --all` counts features
by state without answering the portfolio question it exists for: *what should I
work on next, across everything*. This goal closes both gaps — ingestion that
scales, retrieval that reaches across repos, research that persists with
citations, and a portfolio view that ranks rather than tallies.

The deliberate non-goal: expanding the spec pipeline. It is scaffolding, and the
open question is whether it earns its ~800 lines at all.
