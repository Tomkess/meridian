"""Global project registry (FEAT-008)."""
from pathlib import Path

import pytest

from meridian.home import registry_file
from meridian.registry import (
    RegistryUnreadableError,
    all_projects,
    derive_purpose,
    find_project,
    register,
)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "meridian-home"
    monkeypatch.setenv("MERIDIAN_HOME", str(home))
    return home


class TestRegister:
    def test_creates_entry(self, tmp_path: Path) -> None:
        repo = tmp_path / "my-repo"
        repo.mkdir()
        register("my-repo", repo, "A test repo")

        entries = all_projects()
        assert len(entries) == 1
        assert entries[0].slug == "my-repo"
        assert entries[0].purpose == "A test repo"
        assert entries[0].exists

    def test_reregister_updates_in_place(self, tmp_path: Path) -> None:
        """AC7: re-running init must not append a duplicate."""
        repo = tmp_path / "my-repo"
        repo.mkdir()
        register("my-repo", repo, "First purpose")
        register("my-repo", repo, "Second purpose")

        entries = all_projects()
        assert len(entries) == 1
        assert entries[0].purpose == "Second purpose"

    def test_multiple_projects_sorted(self, tmp_path: Path) -> None:
        for name in ("zeta", "alpha", "mid"):
            d = tmp_path / name
            d.mkdir()
            register(name, d)
        assert [e.slug for e in all_projects()] == ["alpha", "mid", "zeta"]

    def test_paths_with_spaces_round_trip(self, tmp_path: Path) -> None:
        """`~/Local Inferences/Misc` is a real registered project."""
        repo = tmp_path / "Local Inferences" / "Misc"
        repo.mkdir(parents=True)
        register("misc", repo, "Odds and ends")

        entry = find_project("misc")
        assert entry is not None
        assert entry.path == repo.resolve()
        assert entry.exists


class TestStaleEntries:
    def test_missing_path_flagged_not_dropped(self, tmp_path: Path) -> None:
        """AC8: a repo may just be on another disk."""
        repo = tmp_path / "gone"
        repo.mkdir()
        register("gone", repo)
        repo.rmdir()

        entries = all_projects()
        assert len(entries) == 1
        assert entries[0].exists is False


class TestDegradation:
    def test_missing_registry_is_empty_list(self) -> None:
        assert all_projects() == []

    def test_malformed_toml_raises_instead_of_reporting_empty(self) -> None:
        """FEAT-013: 'unreadable' must never be mistaken for 'empty'.

        It was: all_projects() swallowed the parse error and returned [], and
        the next write rewrote the file from that empty list — one stray byte
        permanently deleted every registered project.
        """
        path = registry_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[[project]\nslug = broken")

        with pytest.raises(RegistryUnreadableError):
            all_projects()

    def test_corrupt_registry_is_not_overwritten_by_register(self, tmp_path: Path) -> None:
        """The destructive path: corrupt file, then register wipes it."""
        path = registry_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        corrupt = "garbage [[[ not toml\n"
        path.write_text(corrupt)

        repo = tmp_path / "some-repo"
        repo.mkdir()
        with pytest.raises(RegistryUnreadableError):
            register("some-repo", repo)

        assert path.read_text() == corrupt, "a corrupt registry must be left intact"


class TestSerialisation:
    def test_newline_in_purpose_survives_round_trip(self, tmp_path: Path) -> None:
        """FEAT-013: one newline used to make the file permanently unparseable."""
        repo = tmp_path / "repo-a"
        repo.mkdir()
        register("repo-a", repo, "line one\nline two")

        entries = all_projects()
        assert len(entries) == 1
        assert entries[0].purpose == "line one\nline two"

    def test_quotes_and_backslashes_round_trip(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo-b"
        repo.mkdir()
        tricky = 'has "quotes", a \\ backslash, and a \ttab'
        register("repo-b", repo, tricky)
        assert all_projects()[0].purpose == tricky

    def test_second_project_survives_a_tricky_first(self, tmp_path: Path) -> None:
        """The actual damage: a bad value took every *other* project with it."""
        a, b = tmp_path / "aaa", tmp_path / "bbb"
        a.mkdir()
        b.mkdir()
        register("aaa", a, "ordinary purpose")
        register("bbb", b, "nasty\npurpose")

        assert {e.slug for e in all_projects()} == {"aaa", "bbb"}

    def test_backup_written_before_overwrite(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo-c"
        repo.mkdir()
        register("repo-c", repo, "first")
        register("repo-c", repo, "second")

        backup = registry_file().with_suffix(registry_file().suffix + ".bak")
        assert backup.exists(), "the previous registry should be recoverable"
        assert "first" in backup.read_text()

    def test_no_temp_file_left_behind(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo-d"
        repo.mkdir()
        register("repo-d", repo)
        strays = [p.name for p in registry_file().parent.iterdir() if p.name.endswith(".tmp")]
        assert strays == []

    def test_entry_without_slug_or_path_skipped(self) -> None:
        path = registry_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '[[project]]\nslug = ""\npath = "/tmp"\n\n'
            '[[project]]\nslug = "ok"\npath = "/tmp"\n'
        )
        assert [e.slug for e in all_projects()] == ["ok"]

    def test_find_project_missing(self) -> None:
        assert find_project("nope") is None


class TestDerivePurpose:
    def test_prefers_prose_over_generic_heading(self, tmp_path: Path) -> None:
        """Every VISION.md starts '# Vision' — worthless as a routing signal."""
        specs = tmp_path / "specs"
        specs.mkdir()
        (specs / "VISION.md").write_text(
            "# Vision\n\nNavigate your codebase with purpose.\n"
        )
        assert derive_purpose(specs, "fallback") == "Navigate your codebase with purpose."

    def test_distinctive_heading_used_when_no_prose(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        (specs / "VISION.md").write_text("# Ship betting models faster\n")
        assert derive_purpose(specs, "fallback") == "Ship betting models faster"

    def test_frontmatter_skipped(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        (specs / "VISION.md").write_text(
            "---\ntitle: Vision\nstatus: draft\n---\n\n# Vision\n\nReal purpose here.\n"
        )
        assert derive_purpose(specs, "fallback") == "Real purpose here."

    def test_bullets_and_quotes_skipped(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        (specs / "VISION.md").write_text(
            "# Vision\n\n> a pull quote\n\n- a bullet\n\nThe actual statement.\n"
        )
        assert derive_purpose(specs, "fallback") == "The actual statement."

    def test_falls_back_without_vision(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        assert derive_purpose(specs, "my-repo") == "my-repo"

    def test_empty_vision_falls_back(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        specs.mkdir()
        (specs / "VISION.md").write_text("\n\n")
        assert derive_purpose(specs, "my-repo") == "my-repo"
