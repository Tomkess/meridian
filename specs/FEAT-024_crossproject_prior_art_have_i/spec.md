---
abandoned_at: null
abandoned_reason: null
appetite: s
blocked_at: null
blocked_by: null
confidence: high
created: '2026-08-19'
cycle: 2026-Q3
depends_on:
- feat-023
enables: []
goal: goal-01
id: feat-024
name: 'Cross-project prior art: have I solved this before'
sources: []
status: draft
tags: []
updated: '2026-08-20'
---

## Summary

The LanceDB store is shared by every Meridian install and scoped by a `project`
column, so the data to answer *"have I solved this before, in another repo?"*
already exists. `meridian search --all-projects` already queries it. Nothing
surfaces it: no skill uses the flag, results carry no repo path, and there is no
way to act on a hit beyond reading the chunk text.

That question is the sharpest thing Meridian can do and the one no competitor
can: a per-repo assistant cannot see the other nine repos, and a hosted tool
does not have them. Today the shared store is close to a pure liability — it has
caused three separate data bugs (FEAT-007, FEAT-018, and the `load_config` slug
collapse) and returned nothing in exchange.

This makes prior art a first-class result: separately ranked, attributed to a
repo you can open, and reachable from the skills rather than only the CLI.

## Appetite

`s` — the retrieval already works. This is ranking, presentation, a join against
the project registry, and a skill.

## Design decisions

**Foreign hits are ranked separately and never interleaved.** The corpus is
wildly uneven: `portfolio-management` holds 73 chunks, `misc` 52,
`gdc-mic-ai-evaluation` 43, `meridian` 2. A merged ranking searched from
`meridian` returns almost nothing of its own — the biggest corpus wins on volume
regardless of relevance. So local results are returned first and complete, and
prior art is a separate, explicitly labelled section with its own limit. This
also matches how the answer is used: *my* research is context, *another repo's*
research is a lead.

**A prior-art hit must be openable.** A chunk of text from an unnamed repo is
trivia. `~/.meridian/projects.toml` maps slug → path, so every foreign hit can
carry the repo path and the feature directory. The join is what turns a search
result into an action.

**Prior art is opt-in per query, not a default.** Widening every search by
default would quietly change what every existing skill retrieves, including
`/ask`, whose answers are already treated as fact. The widening must be a
deliberate act with visibly different output.

**A missing repo is reported, not hidden.** A tracked path that no longer
resolves still has rows in the store. Its hits stay useful — the text is right
there — but must be marked, matching how `meridian projects` already treats
stale paths.

## Acceptance Criteria

### Retrieval and ranking

- **AC1** — `meridian search "<q>" --all-projects` returns the current project's
  hits first and complete, then a separate **Prior art** section for other
  projects. The two sets are never interleaved.
- **AC2** — The prior-art section has its own limit (`--prior-art N`), so a large
  foreign corpus cannot crowd out local results.
- **AC3** — At most a stated number of hits per foreign project, so one
  73-chunk repo cannot fill the whole section.
- **AC4** — Prior-art hits are omitted entirely when the query has no foreign
  match above the same relevance bar applied locally. An empty section is
  printed as "no prior art found", not as silence.

### Attribution

- **AC5** — Every prior-art hit names its project, its feature ID, and its
  source file.
- **AC6** — Each hit carries the **absolute path** to the feature directory,
  resolved from `~/.meridian/projects.toml`, so it can be opened directly.
- **AC7** — A hit whose project is untracked or whose path no longer resolves is
  still returned, marked as unresolvable, and never omitted — the research is
  real even when the checkout has moved.
- **AC8** — `--json` carries every field above, so a skill branches on data
  rather than parsing a table.

### Skill surface

- **AC9** — A `/prior-art <question>` skill answers "have I solved this before"
  by searching across projects and reporting, per hit, what the other project
  concluded and where to read it.
- **AC10** — The skill states plainly when the answer comes from another repo,
  and never presents a foreign conclusion as this project's own.
- **AC11** — `/ask` gains an explicit opt-in to widen to prior art, and its
  default behaviour is unchanged.

### Guards

- **AC12** — A test with an uneven fixture — one project with many chunks, the
  current project with one — asserts the local hit is still returned first. This
  is the exact failure the separate ranking exists to prevent, and it reproduces
  the real corpus's shape.
- **AC13** — A test asserts an ordinary `meridian search` (no flag) returns
  **only** the current project's rows. The widening must never leak into the
  default path.

## Scope

`meridian/search.py` (a prior-art pass with its own limits), `meridian/cli.py`
(rendering and flags), a new `/prior-art` skill, `/ask` opt-in, and tests.

## Out of Scope

- **Ranking foreign hits by project recency or importance.** Tempting, and
  unjustifiable until there is evidence about which signal predicts usefulness.
  Relevance and a per-project cap are enough to start.
- **Reading another repo's `spec.md` to summarise its conclusion.** The path is
  provided; following it is the agent's job. Making the CLI read across repo
  boundaries turns a search command into a filesystem crawler.
- **Writing prior-art findings into this project's spec.** That is [[FEAT-025]].
- **De-duplicating a hit that appears in several projects.** [[FEAT-023]] gives
  identical content one hash, which makes this cheap later; doing it here would
  hide that the same document is cited in three places, which is itself useful.

## Key Risks

- **The corpus is too thin for prior art to fire.** With 178 chunks across five
  projects, many queries will legitimately return nothing. AC4 makes that state
  explicit rather than making the feature look broken. The real fix is
  [[FEAT-023]] plus habit, which is why this depends on it.
- **A foreign conclusion gets adopted without its context.** Another repo's ADR
  was right *there*. AC10 is the guard, and it is a prompt-level guard, which is
  the weakest kind — worth a golden run.
- **The shared store becomes load-bearing.** It has caused three data bugs. This
  makes it valuable, which makes those bugs more expensive, not less.

## Verification

Against the real corpus: a query from `meridian` (2 chunks) must still surface
its own hit first while returning prior art from `portfolio-management` (73
chunks). That is the ordering property, tested on the shape that breaks it.
