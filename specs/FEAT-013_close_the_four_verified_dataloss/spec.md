---
abandoned_at: null
abandoned_reason: null
appetite: s
blocked_at: null
blocked_by: null
confidence: high
created: '2026-08-19'
cycle: null
depends_on: []
enables: []
goal: '~'
id: feat-013
name: 'Close the four verified data-loss defects: atomic locked spec writes, unloseable
  registry, atomic index, contract-tested skills'
scheduler: null
sources: []
status: in-progress
tags: []
updated: '2026-08-19'
---

## Summary

A five-phase audit of Meridian v0.2.0 produced 55 raw findings; 16 were dropped
during adversarial verification and 10 survived. Four of the survivors are
data-loss defects, and they share a shape: **all four are silent, all four are
unrecoverable, and all four either print ✓ or exit 0.**

Worse, three of them sit on the only features the audit found genuinely
differentiated — the cross-repo registry and the research corpus. Meridian beat
its null hypothesis in three places and lost your data in two of them.

The four:

1. **Concurrent `cycle` + `close` destroys a spec.** `spec_lock` guarded only
   `transition_spec`; `cycle`, `link-job`, `unlink-job` and `enrich` all did an
   unlocked load → mutate → save, and `save_spec` used `Path.write_text`, which
   truncates before writing. 4 of 75 audit trials left a spec with 4 frontmatter
   keys and no body.
2. **Lost updates between the same commands.** 15 of 75 trials silently
   discarded one of two writes while both printed success.
3. **Two paths silently delete the whole project registry.** A newline in
   `--purpose` produced unparseable TOML; `all_projects()` swallowed the parse
   error and returned `[]`; the next write rewrote the file from that empty
   list. `meridian projects` even printed "No projects tracked. Run `meridian
   register`" — steering the user into the destructive command.
4. **`meridian index` deletes the corpus then exits 0.** The delete ran before
   the embed loop, so any embedding failure — Ollama down, model not pulled —
   destroyed the project's research and reported that it had *not* rebuilt the
   index.

Plus the contract gap that lets a broken skill reach ten repos: the CLI-contract
test scanned only the dogfooded copies, never `meridian/skills/commands/`, which
is the artifact `meridian install` actually ships.

## Appetite

`s` — 1–3 days. Bounded: no new features, no redesign. If it grows into the
`cli.py` decomposition or the `--json` work, stop and split.

## Acceptance Criteria

### Spec writes

- **AC1** — `save_spec` writes via a sibling temp file and `os.replace`, so a
  reader or a competing writer never observes a partial file.
- **AC2** — A failed write leaves the original file untouched and no temp file
  behind.
- **AC3** — A new `edit_spec(path)` context manager performs the whole
  read-modify-write under `spec_lock`, making the safe path the easy one so a
  future call site cannot silently opt out.
- **AC4** — `cycle`, `link-job`, `unlink-job` and `enrich._append_sources` all go
  through it. No unlocked `load_spec` → `save_spec` pair remains.
- **AC5** — An exception inside an `edit_spec` block does not persist a partial
  edit.
- **AC6** — Concurrency tests drive the original races in-process: 40 interleaved
  edits leave the spec structurally whole, 25 rounds of paired writes lose
  neither, and 20 concurrent source appends all survive.
- **AC7** — `save_spec`'s existing skip-unchanged behaviour (B5) still holds.

### Registry

- **AC8** — Serialisation uses a real TOML writer (`tomli_w`). The hand-rolled
  `_quote` is deleted: it missed control characters, which is the whole bug.
- **AC9** — `all_projects()` distinguishes *missing* (→ `[]`) from *unreadable*
  (→ `RegistryUnreadableError`). Treating corrupt as empty is what let one byte
  delete everything.
- **AC10** — `register()` refuses to write over an unreadable registry.
- **AC11** — Every write backs up the previous file to `projects.toml.bak` and
  replaces atomically via a temp file.
- **AC12** — Every CLI consumer — `register`, `projects`, `status --all`,
  `install --all` — reports the error and exits 1 rather than tracebacking, and
  no longer suggests running `register` on the failure path.
- **AC13** — A newline, quote, backslash or tab in `--purpose` round-trips, and a
  second project survives a first one containing them.

### Index

- **AC14** — `reindex_all` embeds every chunk *before* deleting anything. A
  failure at any point leaves the existing rows untouched.
- **AC15** — Other projects' rows are untouched on failure.
- **AC16** — `meridian index` exits 1 on failure and states that the index is
  unchanged, instead of exiting 0 with a message that was factually inverted.
- **AC17** — A failed delete of existing rows is logged, not silently swallowed.
- **AC18** — `embed()` converts `httpx.HTTPStatusError` into an actionable
  `RuntimeError` naming the model and the `ollama pull` fix.

### Contract

- **AC19** — The CLI-contract test scans `meridian/skills/commands/` as well as
  `.claude/commands/meridian/`, so a shipped skill referencing a nonexistent
  subcommand or flag fails the suite.
- **AC20** — The bundled and dogfooded skill copies are compared **byte for
  byte**, making FEAT-007 AC20 and FEAT-006's claim true rather than aspirational.
  The structural check only fingerprinted headings and frontmatter keys, so a
  body rewrite passed.

## Scope

- `meridian/specs.py` — `_atomic_write`, `edit_spec`.
- `meridian/cli.py` — four locked call sites, `_tracked_projects`, index exit code.
- `meridian/enrich.py` — embed-before-delete, logged delete failure, `_append_sources`,
  `HTTPStatusError` handling.
- `meridian/registry.py` — `tomli_w`, `RegistryUnreadableError`, backup, atomic write.
- `pyproject.toml` — add `tomli-w`.
- Tests: `test_spec_concurrency.py`, `test_reindex_atomicity.py` (both new),
  plus registry, contract and skill-sync updates.

## Out of Scope

Everything else in the audit backlog. Specifically **not** here: `--json` output,
a top-level exception handler, idempotent lifecycle commands, `cli.py`
decomposition, golden runs for the ten uncovered skills, and every strategic
question about what Meridian should stop being. Those are separate bets.

## Key Risks

- **`edit_spec` holds the lock across the caller's block.** A slow body blocks
  other writers. Accepted: the blocks are dict mutations, and the alternative is
  the race this feature exists to remove.
- **A corrupt registry now blocks `register` instead of silently "fixing" it.**
  That is the intended behaviour, but it is a behaviour change: the user must
  delete or repair the file. Mitigated by the error naming the path and the
  backup.
- **`meridian index` now exits 1 where it exited 0.** Any script treating exit 0
  as "fine" will start reporting failures — correctly.
- **A new dependency does not reach an installed tool automatically.** Adding
  `tomli-w` broke the globally installed `meridian` with a
  `ModuleNotFoundError` until `uv tool install --editable . --force` was re-run.
  Worth remembering before shipping any future dependency.

## Verification

Every fix was reproduced before and after.

**Spec races.** The same 20 concurrent source appends, run both ways:

```
unlocked (the old code path):  3 of 20 sources survived
edit_spec (FEAT-013):         20 of 20 sources survived
```

**Registry.** Against a sandboxed `MERIDIAN_HOME`:

```
$ meridian register            # with a corrupt projects.toml
Error: The project registry at … could not be read (Expected '=' after a key…).
Fix or remove the file — Meridian will not overwrite it.
→ exit 1, file left byte-identical

$ meridian register --purpose $'line one\nline two'
→ exit 0, round-trips and renders in `meridian projects`
```

**Index.** Seeded a corpus, then indexed with an unpulled model:

```
Error: Ollama rejected the embedding request for model 'no-such-model-xyz' (HTTP 404).
Is the model pulled? Run: ollama pull no-such-model-xyz
  Index unchanged — existing chunks were left in place.
→ 1 chunk survived the failed index
```

That run also surfaced a previously *unverified* audit finding as real: `embed()`
leaked `httpx.HTTPStatusError` as a raw traceback, because `raise_for_status()`
sat inside a try that caught only `ConnectError` and `TimeoutException`. Fixed
here (AC18) since it is the same failure path.

595 tests pass in the locked environment (+36), ruff and mypy clean.
