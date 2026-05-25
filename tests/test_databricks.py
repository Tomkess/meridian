"""Tests for meridian/databricks.py — state normalisation, aggregation, display."""
import pytest

from meridian.databricks import (
    _STATE_PRIORITY,
    _aggregate_states,
    _normalise_task_state,
    run_state_display,
    task_run_display,
)

# ── _normalise_task_state ─────────────────────────────────────────────────── #


class TestNormaliseTaskState:
    @pytest.mark.parametrize(
        "life, result, expected",
        [
            # Active states → RUNNING
            ("RUNNING", "", "RUNNING"),
            ("TERMINATING", "", "RUNNING"),
            # Waiting / dependency states → PENDING (V1 fix)
            ("PENDING", "", "PENDING"),
            ("BLOCKED", "", "PENDING"),  # V1: BLOCKED is NOT running
            # Terminal states → result_state takes over
            ("TERMINATED", "SUCCESS", "SUCCESS"),
            ("TERMINATED", "FAILED", "FAILED"),
            ("TERMINATED", "TIMEDOUT", "TIMEDOUT"),
            ("TERMINATED", "CANCELED", "CANCELED"),
            # Edge: TERMINATED with no result_state falls back to life
            ("SKIPPED", "", "SKIPPED"),
        ],
    )
    def test_normalise(self, life: str, result: str, expected: str):
        assert _normalise_task_state(life, result) == expected

    def test_blocked_is_not_running(self):
        """V1 regression: BLOCKED tasks must never show as 🔄 running."""
        state = _normalise_task_state("BLOCKED", "")
        assert state != "RUNNING"
        assert state == "PENDING"


# ── _aggregate_states ─────────────────────────────────────────────────────── #


class TestAggregateStates:
    def test_empty_returns_unknown(self):
        assert _aggregate_states([]) == "UNKNOWN"

    def test_single_running(self):
        assert _aggregate_states(["RUNNING"]) == "RUNNING"

    def test_running_beats_success(self):
        assert _aggregate_states(["SUCCESS", "RUNNING", "SUCCESS"]) == "RUNNING"

    def test_failed_beats_success(self):
        assert _aggregate_states(["SUCCESS", "FAILED"]) == "FAILED"

    def test_failed_beats_canceled(self):
        assert _aggregate_states(["CANCELED", "FAILED"]) == "FAILED"

    def test_timedout_same_priority_as_failed(self):
        assert _STATE_PRIORITY["TIMEDOUT"] == _STATE_PRIORITY["FAILED"]

    def test_running_beats_failed(self):
        assert _aggregate_states(["FAILED", "RUNNING"]) == "RUNNING"

    def test_all_success(self):
        assert _aggregate_states(["SUCCESS", "SUCCESS", "SUCCESS"]) == "SUCCESS"

    def test_unknown_state_has_lowest_priority(self):
        result = _aggregate_states(["SOME_CUSTOM_STATE", "SUCCESS"])
        assert result == "SUCCESS"

    def test_priority_full_order(self):
        # RUNNING > FAILED = TIMEDOUT > CANCELED > SUCCESS > PENDING
        states = ["PENDING", "SUCCESS", "CANCELED", "FAILED", "RUNNING"]
        assert _aggregate_states(states) == "RUNNING"

        states_no_running = ["PENDING", "SUCCESS", "CANCELED", "FAILED"]
        assert _aggregate_states(states_no_running) == "FAILED"

        states_only_lower = ["PENDING", "SUCCESS", "CANCELED"]
        assert _aggregate_states(states_only_lower) == "CANCELED"


# ── run_state_display ─────────────────────────────────────────────────────── #


class TestRunStateDisplay:
    def test_none_returns_empty_marker(self):
        assert "∅" in run_state_display(None)

    def test_success_green(self):
        result = run_state_display("SUCCESS")
        assert "✅" in result
        assert "green" in result

    def test_failed_red(self):
        result = run_state_display("FAILED")
        assert "❌" in result
        assert "red" in result

    def test_timedout_yellow(self):
        result = run_state_display("TIMEDOUT")
        assert "⏱" in result

    def test_running_cyan(self):
        result = run_state_display("RUNNING")
        assert "🔄" in result
        assert "cyan" in result

    def test_pending_dim(self):
        result = run_state_display("PENDING")
        assert "⏳" in result

    def test_canceled_dim(self):
        result = run_state_display("CANCELED")
        assert "✗" in result

    def test_unknown_state_shows_state_text(self):
        result = run_state_display("SOME_UNKNOWN")
        assert "SOME_UNKNOWN" in result

    def test_case_insensitive(self):
        assert run_state_display("success") == run_state_display("SUCCESS")


# ── task_run_display ──────────────────────────────────────────────────────── #


class TestTaskRunDisplay:
    def test_empty_states_shows_empty_marker(self):
        result = task_run_display({}, ["task1", "task2"])
        assert "∅" in result

    def test_all_none_states(self):
        result = task_run_display({"task1": None, "task2": None}, ["task1", "task2"])
        assert "∅" in result

    def test_all_success_green(self):
        states = {"t1": "SUCCESS", "t2": "SUCCESS", "t3": "SUCCESS"}
        result = task_run_display(states, ["t1", "t2", "t3"])
        assert "✅" in result
        assert "3/3" in result
        assert "green" in result

    def test_partial_success_yellow(self):
        # Some tasks not found (None) → partial
        states = {"t1": "SUCCESS", "t2": None}
        result = task_run_display(states, ["t1", "t2"])
        assert "✅" in result
        assert "yellow" in result

    def test_any_failed_shows_count(self):
        states = {"t1": "SUCCESS", "t2": "FAILED", "t3": "SUCCESS"}
        result = task_run_display(states, ["t1", "t2", "t3"])
        assert "❌" in result
        assert "1/3" in result

    def test_running_takes_priority(self):
        states = {"t1": "RUNNING", "t2": "SUCCESS"}
        result = task_run_display(states, ["t1", "t2"])
        assert "🔄" in result

    def test_canceled(self):
        states = {"t1": "CANCELED"}
        result = task_run_display(states, ["t1"])
        assert "canceled" in result.lower() or "✗" in result
