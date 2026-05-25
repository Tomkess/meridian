"""Tests for meridian/guide.py — each project check, stale-blocked, first_action."""
from datetime import date, timedelta
from pathlib import Path

from meridian.config import MeridianConfig
from meridian.guide import (
    StepResult,
    _check_cycles,
    _check_elaboration,
    _check_features,
    _check_goals,
    _check_research,
    _check_steering,
    _check_tasks,
    _check_vision,
    _stale_blocked_days,
    first_action,
    run_guide,
)
from meridian.specs import create_spec, load_spec, save_spec
from tests.conftest import make_goal

# ── _check_vision ─────────────────────────────────────────────────────────── #


class TestCheckVision:
    def test_no_file_is_error(self, mock_cfg: MeridianConfig):
        result = _check_vision(mock_cfg.specs_path)
        assert result.status == "error"

    def test_empty_file_is_warn(self, mock_cfg: MeridianConfig):
        (mock_cfg.specs_path / "VISION.md").write_text("")
        assert _check_vision(mock_cfg.specs_path).status == "warn"

    def test_sparse_file_is_warn(self, mock_cfg: MeridianConfig):
        (mock_cfg.specs_path / "VISION.md").write_text("Short vision.")
        assert _check_vision(mock_cfg.specs_path).status == "warn"

    def test_good_vision_is_ok(self, mock_cfg: MeridianConfig):
        body = "We are building the world's best spec-first AI development workflow. " * 2
        (mock_cfg.specs_path / "VISION.md").write_text(body)
        assert _check_vision(mock_cfg.specs_path).status == "ok"

    def test_vision_with_frontmatter_uses_body(self, mock_cfg: MeridianConfig):
        # VISION.md may have YAML frontmatter; body must be evaluated, not raw file
        content = "---\ntitle: Vision\n---\n" + ("Long body content here. " * 5)
        (mock_cfg.specs_path / "VISION.md").write_text(content)
        assert _check_vision(mock_cfg.specs_path).status == "ok"


# ── _check_steering ───────────────────────────────────────────────────────── #


class TestCheckSteering:
    def test_no_file_is_warn(self, mock_cfg: MeridianConfig):
        result = _check_steering(mock_cfg.specs_path)
        assert result.status == "warn"

    def test_unfilled_template_is_warn(self, mock_cfg: MeridianConfig):
        # Three+ HTML comments signals an unfilled template
        content = "<!-- c1 -->\n<!-- c2 -->\n<!-- c3 -->\nShort."
        (mock_cfg.specs_path / "STEERING.md").write_text(content)
        assert _check_steering(mock_cfg.specs_path).status == "warn"

    def test_good_content_is_ok(self, mock_cfg: MeridianConfig):
        content = "## Coding Standards\n" + "Use Python 3.11, strict typing. " * 15
        (mock_cfg.specs_path / "STEERING.md").write_text(content)
        assert _check_steering(mock_cfg.specs_path).status == "ok"


# ── _check_goals ─────────────────────────────────────────────────────────── #


class TestCheckGoals:
    def test_no_goals_is_error(self, mock_cfg: MeridianConfig):
        result, goals = _check_goals(mock_cfg.specs_path)
        assert result.status == "error"
        assert goals == []

    def test_one_goal_is_ok(self, mock_cfg: MeridianConfig):
        make_goal(mock_cfg.specs_path, "goal-01", "Reliability")
        result, goals = _check_goals(mock_cfg.specs_path)
        assert result.status == "ok"
        assert len(goals) == 1
        assert goals[0]["id"] == "goal-01"

    def test_multiple_goals(self, mock_cfg: MeridianConfig):
        make_goal(mock_cfg.specs_path, "goal-01")
        make_goal(mock_cfg.specs_path, "goal-02", "Performance")
        _, goals = _check_goals(mock_cfg.specs_path)
        assert len(goals) == 2


# ── _check_features ──────────────────────────────────────────────────────── #


class TestCheckFeatures:
    def test_no_features_is_error(self, mock_cfg: MeridianConfig):
        result, _ = _check_features(mock_cfg.specs_path, [])
        assert result.status == "error"

    def test_feature_without_goal_is_warn(self, mock_cfg: MeridianConfig):
        create_spec(mock_cfg.specs_path, "orphan feature")
        goals = [{"id": "goal-01", "name": "G", "status": "active"}]
        result, _ = _check_features(mock_cfg.specs_path, goals)
        assert result.status == "warn"
        assert "without a goal" in result.detail

    def test_feature_with_unknown_goal_is_warn(self, mock_cfg: MeridianConfig):
        create_spec(mock_cfg.specs_path, "feature", goal="goal-99")
        goals = [{"id": "goal-01", "name": "G", "status": "active"}]
        result, _ = _check_features(mock_cfg.specs_path, goals)
        assert result.status == "warn"

    def test_all_linked_correctly_is_ok(self, mock_cfg: MeridianConfig):
        make_goal(mock_cfg.specs_path, "goal-01")
        create_spec(mock_cfg.specs_path, "feature", goal="goal-01")
        goals = [{"id": "goal-01", "name": "G", "status": "active"}]
        result, _ = _check_features(mock_cfg.specs_path, goals)
        assert result.status == "ok"


# ── _check_elaboration ───────────────────────────────────────────────────── #


class TestCheckElaboration:
    def _make_spec_with_status(
        self,
        specs_dir: Path,
        name: str,
        status: str,
        appetite: str | None = None,
        confidence: str | None = None,
    ) -> Path:
        path = create_spec(specs_dir, name)
        data = load_spec(path)
        data["status"] = status
        data["appetite"] = appetite
        data["confidence"] = confidence
        save_spec(path, data)
        return path

    def test_no_specs_is_error(self):
        assert _check_elaboration([]).status == "error"

    def test_all_ideas_is_warn(self, mock_cfg: MeridianConfig):
        self._make_spec_with_status(mock_cfg.specs_path, "idea one", "idea")
        specs = [load_spec(p) for p in mock_cfg.specs_path.glob("FEAT-*/spec.md")]
        result = _check_elaboration(specs)
        assert result.status == "warn"

    def test_active_missing_appetite_is_warn(self, mock_cfg: MeridianConfig):
        self._make_spec_with_status(mock_cfg.specs_path, "f1", "in-progress", appetite=None)
        specs = [load_spec(p) for p in mock_cfg.specs_path.glob("FEAT-*/spec.md")]
        result = _check_elaboration(specs)
        assert result.status == "warn"
        assert "appetite" in result.detail

    def test_active_missing_confidence_is_warn(self, mock_cfg: MeridianConfig):
        self._make_spec_with_status(
            mock_cfg.specs_path, "f1", "in-progress", appetite="m", confidence=None
        )
        specs = [load_spec(p) for p in mock_cfg.specs_path.glob("FEAT-*/spec.md")]
        result = _check_elaboration(specs)
        assert result.status == "warn"
        assert "confidence" in result.detail

    def test_all_good_is_ok(self, mock_cfg: MeridianConfig):
        self._make_spec_with_status(
            mock_cfg.specs_path, "f1", "in-progress", appetite="m", confidence="high"
        )
        specs = [load_spec(p) for p in mock_cfg.specs_path.glob("FEAT-*/spec.md")]
        result = _check_elaboration(specs)
        assert result.status == "ok"


# ── _check_research ──────────────────────────────────────────────────────── #


class TestCheckResearch:
    def test_no_specs_is_error(self, mock_cfg: MeridianConfig):
        assert _check_research(mock_cfg.specs_path, []).status == "error"

    def test_no_sources_is_warn(self, mock_cfg: MeridianConfig):
        create_spec(mock_cfg.specs_path, "unsourced feature")
        specs = [load_spec(p) for p in mock_cfg.specs_path.glob("FEAT-*/spec.md")]
        result = _check_research(mock_cfg.specs_path, specs)
        assert result.status == "warn"

    def test_with_sources_is_ok(self, mock_cfg: MeridianConfig):
        path = create_spec(mock_cfg.specs_path, "researched feature")
        data = load_spec(path)
        data["sources"] = ["sources/report.txt"]
        save_spec(path, data)
        specs = [load_spec(p) for p in mock_cfg.specs_path.glob("FEAT-*/spec.md")]
        result = _check_research(mock_cfg.specs_path, specs)
        assert result.status == "ok"


# ── _check_cycles ─────────────────────────────────────────────────────────── #


class TestCheckCycles:
    def test_no_active_features_is_ok(self):
        specs = [{"id": "feat-001", "status": "idea", "cycle": None}]
        assert _check_cycles(specs).status == "ok"

    def test_active_without_cycle_is_warn(self):
        specs = [{"id": "feat-001", "status": "in-progress", "cycle": None}]
        result = _check_cycles(specs)
        assert result.status == "warn"
        assert "not assigned" in result.detail

    def test_all_active_in_cycle_is_ok(self):
        specs = [{"id": "feat-001", "status": "in-progress", "cycle": "2026-Q2"}]
        assert _check_cycles(specs).status == "ok"

    def test_stale_blocked_over_threshold_is_warn(self):
        old = (date.today() - timedelta(days=20)).isoformat()
        specs = [
            {
                "id": "feat-001",
                "status": "blocked",
                "cycle": "2026-Q2",
                "blocked_at": old,
                "blocked_by": "external team",
            }
        ]
        result = _check_cycles(specs)
        assert result.status == "warn"
        assert "20d" in result.detail

    def test_blocked_under_threshold_not_flagged(self):
        recent = (date.today() - timedelta(days=5)).isoformat()
        specs = [
            {
                "id": "feat-001",
                "status": "blocked",
                "cycle": "2026-Q2",
                "blocked_at": recent,
                "blocked_by": "infra",
            }
        ]
        result = _check_cycles(specs)
        assert result.status == "ok"


# ── _stale_blocked_days ───────────────────────────────────────────────────── #


class TestStalBlockedDays:
    def test_no_blocked_at_returns_none(self):
        assert _stale_blocked_days({"blocked_at": None}) is None

    def test_today_is_zero_days(self):
        today = date.today().isoformat()
        assert _stale_blocked_days({"blocked_at": today}) == 0

    def test_fourteen_days_ago(self):
        past = (date.today() - timedelta(days=14)).isoformat()
        assert _stale_blocked_days({"blocked_at": past}) == 14

    def test_invalid_date_returns_none(self):
        assert _stale_blocked_days({"blocked_at": "not-a-date"}) is None


# ── _check_tasks ─────────────────────────────────────────────────────────── #


class TestCheckTasks:
    def test_no_in_progress_is_ok(self, mock_cfg: MeridianConfig):
        specs = [{"status": "draft"}]
        result = _check_tasks(mock_cfg.specs_path, specs)
        assert result.status == "ok"

    def test_in_progress_no_tasks_file_is_warn(self, mock_cfg: MeridianConfig):
        path = create_spec(mock_cfg.specs_path, "wip feature")
        data = load_spec(path)
        data["status"] = "in-progress"
        save_spec(path, data)
        specs = [load_spec(p) for p in mock_cfg.specs_path.glob("FEAT-*/spec.md")]
        result = _check_tasks(mock_cfg.specs_path, specs)
        # tasks.md is created by create_spec as a stub — stub is detected as no-tasks
        assert result.status == "warn"

    def test_in_progress_with_real_tasks_is_ok(self, mock_cfg: MeridianConfig):
        path = create_spec(mock_cfg.specs_path, "wip feature")
        data = load_spec(path)
        data["status"] = "in-progress"
        save_spec(path, data)
        # Write a real tasks.md with enough content
        tasks_content = (
            "## Tasks\n\n"
            "- [ ] 1. Set up the module\n"
            "       Pre: none\n"
            "- [ ] 2. Implement core logic\n"
            "       Pre: task 1 complete\n"
            "- [ ] 3. Write tests\n"
            "       Pre: task 2 complete\n"
        )
        (path.parent / "tasks.md").write_text(tasks_content)
        specs = [load_spec(p) for p in mock_cfg.specs_path.glob("FEAT-*/spec.md")]
        result = _check_tasks(mock_cfg.specs_path, specs)
        assert result.status == "ok"

    def test_all_tasks_done_but_still_in_progress_is_warn(self, mock_cfg: MeridianConfig):
        path = create_spec(mock_cfg.specs_path, "nearly done feature")
        data = load_spec(path)
        data["status"] = "in-progress"
        save_spec(path, data)
        # _check_tasks requires len(content) >= 100 to treat as real tasks.md
        tasks_content = (
            "## Tasks — FEAT-001: nearly done feature\n\n"
            "- [x] 1. Set up the module structure and initialisation files\n"
            "       Pre: none\n"
            "       AC: #1\n"
            "- [x] 2. Implement the core algorithm and wire up the CLI command\n"
            "       Pre: task 1 complete\n"
            "       AC: #2\n"
        )
        assert len(tasks_content) >= 100  # guard: this test requires content > threshold
        (path.parent / "tasks.md").write_text(tasks_content)
        specs = [load_spec(p) for p in mock_cfg.specs_path.glob("FEAT-*/spec.md")]
        result = _check_tasks(mock_cfg.specs_path, specs)
        assert result.status == "warn"
        # Message mentions all-done and recommends closing
        assert "tasks checked" in result.detail.lower() or "done" in result.next_action.lower()


# ── first_action ──────────────────────────────────────────────────────────── #


class TestFirstAction:
    def test_all_ok_returns_none(self):
        steps = [StepResult(i, "Step", "sub", "ok", "detail", None) for i in range(8)]
        assert first_action(steps) is None

    def test_returns_first_non_ok_action(self):
        steps = [
            StepResult(1, "S", "s", "ok", "d", None),
            StepResult(2, "S", "s", "warn", "missing", "Fix this"),
            StepResult(3, "S", "s", "error", "also missing", "Fix that"),
        ]
        assert first_action(steps) == "Fix this"

    def test_warn_returned_before_later_error(self):
        steps = [
            StepResult(1, "S", "s", "warn", "w", "Fix warning"),
            StepResult(2, "S", "s", "error", "e", "Fix error"),
        ]
        assert first_action(steps) == "Fix warning"

    def test_step_without_next_action_is_skipped(self):
        steps = [
            StepResult(1, "S", "s", "warn", "w", None),  # no action
            StepResult(2, "S", "s", "error", "e", "Fix error"),
        ]
        assert first_action(steps) == "Fix error"


# ── run_guide integration ────────────────────────────────────────────────── #


class TestRunGuide:
    def test_returns_eight_steps(self, mock_cfg: MeridianConfig):
        steps = run_guide(mock_cfg)
        assert len(steps) == 8

    def test_step_numbers_are_sequential(self, mock_cfg: MeridianConfig):
        steps = run_guide(mock_cfg)
        assert [s.number for s in steps] == list(range(1, 9))

    def test_all_statuses_are_valid(self, mock_cfg: MeridianConfig):
        steps = run_guide(mock_cfg)
        for step in steps:
            assert step.status in ("ok", "warn", "error")

    def test_empty_project_has_errors(self, mock_cfg: MeridianConfig):
        steps = run_guide(mock_cfg)
        statuses = {s.status for s in steps}
        assert "error" in statuses or "warn" in statuses
