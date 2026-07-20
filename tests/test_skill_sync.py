"""Drift guard: bundled skills ↔ in-repo ``.claude/commands/meridian`` copies (FEAT-003).

Meridian ships each skill twice — the source of truth in
``meridian/skills/commands/`` and the in-repo Claude Code copies in
``.claude/commands/meridian/`` that this repository uses when dogfooding. They must stay
structurally consistent; a manual edit to one that skips the other is the exact
drift the FEAT-003 engine was built to catch.

This wires the ``skill_consistency`` structural comparison into CI (it runs in
the existing ``pytest`` step, model-free). The runtime ``--skill`` twice-over
mode is model-gated and runs interactively, not here.

Run:  pytest tests/test_skill_sync.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# The harness lives in scripts/, which is not an installed package.
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from skill_consistency import compare_texts  # noqa: E402

REPO_ROOT = Path(__file__).parents[1]
BUNDLED = REPO_ROOT / "meridian" / "skills" / "commands"
INREPO = REPO_ROOT / ".claude" / "commands" / "meridian"


def _bundled_skills() -> list[Path]:
    return sorted(BUNDLED.glob("*.md"))


def test_skill_dirs_exist() -> None:
    assert _bundled_skills(), f"No bundled skills found in {BUNDLED}"
    assert INREPO.is_dir(), f"In-repo commands dir not found: {INREPO}"


def test_same_skill_set() -> None:
    bundled = {p.name for p in _bundled_skills()}
    inrepo = {p.name for p in INREPO.glob("*.md")}
    missing = bundled - inrepo
    extra = inrepo - bundled
    assert not missing and not extra, (
        f"Skill set drift between bundled and .claude/commands/meridian.\n"
        f"  Missing from .claude/commands/meridian: {sorted(missing)}\n"
        f"  Extra in .claude/commands/meridian:     {sorted(extra)}\n"
        f"Re-sync .claude/commands/meridian/ with meridian/skills/commands/."
    )


@pytest.mark.parametrize(
    "skill_path",
    _bundled_skills(),
    ids=lambda p: p.name,
)
def test_bundled_and_inrepo_are_structurally_consistent(skill_path: Path) -> None:
    counterpart = INREPO / skill_path.name
    if not counterpart.exists():
        pytest.skip(f"{skill_path.name} has no .claude/commands/meridian counterpart")
    report = compare_texts(skill_path.read_text(), counterpart.read_text())
    assert report.consistent, (
        f"Structural drift in {skill_path.name} between the bundled skill and "
        f"its .claude/commands/meridian copy:\n"
        + report.render("bundled", ".claude/commands/meridian")
    )
