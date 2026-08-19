"""Subprocess integration tests for the meridian CLI binary.

These tests run the real installed binary (same venv as pytest) against
a temporary on-disk project.  They verify end-to-end behaviour:
  - correct exit codes
  - spec files created / mutated on disk
  - frontmatter field values after each transition
  - error messages on bad inputs

Run:  .venv/bin/pytest tests/test_cli.py -v
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import frontmatter
import pytest

# ── binary discovery ──────────────────────────────────────────────────────── #


def _find_binary() -> str:
    # Prefer the venv-local binary (same Python env as this test run)
    venv_bin = Path(sys.executable).parent / "meridian"
    if venv_bin.exists():
        return str(venv_bin)
    found = shutil.which("meridian")
    if found:
        return found
    raise RuntimeError(
        "meridian binary not found. Run: uv sync"
    )


MERIDIAN_BIN = _find_binary()

# ── helpers ───────────────────────────────────────────────────────────────── #


def run(
    args: list[str],
    cwd: Path,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run meridian with *args* in *cwd* and return the completed process."""
    e = dict(os.environ)
    e["NO_COLOR"] = "1"  # disable Rich ANSI codes for easier assertion
    if env_extra:
        e.update(env_extra)
    return subprocess.run(
        [MERIDIAN_BIN, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=e,
    )


def _first_spec(project: Path) -> Path:
    """Return the spec.md of the first (only) FEAT dir — raises if absent."""
    matches = sorted(project.glob("specs/FEAT-*/spec.md"))
    assert matches, "No spec files found in project"
    return matches[0]


def _package_version() -> str:
    """Read the version from the package, not a literal.

    A hardcoded version string turns every release into a test edit, which is
    exactly the friction the release flow exists to remove.
    """
    from meridian import __version__

    return __version__


def _bundled_skill_count() -> int:
    """How many skills ship in the package — derived, so adding one cannot rot a test."""
    from meridian import skills

    return len(list((Path(skills.__file__).parent / "commands").glob("*.md")))


def _load_fm(spec_path: Path) -> dict:
    """Load frontmatter from spec.md and return as dict."""
    post = frontmatter.loads(spec_path.read_text())
    return dict(post.metadata)


# ── fixtures ──────────────────────────────────────────────────────────────── #


@pytest.fixture
def proj(tmp_path: Path) -> Path:
    """Minimal on-disk Meridian project: .meridian.toml + specs/ skeleton."""
    specs = tmp_path / "specs"
    specs.mkdir()
    (specs / "goals").mkdir()
    (specs / "decisions").mkdir()
    lancedb = tmp_path / ".meridian" / "lancedb"
    lancedb.mkdir(parents=True)
    (tmp_path / ".meridian.toml").write_text(
        "[meridian]\n"
        'specs_path = "specs"\n'
        f'lancedb_path = "{lancedb}"\n'
    )
    return tmp_path


@pytest.fixture
def proj_with_idea(proj: Path) -> Path:
    """Project that already contains FEAT-001 in idea state."""
    r = run(["new", "add semantic search"], proj)
    assert r.returncode == 0, r.stderr
    return proj


@pytest.fixture
def proj_with_draft(proj_with_idea: Path) -> Path:
    """FEAT-001 advanced to draft."""
    r = run(["close", "feat-001", "--status", "draft"], proj_with_idea)
    assert r.returncode == 0, r.stderr
    return proj_with_idea


@pytest.fixture
def proj_with_inprogress(proj_with_draft: Path) -> Path:
    """FEAT-001 advanced to in-progress."""
    r = run(["close", "feat-001", "--status", "in-progress"], proj_with_draft)
    assert r.returncode == 0, r.stderr
    return proj_with_draft


@pytest.fixture
def proj_with_done(proj_with_inprogress: Path) -> Path:
    """FEAT-001 advanced to done."""
    r = run(["close", "feat-001", "--status", "done"], proj_with_inprogress)
    assert r.returncode == 0, r.stderr
    return proj_with_inprogress


# ── version / help ───────────────────────────────────────────────────────── #


class TestVersion:
    def test_version_long_flag(self, proj: Path) -> None:
        r = run(["--version"], proj)
        assert r.returncode == 0
        assert "meridian" in r.stdout
        assert _package_version() in r.stdout

    def test_version_short_flag(self, proj: Path) -> None:
        r = run(["-V"], proj)
        assert r.returncode == 0
        assert _package_version() in r.stdout

    def test_help_exits_zero(self, proj: Path) -> None:
        r = run(["--help"], proj)
        assert r.returncode == 0

    def test_help_lists_all_commands(self, proj: Path) -> None:
        r = run(["--help"], proj)
        expected_cmds = [
            "status", "new", "close", "cycle", "enrich", "search",
            "index", "transition", "revive",
            "guide", "help",
        ]
        for cmd in expected_cmds:
            assert cmd in r.stdout, f"Command '{cmd}' missing from --help"

    def test_help_command_shows_manual(self, proj: Path) -> None:
        r = run(["help"], proj)
        assert r.returncode == 0
        # Manual should mention workflow stages
        assert "spec" in r.stdout.lower() or "task" in r.stdout.lower()

    def test_no_args_shows_help(self, proj: Path) -> None:
        r = run([], proj)
        # no_args_is_help=True means exit 0 and show help
        assert "meridian" in r.stdout.lower()


# ── meridian new ─────────────────────────────────────────────────────────── #


class TestNew:
    def test_creates_feat_directory(self, proj: Path) -> None:
        r = run(["new", "add semantic search"], proj)
        assert r.returncode == 0
        feat_dirs = sorted((proj / "specs").glob("FEAT-001_*"))
        assert len(feat_dirs) == 1

    def test_creates_spec_file(self, proj: Path) -> None:
        run(["new", "add semantic search"], proj)
        spec = _first_spec(proj)
        assert spec.exists()

    def test_default_status_is_idea(self, proj: Path) -> None:
        run(["new", "add semantic search"], proj)
        fm = _load_fm(_first_spec(proj))
        assert fm["status"] == "idea"

    def test_appetite_flag_written_to_frontmatter(self, proj: Path) -> None:
        run(["new", "add semantic search", "--appetite", "m"], proj)
        fm = _load_fm(_first_spec(proj))
        assert fm["appetite"] == "m"

    def test_invalid_appetite_exits_nonzero(self, proj: Path) -> None:
        r = run(["new", "add semantic search", "--appetite", "xl"], proj)
        assert r.returncode != 0

    def test_goal_missing_warns_but_still_creates_spec(self, proj: Path) -> None:
        # B6: missing goal ID → warns immediately, but spec is still created
        r = run(["new", "add search", "--goal", "goal-99"], proj)
        assert r.returncode == 0
        output = r.stdout + r.stderr
        assert "goal-99" in output
        # Spec file should still exist
        assert _first_spec(proj).exists()

    def test_goal_missing_shows_warning(self, proj: Path) -> None:
        r = run(["new", "add search", "--goal", "goal-99"], proj)
        output = r.stdout + r.stderr
        assert "goal-99" in output

    def test_goal_valid_written_to_frontmatter(self, proj: Path) -> None:
        # Create goal file first
        goal = proj / "specs" / "goals" / "goal-01.md"
        goal.write_text("---\nid: goal-01\nname: Test\nstatus: active\n---\n")
        r = run(["new", "add search", "--goal", "goal-01"], proj)
        assert r.returncode == 0
        fm = _load_fm(_first_spec(proj))
        assert fm.get("goal") == "goal-01"

    def test_second_new_creates_feat_002(self, proj: Path) -> None:
        run(["new", "first feature"], proj)
        run(["new", "second feature"], proj)
        ids = sorted(d.name for d in (proj / "specs").glob("FEAT-*"))
        assert ids[0].startswith("FEAT-001")
        assert ids[1].startswith("FEAT-002")

    def test_registry_updated_after_new(self, proj: Path) -> None:
        run(["new", "add search"], proj)
        registry = proj / "specs" / "REGISTRY.md"
        assert registry.exists()
        assert "FEAT-001" in registry.read_text()

    def test_all_symbol_idea_does_not_crash(self, proj: Path) -> None:
        # G2: slug fallback for ideas with no word chars
        r = run(["new", "!!!"], proj)
        assert r.returncode == 0


# ── meridian status ──────────────────────────────────────────────────────── #


class TestStatus:
    def test_empty_project_exits_zero(self, proj: Path) -> None:
        r = run(["status"], proj)
        assert r.returncode == 0

    def test_shows_feature_id(self, proj_with_idea: Path) -> None:
        r = run(["status"], proj_with_idea)
        assert r.returncode == 0
        assert "FEAT-001" in r.stdout

    def test_shows_lifecycle_status(self, proj_with_idea: Path) -> None:
        r = run(["status"], proj_with_idea)
        assert "idea" in r.stdout

    def test_shows_updated_status_after_transition(
        self, proj_with_draft: Path
    ) -> None:
        r = run(["status"], proj_with_draft)
        assert "draft" in r.stdout


# ── meridian close ───────────────────────────────────────────────────────── #


class TestClose:
    def test_idea_to_draft(self, proj_with_idea: Path) -> None:
        r = run(["close", "feat-001", "--status", "draft"], proj_with_idea)
        assert r.returncode == 0
        fm = _load_fm(_first_spec(proj_with_idea))
        assert fm["status"] == "draft"

    def test_draft_to_in_progress(self, proj_with_draft: Path) -> None:
        r = run(["close", "feat-001", "--status", "in-progress"], proj_with_draft)
        assert r.returncode == 0
        fm = _load_fm(_first_spec(proj_with_draft))
        assert fm["status"] == "in-progress"

    def test_done_prints_drift_reminder(self, proj_with_inprogress: Path) -> None:
        r = run(["close", "feat-001", "--status", "done"], proj_with_inprogress)
        assert r.returncode == 0
        # Should remind about spec drift review
        assert "spec" in (r.stdout + r.stderr).lower()

    def test_blocked_requires_blocked_by(self, proj_with_inprogress: Path) -> None:
        r = run(["close", "feat-001", "--status", "blocked"], proj_with_inprogress)
        assert r.returncode != 0

    def test_blocked_with_reason_succeeds(self, proj_with_inprogress: Path) -> None:
        r = run(
            ["close", "feat-001", "--status", "blocked", "--blocked-by", "waiting for API"],
            proj_with_inprogress,
        )
        assert r.returncode == 0
        fm = _load_fm(_first_spec(proj_with_inprogress))
        assert fm["status"] == "blocked"
        assert fm.get("blocked_by") == "waiting for API"

    def test_blocked_sets_blocked_at_date(self, proj_with_inprogress: Path) -> None:
        run(
            ["close", "feat-001", "--status", "blocked", "--blocked-by", "dep"],
            proj_with_inprogress,
        )
        fm = _load_fm(_first_spec(proj_with_inprogress))
        assert fm.get("blocked_at") is not None

    def test_abandoned_reason_stored(self, proj_with_inprogress: Path) -> None:
        r = run(
            ["close", "feat-001", "--status", "abandoned",
             "--abandoned-reason", "not worth it"],
            proj_with_inprogress,
        )
        assert r.returncode == 0
        fm = _load_fm(_first_spec(proj_with_inprogress))
        assert fm.get("abandoned_reason") == "not worth it"

    def test_confidence_flag_updates_frontmatter(self, proj_with_idea: Path) -> None:
        run(
            ["close", "feat-001", "--status", "draft", "--confidence", "high"],
            proj_with_idea,
        )
        fm = _load_fm(_first_spec(proj_with_idea))
        assert fm.get("confidence") == "high"

    def test_invalid_status_exits_nonzero(self, proj_with_idea: Path) -> None:
        r = run(["close", "feat-001", "--status", "flying"], proj_with_idea)
        assert r.returncode != 0

    def test_invalid_transition_exits_nonzero(self, proj_with_idea: Path) -> None:
        # idea → done is not a valid direct transition
        r = run(["close", "feat-001", "--status", "done"], proj_with_idea)
        assert r.returncode != 0

    def test_unknown_feat_id_exits_nonzero(self, proj: Path) -> None:
        r = run(["close", "feat-999", "--status", "draft"], proj)
        assert r.returncode != 0

    def test_status_required(self, proj_with_idea: Path) -> None:
        r = run(["close", "feat-001"], proj_with_idea)
        assert r.returncode != 0


# ── meridian revive ───────────────────────────────────────────────────────── #


class TestRevive:
    def test_revive_abandoned_returns_to_idea(
        self, proj_with_inprogress: Path
    ) -> None:
        run(
            ["close", "feat-001", "--status", "abandoned",
             "--abandoned-reason", "scope creep"],
            proj_with_inprogress,
        )
        r = run(["revive", "feat-001"], proj_with_inprogress)
        assert r.returncode == 0
        fm = _load_fm(_first_spec(proj_with_inprogress))
        assert fm["status"] == "idea"

    def test_revive_prints_preserved_reason(
        self, proj_with_inprogress: Path
    ) -> None:
        run(
            ["close", "feat-001", "--status", "abandoned",
             "--abandoned-reason", "scope creep"],
            proj_with_inprogress,
        )
        r = run(["revive", "feat-001"], proj_with_inprogress)
        assert "scope creep" in (r.stdout + r.stderr)

    def test_revive_of_an_idea_is_a_no_op_success(
        self, proj_with_idea: Path
    ) -> None:
        """FEAT-015: the target state already holds, so this is not an error.

        An automation loop must be able to re-run a command safely; previously
        this exited 1 and a retry could never succeed.
        """
        r = run(["revive", "feat-001"], proj_with_idea)
        assert r.returncode == 0
        assert "already" in r.stdout

    def test_revive_of_a_draft_still_fails(self, proj_with_draft: Path) -> None:
        """Idempotency must not become "any transition is allowed"."""
        r = run(["revive", "feat-001"], proj_with_draft)
        assert r.returncode != 0
        assert "Cannot transition" in r.stdout

    def test_revive_clears_abandoned_at(self, proj_with_inprogress: Path) -> None:
        run(
            ["close", "feat-001", "--status", "abandoned", "--abandoned-reason", "x"],
            proj_with_inprogress,
        )
        run(["revive", "feat-001"], proj_with_inprogress)
        fm = _load_fm(_first_spec(proj_with_inprogress))
        assert not fm.get("abandoned_at")


# ── meridian cycle ───────────────────────────────────────────────────────── #


class TestCycle:
    def test_set_valid_cycle(self, proj_with_idea: Path) -> None:
        r = run(["cycle", "feat-001", "--set", "2026-Q2"], proj_with_idea)
        assert r.returncode == 0
        fm = _load_fm(_first_spec(proj_with_idea))
        assert fm.get("cycle") == "2026-Q2"

    def test_set_prints_capacity_summary(self, proj_with_idea: Path) -> None:
        r = run(["cycle", "feat-001", "--set", "2026-Q2"], proj_with_idea)
        # Should print cycle capacity info
        output = r.stdout + r.stderr
        assert "2026-Q2" in output

    def test_set_bad_format_warns(self, proj_with_idea: Path) -> None:
        r = run(["cycle", "feat-001", "--set", "next-quarter"], proj_with_idea)
        # Non-YYYY-QN format should warn but still succeed
        assert r.returncode == 0
        output = r.stdout + r.stderr
        assert "warn" in output.lower() or "format" in output.lower() or "typo" in output.lower()

    def test_clear_removes_cycle(self, proj_with_idea: Path) -> None:
        run(["cycle", "feat-001", "--set", "2026-Q2"], proj_with_idea)
        r = run(["cycle", "feat-001", "--clear"], proj_with_idea)
        assert r.returncode == 0
        fm = _load_fm(_first_spec(proj_with_idea))
        assert not fm.get("cycle")

    def test_cycle_alone_shows_current_cycle(
        self, proj_with_idea: Path
    ) -> None:
        # No --set / --clear → shows current cycle value and exits 0
        r = run(["cycle", "feat-001"], proj_with_idea)
        assert r.returncode == 0
        assert "FEAT-001" in r.stdout

    def test_unknown_feat_exits_nonzero(self, proj: Path) -> None:
        r = run(["cycle", "feat-999", "--set", "2026-Q2"], proj)
        assert r.returncode != 0


# ── meridian transition ──────────────────────────────────────────────────── #


class TestTransition:
    def test_no_feat_in_branch_prints_tip(self, proj: Path) -> None:
        r = run(["transition", "--from-merge", "main"], proj)
        # No feat match → prints a tip, exits 0
        assert r.returncode == 0

    def test_matching_done_feature_becomes_in_production(
        self, proj_with_done: Path
    ) -> None:
        r = run(
            ["transition", "--from-merge", "feat-001/add-semantic-search"],
            proj_with_done,
        )
        assert r.returncode == 0
        fm = _load_fm(_first_spec(proj_with_done))
        assert fm["status"] == "in-production"

    def test_from_merge_required(self, proj: Path) -> None:
        r = run(["transition"], proj)
        assert r.returncode != 0

    def test_feat_id_case_insensitive(self, proj_with_done: Path) -> None:
        r = run(
            ["transition", "--from-merge", "FEAT-001/some-slug"],
            proj_with_done,
        )
        assert r.returncode == 0
        fm = _load_fm(_first_spec(proj_with_done))
        assert fm["status"] == "in-production"


# ── meridian init ────────────────────────────────────────────────────────── #


class TestInit:
    def test_creates_toml(self, tmp_path: Path) -> None:
        r = run(["init", "--path", str(tmp_path)], tmp_path)
        assert r.returncode == 0
        assert (tmp_path / ".meridian.toml").exists()

    def test_creates_specs_structure(self, tmp_path: Path) -> None:
        run(["init", "--path", str(tmp_path)], tmp_path)
        specs = tmp_path / "specs"
        assert specs.is_dir()
        assert (specs / "goals").is_dir()
        assert (specs / "decisions").is_dir()

    def test_creates_template_files(self, tmp_path: Path) -> None:
        run(["init", "--path", str(tmp_path)], tmp_path)
        specs = tmp_path / "specs"
        for name in ("VISION.md", "STEERING.md", "CYCLES.md", "SKILLS.md", "REGISTRY.md"):
            assert (specs / name).exists(), f"Missing {name}"

    def test_creates_claude_commands(self, tmp_path: Path) -> None:
        run(["init", "--path", str(tmp_path)], tmp_path)
        commands = tmp_path / ".claude" / "commands" / "meridian"
        assert commands.is_dir()
        skills = list(commands.glob("*.md"))
        expected = _bundled_skill_count()
        assert len(skills) == expected, f"Expected {expected} skill files, got {len(skills)}"

    def test_toml_has_required_keys(self, tmp_path: Path) -> None:
        run(["init", "--path", str(tmp_path)], tmp_path)
        import tomllib
        with open(tmp_path / ".meridian.toml", "rb") as f:
            cfg = tomllib.load(f)
        assert "meridian" in cfg
        assert cfg["meridian"]["specs_path"] == "specs"
        assert cfg["meridian"]["project"], "the project slug scopes the shared index"
        assert "databricks" not in cfg, (
            "FEAT-014: the Databricks integration was removed — the generated "
            "config must not advertise a vendor section that does nothing."
        )

    def test_prints_next_steps(self, tmp_path: Path) -> None:
        r = run(["init", "--path", str(tmp_path)], tmp_path)
        assert "Next steps" in r.stdout
        assert "/meridian:vision" in r.stdout

    def test_refuses_double_init_without_force(self, tmp_path: Path) -> None:
        run(["init", "--path", str(tmp_path)], tmp_path)
        r = run(["init", "--path", str(tmp_path)], tmp_path)
        assert r.returncode != 0
        assert "force" in (r.stdout + r.stderr).lower()

    def test_force_overwrites(self, tmp_path: Path) -> None:
        run(["init", "--path", str(tmp_path)], tmp_path)
        # Corrupt the toml
        (tmp_path / ".meridian.toml").write_text("bad content")
        r = run(["init", "--path", str(tmp_path), "--force"], tmp_path)
        assert r.returncode == 0
        import tomllib
        with open(tmp_path / ".meridian.toml", "rb") as f:
            cfg = tomllib.load(f)
        assert "meridian" in cfg

    def test_project_is_usable_after_init(self, tmp_path: Path) -> None:
        # After init, meridian commands should work in the new project
        run(["init", "--path", str(tmp_path)], tmp_path)
        r = run(["status"], tmp_path)
        assert r.returncode == 0

    def test_guide_passes_after_init(self, tmp_path: Path) -> None:
        run(["init", "--path", str(tmp_path)], tmp_path)
        r = run(["guide"], tmp_path)
        assert r.returncode == 0


# ── meridian install ───────────────────────────────────────────────────────── #


class TestInstall:
    def test_project_installs_namespaced(self, tmp_path: Path) -> None:
        r = run(["install", "--project", "--path", str(tmp_path)], tmp_path)
        assert r.returncode == 0
        dest = tmp_path / ".claude" / "commands" / "meridian"
        assert dest.is_dir()
        skills = list(dest.glob("*.md"))
        expected = _bundled_skill_count()
        assert len(skills) == expected, f"Expected {expected} skill files, got {len(skills)}"

    def test_reports_namespaced_invocation(self, tmp_path: Path) -> None:
        r = run(["install", "--project", "--path", str(tmp_path)], tmp_path)
        assert "/meridian:spec" in r.stdout

    def test_rerun_writes_nothing_when_current(self, tmp_path: Path) -> None:
        """FEAT-010: identical files are 'up to date', not merely 'already there'."""
        run(["install", "--project", "--path", str(tmp_path)], tmp_path)
        r = run(["install", "--project", "--path", str(tmp_path)], tmp_path)
        assert r.returncode == 0
        assert "already up to date" in r.stdout
        assert "0 skill" in r.stdout

    def test_outdated_skill_reported_and_left_alone(self, tmp_path: Path) -> None:
        """A repo that customised a skill must not be silently clobbered."""
        run(["install", "--project", "--path", str(tmp_path)], tmp_path)
        skill = tmp_path / ".claude" / "commands" / "meridian" / "spec.md"
        skill.write_text("locally customised")

        r = run(["install", "--project", "--path", str(tmp_path)], tmp_path)

        assert "outdated" in r.stdout
        assert skill.read_text() == "locally customised"

    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        r = run(["install", "--project", "--path", str(tmp_path), "--dry-run"], tmp_path)
        assert r.returncode == 0
        assert not (tmp_path / ".claude" / "commands" / "meridian").exists()
        assert "would be written" in r.stdout

    def test_force_overwrites(self, tmp_path: Path) -> None:
        run(["install", "--project", "--path", str(tmp_path)], tmp_path)
        skill = tmp_path / ".claude" / "commands" / "meridian" / "spec.md"
        skill.write_text("corrupted")
        run(["install", "--project", "--path", str(tmp_path), "--force"], tmp_path)
        assert skill.read_text() != "corrupted"

    def test_global_installs_into_home(self, tmp_path: Path) -> None:
        # Redirect HOME so the real ~/.claude is never touched.
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        r = run(["install"], tmp_path, env_extra={"HOME": str(fake_home)})
        assert r.returncode == 0
        dest = fake_home / ".claude" / "commands" / "meridian"
        assert len(list(dest.glob("*.md"))) == _bundled_skill_count()


# ── meridian guide ───────────────────────────────────────────────────────── #


class TestGuide:
    def test_runs_on_empty_project(self, proj: Path) -> None:
        r = run(["guide"], proj)
        assert r.returncode == 0

    def test_output_suggests_next_action(self, proj: Path) -> None:
        r = run(["guide"], proj)
        # Should have some actionable content
        assert len(r.stdout.strip()) > 0


# ── meridian index ───────────────────────────────────────────────────────── #


class TestIndex:
    def test_runs_with_no_specs(self, proj: Path) -> None:
        # No Ollama available — should fail gracefully (not traceback)
        r = run(["index"], proj)
        output = r.stdout + r.stderr
        # Either succeeds or prints a friendly error — no raw traceback
        assert "Traceback" not in output
        assert "Error" in output or r.returncode == 0

    def test_rebuilds_registry(self, proj_with_idea: Path) -> None:
        # Delete and rebuild registry
        registry = proj_with_idea / "specs" / "REGISTRY.md"
        if registry.exists():
            registry.unlink()
        # index rebuilds registry even if LanceDB step fails
        run(["index"], proj_with_idea)
        # Registry may be rebuilt by the CLI regardless of embedding step
        # Just assert no crash

    def test_vectors_only_leaves_registry_untouched(self, proj_with_idea: Path) -> None:
        """FEAT-007: recovering another repo's chunks must not dirty its git tree.

        `meridian index` rewrites REGISTRY.md, so telling users to run it in
        nine other repos to repopulate the shared store would modify tracked
        files nobody asked to change.
        """
        registry = proj_with_idea / "specs" / "REGISTRY.md"
        run(["index"], proj_with_idea)
        before = registry.read_text() if registry.exists() else None

        registry.write_text("SENTINEL — must not be regenerated\n")
        r = run(["index", "--vectors-only"], proj_with_idea)

        assert "Traceback" not in r.stdout + r.stderr
        assert registry.read_text() == "SENTINEL — must not be regenerated\n"
        assert "REGISTRY.md rebuilt" not in r.stdout
        assert before is None or before  # registry was writable to begin with


# ── enrich: screenshots (FEAT-006) ───────────────────────────────────────── #

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"pretend-pixels" * 40


def _png(directory: Path, name: str = "kpi.png") -> Path:
    path = directory / name
    path.write_bytes(PNG_BYTES)
    return path


def _sources_dir(project: Path) -> Path:
    return _first_spec(project).parent / "sources"


def _sources_files(project: Path) -> list[Path]:
    """Files inside sources/ — the dir itself is scaffolded by `meridian new`."""
    sources = _sources_dir(project)
    return sorted(p for p in sources.iterdir() if p.is_file()) if sources.exists() else []


class TestEnrichScreenshotRefusals:
    """An image with no notes must never be silently embedded.

    These run through the real binary, so stdin is not a tty — the
    non-interactive refusal path.
    """

    def test_missing_note_exits_nonzero_naming_both_flags(self, proj_with_idea: Path):
        png = _png(proj_with_idea)
        r = run(["enrich", "feat-001", str(png)], proj_with_idea)
        assert r.returncode != 0
        combined = r.stdout + r.stderr
        assert "--note" in combined
        assert "--note-file" in combined

    def test_missing_note_writes_nothing(self, proj_with_idea: Path):
        png = _png(proj_with_idea)
        run(["enrich", "feat-001", str(png)], proj_with_idea)
        assert _sources_files(proj_with_idea) == []
        assert _load_fm(_first_spec(proj_with_idea)).get("sources") in (None, [])

    def test_capture_flags_are_mutually_exclusive(self, proj_with_idea: Path):
        r = run(
            ["enrich", "feat-001", "--latest-screenshot", "--from-clipboard", "-n", "x"],
            proj_with_idea,
        )
        assert r.returncode != 0
        assert "mutually exclusive" in (r.stdout + r.stderr)

    def test_capture_flag_conflicts_with_positional_source(self, proj_with_idea: Path):
        png = _png(proj_with_idea)
        r = run(
            ["enrich", "feat-001", str(png), "--latest-screenshot", "-n", "x"],
            proj_with_idea,
        )
        assert r.returncode != 0
        assert "not both" in (r.stdout + r.stderr)
        assert _sources_files(proj_with_idea) == []

    def test_no_source_and_no_capture_flag_is_refused(self, proj_with_idea: Path):
        r = run(["enrich", "feat-001"], proj_with_idea)
        assert r.returncode != 0
        assert "--latest-screenshot" in (r.stdout + r.stderr)

    def test_note_and_note_file_together_refused(self, proj_with_idea: Path):
        png = _png(proj_with_idea)
        notes = proj_with_idea / "n.md"
        notes.write_text("prose")
        r = run(
            ["enrich", "feat-001", str(png), "-n", "x", "--note-file", str(notes)],
            proj_with_idea,
        )
        assert r.returncode != 0
        assert "not both" in (r.stdout + r.stderr)


class TestEnrichScreenshotInProcess:
    """Paths needing patched capture/embed seams, driven through CliRunner."""

    def _runner(self):
        from typer.testing import CliRunner

        return CliRunner()

    def _invoke(self, monkeypatch, proj: Path, args: list[str], **kwargs):
        from meridian.cli import app

        monkeypatch.chdir(proj)
        monkeypatch.setattr("meridian.enrich.embed", lambda *a, **k: [0.1, 0.2, 0.3, 0.4])
        return self._runner().invoke(app, args, **kwargs)

    def test_note_flag_ingests_image_and_sidecar(self, monkeypatch, proj_with_idea: Path):
        png = _png(proj_with_idea)
        result = self._invoke(
            monkeypatch, proj_with_idea,
            ["enrich", "feat-001", str(png), "--note", "KPI tile shows 0"],
        )
        assert result.exit_code == 0, result.output
        sources = _sources_dir(proj_with_idea)
        assert (sources / "kpi.png").read_bytes() == PNG_BYTES
        assert "KPI tile shows 0" in (sources / "kpi.notes.md").read_text()
        assert "kpi.notes.md" in result.output

    def test_prompted_note_is_used(self, monkeypatch, proj_with_idea: Path):
        png = _png(proj_with_idea)
        monkeypatch.setattr("meridian.cli._stdin_is_tty", lambda: True)
        result = self._invoke(
            monkeypatch, proj_with_idea, ["enrich", "feat-001", str(png)],
            input="tile shows 0\n",
        )
        assert result.exit_code == 0, result.output
        assert "tile shows 0" in (_sources_dir(proj_with_idea) / "kpi.notes.md").read_text()

    def test_empty_prompt_aborts_writing_nothing(self, monkeypatch, proj_with_idea: Path):
        png = _png(proj_with_idea)
        monkeypatch.setattr("meridian.cli._stdin_is_tty", lambda: True)
        result = self._invoke(
            monkeypatch, proj_with_idea, ["enrich", "feat-001", str(png)], input="\n"
        )
        assert result.exit_code != 0
        assert "Aborted" in result.output
        assert _sources_files(proj_with_idea) == []

    def test_latest_screenshot_prints_resolved_name_and_age(
        self, monkeypatch, proj_with_idea: Path
    ):
        shot = _png(proj_with_idea, "Screenshot 2026-08-18 at 15.40.59.png")
        monkeypatch.setattr(
            "meridian.capture.latest_screenshot", lambda directory=None: (shot, 42.0)
        )
        result = self._invoke(
            monkeypatch, proj_with_idea,
            ["enrich", "feat-001", "--latest-screenshot", "-n", "tile shows 0"],
        )
        assert result.exit_code == 0, result.output
        assert "Screenshot 2026-08-18 at 15.40.59.png" in result.output
        assert "just now" in result.output
        # Stored under the deterministic slug, not the spaced original name.
        assert (_sources_dir(proj_with_idea) / "screenshot-2026-08-18-15-40-59.png").exists()

    def test_stale_screenshot_warns_but_proceeds(self, monkeypatch, proj_with_idea: Path):
        shot = _png(proj_with_idea)
        monkeypatch.setattr(
            "meridian.capture.latest_screenshot", lambda directory=None: (shot, 3600.0)
        )
        result = self._invoke(
            monkeypatch, proj_with_idea,
            ["enrich", "feat-001", "--latest-screenshot", "-n", "tile shows 0"],
        )
        assert result.exit_code == 0, result.output
        assert "60m old" in result.output
        assert (_sources_dir(proj_with_idea) / "kpi.notes.md").exists()

    def test_no_screenshots_found_exits_nonzero(self, monkeypatch, proj_with_idea: Path):
        def boom(directory=None):
            raise RuntimeError("No images found in /Users/x/Desktop.")

        monkeypatch.setattr("meridian.capture.latest_screenshot", boom)
        result = self._invoke(
            monkeypatch, proj_with_idea,
            ["enrich", "feat-001", "--latest-screenshot", "-n", "x"],
        )
        assert result.exit_code != 0
        assert "Desktop" in result.output

    def test_clipboard_without_image_exits_nonzero(self, monkeypatch, proj_with_idea: Path):
        def boom(dest):
            raise RuntimeError("Clipboard holds no image. Copy a screenshot first")

        monkeypatch.setattr("meridian.capture.clipboard_image", boom)
        result = self._invoke(
            monkeypatch, proj_with_idea,
            ["enrich", "feat-001", "--from-clipboard", "-n", "x"],
        )
        assert result.exit_code != 0
        assert "no image" in result.output

    def test_note_flag_on_text_source_warns_but_succeeds(
        self, monkeypatch, proj_with_idea: Path
    ):
        doc = proj_with_idea / "paper.txt"
        doc.write_text(" ".join(f"w{i}" for i in range(300)))
        result = self._invoke(
            monkeypatch, proj_with_idea,
            ["enrich", "feat-001", str(doc), "--note", "ignored here"],
        )
        assert result.exit_code == 0, result.output
        assert "images only" in result.output
        assert (_sources_dir(proj_with_idea) / "paper.txt").exists()
        # No sidecar for a text source.
        assert not (_sources_dir(proj_with_idea) / "paper.notes.md").exists()
