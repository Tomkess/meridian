---
abandoned_at: null
abandoned_reason: null
appetite: m
blocked_at: null
blocked_by: null
confidence: medium
created: '2026-08-19'
cycle: null
depends_on: []
enables: []
goal: '~'
id: feat-017
name: 'Real drift detection: check acceptance criteria against what the branch actually
  changed'
status: in-progress
tags: []
updated: '2026-08-19'
---

## Summary

Meridian's premise is that a spec stays true. Its entire mechanism for that was
a printed reminder: `close --status done` told you to go and check. The audit
called this the weakest answer in the field, on the axis that is spec-driven
development's central criticism — and noted the one structural advantage
Meridian has over Linear or Jira here: it is git-native, so it can see the diff.

This measures it. Each acceptance criterion names concrete things — functions,
files, flags, modules — in backticks. If a branch satisfies an AC, at least one
of those names should appear somewhere in what the branch changed. An AC whose
every reference is absent is *suspicious*.

Deliberately a heuristic, and the output says so. What it reliably catches is
the common real failure: an AC written during planning, never built, never
removed from the spec.

## Appetite

`m` — a module, a command, the `close` integration, and tests. Not a semantic
matcher; that is a different and much larger bet.

## Acceptance Criteria

### Extraction

- **AC1** — `extract_criteria()` parses `- **ACn** — text` lines, tolerating em
  dash, en dash, hyphen or colon, and IDs like `AC5b`.
- **AC2** — A criterion continues across indented wrapped lines, so a reference
  in a wrapped line is not lost. Specs in this repo wrap constantly.
- **AC3** — Only backticked tokens that *look like code* count as references —
  filenames, CLI flags, `calls()`, `snake_case`, `module.attr`, `CamelCase`.
  Bare prose words like `done` or `idea` appear in every spec and would match
  any diff, making every AC look satisfied.
- **AC4** — An AC naming nothing concrete is reported as unjudgeable rather than
  counted as passing or failing.

### Comparison

- **AC5** — `changed_files()` includes both committed changes against the merge
  base and uncommitted working-tree changes, so drift is visible before commit.
- **AC6** — The haystack is the file list plus the diff text, so an AC naming a
  file is covered by that file changing even if the identifier never appears.
- **AC7** — `save_spec()` in an AC matches a `save_spec` definition in the diff:
  trailing call parens are stripped before matching.

### Guard rails

- **AC8** — `branch_matches()` detects whether the checked-out branch belongs to
  the feature being checked, using Meridian's `feat-NNN/slug` convention.
- **AC9** — When it does not match, the report refuses to judge and says which
  branch it is on. Comparing one feature's criteria against another's diff
  produces confident nonsense.
- **AC10** — With no changes against the base, it reports that rather than
  marking every criterion uncovered.

### Interface

- **AC11** — `meridian drift <feat-id>` reports covered, uncovered and
  unjudgeable criteria, listing what it looked for in each uncovered one.
- **AC12** — `--base` selects the comparison branch; `--json` emits the full
  report including per-criterion `refs` and `hits`.
- **AC13** — Output states plainly that it is a heuristic, not a verdict.
- **AC14** — `close --status done` runs the check instead of printing the old
  reminder, and falls back to the reminder when there are no criteria.
- **AC15** — A failure inside drift never blocks a lifecycle transition.

## Scope

`meridian/drift.py` (new), `meridian/cli.py` (`drift` command, `_render_drift`,
`close` integration), `tests/test_drift.py` (new), `CLAUDE.md`.

## Out of Scope

- **Semantic matching.** Deciding whether code *means* what an AC says needs a
  model. This is lexical and cheap, and runs on every `close`.
- **Failing the transition on drift.** It informs; it does not gate. Turning it
  into a gate before it has earned trust would just teach people to bypass it.
- **Checking merged features.** Once a branch is merged there is no diff to
  compare against, and AC9 refuses rather than guessing.
- **Prose ACs.** An AC with no concrete reference is unjudgeable by design.

## Key Risks

- **False positives train people to ignore it.** The main mitigation is AC3 —
  only code-shaped references count — plus reporting unjudgeable criteria
  separately instead of lumping them in with failures.
- **False negatives are cheap but silent.** An AC that names a widely-used
  identifier will match almost any diff. Accepted: the tool is for catching
  never-built ACs, not for proving correctness.
- **It runs on every `close --status done`.** Wrapped in try/except (AC15) so a
  drift bug can never block a transition.

## Verification

Built and run against this repo. The first live run exposed a real design flaw
rather than working immediately: asked about FEAT-013 from the FEAT-017 branch,
it compared one feature's criteria against another feature's diff and reported
almost everything as uncovered — confident nonsense. That produced AC8–AC9 and
the `branch_matches` guard:

```
$ meridian drift feat-013
⚠  Current branch is feat-017/drift-detection, which does not look like
   FEAT-013's branch.
   Check out the branch that built FEAT-013 — comparing its criteria against
   unrelated changes says nothing.
```

Run against its own feature on its own branch, the report is meaningful — see
the session where this shipped.
