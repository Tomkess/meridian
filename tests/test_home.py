"""Global Meridian home resolution (FEAT-008)."""
import subprocess
import sys
from pathlib import Path

from meridian.home import (
    icebox_dir,
    inbox_dir,
    meridian_home,
    processed_dir,
    registry_file,
)


class TestMeridianHome:
    def test_env_override_respected(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("MERIDIAN_HOME", str(tmp_path / "custom"))
        assert meridian_home() == tmp_path / "custom"

    def test_defaults_to_dot_meridian(self, monkeypatch) -> None:
        monkeypatch.delenv("MERIDIAN_HOME", raising=False)
        assert meridian_home() == Path("~/.meridian").expanduser()

    def test_blank_env_falls_back_to_default(self, monkeypatch) -> None:
        monkeypatch.setenv("MERIDIAN_HOME", "")
        assert meridian_home() == Path("~/.meridian").expanduser()

    def test_expands_user_in_override(self, monkeypatch) -> None:
        monkeypatch.setenv("MERIDIAN_HOME", "~/somewhere-else")
        assert meridian_home() == Path("~/somewhere-else").expanduser()


class TestDirectories:
    def test_created_on_demand(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("MERIDIAN_HOME", str(tmp_path / "home"))
        assert inbox_dir().is_dir()
        assert processed_dir().is_dir()
        assert icebox_dir().is_dir()

    def test_archive_dirs_live_inside_inbox(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("MERIDIAN_HOME", str(tmp_path / "home"))
        assert processed_dir().parent == inbox_dir()
        assert icebox_dir().parent == inbox_dir()

    def test_create_false_does_not_mkdir(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("MERIDIAN_HOME", str(tmp_path / "home"))
        assert not inbox_dir(create=False).exists()

    def test_registry_file_path_not_created(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("MERIDIAN_HOME", str(tmp_path / "home"))
        path = registry_file()
        assert path.name == "projects.toml"
        assert not path.exists()


class TestSearchContext:
    """Triage must rank captures from any directory, not just inside a repo."""

    def test_falls_back_to_defaults_outside_any_repo(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from meridian.home import DEFAULT_EMBED_MODEL, search_context

        monkeypatch.setenv("MERIDIAN_HOME", str(tmp_path / "home"))
        monkeypatch.chdir(tmp_path)
        # No .meridian.toml and no registered projects.
        path, model = search_context()

        assert model == DEFAULT_EMBED_MODEL
        assert path.name == "lancedb"

    def test_reads_a_registered_projects_config(self, tmp_path: Path, monkeypatch) -> None:
        from meridian.home import search_context
        from meridian.registry import register

        monkeypatch.setenv("MERIDIAN_HOME", str(tmp_path / "home"))
        repo = tmp_path / "some-repo"
        repo.mkdir()
        (repo / ".meridian.toml").write_text(
            '[meridian]\nlancedb_path = "/custom/store"\nollama_model = "custom-model"\n'
        )
        register("some-repo", repo)
        monkeypatch.chdir(tmp_path)

        path, model = search_context()

        assert model == "custom-model"
        assert path == Path("/custom/store")

    def test_prefers_current_repo_over_registry(self, tmp_path: Path, monkeypatch) -> None:
        from meridian.home import search_context
        from meridian.registry import register

        monkeypatch.setenv("MERIDIAN_HOME", str(tmp_path / "home"))
        other = tmp_path / "other-repo"
        other.mkdir()
        (other / ".meridian.toml").write_text('[meridian]\nollama_model = "other-model"\n')
        register("other-repo", other)

        here = tmp_path / "here"
        here.mkdir()
        (here / ".meridian.toml").write_text('[meridian]\nollama_model = "here-model"\n')
        monkeypatch.chdir(here)

        _, model = search_context()
        assert model == "here-model"


class TestRepoIndependence:
    def test_imports_without_a_meridian_toml(self, tmp_path: Path) -> None:
        """The whole point of this module: capture works outside any repo.

        Run in a subprocess from a directory with no .meridian.toml up the
        tree, so an accidental `load_config()` import would fail loudly here
        rather than in a user's home directory.
        """
        workdir = tmp_path / "not-a-repo"
        workdir.mkdir()
        result = subprocess.run(
            [sys.executable, "-c",
             "from meridian.home import inbox_dir; print(inbox_dir(create=False))"],
            cwd=workdir,
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin", "MERIDIAN_HOME": str(tmp_path / "home"),
                 "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        )
        assert result.returncode == 0, result.stderr
        assert "inbox" in result.stdout
