---
abandoned_at: null
abandoned_reason: null
appetite: s
blocked_at: null
blocked_by: null
confidence: high
created: '2026-08-18'
cycle: null
depends_on:
- feat-009
enables: []
goal: '~'
id: feat-010
name: Propagate skills to every registered project with meridian install --all
scheduler: null
sources: []
status: in-progress
tags: []
updated: '2026-08-18'
---

## Summary

Meridian's skills live in the package and are copied into each repo's
`.claude/commands/meridian/`. When a skill changes, every repo that has a copy is
stale until someone runs `meridian install --project` there. With 10+ installs
that is 10 manual runs nobody does, so the skills drift apart silently and the
same slash command behaves differently depending on which repo you are in.

`meridian install` already handles global and single-project installs. The
missing mode is "all of them", which FEAT-009's project registry now makes
possible.

Two propagation modes, because they answer different questions:

- **`--all`** writes directly into every tracked repo. Fast, local, good when the
  repos are yours and you will commit the change yourself.
- **`--all --pr`** proposes the update as a pull request per repo. Correct when
  the repos have their own history, other contributors, or work in progress —
  which is the normal case.

The second is the important one, and its defining constraint is that it must not
disturb any repo. Each PR is built in a throwaway git worktree off
`origin/HEAD`, so no tracked repo's working tree or HEAD is touched. This project
has already been bitten by exactly that failure: two sessions sharing one
checkout silently moved each other's branch. Doing that across ten repos
unattended would be worse.

## Appetite

`s` — 1–3 days. Grew from `xs` when PR mode was added; direct copying alone was
half a day. If this starts wanting PR templates, reviewers, or auto-merge, stop.

## Acceptance Criteria

### Drift detection

- **AC1** — Skill sync compares file *contents*, not mere existence. "Already
  installed" hides the case that matters after an upgrade: a file that is present
  but stale.
- **AC2** — Each skill is reported as `new`, `outdated`, or `up to date`.
- **AC3** — An outdated file is left alone unless `--force` is given, so a repo
  that deliberately customised a skill is never silently clobbered.
- **AC4** — `--dry-run` reports what would change and writes nothing, in every
  mode.

### Direct propagation

- **AC5** — `meridian install --all` installs into every tracked project's
  `.claude/commands/meridian/`.
- **AC6** — Output is one row per project with new / updated / unchanged counts,
  plus a total.
- **AC7** — A project whose path no longer resolves is named and skipped; the run
  continues and exits 0.
- **AC8** — An unwritable project directory is reported per-project and does not
  abort the run.
- **AC9** — With no tracked projects, it prints the `meridian register` hint and
  exits 0.

### Pull-request propagation

- **AC10** — `meridian install --all --pr` opens one PR per tracked repo, branch
  `chore/meridian-skills-vX.Y.Z`, based on that repo's actual default branch —
  resolved per repo, since they are not all `main`.
- **AC11** — **No tracked repo's working tree or HEAD is modified.** The update is
  staged in a temporary worktree created from `origin/HEAD` and removed
  afterwards, including on failure.
- **AC12** — A repo whose skills already match produces no branch and no PR.
- **AC13** — Re-running when the branch already has an open PR updates that PR
  rather than failing or opening a duplicate.
- **AC14** — Repos that are not git, have no `origin`, or whose default branch
  cannot be resolved are reported and skipped — not failures.
- **AC15** — Per-repo failures (fetch, push, `gh`) are reported in the summary and
  do not abort the remaining repos.
- **AC16** — `--pr` without `--all` exits 1 with a clear message.

## Scope

- `meridian/cli.py` — `--all`, `--pr`, `--dry-run` on `install`; `_sync_skills`,
  `_install_to_all`, `_install_prs_to_all`, `_open_skill_pr`, git helpers.
- Tests, `CLAUDE.md`, `meridian help`.

## Out of Scope

- **Publishing the package.** Separate concern, separate feature — see FEAT-011.
- **PR templates, reviewers, labels, auto-merge.** The PR is a delivery
  mechanism, not a workflow.
- **Rolling back a propagated skill.** Revert the PR.
- **Syncing anything but skills** — no config, no templates, no `specs/`.
- **Removing skills deleted from the package.** Sync is additive; a skill removed
  upstream stays in the repos until someone deletes it. Deleting files in ten
  repos unattended is a bigger decision than updating them.

## Key Risks

- **Ten unattended git operations.** Mitigated by AC11 (worktree isolation),
  AC15 (per-repo failure isolation), and `--dry-run` as the default first move.
- **`--force` across all repos** silently discards local skill customisations.
  Mitigated by AC3 making drift visible first — you see what is outdated before
  choosing to overwrite.
- **`gh` not authenticated for some remote.** Surfaces as a per-repo failure row
  rather than an abort.
- **Push permissions.** A repo where the user cannot push branches reports a push
  failure. Acceptable — the alternative is silently skipping repos.

## Dependencies

- **FEAT-009** for the project registry, which is what "all" enumerates.

## Verification

`meridian install --all --pr --dry-run` against the five tracked projects:

```
  Project                 Result
  bet365-apify-scraper    would open   chore/meridian-skills-v0.2.0 → main
  gdc-mic-ai-evaluation   would open   chore/meridian-skills-v0.2.0 → main
  meridian                would open   chore/meridian-skills-v0.2.0 → main
  misc                    would open   chore/meridian-skills-v0.2.0 → main
  portfolio-management    would open   chore/meridian-skills-v0.2.0 → master
```

Per-repo default-branch resolution is doing real work here: portfolio-management
is on `master` while the rest are on `main`. A hardcoded `main` would have failed
on it.

548 tests pass, ruff and mypy clean. The safety property has a direct test —
`test_pr_mode_never_touches_working_tree` puts uncommitted work in a repo and
asserts it survives untouched.

## Open Questions

- Should `--all` warn when a target repo has a dirty working tree, the way
  FEAT-008's routing did? Leaning no: `--pr` is the answer for repos with work in
  progress, and a warning that appears ten times trains you to ignore it.
