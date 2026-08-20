"""Cross-project prior art (FEAT-024).

The shared LanceDB store is scoped by a ``project`` column, and the corpus it
holds is wildly uneven — one repo with 73 chunks next to one with 2. A single
merged relevance ranking is therefore won by whichever repo has written the
most, and a search run from the small repo returns almost nothing of its own.
These tests pin the two properties that prevent that:

  * the local pass is separate, and its hits come first (AC12);
  * the widening never leaks into an ordinary ``meridian search`` (AC13).

The store is real (a temp LanceDB, four-dimensional vectors chosen by hand);
only ``embed`` is patched, so nothing here needs Ollama and nothing here can
reach the developer's own ``~/.meridian``.

Run:  .venv/bin/pytest tests/test_prior_art.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from meridian.enrich import upsert_chunks
from meridian.registry import ProjectEntry, register
from meridian.search import (
    MISSING_FEATURE_DIR,
    MISSING_REPO_PATH,
    UNTRACKED_PROJECT,
    FeatureLocator,
    attribute_prior_art,
    clears_bar,
    relevance_bar,
    search_with_prior_art,
    semantic_search,
)

# ── fixtures and helpers ─────────────────────────────────────────────────── #

QUERY_VEC = [1.0, 0.0, 0.0, 0.0]
LOCAL = "test-project"          # matches the mock_cfg fixture's project slug
DOMINANT = "portfolio-management"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch) -> Path:
    """Per-test MERIDIAN_HOME so registry writes cannot leak between tests."""
    home = tmp_path / "meridian-home"
    monkeypatch.setenv("MERIDIAN_HOME", str(home))
    return home


@pytest.fixture(autouse=True)
def _fixed_embedding(monkeypatch) -> None:
    monkeypatch.setattr("meridian.search.embed", lambda *a, **k: QUERY_VEC)


def _text(word: str, i: int) -> str:
    return f"{word} chunk {i}: " + " ".join(f"{word}{n}" for n in range(30))


def _seed(
    db_path: Path,
    project: str,
    feat_id: str,
    source: str,
    vectors: list[list[float]],
    word: str,
) -> None:
    chunks = [_text(word, i) for i in range(len(vectors))]
    upsert_chunks(db_path, project, feat_id, source, chunks, vectors)


def _near(count: int, offset: float = 0.0) -> list[list[float]]:
    """Vectors hugging the query — every one of them a better match."""
    return [[1.0, 0.0, 0.0, offset + 0.001 * i] for i in range(count)]


def _far(count: int) -> list[list[float]]:
    """Vectors orthogonal to the query — relevant to nothing it asks."""
    return [[0.0, 1.0, 0.0, 0.001 * i] for i in range(count)]


def _uneven(db_path: Path) -> None:
    """The real corpus's shape: a 30-chunk repo against this project's one.

    Every foreign chunk is a *closer* vector match than the local one, so a
    merged ranking has no reason to keep the local row at all.
    """
    _seed(db_path, DOMINANT, "FEAT-003", "portfolio.md", _near(30), "portfolio")
    _seed(db_path, LOCAL, "FEAT-001", "local.md", _far(1), "local")


def _repo(tmp_path: Path, slug: str, feat_dir: str = "FEAT-003_shared_store",
          specs: str = "specs") -> Path:
    repo = tmp_path / "repos" / slug
    (repo / specs / feat_dir).mkdir(parents=True)
    (repo / specs / feat_dir / "spec.md").write_text("---\nid: feat-003\n---\nBody.\n")
    return repo


# ── AC12: the ordering property, on the shape that breaks it ─────────────── #


class TestUnevenCorpusOrdering:
    def test_merged_ranking_loses_the_local_hit(self, mock_cfg) -> None:
        """The precondition — without this the AC12 test proves nothing."""
        _uneven(mock_cfg.lancedb_path)

        merged = semantic_search(mock_cfg, "q", limit=5, rerank=False, all_projects=True)

        assert merged, "sanity: the store is populated"
        assert not [r for r in merged if r["project"] == LOCAL], (
            "a single merged ranking is expected to drop the local row entirely — "
            "that is the failure the separate sections exist to prevent"
        )

    def test_local_hit_is_first_and_complete(self, mock_cfg) -> None:
        """AC1/AC12: local hits come first, even against a dominant corpus."""
        _uneven(mock_cfg.lancedb_path)

        found = search_with_prior_art(mock_cfg, "q", limit=5, rerank=False)

        assert found.local, "the local pass must return this project's row"
        assert found.local[0]["project"] == LOCAL
        assert found.local[0]["source_name"] == "local.md"

    def test_sections_are_never_interleaved(self, mock_cfg) -> None:
        _uneven(mock_cfg.lancedb_path)

        found = search_with_prior_art(mock_cfg, "q", limit=5, rerank=False)

        assert all(r["project"] == LOCAL for r in found.local)
        assert found.prior_art, "the foreign corpus should still surface as prior art"
        assert all(r["project"] != LOCAL for r in found.prior_art)


# ── AC2/AC3: the section's own limits ────────────────────────────────────── #


class TestPriorArtLimits:
    def test_prior_art_limit_caps_the_section(self, mock_cfg) -> None:
        _uneven(mock_cfg.lancedb_path)
        _seed(mock_cfg.lancedb_path, "misc", "FEAT-002", "misc.md", _near(10), "misc")

        found = search_with_prior_art(
            mock_cfg, "q", limit=5, rerank=False, prior_art_limit=3, per_project=3,
        )

        assert len(found.prior_art) == 3

    def test_per_project_cap_leaves_room_for_other_repos(self, mock_cfg) -> None:
        """AC3: a 30-chunk repo must not fill the section on volume."""
        _uneven(mock_cfg.lancedb_path)
        _seed(mock_cfg.lancedb_path, "misc", "FEAT-002", "misc.md", _near(10, 0.5), "misc")
        _seed(mock_cfg.lancedb_path, "scraper", "FEAT-004", "s.md", _near(8, 0.6), "scraper")

        found = search_with_prior_art(
            mock_cfg, "q", limit=5, rerank=False, prior_art_limit=6, per_project=2,
        )

        per_project: dict[str, int] = {}
        for hit in found.prior_art:
            per_project[hit["project"]] = per_project.get(hit["project"], 0) + 1
        assert max(per_project.values()) <= 2
        assert len(per_project) >= 2, "the cap must let a second repo through"

    def test_zero_disables_the_section_entirely(self, mock_cfg) -> None:
        _uneven(mock_cfg.lancedb_path)

        found = search_with_prior_art(mock_cfg, "q", limit=5, rerank=False, prior_art_limit=0)

        assert found.local
        assert found.prior_art == []


# ── AC4: the relevance bar ───────────────────────────────────────────────── #


class TestRelevanceBar:
    def test_foreign_hits_below_the_local_bar_are_dropped(self, mock_cfg) -> None:
        """The local corpus answers the query well; weak foreign rows are noise."""
        _seed(mock_cfg.lancedb_path, LOCAL, "FEAT-001", "local.md", _near(1), "local")
        _seed(mock_cfg.lancedb_path, DOMINANT, "FEAT-003", "p.md", _far(20), "portfolio")

        found = search_with_prior_art(mock_cfg, "q", limit=5, rerank=False)

        assert found.local
        assert found.prior_art == [], (
            "no foreign row clears the bar the local hits had to clear"
        )

    def test_foreign_hits_above_the_local_bar_are_kept(self, mock_cfg) -> None:
        _seed(mock_cfg.lancedb_path, LOCAL, "FEAT-001", "local.md", _far(1), "local")
        _seed(mock_cfg.lancedb_path, DOMINANT, "FEAT-003", "p.md", _near(3), "portfolio")

        found = search_with_prior_art(mock_cfg, "q", limit=5, rerank=False)

        assert found.prior_art

    def test_no_local_hits_means_no_bar(self, mock_cfg) -> None:
        """Nothing local to calibrate against is when prior art matters most."""
        _seed(mock_cfg.lancedb_path, DOMINANT, "FEAT-003", "p.md", _far(3), "portfolio")

        found = search_with_prior_art(mock_cfg, "q", limit=5, rerank=False)

        assert found.local == []
        assert found.prior_art, "with no local evidence, every candidate is a lead"

    def test_bar_is_the_weakest_local_hit(self) -> None:
        bar = relevance_bar([{"_distance": 0.1}, {"_distance": 0.9}])
        assert bar == ("_distance", 0.9)
        assert clears_bar({"_distance": 0.5}, bar)
        assert not clears_bar({"_distance": 1.2}, bar)

    def test_bar_inverts_for_rerank_scores(self) -> None:
        bar = relevance_bar([{"rerank_score": 8.0}, {"rerank_score": 2.0}])
        assert bar == ("rerank_score", 2.0)
        assert clears_bar({"rerank_score": 3.0}, bar)
        assert not clears_bar({"rerank_score": 1.0}, bar)

    def test_incomparable_hit_is_kept_not_dropped(self) -> None:
        """Losing research to a units mismatch would look like a broken feature."""
        assert clears_bar({"rerank_score": 5.0}, ("_distance", 0.2))


# ── AC5–AC7: attribution ─────────────────────────────────────────────────── #


class TestAttribution:
    def _hit(self, project: str = DOMINANT, feat_id: str = "FEAT-003") -> dict:
        return {
            "project": project, "feat_id": feat_id,
            "source_name": "paper.pdf", "chunk_idx": 2,
            "text": "some research", "_distance": 0.2,
        }

    def test_hit_names_project_feature_and_source(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, DOMINANT)
        entries = [ProjectEntry(DOMINANT, repo, "", True)]

        (row,) = attribute_prior_art([self._hit()], entries)

        assert row["project"] == DOMINANT
        assert row["feat_id"] == "FEAT-003"
        assert row["source_name"] == "paper.pdf"

    def test_feature_directory_is_absolute_and_openable(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, DOMINANT)
        entries = [ProjectEntry(DOMINANT, repo, "", True)]

        (row,) = attribute_prior_art([self._hit()], entries)

        assert row["resolvable"] is True
        assert row["unresolvable_reason"] is None
        assert Path(row["feat_path"]).is_absolute()
        assert Path(row["feat_path"]) == repo / "specs" / "FEAT-003_shared_store"
        assert (Path(row["feat_path"]) / "spec.md").exists()
        assert row["project_path"] == str(repo)

    def test_untracked_project_is_marked_not_omitted(self) -> None:
        (row,) = attribute_prior_art([self._hit(project="never-registered")], [])

        assert row["resolvable"] is False
        assert row["unresolvable_reason"] == UNTRACKED_PROJECT
        assert row["text"] == "some research", "the research itself is still returned"

    def test_moved_checkout_is_marked_not_omitted(self, tmp_path: Path) -> None:
        gone = tmp_path / "on-another-disk"
        entries = [ProjectEntry(DOMINANT, gone, "", False)]

        (row,) = attribute_prior_art([self._hit()], entries)

        assert row["resolvable"] is False
        assert row["unresolvable_reason"] == MISSING_REPO_PATH
        assert row["project_path"] == str(gone), "still name where it used to be"

    def test_renamed_feature_directory_still_names_the_repo(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, DOMINANT, feat_dir="FEAT-999_something_else")
        entries = [ProjectEntry(DOMINANT, repo, "", True)]

        (row,) = attribute_prior_art([self._hit()], entries)

        assert row["resolvable"] is False
        assert row["unresolvable_reason"] == MISSING_FEATURE_DIR
        assert row["project_path"] == str(repo)

    def test_foreign_repo_with_a_custom_specs_path(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, DOMINANT, specs="docs/specs")
        (repo / ".meridian.toml").write_text('[meridian]\nspecs_path = "docs/specs"\n')
        entries = [ProjectEntry(DOMINANT, repo, "", True)]

        (row,) = attribute_prior_art([self._hit()], entries)

        assert row["resolvable"] is True
        assert Path(row["feat_path"]) == repo / "docs" / "specs" / "FEAT-003_shared_store"

    def test_locator_reads_the_registry_when_given_no_entries(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, DOMINANT)
        register(DOMINANT, repo)

        _, feat_dir, reason = FeatureLocator().locate(DOMINANT, "FEAT-003")

        assert reason is None
        assert feat_dir == repo / "specs" / "FEAT-003_shared_store"


# ── CLI surface ──────────────────────────────────────────────────────────── #


@pytest.fixture
def proj(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "specs").mkdir(parents=True)
    (root / ".meridian.toml").write_text(
        "[meridian]\n"
        f'project = "{LOCAL}"\n'
        'specs_path = "specs"\n'
        f'lancedb_path = "{tmp_path / "lancedb"}"\n'
    )
    return root


def _invoke(monkeypatch, proj: Path, args: list[str]):
    from typer.testing import CliRunner

    from meridian.cli import app

    monkeypatch.chdir(proj)
    return CliRunner().invoke(app, args)


class TestDefaultPathIsNeverWidened:
    """AC13: the widening is opt-in, per query, and must not leak."""

    def test_plain_search_returns_only_this_project(self, monkeypatch, proj: Path) -> None:
        _uneven(proj.parent / "lancedb")

        result = _invoke(monkeypatch, proj, ["search", "q", "--no-rerank", "--json"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["results"], "the local row must still be found"
        assert {r["project"] for r in payload["results"]} == {LOCAL}
        assert payload["prior_art"] == []
        assert payload["prior_art_searched"] is False

    def test_plain_search_report_mentions_no_foreign_project(
        self, monkeypatch, proj: Path
    ) -> None:
        _uneven(proj.parent / "lancedb")

        result = _invoke(monkeypatch, proj, ["search", "q", "--no-rerank"])

        assert result.exit_code == 0, result.output
        assert DOMINANT not in result.output
        assert "Prior art" not in result.output


class TestPriorArtCli:
    def test_all_projects_prints_two_distinct_sections(self, monkeypatch, proj: Path) -> None:
        _uneven(proj.parent / "lancedb")

        result = _invoke(
            monkeypatch, proj, ["search", "q", "--no-rerank", "--all-projects"]
        )

        assert result.exit_code == 0, result.output
        assert "local.md" in result.output
        assert "Prior art" in result.output
        assert result.output.index("local.md") < result.output.index("Prior art"), (
            "local hits come first and complete"
        )
        assert f"{DOMINANT}/FEAT-003" in result.output

    def test_empty_prior_art_is_stated_not_silent(self, monkeypatch, proj: Path) -> None:
        """AC4: an empty section is printed, never left as silence."""
        db = proj.parent / "lancedb"
        _seed(db, LOCAL, "FEAT-001", "local.md", _near(1), "local")
        _seed(db, DOMINANT, "FEAT-003", "p.md", _far(5), "portfolio")

        result = _invoke(
            monkeypatch, proj, ["search", "q", "--no-rerank", "--all-projects"]
        )

        assert result.exit_code == 0, result.output
        assert "Prior art" in result.output
        assert "No prior art found" in result.output

    def test_unresolvable_project_is_shown_with_its_reason(
        self, monkeypatch, proj: Path
    ) -> None:
        _uneven(proj.parent / "lancedb")

        result = _invoke(
            monkeypatch, proj, ["search", "q", "--no-rerank", "--all-projects"]
        )

        assert "unresolvable" in result.output
        assert "not tracked" in result.output

    def test_resolvable_hit_prints_the_feature_directory(
        self, monkeypatch, proj: Path, tmp_path: Path
    ) -> None:
        _uneven(proj.parent / "lancedb")
        repo = _repo(tmp_path, DOMINANT)
        register(DOMINANT, repo)

        result = _invoke(
            monkeypatch, proj,
            ["search", "q", "--no-rerank", "--all-projects", "--prior-art", "1"],
        )

        # The path is the actionable part of a prior-art hit; Rich must not
        # have folded or truncated it away.
        assert "FEAT-003_shared_store" in result.output
        assert "unresolvable" not in result.output

    def test_json_carries_every_attribution_field(
        self, monkeypatch, proj: Path, tmp_path: Path
    ) -> None:
        """AC8: a skill branches on data, not on a parsed table."""
        _uneven(proj.parent / "lancedb")
        repo = _repo(tmp_path, DOMINANT)
        register(DOMINANT, repo)

        result = _invoke(
            monkeypatch, proj,
            ["search", "q", "--no-rerank", "--all-projects", "--json"],
        )

        payload = json.loads(result.output)
        assert payload["all_projects"] is True
        assert payload["prior_art_searched"] is True
        assert {r["project"] for r in payload["results"]} == {LOCAL}
        hit = payload["prior_art"][0]
        assert {
            "project", "feat_id", "label", "source_name", "chunk_idx", "score",
            "text", "project_path", "feat_path", "resolvable", "unresolvable_reason",
        } <= set(hit)
        assert hit["project"] == DOMINANT
        assert hit["label"] == f"{DOMINANT}/FEAT-003", "never resolved against local specs"
        assert hit["resolvable"] is True
        assert Path(hit["feat_path"]).is_absolute()

    def test_per_project_flag_is_honoured_end_to_end(self, monkeypatch, proj: Path) -> None:
        db = proj.parent / "lancedb"
        _uneven(db)
        _seed(db, "misc", "FEAT-002", "misc.md", _near(10, 0.5), "misc")

        result = _invoke(
            monkeypatch, proj,
            ["search", "q", "--no-rerank", "--all-projects", "--json",
             "--per-project", "1", "--prior-art", "4"],
        )

        payload = json.loads(result.output)
        projects = [r["project"] for r in payload["prior_art"]]
        assert len(projects) == len(set(projects)), "one hit per project at --per-project 1"
