---
id: adr-001
date: 2026-05-22
status: accepted
---

# 001 — Modular chainable skills over monolithic pipeline

**Decision:** Build each workflow step as a separate skill/command that produces a file artifact the next one consumes, rather than one monolithic `/feature-dev` command.

**Considered:** Single pipeline command, modular skills, single orchestrator with sub-skills.

**Why:** Each skill is independently re-runnable. You can `/spec` from an existing idea file without re-interviewing. Skills compose naturally with `make-plan` and `do`. Easier to test and improve individually.
