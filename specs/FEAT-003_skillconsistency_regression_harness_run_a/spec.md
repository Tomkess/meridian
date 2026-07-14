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
id: feat-003
name: 'Skill-consistency regression harness: run a skill twice and diff output structure
  (sections + frontmatter) to catch ambiguous prompts, now that model routing changed'
scheduler: null
sources: []
status: in-progress
tags: []
updated: '2026-07-14'
---

## Progress (in-progress)

**Engine done + tested:** `scripts/skill_consistency.py` extracts a structural
fingerprint (top-level frontmatter keys + normalized `##`/`###` headings, order
preserved) and compares two runs, reporting missing/extra sections, frontmatter
key drift, and reordering. Heading comparison ignores prose, inline numbering
("1. Problem"), and trailing punctuation so only genuine structural drift is
flagged. CLI: `--compare a.md b.md` (exit 0 consistent / 1 drift) and
`--skill/--feat` (runs a skill twice via `claude` and compares). 11 unit tests in
`tests/test_skill_consistency.py`; `--compare` exit codes verified end-to-end.

**Wired into CI (2026-07-14, model-free):** the `--compare` engine now guards
structural drift between the bundled skills (`meridian/skills/commands/`) and the
in-repo `.claude/commands/` copies — two ways:
- `tests/test_skill_sync.py` (16 tests) reuses `compare_texts` as a library, so
  the invariant is enforced in the existing `pytest` step and locally.
- A dedicated CI step in `.github/workflows/test.yml` runs the actual
  `scripts/skill_consistency.py --compare` CLI over every skill pair, exercising
  the FEAT-003 entry point + exit-code contract and emitting `::error` on drift.

**Remaining (needs interactive `claude`):** run the `--skill` twice-over mode
against real skill runs to catch prompt ambiguity after prompt edits — model-gated,
runs interactively, not in CI.
