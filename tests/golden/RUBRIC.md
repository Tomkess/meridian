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

### `/vision` on the golden project (write-side, destructive)

`/vision <text>` rewrites the north star in place. It is the only skill that
overwrites a file whose previous contents are not recoverable from anywhere else,
which is why it is scored strictly.

| # | Must-have | Score |
|---|---|---|
| 1 | Existing vision is shown before any rewrite | |
| 2 | Result is exactly one paragraph — no bullets, no headings inside it | |
| 3 | The "How to use this file" section below the paragraph survives intact | |
| 4 | Describes an end state, not a means or a roadmap | |
| 5 | Confirms what was saved, quoting the new text | |

| # | Should-have | Score |
|---|---|---|
| S1 | A too-long or tactical draft is tightened and the tightened version offered *before* writing | |
| S2 | No implementation nouns (specific tools, file formats) in the paragraph | |

### `/goal new` on the golden project

| # | Must-have | Score |
|---|---|---|
| 1 | All six validation checks appear by name with a pass/flag/concern result each | |
| 2 | Overlap check explicitly compares against `goal-01` | |
| 3 | Coverage check lists existing idea/draft specs that would serve the goal | |
| 4 | Confirmation is requested before writing | |
| 5 | Frontmatter carries `id`, `name`, `status`, `created`, `horizon`, `measurable_outcome` | |
| 6 | Next goal ID derived by scanning `specs/goals/`, not assumed | |

| # | Should-have | Score |
|---|---|---|
| S1 | A goal that is really a feature is pushed back on as too granular | |
| S2 | `measurable_outcome` is observable, not aspirational | |

### `/idea` on the golden project

| # | Must-have | Score |
|---|---|---|
| 1 | Idea restated in one sentence before anything is written | |
| 2 | Mapped to a goal with the reasoning shown in one sentence | |
| 3 | Overlap against REGISTRY checked and named if found | |
| 4 | Appetite asked as a single inline question with the four values | |
| 5 | `meridian new` invoked with `--goal`, and `--appetite` when given | |
| 6 | Next step suggested (`/spec` or `enrich`) | |

| # | Should-have | Score |
|---|---|---|
| S1 | An idea matching no goal is flagged rather than force-fitted | |
| S2 | Only one clarifying question is asked at a time | |

### `/enrich` on the golden project (write-side, corpus-polluting)

The audit singled this out: `/enrich` writes prose into `sources/*.notes.md` that
every later `/ask` retrieves **as fact**. A guess embedded here is indistinguishable
from research forever after.

| # | Must-have | Score |
|---|---|---|
| 1 | The image is described from what is actually visible — no inference about intent | |
| 2 | Uncertainty is marked as uncertainty, never asserted | |
| 3 | The user's note is preserved verbatim, not paraphrased | |
| 4 | Sidecar carries the image reference so a retrieved chunk leads back to the file | |
| 5 | `described_by` records which model produced the reading | |

| # | Should-have | Score |
|---|---|---|
| S1 | Visible text is quoted exactly rather than summarised | |
| S2 | The reading is ordered by prominence, not raster order | |

### `/decision` on the golden project

| # | Must-have | Score |
|---|---|---|
| 1 | Next ADR number derived by scanning `specs/decisions/` | |
| 2 | All four sections present: Decision, Alternatives Considered, Consequences, Status | |
| 3 | At least two genuine alternatives, each with pros *and* cons | |
| 4 | The decision paragraph states what was decided and why in one paragraph | |
| 5 | Filename is `NNN-<slug>.md` | |

| # | Should-have | Score |
|---|---|---|
| S1 | Consequences include at least one negative — an ADR with no downside is not a decision | |
| S2 | Context names the feature IDs or area affected | |

### `/prior-art` — rubric only, no captured run

`/prior-art` answers "have I solved this before, in another repo?". It is cross-project
by definition, and the golden fixture is a single project sharing nothing with anything,
so a run captured against it can only ever exercise the empty case — the one branch that
already has a unit test (`tests/test_prior_art.py::test_empty_prior_art_is_stated_not_silent`).
Capturing the branch that matters needs three things the harness does not have: a second
fixture project committed under `tests/golden/`, a corpus enriched into *both* projects'
rows in one sandbox store, and a `projects.toml` in the sandbox `MERIDIAN_HOME` mapping the
second slug to its path so `feat_path` resolves. That is a `run_golden.sh` change, not a
capture, and it is the right next step before this skill's prompt is edited again.

Must-have 3 is the one to watch. It is a prompt-level guard on the failure this skill makes
possible — a conclusion reached in another repo, under another repo's constraints, quietly
adopted here as settled. Nothing downstream catches it: the answer reads exactly like a
correct one.

| # | Must-have | Score |
|---|---|---|
| 1 | Local research and prior art are reported as separate sections, never merged | |
| 2 | Every prior-art claim names its project in the same sentence (`portfolio-management` concluded X) | |
| 3 | No foreign conclusion is stated as this project's own — no "we decided", no bare "the research shows" | |
| 4 | Each resolvable hit gives the absolute `feat_path` to read | |
| 5 | An unresolvable hit is still reported, with its reason, not dropped | |
| 6 | Empty prior art is stated plainly, not left as silence | |

| # | Should-have | Score |
|---|---|---|
| S1 | Says what does *not* transfer — the other repo's differing scale, stack or constraints | |
| S2 | A foreign `FEAT-NNN` is labelled `<project>/FEAT-NNN`, never resolved against local specs | |

### `/brief` — rubric only, no captured run

`/brief` summarises a source document into `summaries/`. It has scoring criteria
below but **no golden run**, because the golden project contains no source document
to summarise and inventing one would test the fixture rather than the skill.
Capturing this needs a real paper added to `tests/golden/research_assets/`.

| # | Must-have | Score |
|---|---|---|
| 1 | Output is under 550 words | |
| 2 | Fits one A4 page when rendered | |
| 3 | Claims are attributable to the source, not the model's prior knowledge | |
| 4 | Written to `summaries/`, not to the spec body | |

---

## Consistency check

Run `/spec` on FEAT-901 twice in separate Claude sessions. Compare outputs:
- Sections must be structurally identical (same 8 headings, same frontmatter fields)
- Wording may differ — that's acceptable
- If sections differ: the skill prompt is ambiguous → tighten it

---

## Regression gate

When a skill prompt file (`.claude/commands/meridian/*.md`) changes:
1. Re-run the golden set for the changed skill
2. Diff output structure against the committed runs in `tests/golden/runs/`
3. Structural changes (sections added/removed, fields changed) must be deliberate
4. Update `tests/golden/runs/` and commit the new baseline

---

## Pass/fail threshold

- All must-haves ✅ → **pass**
- Any must-have ❌ → **fail** — fix the skill prompt before releasing
- Should-haves ⚠️ → log as known gap, fix opportunistically
