Produce a technical decomposition of a feature.

$ARGUMENTS is the feature ID (e.g. `feat-007`). If omitted, ask which feature to break down.

This skill answers **how** to build it — architecture, components, data model, integration points.
It is distinct from `spec.md` (which answers *what* to build) and `tasks.md` (which lists atomic work units).

## Steps

1. Read the spec at `specs/FEAT-NNN_*/spec.md` — especially Summary, Acceptance Criteria,
   Appetite, and Dependencies sections.
2. Read any summaries in `specs/FEAT-NNN_*/summaries/`.
3. Read specs for any features listed in `depends_on` to understand what's already available.
4. If `specs/STEERING.md` exists, read it — apply its architectural constraints and standards
   to all design decisions below.

Produce a breakdown and write it to `specs/FEAT-NNN_*/breakdown.md`. Use this structure:

---

## Technical Breakdown — FEAT-NNN: <name>

### Components
List each distinct component/module/service that needs to be built or modified.

| Component | What it does | New or existing? | Effort (S/M/L) |
|---|---|---|---|

### Data Model
Any new tables, schemas, or data structures. Include field names and types.

### Integration Points
External systems, APIs, or other features this touches.

### Test Strategy
What needs to be tested and how (unit, integration, manual).

### Total Effort Estimate
S = hours, M = 1–3 days, L = 1–2 weeks, XL = sprint+

**Overall:** M

### Implementation Order
Ordered list of components — what must be built first. This order feeds directly into `/tasks`.

---

After writing the file, update the spec frontmatter: update `updated` to today.
Do **not** transition status — the feature moves to `in-progress` after `/tasks` is run.

Confirm what was written, then suggest: "Run `/tasks FEAT-NNN` to generate the atomic task list."
