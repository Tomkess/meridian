---
model: claude-haiku-4-5-20251001
---

Render a strategic roadmap: goals × features × gaps.

Steps:
1. Read `specs/VISION.md`.
2. Read all files in `specs/goals/`.
3. Read `specs/REGISTRY.md` and all `specs/FEAT-*/spec.md` files.

Output a roadmap view — do NOT write to a file, output in the conversation:

---

## Vision
> <one-line extract from VISION.md>

## Goals × Features

For each goal (sorted by horizon), show its features grouped by lifecycle status:

### goal-NN — <goal name> (<horizon>)
<measurable_outcome>

| Status | Features |
|---|---|
| in-production | FEAT-001 Name, FEAT-002 Name |
| done | FEAT-003 Name |
| in-progress | FEAT-004 Name |
| draft/idea | FEAT-005 Name, FEAT-006 Name |
| blocked | FEAT-007 Name (blocked by: reason) |

**Coverage:** X% of acceptance criteria met across features for this goal.

---

### Unlinked Features
Features not assigned to any goal (goal = `~` or null).

### Gaps
Goals with no features in `in-progress` or later — nothing actively moving toward this bet.

### Suggested Next
Based on dependencies and current state: what 1-3 things should be started next and why.

---

Keep it dense and scannable. Use the actual feature names, not just IDs.
