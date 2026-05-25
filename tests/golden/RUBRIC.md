# Golden-Set Rubric — Layer 3 AI Quality Evaluation

Run this eval before every breaking change to a skill prompt, and at minimum once per
release. Capturing outputs and scoring them is the only way to catch LLM-quality
regressions that unit tests cannot see.

---

## Fixtures

Three representative features in `tests/golden/project/specs/`:

| Feature | Appetite | Status | Tests |
|---|---|---|---|
| FEAT-901 xs_idea | xs | idea | `/spec` |
| FEAT-902 m_draft | m | draft | `/breakdown`, `/ask`, `/research` |
| FEAT-903 l_in_progress | l | in-progress | `/tasks` (regenerate), `/research` |

---

## How to run

```bash
# From the repo root, point Claude at the golden project:
cd tests/golden/project

# Run each skill and capture output to tests/golden/runs/
# (Claude Code skill invocations — run interactively)
```

Use `scripts/run_golden.sh` to launch each skill in turn. Outputs are written to
`tests/golden/runs/<skill>_<feat>.md`. Commit those files so `test_golden_structure.py`
can assert structure on every future CI run.

---

## Scoring rubric

Score each output: ✅ must-have present · ⚠️ should-have missing · ❌ must-have absent

### `/spec` on FEAT-901 (xs/idea → draft)

| # | Must-have | Score |
|---|---|---|
| 1 | All 8 body sections present (Summary, Appetite, Acceptance Criteria, Scope, Out of Scope, Key Risks, Dependencies, Open Questions) | |
| 2 | At least 2 ACs in Given/When/Then format | |
| 3 | `confidence` field set in frontmatter | |
| 4 | `status` transitioned to `draft` (or instruction given) | |

| # | Should-have | Score |
|---|---|---|
| S1 | Spike suggestion if confidence=low on m/l appetite | |
| S2 | `depends_on`/`enables` populated if search found relationships | |

### `/breakdown` on FEAT-902 (m/draft)

| # | Must-have | Score |
|---|---|---|
| 1 | Components table present with ≥ 3 rows | |
| 2 | Implementation Order section present with numbered steps | |
| 3 | Test Strategy section present | |
| 4 | Each component has an effort label (XS/S/M/L/XL) | |

| # | Should-have | Score |
|---|---|---|
| S1 | XL item flagged with split suggestion | |
| S2 | Effort labels map to appetite (sum should not exceed `m`) | |

### `/tasks` on FEAT-903 (l/in-progress — regenerate)

| # | Must-have | Score |
|---|---|---|
| 1 | Every task has a `Pre:` line (including `Pre: none` for first task) | |
| 2 | No `Pre: task N` where task N is defined after the current task | |
| 3 | Tasks reference at least one AC each where applicable | |
| 4 | No task estimated > 4 hours (if flagged: split into subtasks) | |

| # | Should-have | Score |
|---|---|---|
| S1 | `[DECISION NEEDED]` tag on tasks with unresolved open questions | |
| S2 | Test tasks interspersed with implementation tasks (not batched at end) | |

### `/ask` on FEAT-902 (with a question like "what are the risks?")

| # | Must-have | Score |
|---|---|---|
| 1 | Answer cites specific chunks or spec sections | |
| 2 | Gaps section present ("no research enriched yet" or actual gap) | |
| 3 | Does not speculate beyond what's in the spec/sources | |

### `/research` on FEAT-902 or FEAT-903

| # | Must-have | Score |
|---|---|---|
| 1 | Constraints section present | |
| 2 | Cross-feature section present (mentions other features or notes "none found") | |
| 3 | Next research actions list present (≥ 2 items) | |

| # | Should-have | Score |
|---|---|---|
| S1 | Confidence bump suggestion if low+large | |

---

## Consistency check

Run `/spec` on FEAT-901 twice in separate Claude sessions. Compare outputs:
- Sections must be structurally identical (same 8 headings, same frontmatter fields)
- Wording may differ — that's acceptable
- If sections differ: the skill prompt is ambiguous → tighten it

---

## Regression gate

When a skill prompt file (`.claude/commands/*.md`) changes:
1. Re-run the golden set for the changed skill
2. Diff output structure against the committed runs in `tests/golden/runs/`
3. Structural changes (sections added/removed, fields changed) must be deliberate
4. Update `tests/golden/runs/` and commit the new baseline

---

## Pass/fail threshold

- All must-haves ✅ → **pass**
- Any must-have ❌ → **fail** — fix the skill prompt before releasing
- Should-haves ⚠️ → log as known gap, fix opportunistically
