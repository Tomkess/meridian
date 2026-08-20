---
model: claude-sonnet-5
---

Answer a question using semantic search across all enriched research.

$ARGUMENTS is the question to answer, with an optional `--feat FEAT-NNN` flag to scope the search
to a single feature's research corpus, and an optional `--prior-art` flag to also look for
precedent in other Meridian projects.

Examples:
  /ask what are the latency constraints found in the research?
  /ask --feat feat-003 what does the literature say about caching strategies?
  /ask --prior-art have we picked a chunking strategy anywhere before?

## Steps

1. Parse $ARGUMENTS:
   - Extract `--feat FEAT-NNN` if present (normalise to uppercase, e.g. `FEAT-003`). Remove it from
     the question string.
   - Extract `--prior-art` if present, and remove it from the question string. Without it, this
     skill answers from **this project's research only** — that is the default and it does not
     change.
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
   If `--prior-art` was given, run one more search that widens to other projects:
   ```
   meridian search "<question>" --all-projects --json --prior-art 5
   ```
   Its `prior_art` list is other repos' research. Keep it apart from everything above: it
   informs the **Prior art** section only, and never the Answer.

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

### Prior art
**Only when `--prior-art` was given.** Omit this section entirely otherwise.

For each hit in the `prior_art` list, one line naming the project first:
- `<project>/FEAT-NNN` — what **that project** concluded, in its own terms · read it at
  `<feat_path>`, or *"not openable — <unresolvable_reason>"* when it cannot be resolved.

Never fold these into the Answer above and never write *"we found"* or *"the research shows"*
about them — they are another repo's conclusions, reached in another repo's context, and may
not transfer. If `prior_art` is empty, say *"no prior art found in other projects"*.

### What the research doesn't cover
If the question touches areas where no chunks were found, name those gaps explicitly.
Suggest a concrete follow-up: a source to enrich, a spike to run, or a search refinement.

---

Keep the answer focused on what the research actually says. Do not invent or infer beyond the
retrieved chunks. If you are uncertain, say so.
