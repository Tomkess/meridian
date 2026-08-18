# 006 — Screenshots: the CLI captures, the agent describes

**Status:** Accepted  
**Date:** 2026-08-18  
**Context:** FEAT-006 (screenshot ingest); affects `meridian enrich`, `meridian/capture.py`, `/meridian:enrich`

## Decision

Screenshot ingest splits along a capability line discovered empirically: **the CLI captures the file,
the agent describes the pixels.** An image attached in a Claude Code chat reaches the agent as base64
with no filesystem path, and Claude Code keeps no on-disk attachment cache — so an agent can see an
image it cannot copy. The file *is* on disk, in the OS screenshot directory, which is what
`--latest-screenshot` reads. Conversely, an agent that can see the screenshot reads axis labels,
ranges, and anomalies far more accurately than a 6 GB local vision model, so the prose comes from the
agent via `--note-file` and Ollama `--vision` is demoted to a headless fallback. Two rules follow:
`ollama_vision_model` defaults to empty, and an existing `## Visual reading` section is never
overwritten — not by the local model, and never regenerated on `meridian index`.

## Alternatives Considered

| Option | Pros | Cons |
|---|---|---|
| Chosen: CLI captures (`--latest-screenshot`), agent describes (`--note-file`) | Uses the file that already exists; best-quality reading; no new dependency; works headless via `--vision` | Newest-file heuristic can pick the wrong screenshot; macOS-centric |
| Agent writes the image bytes itself | One step, no capture heuristics | Impossible — the agent has no path and cannot reproduce exact bytes; verified, not assumed |
| Ollama vision as the primary describer | Fully local and deterministic pipeline | Misreads dashboard values; needs a ~6 GB model pulled on every machine; worse than a describer already in the loop |
| OCR (tesseract) | Extracts on-screen text exactly | New system dependency; gives strings, not the reading of *what looks wrong* |
| Burn annotations into the pixels (Pillow) | Notes travel inside the image | Nothing searchable; adds an image dependency; destroys the original |
| Multimodal image embeddings | True image similarity search | LanceDB schema migration; no answer to "why is this broken", which is the actual use case |

## Consequences

- **Positive:** the corpus gains visual evidence with prose good enough for `/ask` to answer from;
  zero new runtime dependencies (`subprocess` + `httpx`); the `## Visual reading` section is
  author-agnostic with `Described by:` attribution, so readers can weigh it; the long-standing bug
  where a PNG passed to `enrich` embedded garbage bytes is now a clear error.
- **Negative / trade-offs:** `--latest-screenshot` can resolve the wrong image, mitigated by always
  printing the resolved filename and age and warning past 10 minutes, never by refusing; capture is
  macOS-first (`defaults`, `osascript`), other platforms fall back to a directory chain or an explicit
  path; PNGs committed under `specs/` add repo weight.
- **Neutral:** screenshot chunks key on the sidecar filename, so re-ingest replaces rather than
  duplicates — conditional on `slug_image_name()` staying deterministic; `reindex_all()` now globs
  `*.notes.md` alongside `*.txt`.

## Revisit Trigger

Revisit if Claude Code starts exposing a filesystem path (or a stable cache) for chat attachments —
that would let the skill hand the CLI an exact file and retire the newest-file heuristic. Also
revisit if local multimodal models become accurate enough on dense dashboard screenshots to serve as
the primary describer, or if agents prove unable to locate regions from prose alone, which would
reopen the pixel-annotation option.
