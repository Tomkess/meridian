# Breakdown — FEAT-903: TUI Dashboard

> Appetite: `l`  ·  Status: `in-progress`

## Components

| Component | Description | Effort |
|---|---|---|
| `meridian/tui/app.py` | Root Textual `App` — screen layout, keybindings, startup | M |
| `meridian/tui/widgets/feature_row.py` | `FeatureRow` widget: status badge, progress bar, cycle chip | M |
| `meridian/tui/widgets/dep_graph.py` | Inline dependency popover (triggered by `d`) | S |
| `meridian/tui/data.py` | Data layer: poll specs + Databricks, return typed dicts | L |
| `meridian/tui/progress.py` | Task-file parser: count `- [x]` vs `- [ ]` for progress | S |
| `cli.py` (modify) | Gate `status` on `MERIDIAN_TUI` env var; import TUI app | XS |
| `tests/test_tui.py` | Textual test harness; widget unit tests; legacy fallback | M |

## Implementation Order

1. `tui/progress.py` — standalone, pure file parsing; needed by data layer
2. `tui/data.py` — polling layer; depends on progress + existing databricks.py
3. `tui/widgets/feature_row.py` — renders a single row using data layer output
4. `tui/app.py` — composes rows, wires keybindings, handles refresh
5. `tui/widgets/dep_graph.py` — popover built on top of working app
6. `cli.py` gate + `MERIDIAN_TUI=0` fallback
7. `tests/test_tui.py` — end-to-end widget + integration tests

## Test Strategy

- Unit: `tui/progress.py` — fixture task files with 0%, 50%, 100% completion
- Unit: `tui/data.py` — mock `all_specs()` + mock Databricks; assert typed output
- Widget: Textual `Pilot` API — simulate keypress `r`, `d`, `q`; assert DOM state
- Integration: `MERIDIAN_TUI=0 meridian status` renders Rich table (regression gate)
- CI: run tests without a real terminal (Textual headless mode)

## Notes

- `textual>=0.60,<1.0` — pin the minor range; their reactive API changed between 0.50→0.60
- `tui/` is a new subpackage; add to `[tool.setuptools.packages.find]` include list
- `XL` effort items should be split — `tui/data.py` is borderline L; watch for scope creep
