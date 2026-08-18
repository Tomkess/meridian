---
abandoned_at: null
abandoned_reason: null
appetite: xs
blocked_at: null
blocked_by: null
confidence: high
created: '2026-08-18'
cycle: null
depends_on:
- feat-011
enables: []
goal: '~'
id: feat-012
name: 'Adopt uv project workflow: locked dev env, dependency-groups, uv version bump'
scheduler: null
sources: []
status: in-production
tags: []
updated: '2026-08-18'
---

## Summary

Meridian was already half a uv project — `uv.lock` has been tracked since
FEAT-005 — but nothing actually used it. Three gaps, one of them a hole in the
release gate FEAT-011 had just shipped.

**The quality gate ran on the wrong interpreter.** `scripts/release.sh` invoked
`python3 -m pytest` directly, which resolved to the ambient
`/usr/local/bin/python3` (3.12.0), not the project's locked `.venv`
(3.13.7). CI cannot run on this repo, so that gate is the *only* verification
that exists — and it was verifying against whatever happened to be first on
`PATH` rather than the pinned dependency set. Switching to `uv run --locked`
immediately surfaced a real mypy error at `cli.py:394` that the ambient tooling
had been silently passing.

**`uv version` was blocked by FEAT-011's own design.** That feature made the
version dynamic (`pyproject.toml` reading `meridian.__version__`) to kill the
duplication, which works but means:

```
$ uv version
error: We cannot get or set dynamic project versions in: pyproject.toml
```

The fix is to invert it rather than choose between them: keep `version` static in
`pyproject.toml` — the one place `uv version --bump` can edit — and have
`meridian/__init__.py` read it back from installed metadata. Still one source of
truth, and the hand-rolled semver arithmetic in `release.sh` deletes itself.

**Dev tooling sat in `optional-dependencies`.** That publishes it as an installable
extra of the package, which it is not. PEP 735 `[dependency-groups]` is what uv
wants, is installed by `uv sync`, and is excluded from the built wheel.

## Appetite

`xs` — under a day. Config, a script rewrite, and guard tests.

## Acceptance Criteria

### Version

- **AC1** — `version` is static in `pyproject.toml` and is the single source.
- **AC2** — `meridian.__version__` reads it via `importlib.metadata`, falling back
  to `0.0.0+dev` when running from a source tree that was never installed.
- **AC3** — `uv version` and `uv version --bump patch` both work.
- **AC4** — `scripts/release.sh` delegates version arithmetic to `uv version
  --bump`, with no second semver implementation to keep correct.
- **AC5** — A test asserts the version is not dynamic and that
  `meridian/__init__.py` contains no release literal — the two states that break
  `uv version` or reintroduce drift.

### Locked environment

- **AC6** — Dev tooling lives in `[dependency-groups] dev`; `rerank` stays a real
  extra, since it is a user-facing install option.
- **AC7** — `scripts/release.sh` runs pytest, ruff, and mypy through
  `uv run --locked`.
- **AC8** — Release preflight fails on a stale `uv.lock`: testing against a lock
  that does not match `pyproject.toml` means not testing what ships.
- **AC9** — A test asserts the release script uses the locked environment, so the
  hole cannot silently reopen.
- **AC10** — Every reference to the removed `.[dev]` extra is updated to
  `uv sync` — README, test error messages, and the CI workflow.
- **AC11** — `.github/workflows/test.yml` runs its steps through `uv run
  --locked`. It cannot execute today (billing), but leaving it referencing a
  non-existent extra and bare tool names would make it wrong whenever it comes
  back.

## Scope

- `pyproject.toml` — static version, `[dependency-groups]`, drop the
  `[tool.setuptools.dynamic]` block.
- `meridian/__init__.py` — metadata-based version.
- `meridian/cli.py` — the typing fix the locked mypy found.
- `scripts/release.sh`, `.claude/commands/release.md`.
- `tests/test_packaging.py` (new), plus `.[dev]` references in four test files.
- `README.md`, `CLAUDE.md`, `.github/workflows/test.yml`, `uv.lock`.

## Out of Scope

- **Switching the build backend** to `uv_build`. Gains little here and would need
  the packaging path re-verified; setuptools works.
- **Publishing to PyPI.** Still blocked on the name collision — see FEAT-011.
- **Restoring CI.** Unchanged: billing or visibility, both the user's call.
- **`uv tool install` for end users.** Unaffected — project management and tool
  installation are separate concerns in uv.

## Key Risks

- **`importlib.metadata` needs the package installed.** Running from a bare source
  checkout yields `0.0.0+dev` rather than the real version. Acceptable: the
  editable install and every real installation both resolve correctly, and the
  sentinel is obviously a sentinel.
- **A stale lock now blocks releases.** Intended — it is the failure this feature
  exists to prevent — but it means `uv lock` must be committed with any
  dependency change. Documented in `CLAUDE.md` and the `/release` skill.
- **The locked toolchain is stricter than the ambient one.** It already found one
  latent mypy error; more may surface. That is the feature working.

## Dependencies

- **FEAT-011** for the release script this modifies.

## Verification

Interpreter drift, before the change:

```
release.sh ran:   /usr/local/bin/python3    → Python 3.12.0  (ambient)
uv run uses:      .venv/bin/python3         → Python 3.13.7  (locked)
```

`uv lock --check` reported the lock stale against `pyproject.toml`.

Running mypy in the locked environment found an error the ambient run had been
passing for the whole session:

```
meridian/cli.py:394: error: Argument 1 to "add_row" of "Table" has incompatible
type "*list[object]"; expected "ConsoleRenderable | RichCast | str | None"
```

Fixed by typing the row list as `list[str | Text]`.

After: `uv version` reports `meridian 0.2.0`, `uv version --bump patch --dry-run`
reports `0.2.0 => 0.2.1`, and `./scripts/release.sh patch --dry-run` resolves the
next version through uv and still refuses to release from a feature branch.

559 tests pass in the locked environment (+8 packaging guards), ruff and mypy
clean.
