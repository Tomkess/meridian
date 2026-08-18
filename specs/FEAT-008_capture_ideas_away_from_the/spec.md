---
abandoned_at: null
abandoned_reason: null
appetite: m
blocked_at: null
blocked_by: null
confidence: medium
created: '2026-08-18'
cycle: null
depends_on:
- feat-007
enables: []
goal: '~'
id: feat-008
name: Capture ideas away from the PC into a global inbox and triage them into the
  right project
scheduler: null
sources: []
status: in-production
tags: []
updated: '2026-08-18'
---

## Summary

Ideas arrive away from the keyboard. Meridian only accepts them at the keyboard,
inside a specific repo, via `meridian new`. With one project that was a small
tax. Across 10+ installs it is a real leak: by the time there is a PC and the
right repo is checked out, the idea is gone or degraded.

The instinct is to make capture smarter — an email parser that files into the
correct project automatically. That is the wrong shape. The problem is not
transport, it is that **capture time is the worst possible moment to decide
which project an idea belongs to.** On a phone the target repo is unknown,
unimportant, and expensive to specify. Forcing that decision is what makes
capture cost 60 seconds instead of 5, which is why ideas do not get captured.

So split the two concerns:

- **Capture** is dumb, instant, and project-agnostic. Any text, from anywhere,
  into one global inbox. No routing decision. No repo. No structure.
- **Triage** is deliberate, batched, and happens at the PC. One command lists
  what accumulated, suggests a target project per item, and files the survivors.

The routing suggestion is possible only because FEAT-007 put a `project` column
on the shared LanceDB index. Embedding a captured note and searching the shared
store ranks projects by how close their existing research sits to the idea. The
same column that stops repos clobbering each other is what lets a captured idea
find its home.

## Appetite

`m` — 1–2 weeks. Three parts: an inbox format, a project registry, and a triage
command. The capture adapters are deliberately outside that budget (see Scope) —
a directory of markdown files means anything that can write a file already works.

## Acceptance Criteria

### Inbox

- **AC1** — Captures live as individual markdown files in `~/.meridian/inbox/`,
  one file per capture, named by capture timestamp. One file per idea, never an
  append-to-one-file log: concurrent writers from a phone and a laptop must not
  interleave, and triage must be able to move a single item.
- **AC2** — A capture file is valid with **no** frontmatter at all — a bare line
  of text dropped in by any tool is a legitimate capture. Missing metadata is
  inferred (timestamp from filename, falling back to mtime) rather than rejected.
- **AC3** — Optional frontmatter is honoured when present: `project` (skip
  routing), `goal`, `appetite`, `created`.
- **AC4** — An inline `#project-slug` hashtag anywhere in the body is treated as
  an explicit routing hint, equivalent to frontmatter `project`. Zero effort when
  the target is known, no penalty when it is not.
- **AC5** — `meridian capture "<text>"` writes a well-formed capture from any
  directory, including outside a Meridian repo. It requires no `.meridian.toml`,
  so it works from anywhere on the machine.

### Project registry

- **AC6** — `~/.meridian/projects.toml` records each known project: `slug`,
  absolute `path`, and a one-line `purpose`. Triage must work from outside any
  repo, so it cannot discover projects by walking the filesystem.
- **AC7** — `meridian init` and `meridian install` register the current repo,
  keyed by the FEAT-007 project slug. Re-running updates the entry in place
  rather than duplicating it.
- **AC8** — A registry entry whose `path` no longer exists is reported as stale
  and skipped for routing, never silently dropped — a repo may just be on another
  disk.
- **AC9** — `meridian projects` lists registered projects with their slug, path,
  and whether the path currently resolves.

### Triage

- **AC10** — `meridian inbox` lists pending captures with an index, capture date,
  first line, and the suggested target project with a confidence score.
- **AC11** — Suggestions come from embedding the capture text and searching the
  shared LanceDB index across all projects (`project=None`), aggregating hit
  scores per project. Top 3 candidates are shown, never just the winner.
- **AC12** — When the index has no rows for a project, that project can still be
  suggested from its registry `purpose` line. A brand-new project with no research
  must not be permanently unroutable. *Built differently:* the purpose is embedded
  at triage time, not at registry-write time as written here. Embedding on write
  would make `meridian init` depend on Ollama being up, which would be a bad trade
  for a setup command.
- **AC13** — An explicit `project` (frontmatter or `#hashtag`) bypasses semantic
  routing entirely and is shown as `explicit`, not as a score.
- **AC14** — `meridian inbox route <id> <slug>` runs the equivalent of
  `meridian new` in that project's repo and moves the capture file to
  `~/.meridian/inbox/.processed/`. The file is moved, never deleted.
  *Built differently:* the target is a positional argument, not `--project`.
  `test_contracts.py` checks documented flags against `meridian <subcmd> --help`,
  and a flag on a Typer sub-command is not visible there — so `--project` would
  have been undocumentable. Positional is also shorter to type.
- **AC15** — Routing writes the capture's full text into the new spec's body, so
  nothing is lost to summarisation.
- **AC16** — `meridian inbox drop <id>` moves a capture to
  `~/.meridian/inbox/.icebox/`. Also never deletes.
- **AC17** — Routing is idempotent: re-running `route` on an already-processed id
  fails with a clear message rather than creating a duplicate spec.
- **AC18** — Nothing auto-files. There is no mode where a capture becomes a spec
  without a human naming the target. An inbox that files itself produces 40 stub
  specs nobody kills — the 2-minute weekly triage *is* the feature.

### Safety

- **AC19** — Triage never writes into a repo with a dirty working tree without
  saying so: `route` prints the target path and warns if `git status` is unclean.
- **AC20** — A capture containing no routable text (empty, whitespace-only) is
  reported and skipped, not routed.

## Scope

- `meridian/home.py` — machine-global paths and `search_context()`. *Built as a new
  module rather than in `config.py` as first scoped:* `config.py` exists to load a
  repo's `.meridian.toml`, and capture must never import that path.
- `meridian/inbox.py` — capture file read/write, frontmatter and hashtag parsing.
- `meridian/registry.py` — `~/.meridian/projects.toml` read/write/validate.
- `meridian/routing.py` — suggestion engine.
- `meridian/cli.py` — `capture`, `inbox`, `projects` commands, plus the `status` nudge.
- Tests, `CLAUDE.md`, `meridian help`, `specs/STEERING.md`.

## Out of Scope

- **Capture adapters** (iOS Shortcut, email poller, Telegram bot). Deliberately
  excluded: once the inbox is a directory of markdown files, any of them is a
  few lines of glue, and each carries its own auth and infrastructure story.
  Ship the inbox first, add transports as they are actually wanted.
- **Automatic filing.** See AC18 — this is a rejected design, not a missing one.
- **Editing or elaborating captures during triage.** Route it, then run `/spec`.
- **Syncing the inbox between machines.** The directory is sync-tool agnostic on
  purpose; iCloud, Dropbox, or a git repo all work without Meridian knowing.

## Key Risks

- **Triage never happens** and the inbox becomes a graveyard. Partly accepted:
  an unemptied inbox is still better than a lost idea. Mitigated by keeping
  `meridian inbox` cheap to run and surfacing the pending count in
  `meridian status`.
- **Bad routing suggestions erode trust.** Mitigated by AC11 (show three
  candidates with scores, never one) and AC18 (a human always confirms).
- **The registry drifts** as repos move or are deleted. Mitigated by AC8/AC9 —
  report stale entries rather than failing or silently skipping.
- **Semantic routing is weakest exactly when it matters most** — a genuinely new
  idea resembles nothing already indexed. AC12 softens this with registry
  `purpose` text, but a low-confidence suggestion should read as low-confidence
  rather than as a recommendation.

## Dependencies

- **FEAT-007** (`depends_on`). Cross-project routing needs the `project` column
  and the ability to query the shared index unscoped. Without it, the routing
  signal does not exist.

## Related Research

None ingested. Design rationale is captured in this spec's Summary.

## Verification

Manual end-to-end run on 2026-08-18, against the real machine-global home and the
live shared index:

- `meridian capture` from `/tmp` — a directory with no `.meridian.toml` anywhere up
  the tree — succeeded (AC5). This is the path no other CLI test covers, since every
  existing fixture runs inside a repo.
- Five projects registered; `meridian inbox` from `/tmp` ranked a capture reading
  *"annotate a screenshot and pull it into a feature's research corpus"* as:
  `misc (0.56 · index)`, `gdc-mic-ai-evaluation (0.52 · index)`,
  `portfolio-management (0.46 · purpose)`.
  `misc` is the correct top hit — FEAT-006's screenshot chunks are attributed there,
  not to `meridian`. Note the scores cluster tightly; ranking discriminates weakly on
  a 178-chunk store, which is why the display says "likely"/"weak" rather than
  presenting a winner.
- `meridian inbox drop` moved the capture to `.icebox/`, inbox returned to empty.

Two defects were found by running it rather than by testing it, both now fixed and
covered:

1. **Triage produced no suggestions outside a repo.** `suggest()` took a
   `MeridianConfig`, so `load_config()` failing outside a repo silently disabled
   ranking — in exactly the place the inbox is most likely to be read. It now takes
   the store path and model directly, resolved by `home.search_context()`
   (current repo → a registered project's config → documented defaults).
2. **The test suite polluted the real global registry.** `meridian init` registers
   its repo, and the subprocess CLI tests run the real binary, so every test run
   appended pytest temp directories to `~/.meridian/projects.toml` — ten of them
   before it was caught. Fixed by a session-scoped autouse fixture in
   `tests/conftest.py` that sets `MERIDIAN_HOME` for the whole run, including
   subprocesses, plus `tests/test_home_isolation.py` as a standing guard. The real
   registry was cleaned by hand.

Suite: 577 passed, ruff and mypy clean.

## Open Questions

- Should `meridian status` show the pending inbox count, or does that leak global
  state into a per-project dashboard? Leaning yes — an invisible inbox is an
  unemptied inbox.
- Does routing create the spec at `idea` status (matching `meridian new`), or go
  straight to `draft`? Leaning `idea`: routing is a filing decision, not a
  shaping decision.
- Should captures be embedded into the index themselves, so an old idea surfaces
  when a related one arrives? Attractive, but it puts unrouted noise into the
  research corpus. Probably a separate table if it happens at all.
