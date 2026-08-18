---
abandoned_at: null
abandoned_reason: null
appetite: s
blocked_at: null
blocked_by: null
confidence: high
created: '2026-08-18'
cycle: null
depends_on: []
enables: []
goal: '~'
id: feat-006
name: Ingest annotated screenshots into a feature's research corpus
scheduler: null
sources:
- sources/screenshot-2026-08-18-15-40-59.png
- sources/screenshot-2026-08-18-15-40-59.notes.md
status: done
tags: []
updated: '2026-08-18'
---

## Summary

Meridian's research corpus is text-only: `meridian enrich` handles PDFs, URLs, and text files.
Visual evidence has no door in. The driving use case is dashboard-as-code debugging — the developer
edits declarative dashboard definitions, renders them in the UI, sees something wrong, and the
fastest capture of "what is wrong" is a screenshot plus a sentence of prose. Today that evidence
either lives outside the spec entirely or, worse, gets fed to `meridian enrich` where the PNG is
read as text and garbage bytes are embedded into LanceDB.

This feature adds screenshot ingest: the image is copied into `sources/` untouched, the developer's
notes are stored in a human-editable `.notes.md` sidecar, and the notes — plus a *visual reading* of
the image written by whoever can actually see it — are chunked and embedded so `/ask`, `/research`,
and `/spec` retrieve them and point back at the exact image. Pixels stay pristine; the searchable
artifact is the prose about them.

Two ergonomics decisions came out of prototyping the real workflow (see Related Research):

1. **Capture is the CLI's job.** An image attached in a Claude Code chat arrives as base64 in the
   agent's context with no filesystem path — verified empirically, and no on-disk attachment cache
   exists. So the agent can *see* an image it cannot *copy*. `--latest-screenshot` closes the gap by
   picking the newest image out of the OS screenshot directory, which is where the file already is.
2. **Description is the agent's job.** When the screenshot is in an agent's context, the agent reads
   axis labels, values, and anomalies far more reliably than a local Ollama vision model. The
   `/meridian:enrich` skill writes that reading into the sidecar; Ollama `--vision` remains as the
   headless fallback for when no agent is in the loop.

## Appetite

`s` — 1–3 days

## Acceptance Criteria

- [ ] Given a feature `FEAT-006` and a PNG at `~/shots/kpi.png`, when I run
      `meridian enrich feat-006 ~/shots/kpi.png --note "KPI tile shows 0, expected 4.2M"`,
      then `sources/kpi.png` is a byte-identical copy of the original, `sources/kpi.notes.md`
      contains the note text, and the command reports the number of chunks embedded.
- [ ] Given that ingest, when I run `meridian search "KPI tile shows 0"`, then a chunk from
      `FEAT-006 / kpi.notes.md` is returned and its text contains the image reference
      `sources/kpi.png`, so the retrieving agent can open the screenshot.
- [ ] Given that ingest, when I read `spec.md` frontmatter, then `sources:` contains both
      `sources/kpi.png` and `sources/kpi.notes.md`.
- [ ] Given an image argument with **no** `--note` and **no** `--note-file`, when the command runs
      in a non-interactive shell, then it exits non-zero with a message naming both flags — an
      image with no notes is never silently embedded.
- [ ] Given a fresh screenshot in the OS screenshot directory, when I run
      `meridian enrich feat-006 --latest-screenshot --note "…"` with no positional source, then the
      newest image in that directory is ingested, and the command **prints the resolved filename and
      its age** before embedding — the picked file is never left implicit.
- [ ] Given a macOS box with `defaults read com.apple.screencapture location` set to a custom
      directory, when `--latest-screenshot` runs, then that directory is searched; when the key is
      unset or the platform is not macOS, then `~/Desktop` (then `~/Pictures/Screenshots`) is used,
      and an empty/missing directory exits non-zero naming the directory searched.
- [ ] Given the newest screenshot is older than 10 minutes, when `--latest-screenshot` runs, then a
      warning states the age and the ingest still proceeds — stale-but-named beats silently wrong.
- [ ] Given a screenshot named `Screenshot 2026-08-18 at 15.40.59.png`, when it is ingested, then
      the stored filename is slugified to `screenshot-2026-08-18-15-40-59.png`, the sidecar is
      `screenshot-2026-08-18-15-40-59.notes.md`, and the slug is deterministic (re-ingesting the same
      file produces the same names, so `upsert_chunks` replaces rather than duplicates).
- [ ] Given no image data in the clipboard, when I run `--from-clipboard`, then it exits non-zero
      with a message saying the clipboard holds no image; given an image in the clipboard, then it is
      written into `sources/` as `clipboard-YYYY-MM-DD-HHMMSS.png` and ingested. The stamp is
      dash-separated rather than ISO-with-`T` on purpose: `slug_image_name()` lowercases the stem, so
      an ISO `T` would make the filename the CLI prints differ from the file it writes.
- [ ] Given `--note-file` pointing at a sidecar whose `## Visual reading` section was written by an
      agent, when I run enrich, then that section is preserved verbatim, embedded alongside the
      notes, and the `- Described by:` header line records the author (e.g. `claude-opus-5 (agent)`).
- [ ] Given `/meridian:enrich feat-006 "KPI tile shows 0"` with a screenshot attached in the chat,
      when the skill runs, then it writes a sidecar containing my note plus its own visual reading,
      calls `meridian enrich feat-006 --latest-screenshot --note-file <sidecar>`, and reports the
      resolved image filename back to me.
- [ ] Given an image argument and `--vision`, when a vision model is configured and Ollama is
      reachable, then the sidecar's `## Visual reading` section is filled by that model, the caption
      is embedded alongside the notes, and `- Described by:` records `ollama:<model>`.
- [ ] Given `--vision` and Ollama unreachable or the vision model not pulled, when the command
      runs, then the screenshot and notes are still ingested and embedded, and the caption failure
      is reported as a warning, not an error (degrade, never lose the note).
- [ ] Given both `--vision` and a `--note-file` that already carries a `## Visual reading` section,
      when the command runs, then the existing section wins, no Ollama call is made, and a warning
      says the caption was skipped — an agent's reading is never overwritten by the local model.
- [ ] Given an existing screenshot ingest, when I edit `sources/kpi.notes.md` by hand and re-run
      `meridian enrich feat-006 ~/shots/kpi.png --note-file sources/kpi.notes.md`, then the stale
      chunks for that source are replaced, not duplicated (existing `upsert_chunks` delete-then-add
      contract holds).
- [ ] Given a screenshot ingest, when I run `meridian index` (full rebuild), then the notes sidecar
      is re-embedded, the chunk count matches the pre-rebuild count, no Ollama vision call is made,
      and the sidecar file is byte-unchanged (`git diff` empty) — `reindex_all` no longer skips
      non-`.txt` sources.
- [ ] Given a PNG passed to `meridian enrich` with no note flags in an **interactive** shell, when
      prompted, then the typed note is used; an empty note aborts without writing anything.
- [ ] Given a `--note` or `--note-file` whose note text is blank or whitespace-only, when
      `ingest_screenshot` runs, then it raises before writing anything — the library enforces the
      "no note, no ingest" rule itself rather than trusting the CLI to have checked. *(Added during
      implementation: the CLI guard alone would leave the library callable into a bad state.)*
- [ ] Given a `.pdf`, `.txt`, or URL source, when I run `meridian enrich` as before, then behaviour
      is unchanged (no regression in the existing three paths).
- [ ] Given the new `/meridian:enrich` skill, when the test suite runs, then
      `meridian/skills/commands/enrich.md` and `.claude/commands/meridian/enrich.md` are
      byte-identical (`test_skill_sync.py`) and the skill declares a `model:` in frontmatter
      (`test_models.py`).

## Scope

- Recognised image suffixes: `.png`, `.jpg`, `.jpeg`, `.webp`, `.gif` (still-image semantics only).
- `meridian enrich <feat> [<source>]` extended with:
  - `--note/-n TEXT`, `--note-file PATH`
  - `--latest-screenshot` — resolve newest image from the OS screenshot directory instead of a
    positional source; prints the resolved filename + age
  - `--from-clipboard` — write clipboard image to `sources/clipboard-YYYY-MM-DD-HHMMSS.png` (secondary path,
    guarded when the clipboard holds no image)
  - `--vision/--no-vision` (default off) — Ollama fallback describer, headless use only
- New `ingest_screenshot()` path in `meridian/enrich.py` alongside `enrich_feature()`; image files
  never reach `extract_text()`'s `read_text()` fallback.
- Filenames slugified deterministically: lowercase, spaces and filler words collapsed to `-`,
  punctuation stripped from the stem, suffix preserved.
- Sidecar format: `<slug>.notes.md` with a provenance header (`Image:`, `Feature:`, `Captured:`,
  `Described by:`), a `## Notes` section, and an optional `## Visual reading` section. Header lines
  are prepended into the embedded text so every chunk carries the image path.
- `## Visual reading` is author-agnostic: filled by the calling agent (via `--note-file`), by Ollama
  (via `--vision`), or left absent. An existing section is never overwritten.
- Chunk `source_name` = the sidecar filename.
- `extract_text()` gains an explicit guard: image suffix without the screenshot path raises a clear
  `RuntimeError` naming `--note`.
- `reindex_all()` glob widened to include `*.notes.md` (not all `*.md`, never `summaries/`) so a full
  rebuild preserves screenshot notes; reindex never calls a vision model.
- New `/meridian:enrich` slash command: `meridian/skills/commands/enrich.md` +
  byte-identical `.claude/commands/meridian/enrich.md`, with `model:` frontmatter. It sees the
  attached image, writes notes + visual reading into a sidecar, and shells out to the CLI with
  `--latest-screenshot --note-file`.
- Config: `ollama_vision_model` key in `.meridian.toml` under `[meridian]`, default empty string.
- Docs: `meridian help`, `meridian init` template, `README.md`, `CLAUDE.md` CLI + slash-command
  tables.

## Out of Scope

- Burning annotations into pixels (arrows, boxes, text overlays) — no Pillow dependency. Rejected
  in favour of the sidecar; revisit only if agents prove unable to locate regions from prose.
- OCR of on-screen text (tesseract). An agent reading the image covers the same need better.
- Multimodal / image-vector embeddings and image-to-image similarity search. The vector store stays
  text-only.
- Video, screen recordings, animated GIF frame extraction.
- Cloud vision APIs called by the CLI itself. The CLI describes images only via local Ollama; any
  frontier-model reading arrives through the skill path as text.
- Automated screenshot capture (headless browser driving the dashboard UI). Separate feature.
- Recovering image bytes from a Claude Code chat attachment. Verified impossible — attachments are
  base64 in agent context with no path and no on-disk cache; `--latest-screenshot` is the answer.
- Windows screenshot-directory detection. macOS (`com.apple.screencapture location`) and a
  `~/Desktop` / `~/Pictures/Screenshots` fallback chain only; elsewhere pass an explicit path.
- Image de-duplication or compression on ingest.

## Key Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `--latest-screenshot` silently picks the wrong (older, unrelated) screenshot | high | high | Always print resolved filename + age before embedding; warn above 10 minutes; ingest is idempotent per slug so a wrong pick is cheap to correct |
| Ollama vision caption hallucinates dashboard values and pollutes the corpus | medium | high | `--vision` is opt-in, defaults off, and now the *fallback* rather than the primary describer; output is confined to a labelled `## Visual reading` section with `Described by:` attribution; an agent-written section is never overwritten |
| Binary PNGs committed into `specs/` bloat the git repo | medium | medium | Document expected sizes; note `.gitattributes`/LFS as the escape hatch if a repo outgrows it; no automatic compression in v1 |
| `reindex_all()` glob widening picks up unrelated `.md` files under `sources/` and double-embeds content | medium | low | Restrict to `*.notes.md` plus `*.txt`, never `summaries/` |
| Slugification is non-deterministic or lossy, so re-ingest duplicates chunks instead of replacing them | medium | medium | Pure deterministic slug function with round-trip unit tests; slug collisions overwrite by design (same slug = same screenshot) |
| Reindex regenerates captions, producing drift against the committed sidecar | medium | low | Caption written once at ingest and persisted; `reindex_all` re-embeds stored text and never calls a describer; test asserts `call_count == 0` and byte-unchanged sidecar |
| New skill file drifts between `meridian/skills/commands/` and `.claude/commands/meridian/` | medium | low | `test_skill_sync.py` already enforces byte-parity; add both copies in the same commit |
| Clipboard read is fragile (no image class, TIFF-vs-PNG, non-macOS) | medium | low | Secondary path with an explicit "clipboard holds no image" guard; `--latest-screenshot` is the documented primary |
| Sidecar `source_name` collides when two different directories yield the same image basename | low | medium | Same collision semantics as existing file ingest; document it, do not special-case in v1 |

## Dependencies

- **Depends on:** none. Builds on the existing `enrich` pipeline (`extract_text` → `save_source` →
  `chunk_text` → `embed` → `upsert_chunks`).
- **Enables:** future automated UI-capture feature; visual-regression notes on dashboard-as-code
  features.
- External: Ollama with a vision-capable model — only for the `--vision` fallback. No new Python
  dependencies (base64 + `httpx` cover Ollama; `defaults`/`osascript` via `subprocess` cover macOS
  capture).

## Related Research

No sources have been enriched for this feature yet. Run
`meridian enrich FEAT-006 <pdf|url|file>` to index research, then re-run `/research`.

Prior-art notes from reading the codebase:

- `enrich_feature()` (meridian/enrich.py:265) is a linear six-step pipeline; the screenshot path
  diverges only at extraction and file-saving, so it can reuse steps 3–6 verbatim.
- `save_source()` already `shutil.copy2`s non-URL sources and writes a `.txt` companion for
  non-`.txt` files — that `.txt` companion is exactly the corruption being removed, so the
  screenshot path must not reuse it.
- `upsert_chunks()` deletes by `(feat_id, source_name)` before inserting, which gives re-ingest
  idempotency for free — provided the slug is deterministic.
- `reindex_all()` globs only `sources/*.txt` — a latent gap this feature must close, otherwise
  screenshot notes vanish on the next `meridian index`.
- `test_skill_sync.py` enforces byte-parity between bundled skills and `.claude/commands/meridian/`;
  `test_models.py` requires a `model:` frontmatter key on every bundled skill.
- Cross-feature search returned only unrelated AI-eval research (features in other projects sharing
  `~/.meridian/lancedb`); no existing work overlaps this feature.

Empirical findings from prototyping the capture path (2026-08-18):

- A Claude Code chat attachment (`+` button) reaches the agent as base64 with **no filesystem path**.
  `~/.claude/` has no image/paste/attach/blob cache and no recent image files; the session scratchpad
  under `/private/tmp/claude-501/` likewise holds none. The agent can see the image but cannot copy
  it — hence CLI-side capture.
- The same screenshot *was* on disk at `~/Desktop/Screenshot 2026-08-18 at 15.40.59.png` (83.8 KB),
  which is what makes `--latest-screenshot` viable: the file exists, only the path was missing.
- `defaults read com.apple.screencapture location` returns "does not exist" on an unconfigured box,
  so the implementation must treat a missing key as `~/Desktop` rather than erroring.
- `osascript -e 'clipboard info'` on a text clipboard reports only `«class HTML»`, `«class utf8»`,
  `string` — no image class. Confirms `--from-clipboard` needs a class check before attempting a read.
- An agent-authored visual reading recovered axis labels, ranges, and per-point values from a
  GoodData scatter insight (`Earnings Yield vs FCF Yield`), plus the anomaly that "yield" metrics
  were unbounded (−1600, +3400) — the kind of detail that motivates preferring the agent path over a
  6 GB local vision model.

Post-implementation validation against the live external tools (2026-08-18) — the mocked tests assert
our own branching, so these are the findings only real calls could produce:

- **Ollama `/api/generate` contract confirmed:** payload key `images` (base64 list) and response field
  `.response` are both correct, verified with `gemma4:e4b`.
- **The local model's reading was measurably worse, as predicted.** On the same scatter insight,
  `gemma4:e4b` gave the X range as "-1750 to 0" (dropping the positive tail), placed an outlier at
  "(-1500, -1000)" instead of (-1600, -1250), and concluded "All labeled elements and the data points
  appear visible and accounted for" — i.e. it did not register the anomaly the screenshot was captured
  for. This is the concrete basis for ADR 006's agent-first decision.
- **`«class PNGf»` clipboard extraction works:** writes a valid 1610×876 PNG matching the source.
- **Two defects found that every mocked test passed:** the clipboard filename printed by the CLI did
  not match the file written (ISO `T` lowercased by the slug), and the skill's "do not diagnose root
  causes" instruction was blunt enough to suppress a visible fact about metric definitions. Both
  fixed; the first has a regression test. Lesson worth carrying: for a feature whose whole job is
  talking to external tools, mocked coverage is necessary but never sufficient.

## Open Questions

- `ollama_vision_model` default: **resolved — ship empty (`""`)**. With the agent path as primary,
  a concrete default would only produce "model not found" warnings on machines that never pull a
  multimodal model. `--vision` with no configured model warns and still ingests the note.
- Does the retrieving agent reliably open `sources/kpi.png` from a relative path in chunk text, or
  should the header carry a repo-root-relative path? Verify with a live `/ask` run.
- Should `/meridian:enrich` support ingesting an image the user references by path (rather than the
  latest screenshot) in the same invocation? Probably yes as a positional passthrough; confirm
  during implementation of the CLI surface.
- Multi-image ingest (`meridian enrich feat-006 shots/*.png --note …`) — one shared note or one note
  per image? Deferred; v1 is one image per invocation.
