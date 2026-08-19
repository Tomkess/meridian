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
id: feat-014
name: 'Cut surface: remove Databricks, four low-value skills, and the hand-written
  manual'
status: in-progress
tags: []
updated: '2026-08-19'
---

## Summary

The audit's §5 named six dead ends. This takes the three the owner confirmed,
and leaves the rest alone.

**Databricks (295 lines).** Never used. It was vendor coupling inside a
general-purpose tool — a `[databricks]` section in every generated
`.meridian.toml`, a `scheduler` key in every spec, a job-status column in
`status`, two commands, and a documented path to committing a PAT into a
git-tracked file. No competitor has pipeline integration, so it was either the
wedge or dead weight. It was never the wedge.

**Four skills** — `/plan`, `/challenge`, `/roadmap`, `/connect-dots`. None had
golden coverage. `/connect-dots` issued an unbounded read plus an unbounded CLI
loop with no cap and no empty-corpus branch, which fails by roughly FEAT-050.
Claude Code's plan mode plus a `CLAUDE.md` section reproduces what they did.
Because skills propagate, these were also being pushed into five other repos.

**The 309-line hand-written manual** — 16% of `cli.py`. It had already drifted:
`link-job` and `unlink-job` were registered commands that appeared nowhere in
it. Replaced by a listing derived from `app.registered_commands`, so that class
of drift is now impossible rather than merely fixed.

Deliberately **not** cut, against the audit's recommendation: the lifecycle
commands. §9 argued Linear's free tier replaces `status`/`close`/`new`/`cycle`.
It does not, because Linear cannot put the spec on the branch beside the diff.
These commands shipped 13 features in a single day of use; they are load-bearing.

## Appetite

`s` — deletion plus the reference cleanup that deletion always drags with it.

## Acceptance Criteria

### Databricks

- **AC1** — `meridian/databricks.py` and `tests/test_databricks.py` are deleted.
- **AC2** — `link-job` and `unlink-job` are removed from the CLI.
- **AC3** — `MeridianConfig` drops `databricks_host`, `databricks_token_env`,
  and `databricks_status_timeout`.
- **AC4** — `meridian init` no longer writes a `[databricks]` section, and a
  test asserts its absence rather than its presence.
- **AC5** — `status` drops the job-fetch block, the `Job` column, and the
  `ThreadPoolExecutor` that existed only to serve them.
- **AC6** — The spec template drops the `scheduler` key. Existing specs keep
  theirs harmlessly; nothing reads it.
- **AC7** — No file under `meridian/` mentions Databricks, enforced by a test
  that greps the package — including comments, which is where the last two
  references hid.

### Skills

- **AC8** — `plan.md`, `challenge.md`, `roadmap.md` and `connect-dots.md` are
  removed from **both** `meridian/skills/commands/` and
  `.claude/commands/meridian/`, leaving 11 skills.
- **AC9** — `SKILLS.md` — the template shipped into every project — no longer
  references them.
- **AC10** — `CLAUDE.md` and `README.md` drop them from every table, diagram and
  walkthrough, with the walkthrough renumbered rather than left with a gap.
- **AC11** — A test asserts they stay deleted in both locations.

### Manual

- **AC12** — `meridian help` lists commands derived from `app.registered_commands`
  rather than a hand-written table.
- **AC13** — Listing order is registration order, which follows the workflow —
  and is documented as deliberate, since sorting by `name` would silently do
  nothing (`@app.command()` leaves it `None`).
- **AC14** — The box-drawing helpers that existed only for the manual
  (`_vlen`, `_box_top`, `_box_row`, `_box_bot`, `_connector`) are deleted, along
  with the `unicodedata` import they alone required.

## Scope

`meridian/cli.py`, `meridian/config.py`, `meridian/specs.py`,
`meridian/skills/templates/SKILLS.md`, `tests/conftest.py`, `tests/test_cli.py`,
`tests/test_packaging.py`, `CLAUDE.md`, `README.md`, plus the deleted files.

## Out of Scope

- **The lifecycle commands.** See Summary — kept deliberately.
- **The remaining audit dead ends**: the golden-set infrastructure, `CYCLES.md`,
  and the `/decision` ambition. Not confirmed, not touched.
- **Tier 2 ergonomics** (`--json`, top-level error handler, idempotent
  lifecycle). Next feature.
- **Re-homing Databricks behind an optional extra.** The owner's call was to cut
  it, not to relocate it. It remains in git history if it is ever wanted.

## Key Risks

- **Deleting a skill deletes it from five repos on the next
  `meridian install --all --force`.** That is the intent, but it is a fleet-wide
  change from a local deletion. `--force` is required, so it cannot happen by
  accident.
- **`meridian help` output changed shape.** Anyone parsing it — unlikely, but the
  agent-facing surface is exactly where this matters — sees a different table.
- **Removing config fields is breaking for anyone with a `[databricks]` block.**
  In practice harmless: `load_config` ignores unknown sections, so an existing
  `.meridian.toml` keeps working.

## Verification

```
before: 4,355 lines across 12 modules   cli.py 1,975
after:  3,753 lines across 11 modules   cli.py 1,567
```

`meridian help` now renders from the registered commands. That surfaced the
ordering detail in AC13: the first implementation called `sorted(...,
key=lambda c: c.name or "")`, which is a no-op because Typer leaves `name`
unset for `@app.command()` — the output was registration order by accident.
Made deliberate.

The grep test in AC7 caught two Databricks references that the module deletion
missed: a comment in the `MERIDIAN_DEBUG` block and a section banner left behind
by the command removal.

551 tests pass in the locked environment, ruff and mypy clean.
