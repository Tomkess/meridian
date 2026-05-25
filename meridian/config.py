import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class MeridianConfig:
    specs_path: Path
    lancedb_path: Path
    ollama_model: str
    reranker_model: str
    databricks_host: str
    databricks_token_env: str
    databricks_status_timeout: int  # P5: seconds to wait per job-status fetch
    root: Path  # repo root where .meridian.toml lives


def _find_config_file(start: Path) -> Path | None:
    for parent in [start, *start.parents]:
        candidate = parent / ".meridian.toml"
        if candidate.exists():
            return candidate
    return None


def load_config(cwd: Path | None = None) -> MeridianConfig:
    cwd = cwd or Path.cwd()
    config_file = _find_config_file(cwd)
    if config_file is None:
        raise FileNotFoundError(
            "No .meridian.toml found. Run from within a Meridian project."
        )

    with open(config_file, "rb") as f:
        raw = tomllib.load(f)

    root = config_file.parent
    meridian_section = raw.get("meridian", {})
    databricks_section = raw.get("databricks", {})

    specs_path = root / meridian_section.get("specs_path", "specs")
    lancedb_raw = meridian_section.get("lancedb_path", "~/.meridian/lancedb")
    lancedb_path = Path(lancedb_raw).expanduser()

    return MeridianConfig(
        specs_path=specs_path,
        lancedb_path=lancedb_path,
        ollama_model=meridian_section.get("ollama_model", "mxbai-embed-large"),
        reranker_model=meridian_section.get("reranker_model", "BAAI/bge-reranker-v2-m3"),
        databricks_host=databricks_section.get("host", ""),
        databricks_token_env=databricks_section.get("token_env", "DATABRICKS_TOKEN"),
        databricks_status_timeout=int(databricks_section.get("status_timeout", 8)),
        root=root,
    )
