---
abandoned_at: null
abandoned_reason: null
appetite: s
blocked_at: null
blocked_by: null
confidence: null
created: '2026-07-14'
cycle: null
depends_on: []
enables: []
goal: '~'
id: feat-002
name: 'Add integration tests for external seams: Ollama embed + LanceDB round-trip,
  mocked with pytest-httpx (happy-path, complementing existing degradation tests)'
scheduler: null
sources: []
status: done
tags: []
updated: '2026-07-14'
---

## What was built

`tests/test_enrich_integration.py` — 11 tests covering the two external seams in
`meridian/enrich.py`, complementing the mock-only unit tests in `test_enrich.py`:

- **LanceDB round-trips (real temp store):** upsert → `search_similar` retrieval,
  `feat_id` filter scoping, upsert idempotency (stale-entry replacement, no row
  accumulation), multi-source coexistence, empty-chunk no-op.
- **Search degradation:** returns `[]` for a missing path and for an existing path
  with no `chunks` table.
- **Ollama embed sanitize-retry branch:** unicode chunk → 400 → ASCII-stripped
  retry succeeds (the branch unit tests didn't reach).
- **`enrich_feature` end-to-end:** filesystem + LanceDB real, `embed` mocked at the
  seam; asserts source copy, frontmatter `sources` update, and retrievability.
- **`reindex_all` round-trip + idempotency:** drop-and-rebuild produces stable
  row counts.

**Deviation from the captured idea:** used `unittest.mock` (the existing test
style) instead of adding a `pytest-httpx` dependency — LanceDB round-trips run
against a real temp store since `lancedb`/`pyarrow` are hard deps. No new
dependency added.

Suite: 292 passed / 22 skipped. ruff + mypy clean.
