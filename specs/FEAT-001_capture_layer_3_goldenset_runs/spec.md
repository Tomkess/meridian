---
abandoned_at: null
abandoned_reason: null
appetite: s
blocked_at: null
blocked_by: null
confidence: null
created: '2026-07-14'
cycle: null
depends_on: []
enables: []
goal: '~'
id: feat-001
name: 'Capture Layer 3 golden-set runs: run scripts/run_golden.sh and commit outputs
  to tests/golden/runs/ to un-skip the 22 structural regression tests'
scheduler: null
sources: []
status: in-progress
tags: []
updated: '2026-07-14'
---

## Progress (in-progress)

**Scaffolding done:** `scripts/run_golden.sh` rewritten from a manual stub into a
runnable capture tool — it provisions the fixture project (`tests/golden/project`)
with the bundled skills + a `.meridian.toml`, then invokes each skill headlessly
via `claude -p "/<skill> <feat>" --dangerously-skip-permissions` and writes
`tests/golden/runs/<skill>_<feat>.md`. Skill `model:` frontmatter is honored by
the CLI. Verified via `DRY_RUN=1 ./scripts/run_golden.sh` (prints the plan,
invokes nothing). Fixture runtime artifacts are gitignored.

**Remaining (needs interactive `claude` + Ollama):** run `./scripts/run_golden.sh`,
review the 4 captured outputs, commit them to `tests/golden/runs/` — this un-skips
the 22 tests in `tests/test_golden_structure.py`. Then score against
`tests/golden/RUBRIC.md`.

**Capture working (2026-07-14):** `run_golden.sh` rewritten to solve isolation and
capture the right artifact:
- Copies the fixture to a temp dir OUTSIDE the repo (skill file-writes never touch
  the tracked fixture) and runs with a clean `$HOME` (`env -i ... HOME=<tmp>`), so
  the global `~/.claude` memory no longer leaks this repo's FEAT-001..005 context
  into the child run. Isolation confirmed: `/spec feat-901` now elaborates the
  fixture stub correctly.
- Captures each skill's written artifact (spec.md / breakdown.md), not stdout.

**Captured + committed:** `spec_feat-901.md` (passes all 5 /spec structural tests)
and `breakdown_feat-902.md` (passes all breakdown tests). Golden structure suite
now 19 passed / 10 skipped (was 7 / 22); full suite 333 passed / 10 skipped.

**Test fix:** `_has_section` matched only `##`; the /breakdown skill template
(authoritative) emits `###` subsections under a `## Technical Breakdown` title, so
the test was wrong. Loosened to accept `##` or `###`.

**All four skill captures landed (2026-07-14) — golden suite 31 passed / 0 skipped:**

- `/tasks` — added task-less fixture FEAT-904 (`m`/draft, spec + breakdown, no
  `tasks.md`) so the capture is a genuine draft → generation, not a no-op on
  FEAT-903. Captured 11 atomic tasks (every one `Pre:` + AC refs).
- `/spec`, `/breakdown` — captured earlier this feature (FEAT-901/902).
- `/research`, `/ask` — needed a populated corpus. Added staged research assets
  under `tests/golden/research_assets/<feat-id>/` (kept OUT of `sources/` so
  `meridian enrich` imports them cleanly — enriching a file already in `sources/`
  raises `SameFileError`). `provision()` now enriches + indexes into the
  sandbox-local LanceDB before the run. FEAT-902 (watchfiles notes) + FEAT-903
  (textual polling notes) give a real cross-feature connection; `/research`
  produces findings/gaps/next-actions, `/ask` cites grounded chunks. Extended the
  `run_golden.sh` PLAN with an optional 4th prompt-override field for `/ask`'s
  free-text question.

**Remaining:** score the captured outputs against `tests/golden/RUBRIC.md`
(qualitative Layer-3 rubric pass — the structural baseline is now complete).
