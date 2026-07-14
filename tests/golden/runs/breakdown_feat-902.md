## Technical Breakdown — FEAT-902: Auto-transition watcher (`meridian watch`)

### Components
List each distinct component/module/service that needs to be built or modified.

| Component | What it does | New or existing? | Effort (S/M/L) |
|---|---|---|---|
| `meridian/cli/watch.py` | Defines the `meridian watch <feat-id>` command: arg/flag parsing (`--dry-run`, `--interval`, `--once`), resolves the feature directory, wires the watch loop, prints notices, sets exit codes. | New | S |
| `meridian/watcher.py` | Core watch loop. Uses `watchfiles.watch` on the feature dir if importable, else a polling fallback (default 2s). On each change event, calls the completion evaluator and, if 100% done, invokes the lifecycle transition. Handles keyboard interrupt and clean shutdown. | New | M |
| `meridian/progress.py` | Task-file parser: reads `tasks.md`, counts checked vs total checkboxes, returns `(checked, total, fraction)`. Reused from the FEAT-903 progress parser if it already exists; otherwise created here as the shared implementation. | Existing (shared) / New | S |
| `meridian/lifecycle.py` | Transition engine. `transition(feat_id, to_status, dry_run=False)` validates the source→target edge, rewrites spec frontmatter `status` + `updated`, renames the feature dir to the `FEAT-NNN_<appetite>_<status>` convention, and triggers a registry rebuild. Backs both `meridian close` and `meridian transition`. Extended (not rewritten) so `watch` reuses it. | Existing (modify) | M |
| `meridian/registry.py` | `rebuild()` regenerates `specs/REGISTRY.md` from all spec frontmatter after a transition. Reused as-is; `watch` never writes the registry directly. | Existing (reuse) | S |
| `meridian/cli.py` (modify) | Register the `watch` subcommand in the CLI dispatcher/arg group. | Existing (modify) | S |
| `tests/test_watch.py` | Fixture-driven tests for the parser, the completion decision, dry-run, missing `tasks.md`, and already-`done` handling. | New | M |

### Data Model
No new persistent tables or schemas. `meridian watch` reads and mutates existing on-disk artifacts.

- **Spec frontmatter** (in `spec.md`, mutated only via `lifecycle.transition`):
  - `status: str` — one of `draft | in-progress | done | in-production` (the lifecycle states).
  - `updated: date` (ISO `YYYY-MM-DD`) — refreshed by the transition, not by the watcher.
- **`tasks.md`** — read-only input. Parsed line-by-line for GitHub-style checkboxes.
- **In-memory `TaskProgress`** (transient dataclass returned by `progress.parse_tasks`):
  - `checked: int`
  - `total: int`
  - `fraction: float` (`checked / total`, `0.0` when `total == 0`)
  - `complete: bool` (`total > 0 and checked == total`)
- **In-memory `WatchResult`** (transient, returned by the loop for the CLI to render / exit on):
  - `feat_id: str`
  - `transitioned: bool`
  - `from_status: str`
  - `to_status: str`
  - `reason: str` (e.g. `"all tasks complete"`, `"already done"`, `"no tasks.md"`).

**Checkbox parsing approach:** compile `re.compile(r"^\s*[-*]\s*\[( |x|X)\]", re.MULTILINE)` and scan every matched line. A match with `x`/`X` is a checked box; a match with a space is unchecked. `total` = all matches; `checked` = the `x`/`X` matches. Non-checkbox lines are ignored, so prose in `tasks.md` does not affect the count. This is anchored to line start (after leading whitespace) to avoid matching `[x]` inside sentences — mitigating the "regex fragility" risk from the spec.

**"All tasks done" decision:** `complete = (total > 0 and checked == total)` — i.e. `fraction == 1.0`. A file with zero parseable checkboxes is **not** complete (avoids a transition on an empty/malformed file). Requiring 100% (rather than "≥1 newly checked") directly mitigates the partial-save race-condition risk.

### Integration Points
- **`meridian/lifecycle.py`** — the watcher's only mutation path. It calls `transition(feat_id, "done")`; it never edits frontmatter or renames directories itself. This preserves the invariant that all status changes go through the CLI so the registry is rebuilt (and satisfies "updates REGISTRY.md").
- **`meridian/registry.py`** — invoked transitively by `lifecycle.transition` to regenerate `specs/REGISTRY.md`. No direct coupling from `watch`.
- **`specs/` filesystem layout** — resolves `specs/FEAT-902_m_draft/` from the feat-id via the existing spec-locator used by other commands (matches `FEAT-NNN_*`, so it survives the appetite/status suffix rename). Watches that directory for `tasks.md` writes.
- **`watchfiles` (optional third-party dep)** — `from watchfiles import watch` inside a `try/except ImportError`. When present, delivers OS-native change events. Config knob `watch.interval` could live in `.meridian.toml`; default 2s.
- **Polling fallback** — when `watchfiles` is unavailable, a `time.sleep(interval)` loop stats `tasks.md` mtime and re-parses on change. Same 2s default satisfies the "polls within 2 seconds" criterion on every platform (mitigates the "watchfiles not available" risk).
- **Enables FEAT-903** — the single-feature loop and the `progress`/`lifecycle` seams are designed so FEAT-903's bulk watcher can wrap this over all `in-progress` features.

### Test Strategy
- **Unit — parser (`test_watch.py`)**: fixture `tasks.md` files at 0%, 50%, 100%, mixed `-`/`*` bullets, `[X]` uppercase, indented boxes, and a file containing `[x]` inside prose (must not count). Assert `checked/total/fraction/complete`.
- **Unit — completion decision**: assert `complete` is `False` for `total == 0` and for any unchecked box; `True` only at 100%.
- **Unit — dry-run**: with a 100%-complete fixture and `--dry-run`, assert `lifecycle.transition` is **not** called (mock it) and the "would transition" line is printed.
- **Unit — missing `tasks.md`**: watcher prints a warning and returns exit code 0 (acceptance criterion 3).
- **Unit — already-`done`**: mock `lifecycle.transition` to raise the "invalid transition" error; assert the watcher catches it, prints a notice, and stops without an unhandled exception (acceptance criterion 4).
- **Integration**: real temp `specs/` tree; start the loop with `--once`, flip the last `- [ ]` to `- [x]`, assert spec frontmatter becomes `status: done`, the dir is renamed to `FEAT-902_m_done`, and `REGISTRY.md` reflects it (acceptance criterion 1).
- **Integration — polling fallback**: force the `watchfiles`-absent path (monkeypatch the import) and assert a saved change is detected within the interval (acceptance criterion 2).
- **Manual**: run `meridian watch feat-902` in a terminal, edit `tasks.md` in an editor, confirm live detection and clean `Ctrl-C` shutdown.

### Total Effort Estimate

| Scale | Meaning |
|---|---|
| S | A few hours |
| M | 1–3 days |
| L | 1–2 weeks |
| XL | More than a sprint — consider splitting the feature |

**Overall:** M — roughly 3–5 days. The two M components (`watcher.py`, `lifecycle.py` extension) dominate; everything else is S. Well within the feature-level `m` appetite (1–2 weeks), leaving margin for FEAT-903 seam design.

### Implementation Order
Ordered list of components — what must be built first. This order feeds directly into `/tasks`.

1. **`meridian/progress.py`** — pure, dependency-free checkbox parser + `TaskProgress`. Standalone and unit-testable first (shared with FEAT-903).
2. **`meridian/lifecycle.py`** (extend) — ensure `transition(feat_id, "done", dry_run=...)` exists, validates the source→target edge, raises a typed error on invalid transitions (e.g. already `done`), and triggers `registry.rebuild()`. The watcher depends on this contract.
3. **`meridian/watcher.py`** — the loop: `watchfiles`-or-polling detection, calls the parser, applies the completion rule, invokes the transition, handles missing `tasks.md` / already-done / interrupt, returns `WatchResult`.
4. **`meridian/cli/watch.py` + `meridian/cli.py`** (register) — wire flags (`--dry-run`, `--interval`, `--once`), resolve the feat-id, render notices, map `WatchResult` to exit codes.
5. **`tests/test_watch.py`** — parser units, decision units, dry-run, missing/already-done paths, then the two integration flows.

---

### Open Questions — recommended resolutions

1. **Run until killed, or exit after first transition?** **Recommendation: exit after the first successful transition (exit 0).** A feature can only complete once; once it reaches `done` there is nothing left to watch, and lingering risks acting on stale state. Expose a `--once` flag (default behaviour) and keep the loop structured so FEAT-903's bulk mode can opt into a long-running variant. If no transition occurs, the watcher keeps running until interrupted.

2. **Surface a progress indicator for partial completion?** **Recommendation: yes, minimal — print `feat-902: 4/7 tasks (57%)` on each re-evaluation.** It is nearly free given the parser already yields `checked/total/fraction`, and it makes the watcher observable while idle. Keep it a single stdout line (no live spinner/TUI) to stay within the `m` appetite and out of FEAT-903's dashboard scope.
