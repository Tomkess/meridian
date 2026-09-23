# 007 — Skills install globally; consumer repos track nothing

**Status:** Accepted  
**Date:** 2026-09-23  
**Context:** FEAT-010 (propagate skills to registered projects), FEAT-016 (`install --prune`), FEAT-020 (skilldist module); affects `meridian init`, `meridian install`, `meridian/skilldist.py`, every registered project

## Decision

Meridian's slash commands live in exactly one place per machine: **`~/.claude/commands/meridian/`,
written by `meridian install`.** Consumer repos do not track `.claude/commands/meridian/` or
`.meridian.toml`; both are gitignored. The namespace is unaffected — Claude Code derives
`/meridian:spec` from the directory name, not the repo, and the command files carry no `name:`
frontmatter to override it.

One exception: **the `meridian` repo itself keeps its copies tracked.** There they are not a
distribution channel but a test fixture — `tests/test_skill_sync.py` (FEAT-003) asserts
`.claude/commands/meridian/` matches `meridian/skills/commands/` byte for byte, and that guard is
what catches an edited bundled skill that was never re-synced. This repo dogfoods; everything else
consumes.

The decision was forced by measurement, not preference. A survey of the 12 projects in
`~/.meridian/projects.toml` found three incompatible states: 6 repos tracking commands, 1 tracking
only `.meridian.toml`, 4 tracking nothing, plus the meridian repo. Two of the tracking repos
(`betting-data-science`, `gd-ecommerce-demo`) carried 14 files including `challenge.md`,
`connect-dots.md`, `plan.md` and `roadmap.md` — four skills Meridian no longer ships — while missing
`enrich.md` and `prior-art.md`. Propagation was built to prevent exactly that drift and had not been
run often enough to do so.

`meridian init` continues to plant repo-local copies; under this ADR they land untracked and are
harmless. That is deliberate: `init` stays a one-command bootstrap, and the gitignore is what makes
the distinction.

## Alternatives Considered

| Option | Pros | Cons |
|---|---|---|
| Chosen: global-only, consumer repos gitignore | One version per machine; drift impossible by construction; colleagues clone nothing that fails on first use | `init` output must be gitignored per repo; propagation features retired |
| Per-repo tracked copies + run `install --all --pr` on every release | Commands versioned with the project; a colleague sees which skills the specs were authored under | Every colleague needs the CLI, `~/.meridian/lancedb`, Ollama `mxbai-embed-large`, and `BAAI/bge-reranker-v2-m3` — the search skills and `spec`/`idea`/`goal` all shell out and fail without them; drift is a live problem the moment a release ships without propagation |
| Repo-local copies, propagation only for repos flagged `shared = true` | Keeps team repos current, leaves solo repos alone | A third state to reason about; same workstation dependency wherever it is enabled |
| Ship the skills as a Claude Code plugin | Real distribution channel with its own update path | Meridian is a `uv`/pip CLI with one entry point; skills without the binary are inert, so the plugin would not stand alone |

## Consequences

- **Positive:** a single skill set per machine, updated by one command (`meridian install`, no flags);
  the four dead skills stop propagating; consumer repos ship only the artifacts that are actually
  portable — `specs/`, ADRs, `REGISTRY.md`, `STEERING.md`; a clone no longer carries 12 commands that
  fail on a machine without the local stack.
- **Negative / trade-offs:** `meridian install --all --pr` (FEAT-010) and `--prune` (FEAT-016) lose
  their purpose — `git add` skips ignored paths, so a propagation run against a gitignored repo
  reports "no net change" and opens nothing. Both stay in `skilldist.py` serving the `--local` and
  in-repo (meridian's own) paths, but the `--pr` flow is no longer part of the release ritual, and
  `scripts/release.sh` should stop invoking it. A project's skills now track the machine, not the
  commit — checking out an old branch no longer gives the skills that authored it.
- **Neutral:** `meridian init` behaviour is unchanged; only the gitignore differs. `.meridian.toml`
  becomes machine-local config (it already only held `lancedb_path`, model names and `specs_path` —
  all workstation-scoped). Project identity lives in `~/.meridian/projects.toml`, which was always
  global.

## Revisit Trigger

Revisit if Meridian gains a distribution path that does not require the local stack — skills that
degrade gracefully without LanceDB and Ollama, or a hosted index — because then repo-local copies
would work for colleagues and versioning the skills with the specs becomes worth the drift risk.
Also revisit if Claude Code adds per-project command pinning or a lockfile, which would make
"the skills that authored this commit" recoverable without tracking the files.
