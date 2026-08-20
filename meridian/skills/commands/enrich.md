---
model: claude-sonnet-5
---

Ingest an annotated screenshot into a feature's research corpus.

$ARGUMENTS is the feature ID followed by the note, e.g.
`feat-006 KPI tile shows 0, expected 4.2M`. If the feature ID is missing, ask which feature.
If the note is missing, ask what is wrong with the screenshot — never invent one.

Use this when the user attaches a screenshot and wants it kept as research: a broken dashboard,
an unexpected chart, a UI state worth remembering. For PDFs, URLs, and text files, use
`meridian enrich <feat-id> <source>` directly instead — no skill needed.

That command takes **several sources at once**, and a directory ingests every `.pdf`, `.txt`
and `.md` inside it (non-recursive). Each source is embedded fully before its own rows are
written, so one unreadable file does not lose the sources already ingested in that run; the
command reports per-source outcome and exits non-zero if any failed.

Re-running is cheap: a source whose text has not changed is skipped without touching Ollama.
A URL already saved in `sources/` is **not** re-fetched unless you pass `--refresh`.

Never enrich a file from `summaries/` — that directory holds Meridian's own synthesis, and the
command refuses it. Indexing a brief makes the next `/research` cite the model's own prior
conclusion as evidence.

## Why this skill exists

An image attached in chat reaches you as pixels with **no filesystem path**, so you can see it but
cannot copy it. The file is on disk, though — the OS screenshot directory has it. So the work
splits: the CLI captures the file (`--latest-screenshot`), and you supply the prose, because you can
read axis labels, values, and anomalies that a local vision model would miss.

## Steps

1. Parse $ARGUMENTS into `<feat-id>` (normalise to `FEAT-NNN`) and the note text.

2. Confirm a screenshot is actually attached to this conversation. If none is, say so and stop —
   suggest either attaching one or running
   `meridian enrich <feat-id> <path> --note "…"` with an explicit path.

3. **Look at the image.** Write 2–5 sentences of concrete observation:
   - the chart/page type and its title
   - axis labels and their ranges, or the fields and values visible
   - what specifically looks wrong: empty tiles, absurd ranges, missing series, error text
   - what the labels themselves tell you about the metric definition — e.g. an `Avg` prefix means a
     ratio is being averaged across entities rather than aggregated, and a "yield" running to four
     digits is not a percentage. These are readings of what is on screen, so they belong here.

   The line to hold: describe *what is shown and what it means*, not *why the pipeline produced it*.
   "Both axes are labelled Avg, so a ratio is being averaged per entity" is an observation — keep it.
   "The join must be fanning out" is a guess about code you cannot see — leave it out, because a
   guess embedded as fact pollutes the corpus for every later `/ask`.

4. Write a sidecar file to a scratch path (NOT into `sources/` — the CLI owns that directory).
   Use exactly this format:

   ```markdown
   # Screenshot notes — <image-name>

   - Image: sources/<image-name>
   - Feature: FEAT-NNN
   - Captured: <today, ISO>
   - Described by: <your model name> (agent)

   ## Notes

   <the user's note, verbatim>

   ## Visual reading

   <your 2–5 sentences from step 3>
   ```

   The image name is unknown until the CLI slugifies it, so a placeholder stem is fine — the CLI
   rewrites the header when it saves the sidecar.

5. Ingest it:
   ```
   meridian enrich <feat-id> --latest-screenshot --note-file <scratch-sidecar-path>
   ```
   The CLI prints which screenshot it resolved and how old it is. Do **not** pass `--vision`: that
   flag is the Ollama fallback for headless runs, and your reading is already better.

6. Read the CLI output and report back:
   - the resolved image filename and its age (so the user can catch a wrong pick immediately)
   - the sidecar filename and the number of chunks embedded
   - any warning the CLI printed

7. If the CLI reports the screenshot is older than a few minutes and the user just took one, say so
   plainly — the newest file in the screenshot directory may not be the image they attached. Offer
   the explicit-path form as the fix.

## Output format

```
✓ FEAT-006 ← screenshot-2026-08-18-15-40-59.png + …notes.md (3 chunks embedded)
  Resolved: screenshot-2026-08-18-15-40-59.png (just now) from ~/Desktop
  Reading:  <one-line summary of what you saw>
```

Then one line on what is now searchable, e.g. *"`/ask` will surface this for questions about
unbounded yield metrics."*

---

Do not describe an image you cannot see. Do not write the sidecar into `sources/` yourself. Do not
pass `--vision` when you have already read the image.
