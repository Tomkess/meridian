"""End-to-end CLI tests for project tracking (FEAT-009)."""
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
    raise RuntimeError("meridian binary not found. Run: uv sync")


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


def _make_repo(root: Path, name: str, specs: dict[str, int] | None = None) -> Path:
    """A Meridian project on disk, optionally pre-populated with feature specs."""
    repo = root / name
    (repo / "specs").mkdir(parents=True)
    (repo / ".meridian.toml").write_text(
        f'[meridian]\nproject = "{name}"\nspecs_path = "specs"\n'
        f'lancedb_path = "{root / "lancedb"}"\n'
    )
    n = 1
    for status, count in (specs or {}).items():
        for _ in range(count):
            d = repo / "specs" / f"FEAT-{n:03d}_demo"
            d.mkdir(parents=True)
            (d / "spec.md").write_text(
                f"---\nid: feat-{n:03d}\nname: Demo {n}\nstatus: {status}\n"
                f"appetite: s\ngoal: '~'\n---\nBody.\n"
            )
            n += 1
    return repo


class TestRegister:
    def test_tracks_current_repo(self, tmp_path: Path, home: Path) -> None:
        repo = _make_repo(tmp_path, "my-repo")

        r = run(["register"], repo, home)

        assert r.returncode == 0, r.stderr
        assert "my-repo" in r.stdout
        assert (home / "projects.toml").exists()

    def test_rerun_does_not_duplicate(self, tmp_path: Path, home: Path) -> None:
        repo = _make_repo(tmp_path, "my-repo")
        run(["register"], repo, home)
        run(["register"], repo, home)

        assert (home / "projects.toml").read_text().count("[[project]]") == 1

    def test_name_and_purpose_overrides(self, tmp_path: Path, home: Path) -> None:
        repo = _make_repo(tmp_path, "my-repo")

        run(["register", "--name", "Custom Name", "--purpose", "Does a thing"], repo, home)

        # Assert the parsed value, not the serialiser's whitespace — the
        # registry is written by tomli_w now, and its exact spacing is not a
        # contract.
        import tomllib

        with open(home / "projects.toml", "rb") as f:
            doc = tomllib.load(f)
        entry = doc["project"][0]
        assert entry["slug"] == "custom name"
        assert entry["purpose"] == "Does a thing"

    def test_outside_a_repo_errors_cleanly(self, tmp_path: Path, home: Path) -> None:
        scratch = tmp_path / "not-a-repo"
        scratch.mkdir()

        r = run(["register"], scratch, home)

        assert r.returncode == 1
        assert "Traceback" not in r.stdout + r.stderr
        assert "No .meridian.toml found" in r.stdout


class TestProjects:
    def test_empty_message(self, tmp_path: Path, home: Path) -> None:
        repo = _make_repo(tmp_path, "my-repo")
        r = run(["projects"], repo, home)
        assert "No projects tracked" in r.stdout

    def test_lists_tracked(self, tmp_path: Path, home: Path) -> None:
        repo = _make_repo(tmp_path, "my-repo")
        run(["register", "--purpose", "Ships things"], repo, home)

        r = run(["projects"], repo, home)
        assert "my-repo" in r.stdout
        assert "Ships things" in r.stdout

    def test_flags_missing_path(self, tmp_path: Path, home: Path) -> None:
        repo = _make_repo(tmp_path, "gone-repo")
        other = _make_repo(tmp_path, "here-repo")
        run(["register"], repo, home)
        shutil.rmtree(repo)

        r = run(["projects"], other, home)
        assert "missing" in r.stdout
        assert "not found" in r.stdout


class TestStatusAll:
    def test_aggregates_across_projects(self, tmp_path: Path, home: Path) -> None:
        a = _make_repo(tmp_path, "alpha", {"in-progress": 2, "done": 1})
        b = _make_repo(tmp_path, "beta", {"idea": 3, "blocked": 1})
        run(["register"], a, home)
        run(["register"], b, home)

        r = run(["status", "--all"], a, home)

        assert r.returncode == 0, r.stderr
        assert "alpha" in r.stdout and "beta" in r.stdout
        assert "7 features across 2 projects" in r.stdout
        assert "2 in progress" in r.stdout
        assert "1 blocked" in r.stdout

    def test_works_from_outside_any_repo(self, tmp_path: Path, home: Path) -> None:
        """The dashboard's whole point is not needing the right repo checked out."""
        a = _make_repo(tmp_path, "alpha", {"draft": 1})
        run(["register"], a, home)
        scratch = tmp_path / "not-a-repo"
        scratch.mkdir()

        r = run(["status", "--all"], scratch, home)

        assert r.returncode == 0, r.stderr
        assert "alpha" in r.stdout

    def test_empty_registry_message(self, tmp_path: Path, home: Path) -> None:
        scratch = tmp_path / "not-a-repo"
        scratch.mkdir()
        r = run(["status", "--all"], scratch, home)
        assert "No projects tracked" in r.stdout

    def test_skips_unreadable_project_without_failing(self, tmp_path: Path, home: Path) -> None:
        a = _make_repo(tmp_path, "alpha", {"draft": 1})
        gone = _make_repo(tmp_path, "gone")
        run(["register"], a, home)
        run(["register"], gone, home)
        shutil.rmtree(gone)

        r = run(["status", "--all"], a, home)

        assert r.returncode == 0
        assert "alpha" in r.stdout
        assert "gone" in r.stdout and "skipped" in r.stdout

    def test_plain_status_still_per_project(self, tmp_path: Path, home: Path) -> None:
        a = _make_repo(tmp_path, "alpha", {"draft": 1})
        b = _make_repo(tmp_path, "beta", {"draft": 1})
        run(["register"], a, home)
        run(["register"], b, home)

        r = run(["status"], a, home)

        assert "beta" not in r.stdout, "bare `status` must stay scoped to this repo"
