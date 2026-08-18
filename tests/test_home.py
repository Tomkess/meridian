"""Global Meridian home resolution (FEAT-009)."""
import subprocess
import sys
from pathlib import Path

from meridian.home import meridian_home, registry_file


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

    def test_registry_file_path_not_created(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("MERIDIAN_HOME", str(tmp_path / "home"))
        path = registry_file()
        assert path.name == "projects.toml"
        assert not path.exists()


class TestRepoIndependence:
    def test_imports_without_a_meridian_toml(self, tmp_path: Path) -> None:
        """The registry must be readable from a directory that is not a repo.

        Run in a subprocess from a directory with no .meridian.toml up the tree,
        so an accidental `load_config()` import would fail loudly here rather
        than in a user's home directory.
        """
        workdir = tmp_path / "not-a-repo"
        workdir.mkdir()
        result = subprocess.run(
            [sys.executable, "-c",
             "from meridian.home import registry_file; print(registry_file())"],
            cwd=workdir,
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin", "MERIDIAN_HOME": str(tmp_path / "home"),
                 "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        )
        assert result.returncode == 0, result.stderr
        assert "projects.toml" in result.stdout
