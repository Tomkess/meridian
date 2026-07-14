"""Tests for FEAT-004 — spec_lock serializes concurrent read-modify-write.

The corruption risk: two agents transition the same feature at once, both
load → modify → save, and one update is silently lost (last writer wins).
spec_lock() must make those cycles mutually exclusive.

Run:  .venv/bin/pytest tests/test_spec_lock.py -v
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from meridian.specs import create_spec, load_spec, spec_lock, transition_spec

# ── mutual exclusion ─────────────────────────────────────────────────────── #


def _racy_increment(counter: Path, lock_target: Path, barrier: threading.Barrier) -> None:
    """A deliberately non-atomic read-modify-write, guarded by spec_lock.

    The read/compute/write is split with no atomicity of its own, so if the
    lock fails to serialize, concurrent runs lose updates.
    """
    barrier.wait()  # maximize contention: release all threads together
    with spec_lock(lock_target):
        value = int(counter.read_text())
        # Widen the race window without sleeping: touch the filesystem.
        _ = counter.stat()
        counter.write_text(str(value + 1))


class TestSpecLockMutualExclusion:
    def test_no_lost_updates_under_contention(self, tmp_path: Path) -> None:
        counter = tmp_path / "counter"
        counter.write_text("0")
        lock_target = tmp_path / "FEAT-001_x" / "spec.md"
        lock_target.parent.mkdir()

        n = 25
        barrier = threading.Barrier(n)
        threads = [
            threading.Thread(target=_racy_increment, args=(counter, lock_target, barrier))
            for _ in range(n)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Every increment must have landed — serialized, no lost writes.
        assert int(counter.read_text()) == n

    def test_distinct_specs_use_distinct_locks(self, tmp_path: Path) -> None:
        """Different specs must not block each other (per-path lock keying).

        Acquire spec A's lock and, while holding it, acquire spec B's lock from
        another thread. If they shared a lock this would deadlock; a short join
        timeout catches that.
        """
        a = tmp_path / "a" / "spec.md"
        b = tmp_path / "b" / "spec.md"
        a.parent.mkdir()
        b.parent.mkdir()

        acquired_b = threading.Event()

        def grab_b() -> None:
            with spec_lock(b):
                acquired_b.set()

        with spec_lock(a):
            t = threading.Thread(target=grab_b)
            t.start()
            t.join(timeout=5)
        assert acquired_b.is_set(), "distinct specs should not contend on the same lock"


# ── transition_spec integration ─────────────────────────────────────────── #


class TestTransitionUnderLock:
    def test_transition_still_functional(self, specs_dir: Path) -> None:
        spec_path = create_spec(specs_dir, "Locked feature", appetite="s")
        transition_spec(spec_path, "draft")
        assert load_spec(spec_path)["status"] == "draft"

    def test_no_lock_artifact_left_in_repo(self, specs_dir: Path) -> None:
        """The lock file lives in the temp dir, never beside the spec."""
        spec_path = create_spec(specs_dir, "No litter", appetite="s")
        transition_spec(spec_path, "draft")
        feat_dir = spec_path.parent
        assert list(feat_dir.glob("*.lock")) == []
        assert not (feat_dir / "spec.md.lock").exists()

    def test_concurrent_transitions_do_not_corrupt_spec(self, specs_dir: Path) -> None:
        """Two threads race the same transition; the file stays valid and one wins.

        The FSM permits idea→draft only once; the loser raises ValueError. What
        must NOT happen is a half-written / unparseable spec.
        """
        spec_path = create_spec(specs_dir, "Race target", appetite="s")
        barrier = threading.Barrier(2)
        errors: list[Exception] = []

        def go() -> None:
            barrier.wait()
            try:
                transition_spec(spec_path, "draft")
            except ValueError as e:  # loser: already left 'idea'
                errors.append(e)

        threads = [threading.Thread(target=go) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Spec is still parseable and in the target state.
        assert load_spec(spec_path)["status"] == "draft"
        # At most one thread can have been rejected by the FSM.
        assert len(errors) <= 1


def test_spec_lock_is_a_context_manager(tmp_path: Path) -> None:
    target = tmp_path / "spec.md"
    with spec_lock(target):
        pass  # acquire + release without error
    with pytest.raises(RuntimeError):
        with spec_lock(target):
            raise RuntimeError("propagates through the context manager")
