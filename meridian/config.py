import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

# FEAT-007: used when a directory name slugifies to nothing (e.g. "___").
# A stable literal beats raising: a weird path must never brick the CLI.
UNKNOWN_PROJECT = "unknown-project"


@dataclass
class MeridianConfig:
    specs_path: Path
    lancedb_path: Path
    ollama_model: str
    reranker_model: str
    root: Path  # repo root where .meridian.toml lives
    # FEAT-007: which project owns rows in the shared LanceDB index. The index
    # defaults to ~/.meridian/lancedb, which every install shares, so without
    # this every repo reads and overwrites every other repo's chunks.
    # Non-default on purpose — load_config() always supplies it — and declared
    # before the defaulted fields below, which must stay trailing.
    project: str
    # FEAT-006: optional Ollama vision model used as the *fallback* describer for
    # `meridian enrich --vision`. Empty by default: the primary describer is the
    # agent that can already see the screenshot, so a concrete default would only
    # produce "model not found" warnings on machines that never pull one.
    ollama_vision_model: str = ""


def slugify_project(name: str) -> str:
    """Normalise a project name into an index-safe slug.

    Pure and deterministic: the same string always yields the same slug, with
    no filesystem or git access. Two repos whose directory names match produce
    the same slug — accepted, and resolved by setting `project` explicitly in
    .meridian.toml.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or UNKNOWN_PROJECT


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
    specs_path = root / meridian_section.get("specs_path", "specs")
    # FEAT-018: default through meridian_home() so MERIDIAN_HOME redirects the
    # vector store as well as the registry. It did not, so a test or sandbox
    # following the documented safety instruction still read and wrote the
    # developer's real LanceDB — the likely mechanism behind the destruction of
    # the global store on 2026-08-18.
    from meridian.home import meridian_home

    lancedb_raw = meridian_section.get("lancedb_path")
    lancedb_path = (
        Path(lancedb_raw).expanduser() if lancedb_raw
        else meridian_home() / "lancedb"
    )

    return MeridianConfig(
        specs_path=specs_path,
        lancedb_path=lancedb_path,
        ollama_model=meridian_section.get("ollama_model", "mxbai-embed-large"),
        reranker_model=meridian_section.get("reranker_model", "BAAI/bge-reranker-v2-m3"),
        root=root,
        project=slugify_project(str(meridian_section.get("project", "")) or root.name),
        ollama_vision_model=meridian_section.get("ollama_vision_model", ""),
    )
