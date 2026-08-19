import hashlib
import os
import re
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any

import frontmatter

VALID_STATUSES = ("idea", "draft", "in-progress", "blocked", "done", "in-production", "abandoned")
APPETITE_VALUES = ("xs", "s", "m", "l")
APPETITE_LABELS = {"xs": "< 1 day", "s": "1–3 days", "m": "1–2 weeks", "l": "2–6 weeks"}
CONFIDENCE_VALUES = ("low", "medium", "high")

VALID_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "idea":          ("draft", "abandoned"),
    "draft":         ("in-progress", "abandoned"),
    "in-progress":   ("blocked", "done", "abandoned"),
    "blocked":       ("in-progress", "abandoned"),
    # FEAT-018: shipped features can be retired directly. Previously the only
    # route to `abandoned` ran backwards through `in-progress`, which polluted
    # the active-work counters on the dashboard.
    "done":          ("in-production", "in-progress", "abandoned"),
    "in-production": ("done", "abandoned"),
    "abandoned":     ("idea",),
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _slugify(text: str, max_words: int = 5) -> str:
    words = re.sub(r"[^a-z0-9 ]", "", text.lower()).split()
    slug = "_".join(words[:max_words])
    return slug if slug else "untitled"  # G2: guard against all-symbol idea text


def _today() -> str:
    return date.today().isoformat()


def feat_display_name(specs_path: Path, feat_id: str) -> str:
    """Return 'FEAT-NNN: readable name' for display in search results.

    Derives the name from the directory slug (FEAT-001_add_search →
    'add search') — no extra file I/O beyond a glob.  Falls back to the
    bare feat_id if no matching directory is found.
    """
    feat_id_upper = feat_id.upper()
    dirs = list(specs_path.glob(f"{feat_id_upper}_*"))
    if not dirs:
        return feat_id_upper
    # "FEAT-001_add_semantic_search" → strip prefix → "add_semantic_search" → "add semantic search"
    slug_part = dirs[0].name[len(feat_id_upper) + 1:]
    readable = slug_part.replace("_", " ")
    return f"{feat_id_upper}: {readable}"


# --------------------------------------------------------------------------- #
# Spec I/O
# --------------------------------------------------------------------------- #

FEAT_ID = re.compile(r"^FEAT-\d{3,}$")


class AmbiguousFeatureError(ValueError):
    """More than one spec directory matches a feature ID."""


def find_spec(specs_dir: Path, feature_id: str) -> Path | None:
    """Resolve a feature ID to its spec.md, or None.

    FEAT-018: replaces two near-identical globs that both interpolated the raw
    user string and then took ``candidates[0]`` of an unsorted result. A glob
    metacharacter in the ID silently matched a different feature — reported as
    `meridian close 'feat-*' --status draft` transitioning FEAT-002 — and the
    unsorted pick made the choice vary between machines.
    """
    feat_id_norm = feature_id.strip().upper()
    if not FEAT_ID.match(feat_id_norm):
        raise ValueError(
            f"'{feature_id}' is not a feature ID. Expected the form FEAT-007."
        )

    candidates = sorted(specs_dir.glob(f"{feat_id_norm}_*/spec.md"))
    if not candidates:
        return None
    if len(candidates) > 1:
        names = ", ".join(c.parent.name for c in candidates)
        raise AmbiguousFeatureError(
            f"{feat_id_norm} matches more than one spec directory: {names}. "
            "Rename or remove the duplicate."
        )
    return candidates[0]


def load_spec(spec_path: Path) -> dict[str, Any]:
    post = frontmatter.load(str(spec_path))
    data = dict(post.metadata)
    data["_body"] = post.content
    data["_path"] = spec_path
    return data


def save_spec(spec_path: Path, data: dict[str, Any]) -> None:
    data = dict(data)  # don't mutate caller's dict
    body = data.pop("_body", "")
    data.pop("_path", None)

    # B5: skip write when content hasn't actually changed (avoids spurious `updated` bumps)
    if spec_path.exists():
        try:
            existing = frontmatter.load(str(spec_path))
            existing_meta = {k: v for k, v in existing.metadata.items() if k != "updated"}
            new_meta = {k: v for k, v in data.items() if k != "updated"}
            if existing_meta == new_meta and existing.content.strip() == body.strip():
                return
        except Exception:
            pass  # if comparison fails, proceed with write

    data["updated"] = _today()
    post = frontmatter.Post(body, **data)
    _atomic_write(spec_path, frontmatter.dumps(post) + "\n")


def _atomic_write(path: Path, text: str) -> None:
    """Write via a sibling temp file and os.replace.

    FEAT-013: `Path.write_text` truncates before it writes, so a concurrent
    reader — or a second writer racing between truncate and write — can observe
    or persist a half-written spec. An audit reproduced exactly that: 4 of 75
    concurrent `cycle` + `close` trials left a spec holding 4 frontmatter keys
    and no body. os.replace is atomic within a filesystem, so a reader sees
    either the old file or the new one, never a partial.
    """
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


@contextmanager
def edit_spec(spec_path: Path) -> Iterator[dict[str, Any]]:
    """Locked read-modify-write of one spec.

    FEAT-013: the lock previously guarded only `transition_spec`, while
    `cycle`, `link-job`, `unlink-job` and `enrich` all did an unlocked
    load → mutate → save. Yielding the loaded dict inside the lock makes the
    safe path the easy one, so a new call site cannot silently opt out of it.

    Mutate the yielded dict; it is saved on clean exit and left untouched if
    the block raises.
    """
    with spec_lock(spec_path):
        data = load_spec(spec_path)
        yield data
        save_spec(spec_path, data)


def all_specs(specs_dir: Path) -> list[dict[str, Any]]:
    results = []
    for spec_file in sorted(specs_dir.glob("FEAT-*/spec.md")):
        try:
            results.append(load_spec(spec_file))
        except Exception as e:
            # B4: warn instead of silently dropping — a corrupt spec is actionable
            print(
                f"[meridian] Warning: could not load {spec_file.parent.name}/spec.md: {e}",
                file=sys.stderr,
            )
    return results


# --------------------------------------------------------------------------- #
# FEAT-NNN allocation
# --------------------------------------------------------------------------- #

def next_feat_id(specs_dir: Path) -> str:
    existing = [
        d.name for d in specs_dir.iterdir()
        if d.is_dir() and re.match(r"FEAT-\d+", d.name)
    ]
    nums = [int(m.group(1)) for n in existing if (m := re.match(r"FEAT-(\d+)", n))]
    next_num = (max(nums) + 1) if nums else 1
    return f"FEAT-{next_num:03d}"


# --------------------------------------------------------------------------- #
# Create spec
# --------------------------------------------------------------------------- #

SPEC_TEMPLATE = """\
*Idea captured. Set `appetite` in frontmatter, then run `/spec` to elaborate.*
"""

TASKS_TEMPLATE = """\
*No tasks yet. Run `/breakdown` then `/tasks` to generate an ordered task list.*
"""

def create_spec(
    specs_dir: Path,
    idea: str,
    goal: str | None = None,
    appetite: str | None = None,
) -> Path:
    feat_id = next_feat_id(specs_dir)
    slug = _slugify(idea)
    feat_dir = specs_dir / f"{feat_id}_{slug}"
    feat_dir.mkdir(parents=True, exist_ok=True)
    (feat_dir / "sources").mkdir(exist_ok=True)
    (feat_dir / "summaries").mkdir(exist_ok=True)

    today = _today()
    metadata: dict[str, Any] = {
        "id": feat_id.lower(),
        "name": idea,
        "status": "idea",
        "goal": goal or "~",
        "appetite": appetite or None,   # xs | s | m | l
        "confidence": None,             # low | medium | high — how well the problem is understood
        "cycle": None,                  # e.g. "2026-Q2"
        "created": today,
        "updated": today,
        "tags": [],
        "depends_on": [],
        "enables": [],
        "blocked_by": None,
        "blocked_at": None,             # ISO date when blocked (for staleness detection)
        "abandoned_reason": None,       # why it was killed (preserved through revive cycles)
        "abandoned_at": None,           # ISO date when abandoned
        "sources": [],
    }
    post = frontmatter.Post(SPEC_TEMPLATE, **metadata)
    spec_path = feat_dir / "spec.md"
    spec_path.write_text(frontmatter.dumps(post) + "\n")

    tasks_path = feat_dir / "tasks.md"
    tasks_path.write_text(TASKS_TEMPLATE)

    return spec_path


# --------------------------------------------------------------------------- #
# File locking — serialize concurrent read-modify-write on a spec
# --------------------------------------------------------------------------- #

@contextmanager
def spec_lock(spec_path: Path) -> Iterator[None]:
    """Advisory exclusive lock serializing read-modify-write on one spec.

    Without it, two agents transitioning the same feature concurrently can
    interleave load → modify → save and silently drop one update (last writer
    wins). This matters under parallel multi-agent / worktree workflows; a
    single interactive user never contends.

    Uses ``fcntl.flock`` on POSIX. The lock file lives in the system temp dir
    keyed by the spec's absolute path — no repo pollution, and distinct specs
    never block each other. On platforms without ``fcntl`` (e.g. Windows) this
    degrades to a no-op, which is acceptable for the single-user case.
    """
    try:
        import fcntl
    except ImportError:  # pragma: no cover - non-POSIX fallback
        yield
        return

    key = hashlib.sha1(str(spec_path.resolve()).encode()).hexdigest()[:16]
    lock_path = Path(tempfile.gettempdir()) / f"meridian-spec-{key}.lock"
    with open(lock_path, "w") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


# --------------------------------------------------------------------------- #
# Lifecycle transition
# --------------------------------------------------------------------------- #

def transition_spec(
    spec_path: Path,
    new_status: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Transition a spec to new_status in a single save.

    `extra` lets callers attach additional field updates (e.g. blocked_by,
    abandoned_reason, confidence) that are applied before the single write,
    avoiding the double-save anti-pattern (B3).

    Transitioning to the status a feature is already in is a **no-op success**
    (FEAT-015), not an error: any `extra` fields are still applied, and the
    caller can tell the difference via the returned ``_unchanged`` flag. An
    automation loop must be able to re-run a command safely — previously a
    retry after a partial failure hit "Cannot transition 'done' → 'done'" and
    stuck permanently.

    The whole read-modify-write runs under ``spec_lock`` so concurrent
    transitions of the same feature serialize instead of racing (FEAT-004).
    """
    if new_status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{new_status}'. Valid: {', '.join(VALID_STATUSES)}")

    with spec_lock(spec_path):
        data = load_spec(spec_path)
        current = data.get("status", "idea")

        if current == new_status:
            if extra:
                data.update(extra)
                save_spec(spec_path, data)
            data["_unchanged"] = True
            return data

        allowed = VALID_TRANSITIONS.get(current, ())
        if new_status not in allowed:
            raise ValueError(
                f"Cannot transition '{current}' → '{new_status}'. "
                f"Allowed from '{current}': {', '.join(allowed) or 'none'}"
            )

        data["status"] = new_status
        if new_status == "blocked":
            data["blocked_at"] = _today()
        else:
            data["blocked_by"] = None   # clear stale reason when leaving blocked
            data["blocked_at"] = None   # clear staleness timestamp when unblocked
        if new_status == "abandoned":
            data["abandoned_at"] = _today()
        if new_status == "idea":  # revive — clear date but preserve reason as historical note
            data["abandoned_at"] = None

        # Apply caller-supplied extra fields after status logic so they take precedence
        if extra:
            data.update(extra)

        save_spec(spec_path, data)
        return data


# --------------------------------------------------------------------------- #
# Task progress
# --------------------------------------------------------------------------- #

def task_progress(feat_dir: Path) -> tuple[int, int] | None:
    """Return (checked, total) checkbox counts from tasks.md.

    Returns None when no real task items exist (stub or empty file).
    Checked items are lines matching ``- [x]`` or ``- [X]``.
    """
    tasks_path = feat_dir / "tasks.md"
    if not tasks_path.exists():
        return None
    text = tasks_path.read_text()
    total = len(re.findall(r"^- \[[ xX]\]", text, re.MULTILINE))
    if total == 0:
        return None
    checked = len(re.findall(r"^- \[[xX]\]", text, re.MULTILINE))
    return (checked, total)


# --------------------------------------------------------------------------- #
# REGISTRY rebuild
# --------------------------------------------------------------------------- #

STATUS_ORDER = {s: i for i, s in enumerate(VALID_STATUSES)}


def _cell(value: Any) -> str:
    """Render a value safe for a markdown table cell.

    FEAT-018: a feature name containing a pipe or a newline shifted every
    column of REGISTRY.md — which is a file the AI reads as a source of truth
    about the project.
    """
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


ADR_NUMBER = re.compile(r"^(\d+)")
ADR_HEADING = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
ADR_TITLE_PREFIX = re.compile(r"^\d+\s*[—–-]\s*")
ADR_STATUS_LINE = re.compile(r"^\*\*Status:\*\*\s*(.+?)\s*$", re.MULTILINE)


def _decision_entry(path: Path) -> dict[str, str]:
    """Index one ADR for REGISTRY.md: number, title, status, link.

    Two shapes exist in the wild and both must read. The early ADRs carry YAML
    frontmatter (``status: accepted``); the ones `/decision` writes carry none
    and put the state in a ``**Status:** Accepted`` line. The ``# NNN — Title``
    heading is the only thing every ADR has, so it is the primary title source,
    with frontmatter ``title`` and the filename stem behind it.

    A malformed ADR is never fatal. FEAT-013 showed the failure shape with a
    goal file: the rebuild runs *after* a spec has been written to disk, so
    raising here leaves the registry stale and the user with a traceback. An
    unreadable ADR becomes a row marked ``unparseable`` — visible and
    actionable, rather than silently dropped.
    """
    number = m.group(1) if (m := ADR_NUMBER.match(path.stem)) else ""
    stem_title = re.sub(r"^\d+[-_\s]*", "", path.stem).replace("-", " ").replace("_", " ").strip()
    fallback_title = stem_title or path.stem

    try:
        post = frontmatter.load(str(path))
    except Exception as e:
        # B4 / FEAT-013: warn and keep going — one bad ADR must not stop the rebuild
        print(
            f"[meridian] Warning: could not load decisions/{path.name}: {e}",
            file=sys.stderr,
        )
        return {
            "number": number or "—",
            "title": fallback_title,
            "status": "unparseable",
            "file": path.name,
        }

    meta = post.metadata
    if not number:
        adr_id = str(meta.get("id", ""))
        number = m.group(1) if (m := re.search(r"(\d+)", adr_id)) else "—"

    heading = h.group(1) if (h := ADR_HEADING.search(post.content)) else ""
    title = ADR_TITLE_PREFIX.sub("", heading) or str(meta.get("title") or "") or fallback_title

    status_line = s.group(1) if (s := ADR_STATUS_LINE.search(post.content)) else ""
    # Lower-cased so the column is scannable: the two shapes disagree on case
    # ("accepted" in frontmatter, "Accepted" in the `/decision` template), and a
    # skill filtering for `superseded` should not have to guess which it is.
    status = str(meta.get("status") or status_line or "—").lower()

    return {"number": number, "title": title, "status": status, "file": path.name}


def scan_decisions(decisions_dir: Path) -> list[dict[str, str]]:
    """Index every ADR in ``specs/decisions/``, sorted by filename.

    A missing directory is normal — most projects have no ADRs — and yields an
    empty list rather than an error.
    """
    if not decisions_dir.is_dir():
        return []
    return [_decision_entry(df) for df in sorted(decisions_dir.glob("*.md"))]


def rebuild_registry(specs_dir: Path) -> None:
    specs = all_specs(specs_dir)
    specs.sort(key=lambda s: (STATUS_ORDER.get(s.get("status", "idea"), 99), s.get("id", "")))

    goals_dir = specs_dir / "goals"
    goals = []
    if goals_dir.exists():
        for gf in sorted(goals_dir.glob("*.md")):
            gp = frontmatter.load(str(gf))
            goals.append({
                "id": gp.metadata.get("id", gf.stem),
                "name": gp.metadata.get("name", gf.stem),
                "status": gp.metadata.get("status", "active"),
            })

    decisions = scan_decisions(specs_dir / "decisions")

    lines = [
        "# Meridian Registry",
        "",
        "Index of all features across all goals and lifecycle states.",
        "",
        "## Status Legend",
        "`idea` `draft` `in-progress` `blocked` `done` `in-production` `abandoned`",
        "",
        "## Appetite Legend",
        "`xs` < 1 day  ·  `s` 1–3 days  ·  `m` 1–2 weeks  ·  `l` 2–6 weeks",
        "",
        "## Confidence Legend",
        "`low` problem poorly understood  ·  `medium` rough shape clear  ·  `high` well-defined",
        "",
        "## Features",
        "",
        "| ID | Name | Goal | Status | Appetite | Conf | Cycle | Updated |",
        "|---|---|---|---|---|---|---|---|",
    ]

    for s in specs:
        feat_id = s.get("id", "?").upper()
        name = s.get("name", "Untitled")
        goal = s.get("goal") or "—"
        status = s.get("status", "idea")
        appetite = s.get("appetite") or "—"
        confidence = s.get("confidence") or "—"
        cycle = s.get("cycle") or "—"
        updated = s.get("updated", "—")
        lines.append(
            "| " + " | ".join(_cell(v) for v in (
                feat_id, name, goal, status, appetite, confidence, cycle, updated
            )) + " |"
        )

    if not specs:
        lines.append("| — | — | — | — | — | — | — | — |")

    lines += [
        "",
        "## Goals",
        "",
        "| ID | Name | Status |",
        "|---|---|---|",
    ]

    for g in goals:
        lines.append(
            "| " + " | ".join(_cell(g[k]) for k in ("id", "name", "status")) + " |"
        )

    if not goals:
        lines.append("| — | — | — |")

    # FEAT-021: ADRs last — features are the primary content of this file, and a
    # skill reads it top to bottom. Without this section the decisions were
    # write-only: `/spec` and `/breakdown` could not cite a decision already made.
    lines += [
        "",
        "## Decisions",
        "",
        "| # | Title | Status | File |",
        "|---|---|---|---|",
    ]

    for d in decisions:
        link = f"[{d['file']}](decisions/{d['file']})"
        lines.append(
            "| " + " | ".join(_cell(v) for v in (
                d["number"], d["title"], d["status"], link
            )) + " |"
        )

    if not decisions:
        lines.append("| — | — | — | — |")

    lines.append("")
    (specs_dir / "REGISTRY.md").write_text("\n".join(lines))
