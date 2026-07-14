"""Skill model-selection contract tests.

Every bundled skill in ``meridian/skills/commands/*.md`` declares which model it
runs on via a ``model:`` line in its YAML frontmatter (see the per-skill model
selection design). Model IDs go stale as new generations ship — a skill left
pinned to a superseded ID silently runs on an old model with no test failure.

This module guards that class of drift: it asserts every declared ``model:`` is
in ``VALID_MODEL_IDS`` below. When a new model generation ships, update that set
(and the skill frontmatter) in one place and these tests confirm the sweep was
complete.

Run:  .venv/bin/pytest tests/test_models.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ── source of truth ──────────────────────────────────────────────────────── #

REPO_ROOT = Path(__file__).parents[1]
BUNDLED_SKILLS_DIR = REPO_ROOT / "meridian" / "skills" / "commands"

# Currently-valid model IDs. Keep this in sync with the model generation the
# skills are meant to target. Bump alongside skill frontmatter when a new
# generation ships; that keeps the change reviewable in one diff.
VALID_MODEL_IDS = frozenset(
    {
        "claude-fable-5",
        "claude-opus-4-8",
        "claude-sonnet-5",
        "claude-haiku-4-5-20251001",
    }
)

# ── frontmatter parsing ──────────────────────────────────────────────────── #


def _frontmatter_model(path: Path) -> str | None:
    """Return the ``model:`` value from a skill's YAML frontmatter, or None.

    Frontmatter is the leading ``---`` fenced block. We do a minimal line scan
    rather than pull in a YAML dependency — the frontmatter is trivial.
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    lines = text.splitlines()
    # lines[0] is the opening "---"; scan until the closing "---".
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith("model:"):
            return line.split(":", 1)[1].strip().strip("\"'")
    return None


def _skill_files() -> list[Path]:
    return sorted(BUNDLED_SKILLS_DIR.glob("*.md"))


# ── tests ────────────────────────────────────────────────────────────────── #


def test_skills_dir_exists() -> None:
    assert BUNDLED_SKILLS_DIR.is_dir(), (
        f"Bundled skills dir not found: {BUNDLED_SKILLS_DIR}"
    )
    assert _skill_files(), "No skill .md files found in bundled skills dir"


class TestSkillModelIDs:
    """Every skill that declares a model must use a currently-valid ID."""

    @pytest.mark.parametrize(
        "skill_path",
        _skill_files(),
        ids=lambda p: p.name,
    )
    def test_declared_model_is_valid(self, skill_path: Path) -> None:
        model = _frontmatter_model(skill_path)
        if model is None:
            pytest.skip(f"{skill_path.name} declares no model: frontmatter")
        assert model in VALID_MODEL_IDS, (
            f"[{skill_path.name}] declares `model: {model}` which is not a "
            f"currently-valid model ID.\n"
            f"Valid IDs: {sorted(VALID_MODEL_IDS)}\n"
            f"If a new model generation shipped, update VALID_MODEL_IDS in "
            f"tests/test_models.py and the skill frontmatter together."
        )


def test_no_skill_left_on_a_superseded_id() -> None:
    """Regression guard for the specific IDs this sweep replaced.

    These were the pre-refresh pins; if any skill regresses back to one of them
    (e.g. a stale copy re-introduced), fail loudly with the offending files.
    """
    superseded = {"claude-sonnet-4-6", "claude-opus-4-7"}
    offenders = {
        p.name: m
        for p in _skill_files()
        if (m := _frontmatter_model(p)) in superseded
    }
    assert not offenders, (
        f"Skills still pinned to a superseded model ID: {offenders}"
    )
