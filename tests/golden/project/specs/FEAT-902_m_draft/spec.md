---
id: feat-902
status: draft
appetite: m
confidence: medium
goal: goal-01
cycle: 2026-Q3
depends_on: []
enables: [feat-903]
created: 2026-04-15
updated: 2026-05-10
---

## Summary

Add a `meridian watch` command that monitors a feature's task file for checkbox
completions and automatically transitions lifecycle state when all tasks are done.
This removes the manual `meridian close --status done` step and keeps the registry
accurate without human intervention.

## Appetite

`m` — 1–2 weeks

## Acceptance Criteria

- [ ] Given a feature is `in-progress`, when all `- [x]` checkboxes in `tasks.md` are
  checked, then `meridian watch` transitions it to `done` and updates REGISTRY.md.
- [ ] Given `meridian watch feat-902` is running, when a task file is saved, then the
  watcher polls within 2 seconds and re-evaluates completion.
- [ ] Given the feature has no `tasks.md`, when the watcher starts, then it prints a
  warning and exits cleanly (exit 0).
- [ ] Given a transition fails (e.g. already `done`), when the watcher detects completion,
  then it prints a notice and stops without raising an unhandled exception.

## Scope

- File-watch loop using `watchfiles` or polling fallback
- Single-feature watch mode only (`meridian watch <feat-id>`)
- Dry-run flag (`--dry-run`) that prints what would happen without mutating state

## Out of Scope

- Watching multiple features simultaneously
- Auto-transition to `in-production` (requires merge; that's `meridian transition`)
- Task file writing / editing

## Key Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| watchfiles not available on all platforms | Medium | Low | Polling fallback with 2s interval |
| Race condition: partial save triggers transition | Low | Medium | Require 100% boxes checked, not ≥ 1 new |
| Regex fragility on non-standard task formats | Medium | Medium | Test with tasks.md fixtures; document expected format |

## Dependencies

- **Depends on:** none
- **Enables:** feat-903 (bulk watch for all in-progress features)

## Related Research

No sources enriched yet. Run `meridian enrich feat-902 <source>` to add research.

## Open Questions

1. Should `meridian watch` remain running until killed, or exit after the first transition?
2. Should partial completion (e.g. 80%) surface a progress indicator?
