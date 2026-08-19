"""Cross-repo skill distribution — the git and GitHub half of `meridian install`.

This module holds everything that reaches *outside* the current repository:
copying bundled skills into another project's `.claude/commands/meridian/`,
building a throwaway worktree off `origin/HEAD`, force-pushing a branch, and
opening a pull request with `gh`.

It is the riskiest code in the project — it writes, pushes and opens PRs in the
user's other repositories — and it used to live inside `meridian/cli.py`, where
it could not be exercised without importing the whole Typer app. Splitting it
out is what makes those paths testable against real temporary git repos.

**The boundary is the point.** Nothing here imports `typer` or `rich`, touches a
`Console`, prints, or raises `typer.Exit`. Every function *returns data*: a
`SkillSync` for one directory, a `SyncOutcome` / `PrOutcome` per tracked project
for the fan-out helpers. All rendering and all process-exit decisions stay in
`cli.py`, which owns the tables and the exit codes.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

import meridian
from meridian.registry import ProjectEntry

# A caller-supplied "working on <slug>…" indicator. `cli.py` passes
# `console.status`; the default is a no-op so the module stays Rich-free.
Progress = Callable[[str], AbstractContextManager[object]]


def _no_progress(_label: str) -> AbstractContextManager[object]:
    return nullcontext()


@dataclass
class SkillSync:
    """What a skill install did, or would do."""
    new: list[str]
    changed: list[str]     # present but differs from the bundled version
    current: list[str]     # byte-identical, nothing to do
    written: int
    removed: list[str] = field(default_factory=list)  # deleted upstream, pruned here

    @property
    def pending(self) -> int:
        """Files that differ and were not written (needs --force)."""
        return len(self.changed)


class SyncOutcome(NamedTuple):
    """One tracked project's result from a working-tree sync.

    `status` is one of `synced`, `skipped` (path not found) or `failed` (the
    copy raised `OSError`). The counts are zero for anything but `synced`.
    """
    slug: str
    status: str
    detail: str
    new: int = 0
    changed: int = 0
    current: int = 0
    written: int = 0
    removed: int = 0


class PrOutcome(NamedTuple):
    """One tracked project's result from a PR-mode run.

    `status` is one of `opened`, `updated`, `would open`, `current`, `skipped`
    or `failed`; `detail` is the PR URL, the branch, or the reason.
    """
    slug: str
    status: str
    detail: str


def bundled_skills_dir() -> Path:
    """Where the skills that ship inside the installed package live."""
    return Path(meridian.__file__).parent / "skills" / "commands"


def sync_skills(
    dest: Path, *, force: bool, dry_run: bool, prune: bool = False
) -> SkillSync:
    """Copy bundled skills into *dest*, reporting drift.

    Compares content rather than mere existence: "already installed" hides the
    case that actually matters after an upgrade — a skill that is present but
    stale. An outdated file is only overwritten with --force, so a project that
    deliberately customised a skill is never silently clobbered.

    Sync is additive unless *prune* is set. FEAT-016: a skill deleted from the
    package used to linger in every repo forever, so removing one here changed
    nothing anywhere — the four skills cut in FEAT-014 were still sitting in
    five repos after a full propagation. Pruning is opt-in because deleting
    files across ten repos is a bigger decision than updating them.
    """
    src_dir = bundled_skills_dir()
    new: list[str] = []
    changed: list[str] = []
    current: list[str] = []
    written = 0

    if not dry_run:
        dest.mkdir(parents=True, exist_ok=True)

    for skill in sorted(src_dir.glob("*.md")):
        target = dest / skill.name
        if not target.exists():
            new.append(skill.stem)
        elif target.read_bytes() == skill.read_bytes():
            current.append(skill.stem)
            continue
        else:
            changed.append(skill.stem)
            if not force:
                continue

        if not dry_run:
            shutil.copy2(skill, target)
        written += 1

    removed: list[str] = []
    if prune and dest.is_dir():
        bundled_names = {s.name for s in src_dir.glob("*.md")}
        for stale in sorted(dest.glob("*.md")):
            if stale.name not in bundled_names:
                removed.append(stale.stem)
                if not dry_run:
                    stale.unlink()

    return SkillSync(
        new=new, changed=changed, current=current, written=written, removed=removed
    )


def run_git(
    args: list[str], cwd: Path, timeout: int = 60
) -> subprocess.CompletedProcess[str]:
    """Run git, capturing output. Never raises on a non-zero exit."""
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout
    )


def default_branch(repo: Path) -> str | None:
    """The remote's default branch, e.g. 'main'. None when there is no remote."""
    r = run_git(["symbolic-ref", "refs/remotes/origin/HEAD"], repo)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip().rsplit("/", 1)[-1]
    # Fall back to asking the remote directly — refs/remotes/origin/HEAD is not
    # always present on a clone made with --single-branch.
    r = run_git(["remote", "show", "origin"], repo, timeout=30)
    if r.returncode == 0:
        for line in r.stdout.splitlines():
            if "HEAD branch:" in line:
                return line.split(":", 1)[1].strip()
    return None


def open_skill_pr(
    entry: ProjectEntry, version: str, *, dry_run: bool, prune: bool = False
) -> tuple[str, str]:
    """Propose a skill update to one repo as a pull request.

    Returns (status, detail) for the summary table.

    The copy happens inside a throwaway git worktree, never the repo's own
    working tree: these are ten repos the user may have work in progress in, and
    silently mutating a checkout — or moving its HEAD — is exactly the failure
    this project has already been bitten by.
    """
    if not (entry.path / ".git").exists():
        return "skipped", "not a git repository"

    if run_git(["remote", "get-url", "origin"], entry.path).returncode != 0:
        return "skipped", "no 'origin' remote"

    base = default_branch(entry.path)
    if base is None:
        return "skipped", "could not resolve the default branch"

    branch = f"chore/meridian-skills-{version}"

    fetch = run_git(["fetch", "origin", base], entry.path, timeout=120)
    if fetch.returncode != 0:
        return "failed", f"fetch failed: {fetch.stderr.strip().splitlines()[-1:] or ''}"

    if dry_run:
        return "would open", f"{branch} → {base}"

    tmp = Path(tempfile.mkdtemp(prefix="meridian-skills-"))
    worktree = tmp / "wt"
    try:
        add = run_git(
            ["worktree", "add", "--detach", str(worktree), f"origin/{base}"],
            entry.path, timeout=120,
        )
        if add.returncode != 0:
            return "failed", f"worktree: {add.stderr.strip().splitlines()[-1:] or ''}"

        run_git(["checkout", "-B", branch], worktree)
        result = sync_skills(
            worktree / ".claude" / "commands" / "meridian",
            force=True, dry_run=False, prune=prune,
        )
        if not result.written and not result.removed:
            return "current", "skills already match"

        run_git(["add", ".claude/commands/meridian"], worktree)
        if not run_git(["diff", "--cached", "--quiet"], worktree).returncode:
            return "current", "no net change"

        removed_note = f", {len(result.removed)} removed" if result.removed else ""
        message = (
            f"chore: update Meridian skills to {version}\n\n"
            f"{len(result.new)} added, {len(result.changed)} updated{removed_note}. "
            "Generated by `meridian install --all --pr`.\n"
        )
        commit = run_git(["commit", "-m", message], worktree)
        if commit.returncode != 0:
            return "failed", "commit failed"

        push = run_git(["push", "-u", "origin", branch, "--force-with-lease"], worktree, timeout=180)
        if push.returncode != 0:
            return "failed", f"push failed: {(push.stderr.strip().splitlines() or [''])[-1]}"

        existing = subprocess.run(
            ["gh", "pr", "list", "--head", branch, "--json", "url", "--jq", ".[0].url"],
            cwd=worktree, capture_output=True, text=True, timeout=60,
        )
        if existing.returncode == 0 and existing.stdout.strip():
            return "updated", existing.stdout.strip()

        pr = subprocess.run(
            ["gh", "pr", "create", "--base", base, "--head", branch,
             "--title", f"chore: update Meridian skills to {version}",
             "--body",
             f"Syncs `.claude/commands/meridian/` with Meridian {version}.\n\n"
             f"- {len(result.new)} skill(s) added\n"
             f"- {len(result.changed)} skill(s) updated\n"
             + (f"- {len(result.removed)} skill(s) removed (no longer ship with "
                f"Meridian): {', '.join(result.removed)}\n" if result.removed else "")
             + "\n"
             "Opened by `meridian install --all --pr`.\n"],
            cwd=worktree, capture_output=True, text=True, timeout=120,
        )
        if pr.returncode != 0:
            return "failed", (pr.stderr.strip().splitlines() or ["gh pr create failed"])[-1]
        return "opened", pr.stdout.strip().splitlines()[-1] if pr.stdout.strip() else branch

    except (OSError, subprocess.SubprocessError) as e:
        return "failed", str(e)
    finally:
        run_git(["worktree", "remove", "--force", str(worktree)], entry.path)
        shutil.rmtree(tmp, ignore_errors=True)


def sync_all(
    entries: Iterable[ProjectEntry], *, force: bool, dry_run: bool, prune: bool = False
) -> list[SyncOutcome]:
    """Refresh skills in every tracked project, returning one record each.

    The point of the project registry: after upgrading meridian, one command
    brings every repo's committed skills up to date instead of ten manual
    `--project` runs.

    A path that no longer resolves and a directory that cannot be written are
    both reported as records, never raised — one unreachable repo must not stop
    the other nine.
    """
    outcomes: list[SyncOutcome] = []
    for entry in sorted(entries, key=lambda e: e.slug):
        if not entry.exists:
            outcomes.append(SyncOutcome(entry.slug, "skipped", "path not found — skipped"))
            continue

        dest = entry.path / ".claude" / "commands" / "meridian"
        try:
            result = sync_skills(dest, force=force, dry_run=dry_run, prune=prune)
        except OSError as e:
            outcomes.append(SyncOutcome(entry.slug, "failed", str(e.strerror or e)))
            continue

        outcomes.append(SyncOutcome(
            slug=entry.slug,
            status="synced",
            detail="",
            new=len(result.new),
            changed=len(result.changed),
            current=len(result.current),
            written=result.written,
            removed=len(result.removed),
        ))
    return outcomes


def open_skill_prs(
    entries: Iterable[ProjectEntry],
    version: str,
    *,
    dry_run: bool,
    prune: bool = False,
    progress: Progress = _no_progress,
) -> list[PrOutcome]:
    """Open (or preview) a skill-update PR in every tracked project (FEAT-010).

    *progress* is entered around each repo's turn so a caller can show a
    spinner; it defaults to a no-op, which is what keeps this module free of
    any console dependency.
    """
    outcomes: list[PrOutcome] = []
    for entry in sorted(entries, key=lambda e: e.slug):
        if not entry.exists:
            outcomes.append(PrOutcome(entry.slug, "skipped", "path not found"))
            continue
        with progress(entry.slug):
            status, detail = open_skill_pr(entry, version, dry_run=dry_run, prune=prune)
        outcomes.append(PrOutcome(entry.slug, status, detail))
    return outcomes
