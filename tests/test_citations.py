"""Citation format, resolution, and the search → cite round-trip (FEAT-025).

The round-trip is the test that matters. A format both sides agree on but
neither can resolve passes every format-matching assertion and is worthless, so
``TestRoundTrip`` drives a real LanceDB store: embed → search → format the
citation from the hit → parse it → resolve it → compare the text.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from meridian.citations import (
    Citation,
    CitationFormatError,
    CitationMissingError,
    CitationProjectError,
    format_citation,
    parse_citation,
    resolve,
    resolve_citation,
)
from meridian.config import MeridianConfig
from meridian.enrich import upsert_chunks

VECTOR = [0.1, 0.2, 0.3, 0.4]


def _chunk(word: str = "word") -> str:
    """A chunk long enough to clear chunk_text's 80-character floor."""
    return " ".join(f"{word}{i}" for i in range(100))


def _make_feature(cfg: MeridianConfig, feat_id: str = "FEAT-001",
                  slug: str = "citations") -> Path:
    feat_dir = cfg.specs_path / f"{feat_id}_{slug}"
    (feat_dir / "sources").mkdir(parents=True)
    (feat_dir / "spec.md").write_text(
        f"---\nid: {feat_id.lower()}\nname: Cited\nstatus: draft\nsources: []\n---\nBody.\n"
    )
    return feat_dir


def _store(cfg: MeridianConfig, feat_id: str, source: str, chunks: list[str],
           project: str | None = None) -> None:
    upsert_chunks(
        cfg.lancedb_path, project or cfg.project, feat_id, source,
        chunks, [VECTOR] * len(chunks),
    )


# ── format + parse ────────────────────────────────────────────────────────── #


class TestFormat:
    def test_row_renders_canonical_citation(self) -> None:
        row = {"project": "meridian", "feat_id": "FEAT-025",
               "source_name": "paper.txt", "chunk_idx": 3}
        assert format_citation(row) == "meridian:FEAT-025:paper.txt#3"

    def test_feat_id_is_upper_cased(self) -> None:
        row = {"project": "p", "feat_id": "feat-007",
               "source_name": "a.txt", "chunk_idx": 0}
        assert format_citation(row) == "p:FEAT-007:a.txt#0"

    def test_chunk_zero_is_not_treated_as_missing(self) -> None:
        """chunk_idx 0 is falsy — the first chunk of every source."""
        row = {"project": "p", "feat_id": "FEAT-001",
               "source_name": "a.txt", "chunk_idx": 0}
        assert format_citation(row).endswith("#0")

    def test_missing_field_is_an_error_not_a_placeholder(self) -> None:
        with pytest.raises(CitationFormatError, match="source_name"):
            format_citation({"project": "p", "feat_id": "FEAT-001", "chunk_idx": 1})


class TestParse:
    def test_round_trips_through_string(self) -> None:
        c = Citation("meridian", "FEAT-025", "paper.txt", 3)
        assert parse_citation(str(c)) == c

    def test_source_name_may_contain_a_colon(self) -> None:
        """A URL slug carries a port; splitting greedily would truncate it."""
        c = parse_citation("p:FEAT-001:localhost:8080_docs.txt#2")
        assert c.source_name == "localhost:8080_docs.txt"
        assert c.chunk_idx == 2

    def test_source_name_may_contain_a_hash(self) -> None:
        c = parse_citation("p:FEAT-001:notes#1_draft.txt#7")
        assert c.source_name == "notes#1_draft.txt"
        assert c.chunk_idx == 7

    def test_markdown_wrapping_is_tolerated(self) -> None:
        for wrapped in ("`p:FEAT-001:a.txt#1`", "[p:FEAT-001:a.txt#1]",
                        "  p:FEAT-001:a.txt#1  "):
            assert parse_citation(wrapped) == Citation("p", "FEAT-001", "a.txt", 1)

    def test_lowercase_feat_id_normalises(self) -> None:
        assert parse_citation("p:feat-001:a.txt#1").feat_id == "FEAT-001"

    @pytest.mark.parametrize("bad", [
        "",
        "not a citation",
        "p:FEAT-001:a.txt",          # no chunk index
        "p:FEAT-001:#1",             # no source name
        "p:NOTFEAT:a.txt#1",         # not a feature id
        "p:FEAT-001:a.txt#x",        # index is not a number
        ":FEAT-001:a.txt#1",         # no project
    ])
    def test_malformed_raises(self, bad: str) -> None:
        with pytest.raises(CitationFormatError):
            parse_citation(bad)


# ── resolution ────────────────────────────────────────────────────────────── #


class TestResolveLocal:
    def test_returns_the_stored_text(self, mock_cfg: MeridianConfig) -> None:
        _make_feature(mock_cfg)
        _store(mock_cfg, "FEAT-001", "paper.txt", [_chunk("a"), _chunk("b")])

        resolved = resolve("test-project:FEAT-001:paper.txt#1", mock_cfg)
        assert resolved.text == _chunk("b")

    def test_reports_the_source_path(self, mock_cfg: MeridianConfig) -> None:
        feat_dir = _make_feature(mock_cfg)
        (feat_dir / "sources" / "paper.txt").write_text(_chunk("a"))
        _store(mock_cfg, "FEAT-001", "paper.txt", [_chunk("a")])

        resolved = resolve("test-project:FEAT-001:paper.txt#0", mock_cfg)
        assert resolved.source_path == feat_dir / "sources" / "paper.txt"
        assert resolved.source_exists

    def test_missing_chunk_raises_rather_than_returning_empty(
        self, mock_cfg: MeridianConfig
    ) -> None:
        """AC3: the whole value is checkability, so a gone chunk is loud."""
        _make_feature(mock_cfg)
        _store(mock_cfg, "FEAT-001", "paper.txt", [_chunk("a")])

        with pytest.raises(CitationMissingError, match="paper.txt#9"):
            resolve("test-project:FEAT-001:paper.txt#9", mock_cfg)

    def test_missing_chunk_names_what_is_missing(self, mock_cfg: MeridianConfig) -> None:
        _make_feature(mock_cfg)
        _store(mock_cfg, "FEAT-001", "paper.txt", [_chunk("a")])

        with pytest.raises(CitationMissingError) as excinfo:
            resolve("test-project:FEAT-001:gone.txt#0", mock_cfg)
        message = str(excinfo.value)
        assert "gone.txt" in message and "FEAT-001" in message
        assert "test-project" in message

    def test_empty_store_is_a_missing_chunk_not_a_crash(
        self, mock_cfg: MeridianConfig
    ) -> None:
        _make_feature(mock_cfg)
        with pytest.raises(CitationMissingError):
            resolve("test-project:FEAT-001:paper.txt#0", mock_cfg)

    def test_moved_source_file_still_resolves(self, mock_cfg: MeridianConfig) -> None:
        """The chunk is the evidence; the file path is a convenience pointer.

        A deleted source file leaves the claim checkable — the cited text is
        right there — so this reports rather than raises.
        """
        _make_feature(mock_cfg)
        _store(mock_cfg, "FEAT-001", "paper.txt", [_chunk("a")])

        resolved = resolve("test-project:FEAT-001:paper.txt#0", mock_cfg)
        assert resolved.text == _chunk("a")
        assert not resolved.source_exists

    def test_unknown_feature_directory_yields_no_source_path(
        self, mock_cfg: MeridianConfig
    ) -> None:
        _store(mock_cfg, "FEAT-404", "paper.txt", [_chunk("a")])
        resolved = resolve("test-project:FEAT-404:paper.txt#0", mock_cfg)
        assert resolved.source_path is None
        assert not resolved.source_exists

    def test_apostrophe_in_source_name_does_not_break_the_predicate(
        self, mock_cfg: MeridianConfig
    ) -> None:
        _make_feature(mock_cfg)
        _store(mock_cfg, "FEAT-001", "O'Reilly_report.txt", [_chunk("a")])
        resolved = resolve("test-project:FEAT-001:O'Reilly_report.txt#0", mock_cfg)
        assert resolved.text == _chunk("a")


@pytest.fixture
def private_registry(tmp_path: Path, monkeypatch) -> Path:
    """A project registry scoped to one test.

    The session-wide MERIDIAN_HOME is shared, so a project registered by one
    test stays visible to the next — which would make "this project is not
    tracked" pass or fail depending on test order.
    """
    home = tmp_path / "meridian-home"
    home.mkdir()
    monkeypatch.setenv("MERIDIAN_HOME", str(home))
    return home


class TestResolveAcrossProjects:
    """AC4: a foreign citation resolves when the project is tracked."""

    def _register_foreign(self, tmp_path: Path, mock_cfg: MeridianConfig,
                          slug: str = "other-project") -> Path:
        from meridian.registry import register

        root = tmp_path / slug
        (root / "specs").mkdir(parents=True)
        (root / ".meridian.toml").write_text(
            "[meridian]\n"
            f'project = "{slug}"\n'
            'specs_path = "specs"\n'
            f'lancedb_path = "{mock_cfg.lancedb_path}"\n'
        )
        register(slug, root)
        return root

    def test_tracked_foreign_project_resolves(
        self, mock_cfg: MeridianConfig, other_cfg: MeridianConfig, tmp_path: Path,
        private_registry: Path,
    ) -> None:
        root = self._register_foreign(tmp_path, mock_cfg)
        feat_dir = root / "specs" / "FEAT-002_theirs"
        (feat_dir / "sources").mkdir(parents=True)
        (feat_dir / "spec.md").write_text(
            "---\nid: feat-002\nname: Theirs\nstatus: draft\n---\nBody.\n"
        )
        (feat_dir / "sources" / "theirs.txt").write_text(_chunk("t"))
        _store(other_cfg, "FEAT-002", "theirs.txt", [_chunk("t")])

        resolved = resolve("other-project:FEAT-002:theirs.txt#0", mock_cfg)
        assert resolved.text == _chunk("t")
        assert resolved.source_path == feat_dir / "sources" / "theirs.txt"

    def test_untracked_project_is_not_reported_as_a_missing_chunk(
        self, mock_cfg: MeridianConfig, other_cfg: MeridianConfig,
        private_registry: Path,
    ) -> None:
        """"I cannot see that repo" and "the evidence is gone" are opposite facts."""
        _store(other_cfg, "FEAT-002", "theirs.txt", [_chunk("t")])

        with pytest.raises(CitationProjectError, match="not tracked"):
            resolve("other-project:FEAT-002:theirs.txt#0", mock_cfg)

    def test_untracked_project_error_is_not_a_missing_chunk_error(
        self, mock_cfg: MeridianConfig, private_registry: Path,
    ) -> None:
        with pytest.raises(CitationProjectError) as excinfo:
            resolve("nowhere:FEAT-002:x.txt#0", mock_cfg)
        assert not isinstance(excinfo.value, CitationMissingError)

    def test_tracked_project_whose_path_vanished_is_reported_as_such(
        self, mock_cfg: MeridianConfig, tmp_path: Path, private_registry: Path,
    ) -> None:
        import shutil

        root = self._register_foreign(tmp_path, mock_cfg)
        shutil.rmtree(root)

        with pytest.raises(CitationProjectError, match="no longer resolves"):
            resolve("other-project:FEAT-002:theirs.txt#0", mock_cfg)


# ── the round-trip (AC13) ─────────────────────────────────────────────────── #


class TestRoundTrip:
    """A citation emitted from a search result must resolve back to that text."""

    def test_search_hit_citation_resolves_to_the_same_text(
        self, mock_cfg: MeridianConfig
    ) -> None:
        from meridian.search import semantic_search

        _make_feature(mock_cfg)
        chunks = [_chunk("alpha"), _chunk("beta"), _chunk("gamma")]
        _store(mock_cfg, "FEAT-001", "paper.txt", chunks)

        with patch("meridian.search.embed", side_effect=lambda *a, **k: VECTOR):
            results = semantic_search(mock_cfg, "anything", limit=3, rerank=False)
        assert results, "search returned nothing — the round-trip cannot be tested"

        for row in results:
            citation = format_citation(row)
            resolved = resolve_citation(parse_citation(citation), mock_cfg)
            assert resolved.text == row["text"], (
                f"{citation} resolved to different text than the search hit it "
                "was built from"
            )

    def test_round_trip_survives_a_source_name_with_punctuation(
        self, mock_cfg: MeridianConfig
    ) -> None:
        from meridian.search import semantic_search

        _make_feature(mock_cfg)
        _store(mock_cfg, "FEAT-001", "localhost:8080_docs#v2.txt", [_chunk("x")])

        with patch("meridian.search.embed", side_effect=lambda *a, **k: VECTOR):
            results = semantic_search(mock_cfg, "anything", limit=1, rerank=False)

        citation = format_citation(results[0])
        assert resolve(citation, mock_cfg).text == results[0]["text"]


# ── the CLI (AC2–AC4) ─────────────────────────────────────────────────────── #


@pytest.fixture
def runner():
    from typer.testing import CliRunner

    return CliRunner()


@pytest.fixture
def cited_project(tmp_path: Path, monkeypatch) -> MeridianConfig:
    """A project on disk, with one cited chunk in its own LanceDB store."""
    from meridian.config import load_config

    root = tmp_path / "cited-project"
    (root / "specs").mkdir(parents=True)
    (root / ".meridian.toml").write_text(
        "[meridian]\n"
        'project = "cited-project"\n'
        'specs_path = "specs"\n'
        f'lancedb_path = "{tmp_path / "lancedb"}"\n'
    )
    cfg = load_config(root)
    feat_dir = cfg.specs_path / "FEAT-001_citations"
    (feat_dir / "sources").mkdir(parents=True)
    (feat_dir / "spec.md").write_text(
        "---\nid: feat-001\nname: Cited\nstatus: draft\n---\nBody.\n"
    )
    (feat_dir / "sources" / "paper.txt").write_text(_chunk("a"))
    _store(cfg, "FEAT-001", "paper.txt", [_chunk("a")])
    monkeypatch.chdir(root)
    return cfg


class TestCiteCommand:
    def _invoke(self, runner, args: list[str]):
        from meridian.cli import app

        return runner.invoke(app, ["cite", *args])

    def test_prints_the_chunk_text(self, runner, cited_project) -> None:
        result = self._invoke(runner, ["cited-project:FEAT-001:paper.txt#0"])
        assert result.exit_code == 0
        assert "a0 a1" in result.stdout

    def test_prints_the_source_path(self, runner, cited_project) -> None:
        result = self._invoke(runner, ["cited-project:FEAT-001:paper.txt#0"])
        assert "paper.txt" in result.stdout

    def test_missing_chunk_exits_non_zero(self, runner, cited_project) -> None:
        result = self._invoke(runner, ["cited-project:FEAT-001:paper.txt#42"])
        assert result.exit_code == 1
        assert "paper.txt#42" in result.stdout

    def test_malformed_citation_exits_non_zero(self, runner, cited_project) -> None:
        result = self._invoke(runner, ["definitely not a citation"])
        assert result.exit_code == 1

    def test_untracked_project_exits_non_zero_and_says_so(
        self, runner, cited_project, private_registry: Path,
    ) -> None:
        result = self._invoke(runner, ["nowhere:FEAT-001:paper.txt#0"])
        assert result.exit_code == 1
        assert "not tracked" in result.stdout

    def test_json_carries_the_text_and_identity(self, runner, cited_project) -> None:
        result = self._invoke(runner, ["cited-project:FEAT-001:paper.txt#0", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["resolved"] is True
        assert payload["feat_id"] == "FEAT-001"
        assert payload["chunk_idx"] == 0
        assert payload["text"].startswith("a0 a1")
        assert payload["source_exists"] is True

    def test_json_failure_is_still_json_and_still_non_zero(
        self, runner, cited_project
    ) -> None:
        """An agent must be able to branch on the failure, not parse prose."""
        result = self._invoke(runner, ["cited-project:FEAT-001:paper.txt#42", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["resolved"] is False
        assert payload["error"] == "chunk_missing"

    def test_json_reports_an_untracked_project_distinctly(
        self, runner, cited_project, private_registry: Path,
    ) -> None:
        result = self._invoke(runner, ["nowhere:FEAT-001:paper.txt#0", "--json"])
        payload = json.loads(result.stdout)
        assert payload["error"] == "project_unreachable"

    def test_bracketed_text_in_a_chunk_survives_rendering(
        self, runner, tmp_path: Path, monkeypatch
    ) -> None:
        """Research prose is full of [brackets]; Rich would eat them as markup."""
        from meridian.config import load_config

        root = tmp_path / "bracket-project"
        (root / "specs").mkdir(parents=True)
        (root / ".meridian.toml").write_text(
            "[meridian]\n"
            'project = "bracket-project"\n'
            'specs_path = "specs"\n'
            f'lancedb_path = "{tmp_path / "lancedb"}"\n'
        )
        cfg = load_config(root)
        text = "[FEAT-902 / watchfiles_notes] the debounce " + _chunk("w")
        _store(cfg, "FEAT-001", "notes.txt", [text])
        monkeypatch.chdir(root)

        result = self._invoke(runner, ["bracket-project:FEAT-001:notes.txt#0"])
        assert result.exit_code == 0
        assert "[FEAT-902 / watchfiles_notes]" in result.stdout
