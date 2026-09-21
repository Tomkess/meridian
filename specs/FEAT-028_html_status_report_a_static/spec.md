---
abandoned_at: null
abandoned_reason: null
appetite: m
blocked_at: null
blocked_by: null
confidence: medium
created: '2026-09-21'
cycle: null
depends_on: []
enables: []
goal: '~'
id: feat-028
name: 'HTML status report: a static, self-contained, offline HTML dashboard for one
  project''s specs, generated on demand by ''meridian report'' and never committed.
  Renders client-side from an embedded JSON payload using vanilla JS and inline SVG
  (no CDN, no build step). Shows what a terminal table cannot: dependency graph from
  depends_on/enables, kanban board by lifecycle status, goal x feature matrix with
  gaps visible, task progress bars, staleness heat. Prerequisite: extract the status
  --json payload dict out of cli.py into a shared build_payload() in a new meridian/report.py
  so the CLI and the report cannot drift apart.'
sources: []
status: in-progress
tags: []
updated: '2026-09-21'
---

## Summary

`meridian report` renders the current project's feature dashboard as a single
static HTML file — the visual counterpart to `meridian status`. It embeds the
same data `status --json` already produces, renders it client-side with vanilla
JS and inline SVG, and opens offline in a browser with no server, build step, or
CDN dependency. It exists because a terminal table cannot show relationships
(the `depends_on`/`enables` graph), a goal × feature matrix with visible gaps, or
a kanban-shaped view of lifecycle state — all of which are already present in
the spec frontmatter and simply unrendered today. This is deliberately scoped
as tooling polish, not a goal-01 deliverable: goal-01's non-goal explicitly
warns against expanding the spec pipeline, and this feature is exactly that —
captured anyway because it is useful, not because it advances the cross-repo
memory-layer goal.

## Appetite

`m` — 1–2 weeks

## Acceptance Criteria

- [ ] Given a project with `.meridian.toml`, when `meridian report` runs, then a single self-contained `.html` file is written to a path under the project (default `specs/.meridian/report.html`, override via `--out PATH`) with zero external `<script src>`/`<link>` references — opening it via `file://` with network disabled renders correctly.
- [ ] Given the same specs, when `meridian status --json` and `meridian report` both run, then the feature-level fields in the report's embedded payload match `status --json` byte-for-byte per field (id, name, status, appetite, confidence, cycle, goal, updated, depends_on, enables, blocked_by, tasks) — both call the same `build_payload()` in `meridian/report.py`, extracted from `cli.py`.
- [ ] Given features with non-empty `depends_on`/`enables`, when the report renders, then a dependency graph is drawn as inline SVG with one node per feature and one edge per relationship, and a feature with a `depends_on` pointing to a nonexistent ID is rendered as a distinguishable dangling edge, not silently dropped.
- [ ] Given features across all lifecycle states, when the report renders, then a kanban board groups features into columns matching `STATUS_COLUMNS` from `cli.py`, and a `blocked` feature's card shows its `blocked_by` reason.
- [ ] Given features linked to goals in `specs/goals/`, when the report renders, then a goal × feature matrix is shown with one row per goal (plus an "ungoaled" row for `goal: '~'`) and empty cells visible as gaps, not omitted rows.
- [ ] Given an in-progress feature with a `tasks.md`, when the report renders, then its task progress (checked/total, already computed by `task_progress()`) is shown as a filled bar, not just a fraction.
- [ ] Given `meridian status` and `meridian report` are run back to back with no spec changes between them, then `meridian report` reflects the same on-disk state — no caching, no stale payload.
- [ ] Given the report is generated twice with no changes, when the file is compared, then no committed artifact exists — `meridian report`'s default output path must not be a path any existing `.gitignore` needs to swallow silently (verify: `specs/.meridian/` is already ignored, or add it).
- [ ] Given the package is installed via `uv pip install`/`pipx`, when `meridian report` runs from that install, then the HTML template renders correctly — the template asset is included in package data (guard: extend `test_packaging.py`).

## Scope

- Single-project report only (`meridian report`, run inside a registered project or via `--project SLUG` against the local `.meridian.toml`)
- Extraction of `build_payload()` from `cli.py`'s `status` command into `meridian/report.py`, consumed by both `status --json` and `report`
- One HTML template (inline CSS, inline JS, inline SVG helpers) embedded as package data
- Views: kanban by status, dependency graph, goal × feature matrix, task progress bars, staleness indicator per feature
- `--out PATH` to override the default output location
- `--open` to open the generated file in the default browser after writing

## Out of Scope

- Cross-project / portfolio report (`status --all` equivalent) — explicitly deferred; the per-project scope was chosen over portfolio in the idea's brainstorm precisely to avoid the cross-repo leakage question a shared page raises
- Publishing to Claude Artifacts or any shareable link — static local file only, per explicit instruction
- A live/watching server mode (`--serve`, hot reload) — static, on-demand generation only
- Any CDN-hosted charting library — inline SVG only, no network dependency at render time
- Committing the generated report to the repo — always regenerated, never a tracked artifact
- Editing specs from the report (read-only view)

## Key Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `build_payload()` extraction introduces a schema drift between `status --json` and `report` if done carelessly | medium | high | Extraction is itself an acceptance criterion with a byte-for-byte field comparison; both call sites go through the same function, not parallel implementations |
| Dependency graph layout (auto-positioning nodes/edges without a layout library) becomes fiddly and eats the appetite | medium | medium | Start with a simple deterministic layout (rank by dependency depth, columns = ranks) rather than force-directed; revisit only if it's unreadable at real project sizes (~30 features) |
| Template packaging is missed (asset not included in wheel) and only discovered post-release | low | medium | `test_packaging.py` already exists and is the explicit guard named in the acceptance criteria |
| Scope creep toward portfolio view mid-build, since the payload shape is a near-superset | medium | low | Out-of-scope section explicitly names it; `build_payload()` signature stays single-project only for this feature |

## Dependencies

- **Depends on:** none — consumes existing `status --json` logic, `portfolio.py`, `specs.py` task progress, all already shipped
- **Enables:** a future cross-project portfolio HTML report, if ever pursued, would reuse `report.py`'s template/rendering machinery

## Related Research

No sources enriched yet. Semantic search for "html status report dashboard" returned only FEAT-006 screenshot-ingestion chunks (unrelated topic, no genuine overlap). No existing feature covers this ground; FEAT-026 (portfolio view that ranks) is the nearest prior work but is terminal-only and cross-project, not a rendering concern.

## Open Questions

- Default output path: `specs/.meridian/report.html` was assumed above — confirm this is `.gitignore`d already, or add the entry as part of this feature.
- Dependency graph layout approach (rank-by-depth columns vs. something else) is deferred to `/breakdown` — flagged as the one place this `m`-appetite feature could quietly become `l` if not kept simple.
- Whether `--open` should be default-on or default-off; leaning default-off (explicit is cheaper to reason about in scripts/CI-adjacent use).
