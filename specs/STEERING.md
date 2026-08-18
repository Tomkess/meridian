# Project Steering

Guidance for AI agents working in this project. Read by `/spec`, `/breakdown`, `/tasks`, and `/plan`
before producing any output — treat these as hard constraints, not suggestions.

---

## Architecture Constraints

- **The vector store is global and shared.** `lancedb_path` defaults to
  `~/.meridian/lancedb`, which every Meridian install writes to. Since FEAT-007 every row
  carries a `project` column, `reindex_all()` deletes only the current project's rows, and
  `semantic_search()` scopes to `cfg.project` by default. Treat any new code touching the
  store as cross-project by default: pass a project to `upsert_chunks()` and `search_similar()`,
  and reach for `project=None` only when a query is deliberately cross-project.
- **`meridian index` is not a registry-only command.** It always re-embeds. To repopulate
  another repo's rows without rewriting its `REGISTRY.md` (which would leave an unrelated
  project with modified tracked files), use `meridian index --vectors-only`. To verify reindex
  behaviour in tests, point a `MeridianConfig` at a temp `lancedb_path`.
- **Never resolve a foreign `feat_id` against the local specs directory.** Feature IDs repeat
  across repos — FEAT-001 currently exists in three. Use `search.result_label()`, which
  namespaces rows from other projects as `<project>/FEAT-NNN` instead of borrowing a local
  feature's name.
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
