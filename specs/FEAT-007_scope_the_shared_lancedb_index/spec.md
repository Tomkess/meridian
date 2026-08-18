---
abandoned_at: null
abandoned_reason: null
appetite: s
blocked_at: null
blocked_by: null
confidence: high
created: '2026-08-18'
cycle: null
depends_on: []
enables: []
goal: '~'
id: feat-007
name: Scope the shared LanceDB index per project so 10+ repos stop clobbering each
  other
scheduler: null
sources: []
status: in-progress
tags: []
updated: '2026-08-18'
---

## Summary

Meridian's vector index is global by default but has no notion of which project a
chunk came from. Every installed project writes into the same LanceDB directory
(`~/.meridian/lancedb`) and the same table (`chunks`), and rows carry only
`feat_id`, `source_name`, `chunk_idx`, `text`, `vector`.

This was invisible with one project. With 10+ installs it produces three distinct
failures, in descending severity:

**1. `meridian index` destroys every other project's index.**
`reindex_all()` unconditionally drops the shared table before rebuilding, then
re-adds only the current repo's sources:

```python
if "chunks" in db.table_names():
    db.drop_table("chunks")
```
`meridian/enrich.py:645`

Net effect: at any moment only the most-recently-indexed project has a working
`meridian search` / `/ask`. Every other project silently returns nothing, or
returns whatever survived. The failure is silent — no error, no warning, and the
data loss is invisible until someone searches and gets an empty result.

**2. Search leaks across projects.**
`meridian search "query"` passes `feat_id_filter=None` unless `--feat` is given
(`meridian/cli.py:563`), so the ANN query runs over the whole table. Results from
unrelated repos come back unlabeled, and `format_results()` resolves the
`feat_id` against the *local* `specs_path` (`meridian/search.py:109`) — so a
foreign `FEAT-003` is rendered with the local FEAT-003's name. Wrong provenance
presented as fact, which is worse than a missing result. This also reaches
`/ask`, `/research`, and `/brief`, all of which consume the same pipeline.

**3. Upsert collisions.**
`upsert_chunks()` deletes on `feat_id = X AND source_name = Y`
(`meridian/enrich.py:195`). Same feature number plus same filename across two
repos — e.g. `FEAT-001` + `notes.md` — means enriching in one repo deletes the
other's chunks. Narrower than (1), but likely given every project starts at
FEAT-001 and filenames repeat.

The fix is one new dimension: a `project` identity written on every row, applied
to deletes, and applied as the default search filter. That same column is what
later makes deliberate cross-project queries possible (routing a captured idea to
the right repo), so this is not merely defensive — it is the missing key.

## Appetite

`s` — 1–3 days. Contained: one new config field, one schema column, three call
sites, one migration path, plus tests. If it grows past that (e.g. into a global
project registry or cross-project routing UI), stop and split.

## Acceptance Criteria

### Project identity

- **AC1** — `MeridianConfig` gains a `project: str` field, resolved by
  `load_config()` from `[meridian] project` in `.meridian.toml`.
- **AC2** — When `project` is absent from `.meridian.toml`, it defaults to a slug
  derived from the repo root directory name (lowercase, non-alphanumerics
  collapsed to `-`, trimmed). Resolution is pure and deterministic — same path
  always yields the same slug, with no filesystem or git calls.
- **AC3** — The slug is validated on load: non-empty after slugification. A
  directory name that slugifies to empty (e.g. `___`) falls back to a stable
  literal (`unknown-project`) rather than raising, so a weird path never bricks
  the CLI.
- **AC4** — `meridian init` writes an explicit `project = "<slug>"` line into the
  generated `.meridian.toml`, so the value is visible and editable rather than
  implicit.
- **AC5** — Two different repo paths whose directory names are identical (e.g.
  `~/a/meridian` and `~/b/meridian`) produce the same default slug. This is
  accepted and documented, not solved: the user resolves it by setting `project`
  explicitly. Covered by
  `test_config.py::test_identical_directory_names_collide_by_design`.
- **AC5b** — **NOT IMPLEMENTED.** The original AC also asked that `meridian
  index` warn when it finds rows for the current slug that originate from a
  different `root` path. Detecting that requires storing each row's repo root,
  i.e. a second schema column beyond `project` — real scope on top of an `s`
  appetite, and speculative until someone actually hits the collision. Deferred
  deliberately rather than quietly dropped; the slug collision itself is
  documented in `CLAUDE.md` with the explicit-`project` remedy.

### Storage

- **AC6** — The `chunks` table schema gains a `project` (string) column, written
  on every row by `upsert_chunks()`.
- **AC7** — `upsert_chunks()` takes the project slug as an explicit parameter (not
  read from a global), and its delete predicate is
  `project = P AND feat_id = X AND source_name = Y`. The existing single-quote
  escaping (B1) is applied to the project value too.
- **AC8** — `reindex_all()` no longer drops the table. It deletes only rows where
  `project = <current project>`, then re-adds the current project's sources.
  Other projects' rows are untouched, verified by a test that indexes project A,
  indexes project B, then asserts A's chunks still resolve.
- **AC9** — Opening a table that predates this change (no `project` column) is
  detected by schema inspection, not by exception handling.

### Migration

- **AC10** — On detecting a pre-`project` table, Meridian does **not** silently
  reuse or silently wipe it. `meridian index` recreates the table with the new
  schema and reindexes the current project, printing an explicit notice that
  other projects must each run `meridian index` once to repopulate.
- **AC11** — `meridian search` / `semantic_search()` against a pre-`project`
  table returns no results and prints the same one-line remediation hint, rather
  than erroring or returning unscoped rows.
- **AC12** — Migration is lossless in principle: chunks are derived data,
  rebuildable from each feature's `sources/`. The spec states this explicitly so
  the recreate-and-reindex path is understood as recovery, not destruction.
- **AC12b** — *Added during implementation.* The recovery instruction must not
  itself cause collateral damage. Plain `meridian index` also rewrites
  `REGISTRY.md`, so telling a user to run it in nine other repos would leave nine
  unrelated projects with modified tracked files they never asked to change.
  `meridian index --vectors-only` rebuilds only the vector rows and leaves
  `REGISTRY.md` alone; the migration notice points at that flag. Covered by
  `test_cli.py::test_vectors_only_leaves_registry_untouched`.

### Recovery procedure

After a migration, each other project repopulates its own rows with:

```
cd <project> && meridian index --vectors-only
```

Do **not** use plain `meridian index` for this — see AC12b. Recovery is
per-project and safe to run in any order: with a non-legacy schema in place,
`reindex_all()` takes the scoped-delete path and touches only that project's
rows.

### Search

- **AC13** — `semantic_search()` filters to `cfg.project` by default. Existing
  callers (`/ask`, `/research`, `/brief`, `meridian search`) inherit the scoping
  with no signature change at their call sites.
- **AC14** — `meridian search` gains `--all-projects` to opt out of the scoping
  and query across every indexed repo.
- **AC15** — When `--all-projects` is used, each result line is prefixed with its
  project slug, and `feat_display_name()` is **not** applied to foreign rows —
  a foreign `FEAT-003` renders as `other-repo/FEAT-003`, never resolved against
  the local specs directory.
- **AC16** — `--feat` and `--all-projects` compose: filtering to a feature ID
  across all projects is a valid query and returns matches from each.
- **AC17** — The ANN `where` clause is built with the same quote-escaping applied
  to `feat_id` and `project`, so a slug containing an apostrophe cannot break or
  inject into the predicate.

### Regression safety

- **AC18** — A test asserts the exact failure this feature fixes: index project A,
  index project B, then confirm A's chunks are still retrievable and that a
  search in A returns zero rows belonging to B.
- **AC19** — `test_contracts.py` passes. *Corrected during implementation:* the
  contract runs one direction only — every flag referenced in skill markdown
  must exist in `meridian <subcmd> --help`, not the reverse. A new CLI flag
  therefore needs no skill-markdown change, and `--all-projects` stays out of
  the skills (see Open Questions, now resolved as CLI-only).
- **AC20** — Bundled skills under `meridian/skills/commands/` and the dogfooded
  copies under `.claude/commands/meridian/` stay byte-identical, per the existing
  skill-sync drift guard.
- **AC21** — `CLAUDE.md` and `meridian help` both document the `project` config
  key and `--all-projects`.

## Scope

- `meridian/config.py` — `project` field, slug derivation, validation.
- `meridian/enrich.py` — schema column, `upsert_chunks()` signature and predicate,
  `search_similar()` predicate, `reindex_all()` scoped delete, legacy-schema
  detection.
- `meridian/cli.py` — `--all-projects` flag, result rendering, migration notice,
  `init` template, `help` text.
- `meridian/search.py` — default project filter, foreign-row labelling.
- Tests — per-project isolation, migration path, predicate escaping, contracts.
- `CLAUDE.md` — config table and CLI reference.

## Out of Scope

- Global cross-project registry (`~/.meridian/projects.toml`). Needed for idea
  routing, not for this fix. Separate feature.
- Idea capture inbox and triage command. Depends on this, but is its own bet.
- Per-project LanceDB directories. Rejected: it would fix isolation but destroy
  the ability to ever query across projects, which is the capability the idea
  inbox needs. One table with a `project` column keeps both options open.
- Automatic reindex of other projects during migration. Meridian cannot know
  where the other repos live until the registry exists.
- Backfilling `project` onto existing rows. The value is unknowable for rows
  already written; recreate-and-reindex is correct and cheap.

## Key Risks

- **Silent partial migration** — a user upgrades, runs `meridian index` in one
  repo, and assumes everything is fine while nine repos sit empty. Mitigated by
  AC10/AC11: both the index path and the search path print the same explicit
  remediation line.
- **LanceDB schema-evolution API drift** — detection of the legacy schema must
  not depend on a version-specific `add_columns`. Mitigated by AC9: inspect
  `table.schema` field names, which is stable across the supported range and
  already covered by the FEAT-005 dependency-bounds test.
- **Slug collisions across identically-named directories** — accepted and
  documented (AC5) rather than solved, with a warning on detection. Solving it
  properly needs the registry.
- **Predicate injection via slug** — a directory name with an apostrophe reaching
  a `where` clause. Mitigated by AC17, extending the existing B1 escaping.

## Dependencies

- **Sequenced after FEAT-006.** Confirmed with the session implementing it
  (2026-08-18): FEAT-006 commits on branch `feat-006/screenshot-ingest`;
  FEAT-007 branches off `main` after that PR merges. Four integration
  constraints come out of that conversation and are binding:

  - **AC7 has a fourth call site.** FEAT-006 adds
    `enrich.py::ingest_screenshot()`, which calls
    `upsert_chunks(cfg.lancedb_path, feat_id_norm, sidecar_name, chunks, vectors)`
    with a sidecar name like `kpi.notes.md`. The project-slug parameter must be
    threaded there too. Stated to be the only new call site — verify by grep at
    implementation time rather than trusting the count.

  - **AC8 is a rebase, not a rewrite.** FEAT-006 already changed the
    `reindex_all()` loop body: the glob widened from `sources/*.txt` to `*.txt`
    plus `*.notes.md`, and `*.notes.md` files route through a new
    `notes_chunks()` helper instead of `chunk_text()`. Replacing
    `drop_table("chunks")` with a scoped delete must preserve that loop body
    intact, or screenshot notes silently stop being reindexed. Guarded by
    `tests/test_enrich_integration.py::TestReindexAllWithScreenshots`, which
    asserts chunk-count parity across rebuilds — that test must still pass
    afterwards, and its passing is the acceptance signal for AC8.

  - **AC1 field ordering.** FEAT-006 adds `ollama_vision_model: str = ""` as the
    last `MeridianConfig` field. `project: str` is always supplied by
    `load_config()`, so it is a non-default field and must be declared *before*
    the defaulted trailing fields — a non-default after a default is a
    `TypeError` at class definition.

  - **Schema is unobstructed.** FEAT-006 does not touch `_open_table()` or add
    columns to `chunks`, so AC6 lands on the original schema.

- Conflict surface to expect on rebase: `meridian/cli.py` (FEAT-006 rewrote the
  `enrich` command with five new options and the helpers `_resolve_capture`,
  `_report_enrich`, `_stdin_is_tty`, plus config-template lines that AC4 also
  edits) and `meridian/config.py`. New module `meridian/capture.py` does not
  touch LanceDB and should not conflict.

## Related Research

None ingested. The evidence is the code itself:

- `meridian/config.py:47` — global default `~/.meridian/lancedb`
- `meridian/enrich.py:166-176` — single `chunks` table, schema without `project`
- `meridian/enrich.py:195` — delete predicate missing project scope
- `meridian/enrich.py:277` — search predicate missing project scope
- `meridian/enrich.py:645` — unconditional `drop_table("chunks")`
- `meridian/cli.py:563` — unfiltered default search
- `meridian/search.py:109` — foreign `feat_id` resolved against local specs

## Open Questions

*Both resolved during implementation.*

- **`--all-projects` in the `/ask` skill?** No — CLI-only. Exposing it to `/ask`
  invites accidental cross-project answers in a context where the reader cannot
  see provenance clearly. The contract test does not require a skill reference,
  so nothing forced the issue.
- **Migration notice once, or every run?** Every run. It is the only signal, and
  it stops on its own as soon as the table is recreated.

## Verification

Run against the real shared store on 2026-08-18, before any rebuild:

- `meridian search "screenshot ingestion"` → printed the migration hint and
  exited 0, leaving the store untouched (AC11).
- The live store was confirmed still at 178 rows with the legacy schema
  `['feat_id', 'source_name', 'chunk_idx', 'text', 'vector']`, read via
  `count_rows()` rather than `to_arrow()` — per `specs/STEERING.md`, `to_arrow()`
  returns a single fragment and under-reports row counts.
- Full suite: 491 passed (460 before, +31 for FEAT-007), including FEAT-006's
  `TestReindexAllWithScreenshots` chunk-count-parity test, which is the
  acceptance signal for AC8. `ruff` and `mypy` clean.

The migration then ran for real, unintentionally: `meridian index` was run in
this repo to refresh `REGISTRY.md`, and the same command always calls
`reindex_all()`. The legacy table was recreated and the 178 rows dropped. The
store was rebuilt afterwards through `upsert_chunks()` directly, and now carries
correct attribution:

```
by project: bet365-apify-scraper 8 | gdc-mic-ai-evaluation 43 | meridian 2
            misc 52 | portfolio-management 73
by feat:    FEAT-001 87 | FEAT-005 3 | FEAT-006 51 | FEAT-008 20 | FEAT-009 17
```

That breakdown is the feature working end to end on real data — and it is direct
evidence for the problem statement: **FEAT-001 rows span three repos and FEAT-006
spans two.** Before this change those rows were indistinguishable, and the
`(feat_id, source_name)` delete predicate could pick the wrong repo's chunks.

Two lessons folded back into the code and this spec:

1. `meridian index` is not a registry-only command. Anyone reaching for it to
   refresh `REGISTRY.md` also triggers a full re-embed — hence AC12b and
   `--vectors-only`.
2. Read the shared store with `count_rows()`, never `to_arrow()` — per
   `specs/STEERING.md`, `to_arrow()` returns a single fragment and under-reports
   (it showed 10 rows for a 178-row table).
