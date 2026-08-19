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
from dataclasses import dataclass, field
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


@dataclass
class DriftReport:
    feat_id: str
    base: str
    changed_files: list[str]
    criteria: list[Criterion]
    branch: str = ""
    on_feature_branch: bool = True

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


def _untracked_text(repo: Path, exclude: str | None = None) -> str:
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
            if exclude:
                try:
                    if str(f.relative_to(repo)).startswith(exclude):
                        continue
                except ValueError:
                    pass
            try:
                chunks.append(f.read_text(errors="replace"))
            except OSError:
                continue
    return "\n".join(chunks)


def _diff_text(repo: Path, base: str, exclude: str | None = None) -> str:
    """The branch's changes, optionally excluding a path prefix.

    The exclusion is not an optimisation — it is required for the result to mean
    anything. The spec being assessed states its own acceptance criteria, so if
    the spec file is in the haystack every AC trivially matches its own text and
    nothing is ever reported as drifted.
    """
    point = _merge_base(repo, base)
    pathspec = ["--", ".", f":(exclude){exclude}"] if exclude else []
    committed = _git(["diff", f"{point}...HEAD", *pathspec], repo)
    uncommitted = _git(["diff", "HEAD", *pathspec], repo)
    return "\n".join([committed, uncommitted, _untracked_text(repo, exclude)])


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
    """Compare a feature's acceptance criteria against what its branch changed."""
    feat_id = spec_path.parent.name.split("_")[0]
    criteria = extract_criteria(spec_path.read_text(errors="replace"))

    try:
        feature_dir = str(spec_path.parent.relative_to(repo))
    except ValueError:  # spec outside the repo — nothing to exclude
        feature_dir = None

    files = changed_files(repo, base)
    searchable = [f for f in files if not (feature_dir and f.startswith(feature_dir))]
    haystack = "\n".join(searchable) + "\n" + _diff_text(repo, base, feature_dir)

    for criterion in criteria:
        criterion.hits = [
            ref for ref in criterion.refs
            # Strip the call parens so `save_spec()` matches a definition too.
            if ref.rstrip("()") and ref.rstrip("()") in haystack
        ]

    branch = current_branch(repo)
    return DriftReport(
        feat_id=feat_id, base=base, changed_files=files, criteria=criteria,
        branch=branch, on_feature_branch=branch_matches(feat_id, branch),
    )
