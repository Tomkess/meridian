Deep research synthesis for a feature. Reads all ingested sources, runs semantic search, and
produces a structured research brief: what we know, what we don't, and what to do next.

$ARGUMENTS is the feature ID (e.g. `feat-007` or `FEAT-007`). If omitted, ask the user which
feature to research.

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

3. Run scoped semantic search to retrieve the most relevant chunks from this feature's corpus:
   ```
   meridian search "<feature name>" --feat <feat-id> -n 15
   ```
   Then run a broader cross-feature search to find related knowledge elsewhere:
   ```
   meridian search "<feature name>" -n 8
   ```

4. Read the raw source files in `specs/FEAT-NNN_*/sources/` if they are `.txt` files and are
   small enough (< 200 lines each). This gives full context beyond the top-N chunks.

5. Read any existing summaries in `specs/FEAT-NNN_*/summaries/` to avoid repeating work.

6. Synthesise the output below from the spec, source files, and search results.

## Output format

### Research summary — FEAT-NNN: <name>

**Coverage**: N source(s) enriched · top themes: <3 keywords from chunk content>

---

#### Background
2–3 sentences contextualising the problem space based on the research. What domain, what scale,
what prior work exists.

#### Key findings
Bullet list of concrete findings from the research. Each bullet must:
- Be grounded in a specific chunk or source (cite inline as `[source-name]`)
- Be a fact or claim, not a vague observation
- Be relevant to the feature's spec and goal

Aim for 5–10 bullets. More is fine if the research is deep. Skip filler.

#### Constraints and risks surfaced
What do the sources reveal about constraints, failure modes, tradeoffs, or known pitfalls?
Format as a short table:

| Constraint / Risk | Source | Implication for this feature |
|---|---|---|

#### How this informs the spec
Connect findings directly to the spec's acceptance criteria, open questions, or scope.
Be concrete: "Finding X suggests AC #3 should add a latency threshold" rather than "this is relevant".

#### Cross-feature connections
From the broad search: list any other features whose research overlaps this one semantically.
Format: `FEAT-NNN — <what it shares> (from: <source>)`
If none, omit this section.

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

After producing the output, check: if `confidence` in the spec frontmatter is `low` but the
research is actually substantial (5+ strong findings), suggest updating it:
> *"Research looks solid — consider bumping confidence to `medium`:*
> `meridian close FEAT-NNN --confidence medium`"
