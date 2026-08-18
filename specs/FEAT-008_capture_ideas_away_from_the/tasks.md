## Tasks — FEAT-008: Capture ideas away from the PC into a global inbox and triage them into the right project

> Appetite: `m`  ·  Generated: 2026-08-18

### 1 — Global home layer

- [x] 1. Add `meridian/home.py` with `meridian_home() -> Path` (honours `MERIDIAN_HOME`, defaults
       to `~/.meridian`) and `inbox_dir()`, `processed_dir()`, `icebox_dir()` that create on demand.
       Module must import cleanly with no `.meridian.toml` anywhere — no `load_config()` import.
       Pre: none
       AC: #1, #5
- [x] 2. Write `tests/test_home.py`: `MERIDIAN_HOME` override respected, directories created on
       demand, and an import-isolation test asserting `meridian.home` imports from a directory
       with no `.meridian.toml` up the tree.
       Pre: task 1 complete

### 2 — Capture file format

- [x] 3. Add `meridian/inbox.py` with the `Capture` dataclass and `read_capture(path) -> Capture`:
       parse optional YAML frontmatter, strip it from `text`, extract `#slug` hashtags as routing
       hints, set `hint_source`, infer `created` from filename then mtime.
       Pre: task 1 complete
       AC: #2, #3, #4
- [x] 4. Add `write_capture(text, *, project=None) -> Path` and `list_captures() -> list[Capture]`
       (sorted oldest-first, ignoring `.processed/` and `.icebox/`). Filename is the capture
       timestamp; collisions get a numeric suffix rather than overwriting.
       Pre: task 3 complete
       AC: #1
- [x] 5. Write `tests/test_inbox.py` covering: frontmatter present / absent / malformed, bare-text
       capture valid, hashtag extraction (none, one, several), timestamp inference from filename
       then mtime, whitespace-only capture rejected, filename collision suffixing.
       Pre: task 4 complete
       AC: #2, #3, #4, #20

### 3 — Capture command

- [x] 6. Add `meridian capture "<text>"` to `cli.py`. Must not call `_config()` — it has to work
       from any directory on the machine, including outside a repo. Print the written path.
       Pre: task 4 complete
       AC: #5
- [x] 7. Write CLI tests for `capture`, including the case that matters most: run it from a
       directory with no `.meridian.toml` anywhere up the tree and assert exit 0 plus a written
       file. Every existing CLI test runs inside a fixture repo, so this path is otherwise untested.
       Pre: task 6 complete
       AC: #5

### 4 — Project registry

- [x] 8. Add `meridian/registry.py`: `ProjectEntry` dataclass, `all_projects()` reading
       `~/.meridian/projects.toml` and computing `exists`, `register(slug, path, purpose)` updating
       in place by slug. Missing or malformed TOML degrades to an empty list with a warning, never
       a traceback.
       Pre: task 1 complete
       AC: #6, #7, #8
- [x] 9. Write `tests/test_registry.py`: register creates, re-register updates in place (no
       duplicate), stale path flagged `exists=False` and retained, missing file, malformed TOML.
       Pre: task 8 complete
       AC: #7, #8
- [x] 10. Wire registration into `meridian init` and `meridian install`, keyed by the FEAT-007
       `cfg.project` slug. Purpose line comes from `specs/VISION.md` first heading if present,
       else the repo directory name.
       Pre: task 8 complete
       AC: #7
- [x] 11. Add `meridian projects` listing slug, path, and resolve status.
       Pre: task 8 complete
       AC: #9

### 5 — Triage

- [x] 12. Add `meridian inbox` listing pending captures: index, capture date, first line, and the
       routing hint where one exists (shown as `explicit`, not a score). No suggestions yet.
       Pre: tasks 4 and 8 complete
       AC: #10, #13
- [x] 13. Add `meridian inbox route <id> --project <slug>`: resolve the target repo from the
       registry, create the spec there via `specs.create_spec()` with the capture's full text as
       the body, rebuild the *target* repo's registry, then move the capture to `.processed/`.
       Pre: task 12 complete
       AC: #14, #15
- [x] 14. Make `route` idempotent and safe: a already-processed id fails with a clear message and
       creates nothing; warn (do not block) when the target repo's `git status --porcelain` is
       dirty; refuse a capture with no routable text.
       Pre: task 13 complete
       AC: #17, #19, #20
- [x] 15. Add `meridian inbox drop <id>` moving the capture to `.icebox/`. Never deletes.
       Pre: task 12 complete
       AC: #16
- [x] 16. Write triage tests: full round trip (capture → list → route → spec exists in target repo,
       file in `.processed/`, gone from `inbox/`), double-route fails without duplicate spec,
       routing into repo A leaves repo B untouched, drop lands in `.icebox/`.
       Pre: tasks 13, 14, 15 complete
       AC: #14, #16, #17
- [x] 17. Confirm no auto-file path exists: add a test asserting there is no CLI flag or code path
       that turns a capture into a spec without an explicit `--project`. This is a rejected design,
       so it needs a guard, not just an omission.
       Pre: task 14 complete
       AC: #18

### 6 — Routing suggestions

- [x] 18. Add `meridian/routing.py`: `suggest(capture, entries) -> list[Suggestion]`. Explicit hint
       short-circuits before any embed call. Otherwise embed the capture once, call
       `search_similar(..., project=None)`, aggregate hit scores per project, return top 3.
       Pre: task 8 complete; FEAT-007 `project` column in place (shipped)
       AC: #11, #13
- [x] 19. Add the `purpose` fallback: projects with no rows in the shared index are scored against
       their registry `purpose` text, so a brand-new project is never permanently unroutable.
       Pre: task 18 complete
       AC: #12
- [x] 20. Write `tests/test_routing.py` with a stubbed `search_similar`: score aggregation across
       projects, top-3 truncation, explicit hint bypasses embedding entirely (assert the embed
       function is never called), `purpose` fallback for an unindexed project.
       Pre: task 19 complete
       AC: #11, #12, #13
- [x] 21. Wire suggestions into `meridian inbox`, showing three candidates with scores and their
       basis (`index` / `purpose` / `explicit`). A low-confidence top hit must read as
       low-confidence rather than as a recommendation.
       Pre: tasks 12 and 19 complete
       AC: #10, #11

### 7 — Surfacing and docs

- [x] 22. Show the pending inbox count in `meridian status`. [DECIDED 2026-08-18: yes, show it.
       One dim line, silent when the inbox is empty, with the oldest capture's age once it is a
       day or more old.]
       Pre: task 4 complete
- [x] 23. Document `capture`, `inbox`, and `projects` in `meridian help` and `CLAUDE.md`, including
       the capture file format and the `#slug` hint. Verify `test_contracts.py` still passes —
       every flag named in docs must exist in `--help`.
       Pre: tasks 6, 11, 15 complete
- [x] 24. Add a STEERING.md note: tests must set `MERIDIAN_HOME` to a temp path and never touch the
       real `~/.meridian`. The FEAT-007 wipe is the precedent worth naming.
       Pre: task 1 complete
- [x] 25. Manual verification: capture from a scratch directory outside any repo, triage in this
       repo, confirm the spec lands and the capture is archived. Record the result in spec.md
       under a Verification section, matching FEAT-007's format.
       Pre: tasks 21 and 23 complete

**25 tasks.** Tasks 1–17 deliver a complete, usable feature (capture + manual triage). Tasks 18–21
are the suggestion engine — the part to cut first if the appetite runs out, per breakdown.md.
