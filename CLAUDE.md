# Meridian

AI-driven development workflow system. Navigate your codebase with purpose.

## What this repo is

Meridian is a CLI tool + Claude Code skill set that manages the full development lifecycle:
idea → spec → tasks → build → production. It is designed to be installed into other projects.

## CLI

```bash
meridian status                              # full dashboard (task progress, deps, confidence)
meridian status --json                       # machine-readable — for skills and scripts
meridian register                            # track this repo in the cross-project dashboard
meridian install --all                       # push skills into every tracked repo
meridian install --all --pr                  # ...as a PR per repo (working trees untouched)
meridian install --all --prune               # also remove skills Meridian no longer ships
meridian projects                            # list every tracked project
meridian status --all                        # cross-project dashboard (+ staleness, capacity)
meridian next                                # what to work on next, ranked across all projects
meridian next --limit 10 --project <slug>    # bound the list / narrow to one repo
meridian new "idea text" --appetite m        # quick-capture idea with appetite
meridian new "idea" --goal goal-01           # capture linked to a goal
meridian close <feat-id> --status <s>        # lifecycle transition
meridian close <feat-id> --status done       # marks done + reminds to review spec for drift
meridian close <feat-id> --status blocked --blocked-by <reason>
meridian close <feat-id> --status abandoned --abandoned-reason "why"  # reason persists on revive
meridian close <feat-id> --confidence high   # update problem confidence (low|medium|high)
meridian cycle <feat-id> --set 2026-Q2       # assign to planning cycle (warns if overloaded)
meridian cycle <feat-id> --clear             # remove from cycle
meridian enrich <feat-id> <source>...        # add research (PDF/URL/file) — many at once
meridian enrich <feat-id> <dir>              # ingest every .pdf/.txt/.md in a directory
meridian enrich <feat-id> <url> --refresh    # re-fetch a URL already saved in sources/
meridian enrich <feat-id> <image> --note "what is wrong"      # ingest annotated screenshot
meridian enrich <feat-id> --latest-screenshot --note "..."    # grab newest OS screenshot
meridian enrich <feat-id> --from-clipboard --note "..."       # grab clipboard image (macOS)
meridian enrich <feat-id> <image> --note-file <path>          # notes (+ visual reading) from a sidecar
meridian enrich <feat-id> <image> --note "..." --vision       # add local Ollama caption (fallback)
meridian search "query"                      # semantic search across this project's research
meridian search "query" --all-projects       # + a separate "prior art" section from other repos
meridian cite <citation>                     # resolve a citation back to the exact chunk
meridian index                               # rebuild vector index + REGISTRY.md
meridian index --vectors-only                # vectors only — leaves REGISTRY.md untouched
meridian transition --from-merge <branch>    # auto-transition after git merge (branch: feat-NNN/slug)
meridian drift <feat-id>                     # do the ACs match what the branch changed?
meridian guide                               # project setup advisor
meridian help                                # list every command
```

## Slash commands

| Command | Purpose |
|---|---|
| `/vision` | Read/update north star |
| `/goal new` | Create validated goal |
| `/idea` | Capture + map idea to goal (asks appetite) |
| `/spec` | Elaborate into structured spec + ACs |
| `/breakdown` | Technical decomposition → breakdown.md |
| `/tasks` | Atomic task list → tasks.md (triggers in-progress); tasks include `Pre:` preconditions |
| `/decision` | Write ADR |
| `/enrich <feat> "<note>"` | Ingest an attached screenshot + notes + agent visual reading |
| `/ask [question]` | RAG Q&A — answer a question from enriched research |
| `/prior-art <question>` | Have I solved this before, in another repo? |
| `/research <feat>` | Deep synthesis with citations → `summaries/research-<date>.md` |
| `/brief <feat> [source]` | One-page paper brief (≤ 550 words, A4) → summaries/ |

## Releasing

```bash
./scripts/release.sh patch --dry-run     # preview (refuses unless main + clean + synced)
./scripts/release.sh patch               # bump, verify, changelog, tag, GitHub release
meridian install --all --pr              # propagate the new skills to tracked repos
```

Or run `/release` in Claude Code, which drives the same script and handles the
changelog wording.

The version lives in **one** place — `version` in `pyproject.toml`, bumped by
`uv version`. `meridian/__init__.py` reads it back from installed metadata, so there is
nothing to keep in sync and nothing hand-rolled to bump.

Every check runs through `uv run --locked`, so the gate uses the pinned dependency set
rather than whatever interpreter is first on `PATH`. Preflight also refuses on a stale
`uv.lock`, since that would mean testing something other than what ships.

No GitHub Actions minutes are consumed: `gh release create` is a REST call. This repo
is private and its Actions quota is unavailable, so that local gate is the only
verification that runs. Don't skip it.

## Development

```bash
uv sync                       # create .venv from uv.lock (dev group included)
uv run python -m pytest -q    # or: uv run ruff check . / uv run mypy meridian/
uv lock                       # after changing dependencies — commit the lock
```

Dev tooling lives in `[dependency-groups] dev` (PEP 735), not in
`optional-dependencies`, so it is installed by `uv sync` and excluded from the built
package. `rerank` stays a real extra — it is a user-facing install option.

Installed from git, not PyPI — the name is taken there by an unrelated project.

## Research corpus

**Ingestion is incremental.** Every chunk stores a `content_hash` and the
`embedding_model` that produced its vector, so a rebuild re-embeds only what
changed and reuses a vector whenever identical text already has one — across
features *and* across projects, since the vector is a pure function of (text,
model). A no-op `meridian index` makes zero Ollama calls, which is what makes a
large corpus maintainable at all.

Reuse is scoped by model: vectors from two different embedding models are not
comparable, so a model change re-embeds rather than silently mixing spaces.

**Prior art is a separate section, never merged.** The shared store is uneven —
one repo may hold 73 chunks next to another's 2 — so a single blended ranking is
won by whichever repo has written the most, and a search from the small repo
returns nothing of its own. `--all-projects` therefore returns this project's
hits first and complete, then a capped per-project prior-art section. Each
foreign hit carries the absolute path to its feature directory, and one that
cannot be resolved is marked rather than dropped.

**Citations are the row's identity**: `project:FEAT-NNN:source_name#chunk_idx`.
`meridian search` prints one per hit and `meridian cite` resolves it back to the
exact chunk, exiting non-zero when the chunk is gone — the evidence moved, so the
conclusion resting on it is unverified.

**`summaries/` is never indexed.** It holds what Meridian *wrote*. Indexing a
brief would let the next `/research` retrieve the model's own prior conclusion
and cite it as evidence, writing a more confident version of it — a loop that
compounds confidence while the underlying evidence never changes, and that reads
better every round. There is deliberately no flag to opt in, and `enrich`
refuses a source under `summaries/` outright.

## Stack

- Embeddings: Ollama `mxbai-embed-large`
- Vector store: LanceDB at `~/.meridian/lancedb/`
- Reranker: `BAAI/bge-reranker-v2-m3`

## Config

`.meridian.toml` at repo root.

```toml
[meridian]
project        = "my-repo"    # scopes this repo's rows in the shared index
specs_path     = "specs"
lancedb_path   = "~/.meridian/lancedb"
ollama_model   = "mxbai-embed-large"
reranker_model = "BAAI/bge-reranker-v2-m3"

```

`lancedb_path` defaults to `~/.meridian/lancedb`, which **every** Meridian install
shares. `project` is what keeps repos from reading and overwriting each other's
research; it defaults to a slug of the repo directory name. Two checkouts with the
same directory name get the same slug — set `project` explicitly to separate them.

## Multi-project tracking

`~/.meridian/projects.toml` maps project slugs to repo paths. `meridian init` writes an
entry automatically; `meridian register` adds or updates one for an existing repo.

`meridian status --all` reads each tracked repo's `specs/` directly and prints one row
per project with feature counts by lifecycle state. It needs no repo checked out and
answers the question the per-repo dashboard cannot: what is in flight everywhere.

A tracked path that no longer resolves is reported and skipped, never deleted — a repo
may just be on another disk.

### What to work on next

`meridian status --all` tallies. `meridian next` ranks: **blocked longest first, then
in-progress nearest completion, then in-progress that has stalled, then draft, then
idea.** Done, shipped and abandoned features never rank — they are outcomes, not options.

Every row states the signal that put it there ("12 of 15 tasks done", "nothing changed
in 79 days"), because an opaque score would be worse than the tally it replaces. `--json`
carries those raw signals so a skill can re-rank without re-deriving them.

Staleness comes from `spec.md` and `tasks.md` **mtimes, not git** — a fresh clone or a
branch switch resets them, so a dormant repo can look new. The commands say so on every
run rather than hiding it.

Cycle capacity is summed **across** projects: Shape Up's "at most two large bets" is
meaningless per repo when you have ten of them. Features with no cycle are reported as
uncommitted, never folded into zero.

### Propagating skills

`meridian install --all` refreshes `.claude/commands/meridian/` in every tracked repo.
It compares file contents, so a skill you customised locally shows as `outdated` and is
left alone unless you pass `--force`.

`meridian install --all --pr` proposes the same update as a pull request per repo. Each
one is built in a throwaway git worktree off `origin/HEAD`, so no tracked repo's working
tree or HEAD is touched — important when several of them have work in progress. Requires
`gh` and an `origin` remote; repos without one are reported and skipped.

Sync is **additive** by default: a skill deleted from the package lingers in every
repo until you pass `--prune`. That is opt-in because deleting files across ten repos
is a bigger decision than updating them. `--prune` touches only
`.claude/commands/meridian/`, never a project's own commands.

Add `--dry-run` to any of these to see what would change.

## Skill quality

`tests/golden/` is the Layer-3 gate: captured runs of each skill against a fixture
project, scored against `RUBRIC.md`. Re-capture before any breaking prompt change.

Every bundled skill needs a captured run or a documented exemption — a test enforces
it, because a gate covering part of the surface implies coverage that does not exist.
Each run names its *regression-critical behaviour*: the thing a future prompt edit
would plausibly break while looking like an improvement.

## Drift detection

`meridian drift <feat-id>` compares a feature's acceptance criteria against what its
branch actually changed, and `close --status done` runs it automatically.

Each AC names concrete things in backticks — functions, files, flags. If none of them
appears anywhere in the diff, the AC is worth re-reading. It is a **heuristic, not a
verdict**: an AC can be satisfied by code that uses different words. What it reliably
catches is the common failure — an AC written during planning, never built, never
removed from the spec.

It refuses to judge when the current branch is not the feature's branch, and reports
prose ACs (those naming nothing concrete) separately rather than counting them as
failures.

## Machine-readable output

`status`, `status --all`, `projects`, `guide` and `search` take `--json`. Skills and
scripts should use it: it emits compact JSON to stdout with no Rich decoration, so an
agent branches on data instead of parsing a table out of its own context.

Measured on this repo's dashboard: table 5,912 bytes, compact JSON 4,247. Pipe through
`python -m json.tool` when a human needs to read it.

Any unexpected exception is rendered as a one-line error rather than a traceback.
`MERIDIAN_DEBUG=1` restores the traceback.

Lifecycle commands are idempotent: transitioning to the status a feature is already in
succeeds, applies any flags given, and prints `already <status>`. Illegal transitions
still fail. An automation loop can retry safely.

## Specs structure

```
specs/
  VISION.md          ← north star
  STEERING.md        ← AI context: conventions + standards
  CYCLES.md          ← current betting cycle + icebox
  SKILLS.md          ← workflow guide
  REGISTRY.md        ← auto-generated feature index (not committed — see below)
  goals/             ← strategic bets
  decisions/         ← ADRs
  FEAT-NNN_name/
    spec.md          ← requirements + acceptance criteria
    breakdown.md     ← technical design
    tasks.md         ← atomic work units (AI-executable); each task has Pre: preconditions
    sources/
    summaries/
```

### REGISTRY.md is generated, not tracked

`specs/REGISTRY.md` is gitignored. Every row in it is derived from files that *are*
tracked — spec frontmatter, `goals/`, `decisions/` — so committing it protected nothing
while conflicting on nearly every merge, and hand-resolving those conflicts silently
dropped rows.

Any command that mutates specs (`new`, `close`, `cycle`, …) regenerates it, so a fresh
clone is missing it for exactly one command. `meridian guide` reports it as a setup gap
when absent, and as stale when a spec, goal, or decision is newer than the index — which
is the failure mode that matters now that git no longer carries the file.

## Spec frontmatter fields

| Field | Values | Purpose |
|---|---|---|
| `status` | `idea\|draft\|in-progress\|blocked\|done\|in-production\|abandoned` | Lifecycle state |
| `appetite` | `xs\|s\|m\|l` | How much time this is worth (set before spec) |
| `confidence` | `low\|medium\|high` | How well the problem is understood (hill chart proxy) |
| `cycle` | e.g. `2026-Q2` | Planning cycle this is bet on |
| `depends_on` | list of feat IDs | Explicit dependencies (surfaced in `meridian status`) |
| `enables` | list of feat IDs | Features this unlocks |
| `blocked_by` | string or feat ID | Required when `status: blocked` |
| `blocked_at` | ISO date | Set automatically when entering `blocked`; cleared on unblock |
| `abandoned_reason` | string | Why it was killed — persists through revive for future context |
| `abandoned_at` | ISO date | Set automatically when abandoned; cleared on revive |
| `sources` | list of `sources/...` refs | Research indexed into the corpus |
| `briefs` | list of `summaries/...` refs | Persisted synthesis, so a reader of `spec.md` finds the reasoning without listing the directory |

## Appetite scale

`xs` < 1 day  ·  `s` 1–3 days  ·  `m` 1–2 weeks  ·  `l` 2–6 weeks

## Lifecycle

```
💡 idea → 📝 draft → 🔨 in-progress → ✅ done → 🚀 in-production
                           ↕
                        🚫 blocked
                           ↓
                      🗑  abandoned → (revive) → 💡 idea
```

| Status | Meaning | Trigger |
|---|---|---|
| `idea` | Raw capture — stub spec, no ACs yet | — |
| `draft` | Spec elaborated; breakdown + tasks pending | Run `/spec` |
| `in-progress` | Tasks generated; actively being built | Run `/tasks` |
| `done` | Built, not yet released | `meridian close --status done` |
| `in-production` | Live | `meridian close --status in-production` or `meridian transition --from-merge` |

## Key behaviors

- **`meridian status`** shows task progress inline (`🔨 in-progress [9/15]`), `Conf` column, and a Dependencies section for features with `depends_on`/`enables` set.
- **`meridian cycle --set`** prints cycle capacity summary after assignment and warns if the cycle is overloaded (Shape Up: ≤2 large bets recommended).
- **`meridian close --status done`** prints a reminder to review `spec.md` for implementation drift.
- **`meridian transition --from-merge`** requires branch name to contain `feat-NNN` (e.g. `feat-007/add-search`). Prints a tip if no match is found.
- **`/tasks`** generates tasks with `Pre:` precondition lines so AI agents can start any task without stalling on missing context.
