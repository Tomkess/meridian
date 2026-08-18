"""Machine-global Meridian paths (FEAT-008).

Everything else in Meridian is per-repo and reached through ``load_config()``,
which raises without a ``.meridian.toml``. Capture has to work from anywhere on
the machine — a phone sync folder, a scratch directory, someone's home — so this
module deliberately imports nothing from :mod:`meridian.config` and knows only
about ``~/.meridian``.

``MERIDIAN_HOME`` overrides the location. Tests must set it: the shared store
under the real ``~/.meridian`` has been destroyed once already.
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_HOME = "~/.meridian"


def meridian_home() -> Path:
    """The machine-global Meridian directory. Not created by this call."""
    raw = os.environ.get("MERIDIAN_HOME") or DEFAULT_HOME
    return Path(raw).expanduser()


def inbox_dir(*, create: bool = True) -> Path:
    """Pending captures awaiting triage."""
    return _dir(meridian_home() / "inbox", create)


def processed_dir(*, create: bool = True) -> Path:
    """Captures already routed into a project. Moved here, never deleted."""
    return _dir(inbox_dir(create=create) / ".processed", create)


def icebox_dir(*, create: bool = True) -> Path:
    """Captures explicitly dropped during triage. Also never deleted."""
    return _dir(inbox_dir(create=create) / ".icebox", create)


def registry_file() -> Path:
    """The global project registry (FEAT-008 AC6). May not exist yet."""
    return meridian_home() / "projects.toml"


DEFAULT_LANCEDB = "~/.meridian/lancedb"
DEFAULT_EMBED_MODEL = "mxbai-embed-large"


def search_context() -> tuple[Path, str]:
    """Resolve (lancedb_path, embedding model) without requiring a repo.

    Triage runs from anywhere, so it cannot depend on ``load_config()``. Prefer
    the current repo's settings when there is one, fall back to a registered
    project's, and finally to the documented defaults — the same store every
    install shares. Returning defaults is correct rather than lossy: a machine
    that never customised these is the common case.
    """
    try:
        from meridian.config import load_config

        cfg = load_config()
        return cfg.lancedb_path, cfg.ollama_model
    except Exception:
        pass

    try:
        import tomllib

        from meridian.registry import all_projects

        for entry in all_projects():
            config_file = entry.path / ".meridian.toml"
            if not config_file.exists():
                continue
            with open(config_file, "rb") as f:
                section = tomllib.load(f).get("meridian", {})
            return (
                Path(section.get("lancedb_path", DEFAULT_LANCEDB)).expanduser(),
                section.get("ollama_model", DEFAULT_EMBED_MODEL),
            )
    except Exception:
        pass

    return Path(DEFAULT_LANCEDB).expanduser(), DEFAULT_EMBED_MODEL


def _dir(path: Path, create: bool) -> Path:
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path
