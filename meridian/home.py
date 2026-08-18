"""Machine-global Meridian paths (FEAT-009).

Everything else in Meridian is per-repo and reached through ``load_config()``.
The project registry is the exception: it must be readable from anywhere,
including from a repo that is not itself tracked, so this module deliberately
imports nothing from :mod:`meridian.config` and knows only about ``~/.meridian``.

``MERIDIAN_HOME`` overrides the location. Tests must set it — the shared store
under the real home has been destroyed once already.
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_HOME = "~/.meridian"


def meridian_home() -> Path:
    """The machine-global Meridian directory. Not created by this call."""
    raw = os.environ.get("MERIDIAN_HOME") or DEFAULT_HOME
    return Path(raw).expanduser()


def registry_file() -> Path:
    """The global project registry. May not exist yet."""
    return meridian_home() / "projects.toml"
