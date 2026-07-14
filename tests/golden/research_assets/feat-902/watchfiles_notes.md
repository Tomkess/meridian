# Notes: cross-platform file watching for tasks.md auto-transition

Source: internal engineering notes on the `watchfiles` library and polling
fallbacks, compiled for the tasks.md auto-transition feature.

## watchfiles library

- `watchfiles` is a Rust-backed watcher exposing a uniform API over the OS
  native backends: inotify on Linux, FSEvents on macOS, and
  ReadDirectoryChangesW on Windows. This removes most per-platform branching.
- It coalesces bursts of events with a built-in debounce (default step 50 ms),
  so a single logical save does not fire dozens of callbacks.
- Recommended usage is the `watch()` generator; it yields sets of
  `(Change, path)` tuples already de-duplicated within the debounce window.

## Partial-write races

- Most editors do not write files in place — they write to a temp file and then
  `rename()` over the target. The reliable signal is therefore the rename/close
  event, not raw byte-level `modify` events.
- Reacting to intermediate `modify` events risks parsing a half-written
  `tasks.md` (e.g. a checkbox line truncated mid-write), producing a spurious
  completion count. Debounce and re-read the whole file on the settled event.

## Polling fallback

- Where native events are unavailable (some network filesystems, containers
  with restricted inotify), fall back to stat-based polling. A 1–5 second
  interval is the accepted tradeoff between latency and CPU on large repos.
- Polling should skip work entirely when no feature is `in-progress`, to avoid
  a constant CPU floor on idle repositories.

## Regex robustness

- Task-list completion is counted from Markdown checkboxes. `- [x]` vs `- [ ]`
  is the common form, but `* [X]` (asterisk bullet, capital X) and leading
  indentation both occur in the wild. Match case-insensitively and allow either
  bullet marker, or completion counts drift silently.
