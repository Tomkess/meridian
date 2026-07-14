---
abandoned_at: null
abandoned_reason: null
appetite: xs
blocked_at: null
blocked_by: null
confidence: null
created: '2026-07-14'
cycle: null
depends_on: []
enables: []
goal: '~'
id: feat-005
name: Add dependency-bounds test for LanceDB minor-version API drift (last item on
  production-ready checklist)
scheduler: null
sources: []
status: done
tags: []
updated: '2026-07-14'
---

## What was built

`tests/test_dependency_bounds.py` (12 tests) — two layers of drift protection:

1. **Version bounds:** parses `pyproject.toml` dependencies and asserts each
   installed runtime dep satisfies its declared specifier (parametrized per
   dep). Plus a guard that `lancedb` keeps an upper bound and the installed
   version sits below it.
2. **API surface:** asserts the exact LanceDB / pyarrow methods
   `meridian/enrich.py` calls still exist — `connect`, DB `table_names` /
   `create_table` / `open_table` / `drop_table`, Table `add` / `delete` /
   `search` / `count_rows`, the query chain `.search().limit().where().to_list()`,
   and pyarrow `schema` / `field` / `list_` / `string` / `int32` / `float32`.
   A minor-version bump that renames/removes one fails here with a clear "API
   drift" message instead of deep inside an enrich run.

Added `packaging>=23` to the `dev` extra (used for specifier matching; tomllib
is stdlib on 3.11+). Suite 321 passed / 22 skipped; ruff + mypy clean.
