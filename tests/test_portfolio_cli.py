"""End-to-end CLI tests for `meridian next` and the portfolio columns (FEAT-026).

Every test runs the real binary against throwaway repos with `MERIDIAN_HOME`
pointed at a temp directory, so `meridian register` here can never reach the
developer's real `~/.meridian/projects.toml`.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
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
    """A throwaway MERIDIAN_HOME. Never the developer's real ~/.meridian."""
    return tmp_path / "meridian-home"


def run(args: list[str], cwd: Path, home: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["NO_COLOR"] = "1"
    env["MERIDIAN_HOME"] = str(home)
    # Wide enough that Rich does not wrap a sentence mid-assertion.
    env["COLUMNS"] = "200"
    return subprocess.run(
        [MERIDIAN_BIN, *args], cwd=cwd, capture_output=True, text=True, env=env
    )


def make_repo(root: Path, slug: str, features: list[dict] | None = None) -> Path:
    """A Meridian repo on disk. Each feature dict is frontmatter plus:

    ``age_days`` — how far back to set spec/tasks mtimes,
    ``tasks``    — ``(checked, total)`` checkbox counts for tasks.md,
    ``raw``      — literal spec.md text, for malformed-spec cases.
    """
    repo = root / slug
    (repo / "specs").mkdir(parents=True, exist_ok=True)
    (repo / ".meridian.toml").write_text(
        f'[meridian]\nproject = "{slug}"\nspecs_path = "specs"\n'
        f'lancedb_path = "{root / "lancedb"}"\n'
    )
    for i, spec in enumerate(features or [], start=1):
        spec = dict(spec)
        age = spec.pop("age_days", 0)
        tasks = spec.pop("tasks", None)
        raw = spec.pop("raw", None)
        feat_dir = repo / "specs" / f"FEAT-{i:03d}_demo"
        feat_dir.mkdir(parents=True, exist_ok=True)

        spec_file = feat_dir / "spec.md"
        if raw is not None:
            spec_file.write_text(raw)
        else:
            meta = {
                "id": f"feat-{i:03d}",
                "name": spec.pop("name", f"Demo {i}"),
                "status": spec.pop("status", "idea"),
                "goal": "'~'",
                **spec,
            }
            body = "\n".join(f"{k}: {v}" for k, v in meta.items() if v is not None)
            spec_file.write_text(f"---\n{body}\n---\nBody.\n")

        touched = [spec_file]
        if tasks:
            checked, total = tasks
            tasks_file = feat_dir / "tasks.md"
            tasks_file.write_text(
                "\n".join(
                    f"- [{'x' if n <= checked else ' '}] task {n}"
                    for n in range(1, total + 1)
                ) + "\n"
            )
            touched.append(tasks_file)

        stamp = time.time() - age * 86400
        for path in touched:
            os.utime(path, (stamp, stamp))
    return repo


def days_ago(n: int) -> str:
    from datetime import date, timedelta

    return (date.today() - timedelta(days=n)).isoformat()


# --------------------------------------------------------------------------- #
# meridian next
# --------------------------------------------------------------------------- #

class TestNext:
    def test_ranks_across_projects_from_outside_any_repo(
        self, tmp_path: Path, home: Path
    ) -> None:
        """AC1 — no repo checked out, no repo current."""
        a = make_repo(tmp_path, "alpha", [
            {"status": "in-progress", "tasks": (11, 12)},
        ])
        b = make_repo(tmp_path, "beta", [
            {"status": "blocked", "blocked_at": days_ago(31), "blocked_by": "waiting on infra"},
        ])
        run(["register"], a, home)
        run(["register"], b, home)
        scratch = tmp_path / "not-a-repo"
        scratch.mkdir()

        r = run(["next"], scratch, home)

        assert r.returncode == 0, r.stderr
        assert "alpha" in r.stdout and "beta" in r.stdout
        # AC3 — blocked longest ranks above nearly-done work.
        assert r.stdout.index("beta") < r.stdout.index("alpha")

    def test_every_row_says_why(self, tmp_path: Path, home: Path) -> None:
        """AC2 — an opaque score would be worse than the tally it replaces."""
        a = make_repo(tmp_path, "alpha", [
            {"status": "blocked", "blocked_at": days_ago(31), "blocked_by": "waiting on infra"},
            {"status": "in-progress", "tasks": (11, 12)},
            {"status": "in-progress", "age_days": 47},
        ])
        run(["register"], a, home)

        r = run(["next"], a, home)

        assert "blocked 31 days" in r.stdout
        assert "waiting on infra" in r.stdout
        assert "11 of 12 tasks done" in r.stdout
        assert "nothing changed in 47 days" in r.stdout

    def test_help_states_the_ordering_rule(self, tmp_path: Path, home: Path) -> None:
        """AC3 — the rule lives in --help, not only in the code."""
        from meridian.portfolio import ORDERING_RULE

        r = run(["next", "--help"], tmp_path, home)

        flattened = " ".join(r.stdout.split())
        assert ORDERING_RULE in flattened

    def test_limit_reports_what_it_dropped(self, tmp_path: Path, home: Path) -> None:
        """AC4 — a silent truncation reads as 'that is everything'."""
        a = make_repo(tmp_path, "alpha", [{"status": "idea"} for _ in range(5)])
        run(["register"], a, home)

        r = run(["next", "--limit", "2"], a, home)

        assert "3 more not shown" in r.stdout
        assert "showing 2 of 5" in r.stdout

    def test_no_limit_shows_everything_without_a_dropped_note(
        self, tmp_path: Path, home: Path
    ) -> None:
        a = make_repo(tmp_path, "alpha", [{"status": "idea"} for _ in range(3)])
        run(["register"], a, home)

        r = run(["next"], a, home)

        assert "more not shown" not in r.stdout

    def test_project_narrows_to_one_repo(self, tmp_path: Path, home: Path) -> None:
        """AC5 — the same ranking, scoped to a single repo."""
        a = make_repo(tmp_path, "alpha", [{"status": "draft", "name": "Alpha thing"}])
        b = make_repo(tmp_path, "beta", [{"status": "draft", "name": "Beta thing"}])
        run(["register"], a, home)
        run(["register"], b, home)

        r = run(["next", "--project", "alpha"], tmp_path, home)

        assert "Alpha thing" in r.stdout
        assert "Beta thing" not in r.stdout

    def test_unknown_project_names_the_tracked_ones(self, tmp_path: Path, home: Path) -> None:
        a = make_repo(tmp_path, "alpha", [{"status": "draft"}])
        run(["register"], a, home)

        r = run(["next", "--project", "nope"], tmp_path, home)

        assert r.returncode == 1
        assert "No tracked project named" in r.stdout
        assert "alpha" in r.stdout

    def test_json_carries_the_reason_and_the_raw_signals(
        self, tmp_path: Path, home: Path
    ) -> None:
        """AC6 — a skill must be able to re-rank without re-deriving anything."""
        a = make_repo(tmp_path, "alpha", [
            {"status": "in-progress", "tasks": (11, 12), "appetite": "m",
             "cycle": "2026-Q3", "age_days": 3},
        ])
        run(["register"], a, home)

        r = run(["next", "--json"], a, home)

        payload = json.loads(r.stdout)
        row = payload["features"][0]
        assert row["project"] == "alpha" and row["id"] == "FEAT-001"
        assert row["reason"] == "11 of 12 tasks done"
        assert row["signals"] == {
            "blocked_days": None, "blocked_by": None,
            "tasks_checked": 11, "tasks_total": 12, "tasks_remaining": 1,
            "days_since_change": 3, "stale": False,
        }
        assert row["appetite"] == "m" and row["cycle"] == "2026-Q3"
        assert payload["ordering"] and payload["staleness_note"]

    def test_json_honours_limit_and_reports_the_drop(self, tmp_path: Path, home: Path) -> None:
        a = make_repo(tmp_path, "alpha", [{"status": "idea"} for _ in range(4)])
        run(["register"], a, home)

        payload = json.loads(run(["next", "--limit", "1", "--json"], a, home).stdout)

        assert payload["shown"] == 1 and payload["dropped"] == 3 and payload["total"] == 4

    def test_json_has_no_box_drawing(self, tmp_path: Path, home: Path) -> None:
        a = make_repo(tmp_path, "alpha", [{"status": "draft"}])
        run(["register"], a, home)

        r = run(["next", "--json"], a, home)

        assert not set("─│┌┐└┘━┃╭╮╰╯") & set(r.stdout)

    def test_finished_work_never_ranks(self, tmp_path: Path, home: Path) -> None:
        a = make_repo(tmp_path, "alpha", [
            {"status": "done", "name": "Shipped thing"},
            {"status": "in-production", "name": "Live thing"},
            {"status": "abandoned", "name": "Killed thing"},
        ])
        run(["register"], a, home)

        r = run(["next"], a, home)

        assert "Nothing actionable" in r.stdout
        assert "Shipped thing" not in r.stdout

    def test_empty_registry_message(self, tmp_path: Path, home: Path) -> None:
        scratch = tmp_path / "not-a-repo"
        scratch.mkdir()

        r = run(["next"], scratch, home)

        assert r.returncode == 0
        assert "No projects tracked" in r.stdout


# --------------------------------------------------------------------------- #
# staleness and capacity on `status --all`
# --------------------------------------------------------------------------- #

class TestStatusAllStaleness:
    def test_days_since_change_column(self, tmp_path: Path, home: Path) -> None:
        """AC7 — derived from spec and task file mtimes."""
        a = make_repo(tmp_path, "alpha", [{"status": "draft", "age_days": 47}])
        run(["register"], a, home)

        r = run(["status", "--all"], a, home)

        assert "chg" in r.stdout
        assert "47d" in r.stdout

    def test_stale_projects_are_marked(self) -> None:
        """AC8 — marked the way blocked counts already are."""
        from meridian.cli import _stale_cell
        from meridian.portfolio import STALE_DAYS

        assert "bold red" in _stale_cell(STALE_DAYS)
        assert "bold red" not in _stale_cell(STALE_DAYS - 1)
        assert _stale_cell(None) == "[dim]·[/dim]"

    def test_output_states_the_limits_of_mtime(self, tmp_path: Path, home: Path) -> None:
        """AC9 — a signal whose limits are hidden gets trusted too far."""
        a = make_repo(tmp_path, "alpha", [{"status": "draft"}])
        run(["register"], a, home)

        r = run(["status", "--all"], a, home)

        flattened = " ".join(r.stdout.split())
        assert "mtimes" in flattened
        assert "fresh clone" in flattened

    def test_json_exposes_staleness_and_its_note(self, tmp_path: Path, home: Path) -> None:
        a = make_repo(tmp_path, "alpha", [{"status": "draft", "age_days": 40}])
        run(["register"], a, home)

        payload = json.loads(run(["status", "--all", "--json"], a, home).stdout)

        project = payload["projects"][0]
        assert project["days_since_change"] == 40
        assert project["stale"] is True
        assert payload["staleness_note"]
        # FEAT-009's shape is preserved — existing consumers keep working.
        assert project["counts"] == {"draft": 1}


class TestStatusAllCapacity:
    def test_committed_appetite_per_project_and_total(
        self, tmp_path: Path, home: Path
    ) -> None:
        """AC10 — per project, plus a portfolio total."""
        a = make_repo(tmp_path, "alpha", [
            {"status": "in-progress", "appetite": "m", "cycle": "2026-Q3"},
            {"status": "draft", "appetite": "s", "cycle": "2026-Q3"},
        ])
        run(["register"], a, home)

        r = run(["status", "--all"], a, home)

        assert "Cycle capacity" in r.stdout
        assert "2 committed" in r.stdout
        assert "1×m" in r.stdout and "1×s" in r.stdout
        assert "Portfolio:" in r.stdout

    def test_large_bets_are_summed_across_projects(self, tmp_path: Path, home: Path) -> None:
        """AC11 — two large bets in each of three repos is six, and invisible per repo."""
        for slug in ("alpha", "beta", "gamma"):
            repo = make_repo(tmp_path, slug, [
                {"status": "in-progress", "appetite": "l", "cycle": "2026-Q3"},
                {"status": "draft", "appetite": "l", "cycle": "2026-Q3"},
            ])
            run(["register"], repo, home)

        r = run(["status", "--all"], tmp_path, home)

        flattened = " ".join(r.stdout.split())
        assert "6 large bets committed across 3 projects" in flattened
        assert "at most 2 at a time" in flattened

    def test_two_large_bets_in_one_project_is_not_a_warning(
        self, tmp_path: Path, home: Path
    ) -> None:
        repo = make_repo(tmp_path, "alpha", [
            {"status": "in-progress", "appetite": "l", "cycle": "2026-Q3"},
            {"status": "draft", "appetite": "l", "cycle": "2026-Q3"},
        ])
        run(["register"], repo, home)

        r = run(["status", "--all"], tmp_path, home)

        assert "Shape Up suggests" not in r.stdout

    def test_uncommitted_is_distinct_from_zero(self, tmp_path: Path, home: Path) -> None:
        """AC12 — active work nobody has bet on is not the same as no work."""
        a = make_repo(tmp_path, "alpha", [
            {"status": "in-progress", "appetite": "m"},          # no cycle
            {"status": "draft", "appetite": "s", "cycle": "2026-Q3"},
        ])
        run(["register"], a, home)

        r = run(["status", "--all"], a, home)
        payload = json.loads(run(["status", "--all", "--json"], a, home).stdout)

        assert "1 uncommitted" in r.stdout
        assert payload["projects"][0]["capacity"]["uncommitted"] == 1
        assert payload["portfolio"]["uncommitted"] == 1


# --------------------------------------------------------------------------- #
# robustness
# --------------------------------------------------------------------------- #

class TestRobustness:
    def test_missing_repo_is_reported_and_skipped(self, tmp_path: Path, home: Path) -> None:
        """AC13 — reported, never deleted: it may just be on another disk."""
        alive = make_repo(tmp_path, "alpha", [{"status": "draft"}])
        doomed = make_repo(tmp_path, "gone", [{"status": "draft"}])
        run(["register"], alive, home)
        run(["register"], doomed, home)
        shutil.rmtree(doomed)

        r = run(["next"], tmp_path, home)

        assert r.returncode == 0
        assert "gone" in r.stdout and "skipped" in r.stdout
        assert "alpha" in r.stdout
        # The registry still tracks it.
        assert "gone" in (home / "projects.toml").read_text()

    def test_malformed_spec_does_not_stop_the_ranking(
        self, tmp_path: Path, home: Path
    ) -> None:
        """AC14 — reported, and the remaining projects still rank."""
        broken = make_repo(tmp_path, "broken", [
            {"raw": "---\nstatus: [unclosed\n---\nbody\n"},
            {"status": "draft", "name": "Still readable"},
        ])
        healthy = make_repo(tmp_path, "healthy", [{"status": "draft", "name": "Fine here"}])
        run(["register"], broken, home)
        run(["register"], healthy, home)

        r = run(["next"], tmp_path, home)

        assert r.returncode == 0
        assert "Still readable" in r.stdout and "Fine here" in r.stdout
        assert "could not be parsed" in r.stdout
        assert "could not load" in r.stderr

    def test_ten_projects_of_sixty_features_stays_responsive(
        self, tmp_path: Path, home: Path
    ) -> None:
        """AC15 — the end-to-end command, not just the ranking function."""
        for i in range(10):
            repo = make_repo(tmp_path, f"p{i:02d}", [
                {"status": "in-progress", "tasks": (n % 5, 5), "age_days": n}
                for n in range(60)
            ])
            run(["register"], repo, home)

        started = time.perf_counter()
        r = run(["next", "--limit", "10"], tmp_path, home)
        elapsed = time.perf_counter() - started

        assert r.returncode == 0, r.stderr
        assert "590 more not shown" in r.stdout
        # Includes interpreter start-up; the bar is "no perceptible pause".
        assert elapsed < 10.0, f"`meridian next` over 600 features took {elapsed:.1f}s"
