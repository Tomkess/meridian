"""Global project registry (FEAT-008).

Triage runs from outside any repo and must reach into arbitrary ones, so it
cannot discover projects by walking the filesystem. ``~/.meridian/projects.toml``
is that map, written by ``meridian init`` / ``meridian install`` and keyed by the
FEAT-007 project slug.

A stale entry — a repo moved, renamed, or sitting on an unmounted disk — is
reported, never removed. Silently forgetting a project is exactly the failure
mode this feature exists to prevent.
"""
from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path

from meridian.home import registry_file

logger = logging.getLogger(__name__)


@dataclass
class ProjectEntry:
    slug: str
    path: Path
    purpose: str
    exists: bool


def _quote(value: str) -> str:
    """Minimal TOML basic-string escaping for values we write."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def all_projects() -> list[ProjectEntry]:
    """Every registered project, sorted by slug.

    A missing or unreadable registry yields an empty list rather than raising:
    `meridian inbox` should still list captures on a machine where nothing has
    been registered yet.
    """
    path = registry_file()
    if not path.exists():
        return []
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as e:
        logger.warning("Could not read project registry at %s (%s)", path, e)
        return []

    entries = []
    for item in raw.get("project", []):
        slug = str(item.get("slug", "")).strip()
        raw_path = str(item.get("path", "")).strip()
        if not slug or not raw_path:
            continue
        project_path = Path(raw_path).expanduser()
        entries.append(ProjectEntry(
            slug=slug,
            path=project_path,
            purpose=str(item.get("purpose", "")).strip(),
            exists=project_path.is_dir(),
        ))
    return sorted(entries, key=lambda e: e.slug)


def find_project(slug: str) -> ProjectEntry | None:
    for entry in all_projects():
        if entry.slug == slug:
            return entry
    return None


def register(slug: str, path: Path, purpose: str = "") -> ProjectEntry:
    """Add or update one project, keyed by slug.

    Re-running `meridian init` in the same repo updates the entry in place
    rather than appending a duplicate (AC7).
    """
    entries = {e.slug: e for e in all_projects()}
    entries[slug] = ProjectEntry(
        slug=slug,
        path=path.expanduser().resolve(),
        purpose=purpose.strip(),
        exists=path.is_dir(),
    )
    _write(sorted(entries.values(), key=lambda e: e.slug))
    return entries[slug]


def _write(entries: list[ProjectEntry]) -> None:
    lines = [
        "# Meridian project registry — add a repo with `meridian register`",
        "# (`meridian init` registers automatically). Read by `meridian status --all`",
        "# and `meridian install --all`. Safe to edit by hand.",
        "",
    ]
    for e in entries:
        lines.append("[[project]]")
        lines.append(f'slug    = "{_quote(e.slug)}"')
        lines.append(f'path    = "{_quote(str(e.path))}"')
        lines.append(f'purpose = "{_quote(e.purpose)}"')
        lines.append("")

    path = registry_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


# Headings that name the document rather than describe the project. Matching one
# tells a router nothing — every repo's VISION.md starts "# Vision".
_GENERIC_HEADINGS = {
    "vision", "north star", "northstar", "overview", "readme", "introduction",
    "project vision", "purpose", "about",
}


def derive_purpose(specs_path: Path, fallback: str) -> str:
    """One-line description of a project, for routing and `meridian projects`.

    Prefers the first line of real prose in VISION.md over its heading: the
    heading is almost always the document's name, not the project's purpose,
    and "Vision" is worthless as a routing signal. A distinctive heading is
    used when there is no prose. Falls back to the caller's default.
    """
    vision = specs_path / "VISION.md"
    if not vision.exists():
        return fallback

    heading: str | None = None
    in_frontmatter = False
    for i, line in enumerate(vision.read_text(errors="replace").splitlines()):
        stripped = line.strip()
        if i == 0 and stripped == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if stripped == "---":
                in_frontmatter = False
            continue
        if not stripped or stripped.startswith(("<!--", ">", "|", "-", "*")):
            continue
        if stripped.startswith("#"):
            text = stripped.lstrip("#").strip()
            if text and heading is None and text.lower() not in _GENERIC_HEADINGS:
                heading = text
            continue
        # First real prose line — the closest thing to a stated purpose.
        return stripped[:200]

    return heading or fallback
