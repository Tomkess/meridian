# Golden run — `/vision`

**Captured:** 2026-08-19 · Meridian v0.3.0 · model `claude-haiku-4-5-20251001`
**Fixture:** `tests/golden/project`
**Invocation:** `/vision Meridian should make sure that every team using AI agents can ship software faster by keeping all their specs and tasks and research in files that agents read, so nothing is lost between sessions and everyone stays aligned on what matters`

This is the destructive case: a draft that is too long and too tactical. The skill
must offer a tightened version *before* writing anything.

---

## Output

Here is the current north star:

> Meridian is the development OS for AI-native teams: capture every idea, shape it
> into a spec, plan the work, build with confidence, and ship — all within a single,
> file-backed workflow that any AI agent can read and act on without losing context
> across sessions.

Your draft is longer than one paragraph should carry, and it names means rather
than an end state — "keeping all their specs and tasks and research in files" is
*how* Meridian works, not what the world looks like when it has won. Three phrases
are tactical: `specs and tasks and research`, `in files`, `between sessions`.

Tightened, for your approval before I write:

> Teams working with AI agents never lose the thread. Every idea, decision and piece
> of research stays where both people and agents can find it, so context survives
> across sessions, tools and years — and what the team is building remains legible
> to everyone building it.

This keeps your intent — continuity, alignment, nothing lost — and drops the
mechanism, which will outlive any particular file format.

Two things I deliberately did not carry over:

- **"ship software faster"** — speed is a consequence, and a vision that claims it
  invites arguing about benchmarks. The end state is *not losing the thread*; speed
  follows.
- **"in files"** — the strongest constraint in the current vision, but it belongs in
  `STEERING.md` as an architectural rule. A north star that names a storage format
  stops being true the moment the format changes.

Say the word and I will write it. If you would rather keep "file-backed" as a
first-class promise, say so — it is a defensible choice, and I will fold it back in
rather than argue.

**Nothing has been written yet.** `specs/VISION.md` is unchanged.

---

## Scoring against RUBRIC.md

| # | Must-have | Score |
|---|---|---|
| 1 | Existing vision shown before any rewrite | ✅ |
| 2 | Result is exactly one paragraph | ✅ |
| 3 | "How to use this file" section survives | ✅ (nothing written) |
| 4 | End state, not means | ✅ — mechanism deliberately dropped |
| 5 | Confirms what was saved | ✅ — states plainly that nothing was |

| # | Should-have | Score |
|---|---|---|
| S1 | Too-long draft tightened and offered before writing | ✅ |
| S2 | No implementation nouns in the paragraph | ✅ |

**Result: 7/7.** The behaviour worth protecting in regression is the refusal to
write on the first turn. A future prompt edit that makes `/vision` write
immediately would still look plausible in isolation and would silently destroy an
unrecoverable file.
