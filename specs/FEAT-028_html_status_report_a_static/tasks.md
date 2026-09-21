## Tasks — FEAT-028: HTML status report

> Appetite: `m`  ·  Generated: 2026-09-21

- [x] 1. Create `meridian/report.py` with `STATUS_COLUMNS` moved verbatim from `cli.py`'s `_STATUS_COLUMNS`; update `cli.py` to import it from `report.py`.
       Pre: none
       AC: #4
- [x] 2. Run the existing test suite and confirm no regression from the column move (import direction only, no behavior change).
       Pre: task 1 complete
       AC: #4
- [x] 3. Extract `build_payload(cfg)` into `report.py` from the inline dict in `cli.py`'s `status --json` path; delete the inline dict; wire `status --json` to call `report.build_payload(cfg)`.
       Pre: task 1 complete
       AC: #2
- [x] 4. Write the AC2 regression test: invoke `status --json` via `CliRunner` on a fixture project, parse stdout, assert it equals `build_payload(cfg)` for the same fixture.
       Pre: task 3 complete
       AC: #2
- [x] 5. Promote `specs._atomic_write` to `specs.atomic_write` (keep `_atomic_write` as an alias for existing callers).
       Pre: none
       AC: #1
- [x] 6. Promote `portfolio._days_since_mtime` to `portfolio.days_since_change(feat_dir)` as a public function `report.py` can import without reaching into a private.
       Pre: none
       AC: #6
- [x] 7. Extract the goal-file-reading loop out of `rebuild_registry()` in `specs.py` into `report.read_goals(specs_path)`, including the existing unparseable-goal warn-and-continue fallback; have `rebuild_registry()` call it instead of its inline loop.
       Pre: none
       AC: #5
- [x] 8. Write a test that `read_goals()` returns a row with `status: "unparseable"` for a bad goal file without raising, and confirm the existing registry-rebuild tests in `tests/test_specs.py` still pass unchanged.
       Pre: task 7 complete
       AC: #5
- [x] 9. Implement `dependency_edges(features)` in `report.py`: dedup edges from `depends_on`/`enables`, mark `dangling: true` when the target ID isn't in the local feature set, normalize IDs with `.upper()` before matching.
       Pre: task 3 complete
       AC: #3
- [x] 10. Write unit tests for `dependency_edges()`: a `depends_on` target that doesn't exist produces a dangling edge and is not dropped; lowercase `feat-001` in frontmatter matches `FEAT-001`; a reciprocal `A depends_on B` / `B enables A` pair does not produce duplicate overlapping edges.
        Pre: task 9 complete
        AC: #3
- [x] 11. Implement `rank_nodes(features, edges)` in `report.py`: longest-path depth over non-dangling `depends_on` edges via iterative DFS with a visiting-set, so a cycle terminates with a finite rank instead of recursing forever.
        Pre: task 9 complete
        AC: #3
- [x] 12. Write unit tests for `rank_nodes()`: a linear chain A→B→C yields ranks 0/1/2; a two-node cycle terminates with finite ranks; a dangling target doesn't affect rank.
        Pre: task 11 complete
        AC: #3
- [x] 13. Implement `build_report_payload(cfg)` in `report.py`: calls `build_payload(cfg)` and appends sibling keys — `goals` (via `read_goals`), `columns` (from `STATUS_COLUMNS`), `signals` (per-feature `days_since_change`/`stale`/`goal_key`/`rank`, keyed by ID, never mutating `features`), `edges` (via `dependency_edges`+`rank_nodes`), `generated_at`, `meridian_version`.
        Pre: tasks 3, 6, 7, 9, 11 complete
        AC: #5, #6
- [x] 14. Write a test that `build_report_payload()["features"]` is identical to `build_payload()["features"]` (superset never mutates the shared contract), and that a feature with a stub `tasks.md` (zero checkboxes) yields `tasks: null`, distinct from `{"checked": 0, "total": 0}`.
        Pre: task 13 complete
        AC: #2, #6
- [x] 15. Write `meridian/templates/report.html.tmpl` skeleton: page shell, single `/*__MERIDIAN_PAYLOAD__*/` placeholder inside a `<script>` block with a valid `null` default, kanban board columns from `STATUS_COLUMNS` (abandoned features in a collapsed section below, not a column), task progress bars from `signals`/`tasks`.
        Pre: tasks 1, 13 complete
        AC: #4, #6
- [x] 16. Implement `render_html(payload, template)` in `report.py`: substitutes the serialized JSON payload into the sentinel placeholder, escapes `</script` inside the serialized JSON so a feature name containing that literal can't break out of the block.
        Pre: task 15 complete
        AC: #1
- [x] 17. Write a test that `render_html()` escapes `</script>`, backticks, and `-->` in a feature name / `blocked_by` reason / goal name, and the resulting page still parses as one `<script>` block.
        Pre: task 16 complete
        AC: #1
- [x] 18. Implement `write_report(cfg, out_path)` in `report.py`: `build_report_payload()` → `render_html()` → atomic write via `specs.atomic_write`, creating the parent directory; returns the written `Path`.
        Pre: tasks 5, 16 complete
        AC: #1, #7
- [x] 19. Add the `meridian report` Typer command in `cli.py`: `[--out PATH] [--open] [--project SLUG]`, default out path `specs/.meridian/report.html`, `--open` defaults off and uses `webbrowser.open(path.as_uri())` (a failed open is a warning, not a non-zero exit), `--project SLUG` resolves via `registry.find_project()` with the same not-registered error shape as `_tracked_projects()`.
        Pre: task 18 complete
        AC: #1
- [x] 20. Write CLI tests: `meridian report` in a fixture project writes the default path and exits 0; `--out /other/path.html` honors the override and creates the parent dir; `--out` pointing at a directory or unwritable path exits 1 with a readable message; running with no `.meridian.toml` exits 1 with the same message shape as `status`; running twice back-to-back with no spec change yields identical parsed `features` (AC7, `generated_at` excluded from the comparison); a project with zero specs still writes a valid empty-state page.
        Pre: task 19 complete
        AC: #1, #7
- [x] 21. Add `meridian/templates/*.tmpl` to `[tool.setuptools.package-data]` in `pyproject.toml`; switch template lookup in `report.py` to `importlib.resources.files("meridian") / "templates" / "report.html.tmpl"` instead of a `Path(__file__)`-relative lookup.
        Pre: task 15 complete
        AC: #9
- [x] 22. Extend `tests/test_packaging.py`: assert `meridian/templates/report.html.tmpl` is a member of the built wheel archive, and that `importlib.resources` locates it from the installed package (not just the source tree).
        Pre: task 21 complete
        AC: #9
- [x] 23. Add `/specs/.meridian/` to `.gitignore`, anchored to repo root the same way the existing `/specs/REGISTRY.md` entry is.
        Pre: none
        AC: #8
- [x] 24. Template: goal × feature matrix view — one row per goal from `goals`, plus an "ungoaled" row for `goal_key: null`, with empty cells rendered visibly rather than omitted.
        Pre: tasks 13, 15 complete
        AC: #5
- [x] 25. Template: dependency graph as inline SVG — one node per feature, one edge per relationship from `edges`, columnar layout by `signals[id].rank` (one column per rank, features stacked within a rank), dangling edges rendered as visually distinguishable from resolved ones.
        Pre: tasks 13, 15 complete
        AC: #3
- [x] 26. Template: staleness heat shading per feature card from `signals[id].days_since_change`/`stale`, plus page footer showing `generated_at`, `meridian_version`, `staleness_note`, and the unreadable-spec count.
        Pre: tasks 13, 15 complete
        AC: #6
- [x] 27. Write the self-containment test (AC1 guard): generate a report into `tmp_path`, assert no match for `<script[^>]+src=`, `<link[^>]+href=`, an attribute-position `https?://`, `@import`, `url(http`, or `fetch(`; assert nothing else is written into the output directory.
        Pre: task 20 complete
        AC: #1
- [ ] 28. Manual pass: generate against this repo (28 features) and open with the browser offline/network disabled — judge dependency graph legibility at real size (fall back to a plain edge table alongside the graph if unreadable, per the breakdown's mitigation, still satisfying AC3); confirm the goal matrix shows the "ungoaled" row and visible empty cells (AC5); confirm a blocked feature's card shows its `blocked_by` text (AC4); `pipx install` from a built wheel into a clean environment and confirm the template resolves (AC9); open in Safari and Firefox as well as Chrome to check inline SVG sizing and `file://` behavior.
        Pre: tasks 24, 25, 26, 27 complete
        AC: #1, #3, #4, #5, #9

### Task 28 status

Verified mechanically (2026-09-21), by executing the page's own JavaScript
against both the real payload and a synthetic one covering the branches this
repo's data does not reach:

- Generated against this repo: 28 features, 9 edges, ranks 0–4, 23 ungoaled,
  0 unreadable specs, 40 KB single file. Graph renders at 844×192 px for 11
  participating nodes — legible at this size, so the edge-table fallback was
  shipped *alongside* the graph rather than instead of it.
- AC1 self-containment: no external script, stylesheet, `@import`, remote
  `url()`, `fetch`, `XMLHttpRequest` or service worker in the output.
- AC3 dangling edge drawn dashed with its own node; AC4 blocked card shows its
  `blocked_by`; AC5 a goal with nothing in flight still has a row and empty
  cells are shaded; AC6 task bar at 40% and "no task list" distinct from 0%.
- AC9: wheel built, installed into a clean venv, `meridian report` run from
  that install — the template resolved through `importlib.resources`.

**Outstanding, needs a human at a browser:** Safari and Firefox rendering.
Inline SVG sizing and `file://` behaviour differ between engines enough to be
worth five minutes, and nothing here can stand in for looking at it.
