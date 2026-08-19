"""Packaging invariants (FEAT-012).

These guard the release flow's assumptions. Breaking one of them does not fail
any other test — it fails a release, quietly, later.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def pyproject() -> dict:
    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)


class TestVersionSingleSource:
    def test_version_is_static_in_pyproject(self, pyproject: dict) -> None:
        """`uv version` refuses to operate on a dynamic version.

        This was learned the hard way: resolving the version from
        meridian/__init__.py made `uv version --bump` fail outright.
        """
        assert "version" in pyproject["project"]
        assert "version" not in pyproject["project"].get("dynamic", [])

    def test_package_version_matches_pyproject(self, pyproject: dict) -> None:
        from meridian import __version__

        assert __version__ == pyproject["project"]["version"], (
            "meridian.__version__ disagrees with pyproject.toml — the package is "
            "probably installed from a different source tree than this checkout"
        )

    def test_version_module_holds_no_release_literal(self) -> None:
        """The version must not be hardcoded in two places again.

        The `0.0.0+dev` sentinel is allowed — it is the source-tree fallback for
        when the package was never installed, not a second source of truth.
        """
        import re

        source = (REPO_ROOT / "meridian" / "__init__.py").read_text()
        assert "importlib.metadata" in source

        literals = set(re.findall(r'__version__\s*=\s*"([^"]+)"', source))
        assert literals <= {"0.0.0+dev"}, (
            f"real version literal(s) in meridian/__init__.py: {literals - {'0.0.0+dev'}}"
        )


class TestDependencyGroups:
    def test_dev_tooling_is_a_dependency_group(self, pyproject: dict) -> None:
        """Dev tools belong in [dependency-groups], not in the installable extras."""
        groups = pyproject.get("dependency-groups", {})
        assert "dev" in groups
        assert "dev" not in pyproject["project"].get("optional-dependencies", {})

    def test_rerank_stays_a_real_extra(self, pyproject: dict) -> None:
        """`meridian[rerank]` is a user-facing install option, not dev tooling."""
        extras = pyproject["project"].get("optional-dependencies", {})
        assert "rerank" in extras

    def test_dev_group_covers_the_release_gate(self, pyproject: dict) -> None:
        names = " ".join(pyproject["dependency-groups"]["dev"])
        for tool in ("pytest", "ruff", "mypy"):
            assert tool in names, f"{tool} missing — scripts/release.sh runs it"


class TestLockfile:
    def test_lockfile_is_tracked(self) -> None:
        assert (REPO_ROOT / "uv.lock").exists(), (
            "uv.lock must be committed — the release gate runs `uv run --locked`"
        )

    def test_release_script_uses_the_locked_environment(self) -> None:
        """A gate that runs on an ambient interpreter is not a gate.

        CI cannot run on this repo, so scripts/release.sh is the only
        verification there is; it must not test against whatever Python
        happens to be first on PATH.
        """
        script = (REPO_ROOT / "scripts" / "release.sh").read_text()
        assert "uv run --locked python -m pytest" in script
        assert "uv lock --check" in script


class TestSurfaceStaysCut:
    """FEAT-014 removed vendor coupling and four low-value skills.

    These guard the deletions: each is the kind of thing that creeps back in
    without anyone deciding to bring it back.
    """

    def test_databricks_module_is_gone(self) -> None:
        assert not (REPO_ROOT / "meridian" / "databricks.py").exists()

    def test_no_databricks_references_in_source(self) -> None:
        import re

        offenders = []
        for path in (REPO_ROOT / "meridian").rglob("*.py"):
            if re.search(r"databricks", path.read_text(), re.IGNORECASE):
                offenders.append(path.name)
        assert not offenders, f"Databricks references remain in: {offenders}"

    def test_deleted_skills_stay_deleted(self) -> None:
        bundled = REPO_ROOT / "meridian" / "skills" / "commands"
        dogfood = REPO_ROOT / ".claude" / "commands" / "meridian"
        for name in ("plan.md", "challenge.md", "roadmap.md", "connect-dots.md"):
            assert not (bundled / name).exists(), f"{name} came back in the package"
            assert not (dogfood / name).exists(), f"{name} came back in .claude"

    def test_help_is_generated_not_hand_written(self) -> None:
        """The 309-line manual drifted — link-job/unlink-job were undiscoverable.

        Deriving the listing from `app.registered_commands` makes that
        impossible, so assert the derivation rather than the output.
        """
        source = (REPO_ROOT / "meridian" / "cli.py").read_text()
        assert "app.registered_commands" in source
