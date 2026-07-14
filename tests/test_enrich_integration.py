"""Integration tests for the enrich.py external seams.

Complements tests/test_enrich.py (pure unit tests) by exercising the two seams
that unit tests mock away:

  * LanceDB — real temp-dir round-trips (upsert → search), the feat_id filter,
    upsert idempotency (stale-entry replacement), and graceful empty returns.
    lancedb + pyarrow are hard dependencies, so these run a genuine store.
  * Ollama — the embed() sanitize-retry branch, plus the full enrich_feature
    pipeline with embed mocked at the httpx layer but LanceDB and the filesystem
    real end-to-end.

Run:  .venv/bin/pytest tests/test_enrich_integration.py -v
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from meridian.config import MeridianConfig
from meridian.enrich import (
    embed,
    enrich_feature,
    reindex_all,
    search_similar,
    upsert_chunks,
)

# ── helpers ──────────────────────────────────────────────────────────────── #

DIM = 4


def _chunk(word: str = "word") -> str:
    """A chunk guaranteed to clear the 80-char minimum in chunk_text."""
    return " ".join(f"{word}{i}" for i in range(100))


def _row_count(lancedb_path: Path) -> int:
    import lancedb

    db = lancedb.connect(str(lancedb_path))
    return db.open_table("chunks").count_rows()


# ── LanceDB round-trip ───────────────────────────────────────────────────── #


class TestLanceDbRoundTrip:
    def test_upsert_then_search_returns_stored_chunk(self, tmp_path: Path) -> None:
        db_path = tmp_path / "lancedb"
        chunks = [_chunk("alpha"), _chunk("beta")]
        vectors = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]]

        upsert_chunks(db_path, "FEAT-001", "src.txt", chunks, vectors)

        # Query nearest to the first vector → first chunk ranks top.
        results = search_similar(db_path, [1.0, 0.0, 0.0, 0.0], limit=2)
        assert len(results) == 2
        assert results[0]["text"] == chunks[0]
        assert results[0]["feat_id"] == "FEAT-001"
        assert results[0]["source_name"] == "src.txt"

    def test_feat_id_filter_scopes_results(self, tmp_path: Path) -> None:
        db_path = tmp_path / "lancedb"
        vec = [0.5, 0.5, 0.5, 0.5]
        upsert_chunks(db_path, "FEAT-001", "a.txt", [_chunk("a")], [vec])
        upsert_chunks(db_path, "FEAT-002", "b.txt", [_chunk("b")], [vec])

        # search_similar upper-cases the filter internally.
        results = search_similar(db_path, vec, limit=10, feat_id_filter="feat-002")
        assert results, "filter should still return the matching feature's chunk"
        assert {r["feat_id"] for r in results} == {"FEAT-002"}

    def test_upsert_replaces_stale_entries_no_duplicates(self, tmp_path: Path) -> None:
        """Re-enriching the same source must not accumulate rows (idempotency)."""
        db_path = tmp_path / "lancedb"
        chunks = [_chunk("x"), _chunk("y"), _chunk("z")]
        vectors = [[1.0, 0, 0, 0], [0, 1.0, 0, 0], [0, 0, 1.0, 0]]

        upsert_chunks(db_path, "FEAT-001", "src.txt", chunks, vectors)
        assert _row_count(db_path) == 3
        # Same feat_id + source again → delete-then-add, still 3 rows.
        upsert_chunks(db_path, "FEAT-001", "src.txt", chunks, vectors)
        assert _row_count(db_path) == 3

    def test_upsert_different_source_coexists(self, tmp_path: Path) -> None:
        db_path = tmp_path / "lancedb"
        upsert_chunks(db_path, "FEAT-001", "a.txt", [_chunk("a")], [[1.0, 0, 0, 0]])
        upsert_chunks(db_path, "FEAT-001", "b.txt", [_chunk("b")], [[0, 1.0, 0, 0]])
        # Different source under same feature → both retained.
        assert _row_count(db_path) == 2

    def test_empty_chunks_is_noop(self, tmp_path: Path) -> None:
        db_path = tmp_path / "lancedb"
        upsert_chunks(db_path, "FEAT-001", "src.txt", [], [])
        # No table created, nothing to search.
        assert search_similar(db_path, [1.0, 0, 0, 0]) == []


class TestSearchDegradation:
    def test_missing_path_returns_empty(self, tmp_path: Path) -> None:
        assert search_similar(tmp_path / "does-not-exist", [1.0, 0, 0, 0]) == []

    def test_existing_path_but_no_table_returns_empty(self, tmp_path: Path) -> None:
        # Path exists but the "chunks" table was never created.
        db_path = tmp_path / "lancedb"
        db_path.mkdir(parents=True)
        assert search_similar(db_path, [1.0, 0, 0, 0]) == []


# ── embed sanitize-retry branch (Ollama seam) ───────────────────────────── #


class TestEmbedSanitizeRetry:
    def test_unicode_400_then_sanitized_retry_succeeds(self) -> None:
        """A chunk with unicode gets a 400, then a sanitized retry succeeds.

        Exercises the retry branch in embed() that unit tests don't cover: the
        first /api/embed call 400s on raw unicode; the second /api/embed call
        with ASCII-stripped input returns 200.
        """
        calls: list[dict] = []

        def side_effect(url, **kwargs):
            calls.append({"url": url, "input": kwargs["json"].get("input")})
            m = MagicMock()
            if len(calls) == 1:
                # First attempt with raw unicode → 400.
                m.status_code = 400
                m.raise_for_status = MagicMock()
            else:
                m.status_code = 200
                m.json.return_value = {"embeddings": [[0.7, 0.8]]}
                m.raise_for_status = MagicMock()
            return m

        with patch("httpx.post", side_effect=side_effect):
            result = embed("café ∑ π math", model="mxbai-embed-large")

        assert result == [0.7, 0.8]
        assert len(calls) == 2
        # Second call hits the same /api/embed endpoint with ASCII-only input.
        assert calls[1]["url"].endswith("/api/embed")
        assert calls[1]["input"].isascii()
        assert "caf" in calls[1]["input"]  # non-ascii stripped, ascii kept


# ── enrich_feature end-to-end (fs + LanceDB real, embed mocked) ──────────── #


class TestEnrichFeatureEndToEnd:
    def _make_spec(self, specs_dir: Path) -> Path:
        feat_dir = specs_dir / "FEAT-001_test_feature"
        feat_dir.mkdir()
        (feat_dir / "spec.md").write_text(
            "---\nid: feat-001\nname: Test\nstatus: idea\n---\nBody.\n"
        )
        return feat_dir

    def test_full_pipeline_stores_and_updates_frontmatter(
        self, mock_cfg: MeridianConfig, tmp_path: Path
    ) -> None:
        feat_dir = self._make_spec(mock_cfg.specs_path)
        source = tmp_path / "paper.txt"
        source.write_text(" ".join(f"token{i}" for i in range(400)))

        # Mock only the network embed call; LanceDB + filesystem are real.
        with patch(
            "meridian.enrich.embed",
            side_effect=lambda *a, **k: [0.1, 0.2, 0.3, 0.4],
        ):
            result = enrich_feature(mock_cfg, "feat-001", str(source))

        assert result["feat_id"] == "FEAT-001"
        assert result["chunks"] >= 1

        # Source file copied into the feature's sources/ dir.
        assert (feat_dir / "sources" / "paper.txt").exists()

        # Frontmatter sources list updated.
        from meridian.specs import load_spec

        data = load_spec(feat_dir / "spec.md")
        assert "sources/paper.txt" in data["sources"]

        # Chunk is retrievable from the real LanceDB store.
        hits = search_similar(
            mock_cfg.lancedb_path, [0.1, 0.2, 0.3, 0.4], feat_id_filter="feat-001"
        )
        assert hits
        assert hits[0]["feat_id"] == "FEAT-001"


# ── reindex_all round-trip ───────────────────────────────────────────────── #


class TestReindexAll:
    def test_rebuilds_index_from_sources(
        self, mock_cfg: MeridianConfig
    ) -> None:
        # Two features each with a .txt source on disk.
        for fid in ("FEAT-001", "FEAT-002"):
            src_dir = mock_cfg.specs_path / f"{fid}_feature" / "sources"
            src_dir.mkdir(parents=True)
            (src_dir / "doc.txt").write_text(
                " ".join(f"w{i}" for i in range(300))
            )

        with patch(
            "meridian.enrich.embed",
            side_effect=lambda *a, **k: [0.1, 0.2, 0.3, 0.4],
        ):
            stats = reindex_all(mock_cfg)

        assert stats["sources"] == 2
        assert stats["chunks"] >= 2
        # Everything is searchable afterwards.
        assert search_similar(mock_cfg.lancedb_path, [0.1, 0.2, 0.3, 0.4], limit=100)

    def test_reindex_is_idempotent(self, mock_cfg: MeridianConfig) -> None:
        src_dir = mock_cfg.specs_path / "FEAT-001_feature" / "sources"
        src_dir.mkdir(parents=True)
        (src_dir / "doc.txt").write_text(" ".join(f"w{i}" for i in range(300)))

        with patch(
            "meridian.enrich.embed",
            side_effect=lambda *a, **k: [0.1, 0.2, 0.3, 0.4],
        ):
            first = reindex_all(mock_cfg)
            second = reindex_all(mock_cfg)

        # Drop-and-rebuild must produce the same row count, not accumulate.
        assert first["chunks"] == second["chunks"]
