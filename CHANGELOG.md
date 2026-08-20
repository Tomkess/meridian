# Changelog

## 0.6.1 — 2026-08-20

### Fixed

- **`meridian drift` survives the merge** (FEAT-027). It compared a feature's
  criteria against its branch's diff against `main`, and once the branch is
  merged that diff is empty. But `close --status done` runs drift automatically,
  and by then the branch is usually already merged — so the one moment the check
  fired was the one moment it could say nothing, and it said it in a way that
  reads like a clean bill of health rather than a failure to look. Found by using
  it: all four of FEAT-023–026 reported "nothing to compare" straight after
  merging, and the report looked fine.

  `assess()` now falls back to the feature's commits in the base branch, found
  three ways and unioned — a merge commit naming it, a commit whose message names
  it (what a squash merge leaves), and commits touching its spec directory. A
  merge is diffed against its **first** parent, so unrelated mainline work is not
  counted as the feature's. Branch mode still wins when the branch holds the work.

- **A sibling spec can no longer satisfy an acceptance criterion.** The fallback
  above required this. A spec states its own criteria, so a spec in the haystack
  lets every AC match its own text — which is why the original excluded the
  feature under assessment. That was enough while a diff covered one feature; in
  history mode a single commit that shapes or closes four features drags all four
  specs in. Verified before fixing: FEAT-024's haystack held FEAT-023's, 025's and
  026's spec text. `specs/FEAT-*` is now excluded wholesale, while `REGISTRY.md`,
  `goals/` and `CYCLES.md` stay visible for an AC to name.

- **An empty search reports as empty.** When neither a branch diff nor a matching
  commit exists, the message names both searches that came back and states the
  branch/commit convention, instead of printing something a reader takes for a
  pass.

Five of six new tests fail against the previous implementation; the sixth passes
there for the wrong reason, so a seventh pins the exclusion by running one
history through both exclusion sets.

908 tests, ruff and mypy clean.

## 0.6.0 — 2026-08-20

Invests in the two capabilities nothing else offers — the spec-bound research
corpus and the cross-repo portfolio view — under a new `goal-01`. Everything
here serves one of those two; the spec pipeline was deliberately left alone.

### Added

- **Cross-project prior art** (FEAT-024). `--all-projects` now returns this
  project's hits first and complete, then a separate, capped **Prior art**
  section from other repos. Never merged, because the shared corpus is uneven
  enough that a blended ranking is won by whichever repo has written the most:
  measured on the real store, a merged ranking of a representative query
  returned **zero** rows from the 2-chunk repo in its top 20 — its own research
  was invisible, not merely outranked. Every foreign hit carries the absolute
  path to its feature directory; one that cannot be resolved is marked, never
  dropped. New `/prior-art` skill, and an opt-in on `/ask`.
- **Resolvable citations** (FEAT-025). `meridian search` prints
  `project:FEAT-NNN:source_name#chunk_idx` per hit — the four fields that
  already identify a row, so no schema change and no second identity to
  disagree with the first. `meridian cite <citation>` resolves it back to the
  exact chunk and **exits non-zero when the chunk is gone**: the evidence moved,
  so the conclusion resting on it is unverified. Resolves across projects via
  the registry, distinguishing "project untracked" from "chunk missing".
- **`/research` and `/brief` persist** to `summaries/research-YYYY-MM-DD.md`,
  recorded in a new `briefs:` frontmatter field. Same-day re-runs update that
  day's file; an earlier one is never modified, because the diff is the only
  record that a conclusion changed. Uncited claims are labelled inferences.
- **`meridian next`** (FEAT-026) ranks work across every tracked project with no
  repo checked out: blocked longest → in-progress nearest completion →
  in-progress stalled → draft → idea. Every row states the signal that put it
  there, because an opaque score would be worse than the tally it replaces.
- **`status --all` gains staleness and cycle capacity.** Capacity is summed
  *across* projects — Shape Up's "at most two large bets" is meaningless per
  repo when you have ten. Staleness comes from file mtimes, not git, and the
  output says so on every run: a fresh clone resets them.

### Changed

- **Ingestion is incremental and deduplicated** (FEAT-023). Every chunk stores a
  `content_hash` and its `embedding_model`; a rebuild re-embeds only what
  changed and reuses a vector whenever identical text already has one, across
  features and across projects. A no-op `meridian index` now makes **zero**
  Ollama calls where it previously re-embedded the entire corpus — the reason
  corpus maintenance cost used to scale with corpus size. Reuse is scoped by
  model, since vectors from different models are not comparable.
- **`meridian enrich` takes several sources**, or a directory (non-recursive).
  Per-source atomic, so one unreadable file does not lose what already
  ingested; reports per-source outcome and exits non-zero if any failed.
- **A URL already in `sources/` is no longer silently re-fetched.** `--refresh`
  opts in.
- **The schema migration is additive, never destructive.** A store predating the
  hash columns is backfilled in place — no row is deleted before its replacement
  exists, and an Ollama failure mid-migration leaves the store untouched and
  exits non-zero. Verified against a real 178-chunk store across five projects:
  178 rows before, 178 after, every project's counts identical.

### Fixed

- **`summaries/` can no longer be indexed** — now on purpose rather than by
  accident of a glob. An indexed brief would let the next `/research` retrieve
  the model's own prior conclusion and cite it as evidence, compounding
  confidence while the evidence never changes, and reading *better* each round.
  The symlink route is closed too, and `enrich` refuses such a source outright.
  There is deliberately no flag to opt in.
- **The whole-project delete before each rebuild is now targeted.** Left as-is,
  incremental indexing would have deleted every *skipped* source's rows — the
  new feature would have quietly eaten the corpus.
- **`meridian guide` judges `STEERING.md` by its prose**, not its comment count.
  It flagged Meridian's own 3.4 KB steering file as an unfilled template, and
  passed a single large comment wrapped around nothing.

901 tests (was 655), ruff and mypy clean.

## 0.5.0 — 2026-08-19

Clears the post-audit backlog. The riskiest code in the project — the part that
writes to *other people's repositories* — is now testable and tested, and two
latent data bugs found along the way are closed.

### Added

- **ADRs in `REGISTRY.md`** (FEAT-021). `specs/decisions/` was write-only: no
  skill could see a decision already made, so decisions got silently
  re-litigated. Both ADR shapes are read — the early ones carry YAML
  frontmatter, the ones `/decision` writes carry a `**Status:**` line instead.
- **`meridian guide` step 9 — Registry.** Reports the index as missing, or as
  stale when a spec, goal, or decision is newer than it.

### Changed

- **`specs/REGISTRY.md` is no longer committed** (FEAT-022). Every row is derived
  from files that *are* tracked, so committing it protected nothing while
  conflicting on nearly every merge — and hand-resolving those conflicts had
  silently dropped rows. Rejected `merge=ours`, which needs a per-clone git
  config and, when forgotten, fails silently.
- **Skill distribution extracted to `meridian/skilldist.py`** (FEAT-020).
  `cli.py` 1,927 → 1,718 lines. The module returns data and imports neither
  `typer` nor `rich`; `cli.py` keeps all rendering. That boundary is what makes
  the git and GitHub paths testable — 27 new tests run against real temporary
  git repositories rather than mocked subprocesses, including a direct check
  that a PR run leaves the target repo's working tree and HEAD untouched.
  `install` output was verified byte-identical before and after.

### Fixed

- **A malformed goal file no longer crashes `rebuild_registry`.** FEAT-013
  closed this shape for specs and FEAT-021 closed it for decisions, but the
  goals loop still called `frontmatter.load` unguarded. The rebuild runs *after*
  a spec is written to disk, so one bad goal left the spec saved, the registry
  stale, and a traceback on screen. The goal is now reported as `unparseable`
  and indexing continues.
- **`load_config` resolves its path.** A relative start made the config's parent
  `Path(".")`, whose `.name` is `""`, collapsing the project slug to
  `unknown-project`. That is FEAT-007's cross-project deletion re-entering
  through a path gap: the LanceDB index is shared by every install, so all repos
  loading a relative config wrote under one slug — and `meridian index` in any of
  them would delete the others' research.

655 tests (was 608), ruff and mypy clean.

## 0.4.0 — 2026-08-19

Completes the audit follow-through: the spec-vs-code promise is now measured
rather than asserted, and the quality gate covers the skills that could degrade
silently.

### Added

- **`meridian drift <feat-id>`** — checks whether a feature's acceptance criteria
  match what its branch actually changed, and runs automatically on
  `close --status done`. Each AC names functions, files and flags in backticks;
  if none appears in the diff, the AC is worth re-reading. A heuristic, and the
  output says so — but it reliably catches the common failure: an AC written
  during planning, never built, never removed.
- **`meridian install --prune`** — removes skills that no longer ship with
  Meridian. Sync was additive with no opt-out, so a skill deleted upstream
  lingered in every repo forever.

### Fixed

- **`MERIDIAN_HOME` now redirects the vector store.** It never did: `init`
  hardcoded `~/.meridian/lancedb` and `load_config` ignored the variable, so any
  test or sandbox following the documented safety instruction still read and
  wrote the real store. The most plausible mechanism behind the global store
  being destroyed on 2026-08-18.
- **Feature IDs are validated before use.** Two near-identical globs interpolated
  the raw string and took `candidates[0]` of an unsorted result, so a glob
  metacharacter hit the wrong feature and the pick varied between machines. One
  resolver now validates `^FEAT-\d{3,}$` and refuses ambiguous matches.
- **`enrich` refuses non-text input** instead of embedding mojibake that `/ask`
  later returns as research.
- **`REGISTRY.md` cells escape pipes and newlines**, so a feature name cannot
  shift every column of a file the AI reads as truth.
- **A failed LanceDB delete is logged**, not swallowed — silence there leaves
  duplicate rows that degrade every later search.
- **`done` and `in-production` can be abandoned directly**, instead of walking
  backwards through `in-progress` and polluting the dashboard counters.

### Testing

- Golden-set coverage extended from 5 of 15 skills to **10 of 11**, with one
  documented exemption. The previously uncovered skills were the write-side ones:
  `/enrich`, which writes prose the corpus later returns as fact, and `/vision`,
  which rewrites the north star unrecoverably.
- Each captured run names its *regression-critical behaviour* — the thing a
  future prompt edit would plausibly break while looking like an improvement.
- Coverage cannot rot silently: a skill without a run or an argued exemption
  fails the suite.

608 tests, up from 567.

## 0.3.0 — 2026-08-19

The release that followed a five-phase audit: four verified data-loss defects
closed, a third of the surface cut, and the CLI made safe for an agent to drive.

### Fixed — data loss

- **Concurrent edits no longer destroy a spec.** `spec_lock` guarded only
  `transition_spec`, while `cycle`, `link-job`, `unlink-job` and `enrich` saved
  unlocked — and `save_spec` truncated before writing. Writes are now atomic
  (`os.replace`) and every read-modify-write goes through a new `edit_spec()`
  context manager. Measured on 20 concurrent appends: 3 of 20 survived before,
  20 of 20 after.
- **The project registry can no longer be silently deleted.** A newline in
  `--purpose`, or one corrupt byte, produced unparseable TOML that the next
  write rebuilt from an empty list. Now serialised with `tomli_w`, backed up to
  `.bak`, and never overwritten when unreadable.
- **`meridian index` no longer destroys the corpus on failure.** It deleted
  before embedding, so Ollama being down wiped a project's research and exited
  0 claiming it had not rebuilt. It now embeds first and exits 1 on failure.
- **Shipped skills are under contract.** The CLI-contract test scanned only the
  dogfooded copies, never the bundled directory that `meridian install` ships —
  a broken skill could pass every gate and fail in a downstream repo.

### Added

- `--json` on `status`, `status --all`, `projects`, `guide` and `search`.
  Compact output for skills and scripts: 4,247 bytes where the table is 5,912.
- `meridian register`, `meridian projects`, and `meridian status --all` — a
  cross-project dashboard that needs no repo checked out.
- `meridian install --all` and `--all --pr` to propagate skills to every tracked
  repo, the PR form building each update in a throwaway git worktree so no
  repo's working tree is touched.
- `meridian index --vectors-only`, for repopulating another repo without
  rewriting its `REGISTRY.md`.
- Screenshot ingestion: `meridian enrich <feat> <image> --note`, plus
  `--latest-screenshot`, `--from-clipboard`, `--note-file` and `--vision`.
- `scripts/release.sh` and a `/release` skill. Zero GitHub Actions minutes.

### Changed

- **Per-project scoping of the shared vector index.** Every row now carries a
  `project`; searches scope to the current one, with `--all-projects` to widen.
  Before this, indexing one repo deleted every other repo's vectors.
- **Lifecycle commands are idempotent.** Transitioning to the status a feature
  already holds succeeds and prints `already <status>`; illegal transitions
  still fail. An automation loop can retry safely.
- **Errors are one line, not a traceback.** `MERIDIAN_DEBUG=1` restores detail.
- The dev workflow is `uv sync` / `uv run --locked`; dev tooling moved to
  `[dependency-groups]`, and the version is single-sourced in `pyproject.toml`.
- `meridian help` is generated from the registered commands, so it cannot drift.

### Removed

- **The Databricks integration** — 295 lines, never used, and a documented path
  to committing a token into a git-tracked file.
- **Four skills**: `/plan`, `/challenge`, `/roadmap`, `/connect-dots`. None had
  quality coverage and Claude Code's plan mode covers them.
- **The 309-line hand-written manual**, which had already drifted.

Net: 4,355 → 3,753 lines, with 567 tests where there were 370.

### Note for existing installs

`pip install meridian` installs an unrelated PyPI package. Install from git:

```
uv tool install git+https://github.com/Tomkess/meridian@v0.3.0
```

## 0.2.0 — 2026-07-20

- Guard against LanceDB Python-3.14 segfault
- Namespaced skill install under `.claude/commands/meridian/`

