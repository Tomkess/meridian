---
model: claude-sonnet-4-6
---

Surface cross-feature relationships: overlaps, dependencies, and synergies.
Combines spec-level structural analysis with semantic search across enriched research.

$ARGUMENTS can be a specific feature ID to focus on, or empty to run across all active features.

## Steps

1. Read `specs/REGISTRY.md` to get the full feature list.
2. Read every `specs/FEAT-*/spec.md` that is not `abandoned`.
3. For each feature that has entries in `sources:` (i.e. has been enriched), run:
   ```
   meridian search "<feature name>" --no-rerank -n 5
   ```
   Use the results to find what *other* features' research overlaps semantically.
   If $ARGUMENTS is a specific feature ID, also run:
   ```
   meridian search "<feature name>" --feat <feat-id> -n 5
   ```
   to surface the most relevant chunks within that feature's own corpus.

4. Combine the structural read (frontmatter: `depends_on`, `enables`, `tags`, `goal`) with the semantic search results to produce the output below.

## Output format

### Overlaps
Features that solve similar problems or share significant scope. For each pair:
- **FEAT-NNN ↔ FEAT-MMM**: one sentence on what they share. Recommendation: merge / sequence / keep separate.
- If backed by semantic search hits, quote the relevant chunk snippets.

### Dependencies (undeclared)
Cases where one feature clearly needs output from another but the spec frontmatter doesn't reflect it.
Propose the specific `depends_on` additions.

### Synergies
Features that, built together or in sequence, would multiply value. Note the concrete opportunity.

### Semantic connections (from research)
Findings from `meridian search` — chunks from different features that cluster around the same concepts.
Format: `FEAT-NNN ↔ FEAT-MMM via "<shared concept>" (score X.XX)`

### Gaps
Goals with no features serving them, or areas implied by the vision that no spec covers.

### Suggested frontmatter updates
Concrete YAML patches to apply:
```yaml
# FEAT-NNN spec.md
depends_on: [feat-mmm]
enables: [feat-ppp]
tags: [shared-tag]
```

Be concrete — name features, quote chunks, propose specific edits. Don't pad.
