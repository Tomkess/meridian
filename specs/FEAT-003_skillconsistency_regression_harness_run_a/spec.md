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

**Remaining (needs interactive `claude`):** wire into CI / run the `--skill` mode
against real skill runs to catch prompt ambiguity after prompt edits.
