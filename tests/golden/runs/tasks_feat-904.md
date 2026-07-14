## Tasks — FEAT-904: JSON output mode for `meridian status`

> Appetite: `m`  ·  Generated: 2026-07-14

- [ ] 1. Implement `features_to_dict(specs) -> dict` in `meridian/serialize.py`: a pure
       function (no I/O, no Rich imports) that wraps a list of specs into the versioned
       payload `{schema_version, features: [...]}`, and returns `{"schema_version": 1,
       "features": []}` when given an empty list. [DECISION NEEDED: should
       `schema_version` be an integer (`1`) or a semver string (`"1.0.0"`)? Breakdown
       Notes assume integer — confirm before locking the contract.]
       Pre: none
       AC: #5

- [ ] 2. Write unit tests in `tests/test_status_json.py` for `features_to_dict` with 0,
       1, and many specs; assert the output JSON-round-trips (`json.loads(json.dumps(...))
       == ...`) and that the empty case matches `{"schema_version": 1, "features": []}`
       exactly.
       Pre: task 1 complete
       AC: #1, #5

- [ ] 3. Extend `features_to_dict` to populate each feature object's `dependencies`
       field with `{"depends_on": [...], "enables": [...]}` id arrays, sourced from each
       spec's existing `depends_on`/`enables` frontmatter.
       Pre: task 1 complete
       AC: #3

- [ ] 4. Write a unit test asserting dependency edges serialize as plain id arrays under
       `dependencies`, covering a feature with both `depends_on` and `enables` set and one
       with neither (empty arrays, not omitted keys).
       Pre: task 3 complete
       AC: #3

- [ ] 5. Wire the existing task-progress parser (`meridian/progress.py`) into
       `features_to_dict` so each feature object gains a `progress: {done, total}` field,
       reusing the same parser the Rich table view already calls (do not reimplement
       counting logic).
       Pre: task 1 complete; `meridian/progress.py`'s existing parser function is
       identified and importable
       AC: #2

- [ ] 6. Write a unit test with a fixture `tasks.md` of known done/total counts, asserting
       the JSON `progress` field matches, and that it matches the value the table view's
       parser call would produce for the same fixture (parity check).
       Pre: task 5 complete
       AC: #2

- [ ] 7. Add a `--json` flag to the `status` command in `cli.py`: when set, call
       `features_to_dict(all_specs())` and print the result via plain `print(json.dumps(...))`
       to stdout, fully bypassing the Rich console (no table render, no ANSI codes).
       Pre: task 1 complete
       AC: #1

- [ ] 8. Write an integration test that runs `meridian status --json`, pipes the output
       through `json.tool` (or `json.loads`) and asserts exit code 0, and asserts the raw
       stdout bytes contain no ANSI escape sequences (regression guard for Rich leakage).
       Pre: task 7 complete
       AC: #1

- [ ] 9. Make `--json` respect the `status` command's existing filter argument(s): when a
       filter is supplied alongside `--json`, pass the filtered spec subset into
       `features_to_dict` instead of the full set, so only matching features appear in
       the output array.
       Pre: task 7 complete; existing filter mechanism on `status` identified
       AC: #4

- [ ] 10. Write an integration test that runs `meridian status --json` with a filter
        matching a known subset of fixture features and asserts the output `features`
        array contains only those matches.
        Pre: task 9 complete
        AC: #4

- [ ] 11. Write an end-to-end test for the no-features case: run `meridian status --json`
        against an empty specs directory and assert exit code 0 and stdout equals
        `{"schema_version": 1, "features": []}` (adjust literal to match the decision from
        task 1).
        Pre: tasks 1, 7 complete
        AC: #5

- [ ] 12. Write `docs/status-json.md` documenting the top-level schema
        (`schema_version`, `features[]` with `id`, `name`, `status`, `appetite`,
        `confidence`, `cycle`, `progress`, `dependencies`), and the versioning contract
        (bump `schema_version` only on breaking field changes).
        Pre: tasks 1, 3, 5 complete (fields are finalized)
        AC: none directly — supports Key Risk "schema churn breaking downstream consumers"

- [ ] 13. Add a schema-stability contract test asserting the current `schema_version`
        value and the full set of top-level/per-feature keys match what's documented in
        `docs/status-json.md`, so a future field change fails CI unless the doc and
        version are updated together.
        Pre: tasks 2, 12 complete
        AC: none directly — mitigates Key Risk "schema churn breaking downstream consumers"
