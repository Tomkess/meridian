"""Detect specs that no longer describe the code (FEAT-017).

Meridian's whole premise is that a spec stays true. Until now its entire
mechanism for that was a printed reminder — `close --status done` told you to go
and check. The audit named this the field's central unsolved problem, and noted
that being git-native is the one structural advantage Meridian has here: it can
see the diff.

The approach is deliberately a **heuristic, not a proof**. Each acceptance
criterion names things — functions, files, flags, modules — in backticks. If a
branch claims to satisfy an AC, the things that AC names should appear somewhere
in what the branch changed. An AC whose every reference is absent from the diff
is *suspicious*, not wrong: it may have been satisfied by code that happens to
use different words. The output says so, and ranks rather than judges.

What it reliably catches is the common real failure: an AC written during
planning, never implemented, and never removed from the spec.
"""
from __future__ import annotations

import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

# `- **AC3** — some text` / `- **AC12** ...`; tolerant of em dash, hyphen or colon.
_AC_LINE = re.compile(r"^\s*[-*]\s*\*\*(AC\d+[a-z]?)\*\*\s*[—–\-:]?\s*(.*)$")
_BACKTICKED = re.compile(r"`([^`]+)`")

# A backticked token is a *reference* only if it looks like an identifier rather
# than prose. Bare words ("done", "idea") appear in specs constantly and would
# match any diff, which would make every AC look covered.
_LOOKS_LIKE_CODE = re.compile(
    r"""
    (\w+\.(py|toml|md|lock|sh|yml|yaml|json)\b)  # a filename
    | (^--?[a-z][\w-]*$)                          # a CLI flag
    | (\w+\(\))                                   # a call
    | (\w+_\w+)                                   # snake_case
    | ([a-z]+\.[a-z_]+)                           # module.attr
    | (^[A-Z][a-zA-Z]*[A-Z]\w*$)                  # CamelCase
    """,
    re.VERBOSE,
)


@dataclass
class Criterion:
    id: str
    text: str
    refs: list[str] = field(default_factory=list)
    hits: list[str] = field(default_factory=list)

    @property
    def covered(self) -> bool:
        """True when at least one thing this AC names shows up in the diff."""
        return bool(self.hits)

    @property
    def checkable(self) -> bool:
        """False when the AC names nothing concrete — we cannot judge it."""
        return bool(self.refs)


#: How the diff under assessment was obtained.
#:
#: ``branch`` — the feature's branch is checked out and still has commits the
#: base does not. The original mode.
#:
#: ``history`` — the work is already merged, so there is no branch diff left to
#: read. FEAT-027: this was a real hole. `close --status done` runs drift
#: automatically, and by the time anyone runs it the branch is usually merged,
#: so the one moment the check fires was the one moment it could say nothing.
#:
#: ``none`` — neither: no branch diff and no commits in history naming the
#: feature. Reported honestly rather than as a clean bill of health.
MODE_BRANCH = "branch"
MODE_HISTORY = "history"
MODE_NONE = "none"


@dataclass
class DriftReport:
    feat_id: str
    base: str
    changed_files: list[str]
    criteria: list[Criterion]
    branch: str = ""
    on_feature_branch: bool = True
    mode: str = MODE_BRANCH
    commits: list[str] = field(default_factory=list)

    @property
    def checkable(self) -> list[Criterion]:
        return [c for c in self.criteria if c.checkable]

    @property
    def uncovered(self) -> list[Criterion]:
        return [c for c in self.checkable if not c.covered]

    @property
    def unjudgeable(self) -> list[Criterion]:
        return [c for c in self.criteria if not c.checkable]


def extract_criteria(spec_text: str) -> list[Criterion]:
    """Pull acceptance criteria and the concrete things they name.

    An AC continues onto following indented lines, which is how they are
    actually written — so the reference in a wrapped line is not lost.
    """
    criteria: list[Criterion] = []
    current: Criterion | None = None

    for line in spec_text.splitlines():
        match = _AC_LINE.match(line)
        if match:
            current = Criterion(id=match.group(1), text=match.group(2).strip())
            criteria.append(current)
            continue
        if current is None:
            continue
        # A continuation line is indented and not the start of a new list item.
        if line.startswith((" ", "\t")) and not _AC_LINE.match(line):
            current.text += " " + line.strip()
        elif line.strip():
            current = None

    for criterion in criteria:
        seen: list[str] = []
        for token in _BACKTICKED.findall(criterion.text):
            token = token.strip()
            if _LOOKS_LIKE_CODE.search(token) and token not in seen:
                seen.append(token)
        criterion.refs = seen
    return criteria


def _git(args: list[str], repo: Path) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, timeout=60
    )
    return result.stdout if result.returncode == 0 else ""


def _merge_base(repo: Path, base: str) -> str:
    return _git(["merge-base", base, "HEAD"], repo).strip() or base


def _porcelain(repo: Path) -> list[tuple[str, str]]:
    """(status_code, path) for each entry in `git status --porcelain`."""
    entries = []
    for line in _git(["status", "--porcelain"], repo).splitlines():
        if len(line) > 3:
            entries.append((line[:2].strip(), line[3:].strip()))
    return entries


def changed_files(repo: Path, base: str) -> list[str]:
    """Files this branch changed relative to *base*, including uncommitted work."""
    point = _merge_base(repo, base)
    committed = _git(["diff", "--name-only", f"{point}...HEAD"], repo).split()
    return sorted(set(committed) | {path for _code, path in _porcelain(repo)})


#: Paths kept out of the haystack no matter which feature is being assessed.
#:
#: A spec states its own acceptance criteria, so a spec in the haystack lets
#: every AC match its own text and nothing is ever reported as drifted. The
#: original code excluded only the feature under assessment, which was enough
#: while a diff covered one feature. It is not enough in history mode: a single
#: commit that shapes or closes four features drags all four specs in, and an AC
#: then matches its own words quoted in a *sibling's* spec — the same failure
#: through a neighbour's door.
#:
#: Only `specs/FEAT-*` is excluded, not `specs/` wholesale: `REGISTRY.md`,
#: `goals/` and `CYCLES.md` are legitimate things for an AC to name.
SPEC_EXCLUDES = ("specs/FEAT-*",)


def _excluded(rel_path: str, excludes: Sequence[str]) -> bool:
    """True when *rel_path* matches any exclusion pattern or sits beneath one."""
    return any(
        fnmatch(rel_path, pattern)
        or fnmatch(rel_path, f"{pattern.rstrip('/')}/*")
        or rel_path.startswith(pattern.rstrip("*").rstrip("/") + "/")
        for pattern in excludes
    )


def _pathspec(excludes: Sequence[str]) -> list[str]:
    return ["--", ".", *(f":(exclude){p}" for p in excludes)] if excludes else []


def _untracked_text(repo: Path, excludes: Sequence[str] = ()) -> str:
    """Contents of files git has never seen.

    Without this every brand-new module reads as unimplemented: `git diff` has
    nothing to say about an untracked file, so an AC naming a function defined
    only there finds no match. A new feature's main module is untracked more
    often than not, which made this the single largest source of false
    positives on the first live run.
    """
    chunks = []
    for code, path in _porcelain(repo):
        if not code.startswith("?"):
            continue
        candidate = repo / path
        # git reports an untracked *directory* as a single entry, so the
        # exclusion has to be applied per resolved file — checking the reported
        # path alone lets `specs/` slip through and drag the spec back in.
        files = (
            [f for f in candidate.rglob("*") if f.is_file()]
            if candidate.is_dir() else [candidate]
        )
        for f in files:
            if f.suffix not in {".py", ".md", ".toml", ".sh", ".yml", ".yaml", ".json"}:
                continue
            try:
                if _excluded(str(f.relative_to(repo)), excludes):
                    continue
            except ValueError:
                pass
            try:
                chunks.append(f.read_text(errors="replace"))
            except OSError:
                continue
    return "\n".join(chunks)


def _diff_text(repo: Path, base: str, excludes: Sequence[str] = ()) -> str:
    """The branch's changes, excluding the paths in *excludes*.

    The exclusion is not an optimisation — it is required for the result to mean
    anything. See :data:`SPEC_EXCLUDES`.
    """
    point = _merge_base(repo, base)
    pathspec = _pathspec(excludes)
    committed = _git(["diff", f"{point}...HEAD", *pathspec], repo)
    uncommitted = _git(["diff", "HEAD", *pathspec], repo)
    return "\n".join([committed, uncommitted, _untracked_text(repo, excludes)])


def feature_commits(repo: Path, feat_id: str, base: str) -> list[str]:
    """Commits already in *base* that built this feature, newest first.

    Once a feature is merged there is no branch diff left to read, so the work
    has to be found in history instead. Three signals, in descending order of
    how much they mean:

    * a **merge commit** naming the feature — Meridian's own convention is
      ``Merge FEAT-NNN: ...`` or a ``feat-NNN/slug`` branch name, and a merge
      carries the whole feature in one object;
    * an ordinary **commit whose message names the feature**, which is what a
      squash merge or a direct-to-main commit leaves behind;
    * a commit that **touched the feature's spec directory**, which catches work
      whose message forgot the ID.

    All three are unioned. Double-counting a commit is harmless: the result is a
    text haystack, and the same reference appearing twice is still one hit.
    """
    found: list[str] = []
    seen: set[str] = set()

    searches = [
        ["log", base, "--merges", "-i", f"--grep={feat_id}", "--format=%H"],
        ["log", base, "--no-merges", "-i", f"--grep={feat_id}", "--format=%H"],
        ["log", base, "--format=%H", "--", f"specs/{feat_id.upper()}_*"],
    ]
    for args in searches:
        for sha in _git(args, repo).split():
            if sha not in seen:
                seen.add(sha)
                found.append(sha)
    return found


def _commit_diff(repo: Path, sha: str, excludes: Sequence[str] = ()) -> tuple[str, list[str]]:
    """One commit's changes as ``(diff_text, changed_files)``.

    A merge is diffed against its **first** parent, so the result is what the
    merge brought onto the mainline rather than the unrelated mainline commits
    the branch had not yet seen.
    """
    parents = _git(["rev-list", "--parents", "-n", "1", sha], repo).split()
    first_parent = parents[1] if len(parents) > 1 else None
    pathspec = _pathspec(excludes)

    if first_parent is None:
        # A root commit has nothing to diff against; show it whole.
        text = _git(["show", "--format=", sha, *pathspec], repo)
        names = _git(["show", "--format=", "--name-only", sha, *pathspec], repo).split()
    else:
        text = _git(["diff", first_parent, sha, *pathspec], repo)
        names = _git(["diff", "--name-only", first_parent, sha, *pathspec], repo).split()
    return text, names


def history_diff(
    repo: Path, feat_id: str, base: str, excludes: Sequence[str] = ()
) -> tuple[str, list[str], list[str]]:
    """The feature's changes as recorded in *base*'s history.

    Returns ``(diff_text, changed_files, commits)``.
    """
    commits = feature_commits(repo, feat_id, base)
    texts: list[str] = []
    files: set[str] = set()
    for sha in commits:
        text, names = _commit_diff(repo, sha, excludes)
        if text:
            texts.append(text)
        files.update(names)
    return "\n".join(texts), sorted(files), commits


def current_branch(repo: Path) -> str:
    return _git(["rev-parse", "--abbrev-ref", "HEAD"], repo).strip()


def branch_matches(feat_id: str, branch: str) -> bool:
    """True when the checked-out branch looks like this feature's branch.

    Without this the report is nonsense: asked about FEAT-013 from a branch
    building FEAT-017, it compares one feature's criteria against another's
    diff and calls everything uncovered. Meridian's own branch convention is
    `feat-NNN/slug`, which makes the check trivial and reliable.
    """
    return feat_id.lower() in branch.lower()


def assess(spec_path: Path, repo: Path, base: str = "main") -> DriftReport:
    """Compare a feature's acceptance criteria against what actually changed.

    Prefers the branch diff when there is one, and falls back to the feature's
    commits in *base*'s history when there is not. The fallback is the whole
    point after FEAT-027: a merged feature has no branch diff, and that is
    exactly when `close --status done` asks.
    """
    feat_id = spec_path.parent.name.split("_")[0]
    criteria = extract_criteria(spec_path.read_text(errors="replace"))

    excludes = list(SPEC_EXCLUDES)
    try:
        # Kept alongside the generic pattern for a project whose specs live
        # somewhere other than `specs/FEAT-*`.
        excludes.append(str(spec_path.parent.relative_to(repo)))
    except ValueError:  # spec outside the repo — nothing to exclude
        pass

    branch = current_branch(repo)
    on_feature_branch = branch_matches(feat_id, branch)

    files = changed_files(repo, base)
    commits: list[str] = []
    mode = MODE_BRANCH

    # A branch diff only counts when it is *this feature's* branch. Reading
    # another feature's diff produces confident nonsense, which is why the
    # original refused rather than guessed.
    if files and on_feature_branch:
        diff_text = _diff_text(repo, base, excludes)
    else:
        diff_text, files, commits = history_diff(repo, feat_id, base, excludes)
        mode = MODE_HISTORY if commits else MODE_NONE

    searchable = [f for f in files if not _excluded(f, excludes)]
    haystack = "\n".join(searchable) + "\n" + diff_text

    for criterion in criteria:
        criterion.hits = [
            ref for ref in criterion.refs
            # Strip the call parens so `save_spec()` matches a definition too.
            if ref.rstrip("()") and ref.rstrip("()") in haystack
        ]

    return DriftReport(
        feat_id=feat_id, base=base, changed_files=files, criteria=criteria,
        branch=branch, on_feature_branch=on_feature_branch,
        mode=mode, commits=commits,
    )
