# Tasks — FEAT-904: JSON output mode for `meridian status`

> Appetite: `m`  ·  Generated: 2026-07-14

- [ ] 1. Write `meridian/serialize.py`: `features_to_dict(specs) -> dict` returning
       `{"schema_version": ..., "features": [...]}` with each feature entry carrying
       `id`, `name`, `status`, `appetite`, `confidence`, `cycle` [DECISION NEEDED:
       is `schema_version` an integer (starts at `1`) or a semver string? — spec Open
       Question #1]
       Pre: none
       AC: #1

- [ ] 2. Extend `features_to_dict` to populate `progress` (`done`/`total` integers)
       per feature by calling the existing task-file parser in `meridian/progress.py`
       Pre: task 1 complete; `meridian/progress.py` parser exists and returns
       done/total counts from a `tasks.md`
       AC: #2

- [ ] 3. Extend `features_to_dict` to emit `dependencies` per feature: `depends_on`
       and `enables` serialized as arrays of feature id strings
       Pre: task 1 complete
       AC: #3

- [ ] 4. Handle the empty-project case in `features_to_dict`: calling it with no
       specs returns `{"schema_version": 1, "features": []}` and never raises
       Pre: task 1 complete
       AC: #5

- [ ] 5. Write `tests/test_status_json.py::TestFeaturesToDict` covering 0, 1, and
       many specs — assert schema shape, progress counts against a fixture
       `tasks.md` with known done/total, and dependency-edge arrays
       Pre: tasks 1–4 complete
       AC: #1, #2, #3, #5

- [ ] 6. Add a `--json` flag to the `status` command in `cli.py`: when set, call
       `features_to_dict(all_specs())` and print the result via plain `print(json.dumps(...))`,
       bypassing the Rich console entirely
       Pre: task 1 complete
       AC: #1

- [ ] 7. Wire the `status` command's existing filter options so they narrow the
       spec list before it reaches `features_to_dict` when `--json` is active
       Pre: task 6 complete
       AC: #4

- [ ] 8. Write `tests/test_status_json.py::TestCLI` integration test: run
       `meridian status --json | python -m json.tool`, assert exit code 0; run
       `meridian status --json` with a filter and assert only matching features
       appear in the output array
       Pre: tasks 6–7 complete
       AC: #4, #5

- [ ] 9. Write a regression test asserting `meridian status --json` output contains
       no ANSI escape sequences and no Rich table artifacts, across at least one
       run with existing features present
       Pre: task 6 complete
       AC: #1

- [ ] 10. Write `docs/status-json.md`: document the top-level schema, the
       `schema_version` contract (when to bump it per the resolved decision in
       task 1), and an example payload
       Pre: task 1 complete (schema finalized); decision from task 1 resolved
       AC: none *(supports Key Risk: schema churn breaking downstream consumers)*

- [ ] 11. Run the full suite (`tests/test_status_json.py` plus existing `status`
       command tests) and confirm the legacy Rich table output is unchanged when
       `--json` is omitted
       Pre: tasks 1–10 complete
       AC: #1, #2, #3, #4, #5
