"""Config loading and project-slug derivation (FEAT-007)."""
from pathlib import Path

import pytest

from meridian.config import UNKNOWN_PROJECT, load_config, slugify_project


def _write_toml(root: Path, body: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".meridian.toml").write_text(body)
    return root


class TestSlugifyProject:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("meridian", "meridian"),
            ("Meridian", "meridian"),
            ("gd_projects", "gd-projects"),
            ("My Repo v2", "my-repo-v2"),
            ("  spaced  ", "spaced"),
            ("dots.and.dashes-", "dots-and-dashes"),
            ("__weird__", "weird"),
        ],
    )
    def test_slugs(self, raw: str, expected: str) -> None:
        assert slugify_project(raw) == expected

    def test_empty_slug_falls_back(self) -> None:
        """A name that slugifies to nothing must not brick the CLI."""
        assert slugify_project("___") == UNKNOWN_PROJECT
        assert slugify_project("") == UNKNOWN_PROJECT

    def test_deterministic(self) -> None:
        assert slugify_project("Some Repo") == slugify_project("Some Repo")


class TestLoadConfigProject:
    def test_defaults_to_root_directory_name(self, tmp_path: Path) -> None:
        root = _write_toml(tmp_path / "My Project", '[meridian]\nspecs_path = "specs"\n')
        cfg = load_config(root)
        assert cfg.project == "my-project"

    def test_explicit_project_key_wins(self, tmp_path: Path) -> None:
        root = _write_toml(
            tmp_path / "checkout-two",
            '[meridian]\nproject = "Canonical Name"\nspecs_path = "specs"\n',
        )
        cfg = load_config(root)
        assert cfg.project == "canonical-name"

    def test_identical_directory_names_collide_by_design(self, tmp_path: Path) -> None:
        """Documented in the spec: resolve by setting `project` explicitly."""
        a = _write_toml(tmp_path / "a" / "meridian", "[meridian]\n")
        b = _write_toml(tmp_path / "b" / "meridian", "[meridian]\n")
        assert load_config(a).project == load_config(b).project == "meridian"

    def test_blank_project_key_falls_back_to_directory(self, tmp_path: Path) -> None:
        root = _write_toml(tmp_path / "fallback-repo", '[meridian]\nproject = ""\n')
        assert load_config(root).project == "fallback-repo"

    def test_missing_config_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nowhere")

    def test_relative_cwd_still_yields_the_directory_slug(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A relative start must not collapse the slug to `unknown-project`.

        `root` comes from the config file's parent, so starting at `Path(".")`
        gave a parent whose `.name` is "" — every repo then shared one slug in
        the global index, and a rebuild in any of them deleted the others' rows.
        That is exactly the cross-project deletion FEAT-007 exists to prevent.
        """
        root = _write_toml(tmp_path / "relative-repo", "[meridian]\n")
        monkeypatch.chdir(root)
        assert load_config(Path(".")).project == "relative-repo"
        assert load_config(Path(".")).project != UNKNOWN_PROJECT

    def test_relative_cwd_from_a_subdirectory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _write_toml(tmp_path / "nested-repo", "[meridian]\n")
        (root / "specs" / "FEAT-001").mkdir(parents=True)
        monkeypatch.chdir(root / "specs" / "FEAT-001")
        assert load_config(Path(".")).project == "nested-repo"

    def test_default_cwd_is_resolved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _write_toml(tmp_path / "implicit-repo", "[meridian]\n")
        monkeypatch.chdir(root)
        assert load_config().project == "implicit-repo"
