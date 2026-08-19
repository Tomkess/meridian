---
abandoned_at: null
abandoned_reason: null
appetite: m
blocked_at: null
blocked_by: null
confidence: high
created: '2026-08-19'
cycle: null
depends_on: []
enables: []
goal: '~'
id: feat-019
name: 'Golden-set coverage: rubric and captured runs for the remaining skills'
status: in-production
tags: []
updated: '2026-08-19'
---

## Summary

The audit found the Layer-3 quality harness covering 5 of 15 skills and stale by
a month, and drew the right conclusion: *a quality gate covering a third of the
surface is worse than none, because it implies coverage that does not exist.*

The uncovered skills were exactly the wrong ones — the write-side. `/enrich`
writes prose into the corpus that every later `/ask` retrieves as fact.
`/vision` destructively rewrites the north star. `/goal` and `/idea` gate the
funnel. All four could degrade silently.

FEAT-014 helped by deleting four unscored skills. This covers the rest: rubric
sections and captured runs for `/vision`, `/goal new`, `/idea`, `/enrich` and
`/decision`, leaving one documented exemption.

Each run is scored against its own rubric and, more usefully, names the
**regression-critical behaviour** — the one thing a future prompt edit would
plausibly break while looking like an improvement.

## Appetite

`m` — five runs, six rubric sections, and the tests that stop coverage rotting
again.

## Acceptance Criteria

### Rubric

- **AC1** — Rubric sections exist for `/vision`, `/goal new`, `/idea`,
  `/enrich`, `/decision` and `/brief`.
- **AC2** — Each has must-have criteria that are checkable by reading the
  output, not matters of taste.
- **AC3** — The write-side risk is stated where it applies: `/vision` is
  destructive and unrecoverable, `/enrich` pollutes a shared corpus.

### Runs

- **AC4** — Captured runs exist for `/vision`, `/goal new`, `/idea`, `/enrich`
  and `/decision`, against the golden fixture project.
- **AC5** — Each run records the date, version, model and exact invocation, so a
  later diff compares like with like.
- **AC6** — Each run scores itself against the rubric and states the result.
- **AC7** — Each names its regression-critical behaviour and *why that failure
  would look like an improvement*. A rubric row says what to check; this says
  what to fear.
- **AC8** — Fixtures are chosen to make the check bite: the `/vision` run uses a
  draft that is too long and tactical, `/goal new` proposes a goal that partly
  overlaps `goal-01`, and `/idea` proposes something adjacent to existing
  features. A fixture that trivially passes tests nothing.

### Coverage guard

- **AC9** — A test fails when a bundled skill has neither a captured run nor a
  recorded exemption.
- **AC10** — An exemption must be argued in `RUBRIC.md`, not merely listed in
  code.
- **AC11** — An exemption naming a skill that no longer exists fails, so a
  deleted skill cannot linger as a phantom.
- **AC12** — A captured run with no scoring table fails — that is a transcript,
  not an evaluation.

## Scope

`tests/golden/RUBRIC.md`, five new files in `tests/golden/runs/`, and four
coverage tests in `tests/test_golden_structure.py`.

## Out of Scope

- **`/brief`.** Exempt, with the reason recorded: the golden project holds no
  source document to summarise, and inventing one would test the fixture rather
  than the skill. Covering it means adding a real paper to
  `tests/golden/research_assets/`.
- **Automating the runs.** Capturing them needs a live model; the harness is a
  human-or-agent-run gate, as designed in FEAT-003.
- **Scoring the existing five runs against the new format.** They predate it and
  still pass their own sections.
- **The skill-quality findings from the audit** — `/research` persisting
  nothing, `brief.md`'s self-reported word limit. Those are prompt changes, and
  changing a prompt in the same feature that establishes its baseline would
  destroy the baseline's value.

## Key Risks

- **A golden run is only as good as its fixture.** Mitigated by AC8 — every
  fixture is chosen so a lazy answer fails.
- **Self-scoring is circular.** Partly true and partly the point: the run is a
  *baseline*, and its value is in the diff when a prompt changes, not in the
  score today. AC7 exists because the prose explanation of what to fear survives
  a re-scoring that a checkbox does not.
- **Runs go stale as skills change.** The version and date in each run make
  staleness visible, but nothing enforces re-capture. That is the honest limit
  of this design.

## Verification

10 captured runs for 11 skills, one documented exemption. The coverage guard was
written to fail first: removing a run from the directory makes
`test_every_skill_has_a_run_or_a_recorded_exemption` fail by name.

608 tests pass in the locked environment (+4), ruff and mypy clean.
