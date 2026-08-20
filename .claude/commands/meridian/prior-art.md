---
model: claude-sonnet-5
---

Answer "have I solved this before, in another repo?" by searching every Meridian project's
research and reporting what each other project concluded, and where to read it.

$ARGUMENTS is the question. An optional `-n N` sets how many prior-art hits to consider
(default 6).

Examples:
  /prior-art how should a shared vector store be scoped per project?
  /prior-art -n 10 what have I learned about rate limiting scrapers?

Prior art is **another repo's** research. It is a lead to follow, never this project's own
conclusion. Everything below exists to keep that distinction visible.

## Steps

1. Parse $ARGUMENTS:
   - Extract `-n N` if present; default 6. Remove it from the question string.
   - The remaining text is the question. If nothing remains, ask the user:
     *"What do you want to know whether you have already solved?"*

2. Retrieve both sides in one call:
   ```
   meridian search "<question>" --all-projects --json --prior-art <N> --per-project 2
   ```
   The payload has two separately ranked lists. They are never merged:
   - `results` — this project's own research (`project` equals the current project).
   - `prior_art` — other projects' research, each hit carrying `project`, `feat_id`,
     `source_name`, `feat_path`, `resolvable` and `unresolvable_reason`.

3. If `prior_art` is empty, say so plainly — *"No prior art found: no other project has
   research at least as relevant as this project's own hits."* Then report whatever is in
   `results` and stop. An empty answer is a real answer here; the corpus is small and most
   questions legitimately have no precedent.

4. For each prior-art hit, in order:
   - If `resolvable` is true, read `<feat_path>/spec.md` — and `breakdown.md` or
     `decisions/` if the spec points at one — to find what **that project** concluded.
     Read only that feature's directory. Do not crawl the rest of the repo.
   - If `resolvable` is false, do not guess where the research lives. Report the chunk text
     and the `unresolvable_reason` verbatim; the research is real even though the checkout
     has moved or the project was never registered.
   - Group hits by project so the reader sees which repo said what.

5. Never merge a foreign finding into this project's answer. Attribution rules, without
   exception:
   - Name the project in the same sentence as the claim: *"`portfolio-management` concluded
     X"* — never *"we decided X"* or *"the research shows X"*.
   - Quote or closely paraphrase; do not restate a foreign conclusion as a recommendation.
   - If the other project's context differs (different scale, stack, constraints), say so.
     A conclusion that was right there may be wrong here.
   - Never resolve a foreign `FEAT-NNN` against this repo's specs. Feature IDs repeat across
     repos; use the `<project>/FEAT-NNN` label the CLI already returns.

## Output format

### Have I solved this before? — "<question>"

**In this project** (`<current project>`)
What this repo's own research says, or *"nothing in this project's research"*. One short
paragraph. Cite as `[FEAT-NNN / source-name]`.

---

**Prior art — other repos**

For each project with hits, one block:

#### `<project>` — <FEAT-NNN>: what it concluded
- **Concluded:** one or two sentences, stated as that project's finding, not as advice.
- **Evidence:** `[<project>/FEAT-NNN / source-name]` — the passage this rests on.
- **Read it:** `<feat_path>` — or, when unresolvable: *"not openable — <reason>"*.

If a hit is unresolvable, keep the block, drop the **Read it** path, and say plainly that the
chunk is all that could be recovered.

---

**Does it transfer?**
One short paragraph per genuinely relevant precedent: what carries over to this project and
what does not. Name the differences you can see; where you cannot tell, say you cannot tell.

**Next step**
One concrete action — open a named feature directory, `/ask` a sharper question, or capture
the lead as an idea with `meridian new "<idea>"`.

---

Do not answer the question from your own knowledge. Everything here comes from retrieved
chunks and the feature directories they point at. If the prior art is thin, say it is thin —
a confident synthesis of two chunks from an unrelated repo is worse than no answer.
