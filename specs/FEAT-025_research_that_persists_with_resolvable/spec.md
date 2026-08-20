---
abandoned_at: null
abandoned_reason: null
appetite: m
blocked_at: null
blocked_by: null
confidence: medium
created: '2026-08-19'
cycle: null
depends_on: [feat-023]
enables: []
goal: goal-01
id: feat-025
name: 'Research that persists with resolvable citations'
sources: []
status: draft
tags: []
updated: '2026-08-19'
---

## Summary

The audit's finding was blunt: `/research` produces a synthesis and **persists
nothing**. The reasoning evaporates when the session ends, so the next session
re-derives it from the same sources at full cost, and no spec can point at the
evidence that justified it.

That is the gap between the claim — *a research corpus bound to the specs it
justifies* — and what exists, which is a folder of sources next to a spec that
never references them. The binding is one-directional and by convention only.

This makes research persist, and makes every claim in it resolvable back to the
exact chunk that supports it. A citation is not decoration: it is what lets a
reader — human or agent, six months later — check whether a conclusion still
follows from its evidence, or whether the evidence has since been replaced.

## Appetite

`m` — a citation format, a resolver, `/research` and `/brief` writing files, and
the loop-prevention that stops synthesis becoming evidence.

## Design decisions

**A citation needs no schema change.** `project:FEAT-NNN:source_name#chunk_idx`
is already unique in the store — those four fields are the identity of a row.
Inventing a citation key would create a second identity that can disagree with
the first.

**Synthesis must never be indexed as a source.** `reindex_all` globs
`sources/*.txt` and `sources/*.notes.md` and does not touch `summaries/`, so
today this holds by accident. It has to hold on purpose: if a research brief
were indexed, the next `/research` would retrieve the model's own prior
conclusion, cite it as evidence, and write a stronger version of it. That is a
citation loop that manufactures confidence out of nothing, and it degrades
silently — the output looks *better* each round. This gets an explicit test.

**Persisted research is dated and additive, never overwritten.** A brief is a
snapshot of what was known on a day. Overwriting destroys the diff, which is the
only way to see that a conclusion changed. `summaries/research-YYYY-MM-DD.md`.

**A citation that cannot be resolved is an error, not a warning.** The whole
value is checkability. A citation pointing at a chunk that no longer exists
means the evidence moved and the conclusion is unverified — the loudest possible
signal is the correct one.

## Acceptance Criteria

### Citation format

- **AC1** — Search results carry a stable citation string
  `project:FEAT-NNN:source_name#chunk_idx`, in both table and `--json` output.
- **AC2** — `meridian cite <citation>` prints the exact chunk text plus its
  source path, so any citation in any document can be checked from the CLI.
- **AC3** — Resolving a citation whose chunk no longer exists **fails loudly**
  with a message naming what is missing, and exits non-zero.
- **AC4** — Citations resolve across projects: a citation naming another
  project's row resolves if that project is tracked, and reports the project as
  untracked rather than as missing when it is not.

### Persistence

- **AC5** — `/research <feat>` writes `summaries/research-YYYY-MM-DD.md`
  containing findings, gaps, and next research actions.
- **AC6** — Every factual claim in a written brief carries at least one
  citation. A claim with no supporting chunk is stated as an inference and
  labelled as one.
- **AC7** — Running `/research` twice on the same day updates that day's file;
  running it on a later day writes a new one. Earlier briefs are never modified.
- **AC8** — `/brief` writes to `summaries/` with the same citation discipline.
- **AC9** — The spec's frontmatter records the briefs, so a reader of `spec.md`
  can find the reasoning without listing the directory.

### Loop prevention

- **AC10** — `summaries/` is **never** indexed. A test places a file in
  `summaries/` and asserts `reindex_all` produces no chunk from it.
- **AC11** — The reason is recorded in the code, not only in this spec: an
  indexed synthesis becomes evidence for the next synthesis, and the failure
  looks like improving quality.
- **AC12** — If a future source genuinely belongs in the corpus, it goes in
  `sources/`. There is no flag to index `summaries/`, because the flag would be
  used.

### Guards

- **AC13** — A test asserts a citation emitted by `meridian search` resolves via
  `meridian cite` — round-trip, not format-matching. A format both sides agree
  on but neither can resolve is the likely regression.
- **AC14** — A golden run for `/research` records its regression-critical
  behaviour: that it cites rather than asserts, and that an uncited claim is
  labelled an inference.

## Scope

`meridian/search.py` and `meridian/cli.py` (citation emission, `cite` command),
`meridian/enrich.py` (an explicit summaries exclusion with its reason),
`research.md` and `brief.md` skills, a golden run, and tests.

## Out of Scope

- **Binding acceptance criteria to evidence.** Attractive — an AC that names the
  chunk justifying it — but it changes the spec format and `meridian drift`
  reads that format. Separate feature, after this one proves citations are used.
- **Automatic re-verification of existing citations.** `meridian cite` makes it
  possible by hand; a `verify-all` sweep is worth building only once briefs
  exist to sweep.
- **Cross-project citation in briefs.** [[FEAT-024]] surfaces prior art; citing
  it inside a brief means this project's reasoning depends on another repo's
  checkout being present. Deliberately deferred.
- **A citation for screenshot sidecars beyond the existing chunk identity.**
  They already have `feat_id` + `source_name` + `chunk_idx` and need nothing
  special.

## Key Risks

- **The corpus is too thin to cite.** With most features holding no sources,
  `/research` will often have nothing to work from. AC6 then forces it to label
  nearly everything an inference, which is honest and will look like the feature
  failing. It is not — it is the corpus failing, and [[FEAT-023]] is the fix.
  This is why confidence is `medium` rather than `high`.
- **Citation discipline is enforced in a prompt.** AC6 and AC10's *intent* live
  in skill text, and prompts drift. AC14's golden run is the only real guard,
  and it is a weak one.
- **Dated briefs accumulate.** Ten briefs per feature is clutter. Accepted: the
  diff between them is the point, and clutter is cheaper than a lost conclusion.

## Verification

Round-trip: a citation produced by `meridian search` resolves through
`meridian cite` to the same text. And a file dropped in `summaries/` must produce
zero chunks after a full rebuild — the loop test.
