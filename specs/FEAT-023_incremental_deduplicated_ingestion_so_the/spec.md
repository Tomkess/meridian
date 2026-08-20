---
abandoned_at: null
abandoned_reason: null
appetite: m
blocked_at: null
blocked_by: null
confidence: high
created: '2026-08-19'
cycle: 2026-Q3
depends_on: []
enables:
- feat-024
- feat-025
goal: goal-01
id: feat-023
name: Incremental, deduplicated ingestion so the corpus can grow
sources: []
status: done
tags: []
updated: '2026-08-20'
---

## Summary

`reindex_all` re-embeds **every source of the project, every time**. At today's
178 chunks that is invisible. It is also the reason the corpus cannot grow: each
`meridian index` is O(corpus) Ollama round-trips, so the cost of adding the
hundredth document is paid again on every rebuild thereafter. A research corpus
whose maintenance cost scales with its size is one you stop feeding — which is
exactly the state the corpus is in.

Three separate wastes compound:

1. **Unchanged sources are re-embedded.** Nothing records what was already
   indexed, so a rebuild cannot tell a new PDF from one indexed last month.
2. **Identical content is embedded once per location.** The same paper enriched
   into two features — or into two projects sharing this index — is chunked and
   embedded twice, and produces two independent sets of near-identical vectors
   that then compete in every search.
3. **Ingestion is one source per invocation.** `meridian enrich <feat> <source>`
   takes a single argument, so a directory of twenty PDFs is twenty commands,
   each paying full process and model start-up.

This feature makes ingestion incremental, content-addressed, and batched. It is
the foundation for [[FEAT-024]] and [[FEAT-025]]: both assume a corpus worth
searching, and neither is worth building on an ingestion path that punishes
growth.

## Appetite

`m` — a schema migration, a content-hash cache, batch ingestion, and the tests
that prove nothing is lost. The migration is the part that deserves the time.

## Design decisions

**The hash lives in the table, not in a sidecar manifest.** A
`specs/.index-manifest.json` would be cheaper to write and would desynchronise
from the store the first time an index rebuild is interrupted — and the store is
what queries read. One source of truth, even at the cost of a redundant column
per row.

**Dedup means "do not re-embed", not "do not store".** Embedding is the
expensive operation; a row is bytes. Storing one row per (project, feat, source,
chunk) keeps provenance intact — which feature cited this, in which repo — while
a content-hash → vector cache removes the cost. Collapsing storage would save
little and destroy the provenance [[FEAT-025]] needs for citations.

**Migration re-embeds once rather than dropping.** The existing
`_is_legacy_schema` check drops the whole table when it meets a pre-FEAT-007
schema, which is what destroyed the global store on 2026-08-18. Adding a column
must not repeat that. Rows without a hash are treated as *unknown*, not as
*stale*: the first rebuild after upgrade re-embeds them and backfills, every
later one is incremental, and no row is ever deleted before its replacement
exists.

## Acceptance Criteria

### Incremental indexing

- **AC1** — The `chunks` table carries a `content_hash` column: the SHA-256 of
  the chunk's text.
- **AC2** — `reindex_all` skips embedding for a source whose every chunk hash is
  already present in the store for that project, and reports how many sources
  were skipped.
- **AC3** — A changed source is detected by hash, not mtime. A file touched but
  not edited must not be re-embedded; a file edited in place with a preserved
  mtime must be.
- **AC4** — The returned dict gains `skipped` and `embedded` counts, and
  `meridian index` prints both.

### Dedup

- **AC5** — Within a single `reindex_all` run, two chunks with identical text are
  embedded once and the vector reused.
- **AC6** — Across runs and across features, a chunk whose hash already exists
  anywhere in the store reuses the stored vector instead of calling Ollama.
- **AC7** — Reuse is scoped by embedding model. A vector produced by a different
  `ollama_model` is never reused for another, since the vectors are not
  comparable — the model name is recorded alongside the hash.
- **AC8** — Provenance survives dedup: the same paper in two features still
  yields rows for both, each carrying its own `feat_id` and `project`.

### Migration

- **AC9** — A store written before this feature (no `content_hash` column) is
  **migrated, never dropped**. Its rows are re-embedded once and backfilled.
  *As built:* this covers the FEAT-007-era schema, which is every store in
  existence today. A **pre-FEAT-007** table (no `project` column) is still
  recreated rather than migrated — see the Verification note.
- **AC10** — Migration embeds before deleting, matching FEAT-013: an Ollama
  failure mid-migration leaves the existing rows intact and exits non-zero.
- **AC11** — `meridian index` states plainly when a migration happened and what
  it cost, rather than silently taking ten minutes.

### Batch ingestion

- **AC12** — `meridian enrich <feat> <source>...` accepts multiple sources, and a
  directory argument ingests the supported files within it (non-recursive).
- **AC13** — Batch ingestion is **per-source atomic**: each source is fully
  embedded before its own rows are written, so one unreadable file does not lose
  the sources already ingested in that run.
- **AC14** — A batch reports per-source outcome — ingested, skipped as
  unchanged, or failed with the reason — and exits non-zero if any failed.
- **AC15** — `--refresh` re-fetches sources that came from a URL and re-embeds
  only those whose extracted text has actually changed. *As built:* the flag is
  what makes a re-fetch happen at all — a URL already saved in `sources/` is
  skipped without it, which is a deliberate change to the previous behaviour
  (see Verification).

### Guards

- **AC16** — A test asserts `reindex_all` makes **zero** `embed` calls when
  nothing has changed. This is the property the whole feature exists for, and it
  is the one a later refactor would silently break.
- **AC17** — A test asserts the corpus is byte-identical in content after a
  no-op rebuild — same rows, same hashes, no duplicates introduced.

## Scope

`meridian/enrich.py` (schema, `reindex_all`, `upsert_chunks`, a new hash/vector
cache), `meridian/cli.py` (`enrich` accepting multiple sources, `index`
reporting), and tests.

## Out of Scope

- **Chunking strategy.** `chunk_text` at 200 words with 25 overlap stays as-is.
  Changing chunking and adding hash-based skipping in one feature makes every
  hash change at once and destroys the migration's meaning.
- **A different embedding model.** AC7 makes model changes *safe*; choosing one
  is a separate decision.
- **Recursive directory ingestion.** Non-recursive is the predictable behaviour;
  recursion into a repo tree is how you accidentally index `node_modules`.
- **Deleting rows for sources removed from `sources/`.** Real, but it is a
  deletion path, and deletion paths in this project get their own feature with
  their own tests.

## Key Risks

- **A hash column tempts a future "just drop and rebuild".** Mitigated by AC9
  and by stating the 2026-08-18 incident in the code comment, not only here.
- **Dedup across projects couples them.** Project A's vector is reused for
  project B's identical chunk. Acceptable because the vector is a pure function
  of (text, model) — but it means a corrupted vector is now shared, and AC7 is
  what keeps the function pure.
- **Skipping is only as good as the hash.** A source whose extraction is
  non-deterministic (some PDF extractors reorder whitespace) will re-embed every
  time and look like a bug. Worth a note in the output when a source re-embeds
  despite appearing unchanged.

## Verification

The corpus is 178 chunks; a full rebuild today makes 178 embed calls. After this,
a no-op rebuild must make zero — asserted directly, not measured by wall clock.

### Result — 2026-08-20, branch `feat-023/incremental-ingest`

**The headline number: zero.**
`tests/test_incremental_ingest.py::TestNoOpRebuildEmbedsNothing::test_second_rebuild_makes_zero_embed_calls`
builds a two-source corpus (4 chunks), asserts the first rebuild makes exactly 4
`embed` calls, then asserts the second makes **0** — on the counter itself, not
on elapsed time. The same property is asserted through the CLI: a second
`meridian index` prints `0 chunks embedded`. A batch enrich of three text files
where two are byte-identical made 4 embed calls, not 6, and the `meridian index`
that followed made 0 — the enrich path and the rebuild path now share one cache.

Gate: **696 tests pass** (655 before, 41 new), `ruff check .` clean,
`mypy meridian/` clean — all through `uv run --locked`.

**Schema.** `project, feat_id, source_name, chunk_idx, text, vector,
content_hash, embedding_model`. The last two are new; they are appended, so a
migrated table and a freshly created one have identical field order.

**Three generations, named not counted.** `_is_legacy_schema() -> bool` is gone,
replaced by `schema_generation(table) -> SchemaGeneration`:
`PRE_PROJECT` (no `project`), `PRE_HASH` (FEAT-007 schema, no hash), `CURRENT`.
A boolean could not express the middle case, which is the one that must be
migrated rather than refused.

**Migration.** `PRE_HASH` → `table.add_columns({...: "''"})`. Purely additive:
every row keeps its vector and gets an empty hash, which reads as *unknown*, so
this project re-embeds its own sources once and backfills, while other projects'
rows sit untouched until they rebuild. Ordering is unchanged from FEAT-013 —
chunking, hashing and embedding all happen before the store is touched at all,
so **Ollama dying mid-migration leaves the table byte-for-byte as it was**, still
`PRE_HASH`, and exits non-zero (asserted). A kill between `add_columns` and the
writes is also safe: the empty hashes simply mean the next rebuild re-embeds.

### Deviations

- **AC9 — pre-FEAT-007 stores are still recreated, not migrated.** Those rows
  carry no `project`, so there is no way to attribute them to a repo, reuse them
  under AC7, or delete them selectively; the FEAT-007 recovery path (rebuild
  from `sources/`, which is the source of truth) remains the only correct one,
  and its existing test still asserts it. Every store written since FEAT-007 —
  including the user's — takes the additive path. `reindex_all` now distinguishes
  the two in its result: `migration` is `"backfilled"` or `"recreated"`, and
  `migrated` stays True only for the destructive case, so the CLI never tells
  someone their other projects were wiped when they were not.
- **AC15 — `--refresh` changes the default for URL sources.** Without it, a URL
  already saved in `sources/` is reported as skipped and *not re-fetched*.
  Re-fetching is the only part of ingestion that leaves the machine, and a batch
  re-run to pick up one new paper should not re-crawl twenty sites. With
  `--refresh`, the fetch happens and the hash still decides whether anything is
  re-embedded.
- **Stale rows: behaviour preserved, not extended.** "Deleting rows for sources
  removed from `sources/`" is Out of Scope, but the old code already did it via a
  whole-project delete before every rebuild. Keeping that would have deleted the
  rows of every *skipped* source. It is now a targeted delete of exactly the
  `(feat_id, source_name)` pairs that no longer exist on disk — same outcome,
  narrower blast radius. No new deletion path was added.

### Not done

- The bundled skill `enrich.md` still documents one source per invocation and
  does not mention `--refresh` or directory arguments. Updating it touches the
  shared skill files (and their `--sync` copy), which were outside this branch's
  ownership.
