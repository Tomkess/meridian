---
abandoned_at: null
abandoned_reason: null
appetite: s
blocked_at: null
blocked_by: null
confidence: high
created: '2026-08-19'
cycle: null
depends_on: []
enables: []
goal: '~'
id: feat-020
name: Extract the cross-repo skill distribution machinery out of cli.py into a testable
  meridian/skilldist.py
status: done
tags: []
updated: '2026-08-19'
---

## Summary

Roughly 300 lines of git and GitHub machinery lived inside `meridian/cli.py`.
That code clones, force-pushes and opens pull requests **in the user's other
repositories** — it is the most dangerous code in the project — and none of it
could be reached without importing the whole Typer app. So the riskiest surface
also had the thinnest coverage: a handful of end-to-end CLI runs in
`tests/test_install_all.py` and nothing at the unit level.

FEAT-014 deleted a 309-line static manual from `cli.py` but left this extraction
undone. This is the remaining half of that work.

`meridian/skilldist.py` now owns everything that reaches outside the current
repository and **returns data**. `cli.py` keeps every `Table`, every
`console.print`, and every `typer.Exit`. That boundary is the deliverable: it is
what makes the git and GitHub paths reachable from a test.

## Appetite

`s` — a move, a seam, and the tests the seam buys. No behaviour change.

## Acceptance Criteria

### The module

- **AC1** — `meridian/skilldist.py` exists and exports `SkillSync`,
  `bundled_skills_dir`, `sync_skills`, `run_git`, `default_branch`,
  `open_skill_pr`, `sync_all`, `open_skill_prs`, plus the `SyncOutcome` and
  `PrOutcome` records.
- **AC2** — The module imports neither `typer` nor `rich`, never touches
  `console`, and never raises `typer.Exit`. `test_module_imports_no_ui_libraries`
  enforces this by parsing the module's own AST, so the guard cannot be defeated
  by a lazy import inside a function.
- **AC3** — `sync_all` and `open_skill_prs` iterate the tracked projects and
  return a list of per-project records — slug, status, detail, and for the
  non-PR path the new/changed/current/written counts — instead of printing
  rows. An unreachable path or an `OSError` becomes a `failed` / `skipped`
  record, never an exception: one broken repo must not stop the other nine.
- **AC4** — `open_skill_prs` takes a `progress` callback so `cli.py` can keep its
  per-repo `console.status` spinner without the module knowing that Rich exists.
  It defaults to `contextlib.nullcontext`.

### The CLI

- **AC5** — `meridian/cli.py` imports from `meridian.skilldist` and keeps
  `_install_to_all` and `_install_prs_to_all` as pure rendering: table
  construction, styles, the `total_written` / `total_pending` counters, and the
  `typer.Exit(0)` on an empty registry.
- **AC6** — `SkillSync`, `_bundled_skills_dir`, `_sync_skills`, `_git`,
  `_default_branch` and `_open_skill_pr` are **gone** from `cli.py` — moved, not
  re-exported. `cli.py` drops from 1,927 to 1,718 lines and no longer imports
  `dataclasses`.
- **AC7** — `install` output is byte-identical to the previous release across
  `--all`, `--all --dry-run`, `--all --force`, `--all --prune`, `--all --pr`,
  `--all --pr --dry-run`, `--project` and the `--pr requires --all` error,
  verified by diffing captured runs with `FORCE_COLOR=1` so the markup is
  compared too.

### The tests the seam buys

- **AC8** — `tests/test_skilldist.py` drives the real functions against real
  temporary git repositories built with `git init` — a bare repo as `origin`, a
  seed repo that pushes to it, and a clone. `subprocess` is not mocked.
- **AC9** — `sync_skills` is covered for every classification: `new`, `changed`
  (and left alone without `--force`), `current`, `removed` under `prune`, and
  `dry_run` writing nothing.
- **AC10** — `default_branch` is covered on both paths: resolved from
  `refs/remotes/origin/HEAD`, and — after that ref is deleted, as on a
  `--single-branch` clone — via the `git remote show origin` fallback. A repo
  with no remote returns `None`.
- **AC11** — `open_skill_pr` is covered returning `skipped` with no `.git`,
  `skipped` with no `origin` remote, `would open` under `dry_run=True`, and
  `current` on a repo whose `origin/main` already carries the skills — which
  exercises `git worktree add`, `checkout -B` and the sync inside the throwaway
  worktree for real.
- **AC12** — The safety property is asserted directly: after a non-dry-run
  `open_skill_pr`, the clone's uncommitted file is intact, its `HEAD` is
  unmoved, no `.claude/` was written into the checkout, and the temporary
  worktree is unregistered rather than left dangling in `git worktree list`.
- **AC13** — `tests/test_install_all.py` passes **untouched**. It drives the real
  binary end to end and is the check that the refactor did not overreach.

## Scope

`meridian/skilldist.py` (new), `meridian/cli.py` (`_install_to_all`,
`_install_prs_to_all`, the `install` command, the `dataclasses` import),
`tests/test_skilldist.py` (new).

## Out of Scope

- **The `gh`-dependent tail of `open_skill_pr`** — everything from `git push`
  onward, where it shells out to `gh pr list` and `gh pr create`. Faking `gh`
  would test the fake, and a test that really opened a pull request would be
  worse. It is named as uncovered in the test module's docstring rather than
  papered over with a mock.
- **Behaviour changes of any kind.** No new flags, no changed messages, no
  changed exit codes. A refactor that also alters behaviour cannot be verified
  by diffing its output.
- **`meridian/drift.py`'s own `_git`.** A separate three-line helper with
  different semantics (it returns text and swallows failures). Merging the two
  is a judgement call, not a mechanical move.

## Key Risks

- **Byte-identical output is easy to claim and easy to get wrong** — the plain
  `·` for a skipped project versus the `[dim]·[/dim]` for a zero count renders
  the same without colour, so a NO_COLOR test would not have caught a mix-up.
  Mitigated by capturing every `install` variant before and after with
  `FORCE_COLOR=1` and diffing.
- **Losing the per-repo spinner.** `console.status` is a context manager wrapped
  around each repo's turn, and the obvious extraction drops it. The `progress`
  hook keeps it while leaving the module Rich-free.
- **A UI import creeping back in.** The reason this code was untestable was
  proximity to the console, and nothing structural prevented the regression.
  AC2 makes it a test failure.

## Verification

```
$ uv run --locked python -m pytest -q      → 635 passed  (608 before, +27)
$ uv run --locked ruff check .             → All checks passed!
$ uv run --locked mypy meridian/           → Success: no issues found in 13 source files
```

`tests/test_install_all.py` passed unmodified, 16 tests. `meridian/cli.py`:
1,927 → 1,718 lines.
