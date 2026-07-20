---
model: claude-sonnet-5
---

Answer a question using semantic search across all enriched research.

$ARGUMENTS is the question to answer, with an optional `--feat FEAT-NNN` flag to scope the search
to a single feature's research corpus.

Examples:
  /ask what are the latency constraints found in the research?
  /ask --feat feat-003 what does the literature say about caching strategies?

## Steps

1. Parse $ARGUMENTS:
   - Extract `--feat FEAT-NNN` if present (normalise to uppercase, e.g. `FEAT-003`). Remove it from
     the question string.
   - The remaining text is the question. If no question remains after stripping the flag, ask the
     user: *"What would you like to know?"*

2. Run semantic search to retrieve relevant chunks:
   ```
   meridian search "<question>" -n 10
   ```
   If `--feat` was given, also run a scoped search:
   ```
   meridian search "<question>" --feat <feat-id> -n 10
   ```
   If both were run, merge and deduplicate results, prioritising the scoped hits.

3. If no results are returned (empty LanceDB or no matching chunks):
   - Say: *"No research has been enriched yet. Run `meridian enrich <feat-id> <source>` to index
     a PDF, URL, or text file first."*
   - Stop.

4. Read the retrieved chunks carefully. Synthesise a direct, grounded answer to the question.

## Output format

### Answer
Write the answer in plain prose. Be direct — lead with the conclusion, then support it.
Do not pad. If the research does not contain enough information to answer confidently, say so
explicitly rather than speculating.

### Supporting evidence
For each chunk used to form the answer, cite it:
- `[FEAT-NNN / source-name]` — one sentence quoting or paraphrasing the relevant passage.

Limit to the 3–5 most relevant citations. Do not list every chunk retrieved.

### What the research doesn't cover
If the question touches areas where no chunks were found, name those gaps explicitly.
Suggest a concrete follow-up: a source to enrich, a spike to run, or a search refinement.

---

Keep the answer focused on what the research actually says. Do not invent or infer beyond the
retrieved chunks. If you are uncertain, say so.
