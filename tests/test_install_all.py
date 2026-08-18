"""Skill propagation across tracked projects (FEAT-010)."""
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
    return tmp_path / "meridian-home"


def run(args: list[str], cwd: Path, home: Path) -> subprocess.CompletedProcess[str]:
    e = dict(os.environ)
    e["NO_COLOR"] = "1"
    e["MERIDIAN_HOME"] = str(home)
    return subprocess.run(
        [MERIDIAN_BIN, *args], cwd=cwd, capture_output=True, text=True, env=e
    )


def _make_repo(root: Path, name: str) -> Path:
    repo = root / name
    (repo / "specs").mkdir(parents=True)
    (repo / ".meridian.toml").write_text(
        f'[meridian]\nproject = "{name}"\nspecs_path = "specs"\n'
    )
    return repo


def _skill_count() -> int:
    from meridian import skills

    return len(list((Path(skills.__file__).parent / "commands").glob("*.md")))


class TestInstallAll:
    def test_writes_into_every_tracked_project(self, tmp_path: Path, home: Path) -> None:
        a = _make_repo(tmp_path, "alpha")
        b = _make_repo(tmp_path, "beta")
        run(["register"], a, home)
        run(["register"], b, home)

        r = run(["install", "--all"], a, home)

        assert r.returncode == 0, r.stderr
        for repo in (a, b):
            installed = list((repo / ".claude" / "commands" / "meridian").glob("*.md"))
            assert len(installed) == _skill_count()

    def test_second_run_reports_nothing_to_do(self, tmp_path: Path, home: Path) -> None:
        a = _make_repo(tmp_path, "alpha")
        run(["register"], a, home)
        run(["install", "--all"], a, home)

        r = run(["install", "--all"], a, home)

        assert "0 file(s) written" in r.stdout

    def test_customised_skill_not_clobbered_without_force(
        self, tmp_path: Path, home: Path
    ) -> None:
        a = _make_repo(tmp_path, "alpha")
        run(["register"], a, home)
        run(["install", "--all"], a, home)
        skill = a / ".claude" / "commands" / "meridian" / "spec.md"
        skill.write_text("locally customised")

        r = run(["install", "--all"], a, home)

        assert skill.read_text() == "locally customised"
        assert "outdated" in r.stdout

    def test_force_updates_outdated(self, tmp_path: Path, home: Path) -> None:
        a = _make_repo(tmp_path, "alpha")
        run(["register"], a, home)
        run(["install", "--all"], a, home)
        skill = a / ".claude" / "commands" / "meridian" / "spec.md"
        skill.write_text("locally customised")

        run(["install", "--all", "--force"], a, home)

        assert skill.read_text() != "locally customised"

    def test_dry_run_writes_nothing(self, tmp_path: Path, home: Path) -> None:
        a = _make_repo(tmp_path, "alpha")
        run(["register"], a, home)

        r = run(["install", "--all", "--dry-run"], a, home)

        assert not (a / ".claude").exists()
        assert "would be written" in r.stdout

    def test_missing_path_skipped_not_fatal(self, tmp_path: Path, home: Path) -> None:
        a = _make_repo(tmp_path, "alpha")
        gone = _make_repo(tmp_path, "gone")
        run(["register"], a, home)
        run(["register"], gone, home)
        shutil.rmtree(gone)

        r = run(["install", "--all"], a, home)

        assert r.returncode == 0
        assert "path not found" in r.stdout
        assert (a / ".claude" / "commands" / "meridian").is_dir()

    def test_no_projects_message(self, tmp_path: Path, home: Path) -> None:
        a = _make_repo(tmp_path, "alpha")
        r = run(["install", "--all"], a, home)
        assert "No projects tracked" in r.stdout


class TestPrMode:
    def test_pr_requires_all(self, tmp_path: Path, home: Path) -> None:
        a = _make_repo(tmp_path, "alpha")
        r = run(["install", "--pr"], a, home)
        assert r.returncode == 1
        assert "--pr requires --all" in r.stdout

    def test_non_git_project_skipped(self, tmp_path: Path, home: Path) -> None:
        """A tracked directory that is not a repo cannot receive a PR."""
        a = _make_repo(tmp_path, "alpha")
        run(["register"], a, home)

        r = run(["install", "--all", "--pr"], a, home)

        assert r.returncode == 0
        assert "not a git repository" in r.stdout

    def test_git_repo_without_remote_skipped(self, tmp_path: Path, home: Path) -> None:
        a = _make_repo(tmp_path, "alpha")
        subprocess.run(["git", "init", "-q"], cwd=a, check=True)
        run(["register"], a, home)

        r = run(["install", "--all", "--pr"], a, home)

        assert r.returncode == 0
        assert "no 'origin' remote" in r.stdout

    def test_pr_mode_never_touches_working_tree(self, tmp_path: Path, home: Path) -> None:
        """The core safety property: ten repos, none of them disturbed.

        A repo with uncommitted work must come out of a --pr run byte-identical.
        """
        a = _make_repo(tmp_path, "alpha")
        subprocess.run(["git", "init", "-q"], cwd=a, check=True)
        scratch = a / "work-in-progress.txt"
        scratch.write_text("uncommitted work")
        run(["register"], a, home)

        run(["install", "--all", "--pr"], a, home)

        assert scratch.read_text() == "uncommitted work"
        assert not (a / ".claude").exists(), "PR mode must not write into the checkout"
