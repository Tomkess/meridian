---
abandoned_at: null
abandoned_reason: null
appetite: s
blocked_at: null
blocked_by: null
confidence: high
created: '2026-08-20'
cycle: 2026-Q3
depends_on: []
enables: []
goal: goal-01
id: feat-027
name: 'Drift detection that survives the merge'
sources: []
status: done
tags: []
updated: '2026-08-20'
---

## Summary

`meridian drift` compared a feature's acceptance criteria against **its branch's
diff against main**. Once the branch is merged that diff is empty, so the report
was:

> ⚠ No changes against main — nothing to compare the criteria to.

`meridian close --status done` runs drift automatically, and by the time anyone
runs `close --status done` the branch is usually already merged. So the one
moment the check fires was the one moment it could say nothing — and it said it
in a way that reads like a clean bill of health rather than a failure to look.

Found by using it: all four of FEAT-023–026 reported "nothing to compare"
immediately after merging, and the report looked fine.

## Appetite

`s` — a second way of finding the diff, and the precision fix that second way
turns out to require.

## Design decisions

**Branch mode stays primary; history mode is the fallback.** An unmerged branch
is the sharper signal — it is exactly the feature's work and nothing else. The
fallback only runs when there is no branch diff to read, or the checked-out
branch is not this feature's.

**Three signals find a merged feature's commits**, unioned: a *merge commit*
naming the feature (Meridian's `Merge FEAT-NNN: …` convention), an ordinary
*commit whose message names it* (what a squash merge leaves), and any commit
that *touched the feature's spec directory* (catches work whose message forgot
the ID). Double-counting is harmless — the result is a text haystack.

**A merge is diffed against its first parent**, so the result is what the merge
brought onto the mainline, not the unrelated mainline commits the branch had not
yet seen.

**The exclusion had to widen from one spec to all specs.** This is the
non-obvious part. A spec states its own acceptance criteria, so a spec in the
haystack lets every AC match its own text — the original code excluded the
feature under assessment for exactly this reason. That was sufficient while a
diff covered one feature. It is not sufficient in history mode: one commit that
shapes or closes four features drags all four specs in, and an AC then matches
its own words quoted in a *sibling's* spec. Verified against this repo before
fixing: FEAT-024's haystack contained FEAT-023's, FEAT-025's and FEAT-026's spec
text.

Only `specs/FEAT-*` is excluded, not `specs/` wholesale — `REGISTRY.md`,
`goals/` and `CYCLES.md` are legitimate things for an AC to name.

**An empty search reports as empty, loudly.** The failure mode being fixed is a
negative result that reads as a pass, so the new message names *both* searches
that came back empty and says what the convention is.

## Acceptance Criteria

- **AC1** — `assess()` falls back to the feature's commits in `base` when the
  branch diff is empty, and reports `mode` as `history`.
- **AC2** — `feature_commits()` finds a merged feature by merge commit, by a
  commit message naming the feature, and by commits touching its spec directory.
- **AC3** — A merge commit is diffed against its **first** parent, so unrelated
  mainline work is not counted as the feature's.
- **AC4** — Branch mode still wins when the feature's branch holds the work:
  history mode is a fallback, not a replacement.
- **AC5** — A merged feature can still be **caught drifting** — an AC naming
  something never written is still reported after the merge.
- **AC6** — `SPEC_EXCLUDES` keeps every `specs/FEAT-*` directory out of the
  haystack, so a sibling spec cannot satisfy an AC.
- **AC7** — `specs/REGISTRY.md`, `specs/goals/` and `specs/CYCLES.md` stay
  visible — the exclusion is `specs/FEAT-*`, not `specs/`.
- **AC8** — When neither a branch diff nor a matching commit exists, the report
  says so explicitly and names the convention, rather than printing something a
  reader takes for a pass.
- **AC9** — `close --status done` reports drift after the merge, from `main`.

## Scope

`meridian/drift.py`, `_render_drift` in `meridian/cli.py`, `tests/test_drift.py`.

## Out of Scope

- **Rewriting the lexical heuristic.** Still a heuristic, still ranks rather
  than judges. This changes *where it looks*, not *how it matches*.
- **Cherry-picked or rebased-with-rewritten-message work.** If a commit neither
  names the feature nor touches its spec, nothing can find it. AC8 makes that
  state legible instead of silent.
- **Running drift on `in-production` transitions.** `done` is where the question
  belongs.
- **The idempotent path.** `close --status done` on a feature already `done`
  prints `already done` and skips drift, per FEAT-015. Unchanged.

## Key Risks

- **A commit naming several features pollutes each one's haystack.** Halved by
  AC6 — sibling *specs* are excluded — but a commit that changes two features'
  *code* still contributes both. Accepted: the alternative is per-file
  attribution, and code changed in one commit alongside a feature is weak
  evidence, not no evidence.
- **`--grep` is case-insensitive substring matching.** `FEAT-1` would match
  `FEAT-10`. Not fixed: Meridian pads to three digits, so the collision needs a
  four-digit repo, and the failure is over-inclusion rather than a miss.
- **An AC that asserts *absence* always looks uncovered.** AC7 above says three
  paths stay visible; nothing about them appears in the diff, because the point
  is that they were not touched. FEAT-020's AC13 has the same shape ("passes
  untouched"). Not a new problem and not fixable lexically — a negative claim has
  no positive evidence in a diff — but worth knowing before reading a report:
  these are the false positives, and they are recognisable by the AC wording.
- **History mode makes a passing report cheaper to get.** A feature merged with
  no commits naming it now reports `none`, which is correct — but a feature
  whose merge commit touched a lot will look well-covered. The heuristic's
  existing caveat still applies and is still printed.

## Verification

908 tests pass in the locked environment (+7), ruff and mypy clean.

Five of the six new tests fail against the previous implementation; the sixth —
the sibling-spec case — passes there for the wrong reason, since without history
mode the AC is uncovered anyway. A seventh test pins the exclusion directly by
running the same history through both exclusion sets, so only the widening makes
it pass.

Live, on this repo, from `main` after everything merged: FEAT-023 8/8, FEAT-024
2/2, FEAT-025 4/4, FEAT-026 2/2, and FEAT-020 still correctly flags AC13 — the
criterion that asserts a file was *not* changed, and so by construction names
something absent from its own diff.
