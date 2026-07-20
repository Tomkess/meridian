---
model: claude-sonnet-5
---

Capture a new idea and create a stub spec for it.

The idea text comes from $ARGUMENTS. If $ARGUMENTS is empty, ask the user to describe their idea.

## Steps

1. Read `specs/VISION.md` and all files in `specs/goals/` to understand the current strategic context.
2. Read `specs/REGISTRY.md` to see existing features.
3. Briefly restate the idea back to the user in one sentence to confirm you understood it correctly.
4. Map the idea to the most relevant goal — show your reasoning in one sentence. If no goal fits,
   flag it: "This idea doesn't map cleanly to any current goal — consider `/goal new` first,
   or confirm it's still worth capturing."
5. Check for overlap: does a similar idea already exist in REGISTRY? If yes, name it and ask
   if the user wants to proceed anyway or enrich the existing spec instead.
6. Ask for appetite — one question, inline:
   > "How much time is this worth?  `xs` < 1 day  ·  `s` 1–3 days  ·  `m` 1–2 weeks  ·  `l` 2–6 weeks"
   If the user says "not sure" or skips, proceed without it (can be set later in `/spec`).
7. Run `meridian new "<idea text>" --goal <goal-id>` (append `--appetite <value>` if provided).
8. Confirm what was created and suggest the next step: `/spec` to elaborate, or
   `meridian enrich <feat-id> <source>` if they have research to add first.

Keep the interaction tight — one question at a time if clarification is needed.
