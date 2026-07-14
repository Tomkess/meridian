---
model: claude-sonnet-5
---

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

5. Spawn a design agent to produce the breakdown:
   Use the Agent tool with `model: "opus"`. Pass it a prompt containing:
   - The full spec content (Summary, Acceptance Criteria, Appetite, Dependencies sections)
   - All summaries from step 2
   - All dependency spec contents from step 3
   - All constraints and standards from STEERING.md (step 4)
   - The breakdown structure below (copy it verbatim into the prompt)

   Instruct the agent: *"You are a senior software architect. Using only the provided context,
   produce a complete Technical Breakdown following the exact structure. Apply all STEERING.md
   constraints. Be concrete — name actual components, fields, and integration points. Do not
   leave placeholder text."*

   Write the agent's output to `specs/FEAT-NNN_*/breakdown.md`.

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
Use the component effort scale below — this is **per-component** granularity, separate from
the feature-level `appetite` field in `spec.md` (xs/s/m/l).

| Scale | Meaning |
|---|---|
| S | A few hours |
| M | 1–3 days |
| L | 1–2 weeks |
| XL | More than a sprint — consider splitting the feature |

**Overall:** M  *(replace with your estimate)*

<!-- C4: Component effort (S/M/L/XL) is finer-grained than spec appetite (xs/s/m/l).
     A feature with appetite "m" (1–2 weeks) may have one L component and several S ones. -->

### Implementation Order
Ordered list of components — what must be built first. This order feeds directly into `/tasks`.

---

After writing the file, the spec frontmatter `updated` date will be refreshed automatically
the next time a CLI command writes to it (e.g. when `/tasks` transitions status to `in-progress`).
**Do not edit frontmatter directly** — status transitions must go through the CLI so the registry
is rebuilt. C3: breakdown.md itself does not trigger a status change.

Confirm what was written, then suggest: "Run `/tasks FEAT-NNN` to generate the atomic task list."
