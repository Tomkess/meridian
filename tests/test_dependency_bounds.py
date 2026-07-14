"""Tests for FEAT-005 — dependency bounds + API-surface drift guard.

Two layers of protection against dependency drift:

  1. **Version bounds** — the installed versions of the pinned runtime deps
     satisfy the specifiers declared in pyproject.toml. Catches an environment
     that resolved outside the tested range (e.g. a stray upgrade).

  2. **API surface** — the exact LanceDB / pyarrow methods meridian/enrich.py
     calls still exist. LanceDB's query API has changed across minor versions;
     a bump that renames or drops a method must fail HERE with a clear "API
     drift" message rather than deep inside an enrich run.

Run:  .venv/bin/pytest tests/test_dependency_bounds.py -v
"""

from __future__ import annotations

import tomllib
from importlib.metadata import version
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

REPO_ROOT = Path(__file__).parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"

# Runtime deps whose drift would break Meridian's data layer most directly.
# (All declared runtime deps are checked generically; these two also get the
# API-surface guard below.)
_API_CRITICAL = {"lancedb", "pyarrow"}


def _declared_requirements() -> list[Requirement]:
    data = tomllib.loads(PYPROJECT.read_text())
    return [Requirement(spec) for spec in data["project"]["dependencies"]]


# ── version bounds ───────────────────────────────────────────────────────── #


class TestVersionBounds:
    @pytest.mark.parametrize(
        "req",
        _declared_requirements(),
        ids=lambda r: r.name,
    )
    def test_installed_satisfies_declared_specifier(self, req: Requirement) -> None:
        installed = version(req.name)
        assert req.specifier.contains(installed, prereleases=True), (
            f"{req.name}=={installed} is outside the declared range "
            f"'{req.specifier}' in pyproject.toml. Either the environment "
            f"drifted, or the pin needs updating after re-testing."
        )

    def test_lancedb_pin_has_an_upper_bound(self) -> None:
        """LanceDB's API changes across minors — the pin must cap the major/minor."""
        lancedb_req = next(r for r in _declared_requirements() if r.name == "lancedb")
        uppers = [s for s in lancedb_req.specifier if s.operator in ("<", "<=")]
        assert uppers, (
            "lancedb must keep an upper bound in pyproject.toml; its query API "
            "is not stable across minor versions."
        )
        # Installed version must sit strictly below the cap we've tested against.
        cap = min(Version(s.version) for s in uppers)
        assert Version(version("lancedb")) < cap


# ── API surface ──────────────────────────────────────────────────────────── #


class TestLanceDbApiSurface:
    def test_module_and_object_methods_exist(self, tmp_path: Path) -> None:
        import lancedb
        import pyarrow as pa

        assert hasattr(lancedb, "connect")

        db = lancedb.connect(str(tmp_path / "db"))
        for method in ("table_names", "create_table", "open_table", "drop_table"):
            assert hasattr(db, method), f"lancedb DB API drift: missing .{method}()"

        schema = pa.schema([
            pa.field("feat_id", pa.string()),
            pa.field("chunk_idx", pa.int32()),
            pa.field("vector", pa.list_(pa.float32(), 2)),
        ])
        table = db.create_table("t", schema=schema)
        for method in ("add", "delete", "search", "count_rows"):
            assert hasattr(table, method), f"lancedb Table API drift: missing .{method}()"

    def test_query_builder_chain_exists(self, tmp_path: Path) -> None:
        """enrich.search_similar relies on .search(v).limit(n).where(p).to_list()."""
        import lancedb
        import pyarrow as pa

        db = lancedb.connect(str(tmp_path / "db"))
        schema = pa.schema([
            pa.field("feat_id", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), 2)),
        ])
        table = db.create_table("t", schema=schema)
        table.add([{"feat_id": "FEAT-001", "vector": [1.0, 0.0]}])

        query = table.search([1.0, 0.0])
        for method in ("limit", "where", "to_list"):
            assert hasattr(query, method), f"lancedb query API drift: missing .{method}()"

        # The full chain used in production must actually execute.
        rows = table.search([1.0, 0.0]).limit(1).where("feat_id = 'FEAT-001'").to_list()
        assert rows and rows[0]["feat_id"] == "FEAT-001"


class TestPyArrowApiSurface:
    def test_schema_constructors_exist(self) -> None:
        import pyarrow as pa

        for attr in ("schema", "field", "list_", "string", "int32", "float32"):
            assert hasattr(pa, attr), f"pyarrow API drift: missing pa.{attr}"
