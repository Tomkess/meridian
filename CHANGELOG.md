# Changelog

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

