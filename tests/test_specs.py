"""Tests for meridian/specs.py — state machine, I/O, slug, task progress, registry."""
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from meridian.specs import (
    VALID_TRANSITIONS,
    _slugify,
    all_specs,
    create_spec,
    feat_display_name,
    load_spec,
    next_feat_id,
    rebuild_registry,
    save_spec,
    scan_decisions,
    task_progress,
    transition_spec,
)

# ── _slugify ─────────────────────────────────────────────────────────────── #


class TestSlugify:
    def test_normal_words(self):
        assert _slugify("add user authentication flow") == "add_user_authentication_flow"

    def test_truncates_to_five_words(self):
        assert _slugify("a b c d e f g") == "a_b_c_d_e"

    def test_strips_punctuation(self):
        assert _slugify("Hello, World! It's great") == "hello_world_its_great"

    def test_empty_string_returns_untitled(self):
        # G2: all-symbol / empty ideas must not produce an empty slug
        assert _slugify("") == "untitled"

    def test_all_special_chars_returns_untitled(self):
        assert _slugify("!@#$%^&*()") == "untitled"

    def test_custom_max_words(self):
        assert _slugify("a b c d e f", max_words=3) == "a_b_c"


# ── feat_display_name ────────────────────────────────────────────────────── #


class TestFeatDisplayName:
    def test_returns_id_and_readable_name(self, specs_dir: Path) -> None:
        (specs_dir / "FEAT-001_add_semantic_search").mkdir()
        assert feat_display_name(specs_dir, "feat-001") == "FEAT-001: add semantic search"

    def test_handles_uppercase_input(self, specs_dir: Path) -> None:
        (specs_dir / "FEAT-002_user_auth").mkdir()
        assert feat_display_name(specs_dir, "FEAT-002") == "FEAT-002: user auth"

    def test_falls_back_to_id_when_no_dir(self, specs_dir: Path) -> None:
        assert feat_display_name(specs_dir, "feat-999") == "FEAT-999"

    def test_single_word_slug(self, specs_dir: Path) -> None:
        (specs_dir / "FEAT-003_search").mkdir()
        assert feat_display_name(specs_dir, "feat-003") == "FEAT-003: search"


# ── next_feat_id ─────────────────────────────────────────────────────────── #


class TestNextFeatId:
    def test_empty_dir(self, specs_dir: Path):
        assert next_feat_id(specs_dir) == "FEAT-001"

    def test_with_one_existing(self, specs_dir: Path):
        (specs_dir / "FEAT-001_foo").mkdir()
        assert next_feat_id(specs_dir) == "FEAT-002"

    def test_skips_gaps(self, specs_dir: Path):
        (specs_dir / "FEAT-001_a").mkdir()
        (specs_dir / "FEAT-003_b").mkdir()
        assert next_feat_id(specs_dir) == "FEAT-004"

    def test_zero_pads_to_three_digits(self, specs_dir: Path):
        for i in range(1, 10):
            (specs_dir / f"FEAT-00{i}_x").mkdir()
        assert next_feat_id(specs_dir) == "FEAT-010"


# ── create_spec ──────────────────────────────────────────────────────────── #


class TestCreateSpec:
    def test_creates_spec_and_support_dirs(self, specs_dir: Path):
        path = create_spec(specs_dir, "my new feature")
        assert path.exists()
        parent = path.parent
        assert (parent / "tasks.md").exists()
        assert (parent / "sources").is_dir()
        assert (parent / "summaries").is_dir()

    def test_frontmatter_defaults(self, specs_dir: Path):
        path = create_spec(specs_dir, "test feature")
        data = load_spec(path)
        assert data["status"] == "idea"
        assert data["appetite"] is None
        assert data["confidence"] is None
        assert data["depends_on"] == []
        assert data["enables"] == []

    def test_frontmatter_with_goal_and_appetite(self, specs_dir: Path):
        path = create_spec(specs_dir, "test", goal="goal-01", appetite="m")
        data = load_spec(path)
        assert data["goal"] == "goal-01"
        assert data["appetite"] == "m"

    def test_id_is_lowercase(self, specs_dir: Path):
        path = create_spec(specs_dir, "test")
        data = load_spec(path)
        assert data["id"] == "feat-001"

    def test_sequential_ids(self, specs_dir: Path):
        p1 = create_spec(specs_dir, "first feature")
        p2 = create_spec(specs_dir, "second feature")
        assert load_spec(p1)["id"] == "feat-001"
        assert load_spec(p2)["id"] == "feat-002"

    def test_directory_name_uses_slug(self, specs_dir: Path):
        path = create_spec(specs_dir, "semantic search feature")
        assert "semantic_search_feature" in path.parent.name


# ── transition_spec ──────────────────────────────────────────────────────── #


class TestTransitionSpec:
    def test_valid_idea_to_draft(self, specs_dir: Path):
        path = create_spec(specs_dir, "test")
        data = transition_spec(path, "draft")
        assert data["status"] == "draft"

    def test_invalid_status_raises(self, specs_dir: Path):
        path = create_spec(specs_dir, "test")
        with pytest.raises(ValueError, match="Invalid status"):
            transition_spec(path, "nonexistent")

    def test_disallowed_transition_raises(self, specs_dir: Path):
        path = create_spec(specs_dir, "test")
        # idea → in-progress is not in VALID_TRANSITIONS["idea"]
        with pytest.raises(ValueError, match="Cannot transition"):
            transition_spec(path, "in-progress")

    def test_blocked_sets_blocked_at(self, specs_dir: Path):
        path = create_spec(specs_dir, "test")
        transition_spec(path, "draft")
        transition_spec(path, "in-progress")
        data = transition_spec(path, "blocked")
        assert data["blocked_at"] is not None

    def test_unblocking_clears_blocked_fields(self, specs_dir: Path):
        path = create_spec(specs_dir, "test")
        transition_spec(path, "draft")
        transition_spec(path, "in-progress")
        transition_spec(path, "blocked", extra={"blocked_by": "external dep"})
        data = transition_spec(path, "in-progress")
        assert data["blocked_at"] is None
        assert data["blocked_by"] is None

    def test_abandoned_sets_abandoned_at(self, specs_dir: Path):
        path = create_spec(specs_dir, "test")
        data = transition_spec(path, "abandoned")
        assert data["abandoned_at"] is not None

    def test_revive_clears_abandoned_at_preserves_reason(self, specs_dir: Path):
        path = create_spec(specs_dir, "test")
        transition_spec(path, "abandoned", extra={"abandoned_reason": "not now"})
        data = transition_spec(path, "idea")
        assert data["abandoned_at"] is None
        assert data["abandoned_reason"] == "not now"  # reason preserved through revive

    def test_extra_fields_applied_in_single_save(self, specs_dir: Path):
        """B3: extra fields must land in the file without a second save call."""
        path = create_spec(specs_dir, "test")
        transition_spec(path, "draft")
        transition_spec(path, "in-progress")
        data = transition_spec(path, "blocked", extra={"blocked_by": "waiting for infra"})
        assert data["blocked_by"] == "waiting for infra"
        # Verify it actually persisted to disk
        reloaded = load_spec(path)
        assert reloaded["blocked_by"] == "waiting for infra"

    def test_extra_confidence_persists(self, specs_dir: Path):
        path = create_spec(specs_dir, "test")
        data = transition_spec(path, "draft", extra={"confidence": "high"})
        assert data["confidence"] == "high"
        assert load_spec(path)["confidence"] == "high"

    @pytest.mark.parametrize(
        "from_status, to_status",
        [
            (from_s, to_s)
            for from_s, allowed in VALID_TRANSITIONS.items()
            for to_s in allowed
        ],
    )
    def test_every_valid_transition(self, specs_dir: Path, from_status: str, to_status: str):
        """Exhaustive: every cell in VALID_TRANSITIONS must succeed."""
        path = create_spec(specs_dir, f"test {from_status} to {to_status}")
        # Force the spec directly to the required from_status
        data = load_spec(path)
        data["status"] = from_status
        save_spec(path, data)
        result = transition_spec(path, to_status)
        assert result["status"] == to_status


# ── save_spec no-op guard ────────────────────────────────────────────────── #


class TestSaveSpec:
    def test_noop_does_not_bump_updated(self, specs_dir: Path):
        """B5: loading and re-saving an unchanged spec must not update the date."""
        with patch("meridian.specs._today", return_value="2026-01-01"):
            path = create_spec(specs_dir, "test")

        data = load_spec(path)
        assert data["updated"] == "2026-01-01"

        # Attempt a no-op save on a different day
        with patch("meridian.specs._today", return_value="2026-12-31"):
            save_spec(path, data)

        reloaded = load_spec(path)
        assert reloaded["updated"] == "2026-01-01"  # not 2026-12-31

    def test_changed_content_bumps_updated(self, specs_dir: Path):
        with patch("meridian.specs._today", return_value="2026-01-01"):
            path = create_spec(specs_dir, "test")

        data = load_spec(path)
        data["appetite"] = "l"

        with patch("meridian.specs._today", return_value="2026-12-31"):
            save_spec(path, data)

        reloaded = load_spec(path)
        assert reloaded["updated"] == "2026-12-31"
        assert reloaded["appetite"] == "l"


# ── all_specs ────────────────────────────────────────────────────────────── #


class TestAllSpecs:
    def test_empty_dir(self, specs_dir: Path):
        assert all_specs(specs_dir) == []

    def test_returns_all_valid(self, specs_dir: Path):
        create_spec(specs_dir, "first")
        create_spec(specs_dir, "second")
        results = all_specs(specs_dir)
        assert len(results) == 2

    def test_skips_malformed_with_warning(self, specs_dir: Path, capsys):
        """B4: malformed spec prints a warning to stderr but does not crash."""
        create_spec(specs_dir, "good feature")
        # Plant a corrupted spec
        bad_dir = specs_dir / "FEAT-999_bad"
        bad_dir.mkdir()
        (bad_dir / "spec.md").write_text("---\nunclosed: [bracket\n---\nbody\n")
        results = all_specs(specs_dir)
        # Good spec still loaded
        assert len(results) == 1
        # Warning went to stderr
        captured = capsys.readouterr()
        assert "FEAT-999_bad" in captured.err


# ── task_progress ────────────────────────────────────────────────────────── #


class TestTaskProgress:
    def test_no_tasks_file(self, tmp_path: Path):
        assert task_progress(tmp_path) is None

    def test_stub_template(self, tmp_path: Path):
        (tmp_path / "tasks.md").write_text("*No tasks yet. Run `/breakdown` then `/tasks`...*")
        assert task_progress(tmp_path) is None

    def test_empty_file(self, tmp_path: Path):
        (tmp_path / "tasks.md").write_text("# Tasks\n\nNo checkboxes here.")
        assert task_progress(tmp_path) is None

    def test_all_unchecked(self, tmp_path: Path):
        (tmp_path / "tasks.md").write_text("- [ ] task one\n- [ ] task two\n- [ ] task three\n")
        assert task_progress(tmp_path) == (0, 3)

    def test_some_checked_lowercase(self, tmp_path: Path):
        (tmp_path / "tasks.md").write_text("- [x] done\n- [ ] pending\n")
        assert task_progress(tmp_path) == (1, 2)

    def test_some_checked_uppercase(self, tmp_path: Path):
        (tmp_path / "tasks.md").write_text("- [X] done\n- [ ] pending\n- [X] also done\n")
        assert task_progress(tmp_path) == (2, 3)

    def test_all_checked(self, tmp_path: Path):
        (tmp_path / "tasks.md").write_text("- [x] t1\n- [x] t2\n")
        assert task_progress(tmp_path) == (2, 2)

    def test_ignores_mid_line_checkboxes(self, tmp_path: Path):
        # Only lines that START with "- [" should count
        (tmp_path / "tasks.md").write_text("Some text - [x] not a task\n- [ ] real task\n")
        assert task_progress(tmp_path) == (0, 1)


# ── rebuild_registry ─────────────────────────────────────────────────────── #


class TestRebuildRegistry:
    def test_creates_registry_file(self, specs_dir: Path):
        rebuild_registry(specs_dir)
        assert (specs_dir / "REGISTRY.md").exists()

    def test_registry_contains_features(self, specs_dir: Path):
        create_spec(specs_dir, "search feature")
        create_spec(specs_dir, "auth feature")
        rebuild_registry(specs_dir)
        content = (specs_dir / "REGISTRY.md").read_text()
        assert "FEAT-001" in content
        assert "FEAT-002" in content

    def test_registry_sorted_by_status(self, specs_dir: Path):
        # STATUS_ORDER = idea(0) < draft(1) < in-progress(2) < ... < abandoned(6)
        # So idea features appear FIRST in the registry (lifecycle start), then draft, etc.
        create_spec(specs_dir, "first")   # stays idea; side-effect only
        p2 = create_spec(specs_dir, "second")  # promoted to done (near end)
        data = load_spec(p2)
        data["status"] = "done"
        save_spec(p2, data)
        rebuild_registry(specs_dir)
        content = (specs_dir / "REGISTRY.md").read_text()
        # Extract only the Features table rows (below the column separator line)
        table_start = content.index("|---|---|---|---|---|---|---|---|")
        table_section = content[table_start:]
        # idea (FEAT-001) must appear before done (FEAT-002)
        assert table_section.index("idea") < table_section.index("done")

    def test_registry_includes_goals(self, specs_dir: Path):
        from tests.conftest import make_goal
        make_goal(specs_dir, "goal-01", "My First Goal")
        rebuild_registry(specs_dir)
        content = (specs_dir / "REGISTRY.md").read_text()
        assert "goal-01" in content
        assert "My First Goal" in content


# ── decisions in the registry (FEAT-021) ─────────────────────────────────── #


FRONTMATTER_ADR = """\
---
id: adr-001
date: 2026-05-22
status: accepted
---

# 001 — Modular chainable skills over monolithic pipeline

**Decision:** Build each workflow step as a separate skill.
"""

SKILL_TEMPLATE_ADR = """\
# 002 — Screenshots: the CLI captures, the agent describes

**Status:** Superseded  \n**Date:** 2026-08-18  \n**Context:** FEAT-006

## Decision
The CLI captures the file, the agent describes the pixels.
"""


def make_decision(specs_dir: Path, filename: str, body: str) -> Path:
    path = specs_dir / "decisions" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


class TestRegistryDecisions:
    def test_section_present_even_with_no_adrs(self, specs_dir: Path):
        rebuild_registry(specs_dir)
        content = (specs_dir / "REGISTRY.md").read_text()
        assert "## Decisions" in content

    def test_missing_decisions_dir_is_fine(self, tmp_path: Path):
        """Most projects have no ADRs at all — that is not an error."""
        bare = tmp_path / "bare-specs"
        bare.mkdir()
        rebuild_registry(bare)
        content = (bare / "REGISTRY.md").read_text()
        assert "## Decisions" in content
        assert scan_decisions(bare / "decisions") == []

    def test_frontmatter_adr_title_and_status(self, specs_dir: Path):
        make_decision(specs_dir, "001-modular-skills-over-monolith.md", FRONTMATTER_ADR)
        rebuild_registry(specs_dir)
        content = (specs_dir / "REGISTRY.md").read_text()
        assert "| 001 | Modular chainable skills over monolithic pipeline | accepted |" in content

    def test_skill_template_adr_without_frontmatter(self, specs_dir: Path):
        """`/decision` writes no frontmatter — the status lives in a bold line."""
        make_decision(specs_dir, "002-screenshot-capture.md", SKILL_TEMPLATE_ADR)
        rebuild_registry(specs_dir)
        content = (specs_dir / "REGISTRY.md").read_text()
        assert "| 002 | Screenshots: the CLI captures, the agent describes | superseded |" in content

    def test_link_resolves_to_a_real_file(self, specs_dir: Path):
        """A skill must be able to open the ADR from the link in REGISTRY.md."""
        make_decision(specs_dir, "003-lancedb-global-path.md", FRONTMATTER_ADR)
        rebuild_registry(specs_dir)
        content = (specs_dir / "REGISTRY.md").read_text()

        targets = re.findall(r"\]\((decisions/[^)]+)\)", content)
        assert targets == ["decisions/003-lancedb-global-path.md"]
        # Links are relative to REGISTRY.md, which sits at the root of specs/
        assert (specs_dir / targets[0]).is_file()

    def test_decisions_section_comes_after_features(self, specs_dir: Path):
        """Features are the primary content; a skill reads this file top to bottom."""
        make_decision(specs_dir, "001-a.md", FRONTMATTER_ADR)
        rebuild_registry(specs_dir)
        content = (specs_dir / "REGISTRY.md").read_text()
        assert content.index("## Features") < content.index("## Decisions")

    def test_no_heading_falls_back_to_filename(self, specs_dir: Path):
        make_decision(specs_dir, "004-cli-owns-ops.md", "Just a body, no heading.\n")
        rebuild_registry(specs_dir)
        content = (specs_dir / "REGISTRY.md").read_text()
        assert "| 004 | cli owns ops | — |" in content

    def test_malformed_adr_does_not_raise_and_is_marked(self, specs_dir: Path, capsys):
        """FEAT-013's failure shape: the rebuild runs after a spec is on disk.

        Raising here would leave the registry stale and the user with a
        traceback, so a broken ADR becomes a visible row instead.
        """
        create_spec(specs_dir, "good feature")
        make_decision(specs_dir, "001-good.md", FRONTMATTER_ADR)
        make_decision(specs_dir, "002-broken.md", "---\nunclosed: [bracket\nstatus: x\n---\nbody\n")
        make_decision(specs_dir, "003-later.md", FRONTMATTER_ADR.replace("001 —", "003 —"))

        rebuild_registry(specs_dir)  # must not raise

        content = (specs_dir / "REGISTRY.md").read_text()
        assert "FEAT-001" in content                     # the rest of the registry survived
        assert "| 002 | broken | unparseable |" in content
        assert "003-later.md" in content                 # ADRs after the bad one still listed
        assert "002-broken.md" in capsys.readouterr().err

    def test_unreadable_bytes_do_not_raise(self, specs_dir: Path, capsys):
        path = specs_dir / "decisions" / "005-binary.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff\xfe\x00\x00 not text at all")

        rebuild_registry(specs_dir)  # must not raise

        content = (specs_dir / "REGISTRY.md").read_text()
        assert "| 005 | binary | unparseable |" in content
        assert "005-binary.md" in capsys.readouterr().err

    def test_pipe_in_title_does_not_shift_columns(self, specs_dir: Path):
        """AC10's guarantee, extended to ADR rows."""
        make_decision(specs_dir, "006-piped.md", "# 006 — A | B decision\n")
        rebuild_registry(specs_dir)
        content = (specs_dir / "REGISTRY.md").read_text()
        row = next(ln for ln in content.splitlines() if ln.startswith("| 006 |"))
        assert row.count("|") - row.count("\\|") == 5  # 4 cells → 5 unescaped delimiters
