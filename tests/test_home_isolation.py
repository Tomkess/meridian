"""Guard: the test suite must never write to the developer's real ~/.meridian.

This exists because it happened. `meridian init` registers the repo it creates,
the subprocess CLI tests run the real binary, and for one afternoon every test
run appended pytest tmp directories to the real global registry.
"""
import os
from pathlib import Path

from meridian.home import meridian_home


def test_meridian_home_is_isolated() -> None:
    """The session fixture must be in force for every test that runs."""
    assert "MERIDIAN_HOME" in os.environ, "session isolation fixture is not active"
    assert meridian_home() != Path("~/.meridian").expanduser()


def test_real_home_not_referenced_by_resolved_paths() -> None:
    from meridian.home import registry_file

    real = Path("~/.meridian").expanduser()
    assert real not in registry_file().parents
    assert registry_file() != real / "projects.toml"


def test_init_registration_lands_in_isolated_home(tmp_path: Path) -> None:
    """The specific regression: `init` writing into the real registry."""
    from meridian.registry import all_projects, register

    repo = tmp_path / "some-repo"
    repo.mkdir()
    register("some-repo", repo, "purpose")

    entries = all_projects()
    slugs = [e.slug for e in entries]
    assert "some-repo" in slugs

    # Other tests share this session-scoped home, so the registry legitimately
    # holds their entries too. What must never appear is a path outside the
    # pytest temp tree — that would mean a real repo got registered.
    real_home = Path("~").expanduser()
    for entry in entries:
        assert "pytest" in str(entry.path) or str(entry.path).startswith("/tmp"), (
            f"{entry.slug} → {entry.path} is outside the pytest temp tree; "
            "isolation has broken and real projects are being registered"
        )
        assert entry.path != real_home
