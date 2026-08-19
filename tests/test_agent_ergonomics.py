"""Making the CLI safe for an agent to drive in a loop (FEAT-015).

Three properties an automation loop needs and this CLI did not have: structured
output instead of box-drawing, one-line errors instead of tracebacks, and
commands that can be re-run without hard-failing.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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


def run(args: list[str], cwd: Path, env_extra: dict[str, str] | None = None):
    e = dict(os.environ)
    e["NO_COLOR"] = "1"
    if env_extra:
        e.update(env_extra)
    return subprocess.run([MERIDIAN_BIN, *args], cwd=cwd, capture_output=True, text=True, env=e)


@pytest.fixture
def proj(tmp_path: Path) -> Path:
    specs = tmp_path / "specs"
    (specs / "goals").mkdir(parents=True)
    (specs / "decisions").mkdir()
    (tmp_path / ".meridian.toml").write_text(
        '[meridian]\nproject = "ergo"\nspecs_path = "specs"\n'
        f'lancedb_path = "{tmp_path / "lancedb"}"\n'
    )
    run(["new", "a first feature", "--appetite", "s"], tmp_path)
    return tmp_path


class TestJsonOutput:
    """Skills shell out to this CLI; they should branch on data, not prose."""

    def test_status_json_is_valid_and_structured(self, proj: Path) -> None:
        r = run(["status", "--json"], proj)
        assert r.returncode == 0, r.stderr

        payload = json.loads(r.stdout)
        assert payload["project"] == "ergo"
        assert len(payload["features"]) == 1

        feature = payload["features"][0]
        assert feature["id"] == "FEAT-001"
        assert feature["status"] == "idea"
        assert feature["appetite"] == "s"
        assert "depends_on" in feature

    def test_status_json_has_no_box_drawing(self, proj: Path) -> None:
        """The point of the flag: no decoration in the agent's context."""
        r = run(["status", "--json"], proj)
        assert not set("─│┌┐└┘━┃╭╮╰╯") & set(r.stdout)

    def test_projects_json(self, proj: Path, tmp_path: Path) -> None:
        home = tmp_path / "home"
        run(["register"], proj, {"MERIDIAN_HOME": str(home)})

        r = run(["projects", "--json"], proj, {"MERIDIAN_HOME": str(home)})

        payload = json.loads(r.stdout)
        assert payload["projects"][0]["slug"] == "ergo"
        assert payload["projects"][0]["exists"] is True

    def test_status_all_json(self, proj: Path, tmp_path: Path) -> None:
        home = tmp_path / "home"
        run(["register"], proj, {"MERIDIAN_HOME": str(home)})

        r = run(["status", "--all", "--json"], proj, {"MERIDIAN_HOME": str(home)})

        payload = json.loads(r.stdout)
        entry = payload["projects"][0]
        assert entry["slug"] == "ergo"
        assert entry["counts"]["idea"] == 1

    def test_guide_json_exposes_next_action(self, proj: Path) -> None:
        r = run(["guide", "--json"], proj)
        payload = json.loads(r.stdout)

        assert payload["project"] == "ergo"
        assert payload["steps"], "guide should report its steps"
        assert {"number", "title", "status"} <= set(payload["steps"][0])
        # next_action is what an agent would act on; it may be null when all is well.
        assert "next_action" in payload

    def test_json_flag_documented_in_help(self, proj: Path) -> None:
        for command in ("status", "projects", "guide", "search"):
            r = run([command, "--help"], proj)
            assert "--json" in r.stdout, f"{command} --help does not mention --json"


class TestIdempotentLifecycle:
    """A retry after a partial failure must not hard-fail forever."""

    def test_repeating_a_transition_succeeds(self, proj: Path) -> None:
        assert run(["close", "feat-001", "--status", "draft"], proj).returncode == 0

        r = run(["close", "feat-001", "--status", "draft"], proj)

        assert r.returncode == 0
        assert "already" in r.stdout

    def test_illegal_transition_still_fails(self, proj: Path) -> None:
        """Idempotency must not turn into 'anything goes'."""
        r = run(["close", "feat-001", "--status", "in-production"], proj)
        assert r.returncode != 0
        assert "Cannot transition" in r.stdout

    def test_repeat_still_applies_extra_fields(self, proj: Path) -> None:
        """A no-op transition should still record the flags it was given."""
        run(["close", "feat-001", "--status", "draft"], proj)
        r = run(["close", "feat-001", "--status", "draft", "--confidence", "high"], proj)

        assert r.returncode == 0
        spec = next(proj.glob("specs/FEAT-001_*/spec.md")).read_text()
        assert "confidence: high" in spec

    def test_status_unchanged_after_repeat(self, proj: Path) -> None:
        run(["close", "feat-001", "--status", "draft"], proj)
        run(["close", "feat-001", "--status", "draft"], proj)

        spec = next(proj.glob("specs/FEAT-001_*/spec.md")).read_text()
        assert "status: draft" in spec


class TestErrorHandling:
    """A traceback costs an agent far more context than one clear line."""

    def test_corrupt_config_gives_one_line(self, tmp_path: Path) -> None:
        (tmp_path / ".meridian.toml").write_text("this is not { valid toml")
        (tmp_path / "specs").mkdir()

        r = run(["status"], tmp_path)

        output = r.stdout + r.stderr
        assert r.returncode != 0
        assert "Traceback" not in output
        assert "Error:" in output
        assert "not valid TOML" in output

    def test_debug_env_var_restores_the_traceback(self, tmp_path: Path) -> None:
        """The detail must still be reachable when you actually want it."""
        (tmp_path / ".meridian.toml").write_text("this is not { valid toml")
        (tmp_path / "specs").mkdir()

        r = run(["status"], tmp_path, {"MERIDIAN_DEBUG": "1"})

        assert "Traceback" in (r.stdout + r.stderr)

    def test_error_points_at_the_debug_flag(self, tmp_path: Path) -> None:
        (tmp_path / ".meridian.toml").write_text("nope {")
        (tmp_path / "specs").mkdir()

        r = run(["status"], tmp_path)
        assert "MERIDIAN_DEBUG" in (r.stdout + r.stderr)

    def test_missing_config_still_handled_by_its_own_message(self, tmp_path: Path) -> None:
        """The pre-existing friendly path must not be swallowed by the new one."""
        r = run(["status"], tmp_path)
        assert r.returncode == 1
        assert "No .meridian.toml found" in r.stdout
        assert "Traceback" not in (r.stdout + r.stderr)
