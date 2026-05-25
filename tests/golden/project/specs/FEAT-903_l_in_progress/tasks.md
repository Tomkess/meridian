# Tasks — FEAT-903: TUI Dashboard

> Appetite: `l`  ·  Generated: 2026-05-10

- [x] 1. Write `meridian/tui/progress.py`: parse `tasks.md` checkbox counts
       Pre: none
       AC: #5 (task file changes → progress bar updates)

- [x] 2. Write `tests/test_tui.py::TestProgress` covering 0%, 50%, 100% fixture files
       Pre: task 1 complete
       AC: #5

- [ ] 3. Write `meridian/tui/data.py`: poll `all_specs()` + Databricks, return typed list
       Pre: task 1 complete; `databricks.py` and `specs.py` APIs stable
       AC: #1, #5

- [ ] 4. Write `meridian/tui/widgets/feature_row.py`: `FeatureRow` Textual widget
       Pre: task 3 complete; textual>=0.60 installed in dev env
       AC: #1

- [ ] 5. Write `meridian/tui/app.py`: root App, screen layout, `r`/`q`/`/` keybindings
       Pre: task 4 complete
       AC: #1, #2, #4

- [ ] 6. Write `meridian/tui/widgets/dep_graph.py`: inline dependency popover
       Pre: task 5 complete
       AC: #3

- [ ] 7. Gate `cli.py` `status` command on `MERIDIAN_TUI` env var
       Pre: task 5 complete
       AC: #4

- [ ] 8. Write Textual Pilot integration tests for `r`, `d`, `q` keypresses
       Pre: task 6 complete; Textual headless mode confirmed working
       AC: #2, #3

- [ ] 9. Verify `MERIDIAN_TUI=0 meridian status` renders legacy Rich table
       Pre: task 7 complete
       AC: #4
