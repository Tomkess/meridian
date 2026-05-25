"""Shared fixtures for the Meridian test suite."""
from pathlib import Path

import pytest

from meridian.config import MeridianConfig


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
        "\n"
        "[databricks]\n"
        'host = ""\n'
        'token_env = "DATABRICKS_TOKEN"\n'
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
        databricks_host="",
        databricks_token_env="DATABRICKS_TOKEN",
        databricks_status_timeout=8,
        root=tmp_path,
    )


def make_goal(specs_dir: Path, goal_id: str = "goal-01", name: str = "Test Goal") -> Path:
    """Helper: write a minimal goal file and return its path."""
    content = f"---\nid: {goal_id}\nname: {name}\nstatus: active\n---\nGoal body.\n"
    path = specs_dir / "goals" / f"{goal_id}.md"
    path.write_text(content)
    return path
