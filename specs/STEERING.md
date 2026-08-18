# Project Steering

Guidance for AI agents working in this project. Read by `/spec`, `/breakdown`, `/tasks`, and `/plan`
before producing any output — treat these as hard constraints, not suggestions.

---

## Architecture Constraints

- **Do not run `meridian index` in this repo, or in any repo, until FEAT-007 lands.**
  `lancedb_path` defaults to the global `~/.meridian/lancedb`, and `reindex_all()` calls
  `db.drop_table("chunks")` unconditionally — so a rebuild in one project deletes every other
  project's vectors. This has already happened once (2026-08-18). To verify reindex behaviour, point
  a `MeridianConfig` at a temp `lancedb_path` and call `reindex_all()` directly. To rebuild after a
  loss, chunk + embed per project and go through `upsert_chunks()`, which deletes only rows matching
  `(feat_id, source_name)` instead of dropping the table.
- **Query the store with `search().limit(n)`, never `to_arrow()`.** `to_arrow()` returns a single
  fragment — it reported 10 rows for a 178-row table — so any check built on it will silently
  under-report and look like data loss.

<!-- More architectural rules. Examples:
- All new modules go under `meridian/`
- Config is always loaded via `load_config()`, never accessed directly
- No circular imports between meridian submodules
-->

## Coding Standards
<!-- Language/framework standards. Examples:
- Python 3.11+, type hints on all public functions
- Use `rich` for all CLI output, no plain `print()`
- Prefer dataclasses over dicts for structured return values
-->

## Naming Conventions
<!-- How to name things in this project. Examples:
- Feature IDs: `feat-NNN` lowercase in frontmatter, `FEAT-NNN` in display
- CLI commands: kebab-case (e.g. `sync-jobs`, not `syncJobs`)
- Spec frontmatter keys: snake_case
-->

## Domain Glossary
<!-- Key terms specific to this project/domain. Examples:
- "feature" = a FEAT-NNN spec, not a git feature branch
- "appetite" = time we're willing to invest (xs/s/m/l), not effort estimate
- "cycle" = a planning betting cycle (e.g. "2026-Q2")
-->

## AI Behavior
<!-- How Claude should approach tasks in this project. Examples:
- Always ask for appetite before writing a spec if it's not set
- Tasks should be sized at 1–4 hours each
- Prefer small, focused commits over large sweeping changes
- When in doubt, surface a decision rather than guess
-->
