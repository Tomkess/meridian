---
model: claude-sonnet-4-6
---

Stress-test an idea, feature, or goal against the vision and current strategy.

$ARGUMENTS can be a feature ID, a goal ID, or free-form text describing the idea to challenge.

Steps:
1. Read `specs/VISION.md`.
2. Read all `specs/goals/*.md`.
3. If $ARGUMENTS is a feature ID, read its spec. If a goal ID, read the goal file. If free-form text, treat it as an idea to evaluate.

Run the following challenges and output the results:

---

## Challenge Report — <subject>

### 1. Vision Alignment
Does this serve the north star, or does it only serve a short-term goal? Rate: **Strong / Weak / Misaligned**. Explain in 2 sentences.

### 2. The "So What" Test
If this were completed tomorrow, what would be measurably different? If the answer is vague, flag it.

### 3. Complexity vs. Value
Is the effort proportionate to the outcome? Could a simpler version deliver 80% of the value?

### 4. Hidden Assumptions
What has to be true for this to work? List 3-5 assumptions. Flag any that are unvalidated.

### 5. The Reversibility Test
If this turns out to be wrong, how easy is it to undo or change direction? Rate: **Reversible / Costly to reverse / Irreversible**.

### 6. What's Being Ignored
What problem or stakeholder is this NOT solving, and does that matter?

### 7. Verdict
**Proceed** / **Proceed with caution** / **Rethink** — one sentence on why.

---

Be direct. The purpose of this command is to find weaknesses before they become problems, not to validate the idea.
