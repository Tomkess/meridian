"""Concurrent spec writes must not lose or destroy data (FEAT-013).

The audit reproduced two failures with a 75-trial harness against the real CLI:
4 trials left a spec holding only 4 frontmatter keys and no body, and 15 trials
silently discarded one of two writes while both commands printed a success mark.

These tests drive the same races in-process, which is fast enough to run on every
commit. Each asserts an invariant that held in neither failure mode: the spec
stays structurally whole, and no write is silently dropped.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import frontmatter
import pytest

from meridian.specs import _atomic_write, create_spec, edit_spec, load_spec, save_spec

REQUIRED_KEYS = {"id", "name", "status", "goal", "created", "updated"}


@pytest.fixture
def spec(specs_dir: Path) -> Path:
    path = create_spec(specs_dir, "a feature under concurrent edit", None, "s")
    body = load_spec(path)["_body"]
    assert body.strip(), "fixture precondition: the stub spec has a body"
    return path


def _assert_intact(spec_path: Path) -> dict:
    """The spec must always be parseable and structurally complete."""
    post = frontmatter.loads(spec_path.read_text())
    missing = REQUIRED_KEYS - set(post.metadata)
    assert not missing, f"frontmatter lost keys: {sorted(missing)}"
    assert post.content.strip(), "body was destroyed"
    return dict(post.metadata)


class TestAtomicWrite:
    def test_never_leaves_a_partial_file(self, tmp_path: Path) -> None:
        path = tmp_path / "f.md"
        path.write_text("original")
        with pytest.raises(RuntimeError):
            _atomic_write_failing(path)
        assert path.read_text() == "original", "a failed write must not truncate"

    def test_no_temp_files_left_behind(self, tmp_path: Path) -> None:
        path = tmp_path / "f.md"
        _atomic_write(path, "content")
        strays = [p.name for p in tmp_path.iterdir() if p.name != "f.md"]
        assert strays == []

    def test_replaces_content(self, tmp_path: Path) -> None:
        path = tmp_path / "f.md"
        _atomic_write(path, "one")
        _atomic_write(path, "two")
        assert path.read_text() == "two"


def _atomic_write_failing(path: Path) -> None:
    """Force a mid-write failure to prove the original file survives."""
    real_replace = os.replace

    def boom(*a, **k):
        raise RuntimeError("simulated failure after temp write")

    os.replace = boom
    try:
        _atomic_write(path, "replacement")
    finally:
        os.replace = real_replace


class TestConcurrentEdits:
    """H1: concurrent cycle + close destroyed the spec entirely."""

    def test_spec_survives_many_concurrent_edits(self, spec: Path) -> None:
        def set_cycle(n: int) -> None:
            with edit_spec(spec) as data:
                data["cycle"] = f"2026-Q{(n % 4) + 1}"

        def set_status(_n: int) -> None:
            with edit_spec(spec) as data:
                data["status"] = "draft"

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda i: set_cycle(i) if i % 2 else set_status(i), range(40)))

        data = _assert_intact(spec)
        assert data["status"] == "draft"
        assert str(data["cycle"]).startswith("2026-Q")

    def test_no_lost_update_across_distinct_fields(self, spec: Path) -> None:
        """H2: both commands reported success, one write was discarded."""

        def write_cycle() -> None:
            with edit_spec(spec) as data:
                data["cycle"] = "2026-Q3"

        def write_status() -> None:
            with edit_spec(spec) as data:
                data["status"] = "draft"

        for _ in range(25):
            with edit_spec(spec) as data:
                data["cycle"] = None
                data["status"] = "idea"

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(write_cycle), pool.submit(write_status)]
                for f in futures:
                    f.result()

            data = _assert_intact(spec)
            assert data["cycle"] == "2026-Q3", "cycle write was lost"
            assert data["status"] == "draft", "status write was lost"

    def test_concurrent_source_appends_all_survive(self, spec: Path) -> None:
        """Appending is the most race-prone shape: read list, add, write back."""

        def append(n: int) -> None:
            with edit_spec(spec) as data:
                current = list(data.get("sources") or [])
                data["sources"] = current + [f"sources/doc-{n}.txt"]

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(append, range(20)))

        sources = load_spec(spec)["sources"]
        assert len(sources) == 20, f"lost {20 - len(sources)} appended sources"
        assert len(set(sources)) == 20


class TestEditSpecSemantics:
    def test_exception_inside_block_does_not_save(self, spec: Path) -> None:
        before = spec.read_text()
        with pytest.raises(ValueError):
            with edit_spec(spec) as data:
                data["status"] = "draft"
                raise ValueError("caller failed")
        assert spec.read_text() == before, "a failed edit must not persist"

    def test_saves_on_clean_exit(self, spec: Path) -> None:
        with edit_spec(spec) as data:
            data["confidence"] = "high"
        assert load_spec(spec)["confidence"] == "high"

    def test_save_spec_still_skips_unchanged_writes(self, spec: Path) -> None:
        """B5 behaviour must survive the atomic-write change."""
        data = load_spec(spec)
        before = spec.stat().st_mtime_ns
        save_spec(spec, data)
        assert spec.stat().st_mtime_ns == before, "unchanged save should be a no-op"
