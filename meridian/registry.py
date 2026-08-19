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
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path

import tomli_w

from meridian.home import registry_file

logger = logging.getLogger(__name__)


class RegistryUnreadableError(RuntimeError):
    """`projects.toml` exists but cannot be parsed.

    FEAT-013: this used to be swallowed — `all_projects()` returned an empty
    list, and the next `register` rewrote the file from that empty list,
    permanently deleting every other project. Callers must now see the
    difference between "no projects" and "cannot read the projects".
    """


@dataclass
class ProjectEntry:
    slug: str
    path: Path
    purpose: str
    exists: bool


def all_projects() -> list[ProjectEntry]:
    """Every registered project, sorted by slug.

    A *missing* registry is an empty list — nothing has been registered yet.
    An *unreadable* one raises: silently treating a corrupt file as empty is
    what allowed a single stray byte to wipe the registry on the next write.
    """
    path = registry_file()
    if not path.exists():
        return []
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as e:
        backup = path.with_suffix(path.suffix + ".bak")
        hint = f" A previous copy may exist at {backup}." if backup.exists() else ""
        raise RegistryUnreadableError(
            f"The project registry at {path} could not be read ({e}). "
            f"Fix or remove the file — Meridian will not overwrite it.{hint}"
        ) from e

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


_HEADER = (
    "# Meridian project registry — add a repo with `meridian register`\n"
    "# (`meridian init` registers automatically). Read by `meridian status --all`\n"
    "# and `meridian install --all`. Safe to edit by hand.\n\n"
)


def _write(entries: list[ProjectEntry]) -> None:
    """Serialise the registry, keeping a backup of what was there.

    Uses a real TOML writer: the previous hand-rolled escaping did not handle
    control characters, so a newline in `--purpose` produced a file that could
    never be read again.
    """
    document = {
        "project": [
            {"slug": e.slug, "path": str(e.path), "purpose": e.purpose}
            for e in entries
        ]
    }

    path = registry_file()
    path.parent.mkdir(parents=True, exist_ok=True)

    # Keep the previous good copy — the registry is the one piece of Meridian
    # state that is not reconstructible from any repo.
    if path.exists():
        try:
            shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        except OSError as e:  # pragma: no cover - best effort
            logger.warning("Could not back up the project registry (%s)", e)

    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(_HEADER.encode())
            tomli_w.dump(document, f)
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


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
