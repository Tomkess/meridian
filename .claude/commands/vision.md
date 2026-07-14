---
model: claude-haiku-4-5-20251001
---

Read `specs/VISION.md` and display it.

If $ARGUMENTS is empty: show the current vision and ask the user if they want to update it.

If $ARGUMENTS contains text (the new vision): rewrite `specs/VISION.md` with that text as the one-paragraph north star. Keep the "How to use this file" section intact below the paragraph.

Rules for a good vision:
- One paragraph, no more
- Describes the *end state*, not the means
- Timeless — should still be true in 10 years
- If the user's draft is too long or tactical, suggest a tightened version before writing

After writing, confirm what was saved.
