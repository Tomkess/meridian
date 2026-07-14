### Answer
The research on FEAT-902 (cross-platform file watching for tasks.md auto-transition) identifies three concrete risks, all centered on correctness under real-world editor and filesystem behavior rather than the watching library itself:

1. **Partial-write races** — the biggest risk. Most editors write to a temp file and `rename()` over the target rather than writing in place. If the watcher reacts to intermediate `modify` events instead of the settled rename/close event, it can parse a half-written `tasks.md` (e.g., a checkbox line truncated mid-write) and produce a spurious/incorrect completion count.
2. **Native watch unavailability** — inotify (and equivalents) isn't available everywhere: some network filesystems and containers with restricted inotify won't deliver native events, forcing a fallback path that behaves differently (higher latency, different failure modes).
3. **Polling fallback tradeoffs** — the fallback is stat-based polling at a 1–5 second interval, which trades latency for CPU cost; on large repos this can add a constant CPU floor if not scoped down (the notes recommend skipping polling entirely when no feature is `in-progress`).

A fourth, lower-severity risk is **regex/parsing robustness**: checkbox detection must handle `- [x]` vs `* [X]` variants and indentation, or completion counts will silently drift.

### Supporting evidence
- `[FEAT-902 / watchfiles_notes.txt]` — "Most editors do not write files in place — they write to a temp file and then rename() over the target. The reliable signal is therefore the rename/close event, not raw byte-level modify events."
- `[FEAT-902 / watchfiles_notes.txt]` — "Reacting to intermediate modify events risks parsing a half-written tasks.md ... producing a spurious completion count."
- `[FEAT-902 / watchfiles_notes.txt]` — "Where native events are unavailable (some network filesystems, containers with restricted inotify), fall back to stat-based polling. A 1–5 second interval is the accepted tradeoff between latency and CPU on large repos."
- `[FEAT-902 / watchfiles_notes.txt]` — "Polling should skip work entirely when no feature is in-progress, to avoid a constant CPU floor on idle repositories."
- `[FEAT-902 / watchfiles_notes.txt]` — "`* [X]` (asterisk bullet, capital X) and leading indentation both occur in the wild ... or completion counts drift silently."

### What the research doesn't cover
The corpus for FEAT-902 is a single source file (2 chunks) — it covers watcher mechanics, partial-write races, polling fallback, and regex robustness, but does **not** address: security/permission risks (e.g., watching files outside expected directory scope), behavior under concurrent multi-process writes, or testing/rollout strategy for the auto-transition logic itself. If you need a broader risk picture (e.g., failure modes when auto-transition fires incorrectly and its downstream effects), consider enriching with a source on the auto-transition state machine or running `/breakdown --feat FEAT-902` to see if implementation-level risks are called out there.
