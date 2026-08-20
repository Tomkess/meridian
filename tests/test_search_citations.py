"""Citations in search output (FEAT-025 AC1) — the integration seam.

FEAT-024 owned ``search.py`` and the ``search`` command; FEAT-025 owned
``citations.py``. Neither could write this test, because the wiring only exists
once both are merged: ``meridian search`` emits a citation for every hit, and
that exact string resolves through ``meridian cite``.

That round trip is the whole point. A citation format both halves agree on but
neither can resolve is the regression this file exists to catch, and it is
invisible to a test that only checks the string's shape.

The store is a real temp LanceDB with hand-picked four-dimensional vectors;
only ``embed`` is patched, so nothing here needs Ollama and nothing here can
reach the developer's own ``~/.meridian``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from meridian.enrich import upsert_chunks

QUERY_VEC = [1.0, 0.0, 0.0, 0.0]
LOCAL = "test-project"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "meridian-home"
    monkeypatch.setenv("MERIDIAN_HOME", str(home))
    return home


@pytest.fixture(autouse=True)
def _fixed_embedding(monkeypatch) -> None:
    monkeypatch.setattr("meridian.search.embed", lambda *a, **k: QUERY_VEC)


@pytest.fixture
def proj(tmp_path: Path) -> Path:
    """A repo whose feature really holds the source the chunks came from.

    `meridian cite` reports the source path, so the file has to exist for the
    round trip to mean anything.
    """
    root = tmp_path / "repo"
    feat_dir = root / "specs" / "FEAT-001_indexing"
    (feat_dir / "sources").mkdir(parents=True)
    (feat_dir / "sources" / "notes.txt").write_text("alpha beta\ngamma delta\n")
    (feat_dir / "spec.md").write_text(
        "---\nid: feat-001\nname: Indexing\nstatus: draft\n---\n\n## Summary\n"
    )
    (root / ".meridian.toml").write_text(
        "[meridian]\n"
        f'project = "{LOCAL}"\n'
        'specs_path = "specs"\n'
        f'lancedb_path = "{tmp_path / "lancedb"}"\n'
    )
    upsert_chunks(
        tmp_path / "lancedb", LOCAL, "FEAT-001", "notes.txt",
        ["alpha beta", "gamma delta"],
        [[1.0, 0.0, 0.0, 0.0], [0.9, 0.1, 0.0, 0.0]],
    )
    return root


def _invoke(monkeypatch, proj: Path, args: list[str]):
    from typer.testing import CliRunner

    from meridian.cli import app

    monkeypatch.chdir(proj)
    return CliRunner().invoke(app, args)


class TestCitationsInSearchOutput:
    def test_json_carries_a_citation_for_every_hit(self, monkeypatch, proj: Path) -> None:
        result = _invoke(monkeypatch, proj, ["search", "alpha", "--no-rerank", "--json"])

        assert result.exit_code == 0, result.output
        hits = json.loads(result.output)["results"]
        assert hits, "the fixture rows must be found"
        for hit in hits:
            assert hit["citation"] == (
                f"{hit['project']}:{hit['feat_id']}:{hit['source_name']}#{hit['chunk_idx']}"
            )

    def test_table_output_prints_the_citation(self, monkeypatch, proj: Path) -> None:
        result = _invoke(monkeypatch, proj, ["search", "alpha", "--no-rerank"])

        assert result.exit_code == 0, result.output
        assert "cite:" in result.output
        assert f"{LOCAL}:FEAT-001:notes.txt#" in result.output.replace("\n", "")

    def test_emitted_citation_resolves_through_cite(self, monkeypatch, proj: Path) -> None:
        """The round trip. Format agreement is not resolution."""
        search = _invoke(monkeypatch, proj, ["search", "alpha", "--no-rerank", "--json"])
        citation = json.loads(search.output)["results"][0]["citation"]

        resolved = _invoke(monkeypatch, proj, ["cite", citation])

        assert resolved.exit_code == 0, resolved.output
        # The chunk's own text came back, not merely a restated citation.
        assert "alpha beta" in resolved.output.replace("\n", " ")

    def test_uncitable_row_degrades_to_none_rather_than_a_broken_string(self) -> None:
        """A row that cannot name a chunk must not produce a plausible citation.

        Pre-FEAT-007 rows carry no project. Emitting something that looks like a
        citation but resolves to nothing is worse than emitting nothing, because
        it would be copied into a brief and trusted.
        """
        from meridian.cli import _citation_of

        assert _citation_of({"feat_id": "FEAT-001", "source_name": "n.txt",
                             "chunk_idx": 0}) is None
        assert _citation_of({"project": "p", "feat_id": "FEAT-001",
                             "source_name": "n.txt", "chunk_idx": None}) is None
