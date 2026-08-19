---
abandoned_at: null
abandoned_reason: null
appetite: xs
blocked_at: null
blocked_by: null
confidence: high
created: '2026-08-19'
cycle: null
depends_on:
- feat-010
- feat-014
enables: []
goal: '~'
id: feat-016
name: 'meridian install --prune: remove skills that no longer ship with Meridian'
status: in-production
tags: []
updated: '2026-08-19'
---

## Summary

Skill sync was additive with no way to opt out, so a skill deleted from the
package lingered in every repo forever. Deleting one upstream changed nothing
downstream.

Found by checking work rather than trusting it. FEAT-014 cut four skills, a full
`meridian install --all --pr` propagation ran, and inspecting the resulting PR
showed 11 files added or updated and **zero deletions**. FEAT-010's own spec had
said this outright — "Sync is additive; a skill removed upstream stays in the
repos until someone deletes it" — and I had then told the user that `--force`
would remove them. It does not.

`--prune` removes files in `.claude/commands/meridian/` that no longer ship with
Meridian. Opt-in, because deleting files across ten repos is a bigger decision
than updating them — which is exactly what FEAT-010 reasoned when it scoped this
out. Making it explicit was right; leaving it *impossible* was not.

## Appetite

`xs` — one flag threaded through three call paths, plus tests.

## Acceptance Criteria

- **AC1** — `--prune` deletes `*.md` files in the destination that are not in
  the bundled skill set.
- **AC2** — Default behaviour is unchanged: without `--prune`, sync is additive
  and a stale skill survives. A test asserts this, so the documented default
  cannot drift by accident.
- **AC3** — Pruning touches only `.claude/commands/meridian/`, never a
  project's own `.claude/commands/` entries. Tested directly.
- **AC4** — `--dry-run` composes with `--prune` and deletes nothing.
- **AC5** — Removals are reported per skill in single-project mode and counted
  in the `--all` table.
- **AC6** — In `--pr` mode a repo whose only change is removals still opens a
  PR, rather than reporting `current` and doing nothing.
- **AC7** — The PR body and commit message list what was removed.
- **AC8** — `SkillSync` gains `removed`, so callers report what happened rather
  than inferring it.

## Scope

`meridian/cli.py` (`SkillSync`, `_sync_skills`, `_install_to_all`,
`_install_prs_to_all`, `_open_skill_pr`, the `install` command),
`tests/test_install_all.py`, `CLAUDE.md`.

## Out of Scope

- **Pruning by default.** The blast radius is other people's repos.
- **Pruning anything but skills.** Config, templates and specs are untouched.
- **Reconciling a repo that customised a skill.** `--force` already governs
  overwrites; prune only removes files that no longer exist upstream.

## Key Risks

- **Deleting files in repos you are not looking at.** Mitigated by opt-in, by
  `--dry-run`, by scoping strictly to the meridian command directory, and by
  `--pr` mode proposing rather than applying.
- **A repo that deliberately kept a retired skill loses it.** Accepted: the
  flag is explicit, and the PR shows the deletion before it merges.

## Verification

Propagated across the five tracked projects with `--prune`, then inspected the
resulting PRs. In `gdc-mic-ai-evaluation`:

```
0+  43-  .claude/commands/meridian/challenge.md
0+  57-  .claude/commands/meridian/connect-dots.md
96+  0-  .claude/commands/meridian/enrich.md
0+  54-  .claude/commands/meridian/plan.md
0+  49-  .claude/commands/meridian/roadmap.md
```

The four retired skills are deleted and the new one added, which is exactly the
change the previous propagation silently failed to make.

Checking the other repos corrected a second wrong assumption: only
`gdc-mic-ai-evaluation` had committed skills at all. `bet365-apify-scraper`,
`Misc` and `portfolio_management` had none — their PRs install Meridian skills
for the first time, and there was nothing there to prune.

The global install at `~/.claude/commands/meridian/` still held the old 14,
including all four retired skills. `meridian install --force --prune` brought it
to the correct 11.

573 tests pass in the locked environment (+5), ruff and mypy clean.
