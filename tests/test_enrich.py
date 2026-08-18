"""Tests for meridian/enrich.py — chunking, URL/file detection, embed API shapes."""
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from meridian.enrich import (
    _is_url,
    _require_lancedb_compat,
    _source_filename,
    caption_image,
    chunk_text,
    embed,
    extract_text,
    is_image_source,
    notes_chunks,
    parse_sidecar,
    render_sidecar,
    slug_image_name,
)

# ── LanceDB Python-version guard ─────────────────────────────────────────── #


class TestLanceDBCompatGuard:
    """Guard converts the Python-3.14 LanceDB segfault into a clear error."""

    def test_raises_on_314(self):
        with pytest.raises(RuntimeError, match="3.14"):
            _require_lancedb_compat((3, 14, 0))

    def test_raises_on_315(self):
        with pytest.raises(RuntimeError, match="LanceDB"):
            _require_lancedb_compat((3, 15, 2))

    def test_noop_on_313(self):
        _require_lancedb_compat((3, 13, 7))  # must not raise

    def test_noop_on_311(self):
        _require_lancedb_compat((3, 11, 0))  # must not raise

    def test_uses_live_interpreter_by_default(self):
        # Suite runs on a supported Python (<3.14) → default call must not raise
        _require_lancedb_compat()

# ── _is_url ──────────────────────────────────────────────────────────────── #


class TestIsUrl:
    def test_http(self):
        assert _is_url("http://example.com") is True

    def test_https(self):
        assert _is_url("https://example.com/path") is True

    def test_local_file(self):
        assert _is_url("/path/to/file.pdf") is False

    def test_relative_path(self):
        assert _is_url("report.txt") is False


# ── _source_filename ──────────────────────────────────────────────────────── #


class TestSourceFilename:
    def test_local_file_preserves_name(self):
        assert _source_filename("/path/to/report.pdf") == "report.pdf"

    def test_url_becomes_txt(self):
        name = _source_filename("https://example.com/blog/post")
        assert name.endswith(".txt")
        assert "example" in name

    def test_url_truncated_to_60_chars_plus_ext(self):
        long_url = "https://example.com/" + "x" * 100
        name = _source_filename(long_url)
        # 60 chars slug + ".txt" = 64
        assert len(name) <= 64

    def test_url_with_apostrophe_in_path(self):
        # Regression: source names with ' must not break SQL delete predicates (B1)
        name = _source_filename("https://example.com/o'reilly/report")
        assert "'" in name or name.endswith(".txt")  # must still produce a filename


# ── chunk_text ────────────────────────────────────────────────────────────── #


class TestChunkText:
    def test_empty_string(self):
        assert chunk_text("") == []

    def test_text_below_minimum_length(self):
        # A handful of words produces a chunk < 80 chars — should be filtered
        assert chunk_text("hello world foo") == []

    def test_single_chunk_under_max_words(self):
        text = " ".join([f"word{i}" for i in range(50)])
        chunks = chunk_text(text, max_words=200)
        assert len(chunks) == 1

    def test_produces_overlap(self):
        # 400 words: produces multiple chunks; verify the overlap property holds.
        # The chunker steps forward by (max_words - overlap) each iteration, so
        # the last `overlap` words of chunk N always reappear at the start of chunk N+1.
        words = [f"w{i}" for i in range(400)]
        text = " ".join(words)
        chunks = chunk_text(text, max_words=200, overlap=25)
        assert len(chunks) >= 2
        # The last 25 words of chunk[0] (words 175..199) must appear in chunk[1]
        end_of_first = " ".join(words[175:200])
        assert end_of_first in chunks[1]

    def test_short_tail_below_minimum_is_filtered(self):
        # When the overlap tail has fewer chars than the 80-char minimum, it is dropped.
        # Single-char words: 25 words × ~1 char + 24 spaces = ~49 chars < 80 → filtered.
        text = " ".join(["a"] * 200)
        chunks = chunk_text(text, max_words=200, overlap=25)
        assert len(chunks) == 1

    def test_large_text_many_chunks(self):
        text = " ".join([f"word_{i}" for i in range(1000)])
        chunks = chunk_text(text, max_words=200, overlap=25)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) >= 80


# ── embed (mocked httpx) ─────────────────────────────────────────────────── #


class TestEmbed:
    def _mock_response(self, status_code: int, body: dict) -> MagicMock:
        m = MagicMock()
        m.status_code = status_code
        m.json.return_value = body
        m.raise_for_status = MagicMock()
        return m

    def test_new_api_path(self):
        resp = self._mock_response(200, {"embeddings": [[0.1, 0.2, 0.3]]})
        with patch("httpx.post", return_value=resp) as mock_post:
            result = embed("hello", model="mxbai-embed-large")
        assert result == [0.1, 0.2, 0.3]
        url = mock_post.call_args[0][0]
        assert "/api/embed" in url

    def test_legacy_api_fallback_on_404(self):
        def side_effect(url, **kwargs):
            m = MagicMock()
            if url.endswith("/api/embed"):
                m.status_code = 404
                m.raise_for_status = MagicMock()
            else:
                m.status_code = 200
                m.json.return_value = {"embedding": [0.4, 0.5]}
                m.raise_for_status = MagicMock()
            return m

        with patch("httpx.post", side_effect=side_effect):
            result = embed("hello", model="mxbai-embed-large")
        assert result == [0.4, 0.5]

    def test_legacy_api_fallback_on_400(self):
        def side_effect(url, **kwargs):
            m = MagicMock()
            if url.endswith("/api/embed"):
                m.status_code = 400
                m.raise_for_status = MagicMock()
            else:
                m.status_code = 200
                m.json.return_value = {"embedding": [0.9]}
                m.raise_for_status = MagicMock()
            return m

        with patch("httpx.post", side_effect=side_effect):
            result = embed("hello", model="mxbai-embed-large")
        assert result == [0.9]

    def test_connect_error_raises_friendly_message(self):
        with patch("httpx.post", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(RuntimeError, match="Cannot connect to Ollama"):
                embed("hello", model="mxbai-embed-large")

    def test_timeout_raises_friendly_message(self):
        """B2: ReadTimeout must not propagate as a raw httpx exception."""
        with patch("httpx.post", side_effect=httpx.ReadTimeout("timeout")):
            with pytest.raises(RuntimeError, match="timed out"):
                embed("hello", model="mxbai-embed-large")


# ── SQL injection guard (B1) ─────────────────────────────────────────────── #


class TestUpsertChunksSqlEscape:
    """Verify the delete predicate handles single quotes in source_name."""

    def test_apostrophe_in_source_name_does_not_raise(self, tmp_path: Path):
        """B1: upsert_chunks must escape quotes rather than produce invalid SQL."""
        from meridian.enrich import upsert_chunks

        lancedb_path = tmp_path / "lancedb"
        chunks = [" ".join([f"word{i}" for i in range(100)])]  # > 80 chars
        vectors = [[0.1] * 4]

        # This previously would raise or silently corrupt the delete predicate
        # because source_name contains a single quote.
        upsert_chunks(lancedb_path, "FEAT-001", "O'Reilly_report.pdf", chunks, vectors)
        # If we get here without a crash, the fix is in place.


# ── Screenshot ingest: detection, slugging, sidecars (FEAT-006) ──────────── #


class TestIsImageSource:
    """Image detection gates the screenshot path — URLs stay text-only."""

    @pytest.mark.parametrize(
        "name",
        ["shot.png", "shot.jpg", "shot.jpeg", "shot.webp", "shot.gif", "SHOT.PNG"],
    )
    def test_image_suffixes_detected(self, name):
        assert is_image_source(name) is True

    @pytest.mark.parametrize("name", ["paper.pdf", "notes.txt", "spec.md", "archive.tar.gz"])
    def test_non_image_files_rejected(self, name):
        assert is_image_source(name) is False

    def test_url_ending_in_png_is_not_an_image_source(self):
        # A page that happens to end in .png is still fetched through the HTML
        # extractor — remote ingest is text-only by design.
        assert is_image_source("https://example.com/chart.png") is False


class TestExtractTextImageGuard:
    """Images must never reach the read_text() fallback (the garbage-bytes bug)."""

    def test_png_raises_runtime_error_naming_note_flag(self, tmp_path: Path):
        png = tmp_path / "shot.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n")
        with pytest.raises(RuntimeError, match="--note"):
            extract_text(str(png))

    def test_error_also_names_note_file(self, tmp_path: Path):
        png = tmp_path / "shot.png"
        png.write_bytes(b"\x89PNG")
        with pytest.raises(RuntimeError, match="--note-file"):
            extract_text(str(png))

    def test_txt_still_read_as_text(self, tmp_path: Path):
        txt = tmp_path / "notes.txt"
        txt.write_text("plain content")
        assert extract_text(str(txt)) == "plain content"


class TestSlugImageName:
    """The slug becomes the LanceDB source_name, so it must be deterministic."""

    def test_macos_screenshot_name(self):
        assert (
            slug_image_name("Screenshot 2026-08-18 at 15.40.59.png")
            == "screenshot-2026-08-18-15-40-59.png"
        )

    def test_already_clean_name_unchanged(self):
        assert slug_image_name("kpi.png") == "kpi.png"

    def test_suffix_case_normalised(self):
        assert slug_image_name("KPI.PNG") == "kpi.png"

    def test_deterministic(self):
        name = "Screenshot 2026-08-18 at 15.40.59.png"
        assert slug_image_name(name) == slug_image_name(name)

    def test_no_leading_trailing_or_repeated_dashes(self):
        slug = slug_image_name("  --Weird__name!!  .png")
        stem = Path(slug).stem
        assert not stem.startswith("-")
        assert not stem.endswith("-")
        assert "--" not in stem

    def test_unnameable_stem_falls_back(self):
        assert slug_image_name("!!!.png") == "image.png"


class TestRenderSidecar:
    def test_header_carries_image_feature_and_date(self):
        text = render_sidecar("kpi.png", "feat-006", "tile shows 0")
        assert "- Image: sources/kpi.png" in text
        assert "- Feature: FEAT-006" in text
        assert re.search(r"- Captured: \d{4}-\d{2}-\d{2}", text)

    def test_notes_section_present(self):
        text = render_sidecar("kpi.png", "FEAT-006", "tile shows 0")
        assert "## Notes" in text
        assert "tile shows 0" in text

    def test_reading_section_omitted_without_a_reading(self):
        text = render_sidecar("kpi.png", "FEAT-006", "tile shows 0")
        assert "## Visual reading" not in text
        assert "- Described by:" not in text

    def test_reading_section_present_with_attribution(self):
        text = render_sidecar(
            "kpi.png", "FEAT-006", "tile shows 0",
            reading="Four tiles; leftmost reads 0.",
            described_by="claude-opus-5 (agent)",
        )
        assert "## Visual reading" in text
        assert "Four tiles; leftmost reads 0." in text
        assert "- Described by: claude-opus-5 (agent)" in text


class TestParseSidecar:
    def test_round_trips_rendered_sidecar(self):
        rendered = render_sidecar(
            "kpi.png", "FEAT-006", "tile shows 0",
            reading="Four tiles; leftmost reads 0.",
            described_by="ollama:qwen2.5vl:7b",
        )
        notes, reading, described_by = parse_sidecar(rendered)
        assert notes == "tile shows 0"
        assert reading == "Four tiles; leftmost reads 0."
        assert described_by == "ollama:qwen2.5vl:7b"

    def test_notes_only_sidecar_has_no_reading(self):
        rendered = render_sidecar("kpi.png", "FEAT-006", "tile shows 0")
        notes, reading, described_by = parse_sidecar(rendered)
        assert notes == "tile shows 0"
        assert reading is None
        assert described_by is None

    def test_plain_note_file_returned_whole(self):
        notes, reading, described_by = parse_sidecar("just some scratch prose")
        assert notes == "just some scratch prose"
        assert reading is None
        assert described_by is None


class TestNotesChunks:
    def test_every_chunk_carries_the_image_ref(self):
        long_notes = " ".join(f"word{i}" for i in range(600))
        text = render_sidecar("kpi.png", "FEAT-006", long_notes)
        chunks = notes_chunks(text, "sources/kpi.png", "FEAT-006")
        assert len(chunks) > 1
        assert all("sources/kpi.png" in c for c in chunks)

    def test_short_note_still_yields_one_chunk(self):
        # chunk_text drops anything under 80 chars; a terse screenshot note
        # must not vanish from the corpus.
        chunks = notes_chunks("tile is 0", "sources/kpi.png", "FEAT-006")
        assert len(chunks) == 1
        assert "tile is 0" in chunks[0]

    def test_empty_text_yields_nothing(self):
        assert notes_chunks("   \n  ", "sources/kpi.png", "FEAT-006") == []

    def test_deterministic(self):
        text = render_sidecar("kpi.png", "FEAT-006", " ".join(f"w{i}" for i in range(400)))
        first = notes_chunks(text, "sources/kpi.png", "FEAT-006")
        second = notes_chunks(text, "sources/kpi.png", "FEAT-006")
        assert first == second


class TestCaptionImage:
    """The Ollama fallback describer — errors must be actionable, never raw."""

    def _png(self, tmp_path: Path) -> Path:
        png = tmp_path / "shot.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n")
        return png

    def test_returns_response_text(self, tmp_path: Path):
        resp = MagicMock(status_code=200, text="{}")
        resp.json.return_value = {"response": "  A chart with four tiles.  "}
        with patch("httpx.post", return_value=resp):
            assert caption_image(self._png(tmp_path), "vis") == "A chart with four tiles."

    def test_connect_error_names_ollama_serve(self, tmp_path: Path):
        with patch("httpx.post", side_effect=httpx.ConnectError("boom")):
            with pytest.raises(RuntimeError, match="ollama serve"):
                caption_image(self._png(tmp_path), "vis")

    def test_timeout_is_reported_as_timeout(self, tmp_path: Path):
        with patch("httpx.post", side_effect=httpx.ReadTimeout("slow")):
            with pytest.raises(RuntimeError, match="timed out"):
                caption_image(self._png(tmp_path), "vis")

    def test_missing_model_names_ollama_pull(self, tmp_path: Path):
        resp = MagicMock(status_code=404, text="model 'vis' not found")
        with patch("httpx.post", return_value=resp):
            with pytest.raises(RuntimeError, match="ollama pull vis"):
                caption_image(self._png(tmp_path), "vis")
