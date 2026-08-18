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
- feat-010
enables: []
goal: '~'
id: feat-011
name: 'Release flow: single-sourced version, scripts/release.sh, changelog, tag and
  GitHub release'
scheduler: null
sources: []
status: in-progress
tags: []
updated: '2026-08-18'
---

## Summary

Meridian had no release process. Investigating turned up four separate problems:

1. **The version lived in two places** — `pyproject.toml` and
   `meridian/__init__.py` — guaranteed to drift, and two tests hardcoded the
   literal `"0.2.0"`, so every bump would also be a test edit.
2. **No tags.** v0.2.0 shipped untagged; there was no way to install a specific
   version, and no anchor for changelog generation.
3. **The README was actively wrong.** It said `pip install meridian`, but that
   name on PyPI belongs to an unrelated project (currently at 0.4.0). Anyone
   following the README installed a stranger's package.
4. **No CHANGELOG** and no publish step of any kind.

Underneath all of it: CI cannot run. The repo is private and its GitHub Actions
quota is unavailable ("recent account payments have failed"), so every push since
has failed in 1–2 seconds. Any release process that assumes CI verifies the build
would be verifying nothing. This one runs the gate locally and consumes **zero**
Actions minutes — `gh release create` is a REST call, not a workflow.

## Appetite

`xs` — under a day. A script, a skill, and a pyproject change.

## Acceptance Criteria

### Version

- **AC1** — The version is defined once, in `meridian/__init__.py`.
  `pyproject.toml` declares `dynamic = ["version"]` and reads it via
  `[tool.setuptools.dynamic]`.
- **AC2** — No test asserts a version literal; they read `meridian.__version__`,
  so a bump never requires editing tests.

### Release script

- **AC3** — `scripts/release.sh patch|minor|major|X.Y.Z` computes the next
  version, or accepts an explicit one.
- **AC4** — Preflight refuses unless: on `main`, working tree clean, `main` in
  sync with `origin/main`, and the target tag does not already exist. Each
  refusal names the specific reason.
- **AC5** — The quality gate is pytest + ruff + mypy, run locally. Since CI
  cannot run, this is the only verification that exists and is never skipped.
- **AC6** — `--dry-run` prints every action without mutating anything, including
  the preflight refusals.
- **AC7** — A CHANGELOG section is generated from commits since the last tag and
  prepended under the `# Changelog` heading.
- **AC8** — It commits, creates an annotated tag `vX.Y.Z`, pushes both, and runs
  `gh release create --generate-notes`.
- **AC9** — Zero GitHub Actions minutes are consumed by the release itself.

### Skill

- **AC10** — `/release` drives the script, and is **repo-local**
  (`.claude/commands/release.md`, not `meridian/skills/commands/`) so
  `meridian install --all` never propagates it — releasing Meridian is
  meaningless in another project.
- **AC11** — The skill instructs the agent to edit the generated changelog before
  it ships: raw commit subjects are a starting point, not release notes.
- **AC12** — The skill ends by propagating skills via
  `meridian install --all --pr` (FEAT-010).

### Documentation

- **AC13** — The README installs from git, with the PyPI name collision stated
  outright rather than left as a trap.
- **AC14** — `CLAUDE.md` documents the release flow, the single-source version,
  and the no-Actions-minutes property.

## Scope

- `pyproject.toml` — dynamic version.
- `meridian/__init__.py` — the single source.
- `scripts/release.sh`, `.claude/commands/release.md`, `CHANGELOG.md`.
- `tests/test_cli.py` — version assertions read the package.
- `README.md`, `CLAUDE.md`.

## Out of Scope

- **Publishing to PyPI.** The name is taken; doing it would mean renaming the
  distribution (`meridian-cli` or similar). That is a naming decision, not a
  packaging task, and belongs in its own feature if ever wanted.
- **Restoring CI.** Fixing billing, or making the repo public, is the user's
  call — and the specs reference client work, so public is not obviously safe.
- **A pre-push hook** enforcing the test suite. Proposed and not built; the
  release script already gates the moment that matters.
- **Signing tags or releases.**
- **Removing the dead `test.yml` workflow.** It produces a red X on every PR that
  means nothing, but deleting CI is a decision to make deliberately, not as a
  side effect of adding a release script.

## Key Risks

- **The local gate is the only gate.** If someone runs the script with a broken
  environment, a release ships unverified. Mitigated by the script running the
  full suite itself rather than trusting the operator to have run it.
- **Generated changelogs are noise by default** — commit subjects include
  `chore: close FEAT-00N` entries nobody wants in release notes. Mitigated by
  AC11 making the edit an explicit step rather than an optional polish.
- **`--generate-notes` duplicates the CHANGELOG.** Accepted: GitHub's notes are
  commit-derived and the CHANGELOG is curated; they serve different readers.

## Dependencies

- **FEAT-010** for `meridian install --all --pr`, the propagation step the
  release flow ends with.

## Verification

`./scripts/release.sh patch --dry-run` from a feature branch:

```
==> Releasing 0.2.0 → 0.2.1
==> Preflight
error: on branch 'feat-010/install-all' — release from main
```

Preflight works: it refused rather than cutting a release from a feature branch.
Version computation (0.2.0 → 0.2.1) ran before the refusal, so the bump logic is
exercised too.

Not yet run end-to-end — the first real release will be the first full execution,
deliberately, since a test run would create a real tag and a real GitHub release.

551 tests pass, ruff and mypy clean.
