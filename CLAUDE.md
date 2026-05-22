# Meridian

AI-driven development workflow system. Navigate your codebase with purpose.

## What this repo is

Meridian is a CLI tool + Claude Code skill set that manages the full development lifecycle: idea → spec → implementation → production. It is designed to be installed into other projects.

## CLI

```bash
meridian status                          # full dashboard
meridian new "idea text"                 # quick-capture idea
meridian enrich <feat-id> <source>       # add research (PDF/URL/image)
meridian close <feat-id> --status <s>    # lifecycle transition
meridian sync-jobs                       # auto-link Databricks jobs
meridian index                           # rebuild vector index
meridian transition --from-merge <branch>
```

## Slash commands

| Command | Purpose |
|---|---|
| `/vision` | Read/update north star |
| `/goal new` | Create validated goal |
| `/idea` | Capture + map idea to goal |
| `/spec` | Elaborate into structured spec |
| `/connect-dots` | Cross-feature awareness |
| `/breakdown` | Technical decomposition |
| `/plan` | Phased implementation plan |
| `/roadmap` | Goals × features × gaps |
| `/challenge` | Stress-test against vision |
| `/decision` | Write ADR |

## Stack

- Embeddings: Ollama `mxbai-embed-large`
- Vector store: LanceDB at `~/.meridian/lancedb/`
- Reranker: `BAAI/bge-reranker-v2-m3`
- Scheduler: Databricks Jobs API

## Config

`.meridian.toml` at repo root. See `.meridian.toml` for all options.

## Specs structure

```
specs/
  VISION.md          ← north star
  SKILLS.md          ← workflow guide
  REGISTRY.md        ← feature index
  goals/             ← strategic bets
  decisions/         ← ADRs
  FEAT-NNN_name/
    spec.md
    breakdown.md
    sources/
    summaries/
```
