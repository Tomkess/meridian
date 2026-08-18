# Meridian

AI-driven development workflow system. Navigate your codebase with purpose.

## What this repo is

Meridian is a CLI tool + Claude Code skill set that manages the full development lifecycle:
idea → spec → tasks → build → production. It is designed to be installed into other projects.

## CLI

```bash
meridian status                              # full dashboard (task progress, deps, confidence)
meridian register                            # track this repo in the cross-project dashboard
meridian projects                            # list every tracked project
meridian status --all                        # cross-project dashboard
meridian new "idea text" --appetite m        # quick-capture idea with appetite
meridian new "idea" --goal goal-01           # capture linked to a goal
meridian close <feat-id> --status <s>        # lifecycle transition
meridian close <feat-id> --status done       # marks done + reminds to review spec for drift
meridian close <feat-id> --status blocked --blocked-by <reason>
meridian close <feat-id> --status abandoned --abandoned-reason "why"  # reason persists on revive
meridian close <feat-id> --confidence high   # update problem confidence (low|medium|high)
meridian cycle <feat-id> --set 2026-Q2       # assign to planning cycle (warns if overloaded)
meridian cycle <feat-id> --clear             # remove from cycle
meridian enrich <feat-id> <source>           # add research (PDF/URL/file)
meridian enrich <feat-id> <image> --note "what is wrong"      # ingest annotated screenshot
meridian enrich <feat-id> --latest-screenshot --note "..."    # grab newest OS screenshot
meridian enrich <feat-id> --from-clipboard --note "..."       # grab clipboard image (macOS)
meridian enrich <feat-id> <image> --note-file <path>          # notes (+ visual reading) from a sidecar
meridian enrich <feat-id> <image> --note "..." --vision       # add local Ollama caption (fallback)
meridian search "query"                      # semantic search across this project's research
meridian search "query" --all-projects       # widen to every project sharing the index
meridian index                               # rebuild vector index + REGISTRY.md
meridian index --vectors-only                # vectors only — leaves REGISTRY.md untouched
meridian transition --from-merge <branch>    # auto-transition after git merge (branch: feat-NNN/slug)
meridian guide                               # project setup advisor
meridian help                                # full manual
```

## Slash commands

| Command | Purpose |
|---|---|
| `/vision` | Read/update north star |
| `/goal new` | Create validated goal |
| `/idea` | Capture + map idea to goal (asks appetite) |
| `/spec` | Elaborate into structured spec + ACs |
| `/connect-dots` | Cross-feature awareness |
| `/breakdown` | Technical decomposition → breakdown.md |
| `/tasks` | Atomic task list → tasks.md (triggers in-progress); tasks include `Pre:` preconditions |
| `/plan` | Phased strategy → plan.md (optional) |
| `/roadmap` | Goals × features × gaps |
| `/challenge` | Stress-test against vision |
| `/decision` | Write ADR |
| `/enrich <feat> "<note>"` | Ingest an attached screenshot + notes + agent visual reading |
| `/ask [question]` | RAG Q&A — answer a question from enriched research |
| `/research <feat>` | Deep synthesis — findings, gaps, next research actions |
| `/brief <feat> [source]` | One-page paper brief (≤ 550 words, A4) → summaries/ |

## Stack

- Embeddings: Ollama `mxbai-embed-large`
- Vector store: LanceDB at `~/.meridian/lancedb/`
- Reranker: `BAAI/bge-reranker-v2-m3`
- Scheduler: Databricks Jobs API

## Config

`.meridian.toml` at repo root.

```toml
[meridian]
project        = "my-repo"    # scopes this repo's rows in the shared index
specs_path     = "specs"
lancedb_path   = "~/.meridian/lancedb"
ollama_model   = "mxbai-embed-large"
reranker_model = "BAAI/bge-reranker-v2-m3"

[databricks]
host      = "https://your-workspace.azuredatabricks.net"
token_env = "DATABRICKS_TOKEN"
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

## Specs structure

```
specs/
  VISION.md          ← north star
  STEERING.md        ← AI context: conventions + standards
  CYCLES.md          ← current betting cycle + icebox
  SKILLS.md          ← workflow guide
  REGISTRY.md        ← auto-generated feature index
  goals/             ← strategic bets
  decisions/         ← ADRs
  FEAT-NNN_name/
    spec.md          ← requirements + acceptance criteria
    breakdown.md     ← technical design
    tasks.md         ← atomic work units (AI-executable); each task has Pre: preconditions
    plan.md          ← phased strategy (optional)
    sources/
    summaries/
```

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
