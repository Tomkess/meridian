---
id: feat-904
status: draft
appetite: m
confidence: high
goal: goal-01
cycle: 2026-Q3
depends_on: []
enables: []
created: 2026-04-02
updated: 2026-05-22
---

## Summary

Add a `--json` output mode to `meridian status` so the feature dashboard can be
consumed by scripts, CI dashboards, and external tooling. Instead of the Rich
table, emit a single well-formed JSON document describing every feature: id,
name, status, appetite, confidence, cycle, task progress, and dependency edges.
This turns Meridian's state into a machine-readable API without a server.

## Appetite

`m` — 1–2 weeks

## Acceptance Criteria

- [ ] Given `meridian status --json` is run, when features exist, then a single
  valid JSON object is printed to stdout with no Rich formatting or ANSI codes.
- [ ] Given a feature has a tasks.md, when `--json` runs, then that feature's
  object includes `progress` with `done` and `total` integer counts.
- [ ] Given a feature has `depends_on`/`enables` set, when `--json` runs, then
  those edges appear as arrays of feature ids under `dependencies`.
- [ ] Given `--json` is combined with a filter, when the filter matches a subset,
  then only matching features appear in the output array.
- [ ] Given no features exist, when `--json` runs, then an empty `features` array
  is emitted (exit code 0, not an error).

## Scope

- `--json` flag on the `status` command
- Stable, documented top-level schema (`{schema_version, features: [...]}`)
- Reuse the existing `all_specs()` loader and task-progress parser
- Suppress all Rich output when `--json` is active

## Out of Scope

- Streaming / NDJSON output
- A long-running server or `--watch` mode
- Writing the JSON to a file (callers redirect stdout)

## Key Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Schema churn breaking downstream consumers | Medium | High | Version the payload with `schema_version`; add a contract test |
| Rich accidentally leaking ANSI into stdout | Medium | Medium | Route JSON through a plain `print`, not the Rich console |
| Progress counts drifting from the table view | Low | Medium | Share one parser between table and JSON paths |

## Dependencies

- **Depends on:** nothing
- **Enables:** nothing yet

## Open Questions

1. Should `schema_version` be an integer or a semver string?
