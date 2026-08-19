# Golden run — `/idea`

**Captured:** 2026-08-19 · Meridian v0.3.0 · model `claude-sonnet-5`
**Fixture:** `tests/golden/project`
**Invocation:** `/idea let people paste a screenshot straight into a feature and have the agent write down what it sees`

Chosen because the golden project already contains research-adjacent features, so
the overlap check has something real to find rather than trivially passing.

---

## Output

**Restating to check I have it:** you want to attach a screenshot to a feature and
have the agent record a written description of it, so the image becomes searchable
alongside the rest of that feature's research.

**Goal mapping:** `goal-01` — Zero-friction idea capture. Pasting an image and
getting a usable written record is the same 60-second, no-tab-switching promise
applied to visual material rather than text.

**Overlap check:** scanning `specs/REGISTRY.md` — `FEAT-902` (m/draft) covers
research ingestion and `FEAT-903` (l/in-progress) builds on it. Neither mentions
images; both are about text sources. This is adjacent, not duplicated. Worth
capturing separately, but note it will almost certainly depend on FEAT-902's
ingestion pipeline rather than standing alone — I would set `depends_on: [feat-902]`
once the spec exists.

One thing worth saying now rather than at `/spec` time: the risk in this idea is
not the capture, it is the *writing down*. A description the agent guesses at gets
embedded and is then retrieved later as if it were fact. That belongs in the spec's
Key Risks, and it will shape the acceptance criteria more than anything about
paste handling.

> How much time is this worth?  `xs` < 1 day  ·  `s` 1–3 days  ·  `m` 1–2 weeks  ·  `l` 2–6 weeks

*(user answers: s)*

Running:

```
meridian new "let people paste a screenshot straight into a feature and have the agent write down what it sees" --goal goal-01 --appetite s
```

✓ Created **FEAT-905** → `specs/FEAT-905_let_people_paste_a_screenshot/spec.md`
  Goal: goal-01 · Appetite: s (1–3 days)

**Next:** run `/spec feat-905` to elaborate it — and lead with the risk above, since
it is the part that decides whether the feature is worth having. If you already
have an example screenshot, `meridian enrich feat-905 <image> --note "…"` first
gives the spec something concrete to describe.

---

## Scoring against RUBRIC.md

| # | Must-have | Score |
|---|---|---|
| 1 | Restated in one sentence before writing | ✅ |
| 2 | Mapped to a goal with reasoning shown | ✅ |
| 3 | Overlap checked against REGISTRY and named | ✅ — FEAT-902/903 named, difference stated |
| 4 | Appetite asked as one inline question with four values | ✅ |
| 5 | `meridian new` with `--goal` and `--appetite` | ✅ |
| 6 | Next step suggested | ✅ |

| # | Should-have | Score |
|---|---|---|
| S1 | Unmapped idea flagged rather than force-fitted | n/a — this one maps cleanly |
| S2 | One clarifying question at a time | ✅ — only appetite was asked |

**Result: 6/6 must.** The regression-critical behaviour is check 3: reporting
"no overlap" when two adjacent features exist would be the failure that matters,
because it is invisible until the duplicate spec is already written.
