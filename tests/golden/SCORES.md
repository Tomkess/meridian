# Golden-Set Scores — Layer 3 AI Quality Eval

Scored against [`RUBRIC.md`](RUBRIC.md). Captures live in [`runs/`](runs/) and are
structurally gated by `tests/test_golden_structure.py` (31 passed / 0 skipped).

- **Date:** 2026-07-14
- **Capture:** `scripts/run_golden.sh` (isolated sandbox + clean `$HOME`, enriched corpus)
- **Models:** per-skill `model:` frontmatter (spec/breakdown/tasks/ask/research on `claude-sonnet-5`; `/research` synthesis sub-agent on `opus`)
- **Legend:** ✅ must-have present · ⚠️ should-have / partial · ❌ must-have absent

## Verdict: **PASS**

All must-haves ✅ except two ⚠️ partials on `/spec` (confidence + status), neither a
hard ❌. No skill prompt blocks release; the two `/spec` items are logged as
opportunistic fixes below.

---

### `/spec` — FEAT-901 (xs/idea) → [spec_feat-901.md](runs/spec_feat-901.md)

| # | Must-have | Score |
|---|---|---|
| 1 | All 8 body sections present | ✅ (+ Related Research) |
| 2 | ≥ 2 ACs in Given/When/Then | ✅ (5 ACs, all G/W/T) |
| 3 | `confidence` set in frontmatter | ⚠️ present but `null` — skill did not elicit a value (acceptable for xs, ideally prompted) |
| 4 | `status` → `draft` (or instruction) | ⚠️ file still `status: idea` — the idea→draft CLI transition is emitted to stdout, not reflected in the captured artifact |
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
| S2 | Test tasks interspersed | ⚠️ mostly (task 5 mid; tests cluster 8–11) |

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

---

## Follow-ups (opportunistic, non-blocking)

1. `/spec` leaves `confidence: null` — consider having the skill elicit or default a
   confidence value during idea→draft elaboration.
2. The `/spec` idea→draft transition isn't visible in the captured `spec.md` artifact
   (it runs via the CLI to stdout). Either capture stdout for `/spec` too, or assert
   the transition a different way, so the rubric's must-have #4 is observable.
3. `/tasks` batches most test tasks at the end (S2). Minor — could nudge the prompt to
   interleave test tasks with their implementation tasks.
