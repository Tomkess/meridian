---
abandoned_at: null
abandoned_reason: null
appetite: s
blocked_at: null
blocked_by: null
confidence: high
created: '2026-08-18'
cycle: null
depends_on:
- feat-007
enables: []
goal: '~'
id: feat-009
name: 'Track projects centrally: meridian register plus a cross-project status --all
  dashboard'
scheduler: null
sources: []
status: in-production
tags: []
updated: '2026-08-18'
---

## Summary

Meridian is installed in 10+ repos and every command is scoped to one of them.
`meridian status` answers "what is happening *here*". Nothing answers "what is
happening *everywhere*" — which is the question that actually matters once the
tool is spread across a portfolio of projects.

This is the surviving half of FEAT-008. That feature bet on capture being the
bottleneck — getting ideas in from a phone, into a global inbox, triaged into the
right repo. Built and shipped, then killed: the capture problem was real but
secondary, and the inbox added a whole surface (capture files, routing,
suggestions, triage) to solve it. What FEAT-008 got right was the piece
underneath — a machine-global registry of which projects exist and where they
live. That registry is genuinely the missing primitive, and it is worth keeping
on its own.

So: keep `~/.meridian/projects.toml` and `home.py`, drop everything built on top
of them, and spend the registry on the actual question — a cross-project view.

## Appetite

`s` — 1–3 days. Two commands and a table. If this starts growing filters, sort
orders, or a watch mode, stop: the value is the single glance, not the query
language.

## Acceptance Criteria

### Registration

- **AC1** — `meridian register` records the current repo in
  `~/.meridian/projects.toml`, keyed by the FEAT-007 project slug.
- **AC2** — `--name` overrides the slug and `--purpose` overrides the description,
  so two checkouts sharing a directory name can be told apart.
- **AC3** — Re-running updates the entry in place rather than appending a
  duplicate.
- **AC4** — `meridian init` registers automatically, best-effort: a registry write
  must never be the reason project setup fails.
- **AC5** — Run outside a Meridian repo, `register` exits 1 with the standard
  "No .meridian.toml found" message and no traceback.
- **AC6** — The purpose defaults to the first line of real prose in `VISION.md`,
  skipping generic headings like `# Vision` that describe the document rather
  than the project. Falls back to the repo directory name.

### Registry

- **AC7** — `meridian projects` lists slug, purpose, path, and whether the path
  currently resolves.
- **AC8** — An entry whose path no longer exists is reported as missing and kept,
  never silently dropped — a repo may be on an unmounted disk.
- **AC9** — A missing or malformed `projects.toml` degrades to an empty list with
  a warning, never a traceback.

### Cross-project dashboard

- **AC10** — `meridian status --all` prints one row per tracked project with
  feature counts by lifecycle state (idea, draft, in-progress, blocked, done,
  in-production).
- **AC11** — It reads each tracked repo's `specs/` directly and works from any
  directory, including outside every repo. Not needing the right repo checked out
  is the entire point.
- **AC12** — Bare `meridian status` stays scoped to the current project. The
  cross-project view is opt-in.
- **AC13** — A footer totals features across projects and calls out in-progress
  and blocked counts, since those are the two states that need action.
- **AC14** — A tracked project that cannot be read (missing path, no `specs/`) is
  named and skipped without failing the whole dashboard.
- **AC15** — The table fits an 80-column terminal without truncating project
  names. The project name is the row's identity; if something must be dropped it
  is a lower-value column, not the identifier.

### Global home

- **AC16** — `meridian/home.py` resolves `~/.meridian` (honouring `MERIDIAN_HOME`)
  and imports cleanly with no `.meridian.toml` anywhere up the tree — the registry
  must be readable from a directory that is not a repo.
- **AC17** — The test suite never writes to the developer's real `~/.meridian`,
  enforced by a session-scoped autouse fixture that covers subprocess CLI tests.

## Scope

- `meridian/home.py` — global paths (kept from FEAT-008, trimmed to the registry).
- `meridian/registry.py` — `projects.toml` read/write (kept from FEAT-008).
- `meridian/cli.py` — `register`, `projects`, `status --all`.
- Tests, `CLAUDE.md`, `meridian help`.

## Out of Scope

- **The idea inbox.** Capture, triage, routing suggestions — all removed with
  FEAT-008. See its `abandoned_reason`.
- **Filters, sorting, watch mode** on the dashboard. The value is one glance.
- **Reaching into repos for anything but spec counts.** No git status, no CI, no
  branch state — each of those is a network or subprocess call per project and
  turns a glance into a wait.
- **Auto-discovery of projects** by scanning the filesystem. Explicit registration
  is predictable; a scanner would find every stale clone on the disk.

## Key Risks

- **Registry drift** — projects move or are deleted. Mitigated by AC8/AC14:
  report and skip, never delete or crash.
- **Dashboard width** — the table has seven columns before any prose. Purpose was
  dropped for exactly this reason during implementation; adding columns later
  will re-break it.
- **Stale counts** — the dashboard reads `spec.md` frontmatter, so a project whose
  statuses are not maintained looks wrong. This is a property of the data, not a
  bug, but it makes the dashboard only as honest as its inputs.

## Dependencies

- **FEAT-007** for `cfg.project`, the slug that keys the registry.
- Supersedes **FEAT-008** (abandoned), from which `home.py` and `registry.py` were
  kept intact.

## Verification

Live run against the five tracked projects, 2026-08-18:

```
  Project                  idea   draft    prog    blkd    done    prod
  bet365-apify-scraper        ·       ·       1       ·       ·       ·
  gdc-mic-ai-evaluation       ·       ·       2       ·      11       ·
  meridian                    ·       ·       ·       ·       6       2
  misc                        ·       ·       1       ·       5       ·
  portfolio-management        7       ·       6       ·       ·       6

  47 features across 5 projects · 10 in progress
```

Layout took three attempts, each a real Rich behaviour worth recording:
`overflow="ellipsis"` without `no_wrap` still wraps (a vision statement became a
column of single words); a `ratio` column starves fixed columns to zero width
(the counts vanished entirely); and once the table passes 80 columns Rich shrinks
the *headers* too. Resolved by dropping the Purpose column — `meridian projects`
already shows it.

535 tests pass, ruff and mypy clean.
