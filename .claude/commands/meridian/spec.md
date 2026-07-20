---
model: claude-sonnet-5
---

Elaborate a draft idea into a full structured spec.

$ARGUMENTS is the feature ID (e.g. `feat-007` or `FEAT-007`). If omitted, ask the user which feature to elaborate.

## Steps

1. Find the spec file at `specs/FEAT-NNN_*/spec.md` matching the given ID.
2. Read the current spec (frontmatter + body), `specs/VISION.md`, and the linked goal file from `specs/goals/`.
3. If `specs/STEERING.md` exists, read it — use its constraints and conventions throughout this elaboration.
4. Check the `appetite` field in frontmatter. If it is `null` or missing, ask the user before proceeding:
   > "Before writing the spec — how much time is this feature worth?
   > `xs` = < 1 day  ·  `s` = 1–3 days  ·  `m` = 1–2 weeks  ·  `l` = 2–6 weeks"
   Set the appetite in frontmatter before continuing.
5. Read any text files in `specs/FEAT-NNN_*/sources/` — these are raw research documents.
6. Run semantic search to pull in related context from across all features:
   ```
   meridian search "<feature name>" --no-rerank -n 5
   ```
   Note any results from *other* features — they may reveal relevant prior art or dependencies.
7. Produce the elaborated spec body using the structure below. Write it directly into `spec.md`
   (preserve frontmatter, replace body). Also write a brief summary of each source file to
   `specs/FEAT-NNN_*/summaries/<source-stem>.md`.
8. Establish confidence in the problem definition. **Assess it yourself** from the elaboration
   and available research, and set it — do **not** end your turn waiting for an answer (the skill
   must work headlessly as well as interactively, and it cannot tell which mode it is in):
   - `low` = problem still vague / exploring  ·  `medium` = rough shape clear  ·  `high` =
     well-defined, testable criteria, few unknowns. Default to `medium` when genuinely unsure.
   State the value you chose with one line of reasoning, and how to override it:
   > "Confidence set to `<value>` — <one-line reason>. Override with
   > `meridian close FEAT-NNN --confidence <low|medium|high>` if you'd rate it differently."

   **If your assessed confidence is `low` and appetite is `m` or `l`**, also recommend a spike
   and record it under Open Questions (do not block on it):
   > "Confidence is low on a medium/large feature — consider an `xs` spike first:
   > `meridian new \"spike: <question to answer>\" --appetite xs`
   > A spike is a time-boxed investigation (< 1 day) that produces a decision, not shippable code."

   Never leave `confidence` as `null`.
9. Transition lifecycle state and update remaining fields:
   - If current `status` is `idea`, transition via CLI (rebuilds the registry):
     ```
     meridian close FEAT-NNN --status draft --confidence <low|medium|high>
     ```
   - If `status` is already `draft` or later (re-running `/spec`), skip the close call and update
     confidence directly: edit `confidence` in frontmatter.
   - Update `appetite` (confirmed in step 4) in frontmatter.
   - Patch `depends_on` / `enables` if search surfaced clear relationships.

## Spec body structure

```markdown
## Summary
One paragraph. What is this feature and why does it matter to the goal?

## Appetite
`<xs|s|m|l>` — <label, e.g. "1–2 weeks">

## Acceptance Criteria
- [ ] Given <context>, when <action>, then <outcome>
- [ ] Given ...

## Scope
What is explicitly in scope.

## Out of Scope
What is explicitly excluded (prevents scope creep).

## Key Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|

## Dependencies
- **Depends on:** feat IDs or external deps
- **Enables:** feat IDs unlocked by this feature

## Related Research
Brief bullets from source files and search results that informed this spec.

## Open Questions
Questions that must be answered before or during implementation.
```

Keep writing concise and technical. Acceptance criteria must be testable (Given/When/Then).
Risks should be honest, not boilerplate. If no sources have been enriched yet, note it and suggest
`meridian enrich FEAT-NNN <source>`.

Next step after this: run `/breakdown` to produce the technical design.

**Confidence guide:**
- `low` — you're still exploring the problem space; consider a short spike before writing a full spec.
- `medium` — the shape is clear enough to spec, but expect open questions and pivots during build.
- `high` — well-defined problem, clear success criteria, minimal unknowns; proceed with confidence.
