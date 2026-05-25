# Project Steering

Guidance for AI agents working in this project. Read by `/spec`, `/breakdown`, `/tasks`, and `/plan`
before producing any output — treat these as hard constraints, not suggestions.

---

## Architecture Constraints
<!-- List architectural rules that apply to all features. Examples:
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
