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
