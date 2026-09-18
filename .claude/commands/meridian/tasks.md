---
model: claude-sonnet-5
---

Generate an ordered, atomic task list for a feature — the AI-executable handoff before building.

$ARGUMENTS is the feature ID (e.g. `feat-007`). If omitted, ask which feature to generate tasks for.

This skill bridges spec → build. Each task must be small enough to complete and commit independently
(target: 1–4 hours). Together they form the complete work list for the feature.

## Steps

0. **Lifecycle guard:** Check the spec frontmatter `status` field.
   - If `status` is `idea` → stop and tell the user: *"Run `/spec` first to elaborate this into a draft
     (idea → draft), then `/breakdown`, then `/tasks`. Generating tasks from an unelaborated idea
     produces low-quality work units."*
   - If `status` is `draft` → proceed (this is the expected state).
   - If `status` is already `in-progress` or later → note it but proceed; the user may be regenerating tasks.

1. Read `specs/FEAT-NNN_*/spec.md` — focus on: Summary, Appetite, Acceptance Criteria, Out of Scope.
2. Read `specs/FEAT-NNN_*/breakdown.md` — focus on: Components, Implementation Order, Test Strategy.
   If `breakdown.md` doesn't exist, ask the user to run `/breakdown FEAT-NNN` first.
3. If `specs/STEERING.md` exists, read it — apply its naming conventions and standards to task
   descriptions so they match the project's language and patterns. If `specs/CONTRACT.md` exists,
   read it too and use its exact module, type and CLI names — it is binding, and it replaces
   reading other features' specs to find out what they called things.

   Read nothing else. This stage does **not** need `VISION.md`, the goal file, `sources/`,
   `summaries/`, or other features' specs — the breakdown already encodes those decisions.
   Do not run `meridian search` here.
4. Derive the task list:
   - Follow the **Implementation Order** from `breakdown.md` as the primary sequence.
   - Map each task to at least one Acceptance Criterion where possible.
   - Interleave test/validation tasks with the implementation they cover — place each test task
     immediately after the task that makes it possible, not batched in a block at the end. A
     reader should see impl → test → impl → test, so each slice is independently verifiable.
   - Flag tasks that require a decision with `[DECISION NEEDED]`.
   - Keep tasks atomic: if a task takes > 4 hours, split it.

Write the task list to `specs/FEAT-NNN_*/tasks.md` in a **single** Write call. Do not read it back
to verify, and do not make a revision pass. Task-list output is billed at roughly 5× input and is
never cached, so a write-review-rewrite cycle triples the cost of this stage for little gain.

Keep each task to the three lines shown below — description, `Pre:`, `AC:`. Do not add per-task
rationale, design notes, or code sketches; those belong in `breakdown.md` and repeating them here
is the main reason task lists bloat. If the list exceeds ~60 tasks, stop and say the feature should
be split rather than continuing to write.

---

## Tasks — FEAT-NNN: <name>

> Appetite: `<xs|s|m|l>`  ·  Generated: <today>

- [ ] 1. <Task description>
       Pre: <what must already exist / be true before starting this task>
       AC: #<N> *(reference the AC it satisfies)*
- [ ] 2. <Task description>
       Pre: <precondition, or "none" if this is the first task>
- [ ] 3. Write tests for <component> covering: <AC list>
       Pre: implementation of task N complete
- [ ] 4. <Task description> [DECISION NEEDED: <what needs deciding>]
...

---

Guidelines for `Pre:`:
- Name the specific files, functions, or states that must exist before the task can start.
- "Pre: none" is valid for the first task or standalone tasks.
- If a task depends on another task in this list, write "Pre: task N complete."
- This lets an AI agent pick up any task in isolation without stalling on missing context.

5. If the current `status` is `draft`, transition it via the CLI (do not edit frontmatter directly —
   the CLI also rebuilds the registry):
   ```
   meridian close FEAT-NNN --status in-progress
   ```
   If status is already `in-progress` or later, skip this step.
6. Confirm what was written and show the task count.

## Task quality checklist (apply mentally before writing each task)
- Does it have a single, observable output?
- Are its pre-conditions stated explicitly?
- Could a developer (or AI agent) start it without asking questions?
- Is it small enough to commit independently?
- Does it reference an AC or test strategy item?
