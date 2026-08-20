---
model: claude-sonnet-5
---

Deep research synthesis for a feature. Reads all ingested sources, runs semantic search, and
produces a structured research brief: what we know, what we don't, and what to do next.
The brief is **written to disk with resolvable citations**, so the reasoning survives the session.

$ARGUMENTS is the feature ID (e.g. `feat-007` or `FEAT-007`). If omitted, ask the user which
feature to research.

## Citation rules — read before writing anything

A citation names one chunk of research: `project:FEAT-NNN:source_name#chunk_idx`.
Every field comes straight from a `meridian search --json` result — `project`, `feat_id`,
`source_name`, `chunk_idx`. Use the result's `citation` field verbatim when it is present;
otherwise assemble the four fields in that order.

Three rules, and they are the whole point of this skill:

1. **Every factual claim carries at least one citation.** A claim is factual if it asserts
   something about the world, the domain, or the codebase. No citation, no claim.
2. **A claim with no supporting chunk is an inference, and says so.** Write it as
   `*(inference — no supporting chunk)*` at the end of the line. An honest inference is
   useful; an inference dressed as a finding is not. When the corpus is thin, most lines
   will be inferences — that is the corpus reporting its own state, not a failure.
3. **Never cite a file in `summaries/`.** Those are your own prior conclusions. Citing them
   turns synthesis into evidence, and the next round cites the round before it — the output
   reads better every time while nothing new is ever learned. Evidence lives in `sources/`.

## Steps

1. Resolve the feature:
   - Normalise the ID to uppercase (e.g. `FEAT-007`).
   - Find the spec at `specs/FEAT-NNN_*/spec.md`. Read it fully (frontmatter + body).
   - Extract: feature name, goal, status, appetite, confidence, `sources:` list.

2. Check research coverage:
   - List files in `specs/FEAT-NNN_*/sources/` and `specs/FEAT-NNN_*/summaries/`.
   - If `sources/` is empty, say:
     > *"No research has been enriched for this feature yet. Run:*
     > `meridian enrich FEAT-NNN <pdf|url|file>`
     > *to index your first source, then re-run `/research`."*
     Stop.

3. Run scoped semantic search with `--json`, so every hit carries the fields a citation needs:
   ```
   meridian search "<feature name>" --feat <feat-id> -n 15 --json
   ```
   Then run a broader cross-feature search to find related knowledge elsewhere:
   ```
   meridian search "<feature name>" -n 8 --json
   ```

4. Read the raw source files in `specs/FEAT-NNN_*/sources/` if they are `.txt` files and are
   small enough (< 200 lines each). This gives full context beyond the top-N chunks.
   A claim drawn from a file you read rather than a retrieved chunk still needs a citation —
   find the chunk covering that passage in the search results, or label the claim an inference.

5. Read any existing brief in `specs/FEAT-NNN_*/summaries/` — for continuity, to avoid
   repeating work, and to notice where a conclusion has changed. Treat them as **context, never
   as evidence**: nothing in `summaries/` may be cited.

6. Spawn a synthesis agent to produce the research brief:
   Use the Agent tool with `model: "opus"`. Pass it a prompt containing:
   - The full spec content (frontmatter + body)
   - All semantic search results from step 3 (the raw JSON, so citations stay exact)
   - All source file contents read in step 4
   - All existing summaries from step 5, marked as context-only
   - The citation rules above and the output format below (copy both verbatim)

   Instruct the agent: *"You are a research synthesis expert. Using only the provided context,
   produce a Research Summary following the exact output format. Do not invent findings not
   present in the sources. Every factual claim carries a citation; anything you cannot cite is
   labelled an inference. Never cite a file under summaries/."*

7. Check two citations before writing. Pick the two the argument leans on hardest and run:
   ```
   meridian cite "<citation>"
   ```
   It exits non-zero when the chunk is gone. If it does, the claim is unverified — fix the
   citation or drop the claim. Do not write a brief containing a citation you did not check.

8. Write the brief to `specs/FEAT-NNN_*/summaries/research-YYYY-MM-DD.md`, where the date is
   today's (`date +%F`).
   - If that file already exists, **rewrite it** — a second run on the same day supersedes the
     first.
   - **Never modify a `research-*.md` from any earlier date.** Those are what a conclusion is
     diffed against; overwriting one destroys the only record that the reasoning changed.
   - Print the same content to the conversation, unaltered.

9. Record the brief in the spec's frontmatter so a reader of `spec.md` finds the reasoning
   without listing the directory. Edit `specs/FEAT-NNN_*/spec.md`, preserving every other
   field, so that its frontmatter carries:
   ```yaml
   briefs:
     - summaries/research-YYYY-MM-DD.md
   ```
   Append to the existing `briefs:` list if there is one; do not duplicate an entry that is
   already there; leave `sources:` alone (that lists inputs, not output).

## Output format

### Research summary — FEAT-NNN: <name>

**Coverage**: N source(s) enriched · top themes: <3 keywords from chunk content>

---

#### Background
2–3 sentences contextualising the problem space based on the research. What domain, what scale,
what prior work exists. Cite each sentence, or label it an inference.

#### Key findings
Bullet list of concrete findings from the research. Each bullet must:
- Be a fact or claim, not a vague observation
- Be relevant to the feature's spec and goal
- End with its citation(s) in backticks: `` `project:FEAT-NNN:source_name#chunk_idx` ``
- Or, if no chunk supports it, end with `*(inference — no supporting chunk)*`

Aim for 5–10 bullets. More is fine if the research is deep. Skip filler.

#### Constraints and risks surfaced
What do the sources reveal about constraints, failure modes, tradeoffs, or known pitfalls?
Format as a short table — the Source column holds the citation, not just a filename:

| Constraint / Risk | Source | Implication for this feature |
|---|---|---|

#### How this informs the spec
Connect findings directly to the spec's acceptance criteria, open questions, or scope.
Be concrete: "Finding X suggests AC #3 should add a latency threshold" rather than "this is
relevant". Carry the citation from the finding you are leaning on.

#### Cross-feature connections
From the broad search: list any other features whose research overlaps this one semantically.
Format: `FEAT-NNN — <what it shares> (`<citation>`)`
If none, say so explicitly.

#### Research gaps
What questions does the spec raise that the current research does not answer?
List as open questions:
- *"What happens when X exceeds Y?"*
- *"No source covers Z — this is an assumption."*

#### Recommended next actions
Prioritised list of concrete next steps:
1. Enrich a specific source (name it) to fill a gap
2. Run `/ask` with a specific question
3. Create a spike (if confidence is low on a key assumption)
4. Update spec frontmatter (confidence, depends_on, etc.)

---

After writing the file, confirm:
> *"Brief written to `specs/FEAT-NNN_*/summaries/research-YYYY-MM-DD.md` · N claims cited ·
> M labelled as inferences."*

Then check: if `confidence` in the spec frontmatter is `low` but the research is actually
substantial (5+ strong findings, each cited), suggest updating it:
> *"Research looks solid — consider bumping confidence to `medium`:*
> `meridian close FEAT-NNN --confidence medium`"

A brief that is mostly inferences is **not** grounds for a confidence bump. It is grounds for
enriching more sources.
