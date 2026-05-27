---
model: claude-sonnet-4-6
---

Summarise a research paper or source document as a single A4-page brief.
Strict constraint: the output must fit one A4 page — no more than 550 words.

$ARGUMENTS accepts two forms:
  /brief feat-007                        — list available sources and ask which one to brief
  /brief feat-007 paper.pdf              — brief a specific source by filename (partial match ok)

## Steps

1. Resolve the feature:
   - Normalise the ID to uppercase (e.g. `FEAT-007`).
   - Find the spec at `specs/FEAT-NNN_*/spec.md`. Read its frontmatter to get feature name and goal.

2. Resolve the source:
   - List all files in `specs/FEAT-NNN_*/sources/`.
   - If a source name was given in $ARGUMENTS, match it (case-insensitive partial match is fine).
     If multiple files match, ask the user to pick one.
   - If no source name was given, list the available sources and ask:
     > *"Which source would you like a brief for?*
     > 1. filename-a.txt
     > 2. filename-b.txt"*
     Wait for the user's selection.
   - If `sources/` is empty, say:
     > *"No sources enriched yet. Run `meridian enrich FEAT-NNN <pdf|url|file>` first."*
     Stop.

3. Retrieve content for the chosen source:
   - Read the source file directly from `specs/FEAT-NNN_*/sources/<filename>` if it is a `.txt`
     file (extracted text). Read up to 400 lines — enough for a full paper.
   - If the file is large (> 400 lines), also run a targeted search to get the highest-signal chunks:
     ```
     meridian search "<feature name>" --feat <feat-id> -n 12
     ```
     Filter results to chunks from this source only.

4. Also read any existing summary at `specs/FEAT-NNN_*/summaries/<source-stem>.md` if it exists —
   use it as a quality check, but write the brief fresh from the source text.

5. Write the brief. **Hard limit: 550 words total.** Count carefully. Cut ruthlessly.
   Save it to: `specs/FEAT-NNN_*/summaries/<source-stem>-brief.md`

## Brief format (exactly this structure, no additions)

```markdown
# Brief: <paper/document title>

**Source:** <filename> · **Feature:** FEAT-NNN — <name> · **Date:** <today's date>

---

## In one sentence
<The single most important claim or finding of this paper, ≤ 25 words.>

## Purpose
<Why was this paper written / what problem does it address? 2–3 sentences.>

## Method
<How did the authors arrive at their findings? 1–2 sentences. Skip for non-academic sources.>

## Key findings
- <Finding 1 — be specific, include numbers/thresholds where present>
- <Finding 2>
- <Finding 3>
- <Finding 4 — optional>
- <Finding 5 — optional>

## Limitations
<What does the paper itself acknowledge as limitations or scope? 1–3 bullets. Omit if none stated.>

## Relevance to FEAT-NNN
<How does this directly inform the feature's spec, design, or open questions? 2–3 sentences.>
```

**Word count rules:**
- "In one sentence": ≤ 25 words
- "Purpose": 40–60 words
- "Method": 20–40 words (or omit)
- "Key findings": 10–20 words per bullet, 3–5 bullets
- "Limitations": 10–20 words per bullet, 1–3 bullets (or omit)
- "Relevance": 40–60 words
- Total: must not exceed 550 words

After saving, confirm:
> *"Brief saved to `specs/FEAT-NNN_*/summaries/<source-stem>-brief.md`"*
> *Word count: NNN / 550*

If the word count exceeds 550, trim and re-save before confirming.
