---
abandoned_at: null
abandoned_reason: null
appetite: m
blocked_at: null
blocked_by: null
confidence: high
created: '2026-08-19'
cycle: 2026-Q3
depends_on: []
enables: []
goal: goal-01
id: feat-026
name: Portfolio view that ranks instead of tallies
sources: []
status: draft
tags: []
updated: '2026-08-20'
---

## Summary

`meridian status --all` counts features by lifecycle state across five projects.
It is genuinely useful and it is a **tally**, not a portfolio view. It cannot
answer the question that made cross-project tracking worth building:

> *What should I work on next, across everything?*

Today the answer requires opening five repos and reading `tasks.md` in each.
The counts even actively mislead: `portfolio-management` shows 7 ideas and 6
in-progress, which reads as the busiest project, while saying nothing about
whether any of it has moved in two months.

Three signals are already on disk in every tracked repo and none is surfaced:
**staleness** (when did anything last change), **task progress** (`task_progress`
already computes checked/total), and **blocked age** (`blocked_at` is already
written and `meridian guide` already flags 14+ days — but only within one repo).

This adds a ranked, cross-project view and the staleness and capacity signals
that make the ranking defensible.

## Appetite

`m` — a ranking with a justification, two new signals, a `next` command, `--json`
throughout, and tests for the ordering rules.

## Design decisions

**The ranking must be explainable in one line per row.** An opaque score is
worse than a tally, because a tally at least does not pretend. Every row states
why it ranked where it did — "blocked 31 days", "11 of 12 tasks done", "nothing
changed in 47 days".

**Order: rot first, then completion, then starts.** Blocked-longest ranks above
everything, because a blocked feature is the only state that gets worse purely by
being ignored. Then in-progress nearest completion, which is Shape Up's bias
toward finishing over starting. Then stale in-progress. Ideas and drafts rank
last — they are inventory, not work.

**Staleness is measured from spec and task file mtimes, not git.** Reading git
history in every tracked repo means spawning subprocesses across ten checkouts,
some on unmounted disks. mtime is weaker — a checkout rewrites it — and it is
local, fast, and available even for a repo with no commits. The weakness gets
stated in the output rather than hidden.

**`status --all` keeps its current shape.** It answers "what is in flight
everywhere" and answers it well. `next` is a separate command answering a
separate question. Overloading the dashboard would cost the property that makes
it readable — one row per project.

## Acceptance Criteria

### `meridian next`

- **AC1** — `meridian next` ranks actionable work across **every tracked
  project**, without any repo being checked out or current.
- **AC2** — Each row names project, feature ID, name, and a one-line reason for
  its position.
- **AC3** — Ordering is: blocked longest → in-progress nearest completion →
  in-progress stale → draft → idea. The rule is stated in `--help`, not only in
  the code.
- **AC4** — `--limit N` bounds output, and when rows are dropped the count of
  what was dropped is printed. A silent truncation reads as "that is
  everything".
- **AC5** — `--project <slug>` narrows to one project, so the same ranking works
  inside a single repo.
- **AC6** — `--json` emits every field including the reason and the raw signals
  behind it, so a skill can re-rank without re-deriving.

### Staleness

- **AC7** — `meridian status --all` gains a column showing days since anything
  changed in each project, derived from spec and task file mtimes.
- **AC8** — A project stale beyond a threshold is visually marked, matching how
  blocked counts are already marked.
- **AC9** — The output states that staleness comes from file mtimes and that a
  fresh checkout resets them. A signal whose limits are hidden gets trusted too
  far.

### Capacity

- **AC10** — `meridian status --all` reports, per project, how much appetite is
  committed to the current cycle, and a portfolio total.
- **AC11** — The Shape Up guidance already in `meridian cycle` — at most two
  large bets — is applied **across projects**, not per project. Two large bets in
  each of five repos is ten, which is the failure the guidance exists to prevent
  and which no per-repo check can see.
- **AC12** — A feature with no cycle is counted as uncommitted, not as zero, and
  the distinction appears in the output.

### Robustness

- **AC13** — An unreadable or missing tracked repo is reported and skipped,
  never deleted and never silently omitted — matching the existing behaviour.
- **AC14** — A malformed spec in one project does not stop the ranking. It is
  reported and the remaining projects still rank.
- **AC15** — Ranking ten projects with sixty features each completes without a
  perceptible pause, and a test asserts the whole view is built from at most one
  pass over each project's specs.

## Scope

`meridian/cli.py` (a `next` command and two new columns), a ranking module with
the ordering rules as pure functions, and tests.

## Out of Scope

- **Cross-project dependencies.** `depends_on` is a feature ID with no project
  qualifier, so cross-repo dependencies cannot be expressed today. Making them
  expressible is a data-model change and its own feature.
- **Writing anything.** `next` is read-only across other people's repos. A
  command that mutates ten checkouts is a different risk class entirely.
- **Git-derived activity.** Deliberately rejected above; revisit only if mtime
  proves too noisy in practice.
- **Replacing `status --all`.** It stays as it is.
- **A daily digest or notification.** Scheduling is a separate concern and this
  must be useful when run by hand first.

## Key Risks

- **The ranking encodes my priorities, not the user's.** Mitigated by AC2 and
  AC3 — every row explains itself and the rule is documented, so disagreement is
  visible and arguable rather than mysterious. `--json` lets a skill re-rank.
- **mtime is a weak staleness proxy.** A `git clone` or a `git checkout` resets
  every file, making a long-dormant project look fresh. AC9 states it. Accepted
  because the alternative costs subprocesses in every tracked repo.
- **"Nearest completion" rewards padding.** A feature with twenty trivial tasks
  outranks one with three real ones. Accepted: the alternative is estimating task
  size, which is worse. Worth revisiting with evidence.
- **This is the fourth thing reading `specs/` directly.** `status --all`,
  `guide`, `drift`, and now `next` each re-derive project state. If a fifth
  appears, that is the signal to extract a shared reader rather than to keep
  copying.

## Verification

Against the real five-project registry: `meridian next` must rank without any
repo being checked out, and the ordering rule must be reproducible by hand from
the printed reasons.
