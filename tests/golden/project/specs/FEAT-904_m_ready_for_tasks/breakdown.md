# Breakdown — FEAT-904: JSON output mode for `meridian status`

> Appetite: `m`  ·  Status: `draft`

## Components

| Component | Description | Effort |
|---|---|---|
| `meridian/serialize.py` | Pure function: `features_to_dict(specs) -> dict` producing the versioned payload | M |
| `cli.py` (modify) | Add `--json` flag to `status`; branch to serializer + plain print | S |
| `meridian/progress.py` (reuse) | Existing task-file parser; extract `done`/`total` counts | XS |
| `docs/status-json.md` | Document the schema and `schema_version` contract | S |
| `tests/test_status_json.py` | Schema validity, progress counts, dependency edges, empty case | M |

## Implementation Order

1. `serialize.py` — standalone pure function over already-loaded specs; no I/O
2. `cli.py` — add the `--json` flag, call the serializer, print via plain stdout
3. Wire the shared progress parser so table and JSON report identical counts
4. `docs/status-json.md` — pin the schema and version field
5. `tests/test_status_json.py` — cover all acceptance criteria

## Test Strategy

- Unit: `features_to_dict` with 0, 1, and many specs; assert JSON round-trips
- Unit: progress counts match a fixture tasks.md with known done/total
- Unit: dependency edges serialize as id arrays
- Integration: `meridian status --json | python -m json.tool` exits 0
- Regression: `--json` output contains no ANSI escape sequences

## Notes

- Keep the serializer free of Rich imports so it can never leak formatting
- `schema_version` starts at `1`; bump only on breaking field changes
- Empty-project case must return `{"schema_version": 1, "features": []}`, not error
