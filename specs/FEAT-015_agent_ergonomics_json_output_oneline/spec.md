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
id: feat-015
name: 'Agent ergonomics: --json output, one-line errors, idempotent lifecycle commands'
status: in-progress
tags: []
updated: '2026-08-19'
---

## Summary

Meridian is driven by an agent far more often than by a human, and three
properties an automation loop needs were missing.

**No structured output.** Skills shell out to the CLI and then parse Rich
box-drawing out of the agent's context window. They get prose where they want
data, and exit codes where they want typed results. Every competitor surveyed
in the audit ships an MCP server; `--json` is the cheapest way to stop being
conspicuously not, and a prerequisite for one later.

**Tracebacks on ordinary conditions.** Four everyday situations — a corrupt
`.meridian.toml`, an unreadable spec, a dead URL, an unpulled model — surfaced
as roughly 40 lines of Rich traceback. For an agent that is both harder to
recover from and vastly more expensive to read than one line naming the problem.

**Lifecycle commands that cannot be retried.** Every self-transition exited 1.
Combined with the verified mid-command registry crash from the audit, a retrying
agent was stuck permanently: the first attempt half-succeeded, and the retry
hard-failed with `Cannot transition 'done' → 'done'`.

## Appetite

`s` — three contained changes plus tests. Not an MCP server; that is a separate
bet this makes possible.

## Acceptance Criteria

### Structured output

- **AC1** — `status`, `status --all`, `projects`, `guide` and `search` accept
  `--json`.
- **AC2** — Output is compact JSON on stdout with no Rich decoration, and exits 0.
- **AC3** — `status --json` carries per-feature `id`, `name`, `status`,
  `appetite`, `confidence`, `cycle`, `goal`, `updated`, `depends_on`, `enables`,
  `blocked_by`, and task progress as `{checked, total}` or null.
- **AC4** — `status --all --json` carries per-project counts by lifecycle state,
  plus `exists` so a caller can tell a missing repo from an empty one.
- **AC5** — `guide --json` exposes `next_action`, which is the field an agent
  would act on.
- **AC6** — `search --json` carries `project`, `feat_id`, `label`,
  `source_name`, `chunk_idx`, `score` and `text` per hit.
- **AC7** — A test asserts no box-drawing characters appear in JSON output, and
  another asserts `--json` is discoverable in each command's `--help`.

### Errors

- **AC8** — A single top-level handler renders unexpected exceptions as one-line
  errors. The console entry point becomes `meridian.cli:main` rather than the
  Typer app itself, since there is nowhere else to wrap it.
- **AC9** — `typer.Exit`, `typer.Abort` and `SystemExit` pass through untouched,
  so existing handled paths keep their exact behaviour and exit codes.
- **AC10** — `KeyboardInterrupt` prints `Interrupted.` and exits 130.
- **AC11** — `MERIDIAN_DEBUG=1` restores the full traceback, and the error
  message says so.
- **AC12** — `_friendly()` names the file or URL for TOML, permission, missing
  file, OS and httpx errors, rather than echoing a bare exception repr.

### Idempotency

- **AC13** — `transition_spec` treats `current == new_status` as success: any
  `extra` fields are still applied and saved.
- **AC14** — The returned data carries `_unchanged` so callers can report
  accurately instead of implying work was done.
- **AC15** — `close` prints `✓ FEAT-001 already draft` and exits 0.
- **AC16** — Illegal transitions still fail with the same message. Idempotency
  must not become "any transition is allowed", and there is a test for that.
- **AC17** — `revive` on a feature already in `idea` is a no-op success;
  `revive` on a `draft` still fails.

## Scope

- `meridian/cli.py` — `_emit_json`, `--json` on five commands, `main()`,
  `_friendly()`, `_unchanged` reporting in `close` and `revive`.
- `meridian/specs.py` — idempotent `transition_spec`.
- `pyproject.toml` — entry point moves to `meridian.cli:main`.
- `tests/test_agent_ergonomics.py` (new), `tests/test_cli.py`, `CLAUDE.md`.

## Out of Scope

- **An MCP server.** This is the groundwork, not the thing.
- **`--json` on the remaining commands.** The five here are the ones skills
  actually call; the rest are write commands whose output is a single line.
- **Typed exit codes per failure class.** One line plus exit 1 is the
  improvement; a taxonomy is speculative until something needs it.
- **The remaining audit backlog** — `cli.py` decomposition, golden runs for the
  uncovered skills, real drift detection.

## Key Risks

- **The entry point changed.** An installed tool keeps running the old
  `cli:app` until reinstalled. Harmless — the old path simply lacks the new
  handler — but it means `uv tool install --editable . --force` is needed to see
  the change.
- **Swallowing a real bug.** A blanket handler can hide a genuine defect behind
  a tidy message. Mitigated by `MERIDIAN_DEBUG=1` and by letting Typer's own
  exits through untouched.
- **Idempotency masking a no-op.** `close` on an already-`done` feature now
  exits 0, so a script cannot infer "a transition happened" from the exit code
  alone. Deliberate: the output distinguishes the two, and the alternative
  breaks retries.

## Verification

Output sizes, measured on this repo's own dashboard:

```
table              5,912 bytes
JSON (indent=2)    5,876 bytes
JSON (compact)     4,247 bytes
```

Pretty-printed JSON was *no smaller than the table* — the first implementation
used `indent=2` and would have delivered essentially none of the intended
saving. Switched to compact, which is a 28% reduction and the form an agent
actually wants.

Error handling, live:

```
$ meridian status              # with a corrupt .meridian.toml
Error: .meridian.toml is not valid TOML — Expected '=' after a key in a key/value pair (at line 1, column 5)
  Set MERIDIAN_DEBUG=1 for the full traceback.

$ MERIDIAN_DEBUG=1 meridian status
╭──── Traceback (most recent call last) ────╮
```

Idempotency surfaced a real semantic question: `revive` on a feature already in
`idea` used to exit 1. It is now a no-op success, since the target state holds —
but `revive` on a `draft` still fails, and both are tested, because the useful
half of the old behaviour was rejecting backwards moves.

566 tests pass in the locked environment (+15), ruff and mypy clean.
