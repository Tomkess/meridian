---
model: claude-sonnet-5
---

Manage strategic goals in `specs/goals/`.

## Subcommands

### `/goal new`
Guide the user through creating a new goal.

1. Read `specs/VISION.md` and all existing files in `specs/goals/`.
2. Ask the user to describe the goal if not already in $ARGUMENTS.
3. Run all 6 validation checks — show each with a pass/flag/concern result:
   - **Alignment**: Does it serve the vision? Is it traceable to the north star?
   - **Overlap**: Does it duplicate or heavily overlap an existing goal?
   - **Conflict**: Does it create tension with an existing goal?
   - **Scope**: Too granular (→ should be a spec, not a goal)? Too broad (→ part of the vision)?
   - **Measurability**: Can progress be observed or measured?
   - **Coverage**: Are there existing `idea`/`draft` specs that already serve this goal? List them.
4. Surface any concerns and ask the user to confirm before writing.
5. Determine the next goal ID by scanning `specs/goals/` for existing `goal-NN.md` files.
6. Write `specs/goals/goal-NN.md` with this frontmatter:

```yaml
---
id: goal-NN
name: <title>
status: active
created: <today>
horizon: <1-year | 2-year | 3-year>
measurable_outcome: <one sentence>
---
```

Followed by a 2–4 sentence description of the goal.

### `/goal review`
Re-validate all existing goals against the current vision.

1. Read `specs/VISION.md` and all `specs/goals/*.md`.
2. For each goal, re-run the 6 checks.
3. Output a summary table: Goal | Alignment | Overlap | Conflict | Scope | Measurable | Coverage.
4. Flag any goal that fails 2+ checks as needing revision.
5. Do NOT auto-edit goals — surface findings for the user to act on.
