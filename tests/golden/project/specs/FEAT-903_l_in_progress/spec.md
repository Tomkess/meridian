---
id: feat-903
status: in-progress
appetite: l
confidence: high
goal: goal-01
cycle: 2026-Q3
depends_on: [feat-902]
enables: []
created: 2026-03-01
updated: 2026-05-20
---

## Summary

Replace the current flat REGISTRY.md table with a rich TUI dashboard powered by
`textual`. The dashboard shows live task progress bars, cycle assignments, dependency
arrows, and Databricks job status — all navigable with keyboard shortcuts. This becomes
the primary daily-driver interface for teams running multiple features in parallel.

## Appetite

`l` — 2–6 weeks

## Acceptance Criteria

- [ ] Given `meridian status` is run in a terminal, when features exist, then a Textual
  TUI renders with a row per feature showing id, name, status, progress bar, cycle, and
  Databricks job state.
- [ ] Given the TUI is open, when the user presses `r`, then it refreshes all data from
  disk without exiting.
- [ ] Given a feature has `depends_on` set, when its row is focused, then pressing `d`
  shows an inline dependency graph.
- [ ] Given `MERIDIAN_TUI=0`, when `meridian status` is run, then the legacy Rich table
  renders instead (regression safety).
- [ ] Given a feature's task file changes on disk, when the TUI is open, then the progress
  bar updates within 5 seconds (live polling).

## Scope

- `textual` TUI for `meridian status`
- Keyboard shortcuts: `r` refresh, `d` deps, `q` quit, `/` filter
- Live task progress via file polling
- Databricks status column (reuses existing `databricks.py`)
- `MERIDIAN_TUI=0` fallback to legacy table

## Out of Scope

- Editing specs from within the TUI
- Mouse support beyond basic scrolling
- Remote/shared TUI sessions

## Key Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| textual API changes between versions | High | Medium | Pin `textual>=0.60,<1.0`; integration test on CI |
| TUI not rendering correctly in all terminal emulators | Medium | Medium | Test matrix: iTerm2, Terminal.app, tmux, GitHub Actions |
| Databricks polling latency blocking render loop | Low | High | Run Databricks fetches in background worker thread |
| File polling on large repos causing CPU spike | Low | Medium | Debounce to 5s; skip if no in-progress features |

## Dependencies

- **Depends on:** feat-902 (watch infrastructure reuse)
- **Enables:** nothing yet

## Related Research

`sources/textual_docs_excerpt.md` — key layout and reactive patterns from Textual docs.

## Open Questions

1. Should we ship a `--no-tui` global flag instead of `MERIDIAN_TUI=0`?
