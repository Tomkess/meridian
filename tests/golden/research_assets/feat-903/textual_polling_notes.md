# Notes: live task-progress polling in the Textual TUI dashboard

Source: Textual design notes for the TUI dashboard, focused on how the live
progress bars stay in sync with `tasks.md` on disk.

## Live progress via file polling

- The dashboard keeps each feature's progress bar current by re-reading its
  `tasks.md` and counting checked (`- [x]`) versus unchecked (`- [ ]`) boxes.
- Rather than a native file watcher, the TUI uses a Textual interval timer that
  re-polls every 5 seconds. This is simpler than wiring OS watch events into
  the Textual event loop and is good enough for a human-in-the-loop dashboard.
- The same `tasks.md` parsing logic that drives the progress bar is the natural
  place to detect 100% completion — the point at which a feature could
  auto-transition from `in-progress` to `done`.

## Shared concern: tasks.md as source of truth

- Both the dashboard and any auto-transition mechanism read the identical
  `tasks.md` completion signal. Splitting the parser across two features would
  let their counts diverge; a single shared parser is the intended design.
- Polling debounce matters here too: on a large repo, re-reading every
  feature's `tasks.md` each tick is wasteful. Skip features that are not
  `in-progress`, mirroring the file-watcher's idle optimisation.

## Rendering constraints

- Textual's reactive attributes re-render a widget when their value changes, so
  the progress parser should return a stable integer count; feeding it raw
  float ratios causes redundant repaints.
