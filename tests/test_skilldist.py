"""Cross-repo skill distribution (FEAT-020).

`meridian/skilldist.py` clones, force-pushes and opens pull requests in *other*
people's repositories. While it lived inside `cli.py` none of that could be
reached without the Typer app, so the riskiest code in the project had the
thinnest coverage — the only tests were end-to-end CLI runs.

These exercise the real functions against **real** temporary git repositories
built with `git init`: a bare repo standing in for `origin`, a seed repo that
pushes to it, and a clone. Nothing here mocks `subprocess`, because a mock of
git would only prove that the mock matches the assertions.

Deliberately **not** covered: the tail of `open_skill_pr` from `git push`
onward, which shells out to `gh` to list and create the pull request. Faking
`gh` would test the fake. That path is left to manual verification; everything
before it — worktree creation, the sync, the "nothing to do" early exit — is
covered here.
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from meridian import skilldist
from meridian.registry import ProjectEntry
from meridian.skilldist import (
    bundled_skills_dir,
    default_branch,
    open_skill_pr,
    open_skill_prs,
    run_git,
    sync_all,
    sync_skills,
)

# Keep the fixtures independent of whatever the developer has in ~/.gitconfig.
GIT_ENV = [
    "-c", "user.name=Meridian Test",
    "-c", "user.email=test@example.invalid",
    "-c", "commit.gpgsign=false",
]


def git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *GIT_ENV, *args], cwd=cwd, capture_output=True, text=True, check=True
    )


def entry_for(path: Path, slug: str = "alpha") -> ProjectEntry:
    return ProjectEntry(slug=slug, path=path, purpose="", exists=path.is_dir())


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    """A bare repo with one commit on `main`, usable as a push target."""
    bare = tmp_path / "origin.git"
    bare.mkdir()
    git(["init", "--bare", "-b", "main", "."], bare)

    seed = tmp_path / "seed"
    seed.mkdir()
    git(["init", "-b", "main", "."], seed)
    (seed / "README.md").write_text("seed\n")
    git(["add", "README.md"], seed)
    git(["commit", "-m", "initial"], seed)
    git(["remote", "add", "origin", str(bare)], seed)
    git(["push", "-u", "origin", "main"], seed)
    return bare


@pytest.fixture
def clone(tmp_path: Path, origin: Path) -> Path:
    """A working clone of `origin`, so `refs/remotes/origin/HEAD` is set."""
    target = tmp_path / "clone"
    git(["clone", str(origin), str(target)], tmp_path)
    return target


class TestSyncSkills:
    """Classification is the whole contract: new / changed / current / removed."""

    def test_first_run_is_all_new(self, tmp_path: Path) -> None:
        dest = tmp_path / "commands"
        bundled = sorted(p.stem for p in bundled_skills_dir().glob("*.md"))

        result = sync_skills(dest, force=False, dry_run=False)

        assert sorted(result.new) == bundled
        assert result.changed == [] and result.current == []
        assert result.written == len(bundled)
        assert sorted(p.stem for p in dest.glob("*.md")) == bundled

    def test_second_run_is_all_current(self, tmp_path: Path) -> None:
        dest = tmp_path / "commands"
        sync_skills(dest, force=False, dry_run=False)

        result = sync_skills(dest, force=False, dry_run=False)

        assert result.new == [] and result.changed == []
        assert result.current, "the installed copies must be recognised as identical"
        assert result.written == 0

    def test_edited_file_is_changed_not_current(self, tmp_path: Path) -> None:
        dest = tmp_path / "commands"
        sync_skills(dest, force=False, dry_run=False)
        victim = sorted(dest.glob("*.md"))[0]
        victim.write_text("locally customised\n")

        result = sync_skills(dest, force=False, dry_run=False)

        assert result.changed == [victim.stem]
        assert result.pending == 1
        assert result.written == 0
        assert victim.read_text() == "locally customised\n", "must not clobber without --force"

    def test_force_rewrites_the_changed_file(self, tmp_path: Path) -> None:
        dest = tmp_path / "commands"
        sync_skills(dest, force=False, dry_run=False)
        victim = sorted(dest.glob("*.md"))[0]
        victim.write_text("locally customised\n")

        result = sync_skills(dest, force=True, dry_run=False)

        assert result.changed == [victim.stem]
        assert result.written == 1
        assert victim.read_bytes() == (bundled_skills_dir() / victim.name).read_bytes()

    def test_dry_run_classifies_without_writing(self, tmp_path: Path) -> None:
        dest = tmp_path / "commands"

        result = sync_skills(dest, force=False, dry_run=True)

        assert result.new and result.written == len(result.new)
        assert not dest.exists(), "dry run must not even create the directory"

    def test_prune_removes_only_unbundled_files(self, tmp_path: Path) -> None:
        dest = tmp_path / "commands"
        sync_skills(dest, force=False, dry_run=False)
        stale = dest / "connect-dots.md"
        stale.write_text("no longer ships with Meridian\n")

        result = sync_skills(dest, force=False, dry_run=False, prune=True)

        assert result.removed == ["connect-dots"]
        assert not stale.exists()
        assert len(list(dest.glob("*.md"))) == len(list(bundled_skills_dir().glob("*.md")))

    def test_without_prune_a_stale_file_survives(self, tmp_path: Path) -> None:
        dest = tmp_path / "commands"
        sync_skills(dest, force=False, dry_run=False)
        stale = dest / "connect-dots.md"
        stale.write_text("no longer ships with Meridian\n")

        result = sync_skills(dest, force=False, dry_run=False)

        assert result.removed == []
        assert stale.exists(), "sync is additive by default — documented behaviour"

    def test_prune_dry_run_deletes_nothing(self, tmp_path: Path) -> None:
        dest = tmp_path / "commands"
        sync_skills(dest, force=False, dry_run=False)
        stale = dest / "connect-dots.md"
        stale.write_text("no longer ships with Meridian\n")

        result = sync_skills(dest, force=False, dry_run=True, prune=True)

        assert result.removed == ["connect-dots"]
        assert stale.exists()


class TestRunGit:
    def test_returns_output_from_a_real_repo(self, clone: Path) -> None:
        r = run_git(["rev-parse", "--abbrev-ref", "HEAD"], clone)
        assert r.returncode == 0
        assert r.stdout.strip() == "main"

    def test_non_zero_exit_does_not_raise(self, tmp_path: Path) -> None:
        """Every caller branches on `returncode`; an exception would bypass all of it."""
        not_a_repo = tmp_path / "plain"
        not_a_repo.mkdir()

        r = run_git(["rev-parse", "--git-dir"], not_a_repo)

        assert r.returncode != 0


class TestDefaultBranch:
    def test_resolves_from_remote_head_ref(self, clone: Path) -> None:
        # A fresh clone has this symbolic ref; that is the fast path.
        assert run_git(["symbolic-ref", "refs/remotes/origin/HEAD"], clone).returncode == 0

        assert default_branch(clone) == "main"

    def test_falls_back_to_remote_show(self, clone: Path) -> None:
        """`--single-branch` clones have no refs/remotes/origin/HEAD to read."""
        git(["symbolic-ref", "-d", "refs/remotes/origin/HEAD"], clone)
        assert run_git(["symbolic-ref", "refs/remotes/origin/HEAD"], clone).returncode != 0

        assert default_branch(clone) == "main"

    def test_none_without_a_remote(self, tmp_path: Path) -> None:
        repo = tmp_path / "lonely"
        repo.mkdir()
        git(["init", "-b", "main", "."], repo)

        assert default_branch(repo) is None


class TestOpenSkillPr:
    def test_skips_a_directory_that_is_not_a_repo(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()

        assert open_skill_pr(entry_for(plain), "v1.2.3", dry_run=True) == (
            "skipped", "not a git repository",
        )

    def test_skips_a_repo_without_an_origin(self, tmp_path: Path) -> None:
        repo = tmp_path / "lonely"
        repo.mkdir()
        git(["init", "-b", "main", "."], repo)

        assert open_skill_pr(entry_for(repo), "v1.2.3", dry_run=True) == (
            "skipped", "no 'origin' remote",
        )

    def test_dry_run_reports_the_branch_it_would_open(self, clone: Path) -> None:
        status, detail = open_skill_pr(entry_for(clone), "v1.2.3", dry_run=True)

        assert status == "would open"
        assert detail == "chore/meridian-skills-v1.2.3 → main"

    def test_dry_run_writes_nothing_into_the_checkout(self, clone: Path) -> None:
        open_skill_pr(entry_for(clone), "v1.2.3", dry_run=True)

        assert not (clone / ".claude").exists()
        assert run_git(["status", "--porcelain"], clone).stdout == ""

    def test_up_to_date_repo_short_circuits_before_gh(self, clone: Path, origin: Path) -> None:
        """The real worktree path, stopping before any `gh` call.

        `origin/main` already carries the current skills, so the throwaway
        worktree has nothing to commit and `open_skill_pr` returns early. This
        covers `git worktree add`, `checkout -B` and the sync inside it — the
        part that has to be right for the safety property to hold.
        """
        seed = clone.parent / "seed"
        sync_skills(seed / ".claude" / "commands" / "meridian", force=True, dry_run=False)
        git(["add", "-A"], seed)
        git(["commit", "-m", "add skills"], seed)
        git(["push", "origin", "main"], seed)

        status, detail = open_skill_pr(entry_for(clone), "v1.2.3", dry_run=False)

        assert (status, detail) == ("current", "skills already match")

    def test_the_checkout_is_never_disturbed(self, clone: Path, origin: Path) -> None:
        """The safety property: work in progress survives a --pr run untouched."""
        seed = clone.parent / "seed"
        sync_skills(seed / ".claude" / "commands" / "meridian", force=True, dry_run=False)
        git(["add", "-A"], seed)
        git(["commit", "-m", "add skills"], seed)
        git(["push", "origin", "main"], seed)
        wip = clone / "work-in-progress.txt"
        wip.write_text("uncommitted work")
        head_before = run_git(["rev-parse", "HEAD"], clone).stdout

        open_skill_pr(entry_for(clone), "v1.2.3", dry_run=False)

        assert wip.read_text() == "uncommitted work"
        assert run_git(["rev-parse", "HEAD"], clone).stdout == head_before
        assert not (clone / ".claude").exists()
        # The temporary worktree must be unregistered again, not left dangling.
        assert "meridian-skills-" not in run_git(["worktree", "list"], clone).stdout


class TestSyncAll:
    def test_returns_one_record_per_project_sorted_by_slug(self, tmp_path: Path) -> None:
        b = tmp_path / "beta"
        a = tmp_path / "alpha"
        a.mkdir()
        b.mkdir()

        outcomes = sync_all(
            [entry_for(b, "beta"), entry_for(a, "alpha")], force=False, dry_run=False
        )

        assert [o.slug for o in outcomes] == ["alpha", "beta"]
        assert {o.status for o in outcomes} == {"synced"}
        assert all(o.new and o.written == o.new for o in outcomes)

    def test_missing_path_is_a_record_not_an_exception(self, tmp_path: Path) -> None:
        gone = tmp_path / "gone"

        (outcome,) = sync_all([entry_for(gone, "gone")], force=False, dry_run=False)

        assert outcome.status == "skipped"
        assert "path not found" in outcome.detail
        assert (outcome.new, outcome.changed, outcome.current, outcome.written) == (0, 0, 0, 0)

    def test_one_unwritable_repo_does_not_stop_the_others(self, tmp_path: Path) -> None:
        broken = tmp_path / "broken"
        broken.mkdir()
        (broken / ".claude").write_text("a file where a directory must go")
        good = tmp_path / "good"
        good.mkdir()

        outcomes = sync_all(
            [entry_for(broken, "broken"), entry_for(good, "good")],
            force=False, dry_run=False,
        )

        by_slug = {o.slug: o for o in outcomes}
        assert by_slug["broken"].status == "failed"
        assert by_slug["broken"].detail
        assert by_slug["good"].status == "synced"
        assert (good / ".claude" / "commands" / "meridian").is_dir()

    def test_counts_reflect_a_second_pass(self, tmp_path: Path) -> None:
        repo = tmp_path / "alpha"
        repo.mkdir()
        sync_all([entry_for(repo)], force=False, dry_run=False)
        victim = sorted((repo / ".claude/commands/meridian").glob("*.md"))[0]
        victim.write_text("customised\n")

        (outcome,) = sync_all([entry_for(repo)], force=False, dry_run=False)

        assert outcome.new == 0
        assert outcome.changed == 1
        assert outcome.current > 0
        assert outcome.written == 0


class TestOpenSkillPrs:
    def test_records_every_project_and_reports_a_missing_path(self, tmp_path: Path) -> None:
        gone = tmp_path / "gone"
        plain = tmp_path / "plain"
        plain.mkdir()

        outcomes = open_skill_prs(
            [entry_for(plain, "plain"), entry_for(gone, "gone")], "v1.2.3", dry_run=True
        )

        assert [(o.slug, o.status, o.detail) for o in outcomes] == [
            ("gone", "skipped", "path not found"),
            ("plain", "skipped", "not a git repository"),
        ]

    def test_progress_hook_is_entered_once_per_reachable_repo(self, tmp_path: Path) -> None:
        """The hook is how `cli.py` keeps its spinner without this module knowing Rich."""
        import contextlib

        seen: list[str] = []

        @contextlib.contextmanager
        def spy(slug: str):
            seen.append(slug)
            yield

        plain = tmp_path / "plain"
        plain.mkdir()
        gone = tmp_path / "gone"

        open_skill_prs(
            [entry_for(plain, "plain"), entry_for(gone, "gone")],
            "v1.2.3", dry_run=True, progress=spy,
        )

        assert seen == ["plain"], "an unreachable path is skipped before the hook"

    def test_dry_run_over_a_real_clone(self, clone: Path) -> None:
        (outcome,) = open_skill_prs([entry_for(clone)], "v9.9.9", dry_run=True)

        assert outcome.status == "would open"
        assert outcome.detail == "chore/meridian-skills-v9.9.9 → main"


def test_module_imports_no_ui_libraries() -> None:
    """FEAT-020's entire point: this module returns data, `cli.py` renders it.

    An `import rich` creeping back in is how the git and GitHub paths became
    untestable the first time, so guard it structurally rather than by
    convention. Parsed rather than grepped — the docstring names both libraries.
    """
    tree = ast.parse(Path(skilldist.__file__).read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert not imported & {"typer", "rich", "click"}, (
        f"skilldist must stay free of UI libraries, found: {sorted(imported)}"
    )
