---
appetite: xs
blocked_at: null
blocked_by: null
confidence: high
created: 2026-05-01
cycle: null
depends_on: []
enables: []
goal: goal-01
id: feat-901
status: draft
updated: '2026-07-14'
---

## Summary

`meridian search` results currently identify a hit by feature only via a display
name computed by `feat_display_name()` (`meridian/specs.py:43`), which was added in
commit `fddfdd2` (2026-05-25) *after* this idea was filed. That helper derives the
name by stripping `FEAT-NNN_` off the spec's directory name and turning underscores
into spaces — it assumes the directory suffix is always the idea-derived slug
(`FEAT-001_add_semantic_search` → "add semantic search"). It has no fallback to the
spec's actual content. When a directory doesn't hold that slug — e.g. this very
repo's `FEAT-901_xs_idea`, `FEAT-902_m_draft`, `FEAT-903_l_in_progress` — the
"name" shown is garbage:

```
$ python3 -c "from meridian.specs import feat_display_name as f; from pathlib import Path
print(f(Path('specs'), 'feat-901'))"
FEAT-901: xs idea
```

So the original ask ("show the real feature name, not just the feat_id") is only
half-solved: a name is shown, but it isn't reliably *the feature's name* — it's
whatever the directory happens to be called. This makes `meridian search` results
for older, renamed, or non-standard directories (any repo that doesn't strictly
follow the `meridian new` slug convention) confusing rather than helpful, directly
undercutting goal-01's "no friction" bar since users have to open the spec to
figure out what a result actually refers to.

## Appetite

`xs` — < 1 day

## Acceptance Criteria

- [ ] Given a feature whose directory slug matches its idea text (the `meridian new`
  happy path), when `meridian search` returns a hit for it, then the result header
  still reads `FEAT-NNN: <readable name>` (no regression vs. current behavior).
- [ ] Given a feature whose directory does **not** encode a readable slug (e.g.
  `FEAT-901_xs_idea`), when `meridian search` returns a hit for it, then the
  displayed name is derived from the spec's actual content (its idea line /
  Summary), not from the directory name.
- [ ] Given a feat_id with no matching spec directory at all, when it's displayed,
  then it falls back to the bare `FEAT-NNN` id (preserves existing regression
  test `TestFeatDisplayName.test_falls_back_to_id_when_no_dir`).
- [ ] Given a spec whose idea/Summary text is long, when its name is rendered in
  search results, then it is truncated to a scannable length (consistent with the
  existing ~200-char preview truncation already used for chunk text at
  `cli.py:581`) so long entries don't blow out the result list's alignment.
- [ ] Given the existing `TestFeatDisplayName` suite (`tests/test_specs.py:45-63`),
  when the fix lands, then all four existing cases still pass unchanged, plus new
  cases cover the mismatched-slug and long-text scenarios above.

## Scope

- Make the search result's per-hit name authoritative: read it from the spec's
  own content (first idea line, or `## Summary` once elaborated) rather than
  parsing the directory name.
- Keep `feat_display_name()` (or its replacement) as the single function backing
  both call sites already found (`meridian/cli.py:582`, `meridian/search.py`) so
  there's one code path to fix.
- Directory-slug parsing may remain as a last-resort fallback (cheap, no I/O) when
  the spec file itself can't be read, but must never be the primary source once a
  readable name is available in the spec.
- Add regression tests for the mismatched-slug case, reproduced above, so this
  doesn't silently regress again.

## Out of Scope

- Adding a formal `title`/`name` field to the frontmatter schema — that's a wider
  schema change touching `create_spec`, `save_spec`, and the registry, well beyond
  an `xs` fix. This feature only needs to *read* an existing, already-authoritative
  text source (the idea line / Summary), not add a new one.
- Migrating or renaming existing non-conforming spec directories (e.g. this repo's
  `FEAT-90x_<appetite>_<status>` fixtures) — the fix must tolerate them, not fix
  their names.
- Changing `meridian status` / the registry table's name rendering — out of scope
  unless it shares the same helper for free.

## Key Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Reading spec.md per result adds file I/O to every `meridian search` hit (docstring currently promises "no extra file I/O beyond a glob") | High (by design) | Low | `limit` defaults to 5 and is user-bounded; one small YAML/text parse per hit is negligible next to the embedding search itself |
| No frontmatter title field exists yet, so "name" must be inferred from free text (idea line or Summary) which can be verbose or absent | Medium | Low | Truncate consistently with the existing chunk-preview truncation; fall back to directory slug, then bare id, if body is empty |
| Fix only updates `feat_display_name()` but a second call site (`meridian/search.py`) reimplements its own logic and gets missed | Medium | Medium | Confirmed both call sites exist (`cli.py:582`, `search.py`) — route both through one shared helper during implementation |
| Existing happy-path tests (`tests/test_specs.py:45-63`) assume directory-slug derivation is the whole implementation and could mask a regression if not updated | Low | Medium | Extend `TestFeatDisplayName` with the mismatched-slug case reproduced in this spec, so the exact bug found here is pinned as a regression test |

## Dependencies

- **Depends on:** none
- **Enables:** none identified

## Related Research

- No `sources/` documents have been enriched for this feature yet — `meridian
  search` itself returned no results ("Run `meridian enrich feat-901 <source>` to
  index research"), so there is no ingested research corpus to draw on.
- Codebase inspection of the installed `meridian` package (`meridian/specs.py:43`,
  `meridian/cli.py:582-587`) found this was partially implemented on 2026-05-25 in
  commit `fddfdd2` ("CLI enhancements — ... display names"), 24 days after this
  idea was filed (2026-05-01) — worth checking with whoever filed the idea whether
  they've seen the current (buggy) behavior or filed it against the pre-`fddfdd2`
  bare-`feat_id` output.
- Reproduced directly against this repo's own `specs/` directory: `feat_display_name`
  returns `"FEAT-902: m draft"` and `"FEAT-903: l in progress"` for FEAT-902/903 —
  concrete, current evidence the existing fix is incomplete, not hypothetical.
- `tests/test_specs.py:45-63` (`TestFeatDisplayName`) — existing coverage is
  happy-path only; no case exercises a directory whose suffix isn't a readable slug.
- Corroborating evidence from `meridian/specs.py:327` (`rebuild_registry`): it reads
  `s.get("name", "Untitled")` directly off spec frontmatter — a *third*, entirely
  separate expectation of where "name" lives, distinct from both `feat_display_name`'s
  directory-slug guess and this spec's own body text. No spec in this project
  (feat-901 through feat-904, including the fully elaborated feat-902/903/904) ever
  sets a `name:` frontmatter key, so `specs/REGISTRY.md` shows "Untitled" for every
  single feature today. This confirms the project has no single, reliable source of
  truth for a feature's display name yet — two different code paths each guess
  differently, and both are wrong for this repo's specs. Worth flagging to whoever
  owns `/spec` and `meridian new` even though fixing the registry's "Untitled" rows
  is out of scope here.

## Open Questions

1. Should the displayed name come from the spec's first body line (works even at
   `status: idea` before a Summary exists) or specifically the `## Summary`
   section (richer, but only exists post-`/spec`)? Leaning toward "first
   non-empty body line, whatever it is" for simplicity and universality.
2. Is there a real-world repo already hitting this bug in a non-fixture way (i.e.
   directories renamed after creation, or migrated from another tool), or is the
   mismatched-slug case here specific to this project's own fixtures? Affects how
   urgently this should be prioritized versus other `xs` work.
3. Should this also fix `meridian status`'s table if it turns out to share the
   same helper — or is that better tracked as its own follow-up once this lands?
