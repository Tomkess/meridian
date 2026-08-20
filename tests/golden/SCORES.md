# Golden-Set Scores — Layer 3 AI Quality Eval

Scored against [`RUBRIC.md`](RUBRIC.md). Captures live in [`runs/`](runs/) and are
structurally gated by `tests/test_golden_structure.py` (31 passed / 0 skipped).

- **Date:** 2026-07-14
- **Capture:** `scripts/run_golden.sh` (isolated sandbox + clean `$HOME`, enriched corpus)
- **Models:** per-skill `model:` frontmatter (spec/breakdown/tasks/ask/research on `claude-sonnet-5`; `/research` synthesis sub-agent on `opus`)
- **Legend:** ✅ must-have present · ⚠️ should-have / partial · ❌ must-have absent

## Verdict: **PASS**

All must-haves ✅. The two earlier `/spec` partials (confidence `null`; idea→draft
transition not visible in the artifact) and the `/tasks` should-have (test tasks
batched at the end) were fixed in the skill prompts and re-captured — see
"Resolved follow-ups" below.

---

### `/spec` — FEAT-901 (xs/idea) → [spec_feat-901.md](runs/spec_feat-901.md)

| # | Must-have | Score |
|---|---|---|
| 1 | All 8 body sections present | ✅ (+ Related Research) |
| 2 | ≥ 2 ACs in Given/When/Then | ✅ (5 ACs, all G/W/T) |
| 3 | `confidence` set in frontmatter | ✅ `high` — /spec now self-assesses and sets it (never `null`), guarded by `test_confidence_resolved_not_null` |
| 4 | `status` → `draft` (or instruction) | ✅ `draft` — /spec runs the CLI transition without blocking; visible in the artifact, guarded by `test_idea_transitioned_to_draft` |
| S1 | Spike suggestion if low-conf m/l | n/a (xs) |
| S2 | `depends_on`/`enables` if found | ✅ correctly reports "none identified" (empty corpus) |

Quality note: the elaboration caught that a prior implementation already exists and
that two name-resolution strategies conflict — well above a template fill-in.

### `/breakdown` — FEAT-902 (m/draft) → [breakdown_feat-902.md](runs/breakdown_feat-902.md)

| # | Must-have | Score |
|---|---|---|
| 1 | Components table ≥ 3 rows | ✅ (7 rows) |
| 2 | Implementation Order, numbered | ✅ (5 steps) |
| 3 | Test Strategy present | ✅ |
| 4 | Effort label per component | ✅ (S/M/L) |
| S1 | XL flagged with split | n/a (no XL) |
| S2 | Effort sum ≤ `m` appetite | ✅ (overall M) |

### `/tasks` — FEAT-904 (m/draft, task-less) → [tasks_feat-904.md](runs/tasks_feat-904.md)

Rubric names FEAT-903, but that fixture ships a complete `tasks.md` (a no-op);
FEAT-904 is the task-less target so this is a genuine generation.

| # | Must-have | Score |
|---|---|---|
| 1 | Every task has a `Pre:` (incl. `Pre: none`) | ✅ (11 tasks; task 1 = `Pre: none`) |
| 2 | No forward `Pre: task N` reference | ✅ (all preconditions point backward) |
| 3 | Tasks reference an AC where applicable | ✅ (task 10 correctly = `AC: none`, supports a risk) |
| 4 | No task > 4h / split | ✅ |
| S1 | `[DECISION NEEDED]` on open questions | ✅ (task 1 flags schema_version int-vs-semver) |
| S2 | Test tasks interspersed | ✅ /tasks prompt now interleaves impl → test → impl → test (re-captured: 13 tasks alternating) |

### `/ask` — FEAT-902 ("key risks?") → [ask_feat-902.md](runs/ask_feat-902.md)

| # | Must-have | Score |
|---|---|---|
| 1 | Cites chunks / spec sections | ✅ (quotes `[FEAT-902 / watchfiles_notes.txt]`) |
| 2 | Gaps section present | ✅ ("What the research doesn't cover") |
| 3 | No speculation beyond sources | ✅ (grounded; flags single-source narrowness) |

### `/research` — FEAT-902 → [research_feat-902.md](runs/research_feat-902.md)

| # | Must-have | Score |
|---|---|---|
| 1 | Constraints section present | ✅ (risk table) |
| 2 | Cross-feature section present | ✅ (FEAT-903 shared polling core, cites `textual_polling_notes`) |
| 3 | Next actions ≥ 2 | ✅ (4 items) |
| S1 | Confidence bump if low+large | ✅ correct judgment — declined, held `medium` (single source) |

**Stale as of FEAT-025 (2026-08-20).** This capture predates resolvable citations. It
cites bare source names (`[watchfiles_notes]`), writes no file, and labels no
inferences — so it scores ❌ on all six must-haves of the new "citation discipline"
section in the rubric. Re-capture with `scripts/run_golden.sh research` (needs Ollama
+ the `claude` CLI; it enriches a corpus, which is why it was not run as part of the
FEAT-025 change) and re-score before the next release. Until then the guard is
`tests/test_research_persistence.py`, which holds the prompt contract, not the output.

---

## Resolved follow-ups (2026-07-14)

1. **`/spec` `confidence: null`** → fixed. Step 8 now self-assesses confidence and sets
   it (defaulting to `medium` when unsure) instead of ending the turn on an interactive
   question the headless run can't answer. Guarded by `test_confidence_resolved_not_null`.
2. **`/spec` idea→draft transition not observable** → fixed by the same change: because
   step 8 no longer blocks, step 9's `meridian close … --status draft` now runs, so the
   captured `spec.md` shows `status: draft`. Guarded by `test_idea_transitioned_to_draft`.
   (Root cause: in `claude -p` the model can't tell no user is present, so an interactive
   "what's your confidence?" question silently ended the run before the transition.)
3. **`/tasks` batched test tasks at the end** → fixed. The derive step now instructs
   interleaving each test task immediately after the implementation it covers. Re-captured
   `tasks_feat-904.md` alternates impl → test across all 13 tasks.
