"""Meridian — AI-driven development workflow system."""
from importlib.metadata import PackageNotFoundError, version

try:
    # Single source of truth is `version` in pyproject.toml. Reading it back from
    # installed metadata means there is nothing to keep in sync, and — unlike a
    # dynamic version resolved from this file — it leaves `uv version --bump`
    # able to do the bumping.
    __version__ = version("meridian")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0+dev"

__all__ = ["__version__"]
