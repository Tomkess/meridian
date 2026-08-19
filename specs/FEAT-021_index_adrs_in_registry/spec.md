---
abandoned_at: null
abandoned_reason: null
appetite: xs
blocked_at: null
blocked_by: null
confidence: high
created: '2026-08-19'
cycle: null
depends_on: []
enables: []
goal: '~'
id: feat-021
name: Index architecture decision records in REGISTRY.md
status: done
tags: []
updated: '2026-08-19'
---

## Summary

`rebuild_registry()` scans feature directories and `specs/goals/*.md`, but never
`specs/decisions/`. Six ADRs exist in this repo and not one of them is visible to
any skill: `REGISTRY.md` is what `/idea`, `/spec` and `/breakdown` read to orient
themselves, so a decision that has already been made and written down cannot be
cited. ADRs are write-only.

The fix is a third section in the generated index — number, title, status, and a
relative link a skill can open — placed after Features and Goals so the primary
content stays at the top of a file that is read top to bottom.

The care goes into parsing. Two ADR shapes exist in the wild: `001`–`005` carry
YAML frontmatter with `status: accepted`, while `006` — written by the current
`/decision` template — carries no frontmatter at all and puts the state in a
`**Status:** Accepted` line. Both must read, and neither may be able to break
the rebuild: FEAT-013 established this exact failure shape with a malformed goal
file, where the rebuild raised *after* a spec had already been written to disk,
leaving a stale registry and a traceback.

## Appetite

`xs` — one scan function, one section, and the degradation tests. Not a schema.

## Acceptance Criteria

### Indexing

- **AC1** — `scan_decisions()` in `meridian/specs.py` indexes every `*.md` in
  `specs/decisions/`, sorted by filename, and `rebuild_registry()` renders them
  as a `## Decisions` section of `REGISTRY.md`. The signature of
  `rebuild_registry()` is unchanged — all six call sites in `cli.py` keep working.
- **AC2** — Each row carries the ADR number, its title, its status, and a link
  relative to `REGISTRY.md` (`decisions/006-....md`), so a skill can open the
  record from the index without a search.
- **AC3** — The section is emitted after `## Features` and `## Goals`. Features
  are the primary content of the file and a skill reads it top to bottom.
- **AC4** — An empty or absent `specs/decisions/` yields the section with a
  placeholder row, exactly as `## Goals` already does. Most projects have no ADRs.

### Deriving title and status

- **AC5** — The title comes from the first `# ` heading with its `NNN —` prefix
  stripped (`ADR_TITLE_PREFIX`), since neither ADR shape puts a title in
  frontmatter; a frontmatter `title` and then the filename stem stand behind it.
- **AC6** — The status comes from frontmatter `status` when present, otherwise
  from a `**Status:**` line (`ADR_STATUS_LINE`) — the shape `/decision` writes.
  It is lower-cased so a skill filtering for `superseded` need not guess the case.
- **AC7** — The number comes from the filename's leading digits, falling back to
  the digits in a frontmatter `id` such as `adr-003`.

### Degradation

- **AC8** — A decision file with broken YAML, no heading, or unreadable bytes is
  never fatal. `_decision_entry()` catches it, warns on stderr in the style of
  `all_specs()`, and emits a row marked `unparseable` — visible rather than
  silently dropped. Every other ADR, and the rest of the registry, still writes.
- **AC9** — ADR rows go through `_cell()`, so a `|` in a heading cannot shift the
  columns of a file the AI reads as a source of truth (FEAT-018 AC10).

## Scope

`meridian/specs.py` (`scan_decisions`, `_decision_entry`, `rebuild_registry`,
`ADR_NUMBER`, `ADR_HEADING`, `ADR_TITLE_PREFIX`, `ADR_STATUS_LINE`),
`tests/test_specs.py` (`TestRegistryDecisions`).

## Out of Scope

- **Embedding ADRs in the vector index.** `meridian search` would then answer
  "what did we decide about X" semantically. Worth doing, but it touches the
  shared LanceDB store and is a bigger bet than an index row.
- **Teaching `/spec` and `/breakdown` to consult the section.** The prompts have
  golden runs behind them; changing them is a Layer-3 re-capture, not an `xs`.
- **Normalising the two ADR shapes on disk.** Reading both is cheap; rewriting
  six committed records to satisfy a parser is not.
- **Guarding the goals scan the same way.** `rebuild_registry()` still calls
  `frontmatter.load` on `specs/goals/*.md` unguarded, so a malformed goal can
  still raise. Same fix, different feature — flagged, not smuggled in here.

## Key Risks

- **Status is free text.** `accepted`, `superseded`, `proposed` and anything else
  an author types all pass through. Deliberate: ADR status is not a state machine
  in this codebase, and validating it would reject records that already exist.
- **A heading-less ADR gets a title derived from its filename.** Readable
  (`004-cli-owns-ops.md` → `cli owns ops`) but not the author's words. The
  alternative — no row — is worse, because the record then stays invisible.

## Verification

Rendered against this repo's own six ADRs, both shapes parsed:

```
| 001 | Modular chainable skills over monolithic pipeline | accepted | [001-…](decisions/001-…) |
| 006 | Screenshots: the CLI captures, the agent describes | accepted | [006-…](decisions/006-…) |
```

`001` supplied its status from frontmatter, `006` from its `**Status:**` line.
