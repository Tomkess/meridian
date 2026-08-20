---
model: claude-sonnet-5
---

Summarise a research paper or source document as a single A4-page brief.
Strict constraint: the output must fit one A4 page — no more than 550 words.

$ARGUMENTS accepts two forms:
  /brief feat-007                        — list available sources and ask which one to brief
  /brief feat-007 paper.pdf              — brief a specific source by filename (partial match ok)

## Citation rules — read before writing anything

A citation names one chunk of research: `project:FEAT-NNN:source_name#chunk_idx`.
Every field comes straight from a `meridian search --json` result — `project`, `feat_id`,
`source_name`, `chunk_idx`. Use the result's `citation` field verbatim when it is present;
otherwise assemble the four fields in that order.

The same three rules `/research` follows, because a brief is read the same way:

1. **Every factual claim about the source carries a citation.** Findings, numbers, thresholds,
   stated limitations — each ends with its citation in backticks.
2. **A claim you cannot tie to a chunk is an inference, and says so** — end the line with
   `*(inference — no supporting chunk)*`. Your prior knowledge of a paper is not the paper.
3. **Never cite a file in `summaries/`.** Those are Meridian's own synthesis. Citing one makes
   the next brief evidence for the brief after it, and the argument grows more confident while
   resting on nothing new. Evidence lives in `sources/`.

Word budget note: a citation is not prose. Count words, not citation strings, against the 550.

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
   - Run a scoped search with `--json` to get the citable chunks for this source:
     ```
     meridian search "<feature name>" --feat <feat-id> -n 12 --json
     ```
     Keep only results whose `source_name` is the chosen source. These are what you cite; the
     full text you read is what you understand.

4. Also read any existing brief in `specs/FEAT-NNN_*/summaries/` — use it as a quality check,
   but write this brief fresh from the source text, and cite nothing from it.

5. Check one citation before writing:
   ```
   meridian cite "<citation>"
   ```
   If it exits non-zero the chunk is gone — re-run the search and use a citation that resolves.

6. Write the brief. **Hard limit: 550 words total.** Count carefully. Cut ruthlessly.
   Save it to: `specs/FEAT-NNN_*/summaries/<source-stem>-brief.md`
   - Re-briefing the same source rewrites that file.
   - Never modify a brief belonging to a different source, and never modify a
     `research-*.md` — those are `/research` output and are diffed across dates.

7. Record the brief in the spec's frontmatter so a reader of `spec.md` finds it without
   listing the directory. Edit `specs/FEAT-NNN_*/spec.md`, preserving every other field, so
   that its frontmatter carries:
   ```yaml
   briefs:
     - summaries/<source-stem>-brief.md
   ```
   Append to the existing `briefs:` list; do not duplicate an entry already there; leave
   `sources:` alone (that lists inputs, not output).

## Brief format (exactly this structure, no additions)

```markdown
# Brief: <paper/document title>

**Source:** <filename> · **Feature:** FEAT-NNN — <name> · **Date:** <today's date>

---

## In one sentence
<The single most important claim or finding of this paper, ≤ 25 words.> `<citation>`

## Purpose
<Why was this paper written / what problem does it address? 2–3 sentences.> `<citation>`

## Method
<How did the authors arrive at their findings? 1–2 sentences. Skip for non-academic sources.> `<citation>`

## Key findings
- <Finding 1 — be specific, include numbers/thresholds where present> `<citation>`
- <Finding 2> `<citation>`
- <Finding 3> `<citation>`
- <Finding 4 — optional>
- <Finding 5 — optional>

## Limitations
<What does the paper itself acknowledge as limitations or scope? 1–3 bullets. Omit if none stated.> `<citation>`

## Relevance to FEAT-NNN
<How does this directly inform the feature's spec, design, or open questions? 2–3 sentences.>
<This section is usually judgment rather than quotation — label uncited sentences
`*(inference — no supporting chunk)*`.>
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
> *Word count: NNN / 550 · N claims cited · M labelled as inferences*

If the word count exceeds 550, trim and re-save before confirming.
