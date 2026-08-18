"""End-to-end CLI tests for the global idea inbox (FEAT-008)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _find_binary() -> str:
    venv_bin = Path(sys.executable).parent / "meridian"
    if venv_bin.exists():
        return str(venv_bin)
    found = shutil.which("meridian")
    if found:
        return found
    raise RuntimeError("meridian binary not found. Run: uv pip install -e '.[dev]'")


MERIDIAN_BIN = _find_binary()


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """A throwaway MERIDIAN_HOME. Never the developer's real ~/.meridian."""
    return tmp_path / "meridian-home"


def run(args: list[str], cwd: Path, home: Path) -> subprocess.CompletedProcess[str]:
    e = dict(os.environ)
    e["NO_COLOR"] = "1"
    e["MERIDIAN_HOME"] = str(home)
    return subprocess.run(
        [MERIDIAN_BIN, *args], cwd=cwd, capture_output=True, text=True, env=e
    )


def _make_repo(root: Path, name: str) -> Path:
    """A minimal Meridian project on disk."""
    repo = root / name
    (repo / "specs").mkdir(parents=True)
    (repo / ".meridian.toml").write_text(
        f'[meridian]\nproject = "{name}"\nspecs_path = "specs"\n'
        f'lancedb_path = "{root / "lancedb"}"\n'
    )
    return repo


def _register(repo: Path, home: Path, slug: str, purpose: str = "") -> None:
    registry = home / "projects.toml"
    registry.parent.mkdir(parents=True, exist_ok=True)
    existing = registry.read_text() if registry.exists() else ""
    registry.write_text(
        existing
        + f'\n[[project]]\nslug = "{slug}"\npath = "{repo}"\npurpose = "{purpose}"\n'
    )


def _capture_id(home: Path) -> str:
    files = sorted((home / "inbox").glob("*.md"))
    assert files, "no pending capture found"
    return files[0].stem


class TestCaptureOutsideRepo:
    def test_works_with_no_meridian_toml_anywhere(self, tmp_path: Path, home: Path) -> None:
        """AC5 — the path every other CLI test misses, since they all run in a repo."""
        scratch = tmp_path / "not-a-repo"
        scratch.mkdir()

        r = run(["capture", "an idea from the sofa"], scratch, home)

        assert r.returncode == 0, r.stderr
        assert "Traceback" not in r.stdout + r.stderr
        assert "No .meridian.toml found" not in r.stdout + r.stderr
        assert list((home / "inbox").glob("*.md"))

    def test_empty_text_rejected(self, tmp_path: Path, home: Path) -> None:
        scratch = tmp_path / "not-a-repo"
        scratch.mkdir()
        r = run(["capture", "   "], scratch, home)
        assert r.returncode == 1
        assert "Nothing to capture" in r.stdout

    def test_explicit_project_tag(self, tmp_path: Path, home: Path) -> None:
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        run(["capture", "scoped idea", "--project", "meridian"], scratch, home)

        content = next((home / "inbox").glob("*.md")).read_text()
        assert "project: meridian" in content


class TestInboxListing:
    def test_empty_inbox_message(self, tmp_path: Path, home: Path) -> None:
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        r = run(["inbox"], scratch, home)
        assert r.returncode == 0
        assert "Inbox empty" in r.stdout

    def test_lists_pending_capture(self, tmp_path: Path, home: Path) -> None:
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        run(["capture", "a distinctive idea about retries"], scratch, home)

        r = run(["inbox"], scratch, home)
        assert "1 pending" in r.stdout
        assert "a distinctive idea about retries" in r.stdout

    def test_hashtag_hint_shown_without_any_registry(self, tmp_path: Path, home: Path) -> None:
        """The state a new machine is in right after its first phone capture."""
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        run(["capture", "an idea #some-project"], scratch, home)

        r = run(["inbox"], scratch, home)

        assert "some-project" in r.stdout
        assert "explicit" in r.stdout

    def test_warns_when_no_projects_registered(self, tmp_path: Path, home: Path) -> None:
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        run(["capture", "orphan idea"], scratch, home)

        r = run(["inbox"], scratch, home)
        assert "No projects registered" in r.stdout


class TestRoute:
    def test_round_trip_creates_spec_and_archives(self, tmp_path: Path, home: Path) -> None:
        """AC14/AC15: spec lands in the target repo, capture is moved not deleted."""
        repo = _make_repo(tmp_path, "target-repo")
        _register(repo, home, "target-repo")
        scratch = tmp_path / "scratch"
        scratch.mkdir()

        run(["capture", "add retry logic\n\nwith exponential backoff"], scratch, home)
        cid = _capture_id(home)

        r = run(["inbox", "route", cid, "target-repo"], scratch, home)
        assert r.returncode == 0, r.stdout + r.stderr

        specs = sorted(repo.glob("specs/FEAT-*/spec.md"))
        assert len(specs) == 1
        body = specs[0].read_text()
        assert "add retry logic" in body
        assert "with exponential backoff" in body, "full text must survive routing"

        assert not list((home / "inbox").glob("*.md")), "capture should leave pending"
        assert list((home / "inbox" / ".processed").glob("*.md")), "capture must be archived"

    def test_double_route_creates_no_duplicate(self, tmp_path: Path, home: Path) -> None:
        """AC17."""
        repo = _make_repo(tmp_path, "target-repo")
        _register(repo, home, "target-repo")
        scratch = tmp_path / "scratch"
        scratch.mkdir()

        run(["capture", "one idea"], scratch, home)
        cid = _capture_id(home)
        run(["inbox", "route", cid, "target-repo"], scratch, home)

        r = run(["inbox", "route", cid, "target-repo"], scratch, home)

        assert r.returncode == 1
        assert "No pending capture" in r.stdout
        assert len(sorted(repo.glob("specs/FEAT-*/spec.md"))) == 1

    def test_routing_leaves_other_projects_untouched(self, tmp_path: Path, home: Path) -> None:
        repo_a = _make_repo(tmp_path, "repo-a")
        repo_b = _make_repo(tmp_path, "repo-b")
        _register(repo_a, home, "repo-a")
        _register(repo_b, home, "repo-b")
        scratch = tmp_path / "scratch"
        scratch.mkdir()

        run(["capture", "an idea for A"], scratch, home)
        run(["inbox", "route", _capture_id(home), "repo-a"], scratch, home)

        assert sorted(repo_a.glob("specs/FEAT-*/spec.md"))
        assert not sorted(repo_b.glob("specs/FEAT-*/spec.md"))

    def test_unknown_project_rejected(self, tmp_path: Path, home: Path) -> None:
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        run(["capture", "an idea"], scratch, home)

        r = run(["inbox", "route", _capture_id(home), "nope"], scratch, home)

        assert r.returncode == 1
        assert "Unknown project" in r.stdout
        assert list((home / "inbox").glob("*.md")), "failed route must not consume the capture"

    def test_missing_registered_path_rejected(self, tmp_path: Path, home: Path) -> None:
        repo = _make_repo(tmp_path, "gone-repo")
        _register(repo, home, "gone-repo")
        shutil.rmtree(repo)
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        run(["capture", "an idea"], scratch, home)

        r = run(["inbox", "route", _capture_id(home), "gone-repo"], scratch, home)

        assert r.returncode == 1
        assert "does not exist" in r.stdout

    def test_unknown_capture_id_rejected(self, tmp_path: Path, home: Path) -> None:
        repo = _make_repo(tmp_path, "target-repo")
        _register(repo, home, "target-repo")
        scratch = tmp_path / "scratch"
        scratch.mkdir()

        r = run(["inbox", "route", "2020-01-01T000000", "target-repo"], scratch, home)
        assert r.returncode == 1
        assert "No pending capture" in r.stdout


class TestDrop:
    def test_moves_to_icebox_not_deleted(self, tmp_path: Path, home: Path) -> None:
        """AC16."""
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        run(["capture", "a bad idea"], scratch, home)
        cid = _capture_id(home)

        r = run(["inbox", "drop", cid], scratch, home)

        assert r.returncode == 0
        assert not list((home / "inbox").glob("*.md"))
        iced = list((home / "inbox" / ".icebox").glob("*.md"))
        assert iced and "a bad idea" in iced[0].read_text()


class TestNoAutoFile:
    def test_route_requires_explicit_project(self, tmp_path: Path, home: Path) -> None:
        """AC18: auto-filing is a rejected design, so it needs a guard.

        `route` must not fall back to its own suggestion when no project is
        named — an inbox that files itself produces specs nobody kills.
        """
        repo = _make_repo(tmp_path, "target-repo")
        _register(repo, home, "target-repo")
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        run(["capture", "an idea"], scratch, home)

        r = run(["inbox", "route", _capture_id(home)], scratch, home)

        assert r.returncode != 0, "route without a project must fail, not guess"
        assert not sorted(repo.glob("specs/FEAT-*/spec.md"))


class TestStatusNudge:
    def test_status_shows_pending_count(self, tmp_path: Path, home: Path) -> None:
        repo = _make_repo(tmp_path, "target-repo")
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        run(["capture", "one idea"], scratch, home)
        run(["capture", "another idea"], scratch, home)

        r = run(["status"], repo, home)

        assert "2 ideas pending triage" in r.stdout

    def test_status_silent_when_inbox_empty(self, tmp_path: Path, home: Path) -> None:
        """Costs nothing in the common case."""
        repo = _make_repo(tmp_path, "target-repo")

        r = run(["status"], repo, home)

        assert "pending triage" not in r.stdout

    def test_singular_wording(self, tmp_path: Path, home: Path) -> None:
        repo = _make_repo(tmp_path, "target-repo")
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        run(["capture", "single idea"], scratch, home)

        r = run(["status"], repo, home)

        assert "1 idea pending triage" in r.stdout


class TestProjectsCommand:
    def test_lists_registered(self, tmp_path: Path, home: Path) -> None:
        repo = _make_repo(tmp_path, "listed-repo")
        _register(repo, home, "listed-repo", "Does a thing")
        scratch = tmp_path / "scratch"
        scratch.mkdir()

        r = run(["projects"], scratch, home)
        assert r.returncode == 0
        assert "listed-repo" in r.stdout
        assert "Does a thing" in r.stdout

    def test_flags_stale_entry(self, tmp_path: Path, home: Path) -> None:
        repo = _make_repo(tmp_path, "gone-repo")
        _register(repo, home, "gone-repo")
        shutil.rmtree(repo)
        scratch = tmp_path / "scratch"
        scratch.mkdir()

        r = run(["projects"], scratch, home)
        assert "missing" in r.stdout
        assert "not found" in r.stdout

    def test_empty_registry_message(self, tmp_path: Path, home: Path) -> None:
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        r = run(["projects"], scratch, home)
        assert "No projects registered" in r.stdout
