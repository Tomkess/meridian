## Technical Breakdown — FEAT-028: HTML status report

### Components

List each distinct component/module/service that needs to be built or modified.

| Component | What it does | New or existing? | Effort (S/M/L) |
|---|---|---|---|
| `meridian/report.py` — `build_payload(cfg)` | The extraction named in AC2. Lifts the dict literal currently inlined in `cli.py:status` (lines 454–476) into one function that takes a loaded `MeridianConfig` and returns the single-project payload: `{"project": cfg.project, "features": [...]}` with the exact same twelve per-feature keys (`id`, `name`, `status`, `appetite`, `confidence`, `cycle`, `goal`, `updated`, `depends_on`, `enables`, `blocked_by`, `tasks`). `status --json` calls it; `report` calls it. No second implementation exists anywhere. | New module, existing logic moved | S |
| `meridian/report.py` — `build_report_payload(cfg)` | The report's superset payload. Calls `build_payload(cfg)` and *adds* keys the HTML needs but the CLI contract does not carry: `goals` (read from `specs/goals/*.md`), `columns` (from the shared status-column tuple), `staleness` (per-feature `days_since_change` + `stale_days` + `staleness_note`), `dependency_edges` (resolved + dangling), and `generated_at`. Never mutates the `features` list entries that AC2 compares — it appends sibling keys, so a byte-for-byte per-field comparison still passes. | New | M |
| `meridian/report.py` — `read_goals(specs_path)` | Parses `specs/goals/*.md` frontmatter (`id`, `name`, `status`) the same way `rebuild_registry()` already does in `specs.py:467–488`, including the warn-and-continue `unparseable` fallback. Returns a list of goal dicts. Extracted here rather than duplicated — `rebuild_registry` should call it too so the two goal readers cannot disagree. | New (refactor of existing loop in `specs.py`) | S |
| `meridian/report.py` — `dependency_edges(features)` | Turns `depends_on`/`enables` into a deduplicated edge list. Each edge is `{"from": ID, "to": ID, "kind": "depends_on"|"enables", "dangling": bool}`. `dangling=True` when the target ID is not in the local feature set (AC3's explicit requirement). Normalises IDs with `.upper()` before matching, because frontmatter carries `feat-028` lowercase while the payload carries `FEAT-028`. | New | S |
| `meridian/report.py` — `rank_nodes(features, edges)` | The deterministic layout the spec's risk table asks for: longest-path depth over the non-dangling `depends_on` edges, computed with an iterative DFS carrying a visiting-set so a `depends_on` cycle yields a finite rank instead of recursing forever. Output is `{feat_id: rank}`; the SVG turns rank into an x-column and within-rank index into a y-row. No force-directed layout, no layout library. | New | M |
| `meridian/report.py` — `render_html(payload, template)` | Substitutes the compact JSON payload into the template's single placeholder and returns the finished HTML string. Uses a sentinel token (`/*__MERIDIAN_PAYLOAD__*/`) rather than `str.format`/`Template` — the template is full of CSS braces and `$` selectors that both of those would eat. Escapes `</script` in the serialised JSON so a feature name containing that literal cannot break out of the `<script>` block. | New | S |
| `meridian/report.py` — `write_report(cfg, out_path)` | Orchestration: build payload → render → atomic write (reuse `specs._atomic_write`, which already does mkstemp + fsync + `os.replace`). Creates the parent directory. Returns the written `Path`. No caching layer at all — AC7 is satisfied by construction because every call re-reads `all_specs()`. | New | S |
| `meridian/templates/report.html.tmpl` | The single self-contained template: inline `<style>`, inline `<script>`, inline SVG drawn by JS. Zero `<script src>` / `<link rel=stylesheet>`. Renders five views from the embedded payload: kanban board, dependency graph, goal × feature matrix, task progress bars, staleness heat. System font stack only (no Google Fonts — that is a network reference). | New | L |
| `meridian/cli.py` — `report` command | New Typer command: `meridian report [--out PATH] [--open] [--project SLUG]`. Default out path `specs/.meridian/report.html`. `--open` defaults to **off** (see open question resolution below) and uses `webbrowser.open(path.as_uri())`. Prints the written path on success. | Existing file, new command | S |
| `meridian/cli.py` — `status --json` call site | Replaced with `_emit_json(report.build_payload(_config()))`. The inline dict comprehension is deleted, not commented out — two copies is the exact drift AC2 forbids. | Existing, modified | S |
| `meridian/cli.py` — `_STATUS_COLUMNS` | AC4 requires the report's kanban columns to match `STATUS_COLUMNS` from `cli.py`. `cli.py` must not be imported by `report.py` (it pulls Typer, Rich and the whole command tree into a rendering module). Move the tuple to `meridian/report.py` as `STATUS_COLUMNS` and have `cli.py` import it — the same direction `portfolio.APPETITE_WEIGHT` already flows (`cli.py:121`). | Existing, moved | S |
| `pyproject.toml` — package data | Add `"templates/*.tmpl"` to `[tool.setuptools.package-data].meridian`. Currently only `skills/commands/*.md` and `skills/templates/*.md` are listed, so a new `meridian/templates/` directory ships **no** files in the wheel. This is the exact failure AC9 guards. | Existing, modified | S |
| `.gitignore` | Add `/specs/.meridian/`. Verified today: the file has no such entry (it ignores `/specs/REGISTRY.md` and nothing else under `specs/`). AC8 is currently unsatisfied. | Existing, modified | S |
| `tests/test_report.py` | Unit coverage for payload extraction, edge resolution, ranking, escaping, and the self-containment assertion. | New | M |
| `tests/test_packaging.py` | Extend with a template-in-wheel assertion, per AC9's named guard. | Existing, modified | S |

### Data Model

No database, no schema migration. Three in-memory structures, all plain
JSON-serialisable dicts so they can be embedded verbatim in the HTML.

**1. `build_payload()` return — the contract shared with `status --json`.**
This shape is frozen by AC2; adding or renaming a key here is a breaking change
to every skill that shells out to `meridian status --json`.

```
{
  "project": str,                    # cfg.project
  "features": [
    {
      "id":          str,            # "FEAT-028" — upper-cased from frontmatter
      "name":        str | None,
      "status":      str,            # one of specs.VALID_STATUSES, default "idea"
      "appetite":    str | None,     # xs | s | m | l
      "confidence":  str | None,     # low | medium | high
      "cycle":       str | None,     # e.g. "2026-Q2"
      "goal":        str | None,     # "goal-01", or "~" for ungoaled (NOT normalised — status --json emits the raw value today)
      "updated":     str | None,     # ISO date, may be a datetime.date pre-serialisation
      "depends_on":  list[str],      # [] when unset
      "enables":     list[str],      # [] when unset
      "blocked_by":  str | None,
      "tasks":       {"checked": int, "total": int} | None   # from specs.task_progress()
    }
  ]
}
```

Note on `goal`: `portfolio._opt_str()` normalises `"~"` to `None`, but
`status --json` does **not** — it emits `s.get("goal")` raw. `build_payload()`
must preserve the raw behaviour or AC2's byte-for-byte comparison fails against
the shipped CLI. Normalisation happens one layer up, in the report payload's
`goal_key` field.

**2. `build_report_payload()` return — the superset the HTML consumes.**

```
{
  "project": str,
  "features": [ ...unchanged from build_payload... ],
  "generated_at": str,               # ISO-8601 timestamp, rendered in the page footer
  "meridian_version": str,           # meridian.__version__
  "stale_days": int,                 # portfolio.STALE_DAYS (30)
  "staleness_note": str,             # portfolio.STALENESS_NOTE — the caveat travels with the number
  "columns": [ {"status": str, "label": str} ],   # from STATUS_COLUMNS, in order
  "goals": [
    {"id": str, "name": str, "status": str}       # status may be "unparseable"
  ],
  "signals": {                       # keyed by feature ID, kept out of `features` to protect AC2
    "FEAT-028": {
      "days_since_change": int | None,
      "stale": bool,
      "goal_key": str | None,        # normalised: "~"/""/None all collapse to None → "ungoaled" row
      "rank": int                    # dependency depth, 0 for roots
    }
  },
  "edges": [
    {"from": str, "to": str, "kind": "depends_on" | "enables", "dangling": bool}
  ]
}
```

**3. Template placeholder.** The template file contains exactly one occurrence of
`/*__MERIDIAN_PAYLOAD__*/` inside a `<script>` block:

```html
<script>const DATA = /*__MERIDIAN_PAYLOAD__*/null/*__END__*/;</script>
```

Keeping a valid `null` default means the template file itself is a syntactically
valid HTML page and can be opened during development without running the CLI.

**Status column set (AC4).** Moved verbatim from `cli.py:156–163`:
`idea`, `draft`, `in-progress`, `blocked`, `done`, `in-production`. Note that
`abandoned` is in `specs.VALID_STATUSES` but deliberately *not* a column — the
kanban must place abandoned features somewhere, so they go into a collapsed
"abandoned" section below the board rather than silently vanishing (same
principle as `_project_json` keeping unreadable projects in the payload).

### Integration Points

- **`meridian/config.py` → `load_config()`** — `report` resolves the project the
  same way `status` does, via `cli._config()`. `--project SLUG` resolves through
  `registry.find_project(slug)` and then loads that repo's `.meridian.toml`;
  a slug that is not registered exits 1 with the same message shape
  `_tracked_projects()` uses. STEERING's "capture must work outside a repo" rule
  does not apply here — `report` is explicitly a single-project command and
  `load_config()` raising outside a repo is correct behaviour.
- **`meridian/specs.py` → `all_specs()`, `task_progress()`** — the only spec
  readers. `all_specs()` already warns-and-drops unparseable specs to stderr;
  the report inherits that, and the page footer shows a count of specs on disk
  versus specs in the payload (mirroring `portfolio._spec_file_count()`) so a
  dropped spec is visible in the HTML, not just in the terminal scrollback.
- **`meridian/specs.py` → `_atomic_write()`** — reused for the HTML write.
  Currently private; promote to `atomic_write()` (keeping `_atomic_write` as an
  alias) rather than adding a second mkstemp/replace implementation.
- **`meridian/specs.py` → `rebuild_registry()`** — refactored to call the new
  `read_goals()`. This is the only behavioural change to an existing shipped
  path; `tests/test_specs.py` covers the registry rebuild and must stay green
  unchanged.
- **`meridian/portfolio.py` → `STALE_DAYS`, `STALENESS_NOTE`** — imported for
  the staleness heat, not re-declared. The `days_since_change` computation is
  `portfolio._days_since_mtime([spec.md, tasks.md], now)`; promote it to
  `days_since_change(feat_dir)` so `report.py` does not reach into a private.
  STEERING's architecture note about two numbers disagreeing (the `_STALE_BLOCKED_DAYS`
  import comment in `portfolio.py:31–35`) is the precedent.
- **`meridian/registry.py` → `find_project()`** — only for `--project SLUG`.
  Crucially, `report` reads the *target repo's* specs directly; it never resolves
  a foreign `feat_id` against the local specs directory (STEERING hard constraint).
  Since the report is single-project, every ID in the payload comes from one
  specs tree, so the `<project>/FEAT-NNN` namespacing problem does not arise —
  but the page title must name the project so a report opened from `~/Downloads`
  is not mistaken for another repo's.
- **Vector store / LanceDB** — untouched. `report.py` must not import
  `meridian.search` or `meridian.index`. This is deliberate: the global store is
  shared across projects (STEERING) and a read-only rendering command has no
  business opening it. It also keeps `meridian report` fast and importable
  without the lancedb native extension.
- **Browser (`file://`)** — the only runtime. No fetch, no XHR, no service
  worker, no `import` of a module URL. `webbrowser.open(path.as_uri())` for
  `--open`; failure to open is a warning, not a non-zero exit — the file was
  still written.
- **`.gitignore`** — `/specs/.meridian/` added, anchored to repo root exactly
  like the existing `/specs/REGISTRY.md` entry so the shipped template and the
  golden fixture under `tests/golden/project/` are unaffected.
- **Packaging (`setuptools`)** — `meridian/templates/report.html.tmpl` must be
  listed in `[tool.setuptools.package-data]`. Template lookup at runtime uses
  `importlib.resources.files("meridian") / "templates" / "report.html.tmpl"`,
  not `Path(__file__).parent`, so it works from a zip-imported install.

### Test Strategy

**Unit — `tests/test_report.py` (new).**

- `build_payload()` on a fixture specs tree returns the twelve documented keys
  per feature and nothing more. Assert on the exact key set, not a subset — an
  extra key is the drift AC2 is written to catch.
- **AC2 regression, the important one:** invoke `status --json` through
  `typer.testing.CliRunner`, parse stdout, and assert it is `==` to
  `build_payload(cfg)` for the same fixture. This is the test that fails the day
  someone re-inlines the dict.
- `build_report_payload()["features"]` is identical to `build_payload()["features"]`
  — proves the superset never mutates the shared contract.
- `dependency_edges()`: a feature with `depends_on: [FEAT-999]` where FEAT-999
  does not exist produces one edge with `dangling: True` and is **not** dropped
  (AC3). Lowercase `feat-001` in frontmatter matches `FEAT-001`. A reciprocal
  `A depends_on B` / `B enables A` pair does not produce two overlapping edges.
- `rank_nodes()`: a linear chain A→B→C yields ranks 0/1/2; a two-node cycle
  terminates and yields finite ranks; a dangling target does not affect rank.
- `read_goals()`: an unparseable goal file yields a row with
  `status: "unparseable"` and does not raise (matches `rebuild_registry`'s
  existing contract).
- `render_html()`: a feature named `</script><img onerror=1>` appears in the
  output with the `</script` sequence escaped, and the resulting page still
  parses as one `<script>` block. Same for a `blocked_by` reason containing
  backticks and a goal name containing `-->`.
- Payload for `tasks`: a feature with a stub `tasks.md` (the `TASKS_TEMPLATE`
  placeholder, zero checkboxes) yields `tasks: null`, not `{"checked":0,"total":0}` —
  `task_progress()` returns `None` there and the bar must render as "no task
  list", distinct from 0%.

**Self-containment — the AC1 guard, also in `tests/test_report.py`.**

- Generate a report into `tmp_path`, read it, and assert no match for
  `<script[^>]+src=`, `<link[^>]+href=`, `https?://` inside attribute position,
  `@import`, `url(http`, or `fetch(`. A plain-text `https://` in a feature name
  is legitimate, so the regexes are attribute-scoped rather than a blanket URL
  ban.
- Assert the file is a single file: nothing else is written into the output
  directory.

**Packaging — `tests/test_packaging.py` (extend, AC9's named guard).**

- Build a wheel (the existing test already exercises the build path) and assert
  `meridian/templates/report.html.tmpl` is a member of the archive.
- Assert `importlib.resources` can locate the template from the installed
  package, not just from the source tree — a `Path(__file__)` lookup passes in
  the repo and fails in the wheel, which is precisely the bug AC9 names.

**CLI — `tests/test_cli.py` (extend).**

- `meridian report` in a fixture project writes `specs/.meridian/report.html`
  and exits 0.
- `--out /some/other/path.html` honours the override and creates the parent dir.
- `--out` pointing at a directory, or at an unwritable path, exits 1 with a
  readable message rather than a traceback.
- Running in a directory with no `.meridian.toml` exits 1 with the
  `load_config()` message (same shape as `status`).
- Running twice back-to-back with no spec change (AC7) produces a payload whose
  `features` block is identical — `generated_at` will differ, so compare the
  parsed `features`, not the raw bytes.
- A project with zero specs still writes a valid page showing an empty-state
  message, rather than erroring.

**Manual — the part no assertion covers.**

1. Generate against this repo (28 features, ~7 goals worth of rows, real
   `depends_on` data) and open with the browser offline / network disabled.
   Confirm the dependency graph is legible at that size — this is the named
   appetite risk. If it is not legible at 28 nodes, the fix is a simpler layout
   or an edge-list fallback view, **not** a layout library.
2. Confirm the goal × feature matrix shows an "ungoaled" row for the many
   `goal: '~'` features in this repo and shows empty cells as visible gaps
   (AC5) — an empty goal row must still render.
3. Confirm a blocked feature's card shows its `blocked_by` text (AC4).
4. `pipx install` from a built wheel into a clean environment, run `meridian report`
   in a different repo, confirm the template resolves (AC9, belt and braces
   alongside the automated assertion).
5. Open in Safari and Firefox as well as Chrome — inline SVG sizing and
   `file://` behaviour differ enough to be worth five minutes.

**Not tested:** the visual appearance of the HTML. There is no snapshot test of
the rendered page; a DOM snapshot would break on every CSS tweak and buy nothing.
The tests assert on the *payload* and on *self-containment*, which are the two
properties that can silently regress.

### Total Effort Estimate

| Scale | Meaning |
|---|---|
| S | A few hours |
| M | 1–3 days |
| L | 1–2 weeks |
| XL | More than a sprint — consider splitting the feature |

**Overall:** M

The extraction (`build_payload`) is a few hours and is genuinely low-risk — the
dict literal moves wholesale and one test pins it. The payload superset,
edge resolution and ranking are another day. The template is the bulk: five
views, hand-written SVG, and a light/dark-tolerant stylesheet with no framework.

Two things keep this inside the `m` appetite rather than sliding to `l`:

- **The graph layout stays deterministic and columnar.** Rank by longest
  `depends_on` depth, one column per rank, features stacked vertically within a
  rank, edges as straight lines or simple cubic curves. No force simulation, no
  edge-crossing minimisation, no drag interactions. The spec's risk table names
  this as the one place the feature quietly becomes `l`, and the mitigation is to
  accept an imperfect-but-readable graph at ~30 nodes.
- **No portfolio view.** `build_payload()` takes one `cfg` and returns one
  project. The moment it grows an `entries` parameter or returns a `projects`
  list, this is a different feature. The payload shape being a near-superset of
  `status --all --json` is a trap the spec already flagged.

If the graph turns out unreadable at real size during step 1 of manual testing,
the correct response is to ship the columnar graph anyway plus a plain
dependency *table* beneath it (from → to → dangling), and open a follow-up. That
keeps AC3 satisfied — every relationship is rendered, dangling ones distinguishably —
without spending a second week on layout.

### Implementation Order

1. **Move `_STATUS_COLUMNS` → `meridian/report.py` as `STATUS_COLUMNS`.** Create
   the module as an otherwise-empty file with just the tuple, and change
   `cli.py` to import it. Smallest possible first commit that establishes the
   `cli.py → report.py` import direction. Existing tests must stay green with no
   edits.
2. **Extract `build_payload(cfg)` into `report.py`; rewire `status --json`.**
   Delete the inline dict. Add the `CliRunner`-vs-`build_payload` equality test
   in the same commit — the extraction is worthless without the test that pins
   it, and AC2 is an acceptance criterion about drift, not about code location.
3. **Promote the shared helpers.** `specs._atomic_write` → `specs.atomic_write`;
   `portfolio._days_since_mtime` → `portfolio.days_since_change(feat_dir)`;
   the goals loop in `rebuild_registry` → `report.read_goals()` (or
   `specs.read_goals()` if it reads better there) with `rebuild_registry`
   calling it. Pure refactor, no new behaviour, existing tests unchanged.
4. **`dependency_edges()` + `rank_nodes()` with their unit tests.** Pure
   functions over the feature list, no filesystem, no HTML. Testable in
   isolation and the piece most likely to hold a subtle bug (ID case, cycles,
   dangling targets). Get this right before anything draws it.
5. **`build_report_payload()`.** Assembles goals, columns, signals, edges,
   staleness and metadata around the frozen `features` list. Test that
   `features` is untouched.
6. **`meridian/templates/report.html.tmpl` — skeleton + kanban + task bars.**
   Page shell, embedded payload, the status columns (AC4) and the progress bars
   (AC6). At this point the page is already useful, which matters if the
   appetite runs short.
7. **`render_html()` + `write_report()` + the `report` CLI command.** End-to-end
   path: `meridian report` writes a file that opens. Add the `--out` and
   `--open` flags. First point at which the feature is demonstrable.
8. **Packaging + gitignore.** `pyproject.toml` package-data entry,
   `importlib.resources` lookup, `/specs/.meridian/` in `.gitignore`, and the
   `test_packaging.py` extension. Done here rather than last because AC9's
   failure mode is invisible in the source tree — every later manual test should
   be running against a wheel-correct layout.
9. **Template — goal × feature matrix (AC5).** Needs `goals` and `goal_key`
   from step 5. Includes the "ungoaled" row and visible empty cells.
10. **Template — dependency graph SVG (AC3).** Last of the views because it is
    the riskiest and the most droppable-to-a-table. Consumes `edges` and `rank`
    already computed and tested in step 4, so this step is rendering only.
11. **Template — staleness heat + footer.** Per-feature staleness shading, the
    `STALENESS_NOTE` caveat, `generated_at`, `meridian_version`, and the
    unreadable-spec count.
12. **Self-containment test + CLI tests + manual pass.** The AC1 regex guard,
    the `test_cli.py` additions, then the five manual checks — including the
    graph-legibility judgement call that decides whether the fallback table
    from the effort estimate is needed.
