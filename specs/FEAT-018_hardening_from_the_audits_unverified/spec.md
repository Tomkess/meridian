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
id: feat-018
name: 'Hardening from the audit''s unverified findings: validated feature IDs, safe
  registry cells, binary rejection, MERIDIAN_HOME redirect'
status: in-production
tags: []
updated: '2026-08-19'
---

## Summary

The audit produced 29 findings that a single auditor reported and nobody
independently reproduced. They were labelled as leads throughout, and left
alone. This works the ones that are still live and cheap.

A third of the list is already gone. Databricks findings died with FEAT-014,
skill findings for `/plan` and `/connect-dots` died with them, and FEAT-013
and FEAT-015 already fixed the `HTTPStatusError` leak and the idempotency gap.
What remains is a short list of genuine sharp edges.

The most consequential is quiet: **`MERIDIAN_HOME` did not redirect the vector
store.** `init` hardcoded `~/.meridian/lancedb` and `load_config` never consulted
`meridian_home()`, so any test or sandbox that followed the documented safety
instruction still read and wrote the developer's real LanceDB. That is the most
plausible mechanism behind the destruction of the global store on 2026-08-18,
and it means the isolation fixture added in FEAT-008 was only ever half true.

## Appetite

`s` — six contained fixes and their tests. Not a refactor.

## Acceptance Criteria

### Feature-ID resolution

- **AC1** — One `find_spec()` in `specs.py` replaces the near-identical globs in
  `cli._find_spec` and `enrich._find_spec_path`.
- **AC2** — A feature ID must match `^FEAT-\d{3,}$`. A glob metacharacter is
  rejected rather than interpolated — reported repro:
  `meridian close 'feat-*' --status draft` transitioned FEAT-002, not FEAT-001.
- **AC3** — Candidates are sorted, and more than one match raises
  `AmbiguousFeatureError` instead of silently picking whichever the filesystem
  returned first, which varied between machines.
- **AC4** — An unknown ID returns `None` — not found is not an error at this
  layer; the caller decides.

### Global home

- **AC5** — `lancedb_path` defaults to `meridian_home() / "lancedb"`, so
  `MERIDIAN_HOME` redirects the vector store as well as the registry.
- **AC6** — An explicit `lancedb_path` in `.meridian.toml` still wins.

### Corpus integrity

- **AC7** — `extract_text` refuses a file that does not look like text — no NUL
  bytes, over 85% printable in the first 4 KB. `enrich` previously reported
  "1 chunks embedded" for random bytes and left retrievable mojibake in the
  corpus, trivially triggered by a `.docx` or a mistyped path.
- **AC8** — Genuine UTF-8 text, including accents, is unaffected; an empty file
  is still valid.
- **AC9** — A failed LanceDB delete in `upsert_chunks` is logged rather than
  swallowed. A silent failure there leaves duplicate rows, which quietly
  degrades every later search.

### Registry integrity

- **AC10** — Table cells escape `|` and collapse newlines, so a feature name
  containing either cannot shift every column of `REGISTRY.md` — a file the AI
  reads as a source of truth.

### Lifecycle

- **AC11** — `done` and `in-production` can transition directly to `abandoned`.
  Retiring a shipped feature previously required walking it backwards through
  `in-progress`, which polluted the active-work counters on the dashboard.

## Scope

`meridian/specs.py` (`find_spec`, `AmbiguousFeatureError`, `_cell`,
`VALID_TRANSITIONS`), `meridian/config.py`, `meridian/cli.py`,
`meridian/enrich.py` (`_find_spec_path`, `extract_text`, `_looks_like_text`,
`upsert_chunks`), `tests/test_drift.py`.

## Out of Scope

Findings deliberately left, with reasons:

- **`REGISTRY.md` merge conflicts.** The fix is to stop committing a generated
  file, which changes how every tracked repo works. That is the user's call.
- **`init --force` overwriting `VISION.md`.** Real, but `--force` is an explicit
  destructive flag and the behaviour is at least honest.
- **`transition --from-merge` no-opping on an `in-progress` feature.** Now
  arguably obsolete: FEAT-015 made transitions idempotent, and the right fix
  depends on whether merging should imply `done`, which is a workflow decision.
- **The AppleScript path interpolation in `capture.py`.** Latent, not reachable:
  it needs a controlled `$TMPDIR` plus a pre-created directory.
- **Duplicate cycle-capacity computation.** Cosmetic divergence, no data at risk.
- **Skill-quality findings** (`/research` persisting nothing, `brief.md`'s
  self-reported word limit). Those belong with the golden-run work, not here.

## Key Risks

- **The ID validator rejects input that used to work.** Deliberate — anything it
  rejects was never a valid feature ID — but a script passing a lowercase or
  padded ID now gets a clear error instead of silent wrong-feature behaviour.
- **The text sniff could reject a legitimate file.** Tuned permissively: bytes
  ≥ 128 count as printable so UTF-8 prose passes, and only NUL bytes or heavy
  control-character density trigger a refusal.
- **Changing the default `lancedb_path` moves the store** for anyone who set
  `MERIDIAN_HOME` and relied on the old behaviour. Nobody can have: the old
  behaviour was that the setting did nothing.

## Verification

`MERIDIAN_HOME` redirect, which is the fix that matters most:

```
$ MERIDIAN_HOME=/tmp/hcheck-home meridian ... → lancedb_path=/tmp/hcheck-home/lancedb
```

Before this, that returned the developer's real `~/.meridian/lancedb` regardless
of the environment variable.

604 tests pass in the locked environment (+9), ruff and mypy clean.
