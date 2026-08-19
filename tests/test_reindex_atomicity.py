"""A failed reindex must not destroy the corpus (FEAT-013).

The audit reproduced this against the real store: 4 chunks in, Ollama
unreachable, "Vector index was not rebuilt", exit code 0, 0 chunks out. The
delete ran before the embed loop, so the failure that stopped the rebuild had
already taken the data with it.
"""
from __future__ import annotations

import pytest

from meridian import enrich as enrich_mod
from meridian.enrich import search_similar, upsert_chunks

VEC = [1.0, 0.0, 0.0, 0.0]


def _chunk(word: str = "word") -> str:
    return " ".join(f"{word}{i}" for i in range(100))


def _write_source(cfg, feat_id: str, name: str, body: str) -> None:
    sources = cfg.specs_path / f"{feat_id}_demo" / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    (sources / name).write_text(body)


def _rows(cfg, project: str = "test-project") -> list[dict]:
    return search_similar(cfg.lancedb_path, VEC, limit=100, project=project)


class TestReindexFailureLeavesCorpusIntact:
    def test_embedding_failure_does_not_delete_existing_chunks(
        self, mock_cfg, monkeypatch
    ) -> None:
        """The exact reported failure: Ollama down during `meridian index`."""
        upsert_chunks(
            mock_cfg.lancedb_path, "test-project", "FEAT-001", "existing.txt",
            [_chunk("existing")], [VEC],
        )
        assert len(_rows(mock_cfg)) == 1

        _write_source(mock_cfg, "FEAT-001", "ours.txt", _chunk("ours"))

        def ollama_is_down(text, model=None):
            raise RuntimeError("Cannot connect to Ollama at http://localhost:11434")

        monkeypatch.setattr(enrich_mod, "embed", ollama_is_down)

        with pytest.raises(RuntimeError):
            enrich_mod.reindex_all(mock_cfg)

        survivors = _rows(mock_cfg)
        assert len(survivors) == 1, "a failed rebuild must not delete the corpus"
        assert survivors[0]["source_name"] == "existing.txt"

    def test_failure_partway_through_still_preserves_everything(
        self, mock_cfg, monkeypatch
    ) -> None:
        """Failing on the second source must not leave a half-built index."""
        upsert_chunks(
            mock_cfg.lancedb_path, "test-project", "FEAT-001", "existing.txt",
            [_chunk("existing")], [VEC],
        )
        _write_source(mock_cfg, "FEAT-001", "a.txt", _chunk("aaa"))
        _write_source(mock_cfg, "FEAT-002", "b.txt", _chunk("bbb"))

        calls: list[str] = []

        def fail_on_second(text, model=None):
            calls.append(text)
            if len(calls) > 1:
                raise RuntimeError("model not pulled")
            return VEC

        monkeypatch.setattr(enrich_mod, "embed", fail_on_second)

        with pytest.raises(RuntimeError):
            enrich_mod.reindex_all(mock_cfg)

        survivors = _rows(mock_cfg)
        assert [r["source_name"] for r in survivors] == ["existing.txt"]

    def test_successful_rebuild_still_replaces_own_rows(self, mock_cfg, monkeypatch) -> None:
        """The happy path must be unchanged: stale rows for this project go."""
        upsert_chunks(
            mock_cfg.lancedb_path, "test-project", "FEAT-099", "deleted.txt",
            [_chunk("stale")], [VEC],
        )
        _write_source(mock_cfg, "FEAT-001", "ours.txt", _chunk("ours"))
        monkeypatch.setattr(enrich_mod, "embed", lambda text, model=None: VEC)

        result = enrich_mod.reindex_all(mock_cfg)

        assert result["sources"] == 1
        assert {r["source_name"] for r in _rows(mock_cfg)} == {"ours.txt"}

    def test_other_projects_untouched_on_failure(self, mock_cfg, monkeypatch) -> None:
        upsert_chunks(
            mock_cfg.lancedb_path, "other-project", "FEAT-001", "theirs.txt",
            [_chunk("theirs")], [VEC],
        )
        _write_source(mock_cfg, "FEAT-001", "ours.txt", _chunk("ours"))

        def boom(text, model=None):
            raise RuntimeError("ollama down")

        monkeypatch.setattr(enrich_mod, "embed", boom)

        with pytest.raises(RuntimeError):
            enrich_mod.reindex_all(mock_cfg)

        assert len(_rows(mock_cfg, "other-project")) == 1


class TestEmbedErrorMessages:
    """FEAT-013: a model that was never pulled is the commonest misconfiguration."""

    def test_http_status_error_becomes_actionable_runtime_error(self, monkeypatch) -> None:
        import httpx

        from meridian.enrich import embed

        class FakeResponse:
            status_code = 404

            def raise_for_status(self):
                raise httpx.HTTPStatusError(
                    "404", request=httpx.Request("POST", "http://x"), response=self
                )

            def json(self):  # pragma: no cover - never reached
                return {}

        monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse())

        with pytest.raises(RuntimeError) as excinfo:
            embed("some text", model="no-such-model")

        message = str(excinfo.value)
        assert "no-such-model" in message
        assert "ollama pull" in message
        assert "Traceback" not in message
