"""`summaries/` is never indexed (FEAT-025, AC10–AC12).

The failure this guards against is a citation loop: index a research brief, and
the next `/research` retrieves the model's own prior conclusion, cites it as
evidence, and writes a more confident version of it. It degrades *silently* —
every round reads better than the last, because a corpus of your own output
agrees with you by construction.

Until now the exclusion held by accident: `reindex_all` globs `sources/` and
never looks at `summaries/`. These tests make it hold on purpose, so widening
that glob fails here instead of in six months' worth of briefs.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import patch

import pytest

from meridian.config import MeridianConfig
from meridian.enrich import (
    SYNTHESIS_DIRS,
    enrich_feature,
    indexable_sources,
    is_synthesis_path,
    reindex_all,
    search_similar,
)

VECTOR = [0.1, 0.2, 0.3, 0.4]
BODY = " ".join(f"w{i}" for i in range(300))


def _feature(cfg: MeridianConfig, feat_id: str = "FEAT-001") -> Path:
    feat_dir = cfg.specs_path / f"{feat_id}_loop"
    (feat_dir / "sources").mkdir(parents=True)
    (feat_dir / "summaries").mkdir(parents=True)
    (feat_dir / "spec.md").write_text(
        f"---\nid: {feat_id.lower()}\nname: Loop\nstatus: draft\nsources: []\n---\nBody.\n"
    )
    return feat_dir


def _all_source_names(cfg: MeridianConfig) -> set[str]:
    rows = search_similar(cfg.lancedb_path, VECTOR, limit=1000, project=cfg.project)
    return {r["source_name"] for r in rows}


# ── AC10: a file in summaries/ produces no chunk ──────────────────────────── #


class TestSummariesAreNeverIndexed:
    def test_brief_in_summaries_produces_no_chunk_after_full_rebuild(
        self, mock_cfg: MeridianConfig
    ) -> None:
        feat_dir = _feature(mock_cfg)
        (feat_dir / "sources" / "paper.txt").write_text(BODY)
        (feat_dir / "summaries" / "research-2026-08-20.md").write_text(BODY)
        (feat_dir / "summaries" / "research-2026-08-20.txt").write_text(BODY)
        (feat_dir / "summaries" / "paper-brief.notes.md").write_text(BODY)

        with patch("meridian.enrich.embed", side_effect=lambda *a, **k: VECTOR):
            stats = reindex_all(mock_cfg)

        assert stats["sources"] == 1, "only sources/paper.txt is corpus"
        assert _all_source_names(mock_cfg) == {"paper.txt"}

    def test_empty_sources_with_a_full_summaries_indexes_nothing(
        self, mock_cfg: MeridianConfig
    ) -> None:
        feat_dir = _feature(mock_cfg)
        (feat_dir / "summaries" / "research-2026-08-20.md").write_text(BODY)

        with patch("meridian.enrich.embed", side_effect=lambda *a, **k: VECTOR):
            stats = reindex_all(mock_cfg)

        assert stats["chunks"] == 0
        assert _all_source_names(mock_cfg) == set()

    def test_symlink_from_sources_into_summaries_is_skipped(
        self, mock_cfg: MeridianConfig
    ) -> None:
        """The realistic back door: make the brief searchable "just this once"."""
        feat_dir = _feature(mock_cfg)
        brief = feat_dir / "summaries" / "research-2026-08-20.txt"
        brief.write_text(BODY)
        (feat_dir / "sources" / "brief-link.txt").symlink_to(brief)

        with patch("meridian.enrich.embed", side_effect=lambda *a, **k: VECTOR):
            reindex_all(mock_cfg)

        assert _all_source_names(mock_cfg) == set()

    def test_indexable_sources_returns_nothing_for_a_summaries_dir(
        self, mock_cfg: MeridianConfig
    ) -> None:
        feat_dir = _feature(mock_cfg)
        (feat_dir / "summaries" / "research-2026-08-20.txt").write_text(BODY)
        assert indexable_sources(feat_dir / "summaries") == []

    def test_ordinary_sources_still_index(self, mock_cfg: MeridianConfig) -> None:
        """The exclusion must not be so broad that it eats the corpus."""
        feat_dir = _feature(mock_cfg)
        (feat_dir / "sources" / "paper.txt").write_text(BODY)
        (feat_dir / "sources" / "shot.notes.md").write_text(BODY)

        assert {p.name for p in indexable_sources(feat_dir / "sources")} == {
            "paper.txt", "shot.notes.md",
        }


class TestIsSynthesisPath:
    @pytest.mark.parametrize("path", [
        "summaries/research-2026-08-20.md",
        "/repo/specs/FEAT-001_x/summaries/paper-brief.md",
        "specs/FEAT-001_x/summaries/nested/deep.txt",
    ])
    def test_inside_summaries_is_synthesis(self, path: str) -> None:
        assert is_synthesis_path(path)

    @pytest.mark.parametrize("path", [
        "sources/paper.txt",
        "/repo/specs/FEAT-001_x/sources/paper.txt",
        "summaries",  # a *file* called summaries is not a summaries directory
    ])
    def test_outside_summaries_is_not(self, path: str) -> None:
        assert not is_synthesis_path(path)


# ── AC11: the reason is recorded in the code ──────────────────────────────── #


class TestTheReasonIsInTheCode:
    """A rule whose reason lives only in a spec gets removed by whoever is
    tidying up next year and never reads the spec."""

    def test_enrich_module_explains_the_loop(self) -> None:
        import meridian.enrich as enrich_mod

        source = inspect.getsource(enrich_mod)
        marker = source[source.index("SYNTHESIS_DIRS") - 2000:source.index("SYNTHESIS_DIRS")]
        for phrase in ("evidence", "loop", "silent"):
            assert phrase in marker.lower(), (
                f"the summaries exclusion does not explain '{phrase}' — AC11 "
                "requires the reason in the code, not only in the spec"
            )

    def test_is_synthesis_path_is_documented(self) -> None:
        assert is_synthesis_path.__doc__ and "symlink" in is_synthesis_path.__doc__


# ── AC12: no flag exists to index summaries/ ──────────────────────────────── #


class TestNoEscapeHatch:
    """"There is no flag to index summaries/, because the flag would be used."""

    def test_no_cli_option_mentions_summaries(self) -> None:
        from typer.main import get_command

        from meridian.cli import app

        click_app = get_command(app)
        offenders = []
        for name, command in click_app.commands.items():
            for param in command.params:
                haystack = " ".join(
                    str(x) for x in (list(getattr(param, "opts", []) or []),
                                     getattr(param, "help", "") or "")
                ).lower()
                if "summar" in haystack:
                    offenders.append(f"{name}:{param.name}")
        assert not offenders, (
            f"A flag to index summaries/ exists: {offenders}. It would be used."
        )

    def test_reindex_takes_no_include_flag(self) -> None:
        params = set(inspect.signature(reindex_all).parameters)
        assert params == {"cfg"}, (
            f"reindex_all grew parameters {params - {'cfg'}} — an opt-in to index "
            "synthesis must not exist"
        )

    def test_synthesis_dirs_is_not_configurable(self) -> None:
        """A config key would be the same escape hatch with extra steps."""
        from meridian.config import MeridianConfig as Cfg

        assert not any(
            "summar" in f.lower() or "synthesis" in f.lower()
            for f in Cfg.__dataclass_fields__
        )
        assert isinstance(SYNTHESIS_DIRS, frozenset)


# ── the ingest door: enrich pointed at a brief ────────────────────────────── #


class TestEnrichRefusesSynthesis:
    def test_enriching_a_brief_is_refused(self, mock_cfg: MeridianConfig) -> None:
        feat_dir = _feature(mock_cfg)
        brief = feat_dir / "summaries" / "research-2026-08-20.md"
        brief.write_text(BODY)

        with patch("meridian.enrich.embed", side_effect=lambda *a, **k: VECTOR):
            with pytest.raises(RuntimeError, match="summaries/"):
                enrich_feature(mock_cfg, "feat-001", str(brief))

    def test_refusal_explains_the_loop_rather_than_just_saying_no(
        self, mock_cfg: MeridianConfig
    ) -> None:
        feat_dir = _feature(mock_cfg)
        brief = feat_dir / "summaries" / "research-2026-08-20.md"
        brief.write_text(BODY)

        with pytest.raises(RuntimeError) as excinfo:
            enrich_feature(mock_cfg, "feat-001", str(brief))
        message = str(excinfo.value)
        assert "sources/" in message, "the refusal must name the way out"

    def test_refusal_writes_nothing(self, mock_cfg: MeridianConfig) -> None:
        feat_dir = _feature(mock_cfg)
        brief = feat_dir / "summaries" / "research-2026-08-20.md"
        brief.write_text(BODY)

        with pytest.raises(RuntimeError):
            enrich_feature(mock_cfg, "feat-001", str(brief))

        assert list((feat_dir / "sources").iterdir()) == []
        assert _all_source_names(mock_cfg) == set()

    def test_an_ordinary_source_is_still_accepted(
        self, mock_cfg: MeridianConfig, tmp_path: Path
    ) -> None:
        _feature(mock_cfg)
        paper = tmp_path / "paper.txt"
        paper.write_text(BODY)

        with patch("meridian.enrich.embed", side_effect=lambda *a, **k: VECTOR):
            result = enrich_feature(mock_cfg, "feat-001", str(paper))

        assert result["chunks"] >= 1
