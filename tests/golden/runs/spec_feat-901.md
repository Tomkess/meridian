---
id: feat-901
status: idea
appetite: xs
confidence: null
goal: goal-01
cycle: null
depends_on: []
enables: []
created: 2026-05-01
updated: 2026-05-01
---

## Summary

`meridian search` currently prints results labeled only by bare `feat_id`
(e.g. `FEAT-014`), forcing the reader to cross-reference the ID against
`REGISTRY.md` or the spec directory to know what feature actually matched.
This feature makes search results self-describing by showing the feature's
human-readable name alongside its ID, so an agent or teammate scanning
results can immediately tell what surfaced without a second lookup —
directly serving goal-01's "zero-friction" bar (no tab-switching to
decode an ID).

**Codebase note:** a first pass at this already exists upstream
(`meridian/specs.py::feat_display_name`, wired into
`meridian/search.py::format_results` and `meridian/cli.py::search`,
with unit tests in `tests/test_specs.py::TestFeatDisplayName`). It derives
the display name by parsing the feature's directory slug
(`FEAT-001_add_search` → `"add search"`). That works only when the
directory suffix is an idea-text slug. Verified against this project's
own specs, it does not:

```
feat_display_name(specs_dir, "feat-901") → "FEAT-901: xs idea"
feat_display_name(specs_dir, "feat-902") → "FEAT-902: m draft"
feat_display_name(specs_dir, "feat-903") → "FEAT-903: l in progress"
```

Directories here are suffixed `<appetite>_<status>`, not an idea slug, so
the "name" shown is internal metadata leakage, not a feature name — worse
than the bare ID it replaced. Separately, `rebuild_registry`
(`meridian/specs.py:290`) already reads a `name` field straight from spec
frontmatter for REGISTRY.md — but none of this project's spec.md files
(`FEAT-901`/`902`/`903`) actually carry a `name:` field, even though
`create_spec` writes one (`meridian/specs.py:149`) for specs created via
`meridian new`. So there are two independent, inconsistent name-resolution
strategies in the codebase, and neither is robust on its own for specs
that predate/bypass the `name:` field or that live in non-slug directories.

This spec scopes fixing that inconsistency, not shipping the concept from
scratch.

## Appetite

`xs` — < 1 day

## Acceptance Criteria

- [ ] Given a feature's `spec.md` has a `name` field in frontmatter, when
  `meridian search` prints results, then the label reads `FEAT-NNN: <name>`
  using that frontmatter value (matches how `rebuild_registry` already
  resolves names for `REGISTRY.md`).
- [ ] Given a feature's `spec.md` has no `name` field but its directory
  follows the `FEAT-NNN_<idea_slug>` convention, when `meridian search`
  prints results, then the label falls back to the humanized directory
  slug (existing `feat_display_name` behavior, preserved for specs created
  before the `name` field existed).
- [ ] Given neither a `name` field nor a slug-shaped directory suffix exists
  (e.g. this project's own `FEAT-901_xs_idea`, `FEAT-902_m_draft`,
  `FEAT-903_l_in_progress`), when `meridian search` prints results, then
  the label does not leak internal metadata tokens (`xs`, `draft`,
  `in_progress`, etc.) as if they were the feature name — it falls back to
  the bare `FEAT-NNN` ID instead.
- [ ] Given both the rich CLI path (`cli.py::search`) and the plain-text
  path (`search.py::format_results`, used by skills like `/ask`), when the
  same result set is rendered by each, then both show the identical
  resolved name (no divergence between the two call sites).
- [ ] Given `meridian search "<query>" --no-rerank -n 5` is run in a
  terminal, when at least one enriched result exists, then every result
  line shows `FEAT-NNN: <name>` rather than a bare ID (regression check
  for the existing behavior this spec builds on).

## Scope

- Resolve the fallback order inside `feat_display_name` (or its
  replacement) to: frontmatter `name` → directory-slug heuristic → bare
  `feat_id`.
- A cheap heuristic to detect when a directory suffix is *not* a real idea
  slug (e.g. matches known status/appetite tokens) so step 3's fallback
  doesn't fire garbage instead of the ID.
- Unit tests covering all four fallback branches, including a fixture that
  reproduces this project's own `<appetite>_<status>` directory pattern.
- Keep both call sites (`cli.py::search`, `search.py::format_results`)
  passing through the same resolver so they can't drift again.

## Out of Scope

- Backfilling a `name:` field into every existing `spec.md` that lacks one
  (a migration, not a display fix — could be a fast follow if desired).
- Renaming existing spec directories to match the idea-slug convention.
- Changes to `REGISTRY.md` rendering — it already reads `name` correctly
  from frontmatter and is unaffected by this fix.
- Ranking/reranking behavior in `semantic_search` — display-only change.

## Key Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Heuristic for "not a real slug" is imperfect (a genuine idea slug could coincidentally match a status/appetite token) | Low | Low | Prefer frontmatter `name` first so the heuristic is only a last-resort guard; document the known edge case |
| Fixing `feat_display_name` in place changes output for any spec currently relying on the (broken) status-leak behavior | Low | Low | No legitimate caller depends on the current garbage output; covered by existing + new unit tests |
| Two call sites (`cli.py`, `search.py`) drift again if not refactored to share one resolver | Medium | Medium | Route both through the same function; add a test asserting output parity between them |

## Dependencies

- **Depends on:** none
- **Enables:** none identified

## Related Research

- No `sources/` material has been enriched for this feature yet. Run
  `meridian enrich feat-901 <source>` if research docs exist.
- Direct codebase inspection (this elaboration): `meridian/specs.py:43`
  (`feat_display_name`), `meridian/specs.py:290` (`rebuild_registry`,
  reads `name` from frontmatter), `meridian/specs.py:149` (`create_spec`
  writes `name` into frontmatter), `meridian/search.py` (`format_results`),
  `meridian/cli.py:543` (`search` command), `tests/test_specs.py`
  (`TestFeatDisplayName`).
- `meridian search --no-rerank` returned no results when run in this
  project (`No results. Run meridian enrich <feat-id> <source> to index
  research.`) — the vector index here has nothing enriched yet, so
  cross-feature semantic search couldn't surface prior art beyond the
  direct code read above.

## Open Questions

1. Should `create_spec` (or a one-time migration command) backfill
   `name:` onto specs that predate the field, so the slug-parsing fallback
   is needed less over time?
2. Is the `<appetite>_<status>` directory suffix used elsewhere in this
   project intentionally (e.g. for at-a-glance folder browsing), or should
   spec directories be renamed to the idea-slug convention `create_spec`
   already produces for new specs?
3. Should the "not a real slug" heuristic be a fixed token blocklist
   (`APPETITE_VALUES` ∪ `VALID_STATUSES`, both already defined in
   `specs.py`) or something more general?
