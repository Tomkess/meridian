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
status: draft
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
  suggested from its registry `purpose` line, embedded at registry-write time.
  A brand-new project with no research must not be permanently unroutable.
- **AC13** — An explicit `project` (frontmatter or `#hashtag`) bypasses semantic
  routing entirely and is shown as `explicit`, not as a score.
- **AC14** — `meridian inbox route <id> --project <slug>` runs the equivalent of
  `meridian new` in that project's repo and moves the capture file to
  `~/.meridian/inbox/.processed/`. The file is moved, never deleted.
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

- `meridian/inbox.py` — capture file read/write, frontmatter and hashtag parsing.
- `meridian/registry.py` — `~/.meridian/projects.toml` read/write/validate.
- `meridian/cli.py` — `capture`, `inbox`, `projects` commands.
- `meridian/config.py` — locate the global Meridian home independently of any repo.
- Tests, `CLAUDE.md`, `meridian help`.

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
