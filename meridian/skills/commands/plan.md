---
model: claude-sonnet-4-6
---

Generate a phased implementation plan for a feature.

$ARGUMENTS is the feature ID (e.g. `feat-007`). If omitted, ask which feature to plan.

This skill answers **when and in what order** to build — phases, milestones, dependencies.
It is optional but useful for larger features (appetite `l` or multi-team work).

## Steps

1. Read `specs/FEAT-NNN_*/spec.md` (requirements, appetite, ACs) and
   `specs/FEAT-NNN_*/breakdown.md` (components, implementation order).
   If `breakdown.md` doesn't exist, ask the user to run `/breakdown FEAT-NNN` first.
2. Read specs of any `depends_on` features to confirm they're `done` or `in-production`.
   If not, flag the dependency gap.
3. If `specs/STEERING.md` exists, read it — apply its conventions to naming and structure.

Write the plan to `specs/FEAT-NNN_*/plan.md`:

---

## Implementation Plan — FEAT-NNN: <name>

**Appetite:** `<xs|s|m|l>` — <label>
**Suggested branch:** `feat/feat-NNN-short-slug`

### Phase 1 — <name> (e.g. "Foundation")
**Goal:** What this phase achieves and why it comes first.
**Tasks:**
- [ ] Task A
- [ ] Task B
**Done when:** Verifiable completion condition.

### Phase 2 — <name>
...

### Phase N — <name>
...

---

**Estimated total:** M

---

After writing the file, update `updated` in the spec frontmatter.
Confirm what was written, then suggest: "Run `/tasks FEAT-NNN` to generate the atomic task list
from spec + breakdown."

Keep phases small enough to commit independently.
Flag any tasks that require a decision with `[DECISION NEEDED]`.
