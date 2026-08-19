# Golden run — `/decision`

**Captured:** 2026-08-19 · Meridian v0.3.0 · model `claude-sonnet-5`
**Fixture:** `tests/golden/project` (`specs/decisions/` contains `001-…`, `002-…`)
**Invocation:** `/decision store research embeddings in one shared vector database rather than one per project`

---

## Output

Scanning `specs/decisions/` — `001` and `002` exist, so this is **003**.

Writing `specs/decisions/003-shared-vector-store.md`:

---

# 003 — One shared vector store, scoped by project

**Status:** Accepted
**Date:** 2026-08-19
**Context:** FEAT-902, FEAT-903 — research ingestion and retrieval

## Decision

Research embeddings for every project live in a single LanceDB store at
`~/.meridian/lancedb`, with a `project` column on every row scoping reads and
writes. The alternative — one store per repository — gives isolation for free but
permanently forecloses cross-project retrieval, which is the capability most likely
to justify this system existing. A column is reversible; a directory layout is not.

## Alternatives Considered

| Option | Pros | Cons |
|---|---|---|
| **Shared store, project column** (chosen) | Cross-project search stays possible; one store to back up; one schema to migrate | Every write path must scope correctly, or one project reads another's research; a bug is cross-tenant rather than local |
| One store per repository | Isolation by construction; a corrupt store affects one project | Cross-project retrieval impossible without a federation layer; N stores to migrate on schema change; no way to ask "where have I seen this before" |
| A hosted vector service | No local resource cost; scales past one machine | Adds a network dependency and an account to a tool whose premise is local, file-backed and offline-capable |

## Consequences

- Every query must pass a project scope. Forgetting is a silent correctness bug,
  not a crash — a search returns another project's research and looks fine.
- A destructive operation on the store is cross-project by default. Rebuilds must
  delete only the current project's rows, never the table.
- Retrieved rows must never resolve a foreign feature ID against local specs, or a
  result will be labelled with the wrong feature's name.
- Backups get simpler: one directory covers every project.
- If cross-project retrieval turns out never to be used, this decision cost
  isolation for nothing, and reverting means re-embedding every corpus.

---

✓ Written to `specs/decisions/003-shared-vector-store.md`

Worth noting: consequence two is not hypothetical. A shared store makes
"rebuild the index" mean something different from what it looks like it means, and
that is the failure mode to design against from the start.

---

## Scoring against RUBRIC.md

| # | Must-have | Score |
|---|---|---|
| 1 | Next ADR number derived by scanning | ✅ — 001, 002 present → 003 |
| 2 | All four sections present | ✅ |
| 3 | Two or more genuine alternatives with pros *and* cons | ✅ — three, each with both |
| 4 | Decision paragraph states what and why | ✅ |
| 5 | Filename is `NNN-<slug>.md` | ✅ |

| # | Should-have | Score |
|---|---|---|
| S1 | Consequences include a negative | ✅ — four of five are costs |
| S2 | Context names affected features | ✅ — FEAT-902, FEAT-903 |

**Result: 5/5 must, 2/2 should.**

The regression-critical behaviour is should-have S1. An ADR whose Consequences
section lists only benefits has not recorded a decision — it has recorded a
preference, and it gives a future reader nothing to weigh when the trade-off comes
due. A prompt edit that makes the output more confident would plausibly drop the
negatives first.
