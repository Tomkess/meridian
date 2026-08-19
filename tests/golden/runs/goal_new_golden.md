# Golden run — `/goal new`

**Captured:** 2026-08-19 · Meridian v0.3.0 · model `claude-sonnet-5`
**Fixture:** `tests/golden/project` (vision + `goal-01` "Zero-friction idea capture")
**Invocation:** `/goal new Make research retrievable — every PDF, link and screenshot a team collects should be findable by an agent months later`

Chosen because it *partially* overlaps `goal-01`. A skill that rubber-stamps it
fails the check that matters.

---

## Output

**Goal under consideration:** Make research retrievable — every PDF, link and
screenshot a team collects should be findable by an agent months later.

Running the six checks against the vision and `specs/goals/`.

**1. Alignment — pass.** The vision promises a workflow "any AI agent can read and
act on without losing context across sessions." Retrievable research is that
promise applied to material the team did not write. Traceable.

**2. Overlap — flag.** `goal-01` (Zero-friction idea capture) covers *getting things
in* within 60 seconds. This goal covers *getting things back out* months later.
They share the ingestion moment and diverge after it. That is a real seam, but it
is thin enough to be worth naming now: if you later find yourself writing specs
that could sit under either, the two should merge.

**3. Conflict — pass, with one tension.** `goal-01` optimises for speed at capture.
Retrievability usually wants structure at capture — tags, a source, a reason.
Those pull against each other. Not a blocker; a design constraint. Whatever serves
this goal must not add a step to capture.

**4. Scope — pass.** Not granular enough to be a spec: it implies extraction,
chunking, embedding, retrieval and provenance, which is several features. Not
broad enough to be the vision: it names one capability rather than an end state.

**5. Measurability — flag.** "Findable months later" is not observable as written.
Suggest: *a question answerable from ingested research returns the correct source
in the top three results, six months after ingestion.* That is testable against a
fixed question set and degrades visibly.

**6. Coverage — pass.** Scanning `specs/`: `FEAT-902` (m/draft) and `FEAT-903`
(l/in-progress) both touch research handling and currently sit under `goal-01`
by default rather than by decision. If you accept this goal, they should move —
otherwise `goal-01` accumulates work that has nothing to do with capture speed.

---

**Two concerns before I write anything:**

1. The overlap with `goal-01` is real but thin. I would write this as a separate
   goal. Push back if you would rather widen `goal-01` to "capture and recall" —
   that is defensible and means one fewer goal to keep honest.
2. `measurable_outcome` needs your number. I have proposed top-three at six
   months; if that is wrong, it is wrong now rather than in a year.

Next ID by scanning `specs/goals/`: `goal-01.md` exists, so the next is **`goal-02`**.

Confirm and I will write `specs/goals/goal-02.md`:

```yaml
---
id: goal-02
name: Research stays retrievable
status: active
created: 2026-08-19
horizon: 2-year
measurable_outcome: A question answerable from ingested research returns the correct
  source in the top three results six months after ingestion.
---
```

> Research a team collects should remain as reachable as the code it informed.
> Every PDF, link and screenshot ingested is retrievable by an agent long after
> whoever added it has forgotten it exists, with provenance intact so a retrieved
> claim can be traced to its source. Success is measured by retrieval quality
> against a fixed question set, not by how much has been ingested.

**Nothing written yet — awaiting your confirmation.**

---

## Scoring against RUBRIC.md

| # | Must-have | Score |
|---|---|---|
| 1 | Six checks by name with a result each | ✅ |
| 2 | Overlap explicitly compares against `goal-01` | ✅ |
| 3 | Coverage lists existing specs that would serve it | ✅ — FEAT-902, FEAT-903 |
| 4 | Confirmation requested before writing | ✅ |
| 5 | Frontmatter carries all six keys | ✅ |
| 6 | Next ID derived by scanning | ✅ |

| # | Should-have | Score |
|---|---|---|
| S1 | A goal that is really a feature is pushed back on | n/a — this one is correctly sized |
| S2 | `measurable_outcome` observable | ✅ — flagged the vague version and proposed a testable one |

**Result: 6/6 must, 1/1 applicable should.** The regression-critical behaviours are
check 2 (naming the overlapping goal rather than saying "no overlap") and check 6
(deriving the ID rather than guessing `goal-02`).
