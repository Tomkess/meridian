"""Global idea inbox: capture files and their parsing (FEAT-008).

A capture is one markdown file in ``~/.meridian/inbox/``. Frontmatter is
entirely optional — a bare line of text dropped in by any tool is a valid
capture, because the point is that capture costs five seconds from a phone.
Everything that can be inferred (timestamp, routing hint) is inferred rather
than demanded.

One file per capture, never an append-to-one-file log: a phone and a laptop
writing at once must not interleave, and triage must be able to move a single
item without rewriting the rest.
"""
from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from meridian.home import inbox_dir

# Filenames are the capture timestamp: 2026-08-18T164500.md, plus an optional
# -N suffix when two captures land in the same second.
_FILENAME_TS = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2})(\d{2})(\d{2})(?:-\d+)?$")
_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
# A routing hint: #some-project-slug. Requires a letter to start, so "#1" and
# "#2026" in prose are not mistaken for project names.
_HASHTAG = re.compile(r"(?<!\w)#([a-z][a-z0-9-]*)", re.IGNORECASE)

_FRONTMATTER_KEYS = ("project", "goal", "appetite", "created")


@dataclass
class Capture:
    path: Path
    text: str
    created: datetime.datetime
    project: str | None = None
    goal: str | None = None
    appetite: str | None = None
    hint_source: str | None = None  # "frontmatter" | "hashtag" | None

    @property
    def capture_id(self) -> str:
        """Stable id used by `meridian inbox route/drop`."""
        return self.path.stem

    @property
    def first_line(self) -> str:
        for line in self.text.splitlines():
            if line.strip():
                return line.strip()
        return ""

    @property
    def is_routable(self) -> bool:
        """False for empty or whitespace-only captures (AC20)."""
        return bool(self.text.strip())


def _created_from(path: Path) -> datetime.datetime:
    """Timestamp from the filename, falling back to mtime.

    Filename first because a capture may be synced from another device, where
    mtime reflects the sync rather than the thought.
    """
    m = _FILENAME_TS.match(path.stem)
    if m:
        date_part, hh, mm, ss = m.groups()
        try:
            d = datetime.date.fromisoformat(date_part)
            return datetime.datetime(d.year, d.month, d.day, int(hh), int(mm), int(ss))
        except ValueError:
            pass
    return datetime.datetime.fromtimestamp(path.stat().st_mtime)


def _parse_frontmatter(raw: str) -> tuple[dict, str]:
    """Split optional frontmatter from the body.

    Malformed frontmatter is treated as body text rather than an error: losing
    a captured idea to a YAML typo would be worse than ignoring its metadata.
    """
    m = _FRONTMATTER.match(raw)
    if not m:
        return {}, raw
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return {}, raw
    if not isinstance(data, dict):
        return {}, raw
    return data, raw[m.end():]


def _hashtag_hint(text: str) -> str | None:
    match = _HASHTAG.search(text)
    return match.group(1).lower() if match else None


def read_capture(path: Path) -> Capture:
    """Parse one capture file. Never raises on missing or odd metadata."""
    raw = path.read_text(errors="replace")
    data, body = _parse_frontmatter(raw)

    fields = {k: data.get(k) for k in _FRONTMATTER_KEYS}
    project = fields["project"]
    hint_source: str | None = None
    if project:
        project = str(project).strip().lower()
        hint_source = "frontmatter"
    else:
        project = _hashtag_hint(body)
        if project:
            hint_source = "hashtag"

    created = None
    if fields["created"]:
        try:
            created = datetime.datetime.fromisoformat(str(fields["created"]))
        except ValueError:
            created = None

    return Capture(
        path=path,
        text=body.strip("\n"),
        created=created or _created_from(path),
        project=project or None,
        goal=str(fields["goal"]).strip() if fields["goal"] else None,
        appetite=str(fields["appetite"]).strip() if fields["appetite"] else None,
        hint_source=hint_source,
    )


def write_capture(
    text: str,
    *,
    project: str | None = None,
    now: datetime.datetime | None = None,
) -> Path:
    """Write a capture and return its path.

    ``now`` is injectable so tests need not sleep to produce distinct names.
    """
    stamp = (now or datetime.datetime.now()).strftime("%Y-%m-%dT%H%M%S")
    directory = inbox_dir()

    path = directory / f"{stamp}.md"
    suffix = 1
    while path.exists():
        # Two captures in the same second must both survive.
        path = directory / f"{stamp}-{suffix}.md"
        suffix += 1

    body = text.strip()
    if project:
        path.write_text(f"---\nproject: {project}\n---\n{body}\n")
    else:
        path.write_text(f"{body}\n")
    return path


def list_captures() -> list[Capture]:
    """Pending captures, oldest first. Archived subdirectories are excluded."""
    directory = inbox_dir()
    files = sorted(p for p in directory.glob("*.md") if p.is_file())
    return sorted((read_capture(p) for p in files), key=lambda c: c.created)


def find_capture(capture_id: str) -> Capture | None:
    """Look up a pending capture by id (its filename stem)."""
    for capture in list_captures():
        if capture.capture_id == capture_id:
            return capture
    return None


def archive(capture: Capture, destination: Path) -> Path:
    """Move a capture out of the pending inbox. Never deletes.

    Returns the new path. A name clash in the destination gets a suffix rather
    than overwriting a previously archived capture.
    """
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / capture.path.name
    suffix = 1
    while target.exists():
        target = destination / f"{capture.path.stem}-{suffix}{capture.path.suffix}"
        suffix += 1
    capture.path.rename(target)
    return target
