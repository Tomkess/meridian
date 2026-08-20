"""FEAT-023 — incremental, deduplicated ingestion.

The property this file exists for is one line long: **a rebuild that changes
nothing must call Ollama zero times.** Everything else — the hash column, the
model scoping, the migration, batch ingest — is machinery in service of that,
and `TestNoOpRebuildEmbedsNothing` is the test a later refactor would break
while looking like an improvement.

The embed seam is monkeypatched with a *counting* stub throughout: the point is
never "it worked", it is "it worked without paying". Assertions are on the call
count, not on wall clock.

Run:  uv run --locked python -m pytest tests/test_incremental_ingest.py -v
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from meridian import enrich as enrich_mod
from meridian.config import MeridianConfig
from meridian.enrich import (
    CONTENT_HASH,
    EMBEDDING_MODEL,
    SchemaGeneration,
    chunk_text,
    expand_sources,
    hash_chunk,
    reindex_all,
    schema_generation,
    upsert_chunks,
)

VEC = [0.1, 0.2, 0.3, 0.4]
DIM = len(VEC)


# ── helpers ──────────────────────────────────────────────────────────────── #


def _body(word: str = "word", count: int = 300) -> str:
    """Prose long enough to survive chunk_text's 80-character floor."""
    return " ".join(f"{word}{i}" for i in range(count))


def _write_source(cfg: MeridianConfig, feat_id: str, name: str, body: str) -> Path:
    sources = cfg.specs_path / f"{feat_id}_demo" / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    path = sources / name
    path.write_text(body)
    return path


def _make_spec(cfg: MeridianConfig, feat_id: str) -> Path:
    feat_dir = cfg.specs_path / f"{feat_id}_demo"
    (feat_dir / "sources").mkdir(parents=True, exist_ok=True)
    spec = feat_dir / "spec.md"
    spec.write_text(
        f"---\nid: {feat_id.lower()}\nname: Demo\nstatus: idea\nsources: []\n---\nBody.\n"
    )
    return spec


class CountingEmbed:
    """An embed stub that records every call. The whole feature is a call count."""

    def __init__(self, vector: list[float] | None = None) -> None:
        self.calls: list[str] = []
        self._vector = vector or VEC

    def __call__(self, text: str, model: str | None = None, **_kw) -> list[float]:
        self.calls.append(text)
        return list(self._vector)

    @property
    def count(self) -> int:
        return len(self.calls)

    def reset(self) -> None:
        self.calls.clear()


@pytest.fixture
def counting_embed(monkeypatch) -> CountingEmbed:
    stub = CountingEmbed()
    monkeypatch.setattr(enrich_mod, "embed", stub)
    return stub


def _open(cfg: MeridianConfig):
    import lancedb

    return lancedb.connect(str(cfg.lancedb_path)).open_table("chunks")


def _all_rows(cfg: MeridianConfig) -> list[dict]:
    """Every row, sorted — never `to_arrow()`, which caps silently at 10."""
    table = _open(cfg)
    rows = table.search().limit(max(table.count_rows(), 1)).to_list()
    return sorted(
        rows, key=lambda r: (r["project"], r["feat_id"], r["source_name"], r["chunk_idx"])
    )


def _snapshot(cfg: MeridianConfig) -> list[tuple]:
    return [
        (
            r["project"], r["feat_id"], r["source_name"], r["chunk_idx"],
            r["text"], r[CONTENT_HASH], r[EMBEDDING_MODEL],
            tuple(round(float(v), 6) for v in r["vector"]),
        )
        for r in _all_rows(cfg)
    ]


def _make_pre_hash_table(cfg: MeridianConfig, rows: list[dict]) -> None:
    """A FEAT-007-era table: `project`, but no content hash. The upgrade case."""
    import lancedb
    import pyarrow as pa

    cfg.lancedb_path.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(cfg.lancedb_path))
    schema = pa.schema([
        pa.field("project", pa.string()),
        pa.field("feat_id", pa.string()),
        pa.field("source_name", pa.string()),
        pa.field("chunk_idx", pa.int32()),
        pa.field("text", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), DIM)),
    ])
    db.create_table("chunks", schema=schema).add(rows)


# ── AC16: the property everything else serves ────────────────────────────── #


class TestNoOpRebuildEmbedsNothing:
    """AC16 — zero embed calls when nothing changed. Assert the number itself.

    Before FEAT-023 this number was 178 on the real corpus: every rebuild paid
    for the whole corpus again, which is why the corpus stopped growing.
    """

    def test_second_rebuild_makes_zero_embed_calls(self, mock_cfg, counting_embed) -> None:
        _write_source(mock_cfg, "FEAT-001", "a.txt", _body("alpha"))
        _write_source(mock_cfg, "FEAT-002", "b.txt", _body("beta"))

        first = reindex_all(mock_cfg)
        assert counting_embed.count == first["chunks"] > 0
        assert first["embedded"] == counting_embed.count

        counting_embed.reset()
        second = reindex_all(mock_cfg)

        assert counting_embed.count == 0, (
            "a rebuild that changes nothing must not call Ollama at all — "
            f"it made {counting_embed.count} calls"
        )
        assert second["embedded"] == 0
        assert second["skipped"] == second["sources"] == first["sources"]
        assert second["chunks"] == first["chunks"]

    def test_a_source_too_short_to_chunk_still_costs_nothing(
        self, mock_cfg, counting_embed
    ) -> None:
        """A stub note yields zero chunks — it must not re-enter the embed loop."""
        _write_source(mock_cfg, "FEAT-001", "stub.txt", "too short")
        _write_source(mock_cfg, "FEAT-002", "a.txt", _body("alpha"))
        reindex_all(mock_cfg)

        counting_embed.reset()
        result = reindex_all(mock_cfg)

        assert counting_embed.count == 0
        assert result["sources"] == 2

    def test_only_the_edited_source_is_re_embedded(self, mock_cfg, counting_embed) -> None:
        _write_source(mock_cfg, "FEAT-001", "a.txt", _body("alpha"))
        _write_source(mock_cfg, "FEAT-002", "b.txt", _body("beta"))
        reindex_all(mock_cfg)

        counting_embed.reset()
        edited = _write_source(mock_cfg, "FEAT-002", "b.txt", _body("gamma"))
        result = reindex_all(mock_cfg)

        assert result["skipped"] == 1
        assert counting_embed.count == len(chunk_text(edited.read_text()))
        assert result["changed"] == ["FEAT-002/b.txt"]


class TestCorpusIsUnchangedByANoOpRebuild:
    """AC17 — same rows, same hashes, no duplicates."""

    def test_rows_are_identical_after_a_no_op_rebuild(self, mock_cfg, counting_embed) -> None:
        _write_source(mock_cfg, "FEAT-001", "a.txt", _body("alpha"))
        _write_source(mock_cfg, "FEAT-002", "b.txt", _body("beta"))
        reindex_all(mock_cfg)
        before = _snapshot(mock_cfg)

        reindex_all(mock_cfg)

        assert _snapshot(mock_cfg) == before
        assert len(before) == len({(r[0], r[1], r[2], r[3]) for r in before}), (
            "no duplicate (project, feat, source, chunk) rows"
        )

    def test_other_projects_rows_survive_a_rebuild(self, mock_cfg, other_cfg, counting_embed) -> None:
        upsert_chunks(
            mock_cfg.lancedb_path, "other-project", "FEAT-001", "theirs.txt",
            [_body("theirs")], [VEC], embedding_model="mxbai-embed-large",
        )
        _write_source(mock_cfg, "FEAT-001", "ours.txt", _body("ours"))

        reindex_all(mock_cfg)
        reindex_all(mock_cfg)

        theirs = [r for r in _all_rows(mock_cfg) if r["project"] == "other-project"]
        assert len(theirs) == 1
        assert theirs[0]["source_name"] == "theirs.txt"


# ── AC1 / AC3: the hash itself ───────────────────────────────────────────── #


class TestContentHashColumn:
    def test_column_holds_the_sha256_of_the_chunk_text(self, mock_cfg, counting_embed) -> None:
        _write_source(mock_cfg, "FEAT-001", "a.txt", _body("alpha"))
        reindex_all(mock_cfg)

        for row in _all_rows(mock_cfg):
            expected = hashlib.sha256(row["text"].encode("utf-8")).hexdigest()
            assert row[CONTENT_HASH] == expected == hash_chunk(row["text"])

    def test_touching_a_file_does_not_re_embed_it(self, mock_cfg, counting_embed) -> None:
        """AC3 — detection is by hash, not mtime."""
        path = _write_source(mock_cfg, "FEAT-001", "a.txt", _body("alpha"))
        reindex_all(mock_cfg)

        counting_embed.reset()
        path.touch()  # mtime moves, bytes do not
        result = reindex_all(mock_cfg)

        assert counting_embed.count == 0
        assert result["skipped"] == 1

    def test_editing_in_place_with_a_preserved_mtime_does_re_embed(
        self, mock_cfg, counting_embed
    ) -> None:
        """AC3, the other direction — an mtime-based check would miss this."""
        path = _write_source(mock_cfg, "FEAT-001", "a.txt", _body("alpha"))
        reindex_all(mock_cfg)
        stat = path.stat()

        counting_embed.reset()
        path.write_text(_body("omega"))
        import os

        os.utime(path, (stat.st_atime, stat.st_mtime))  # pretend it never changed
        result = reindex_all(mock_cfg)

        assert counting_embed.count > 0
        assert result["skipped"] == 0


# ── AC2 / AC4: what a rebuild reports ────────────────────────────────────── #


class TestReindexReporting:
    def test_result_carries_skipped_and_embedded_counts(self, mock_cfg, counting_embed) -> None:
        _write_source(mock_cfg, "FEAT-001", "a.txt", _body("alpha"))
        _write_source(mock_cfg, "FEAT-002", "b.txt", _body("beta"))
        reindex_all(mock_cfg)
        _write_source(mock_cfg, "FEAT-003", "c.txt", _body("gamma"))

        counting_embed.reset()
        result = reindex_all(mock_cfg)

        assert result["skipped"] == 2
        assert result["skipped_chunks"] > 0
        assert result["embedded"] == counting_embed.count
        assert result["sources"] == 3

    def test_sources_removed_from_disk_lose_their_rows(self, mock_cfg, counting_embed) -> None:
        """The narrowed delete must still clear what the wholesale one did."""
        path = _write_source(mock_cfg, "FEAT-001", "a.txt", _body("alpha"))
        _write_source(mock_cfg, "FEAT-002", "b.txt", _body("beta"))
        reindex_all(mock_cfg)

        path.unlink()
        reindex_all(mock_cfg)

        assert {r["source_name"] for r in _all_rows(mock_cfg)} == {"b.txt"}


# ── AC5–AC8: dedup ───────────────────────────────────────────────────────── #


class TestDedup:
    def test_identical_chunks_in_one_run_are_embedded_once(self, mock_cfg, counting_embed) -> None:
        """AC5 — the same paper enriched into two features costs one embed."""
        body = _body("shared")
        _write_source(mock_cfg, "FEAT-001", "paper.txt", body)
        _write_source(mock_cfg, "FEAT-002", "paper.txt", body)

        result = reindex_all(mock_cfg)

        chunks = len(chunk_text(body))
        assert counting_embed.count == chunks, "the second copy must reuse, not re-embed"
        assert result["chunks"] == 2 * chunks
        assert result["reused"] == chunks

    def test_a_hash_already_in_the_store_is_reused_across_runs(
        self, mock_cfg, counting_embed
    ) -> None:
        """AC6 — a new feature citing an indexed paper calls Ollama zero times."""
        body = _body("shared")
        _write_source(mock_cfg, "FEAT-001", "paper.txt", body)
        reindex_all(mock_cfg)

        counting_embed.reset()
        _write_source(mock_cfg, "FEAT-002", "paper.txt", body)
        result = reindex_all(mock_cfg)

        assert counting_embed.count == 0
        assert result["reused"] == len(chunk_text(body))

    def test_provenance_survives_dedup(self, mock_cfg, counting_embed) -> None:
        """AC8 — one vector, but still a row per feature that cited it."""
        body = _body("shared")
        _write_source(mock_cfg, "FEAT-001", "paper.txt", body)
        _write_source(mock_cfg, "FEAT-002", "paper.txt", body)
        reindex_all(mock_cfg)

        rows = _all_rows(mock_cfg)
        assert {r["feat_id"] for r in rows} == {"FEAT-001", "FEAT-002"}
        assert {r["project"] for r in rows} == {"test-project"}
        by_feat = {f: [r for r in rows if r["feat_id"] == f] for f in ("FEAT-001", "FEAT-002")}
        assert len(by_feat["FEAT-001"]) == len(by_feat["FEAT-002"]) == len(chunk_text(body))
        # Same text, same hash, same vector — different provenance.
        assert by_feat["FEAT-001"][0][CONTENT_HASH] == by_feat["FEAT-002"][0][CONTENT_HASH]

    def test_reuse_is_scoped_by_embedding_model(self, mock_cfg, counting_embed) -> None:
        """AC7 — vectors from another model are never reused, only replaced."""
        _write_source(mock_cfg, "FEAT-001", "a.txt", _body("alpha"))
        reindex_all(mock_cfg)
        assert {r[EMBEDDING_MODEL] for r in _all_rows(mock_cfg)} == {"mxbai-embed-large"}

        counting_embed.reset()
        other_model = replace(mock_cfg, ollama_model="nomic-embed-text")
        result = reindex_all(other_model)

        assert counting_embed.count == result["chunks"] > 0, (
            "a different model must re-embed — its vectors are not comparable"
        )
        assert result["reused"] == 0
        assert {r[EMBEDDING_MODEL] for r in _all_rows(mock_cfg)} == {"nomic-embed-text"}

    def test_switching_back_reuses_nothing_stale(self, mock_cfg, counting_embed) -> None:
        """The rows now belong to model B; model A must not read them as its own."""
        _write_source(mock_cfg, "FEAT-001", "a.txt", _body("alpha"))
        reindex_all(replace(mock_cfg, ollama_model="model-b"))

        counting_embed.reset()
        reindex_all(mock_cfg)  # back to mxbai-embed-large
        assert counting_embed.count > 0


# ── AC9–AC11: migration ──────────────────────────────────────────────────── #


class TestSchemaGenerations:
    """Three generations exist, so the check has to name which one it found."""

    def test_names_the_current_generation(self, mock_cfg, counting_embed) -> None:
        _write_source(mock_cfg, "FEAT-001", "a.txt", _body("alpha"))
        reindex_all(mock_cfg)
        assert schema_generation(_open(mock_cfg)) is SchemaGeneration.CURRENT

    def test_names_the_pre_hash_generation(self, mock_cfg) -> None:
        _make_pre_hash_table(mock_cfg, [{
            "project": "test-project", "feat_id": "FEAT-001", "source_name": "old.txt",
            "chunk_idx": 0, "text": _body("old"), "vector": VEC,
        }])
        assert schema_generation(_open(mock_cfg)) is SchemaGeneration.PRE_HASH

    def test_names_the_pre_project_generation(self, mock_cfg) -> None:
        import lancedb
        import pyarrow as pa

        mock_cfg.lancedb_path.mkdir(parents=True, exist_ok=True)
        db = lancedb.connect(str(mock_cfg.lancedb_path))
        db.create_table("chunks", schema=pa.schema([
            pa.field("feat_id", pa.string()),
            pa.field("text", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), DIM)),
        ]))
        assert schema_generation(_open(mock_cfg)) is SchemaGeneration.PRE_PROJECT


class TestPreHashMigration:
    """AC9/AC10 — migrated, never dropped. The 2026-08-18 incident, not repeated."""

    def _seed(self, cfg: MeridianConfig) -> None:
        _make_pre_hash_table(cfg, [
            {"project": "test-project", "feat_id": "FEAT-001", "source_name": "ours.txt",
             "chunk_idx": 0, "text": _body("ours"), "vector": VEC},
            {"project": "other-project", "feat_id": "FEAT-001", "source_name": "theirs.txt",
             "chunk_idx": 0, "text": _body("theirs"), "vector": VEC},
        ])

    def test_rows_are_kept_and_backfilled_not_dropped(self, mock_cfg, counting_embed) -> None:
        self._seed(mock_cfg)
        _write_source(mock_cfg, "FEAT-001", "ours.txt", _body("ours"))

        result = reindex_all(mock_cfg)

        assert result["migration"] == "backfilled"
        assert result["migrated"] is False, "backfill must not claim other projects were wiped"
        rows = _all_rows(mock_cfg)
        # The other project's research is still there, untouched, awaiting its
        # own rebuild — the whole point of not dropping.
        theirs = [r for r in rows if r["project"] == "other-project"]
        assert len(theirs) == 1
        assert theirs[0][CONTENT_HASH] == ""
        # Ours was re-embedded once and now carries hash + model.
        ours = [r for r in rows if r["project"] == "test-project"]
        assert ours and all(r[CONTENT_HASH] and r[EMBEDDING_MODEL] for r in ours)

    def test_the_rebuild_after_a_migration_is_incremental(self, mock_cfg, counting_embed) -> None:
        self._seed(mock_cfg)
        _write_source(mock_cfg, "FEAT-001", "ours.txt", _body("ours"))
        reindex_all(mock_cfg)

        counting_embed.reset()
        result = reindex_all(mock_cfg)

        assert counting_embed.count == 0
        assert result["migration"] is None

    def test_ollama_failure_mid_migration_leaves_every_row_intact(
        self, mock_cfg, monkeypatch
    ) -> None:
        """AC10 — embed before delete, and before the schema changes at all."""
        self._seed(mock_cfg)
        _write_source(mock_cfg, "FEAT-001", "ours.txt", _body("ours"))

        def ollama_is_down(text, model=None, **_kw):
            raise RuntimeError("Cannot connect to Ollama at http://localhost:11434")

        monkeypatch.setattr(enrich_mod, "embed", ollama_is_down)

        with pytest.raises(RuntimeError):
            reindex_all(mock_cfg)

        table = _open(mock_cfg)
        assert table.count_rows() == 2, "a failed migration must not lose a row"
        assert schema_generation(table) is SchemaGeneration.PRE_HASH, (
            "the schema must not change either — the next attempt starts clean"
        )

    def test_enrich_path_migrates_without_a_full_reindex(self, mock_cfg, counting_embed) -> None:
        """`meridian enrich` on an old store must work, not demand `index` first."""
        self._seed(mock_cfg)
        spec = _make_spec(mock_cfg, "FEAT-002")
        source = spec.parent / "paper.txt"
        source.write_text(_body("fresh"))

        enrich_mod.enrich_feature(mock_cfg, "feat-002", str(source))

        assert schema_generation(_open(mock_cfg)) is SchemaGeneration.CURRENT
        assert _open(mock_cfg).count_rows() > 2  # nothing was dropped to get here


# ── AC12–AC15: batch ingestion ───────────────────────────────────────────── #


class TestExpandSources:
    def test_directory_expands_non_recursively(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.pdf").write_bytes(b"%PDF-")
        (tmp_path / "c.png").write_bytes(b"\x89PNG")
        nested = tmp_path / "nested"
        nested.mkdir()
        (nested / "deep.txt").write_text("deep")

        targets, failures = expand_sources([str(tmp_path)])

        assert [Path(t).name for t in targets] == ["a.txt", "b.pdf"]
        assert failures == []

    def test_empty_directory_is_reported_not_silent(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        targets, failures = expand_sources([str(empty)])
        assert targets == []
        assert failures and "no .pdf/.txt/.md" in failures[0][1]

    def test_files_and_urls_pass_through(self, tmp_path: Path) -> None:
        doc = tmp_path / "a.txt"
        doc.write_text("a")
        targets, failures = expand_sources([str(doc), "https://example.com/x"])
        assert targets == [str(doc), "https://example.com/x"]
        assert failures == []


class TestBatchIngestion:
    def _project(self, mock_cfg: MeridianConfig) -> None:
        _make_spec(mock_cfg, "FEAT-001")

    def test_each_source_is_written_before_the_next_is_read(
        self, mock_cfg, counting_embed, tmp_path: Path
    ) -> None:
        """AC13 — one unreadable file must not lose what was already ingested."""
        self._project(mock_cfg)
        good = tmp_path / "good.txt"
        good.write_text(_body("good"))
        broken = tmp_path / "broken.txt"
        broken.write_bytes(b"\x00\x01\x02" * 500)

        enrich_mod.enrich_feature(mock_cfg, "feat-001", str(good))
        with pytest.raises(RuntimeError):
            enrich_mod.enrich_feature(mock_cfg, "feat-001", str(broken))

        assert {r["source_name"] for r in _all_rows(mock_cfg)} == {"good.txt"}

    def test_re_ingesting_an_unchanged_file_is_reported_as_skipped(
        self, mock_cfg, counting_embed, tmp_path: Path
    ) -> None:
        self._project(mock_cfg)
        doc = tmp_path / "paper.txt"
        doc.write_text(_body("paper"))

        first = enrich_mod.enrich_feature(mock_cfg, "feat-001", str(doc))
        counting_embed.reset()
        second = enrich_mod.enrich_feature(mock_cfg, "feat-001", str(doc))

        assert first["skipped"] is False and first["embedded"] > 0
        assert second["skipped"] is True
        assert counting_embed.count == 0

    def test_the_same_paper_in_a_second_feature_reuses_its_vectors(
        self, mock_cfg, counting_embed, tmp_path: Path
    ) -> None:
        """AC6 + AC8 through the enrich path."""
        self._project(mock_cfg)
        _make_spec(mock_cfg, "FEAT-002")
        doc = tmp_path / "paper.txt"
        doc.write_text(_body("paper"))

        enrich_mod.enrich_feature(mock_cfg, "feat-001", str(doc))
        counting_embed.reset()
        result = enrich_mod.enrich_feature(mock_cfg, "feat-002", str(doc))

        assert counting_embed.count == 0
        assert result["reused"] == result["chunks"] > 0
        assert {r["feat_id"] for r in _all_rows(mock_cfg)} == {"FEAT-001", "FEAT-002"}


class TestUrlRefresh:
    """AC15 — --refresh re-fetches; re-embedding still depends on the text."""

    def _stub_url(self, monkeypatch, pages: list[str]) -> list[int]:
        fetches = [0]

        def fake_extract(url: str) -> str:
            fetches[0] += 1
            return pages[min(fetches[0] - 1, len(pages) - 1)]

        monkeypatch.setattr(enrich_mod, "_extract_url", fake_extract)
        return fetches

    def test_without_refresh_an_ingested_url_is_not_fetched_again(
        self, mock_cfg, counting_embed, monkeypatch
    ) -> None:
        _make_spec(mock_cfg, "FEAT-001")
        fetches = self._stub_url(monkeypatch, [_body("page")])

        enrich_mod.enrich_feature(mock_cfg, "feat-001", "https://example.com/paper")
        result = enrich_mod.enrich_feature(mock_cfg, "feat-001", "https://example.com/paper")

        assert fetches[0] == 1
        assert result["skipped"] is True
        assert "--refresh" in result["reason"]

    def test_refresh_refetches_but_only_re_embeds_changed_text(
        self, mock_cfg, counting_embed, monkeypatch
    ) -> None:
        _make_spec(mock_cfg, "FEAT-001")
        fetches = self._stub_url(monkeypatch, [_body("page")])

        enrich_mod.enrich_feature(mock_cfg, "feat-001", "https://example.com/paper")
        counting_embed.reset()
        result = enrich_mod.enrich_feature(
            mock_cfg, "feat-001", "https://example.com/paper", refresh=True
        )

        assert fetches[0] == 2, "--refresh must go back to the network"
        assert counting_embed.count == 0, "unchanged text must not be re-embedded"
        assert result["skipped"] is True

    def test_refresh_re_embeds_when_the_page_changed(
        self, mock_cfg, counting_embed, monkeypatch
    ) -> None:
        _make_spec(mock_cfg, "FEAT-001")
        self._stub_url(monkeypatch, [_body("page"), _body("rewritten")])

        enrich_mod.enrich_feature(mock_cfg, "feat-001", "https://example.com/paper")
        counting_embed.reset()
        result = enrich_mod.enrich_feature(
            mock_cfg, "feat-001", "https://example.com/paper", refresh=True
        )

        assert counting_embed.count > 0
        assert result["skipped"] is False


# ── CLI: what the operator actually sees ─────────────────────────────────── #


@pytest.fixture
def cli_project(tmp_path: Path, monkeypatch) -> Path:
    """A real project root on disk, with cwd inside it. MERIDIAN_HOME is already
    redirected session-wide by conftest, and lancedb_path is pinned to tmp on top
    of that — no command here can reach the developer's real store."""
    root = tmp_path / "repo"
    (root / "specs" / "FEAT-001_demo" / "sources").mkdir(parents=True)
    (root / "specs" / "FEAT-001_demo" / "spec.md").write_text(
        "---\nid: feat-001\nname: Demo\nstatus: idea\nsources: []\n---\nBody.\n"
    )
    (root / ".meridian.toml").write_text(
        "[meridian]\n"
        'specs_path = "specs"\n'
        f'lancedb_path = "{root / ".meridian" / "lancedb"}"\n'
        'project = "cli-test"\n'
    )
    monkeypatch.chdir(root)
    return root


def _cli(args: list[str]):
    from typer.testing import CliRunner

    from meridian.cli import app

    return CliRunner().invoke(app, args)


class TestIndexCommandReporting:
    def test_index_prints_skipped_and_embedded(self, cli_project: Path, counting_embed) -> None:
        """AC4 — the numbers are the point of running it twice."""
        (cli_project / "specs" / "FEAT-001_demo" / "sources" / "a.txt").write_text(_body("alpha"))

        first = _cli(["index", "--vectors-only"])
        assert first.exit_code == 0, first.output
        assert "chunks embedded" in first.output

        second = _cli(["index", "--vectors-only"])
        assert second.exit_code == 0, second.output
        assert "1 sources unchanged and skipped" in second.output
        assert "0 chunks embedded" in second.output

    def test_index_states_that_a_migration_happened_and_what_it_cost(
        self, cli_project: Path, counting_embed
    ) -> None:
        """AC11 — never a silent ten minutes."""
        cfg_path = cli_project / ".meridian" / "lancedb"
        (cli_project / "specs" / "FEAT-001_demo" / "sources" / "a.txt").write_text(_body("alpha"))
        _make_pre_hash_table(
            MeridianConfig(
                specs_path=cli_project / "specs", lancedb_path=cfg_path,
                ollama_model="m", reranker_model="r", root=cli_project, project="cli-test",
            ),
            [{"project": "cli-test", "feat_id": "FEAT-001", "source_name": "a.txt",
              "chunk_idx": 0, "text": _body("alpha"), "vector": VEC}],
        )

        result = _cli(["index", "--vectors-only"])

        assert result.exit_code == 0, result.output
        assert "migrated in place" in result.output
        assert "re-embedded" in result.output
        assert "No rows were deleted" in result.output


class TestEnrichCommandBatch:
    def test_multiple_sources_in_one_invocation(self, cli_project: Path, counting_embed) -> None:
        """AC12 — twenty PDFs used to be twenty commands."""
        a = cli_project / "a.txt"
        b = cli_project / "b.txt"
        a.write_text(_body("alpha"))
        b.write_text(_body("beta"))

        result = _cli(["enrich", "feat-001", str(a), str(b)])

        assert result.exit_code == 0, result.output
        assert "a.txt" in result.output and "b.txt" in result.output
        assert "2 ingested" in result.output

    def test_directory_argument_ingests_its_files(self, cli_project: Path, counting_embed) -> None:
        papers = cli_project / "papers"
        papers.mkdir()
        (papers / "one.txt").write_text(_body("one"))
        (papers / "two.txt").write_text(_body("two"))

        result = _cli(["enrich", "feat-001", str(papers)])

        assert result.exit_code == 0, result.output
        sources = cli_project / "specs" / "FEAT-001_demo" / "sources"
        assert {p.name for p in sources.iterdir()} == {"one.txt", "two.txt"}

    def test_one_bad_source_does_not_lose_the_others_and_exits_nonzero(
        self, cli_project: Path, counting_embed
    ) -> None:
        """AC13 + AC14 — the batch reports per source and fails loudly."""
        good = cli_project / "good.txt"
        good.write_text(_body("good"))
        broken = cli_project / "broken.txt"
        broken.write_bytes(b"\x00\x01\x02" * 500)

        result = _cli(["enrich", "feat-001", str(good), str(broken)])

        assert result.exit_code == 1, result.output
        assert "good.txt" in result.output
        assert "broken.txt" in result.output
        assert "1 ingested" in result.output and "1 failed" in result.output
        # The good source really did land, despite the sibling failing.
        assert (cli_project / "specs" / "FEAT-001_demo" / "sources" / "good.txt").exists()

    def test_unchanged_source_is_reported_as_skipped(
        self, cli_project: Path, counting_embed
    ) -> None:
        doc = cli_project / "paper.txt"
        doc.write_text(_body("paper"))

        _cli(["enrich", "feat-001", str(doc)])
        counting_embed.reset()
        again = _cli(["enrich", "feat-001", str(doc)])

        assert again.exit_code == 0, again.output
        assert "nothing re-embedded" in again.output
        assert counting_embed.count == 0

    def test_a_single_missing_source_still_reads_as_before(
        self, cli_project: Path, counting_embed
    ) -> None:
        result = _cli(["enrich", "feat-001", str(cli_project / "nope.txt")])
        assert result.exit_code == 1
        assert "Error:" in result.output


# ── LanceDB API surface (FEAT-005 guard, extended for FEAT-023) ──────────── #


class TestLanceDbApiSurface:
    """The incremental path leans on three APIs the old code never used."""

    def test_plain_filtered_projected_scan_works(self, tmp_path: Path) -> None:
        import lancedb
        import pyarrow as pa

        db = lancedb.connect(str(tmp_path / "db"))
        table = db.create_table("t", schema=pa.schema([
            pa.field("k", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), 2)),
        ]))
        table.add([{"k": f"k{i}", "vector": [float(i), 0.0]} for i in range(25)])

        rows = table.search().where("k != 'nope'").select(["k"]).limit(25).to_list()
        assert len(rows) == 25, "lancedb API drift: query-less scan with select()"

    def test_default_limit_is_still_ten(self, tmp_path: Path) -> None:
        """Documented trap, asserted: an unbounded scan silently returns 10."""
        import lancedb
        import pyarrow as pa

        db = lancedb.connect(str(tmp_path / "db"))
        table = db.create_table("t", schema=pa.schema([
            pa.field("k", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), 2)),
        ]))
        table.add([{"k": f"k{i}", "vector": [float(i), 0.0]} for i in range(25)])

        assert len(table.search().to_list()) == 10
        assert len(table.search().limit(table.count_rows()).to_list()) == 25

    def test_add_columns_is_additive(self, tmp_path: Path) -> None:
        """The migration's one dependency. Without it, rows would have to move."""
        import lancedb
        import pyarrow as pa

        db = lancedb.connect(str(tmp_path / "db"))
        table = db.create_table("t", schema=pa.schema([
            pa.field("k", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), 2)),
        ]))
        table.add([{"k": "a", "vector": [1.0, 0.0]}])

        table.add_columns({CONTENT_HASH: "''"})

        assert CONTENT_HASH in set(table.schema.names)
        assert table.count_rows() == 1
        assert table.search().limit(1).to_list()[0][CONTENT_HASH] == ""
