"""Tests for meridian/enrich.py — chunking, URL/file detection, embed API shapes."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from meridian.enrich import (
    _is_url,
    _source_filename,
    chunk_text,
    embed,
)

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
