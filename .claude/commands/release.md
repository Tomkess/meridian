---
description: Cut a Meridian release — bump, verify, tag, publish, then propagate skills.
---

Release Meridian. `$ARGUMENTS` is `patch`, `minor`, `major`, or an explicit `X.Y.Z`.
If omitted, ask which — do not guess.

This command is **repo-local on purpose**. It lives in `.claude/commands/`, not in
`meridian/skills/commands/`, so `meridian install --all` never propagates it to the
other tracked projects — releasing Meridian is meaningless in `portfolio-management`.

## Steps

1. Confirm the bump level with the user if `$ARGUMENTS` is empty.

2. Preview first, always:
   ```
   ./scripts/release.sh <bump> --dry-run
   ```
   It refuses to proceed unless you are on `main`, the tree is clean, `main` matches
   `origin/main`, and the tag does not already exist. Report any refusal verbatim and
   stop — those guards are the point, not an obstacle to route around.

3. Run it for real:
   ```
   ./scripts/release.sh <bump>
   ```
   The script bumps the version with `uv version` (the single source is `version` in
   `pyproject.toml`; `meridian/__init__.py` reads it back from installed metadata),
   runs pytest + ruff + mypy through `uv run --locked`, prepends a CHANGELOG section
   generated from commits since the last tag, commits, tags, pushes, and creates the
   GitHub release.

4. **Edit the generated CHANGELOG section before it ships.** Raw commit subjects are
   a starting point, not release notes. Group them, drop the noise (`chore: close
   FEAT-00N`), and lead with what a reader would care about. If the script already
   committed, amend:
   ```
   git commit --amend --no-edit CHANGELOG.md && git push --force-with-lease
   ```

5. Propagate the skills to every tracked project:
   ```
   meridian install --all --pr --dry-run
   meridian install --all --pr
   ```
   Report the per-repo results. Repos that are not git, have no `origin`, or already
   match are skipped — that is expected, not failure.

6. Summarise: the version, the release URL, and which repos got skill PRs.

## Notes

- **No GitHub Actions minutes are used.** `gh release create` is a REST call. This
  repo is private with Actions billing unavailable, so CI cannot run — the script's
  local pytest/ruff/mypy gate is the only verification that exists. Never skip it.
- The gate runs through `uv run --locked`. If preflight complains that `uv.lock` is
  out of date, run `uv lock` and commit it — do not bypass the check, because a stale
  lock means the gate is not testing what ships.
- The local install is editable (`uv tool install --editable`), so this machine runs
  the new code the moment `main` moves. Other machines use
  `uv tool install git+https://github.com/Tomkess/meridian@vX.Y.Z`.
- Meridian is **not** published to PyPI, and the name is taken there by an unrelated
  project. Do not add a publish step without renaming the distribution first.
