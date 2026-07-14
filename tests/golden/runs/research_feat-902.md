### Research summary — FEAT-902: meridian watch — auto-transition on task completion

**Coverage**: 1 source enriched · top themes: file-watching, polling-fallback, checkbox-regex

---

#### Background
The feature operates in the domain of cross-platform filesystem watching, where a background process must detect edits to a feature's `tasks.md` and re-evaluate Markdown checkbox completion to drive lifecycle transitions [watchfiles_notes]. Prior internal engineering work evaluated the Rust-backed `watchfiles` library — which unifies inotify (Linux), FSEvents (macOS), and ReadDirectoryChangesW (Windows) behind one API — alongside a stat-based polling fallback for environments where native events are unavailable [watchfiles_notes]. The scale concern is idle-repo CPU cost when watching or polling many features [watchfiles_notes].

#### Key findings
- `watchfiles` is a Rust-backed watcher exposing a uniform API over OS-native backends (inotify/FSEvents/ReadDirectoryChangesW), removing most per-platform branching [watchfiles_notes].
- It coalesces event bursts with a built-in debounce (default step 50 ms), so one logical save does not fire dozens of callbacks; the recommended `watch()` generator yields already de-duplicated `(Change, path)` sets [watchfiles_notes].
- Editors typically write to a temp file and `rename()` over the target, so the reliable trigger is the rename/close event, not raw byte-level `modify` events [watchfiles_notes].
- Reacting to intermediate `modify` events risks parsing a half-written `tasks.md` (e.g. a checkbox line truncated mid-write), producing a spurious completion count; the mitigation is to debounce and re-read the whole file on the settled event [watchfiles_notes].
- Where native events are unavailable (some network filesystems, containers with restricted inotify), a stat-based polling fallback with a 1–5 second interval is the accepted latency/CPU tradeoff on large repos [watchfiles_notes].
- Polling should skip work entirely when no feature is `in-progress`, avoiding a constant CPU floor on idle repositories [watchfiles_notes].
- Checkbox completion counting must be robust: beyond `- [x]` / `- [ ]`, the forms `* [X]` (asterisk bullet, capital X) and leading indentation both occur in the wild, so matching must be case-insensitive and accept either bullet marker or counts drift silently [watchfiles_notes].

#### Constraints and risks surfaced

| Constraint / Risk | Source | Implication for this feature |
|---|---|---|
| Native events unavailable on some network FS / restricted-inotify containers | [watchfiles_notes] | Confirms the spec's polling fallback is mandatory, not optional |
| Partial/half-written file parsed on intermediate `modify` event | [watchfiles_notes] | Must trigger on settled rename/close event and re-read whole file, reinforcing the "100% boxes checked" race mitigation |
| Non-standard checkbox formats (`* [X]`, indentation, capital X) | [watchfiles_notes] | Regex must be case-insensitive and bullet-agnostic, or completion counts silently drift |
| Idle-repo CPU floor from constant polling | [watchfiles_notes] | Watcher/poller must skip features that are not `in-progress` |
| Debounce needed to avoid duplicate callbacks per save | [watchfiles_notes] | Re-evaluation logic must tolerate/expect coalesced events |

#### How this informs the spec
- AC #2 requires polling within 2 seconds of a save; the source's accepted 1–5 s polling interval [watchfiles_notes] means a 2 s target sits at the fast end of the range — achievable, but the fallback path must be explicitly tuned to ≤2 s rather than the default.
- The "partial save triggers transition" risk in the spec's Key Risks table is directly validated: the source shows the correct fix is triggering on the rename/close (settled) event and re-reading the whole file, not merely requiring 100% boxes [watchfiles_notes]. The spec's mitigation ("require 100% checked") should be augmented with "re-read on settled event."
- The "Regex fragility on non-standard task formats" risk is confirmed and made concrete: the spec should document the expected format AND match case-insensitively across `-`/`*` bullets with optional indentation [watchfiles_notes].
- Open Question #1 (run until killed vs exit after first transition) is not directly answered by the source, but the idle-skip optimisation [watchfiles_notes] favours a long-running watcher that cheaply skips non-`in-progress` features.
- The cross-platform `watchfiles` uniformity finding [watchfiles_notes] lowers the spec's "watchfiles not available on all platforms" likelihood for the three major OSes, isolating the real gap to network/container filesystems (covered by the fallback).

#### Cross-feature connections
- FEAT-903 — shares the polling debounce and idle-skip optimisation for reading each feature's `tasks.md`; its TUI live progress polling explicitly mirrors this file-watcher's idle optimisation and 5 s update target (from: textual_polling_notes). FEAT-903 `depends_on: [feat-902]` and this spec `enables: feat-903`, so the watch/poll core built here is the shared substrate for the TUI dashboard.

#### Research gaps
- *"What exact polling interval meets AC #2's 2 s requirement without excessive CPU?"* — the source gives a 1–5 s range but does not pin a value for the 2 s SLA.
- *"How should a failed transition (e.g. already `done`, AC #4) be detected and surfaced?"* — no source covers transition-failure handling; this is currently an assumption.
- *"Should the watcher exit after the first transition or run until killed (Open Question #1)?"* — not answered by any source.
- *"Should partial completion surface a progress indicator (Open Question #2)?"* — no source addresses progress reporting for a single watched feature.
- *"What is the behaviour when `tasks.md` is absent (AC #3)?"* — no source covers the missing-file case; assumption only.

#### Recommended next actions
1. Enrich a source on `watchfiles` debounce/settle configuration and minimum reliable polling interval to resolve the AC #2 2 s target (the current single source only gives the 1–5 s range) [watchfiles_notes].
2. Run `/ask "How should meridian handle a failed lifecycle transition when the watcher detects completion (AC #4)?"` — no current source covers transition-failure semantics.
3. Create a spike to validate that a 2 s polling fallback plus rename/close-triggered re-read reliably avoids partial-write false positives, since confidence on the race mitigation is medium.
4. Update spec frontmatter: `sources` still lists only `watchfiles_notes.md` and confidence is `medium`; after resolving the polling-interval and transition-failure gaps, consider raising confidence and record the coordination note with FEAT-903's shared polling core.

---

One coverage note: research is grounded in a single source (present as duplicate `.md`/`.txt` files, byte-identical). It's solid but narrow — 7 findings, all from one document, with several ACs (transition-failure handling, missing-file behavior, run-until-killed semantics) still unaddressed. That's not the "5+ strong findings across the spec's open questions" bar for a confidence bump — I'd hold `confidence: medium` as-is until the gaps above (especially AC #4 transition-failure handling) get a source or a `/ask` pass.
