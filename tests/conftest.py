"""Shared fixtures for the Meridian test suite."""
import os
from pathlib import Path

import pytest

from meridian.config import MeridianConfig


@pytest.fixture(scope="session", autouse=True)
def _isolate_meridian_home(tmp_path_factory) -> Path:
    """Point MERIDIAN_HOME at a throwaway directory for the whole session.

    Autouse and session-scoped because the damage is silent and global: the
    subprocess CLI tests run the real binary, which inherits this process's
    environment, and `meridian init` registers the repo it just created. Without
    this, running the test suite writes pytest tmp directories into the
    developer's real ~/.meridian/projects.toml (observed 2026-08-18) and any
    future global write would land there too.

    Sets the variable in os.environ directly rather than via monkeypatch so it
    survives into subprocesses spawned by any test.
    """
    home = tmp_path_factory.mktemp("meridian-home")
    previous = os.environ.get("MERIDIAN_HOME")
    os.environ["MERIDIAN_HOME"] = str(home)
    yield home
    if previous is None:
        os.environ.pop("MERIDIAN_HOME", None)
    else:
        os.environ["MERIDIAN_HOME"] = previous


@pytest.fixture
def specs_dir(tmp_path: Path) -> Path:
    """Minimal specs/ directory with goals/ and decisions/ subdirs."""
    sd = tmp_path / "specs"
    sd.mkdir()
    (sd / "goals").mkdir()
    (sd / "decisions").mkdir()
    return sd


@pytest.fixture
def project_dir(tmp_path: Path, specs_dir: Path) -> Path:
    """Full project root: .meridian.toml pointing at specs/."""
    toml = (
        "[meridian]\n"
        f'specs_path = "specs"\n'
        f'lancedb_path = "{tmp_path / ".meridian" / "lancedb"}"\n'
    )
    (tmp_path / ".meridian.toml").write_text(toml)
    return tmp_path


@pytest.fixture
def mock_cfg(tmp_path: Path, specs_dir: Path) -> MeridianConfig:
    """MeridianConfig backed by a tmp directory — no real Ollama or Databricks needed."""
    return MeridianConfig(
        specs_path=specs_dir,
        lancedb_path=tmp_path / ".meridian" / "lancedb",
        ollama_model="mxbai-embed-large",
        reranker_model="BAAI/bge-reranker-v2-m3",
        root=tmp_path,
        project="test-project",
    )


@pytest.fixture
def other_cfg(tmp_path: Path, specs_dir: Path) -> MeridianConfig:
    """A second project sharing mock_cfg's LanceDB path.

    FEAT-007: the shared index is the whole problem, so isolation tests need
    two configs that differ only by project slug.
    """
    return MeridianConfig(
        specs_path=specs_dir,
        lancedb_path=tmp_path / ".meridian" / "lancedb",
        ollama_model="mxbai-embed-large",
        reranker_model="BAAI/bge-reranker-v2-m3",
        root=tmp_path,
        project="other-project",
    )


def make_goal(specs_dir: Path, goal_id: str = "goal-01", name: str = "Test Goal") -> Path:
    """Helper: write a minimal goal file and return its path."""
    content = f"---\nid: {goal_id}\nname: {name}\nstatus: active\n---\nGoal body.\n"
    path = specs_dir / "goals" / f"{goal_id}.md"
    path.write_text(content)
    return path
