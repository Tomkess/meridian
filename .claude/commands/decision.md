---
model: claude-sonnet-5
---

Write an Architecture Decision Record (ADR).

$ARGUMENTS can be a title or free-form description of the decision. If empty, ask the user what decision to record.

Steps:
1. Read `specs/decisions/` to find the next ADR number (e.g. if `005-...md` exists, next is `006`).
2. Ask the user (if not obvious from context):
   - What was decided?
   - What were the main alternatives considered?
   - What drove the choice?
3. Write the ADR to `specs/decisions/NNN-<slug>.md` using this structure:

```markdown
# NNN — <Title>

**Status:** Accepted  
**Date:** <today>  
**Context:** <feature IDs or area this affects>

## Decision
One paragraph: what was decided and the core reason.

## Alternatives Considered
| Option | Pros | Cons |
|---|---|---|
| Chosen: <option> | ... | ... |
| <alternative> | ... | ... |

## Consequences
- **Positive:** ...
- **Negative / trade-offs:** ...
- **Neutral:** ...

## Revisit Trigger
What circumstance would prompt re-evaluating this decision?
```

Keep ADRs short — the goal is to capture the *why* so future contributors don't have to reverse-engineer the reasoning. After writing, confirm the file path.
