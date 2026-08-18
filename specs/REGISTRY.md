# Meridian Registry

Index of all features across all goals and lifecycle states.

## Status Legend
`idea` `draft` `in-progress` `blocked` `done` `in-production` `abandoned`

## Appetite Legend
`xs` < 1 day  ·  `s` 1–3 days  ·  `m` 1–2 weeks  ·  `l` 2–6 weeks

## Confidence Legend
`low` problem poorly understood  ·  `medium` rough shape clear  ·  `high` well-defined

## Features

| ID | Name | Goal | Status | Appetite | Conf | Cycle | Updated |
|---|---|---|---|---|---|---|---|
| FEAT-009 | Track projects centrally: meridian register plus a cross-project status --all dashboard | ~ | in-progress | s | high | — | 2026-08-18 |
| FEAT-001 | Capture Layer 3 golden-set runs: run scripts/run_golden.sh and commit outputs to tests/golden/runs/ to un-skip the 22 structural regression tests | ~ | done | s | — | — | 2026-07-14 |
| FEAT-002 | Add integration tests for external seams: Ollama embed + LanceDB round-trip, mocked with pytest-httpx (happy-path, complementing existing degradation tests) | ~ | done | s | — | — | 2026-07-14 |
| FEAT-003 | Skill-consistency regression harness: run a skill twice and diff output structure (sections + frontmatter) to catch ambiguous prompts, now that model routing changed | ~ | done | s | — | — | 2026-07-14 |
| FEAT-004 | Add file lock to transition_spec() to prevent frontmatter corruption under concurrent multi-agent/worktree writes | ~ | done | xs | — | — | 2026-07-14 |
| FEAT-005 | Add dependency-bounds test for LanceDB minor-version API drift (last item on production-ready checklist) | ~ | done | xs | — | — | 2026-07-14 |
| FEAT-006 | Ingest annotated screenshots into a feature's research corpus | ~ | done | s | high | — | 2026-08-18 |
| FEAT-007 | Scope the shared LanceDB index per project so 10+ repos stop clobbering each other | ~ | in-production | s | high | — | 2026-08-18 |
| FEAT-008 | Capture ideas away from the PC into a global inbox and triage them into the right project | ~ | abandoned | m | medium | — | 2026-08-18 |

## Goals

| ID | Name | Status |
|---|---|---|
| — | — | — |
