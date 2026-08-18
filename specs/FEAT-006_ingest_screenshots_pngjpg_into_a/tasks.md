## Tasks — FEAT-006: Ingest annotated screenshots into a feature's research corpus

> Appetite: `s`  ·  Generated: 2026-08-18 (revised after capture-path prototyping)

- [x] 1. Add `ollama_vision_model: str = ""` as the last field of `MeridianConfig` (`meridian/config.py:7-19`) and read it in `load_config` via `meridian_section.get("ollama_vision_model", "")` (`meridian/config.py:44-52`).
       Pre: none
- [x] 2. Add `ollama_vision_model = ""` to the `.meridian.toml` block written by `meridian init` (`meridian/cli.py:841-851`) and to the config table printed by `meridian help` (`meridian/cli.py:1224-1235`).
       Pre: task 1 complete
- [x] 3. Write tests confirming `load_config` defaults `ollama_vision_model` to `""` and that both existing `MeridianConfig` construction sites (`config.py:45`, `tests/conftest.py` `mock_cfg`) still work.
       Pre: task 1 complete
- [x] 4. Add `IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})` and `is_image_source(source: str) -> bool` to `meridian/enrich.py` near `_is_url` (~line 39): `False` for URLs, else suffix check on `Path(source).expanduser()`.
       Pre: none
- [x] 5. Write `TestIsImageSource` in `tests/test_enrich.py`: all recognised suffixes (incl. upper-case `.PNG`) → `True`; `.pdf`/`.txt`/`.md` and a URL ending in `.png` → `False`.
       Pre: task 4 complete
- [x] 6. Add the image guard in `extract_text()` (`meridian/enrich.py:66-76`): between the `.pdf` branch and the `read_text` fallback, `if is_image_source(source): raise RuntimeError(...)` naming both `--note` and `--note-file`.
       Pre: task 4 complete
       AC: #19 *(closes the silent binary-as-text embedding bug without touching the PDF/URL/text paths)*
- [x] 7. Write `TestExtractTextImageGuard` in `tests/test_enrich.py`: a 4-byte PNG-signature file raises `RuntimeError` matching `--note`; a `.txt` file still returns as text.
       Pre: task 6 complete
- [x] 8. Write `slug_image_name(name: str) -> str` in `meridian/enrich.py`: lowercase stem, drop the filler word `at`, collapse non-alphanumeric runs to `-`, strip/collapse repeats, preserve lowercased suffix. `Screenshot 2026-08-18 at 15.40.59.png` → `screenshot-2026-08-18-15-40-59.png`.
       Pre: none
       AC: #8 *(slug is the LanceDB `source_name`, so determinism decides replace-vs-duplicate)*
- [x] 9. Write `TestSlugImageName` in `tests/test_enrich.py`: the macOS screenshot case; already-clean names unchanged; suffix case normalised; two calls identical; no leading/trailing/repeated `-`.
       Pre: task 8 complete
- [x] 10. Create `meridian/capture.py` with `screenshot_dir() -> Path`: on darwin run `defaults read com.apple.screencapture location` via `subprocess.run(capture_output=True, timeout=5)`, treating a non-zero exit as "key unset" rather than an error; fall back to `~/Desktop`, then `~/Pictures/Screenshots`; raise `RuntimeError` naming every directory tried when none exists. Wrap `FileNotFoundError`/`TimeoutExpired` into `RuntimeError`.
       Pre: none
       AC: #6
- [x] 11. Add `latest_screenshot(directory: Path | None = None) -> tuple[Path, float]` to `meridian/capture.py`: non-recursive scan of `directory or screenshot_dir()` filtered by `IMAGE_SUFFIXES`, newest by `st_mtime`, returning `(path, age_seconds)`; `RuntimeError` naming the directory when it holds no images. Return the age; do not judge it.
       Pre: tasks 4, 10 complete
       AC: #5
- [x] 12. Write `tests/test_capture.py` `TestScreenshotDir` + `TestLatestScreenshot` with `subprocess.run` patched: custom `defaults` path honoured; non-zero `defaults` exit falls back to `~/Desktop`; missing dirs walk the chain then raise naming all of them; non-darwin skips `defaults`; newest-of-three by mtime; non-image files ignored; subdirectories not descended; empty dir raises naming the dir.
       Pre: task 11 complete
       AC: #5, #6
- [x] 13. Write `render_sidecar(image_name, feat_id, notes, reading=None, described_by=None) -> str` in `meridian/enrich.py`: provenance header (`Image:`, `Feature:`, `Captured:` ISO date, optional `Described by:`), `## Notes`, optional `## Visual reading`. Author-agnostic — same renderer for agent and Ollama readings.
       Pre: none
- [x] 14. Write `parse_sidecar(text) -> tuple[str, str | None, str | None]` in `meridian/enrich.py`: returns `(notes, reading, described_by)`; falls back to `(text.strip(), None, None)` for a header-less note file. `reading is not None` is the signal that suppresses the Ollama call.
       Pre: task 13 complete
- [x] 15. Write `TestRenderSidecar` and `TestParseSidecar` in `tests/test_enrich.py`: round-trip; header carries image path/feature/date; `## Visual reading` + `- Described by:` only when a reading is passed; header-less plain text parses as notes-only with `reading is None`.
       Pre: tasks 13, 14 complete
- [x] 16. Write `notes_chunks(sidecar_text: str, image_ref: str, feat_id: str) -> list[str]` in `meridian/enrich.py`: `chunk_text` (`:81`), falling back to `[sidecar_text.strip()]` when it returns `[]` on non-empty input, then prefix every chunk with `f"[Screenshot {image_ref} · {feat_id}]\n"`.
       Pre: none
       AC: #2, #17 *(single chunking path shared by ingest and reindex; determinism gives count parity)*
- [x] 17. Write `TestNotesChunks` in `tests/test_enrich.py`: every chunk carries the image ref; a <80-char note yields exactly one chunk; a 600-word sidecar yields multiple chunks all carrying the ref; two calls identical.
       Pre: task 16 complete
- [x] 18. Write `save_screenshot(feat_dir: Path, image: Path, sidecar_text: str, slug: str) -> tuple[str, str]` in `meridian/enrich.py`: `shutil.copy2` byte-identical to `sources/<slug>` (skip if src==dest), write `<slug-stem>.notes.md`, return both names. Must not call `save_source` (avoids its `.txt`-sibling behaviour).
       Pre: tasks 8, 13 complete
- [x] 19. Write integration test in `tests/test_enrich_integration.py`: after `save_screenshot`, `sha256` of source and copy match, and `sources/<slug-stem>.txt` does NOT exist.
       Pre: task 18 complete
       AC: #1
- [x] 20. Write `caption_image(path: Path, model: str, base_url="http://localhost:11434") -> str` in `meridian/enrich.py`: `POST /api/generate` with base64 image, mapping `httpx.ConnectError` / `httpx.TimeoutException` / 404-or-"not found" to actionable `RuntimeError`s (matching `embed`'s style at `enrich.py:141-153`).
       Pre: none
       AC: #12, #13
- [x] 21. Write `TestCaptionImage` in `tests/test_enrich.py` with mocked `httpx.post`: 200 → `data["response"]`; connect error → matching `ollama serve`; timeout → matching `timed out`; 404 → matching `ollama pull`.
       Pre: task 20 complete
- [x] 22. Write `ingest_screenshot(cfg, feat_id, image, note=None, note_file=None, vision=False) -> dict` in `meridian/enrich.py` alongside `enrich_feature` (`:265`): resolve feat dir (reuse the glob at `:266-271`), resolve note + existing reading via `parse_sidecar`, apply the describer-precedence rule (existing reading wins and suppresses Ollama with a warning; else attempt `caption_image` when `vision=True`, degrading to a warning on failure; else no reading), slug the filename, render + save via tasks 13/18, chunk via `notes_chunks`, embed via `embed`, store via `upsert_chunks`, append both `sources/<slug>` and `sources/<slug-stem>.notes.md` to frontmatter (idempotent guard as at `:291-296`). Returns `{"feat_id", "source", "sidecar", "chunks", "described_by", "warnings"}`.
       Pre: tasks 6, 14, 16, 18, 20 complete
       AC: #1, #2, #3, #10, #12, #13, #14, #15
- [x] 23. Write integration tests in `tests/test_enrich_integration.py` for `ingest_screenshot`: chunk retrievable via `search_similar` carrying `sources/<slug>` (AC #2); frontmatter lists both refs (AC #3); a spaced macOS filename ends up slugified in `sources/`, frontmatter, and LanceDB `source_name` (AC #8); missing note+note_file raises (AC #4 library half); an agent-written `## Visual reading` survives byte-identical with `described_by` round-tripped (AC #10); `vision=True` alongside an existing reading makes zero `caption_image` calls and warns (AC #14); patched caption success writes `ollama:<model>` attribution and embeds the caption (AC #12); caption failure still ingests with an Ollama warning (AC #13); unconfigured `ollama_vision_model` warns by name and still ingests; re-ingest from an edited sidecar replaces chunks rather than duplicating (AC #15).
       Pre: task 22 complete
- [x] 24. Widen `reindex_all()`'s glob (`meridian/enrich.py:305-327`, line 319) to `sorted([*sources_dir.glob("*.txt"), *sources_dir.glob("*.notes.md")])`; route `*.notes.md` through `notes_chunks` with the image ref parsed from the header's `- Image:` line (fallback `sources/<stem>` + the sibling image's real suffix); never call a describer during reindex.
       Pre: tasks 14, 16 complete
       AC: #17
- [x] 25. Write `TestReindexAll` tests in `tests/test_enrich_integration.py`: screenshot + plain `.txt` reindex to the same chunk count and `sources == 2` with the screenshot row surviving; a `README.md` and a `summaries/brief.md` under `sources/` are NOT indexed; a captioned sidecar's bytes are unchanged after reindex and `caption_image` is never called (`call_count == 0`).
       Pre: task 24 complete
       AC: #17
- [x] 26. Extend the `enrich` CLI command (`meridian/cli.py:507-535`): make `source` optional; add `--note/-n`, `--note-file`, `--latest-screenshot`, `--from-clipboard`, `--vision/--no-vision`; validate mutual exclusion (capture flags vs each other and vs a positional source) before any I/O; on `--latest-screenshot` always print `Using <name> (<n>m old) from <dir>` and warn when `age > 600s`; keep non-image sources on the untouched `enrich_feature` path (warning if note flags were passed); resolve the note via `--note-file` → `--note` → `sys.stdin.isatty()`-guarded `typer.prompt`, refusing with exit 1 and writing nothing when non-interactive without a note or when the prompt is left empty; print warnings in yellow then a success line naming image + sidecar + chunk count, appending `· described by <x>`.
       Pre: tasks 11, 22 complete
       AC: #1, #4, #5, #7, #18, #19
- [x] 27. Write CLI tests in `tests/test_cli.py`: non-interactive image with no note flags exits non-zero naming both flags and writes nothing (AC #4, #18); `CliRunner` with patched tty — empty prompt aborts writing nothing, typed input becomes the note (AC #18); `--latest-screenshot` (with `meridian.capture.latest_screenshot` patched to a `tmp_path` image) prints the resolved filename and age and ingests it (AC #5); a 3600s-old screenshot warns but exits 0 (AC #7); `latest_screenshot` raising exits non-zero naming the searched directory (AC #6); `--latest-screenshot` together with a positional source, or with `--from-clipboard`, exits non-zero naming the conflict and writes nothing; `--note` on a `.pdf` warns but succeeds unchanged (AC #19); extend `TestHelp` with all five new flags.
       Pre: task 26 complete
- [x] 28. Add `clipboard_image(dest: Path) -> Path` to `meridian/capture.py` and wire `--from-clipboard`: probe `osascript -e 'clipboard info'` and raise `RuntimeError("Clipboard holds no image…")` unless an image class (`PNGf`/`TIFF`) is present; otherwise extract `the clipboard as «class PNGf»` to `dest` named `clipboard-<ISO-timestamp>.png`; non-darwin and missing-`osascript` cases raise pointing at `--latest-screenshot`.
       Pre: tasks 10, 26 complete
       AC: #9
- [x] 29. Write `TestClipboardImage` in `tests/test_capture.py` (patched `subprocess.run`) and the CLI counterpart: `clipboard info` without an image class raises matching `no image` (the observed real-world state); output containing `«class PNGf»` proceeds and writes `dest`; `FileNotFoundError` from `osascript` raises pointing at `--latest-screenshot`; non-darwin raises immediately; `--from-clipboard` with no image exits non-zero.
       Pre: task 28 complete
       AC: #9
- [x] 30. Write the `/meridian:enrich` skill at `meridian/skills/commands/enrich.md` with `model: claude-sonnet-5` frontmatter: parse `<feat-id> "<note>"`, look at the attached screenshot, write a sidecar into the session scratchpad using the `render_sidecar` format (user note under `## Notes`, own reading under `## Visual reading`, `Described by: <model> (agent)`), run `meridian enrich <feat> --latest-screenshot --note-file <sidecar>`, then report the resolved image filename and chunk count from the CLI's output. State explicitly that it must not write into `sources/` itself — the CLI owns that directory.
       Pre: task 26 complete
       AC: #11
- [x] 31. Copy `meridian/skills/commands/enrich.md` byte-identically to `.claude/commands/meridian/enrich.md` in the same commit, then run `pytest tests/test_skill_sync.py tests/test_models.py tests/test_skill_consistency.py` to confirm parity, the `model:` declaration, and structural consistency.
       Pre: task 30 complete
       AC: #20
- [x] 32. Update docs: `meridian help` CLI table (`cli.py:1134-1135`) with `--latest-screenshot` and `--vision` example rows, the `sources/` layout line (`cli.py:1256`), `README.md` CLI table (~line 148) and Ollama setup section (~lines 74-80), and `CLAUDE.md` — CLI block plus the **slash-command table** gaining `/enrich` — naming the exact flags `--note`, `--note-file`, `--latest-screenshot`, `--from-clipboard`, `--vision` so `tests/test_contracts.py::TestFlagsExist` picks them up.
       Pre: tasks 26, 30 complete
- [x] 33. Run `ruff check . && mypy meridian/ && pytest`; confirm the five new `(enrich, --flag)` contract pairs are collected and green and the whole suite passes.
       Pre: tasks 3, 5, 7, 9, 12, 15, 17, 19, 21, 23, 25, 27, 29, 31, 32 complete
- [x] 34. Write an ADR via `/decision`: capture belongs to the CLI because Claude Code chat attachments carry no filesystem path (verified — no on-disk cache); description belongs to the agent, with Ollama `--vision` as headless fallback; `ollama_vision_model` defaults to empty; an existing `## Visual reading` is never overwritten; readings are never regenerated on reindex.
       Pre: task 24 complete
- [x] 35. Manual verification — **done for the CLI path**: real screenshot
       (`Screenshot 2026-08-18 at 15.40.59.png`) ingested via
       `meridian enrich feat-006 --latest-screenshot --note-file <sidecar>`; resolved-name + 56m
       staleness warning printed; stored as `screenshot-2026-08-18-15-40-59.png` + sidecar;
       `meridian search "unbounded yield metric axis outliers" --feat feat-006` returns it as the top
       hit with `sources/…png` in the chunk text; `reindex_all` chunk parity and byte-unchanged
       sidecar confirmed in an isolated store.
       Pre: task 33 complete
- [ ] 36. Outstanding manual checks: (a) invoke `/meridian:enrich` as a real slash command with an
       attached screenshot, end to end; (b) `ollama pull` a multimodal model, set
       `ollama_vision_model`, and exercise `--vision` with Ollama up and stopped; (c) `--from-clipboard`
       against a real clipboard image. All three are covered by automated tests with patched seams,
       but none has been run against the live external tool.
       Pre: task 35 complete
- [ ] 37. Do NOT run `meridian index` in this repo until FEAT-007 lands: `lancedb_path` is the global
       `~/.meridian/lancedb`, and `reindex_all` still drops the whole table, so a rebuild here wipes
       every other project's vectors. Verify reindex behaviour in an isolated store instead.
       Pre: none
