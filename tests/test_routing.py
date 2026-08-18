"""Routing suggestions for captured ideas (FEAT-008)."""
import datetime
from pathlib import Path

import pytest

from meridian.inbox import Capture
from meridian.registry import ProjectEntry
from meridian.routing import suggest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MERIDIAN_HOME", str(tmp_path / "meridian-home"))


def _capture(text: str = "add retry logic to the scraper", project: str | None = None) -> Capture:
    return Capture(
        path=Path("/tmp/2026-08-18T164500.md"),
        text=text,
        created=datetime.datetime(2026, 8, 18, 16, 45),
        project=project,
        hint_source="frontmatter" if project else None,
    )


def _entries(*slugs: str, purpose: str = "") -> list[ProjectEntry]:
    return [
        ProjectEntry(slug=s, path=Path(f"/repos/{s}"), purpose=purpose or f"{s} purpose", exists=True)
        for s in slugs
    ]


def _stub_search(monkeypatch, hits: list[dict]) -> None:
    import meridian.enrich as enrich_mod

    monkeypatch.setattr(enrich_mod, "search_similar", lambda *a, **k: hits)


def _stub_embed(monkeypatch, calls: list | None = None) -> None:
    import meridian.enrich as enrich_mod

    def fake_embed(text, model=None):
        if calls is not None:
            calls.append(text)
        return [1.0, 0.0, 0.0, 0.0]

    monkeypatch.setattr(enrich_mod, "embed", fake_embed)


class TestExplicitHint:
    def test_short_circuits_without_embedding(self, mock_cfg, monkeypatch) -> None:
        """AC13: a labelled capture must route without Ollama running."""
        calls: list = []
        _stub_embed(monkeypatch, calls)

        result = suggest(_capture(project="meridian"), _entries("meridian"), mock_cfg.lancedb_path, mock_cfg.ollama_model)

        assert result == [result[0]]
        assert result[0].slug == "meridian"
        assert result[0].basis == "explicit"
        assert calls == [], "explicit hint must not trigger an embed call"


class TestIndexScoring:
    def test_aggregates_hits_per_project(self, mock_cfg, monkeypatch) -> None:
        _stub_embed(monkeypatch)
        _stub_search(monkeypatch, [
            {"project": "meridian", "_distance": 0.9},
            {"project": "portfolio-management", "_distance": 0.1},
            {"project": "meridian", "_distance": 0.5},
        ])

        result = suggest(_capture(), _entries("meridian", "portfolio-management"), mock_cfg.lancedb_path, mock_cfg.ollama_model)

        assert [s.slug for s in result] == ["portfolio-management", "meridian"]
        assert all(s.basis in ("index", "purpose") for s in result)

    def test_best_hit_wins_not_row_count(self, mock_cfg, monkeypatch) -> None:
        """A project with many weak hits must not outrank one strong match."""
        _stub_embed(monkeypatch)
        _stub_search(monkeypatch, [
            {"project": "noisy", "_distance": 5.0},
            {"project": "noisy", "_distance": 5.0},
            {"project": "noisy", "_distance": 5.0},
            {"project": "precise", "_distance": 0.05},
        ])

        result = suggest(_capture(), _entries("noisy", "precise"), mock_cfg.lancedb_path, mock_cfg.ollama_model)
        assert result[0].slug == "precise"

    def test_unregistered_project_hits_ignored(self, mock_cfg, monkeypatch) -> None:
        """A row from a repo no longer in the registry is not a routing target."""
        _stub_embed(monkeypatch)
        _stub_search(monkeypatch, [{"project": "ghost-repo", "_distance": 0.01}])

        result = suggest(_capture(), _entries("meridian"), mock_cfg.lancedb_path, mock_cfg.ollama_model)
        assert "ghost-repo" not in [s.slug for s in result]

    def test_truncated_to_top_three(self, mock_cfg, monkeypatch) -> None:
        _stub_embed(monkeypatch)
        _stub_search(monkeypatch, [
            {"project": f"p{i}", "_distance": float(i) / 10} for i in range(6)
        ])

        result = suggest(
            _capture(), _entries(*[f"p{i}" for i in range(6)]),
            mock_cfg.lancedb_path, mock_cfg.ollama_model,
        )
        assert len(result) == 3


class TestPurposeFallback:
    def test_unindexed_project_still_routable(self, mock_cfg, monkeypatch) -> None:
        """AC12: a brand-new project has no rows but must not be invisible."""
        _stub_embed(monkeypatch)
        _stub_search(monkeypatch, [])

        result = suggest(_capture(), _entries("brand-new"), mock_cfg.lancedb_path, mock_cfg.ollama_model)

        assert [s.slug for s in result] == ["brand-new"]
        assert result[0].basis == "purpose"


class TestDegradation:
    def test_embed_failure_returns_empty(self, mock_cfg, monkeypatch) -> None:
        """Ollama down must not block manual triage."""
        import meridian.enrich as enrich_mod

        def boom(text, model=None):
            raise RuntimeError("ollama not running")

        monkeypatch.setattr(enrich_mod, "embed", boom)

        assert suggest(_capture(), _entries("meridian"), mock_cfg.lancedb_path, mock_cfg.ollama_model) == []

    def test_index_failure_falls_back_to_purpose(self, mock_cfg, monkeypatch) -> None:
        import meridian.enrich as enrich_mod

        _stub_embed(monkeypatch)

        def boom(*a, **k):
            raise RuntimeError("legacy index")

        monkeypatch.setattr(enrich_mod, "search_similar", boom)

        result = suggest(_capture(), _entries("meridian"), mock_cfg.lancedb_path, mock_cfg.ollama_model)
        assert [s.basis for s in result] == ["purpose"]

    def test_no_entries_returns_empty(self, mock_cfg, monkeypatch) -> None:
        _stub_embed(monkeypatch)
        assert suggest(_capture(), [], mock_cfg.lancedb_path, mock_cfg.ollama_model) == []

    def test_unroutable_capture_returns_empty(self, mock_cfg, monkeypatch) -> None:
        _stub_embed(monkeypatch)
        assert suggest(_capture(text="   "), _entries("meridian"), mock_cfg.lancedb_path, mock_cfg.ollama_model) == []
