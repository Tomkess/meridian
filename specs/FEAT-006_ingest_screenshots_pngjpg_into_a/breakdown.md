## Technical Breakdown — FEAT-006: Ingest annotated screenshots into a feature's research corpus

### Components

| Component | What it does | New or existing? | Effort (S/M/L) |
|---|---|---|---|
| `IMAGE_SUFFIXES` + `is_image_source(source: str) -> bool` (`meridian/enrich.py`, new section after `_is_url`, ~line 39) | `frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})`; returns `False` for URLs (URL ingest stays text-only), else `Path(source).expanduser().suffix.lower() in IMAGE_SUFFIXES`. Single predicate used by the CLI dispatcher, `extract_text`'s guard, `ingest_screenshot`, and the screenshot-directory scan. | New | S |
| `extract_text()` image guard (`meridian/enrich.py:66-76`) | Insert between the `.pdf` branch (line 73-74) and the `read_text` fallback (line 76): `if is_image_source(source): raise RuntimeError(...)` naming `--note` / `--note-file`. Closes the garbage-bytes bug — an image can no longer reach `path.read_text(errors="replace")`. | Existing (modified) | S |
| `screenshot_dir() -> Path` (new module `meridian/capture.py`) | Resolution chain: on `sys.platform == "darwin"` run `subprocess.run(["defaults", "read", "com.apple.screencapture", "location"], capture_output=True)` — a non-zero exit or a stderr "does not exist" means the key is unset, **not** an error (verified: this box returns exactly that). Then fall back to `~/Desktop`, then `~/Pictures/Screenshots`. Returns the first existing directory; raises `RuntimeError` naming every directory tried when none exists. | New | S |
| `latest_screenshot(directory: Path \| None = None) -> tuple[Path, float]` (`meridian/capture.py`) | Scans `directory or screenshot_dir()` non-recursively for files whose suffix is in `IMAGE_SUFFIXES`, returns `(newest_path, age_seconds)` by `st_mtime`. Raises `RuntimeError` naming the searched directory when it holds no images. Age is returned rather than judged — the caller decides what to warn about. | New | S |
| `clipboard_image(dest: Path) -> Path` (`meridian/capture.py`) | `osascript -e 'clipboard info'` first; if the output contains no image class (`PNGf`, `TIFF`, `class PNGf`), raise `RuntimeError("Clipboard holds no image…")` — verified necessary, a text clipboard reports only `«class HTML»`/`«class utf8»`/`string`. Otherwise `osascript -e 'set f to open for access POSIX file "…" with write permission' …` writing `the clipboard as «class PNGf»` to `dest`. macOS-only; non-darwin raises immediately with "use --latest-screenshot or an explicit path". | New | M |
| `slug_image_name(name: str) -> str` (`meridian/enrich.py`) | Deterministic, pure: lowercase the stem, drop the filler word `at`, replace runs of non-alphanumerics with `-`, strip leading/trailing `-`, collapse repeats, preserve the lowercased suffix. `Screenshot 2026-08-18 at 15.40.59.png` → `screenshot-2026-08-18-15-40-59.png`. Determinism is load-bearing: the slug becomes `source_name`, so a stable slug is what makes `upsert_chunks`' delete-then-add replace instead of duplicate. | New | S |
| `render_sidecar(image_name, feat_id, notes, reading=None, described_by=None) -> str` (`meridian/enrich.py`) | Builds the `.notes.md` text: provenance header (`Image:`, `Feature:`, `Captured:`, optional `Described by:`), `## Notes`, optional `## Visual reading`. Author-agnostic — the same renderer serves an agent-written reading and an Ollama caption. Pure function, no I/O. | New | S |
| `parse_sidecar(text) -> tuple[str, str \| None, str \| None]` (`meridian/enrich.py`) | Inverse of `render_sidecar`: returns `(notes, reading, described_by)`. Used when `--note-file` points at a `*.notes.md` file so re-ingest does not nest headers inside `## Notes` and chunk counts stay stable. Falls back to `(text.strip(), None, None)` for a plain note file with no `## Notes` heading. The `reading is not None` case is what suppresses the Ollama call under `--vision`. | New | S |
| `caption_image(path, model, base_url="http://localhost:11434") -> str` (`meridian/enrich.py`) | **Fallback describer**, headless use only. `POST /api/generate` with base64 image; raises `RuntimeError` with actionable text on connect error, timeout, or 404/model-missing. Never called on reindex, and never called when the sidecar already carries a `## Visual reading`. | New | M |
| `save_screenshot(feat_dir, image, sidecar_text, slug) -> tuple[str, str]` (`meridian/enrich.py`) | `shutil.copy2` the image into `feat_dir/sources/<slug>` byte-identical (skip when `src == dest`), write `<slug-stem>.notes.md` next to it, return `(image_name, sidecar_name)`. Deliberately does **not** reuse `save_source` (`enrich.py:243-260`) because that writes a `<stem>.txt` sibling for every non-`.txt` source — for a PNG that sibling is exactly the corruption we are removing. | New | S |
| `notes_chunks(sidecar_text, image_ref, feat_id) -> list[str]` (`meridian/enrich.py`) | The one chunking path shared by ingest and reindex: `chunk_text(sidecar_text)`; if that returns `[]` and the text is non-empty, fall back to `[sidecar_text.strip()]` (short screenshot notes are commonly < the 80-char floor at `enrich.py:87`); then prefix every chunk with `f"[Screenshot {image_ref} · {feat_id}]\n"` so *each* chunk carries `sources/<slug>.png`. Determinism of this function is what makes the `meridian index` chunk-count parity AC hold. | New | M |
| `ingest_screenshot(cfg, feat_id, image, note=None, note_file=None, vision=False) -> dict` (`meridian/enrich.py`, alongside `enrich_feature` at line 265) | The orchestrator: resolve feat dir → resolve note text and any existing reading via `parse_sidecar` → optional Ollama caption only when no reading exists (degrading on failure) → render + save sidecar + copy image under its slug → chunk → `embed` → `upsert_chunks` → append **both** refs to `sources:` frontmatter. Returns `{"feat_id", "source", "sidecar", "chunks", "described_by", "warnings"}`. | New | M |
| `reindex_all()` glob widening (`meridian/enrich.py:305-327`, glob at line 319) | Iterate `sorted([*sources_dir.glob("*.txt"), *sources_dir.glob("*.notes.md")])`; for `*.notes.md` route through `notes_chunks(text, image_ref, feat_id)` where `image_ref` is parsed from the header's `- Image:` line (fallback: `sources/<stem>` with the sibling image's real suffix). Readings are read from the file, never regenerated — no vision call, sidecar left byte-unchanged. | Existing (modified) | M |
| `enrich` CLI command (`meridian/cli.py:507-535`) | `source` becomes optional; five new options (`--note`, `--note-file`, `--latest-screenshot`, `--from-clipboard`, `--vision`), mutual-exclusion validation, resolved-file reporting with age, interactive note prompt, warning rendering, updated docstring/help. | Existing (modified) | M |
| `/meridian:enrich` skill — `meridian/skills/commands/enrich.md` **and** byte-identical `.claude/commands/meridian/enrich.md` | Takes `<feat-id> "<note>"` with a screenshot attached in chat. Steps: look at the attached image; write `<scratch>/<slug>.notes.md` via the sidecar format with the user's note under `## Notes` and its own reading under `## Visual reading` + `Described by: <model> (agent)`; run `meridian enrich <feat> --latest-screenshot --note-file <sidecar>`; report the resolved image filename and chunk count. Requires `model:` frontmatter (`test_models.py`) and both copies identical (`test_skill_sync.py`). | New | M |
| `ollama_vision_model` config key (`meridian/config.py:7-19`, `:44-52`) | New dataclass field + `meridian_section.get(...)`, default `""`. | Existing (modified) | S |
| Docs: `meridian help` (cli.py:1134-1135 CLI table, cli.py:1224-1235 config block, cli.py:1256 layout note), `meridian init` toml template (cli.py:841-851), `README.md:148` + Ollama setup at `README.md:74-80`, `CLAUDE.md` CLI **and slash-command** tables | Keep the skill↔CLI contract green and make the capture flags discoverable. | Existing (modified) | S |

### Data Model

**Sidecar file — `specs/FEAT-006_.../sources/<slug>.notes.md`** (human-editable, source of truth for re-embedding):

```markdown
# Screenshot notes — screenshot-2026-08-18-15-40-59.png

- Image: sources/screenshot-2026-08-18-15-40-59.png
- Feature: FEAT-006
- Captured: 2026-08-18
- Described by: claude-opus-5 (agent)

## Notes

Earnings-yield scatter is unusable — points blow the axis out to -1750/+4k

## Visual reading

GoodData scatter insight titled "Earnings Yield vs FCF Yield". X axis "Avg Earnings Yield"
spans -1750 to ~+60; Y axis "Avg FCF Yield" spans -2k to 4k. Nine points; six cluster at
(≈0, ≈0), four outliers dominate the scale: (-1600, -1250), (-320, +3400), (-165, -200),
(+60, +400). Neither metric is bounded like a ratio, consistent with an absolute amount or a
near-zero denominator on a handful of entities.
```

- `- Described by:` records the author of `## Visual reading`: `claude-opus-5 (agent)` on the skill
  path, `ollama:<model>` on the `--vision` path, absent when there is no reading. It is the field the
  "never overwrite an agent reading" rule keys on, together with the presence of the section itself.
- `## Visual reading` replaces the earlier `## Vision caption` naming — the section is
  author-agnostic, so nothing in the format changes when the describer changes.
- Header block is part of the embedded text (prefixed onto every chunk by `notes_chunks`), which is
  what lets a retrieving agent open the exact image from a search hit.
- `Captured:` uses the *ingest* date (`datetime.date.today().isoformat()`), matching the `_today()`
  convention in `meridian/specs.py:39`. Written once and preserved on re-ingest when the existing
  sidecar is parsed via `--note-file`, so reindex output stays byte-stable.

**Filename slugs.** Screenshot filenames from macOS contain spaces and dots
(`Screenshot 2026-08-18 at 15.40.59.png`); clipboard captures have no name at all. Both are
normalised before touching disk or LanceDB:

| Source | Stored as |
|---|---|
| `Screenshot 2026-08-18 at 15.40.59.png` | `screenshot-2026-08-18-15-40-59.png` |
| clipboard | `clipboard-2026-08-18T161221.png` |
| `~/shots/kpi.png` | `kpi.png` (already clean) |

**Spec frontmatter**: no new fields. `sources:` gains **two** entries per screenshot —
`sources/<slug>.png` and `sources/<slug>.notes.md` — appended with the same idempotent
`if ref not in sources_list` guard used at `enrich.py:291-296`, written through `load_spec`/`save_spec`
(`meridian/specs.py:64-90`; `save_spec`'s no-op-when-unchanged branch at `:78-86` means a repeat
ingest does not bump `updated`).

**LanceDB schema** (`enrich.py:169-175`): **unchanged** — no migration, no new column, no image
vectors. New *usage* only: `source_name` holds the sidecar filename (`<slug>.notes.md`, never the
image), so the existing `upsert_chunks` delete-then-add predicate (`enrich.py:192-197`) gives the
"edit sidecar, re-run, chunks replaced not duplicated" AC for free — conditional on `slug_image_name`
being deterministic. The image itself has no row in `chunks`; it is referenced from chunk `text`.

**`.meridian.toml` → `[meridian]`**:

```toml
ollama_vision_model = ""   # optional fallback describer for `meridian enrich --vision`
```

`MeridianConfig` gains `ollama_vision_model: str = ""`. Because `root: Path` has no default, the new
field must be declared **last** in the dataclass (`config.py:19` onward) and given the `""` default so
the only two construction sites (`config.py:45` and the `mock_cfg` fixture in `tests/conftest.py`)
keep working; `load_config` reads `meridian_section.get("ollama_vision_model", "")`.

**Empty default is settled** (spec Open Questions). With the agent path primary, a concrete default
would only produce "model not found" warnings on machines that never pull a multimodal model.
`--vision` with no configured model emits one actionable warning naming the config key and still
ingests the note.

### Integration Points

**CLI — `meridian/cli.py:507`:**

```python
@app.command()
def enrich(
    feature_id: str = typer.Argument(..., help="Feature ID (e.g. feat-007)"),
    source: str | None = typer.Argument(
        None, help="Path to PDF/text/image file or URL (omit with --latest-screenshot/--from-clipboard)"),
    note: str | None = typer.Option(
        None, "--note", "-n",
        help="Note describing the screenshot (required for image sources)"),
    note_file: Path | None = typer.Option(
        None, "--note-file",
        help="Read the note (and any existing visual reading) from a sidecar file"),
    latest_screenshot: bool = typer.Option(
        False, "--latest-screenshot",
        help="Ingest the newest image from the OS screenshot directory"),
    from_clipboard: bool = typer.Option(
        False, "--from-clipboard",
        help="Ingest the image currently in the clipboard (macOS)"),
    vision: bool = typer.Option(
        False, "--vision/--no-vision",
        help="Fallback: describe the image with the configured Ollama vision model"),
):
    """Ingest a PDF, URL, text file, or annotated screenshot into a feature's research corpus."""
```

Validation and dispatch, replacing the single `enrich_feature` call at `cli.py:517`:

1. **Argument validation** (before any I/O): `--latest-screenshot` and `--from-clipboard` are mutually
   exclusive with each other and with a positional `source`; exactly one source of image bytes must be
   given. No source at all and no capture flag → the current typer "missing argument" behaviour.
2. **Capture resolution** — `--latest-screenshot` → `latest_screenshot()`; print
   `Using <name> (<n>m old) from <dir>` **always**, plus a yellow `[yellow]⚠[/yellow] screenshot is <n>m old`
   when `age > 600s`. `--from-clipboard` → `clipboard_image(tmp)` into the session temp dir, then treated
   as a normal image path. Both raise `RuntimeError`, caught into red + `Exit(1)` in the same shape as
   `cli.py:518-523`.
3. **Non-image path** — if `not is_image_source(resolved)`: warn if note/vision flags were passed, then
   call `enrich_feature(cfg, feature_id, source)` exactly as today. **No behavioural change on the
   PDF/URL/text paths.**
4. **Note resolution** for image paths: `--note-file` (read, then `parse_sidecar`) → `--note` →
   interactive prompt guarded by `sys.stdin.isatty()`. Non-tty → red
   `An image needs notes. Pass --note "…" or --note-file <path>.` + `Exit(1)`. Tty →
   `typer.prompt("Note describing this screenshot", default="")`; empty/whitespace → `Aborted — nothing
   was written.` + `Exit(1)` **before** any file copy or frontmatter write.
5. `console.status(...)` wraps `ingest_screenshot(...)`.
6. On success: print each `result["warnings"]` in yellow, then
   `✓ FEAT-006 ← screenshot-2026-08-18-15-40-59.png + …notes.md (N chunks embedded)`, appending
   `· described by <x>` when `result["described_by"]` is set. Keep the existing `chunks == 0` yellow
   branch (`cli.py:526-530`) as a net.

**macOS capture seams** (`meridian/capture.py`, `subprocess` only — no new dependency):

```python
# screenshot dir; a missing key is normal, not an error
subprocess.run(["defaults", "read", "com.apple.screencapture", "location"],
               capture_output=True, text=True, timeout=5)

# clipboard class probe, then extraction
subprocess.run(["osascript", "-e", "clipboard info"], capture_output=True, text=True, timeout=5)
```

Both are wrapped so `FileNotFoundError` (binary absent, non-macOS) and `subprocess.TimeoutExpired`
surface as `RuntimeError` with a message pointing at `--latest-screenshot` or an explicit path.

**Ollama vision API — `caption_image`,** reusing the module's existing `httpx` import (`enrich.py:9`):

```python
resp = httpx.post(
    f"{base_url}/api/generate",
    json={
        "model": model,
        "prompt": ("Describe this screenshot of a data application in 2-4 sentences. "
                   "State visible labels, numbers, and anything that looks broken or empty. "
                   "Do not speculate about causes."),
        "images": [base64.b64encode(path.read_bytes()).decode("ascii")],
        "stream": False,
    },
    timeout=180,
)
```
Response: `data["response"].strip()`. Failure mapping (all `RuntimeError`, caught by
`ingest_screenshot` and demoted to `warnings`): `httpx.ConnectError` → "Cannot connect to Ollama at …
Start it with: ollama serve"; `httpx.TimeoutException` → "Vision model timed out"; `404` or a body
containing `not found` → "Vision model '<model>' is not pulled. Run: ollama pull <model>". Mirrors the
friendly-error style already in `embed` (`enrich.py:141-153`).

**Describer precedence inside `ingest_screenshot`** — one rule, three cases:

| Sidecar has `## Visual reading`? | `--vision`? | Result |
|---|---|---|
| yes | either | existing reading kept verbatim, no Ollama call, warning when `--vision` was asked for |
| no | yes | `caption_image` attempted; failure → warning, ingest continues |
| no | no | no reading section; notes-only ingest |

**Skill path — `/meridian:enrich`:** the skill writes the sidecar into the session scratchpad, not
into `sources/` (the CLI owns `sources/`), then passes it with `--note-file`. Because the CLI copies
the image under its slug and rewrites the sidecar next to it, the skill does not need to know the
final filename in advance — it reads it back from the CLI's success line. Both skill copies must be
written in the same commit (`test_skill_sync.py`), and `enrich.md` needs `model:` frontmatter
(`test_models.py`) — use `claude-sonnet-5`, matching `ask.md`/`research.md`.

**Pipeline reuse:** `chunk_text` (`:81`), `embed` (`:105`, with its ASCII-sanitize + legacy-endpoint
fallbacks), `upsert_chunks` (`:179`, incl. the B1 quote escaping), `search_similar` (`:211`),
`semantic_search`/`format_results` (`meridian/search.py:41,89`) are used unmodified — `/ask` and
`/research` pick screenshots up with zero skill changes because the image path is inside chunk `text`,
and `format_results` already prints `[<feature>] <slug>.notes.md chunk 0`.

**Docs to update** (flag references in `CLAUDE.md` are *asserted* by
`tests/test_contracts.py::TestFlagsExist`, so this is test-enforced, not cosmetic):
- `meridian/cli.py:1134` — rows for `meridian enrich feat-007 --latest-screenshot --note "what is wrong"`
  and the `--vision` fallback.
- `meridian/cli.py:1228` + `meridian init` template (`cli.py:845-846`) — `ollama_vision_model = ""`.
- `meridian/cli.py:1256` — extend the `sources/` layout line to "raw PDFs, text, downloaded pages,
  screenshots + .notes.md sidecars".
- `README.md:148` — CLI table rows; `README.md:74-80` — `--vision` needs a multimodal model pulled.
- `CLAUDE.md` — CLI block gets the capture flags; the **slash-command table** gets `/enrich`.

### Test Strategy

`tests/test_enrich.py` — pure units, no network, no LanceDB:

- `TestIsImageSource`: `.png/.jpg/.jpeg/.webp/.gif` (incl. upper-case `.PNG`) → `True`; `.pdf/.txt/.md`
  and `https://…/x.png` → `False`.
- `TestExtractTextImageGuard::test_png_raises_runtime_error_naming_note_flag` — a 4-byte
  `b"\x89PNG"` file raises `RuntimeError` matching `--note`. Regression lock for the garbage-bytes bug.
  Sibling `test_txt_still_read_as_text` guards the no-regression AC at unit level.
- `TestSlugImageName`: `"Screenshot 2026-08-18 at 15.40.59.png"` → `"screenshot-2026-08-18-15-40-59.png"`;
  already-clean names pass through unchanged; suffix case normalised; called twice → identical output
  (determinism, the prerequisite for chunk replacement); no leading/trailing/repeated `-`.
- `TestRenderSidecar` / `TestParseSidecar`: round-trip render→parse; header carries image path,
  feature id, ISO date; `## Visual reading` + `- Described by:` present only when a reading is passed;
  header-less plain text parses as notes-only with `reading is None`.
- `TestNotesChunks`: every chunk contains the image ref; a 30-char note yields exactly one chunk (the
  sub-80-char fallback); a 600-word sidecar yields >1 chunk, all carrying the ref; two calls on
  identical input return identical lists.
- `TestCaptionImage` (mocked `httpx.post`, mirroring the existing `TestEmbed`): 200 → `data["response"]`;
  `httpx.ConnectError` → `RuntimeError` matching `ollama serve`; `httpx.ReadTimeout` → matching
  `timed out`; 404 → matching `ollama pull`.

`tests/test_capture.py` (new file) — `subprocess.run` patched, `tmp_path` directories:

- `TestScreenshotDir`: `defaults` returning a custom path → that path; `defaults` exiting non-zero (the
  "does not exist" case observed on this box) → `~/Desktop`; `~/Desktop` absent → `~/Pictures/Screenshots`;
  none present → `RuntimeError` naming every directory tried; non-darwin skips the `defaults` call entirely.
- `TestLatestScreenshot`: three images with staggered `st_mtime` → newest returned with a plausible age;
  non-image files (`.txt`, `.pdf`) ignored; empty directory → `RuntimeError` naming the directory;
  subdirectories not descended into.
- `TestClipboardImage`: `clipboard info` output with no image class → `RuntimeError` matching
  `no image` (this is the observed real-world state, so it is the primary case); output containing
  `«class PNGf»` → proceeds and writes `dest`; `FileNotFoundError` from `osascript` → `RuntimeError`
  pointing at `--latest-screenshot`; non-darwin → immediate `RuntimeError`.

`tests/test_enrich_integration.py` — real filesystem + real LanceDB, `meridian.enrich.embed` patched,
`mock_cfg` fixture:

- `TestIngestScreenshot::test_image_copied_byte_identical` — `sha256` of source == `sha256` of
  `sources/<slug>.png`, **and** `not (sources/"<slug>.txt").exists()` (proves `save_source`'s `.txt`
  sibling path was bypassed). AC-1.
- `test_spaced_filename_is_slugified` — ingesting `Screenshot 2026-08-18 at 15.40.59.png` yields
  `sources/screenshot-2026-08-18-15-40-59.png` + `…notes.md`, and both are the values in frontmatter and
  in LanceDB `source_name`. AC "slug".
- `test_sidecar_contains_note_and_chunks_reported`, `test_chunk_is_retrievable_and_carries_image_path`
  (via `search_similar` with `feat_id_filter`), `test_frontmatter_lists_both_refs`. AC-1/2/3.
- `test_missing_note_raises` — `note=None, note_file=None` raises (library half of the refusal AC).
- `test_agent_reading_preserved_verbatim` — `--note-file` with a sidecar carrying `## Visual reading` +
  `Described by: claude-opus-5 (agent)`: section text byte-identical afterwards, `described_by`
  round-trips, reading text present in stored chunks.
- `test_vision_skipped_when_reading_exists` — same input plus `vision=True` and a `MagicMock` on
  `caption_image`: `call_count == 0`, warning says the caption was skipped.
- `test_vision_caption_persisted_and_embedded` — patched `caption_image` sentinel with
  `ollama_vision_model="qwen2.5vl:7b"`: sidecar gains `## Visual reading`, `- Described by: ollama:qwen2.5vl:7b`,
  sentinel present in chunk text, `result["described_by"]` set.
- `test_vision_failure_degrades_to_warning` — `caption_image` raising: chunks ≥ 1, image + sidecar on
  disk, no reading section, warning mentions Ollama.
- `test_unconfigured_vision_model_warns_and_ingests` — `--vision` with `ollama_vision_model == ""`:
  warning names the config key, ingest succeeds.
- `test_reingest_from_edited_sidecar_replaces_chunks` — ingest, edit `## Notes`, re-ingest with
  `note_file=<sidecar>`: row count unchanged, new wording retrievable, old wording gone.
- `TestReindexAll::test_notes_sidecar_reindexed_with_stable_count` — screenshot + one `doc.txt`, record
  row count, `reindex_all`, assert equal count, `sources == 2`, screenshot row survives.
- `test_reindex_ignores_non_notes_markdown` — a `README.md` and a `summaries/brief.md` in place are not
  indexed (glob over-match risk).
- `test_reindex_does_not_regenerate_reading` — `MagicMock` on `caption_image`, `reindex_all` over a
  captioned sidecar: `call_count == 0` and the sidecar bytes are unchanged.

`tests/test_cli.py` — real binary via the `run()` helper and `proj` fixture, plus `CliRunner` where a
tty or patched capture is needed:

- `TestEnrichScreenshot::test_missing_note_non_interactive_exits_nonzero` — subprocess run of
  `enrich feat-001 <png>`: non-zero exit, output naming both `--note` and `--note-file`.
- `test_missing_note_writes_nothing` — after that run, `sources/` empty/absent and `sources:` still `[]`.
- `test_empty_prompt_aborts` / `test_prompted_note_is_used` — `CliRunner` with `sys.stdin.isatty`
  monkeypatched `True` and `meridian.enrich.embed` patched; empty input aborts writing nothing, typed
  input becomes the note.
- `TestLatestScreenshotFlag::test_prints_resolved_name_and_age` — `meridian.capture.latest_screenshot`
  patched to a `tmp_path` image: stdout contains the resolved filename and an age; the ingested
  filename matches.
- `test_stale_screenshot_warns_but_proceeds` — patched age of 3600s: warning present, exit 0.
- `test_no_screenshots_exits_nonzero` — patched `latest_screenshot` raising: non-zero exit, output names
  the searched directory.
- `test_mutually_exclusive_flags` — `--latest-screenshot` together with a positional source, and with
  `--from-clipboard`: non-zero exit, message naming the conflict, nothing written.
- `test_clipboard_without_image_exits_nonzero` — patched `clipboard_image` raising: non-zero exit,
  message about no image in the clipboard.
- `test_pdf_path_unaffected` + `test_note_flag_on_pdf_warns_but_succeeds` — existing PDF/URL/text tests
  stay green unmodified.
- Extend `TestHelp` expectations with `--note`, `--note-file`, `--latest-screenshot`,
  `--from-clipboard`, `--vision` in `meridian enrich --help`.

`tests/test_skill_sync.py`, `tests/test_models.py`, `tests/test_contracts.py`, `tests/test_skill_consistency.py`
— no new test code, but all four gain cases automatically and must pass: byte-parity of the two
`enrich.md` copies, its `model:` frontmatter, the five new `(enrich, --flag)` pairs derived from
`CLAUDE.md`, and structural consistency of the new skill. A doc-only typo (`--notes`) must fail
`test_contracts.py`.

`tests/test_specs.py` / `tests/test_spec_lock.py` — untouched; note in the PR that `ingest_screenshot`
updates frontmatter through the same unlocked `load_spec`/`save_spec` pair as `enrich_feature`
(`enrich.py:289-296`) rather than `transition_spec`, so it inherits, and does not worsen, the existing
concurrency posture.

Manual verification (once, on the dev machine — cannot run in CI):

1. Cmd+Shift+4 a broken dashboard tile, then `meridian enrich feat-006 --latest-screenshot --note "…"`
   → confirm the resolved filename + age line, the slugified name in `sources/`, and the chunk count.
2. Same screenshot attached in Claude Code + `/meridian:enrich feat-006 "…"` → confirm the sidecar
   carries both the note and an agent visual reading, and that `Described by:` names the agent.
3. `meridian search "<phrase from the reading>"` → hit shows `<slug>.notes.md` and its text carries
   `sources/<slug>.png`; open that path.
4. `ollama pull <vision-model>` + set `ollama_vision_model`, then re-ingest a *fresh* screenshot with
   `--vision` and no reading in the sidecar → caption lands with `ollama:<model>` attribution. Stop
   Ollama and repeat → warning, ingest still succeeds.
5. `meridian index` → reported chunk total matches the pre-rebuild total and `git diff` on the sidecar
   is empty.

### Total Effort Estimate

| Component | Effort |
|---|---|
| `is_image_source` + `IMAGE_SUFFIXES` | S |
| `extract_text()` image guard | S |
| `slug_image_name` | S |
| `screenshot_dir` + `latest_screenshot` (`meridian/capture.py`) | S |
| `clipboard_image` (osascript class probe + extraction) | M |
| `render_sidecar` / `parse_sidecar` (author-agnostic reading section) | S |
| `caption_image` (Ollama fallback + error mapping) | M |
| `save_screenshot` | S |
| `notes_chunks` (prefixing + short-note fallback + determinism) | M |
| `ingest_screenshot` orchestrator (incl. describer precedence) | M |
| `reindex_all` glob widening + sidecar routing | M |
| CLI options, mutual exclusion, capture reporting, prompt, warnings | M |
| `/meridian:enrich` skill (both copies, model frontmatter) | M |
| `ollama_vision_model` config plumbing | S |
| Docs (help, init template, README, CLAUDE.md CLI + slash table) | S |
| Tests (≈40 cases across 4 files, one of them new) | L |

**Overall: M — 2.5 days, still inside the `s` appetite (1–3 days).** The capture layer and the skill
add roughly half a day over the original estimate; no new runtime dependency (`subprocess` + `httpx`
only), no LanceDB migration, no change to the three existing ingest paths. Cost centres: the test
matrix, slug determinism, describer precedence, and the non-interactive/empty-note refusal writing
*nothing*.

### Implementation Order

1. **Config plumbing** — `ollama_vision_model: str = ""` as the last field of `MeridianConfig`
   (`meridian/config.py:19`), read in `load_config` (`:44-52`), added to the `meridian init` template
   (`cli.py:845-846`) and the `meridian help` config block (`cli.py:1228`). *Verifies:* existing suite
   green (only two construction sites).
2. **Image detection + `extract_text` guard** — `IMAGE_SUFFIXES`, `is_image_source`, and the
   `RuntimeError` branch in `extract_text` (`enrich.py:73-76`), tests first. Smallest change that kills
   the garbage-bytes bug.
3. **`slug_image_name`** — pure, deterministic, with the macOS-screenshot fixture as the headline case.
   Must land before anything writes into `sources/`, because the slug is the LanceDB `source_name`.
4. **`meridian/capture.py`: `screenshot_dir` + `latest_screenshot`** — the resolution chain, the
   "`defaults` key missing is normal" branch, and `(path, age)`. Independent of everything in
   `enrich.py`; fully unit-testable with patched `subprocess.run`.
5. **Sidecar render/parse** — `render_sidecar` / `parse_sidecar` with the `## Visual reading` +
   `Described by:` fields and round-trip tests. Pure functions, no I/O.
6. **`notes_chunks`** — chunk + per-chunk image-ref prefix + sub-80-char fallback + determinism tests.
   Must precede anything that stores chunks: both ingest and reindex depend on it being the single
   chunking path.
7. **`save_screenshot`** — byte-identical `copy2` under the slug + sidecar write; test asserts no
   `.txt` sibling.
8. **`caption_image`** — Ollama `/api/generate` with the four mocked failure branches. Independent of
   steps 5-7; must precede step 9.
9. **`ingest_screenshot`** — wire steps 3/5/6/7/8 together, including the three-case describer
   precedence table. Add the integration tests for copy fidelity, slugging, retrieval, frontmatter,
   agent-reading preservation, vision success/failure/skip, and re-ingest replacement.
10. **`reindex_all` widening** — `*.notes.md` included, routed through `notes_chunks`, image ref parsed
    from the header, no describer call. Add parity, over-match, and no-regeneration tests.
11. **CLI surface** — the five options, mutual-exclusion validation, `--latest-screenshot` resolution
    reporting with age + staleness warning, tty-guarded prompt, abort-writes-nothing, warning/success
    output. Add the CLI tests; confirm existing PDF/URL/text CLI tests untouched.
12. **`clipboard_image` + `--from-clipboard`** — deliberately last of the capture work: it is the
    fragile, secondary path, and `--latest-screenshot` already delivers the workflow. Ship the
    "clipboard holds no image" guard even if extraction proves flaky.
13. **`/meridian:enrich` skill** — write `meridian/skills/commands/enrich.md` with `model: claude-sonnet-5`
    frontmatter and copy it byte-identically to `.claude/commands/meridian/enrich.md` in the same commit.
    Run `test_skill_sync.py`, `test_models.py`, `test_skill_consistency.py`.
14. **Docs + contract sweep** — `cli.py:1134` help rows, `cli.py:1256` layout line, `README.md:148` and
    `:74-80`, `CLAUDE.md` CLI block **and slash-command table**. Then
    `ruff check . && mypy meridian/ && pytest` — `test_contracts.py` must collect and pass the five new
    `(enrich, --flag)` pairs.
15. **ADR** — `/decision` recording: capture belongs to the CLI because chat attachments carry no path;
    description belongs to the agent with Ollama `--vision` as headless fallback;
    `ollama_vision_model` defaults to empty; an existing `## Visual reading` is never overwritten; and
    readings are never regenerated on reindex.
16. **Manual pass** (the 5 steps above) on a real broken-dashboard screenshot, then
    `meridian close feat-006 --status done` and review `spec.md` for drift.
