"""Cross-project portfolio ranking (FEAT-026).

``meridian status --all`` tallies. This module answers the question a tally
cannot: *what should I work on next, across everything?*

Two layers, deliberately separable:

* **Gathering** — :func:`gather` reads each tracked project's specs exactly
  once and attaches the three signals already sitting on disk: blocked age
  (``blocked_at``), task progress (``tasks.md`` checkboxes) and staleness
  (spec/task file mtimes).
* **Ranking** — :func:`tier`, :func:`rank_key`, :func:`reason` and :func:`rank`
  are pure functions over :class:`Feature` values. No Rich, no typer, no
  filesystem. That is what makes the ordering testable, and what lets a
  ``--json`` consumer re-rank without re-deriving any signal.

The ordering is stated once, in :data:`ORDERING_RULE`, and printed by the
command. An opaque score would be worse than the tally it replaces: every row
has to be able to say why it is where it is.
"""
from __future__ import annotations

import time
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

# The blocked-age threshold is `meridian guide`'s, imported rather than
# re-declared: two numbers that must agree is exactly how a "14 days" in one
# view and a "21 days" in another get shipped. Private on purpose over there —
# this is the one other place in the codebase that needs the same convention.
from meridian.guide import _STALE_BLOCKED_DAYS
from meridian.registry import ProjectEntry
from meridian.specs import all_specs, task_progress

# --------------------------------------------------------------------------- #
# Conventions
# --------------------------------------------------------------------------- #

#: Statuses that represent work someone could pick up. `done`, `in-production`
#: and `abandoned` are outcomes, not options, so they never rank.
ACTIONABLE_STATUSES = ("blocked", "in-progress", "draft", "idea")

#: Statuses whose appetite counts against a cycle — the same set
#: `meridian cycle` uses. An idea has not been shaped, so its appetite is not
#: a commitment.
COMMITTABLE_STATUSES = ("draft", "in-progress", "blocked")

#: Blocked at least this long is "rotting" — `meridian guide`'s threshold.
BLOCKED_LONG_DAYS = _STALE_BLOCKED_DAYS

#: Nothing changed for this long and the row is marked stale.
STALE_DAYS = 30

#: Weighted effort units, proportional to the appetite labels. Shared with
#: `meridian cycle`'s capacity summary so both views count the same way.
APPETITE_WEIGHT: dict[str, float] = {"xs": 0.5, "s": 1.0, "m": 3.0, "l": 6.0}

#: Shape Up: at most two big bets in flight. Applied across projects — two
#: large bets in each of five repos is ten, and no per-repo check can see that.
LARGE_APPETITE = "l"
MAX_LARGE_BETS = 2

ORDERING_RULE = (
    "blocked longest first, then in-progress nearest completion, "
    "then in-progress that has stalled, then draft, then idea"
)

STALENESS_NOTE = (
    "Days since change comes from spec.md and tasks.md file mtimes, not git — "
    "a fresh clone or a branch switch resets them to now."
)

# Rank tiers, in the order of ORDERING_RULE.
TIER_BLOCKED = 0
TIER_FINISHING = 1
TIER_STALLED = 2
TIER_DRAFT = 3
TIER_IDEA = 4

_SECONDS_PER_DAY = 86400.0


# --------------------------------------------------------------------------- #
# Values
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Feature:
    """One feature, flattened to the signals the ranking uses.

    Everything the ordering depends on is a field here, so ranking never
    touches the filesystem and a ``--json`` consumer sees exactly the inputs
    the ranking saw.
    """

    project: str
    feat_id: str
    name: str
    status: str
    appetite: str | None = None
    confidence: str | None = None
    cycle: str | None = None
    goal: str | None = None
    blocked_by: str | None = None
    blocked_days: int | None = None
    tasks_checked: int | None = None
    tasks_total: int | None = None
    days_since_change: int | None = None
    depends_on: tuple[str, ...] = ()
    updated: str | None = None
    path: str | None = None

    @property
    def is_stale(self) -> bool:
        return self.days_since_change is not None and self.days_since_change >= STALE_DAYS

    @property
    def tasks_remaining(self) -> int | None:
        if self.tasks_total is None or self.tasks_checked is None:
            return None
        return max(0, self.tasks_total - self.tasks_checked)


@dataclass(frozen=True)
class Capacity:
    """How much appetite one project has committed to a cycle."""

    committed: int = 0
    weight: float = 0.0
    by_appetite: tuple[tuple[str, int], ...] = ()
    large_bets: int = 0
    uncommitted: int = 0      # active features carrying no cycle — not the same as zero
    unsized: int = 0          # committed but no appetite set, so weight under-reports
    cycles: tuple[str, ...] = ()


@dataclass(frozen=True)
class PortfolioCapacity:
    """The same numbers summed across every project, plus the Shape Up check."""

    committed: int = 0
    weight: float = 0.0
    large_bets: int = 0
    uncommitted: int = 0
    unsized: int = 0
    projects_committed: int = 0
    cycles: tuple[str, ...] = ()

    @property
    def overloaded(self) -> bool:
        return self.large_bets > MAX_LARGE_BETS


@dataclass(frozen=True)
class ProjectView:
    """One tracked project, read once."""

    slug: str
    path: Path
    features: tuple[Feature, ...]
    counts: dict[str, int]
    days_since_change: int | None
    capacity: Capacity
    unreadable_specs: int = 0   # spec.md files on disk that would not parse


@dataclass(frozen=True)
class SkippedProject:
    """A tracked project that could not be read. Reported, never removed."""

    slug: str
    path: str
    why: str


@dataclass(frozen=True)
class Portfolio:
    projects: tuple[ProjectView, ...] = ()
    skipped: tuple[SkippedProject, ...] = ()

    def features(self) -> list[Feature]:
        return [f for view in self.projects for f in view.features]

    def capacity(self) -> PortfolioCapacity:
        return portfolio_capacity(self.projects)

    @property
    def is_stale(self) -> bool:  # pragma: no cover - convenience for callers
        return any(
            v.days_since_change is not None and v.days_since_change >= STALE_DAYS
            for v in self.projects
        )


# --------------------------------------------------------------------------- #
# Ranking — pure functions over Feature values
# --------------------------------------------------------------------------- #

def tier(feature: Feature) -> int | None:
    """Which band of :data:`ORDERING_RULE` *feature* falls into, or None.

    ``None`` means "not actionable" — a done, shipped or abandoned feature is
    an outcome, not something to pick up.

    In-progress splits in two: a feature with at least one task checked off is
    *finishing* and outranks one that has been started in name only. Requiring
    real progress for the "nearest completion" band is what stops an untouched
    feature with a 20-item task list from outranking one that is 11/12 done.
    """
    status = feature.status
    if status == "blocked":
        return TIER_BLOCKED
    if status == "in-progress":
        checked = feature.tasks_checked or 0
        return TIER_FINISHING if checked > 0 else TIER_STALLED
    if status == "draft":
        return TIER_DRAFT
    if status == "idea":
        return TIER_IDEA
    return None


def rank_key(feature: Feature) -> tuple:
    """Sort key implementing :data:`ORDERING_RULE`. Ascending, total, stable.

    Ties break on project then feature ID so the order is reproducible across
    machines rather than dependent on directory iteration.
    """
    band = tier(feature)
    tail = (feature.project, feature.feat_id)
    days = feature.days_since_change

    if band == TIER_BLOCKED:
        # Longest blocked first. An unrecorded blocked_at sorts after every
        # known age — it is a data gap, not an urgent one.
        age = -feature.blocked_days if feature.blocked_days is not None else 1
        return (TIER_BLOCKED, age, -(days or 0), *tail)

    if band == TIER_FINISHING:
        remaining = feature.tasks_remaining
        total = feature.tasks_total or 1
        checked = feature.tasks_checked or 0
        fraction = checked / total
        # Fewest tasks left first; on a tie the more complete one wins, so
        # 11/12 outranks 1/2.
        return (TIER_FINISHING, remaining if remaining is not None else 999, -fraction, *tail)

    if band == TIER_STALLED:
        # Rot first: the one nothing has happened to for longest.
        return (TIER_STALLED, -(days or 0), *tail)

    if band in (TIER_DRAFT, TIER_IDEA):
        # Inventory. Freshest first — a spec you shaped this week is the one
        # you are most likely to be able to start, while a year-old idea is
        # exactly what should sit at the bottom of the list.
        return (band, days if days is not None else 10**6, *tail)

    return (99, *tail)


def reason(feature: Feature) -> str:
    """One line saying why *feature* ranked where it did.

    The ranking is only defensible if every row can be argued with, which
    means naming the signal and its value — never a score.
    """
    band = tier(feature)
    days = feature.days_since_change

    if band == TIER_BLOCKED:
        if feature.blocked_days is None:
            line = "blocked, no date recorded"
        else:
            line = f"blocked {_days(feature.blocked_days)}"
        if feature.blocked_by:
            line += f" — {clip(feature.blocked_by, 44)}"
        return line

    if band == TIER_FINISHING:
        line = f"{feature.tasks_checked} of {feature.tasks_total} tasks done"
        if feature.is_stale:
            line += f", nothing changed in {_days(days)}"
        return line

    if band == TIER_STALLED:
        line = (
            "in progress, no tasks checked yet" if feature.tasks_total
            else "in progress, no task list yet"
        )
        return _with_age(line, days)

    if band == TIER_DRAFT:
        return _with_age("drafted, ready to start", days)

    if band == TIER_IDEA:
        return _with_age("idea, not shaped yet", days)

    return feature.status


def rank(features: Iterable[Feature], *, project: str | None = None) -> list[Feature]:
    """Actionable features, ordered by :data:`ORDERING_RULE`.

    ``project`` narrows to one slug, so the same ranking works inside a single
    repo without a second implementation.
    """
    pool = [
        f for f in features
        if tier(f) is not None and (project is None or f.project == project)
    ]
    return sorted(pool, key=rank_key)


def as_dict(feature: Feature) -> dict[str, Any]:
    """JSON-ready row: the reason plus every raw signal behind it."""
    return {
        "project": feature.project,
        "id": feature.feat_id,
        "name": feature.name,
        "status": feature.status,
        "reason": reason(feature),
        "tier": tier(feature),
        "appetite": feature.appetite,
        "confidence": feature.confidence,
        "cycle": feature.cycle,
        "goal": feature.goal,
        "depends_on": list(feature.depends_on),
        "updated": feature.updated,
        "path": feature.path,
        "signals": {
            "blocked_days": feature.blocked_days,
            "blocked_by": feature.blocked_by,
            "tasks_checked": feature.tasks_checked,
            "tasks_total": feature.tasks_total,
            "tasks_remaining": feature.tasks_remaining,
            "days_since_change": feature.days_since_change,
            "stale": feature.is_stale,
        },
    }


# --------------------------------------------------------------------------- #
# Capacity — also pure
# --------------------------------------------------------------------------- #

def capacity_of(features: Iterable[Feature]) -> Capacity:
    """Appetite one project has committed to a cycle.

    A feature with no cycle is *uncommitted*, which is a different thing from
    contributing zero: it is work in flight that nobody has bet on.
    """
    committed = [
        f for f in features
        if f.status in COMMITTABLE_STATUSES and f.cycle
    ]
    uncommitted = [
        f for f in features
        if f.status in COMMITTABLE_STATUSES and not f.cycle
    ]
    counts = Counter(f.appetite for f in committed if f.appetite)
    return Capacity(
        committed=len(committed),
        weight=sum(APPETITE_WEIGHT.get(f.appetite or "", 0.0) for f in committed),
        by_appetite=tuple(sorted(counts.items())),
        large_bets=sum(1 for f in committed if f.appetite == LARGE_APPETITE),
        uncommitted=len(uncommitted),
        unsized=sum(1 for f in committed if not f.appetite),
        cycles=tuple(sorted({str(f.cycle) for f in committed if f.cycle})),
    )


def portfolio_capacity(views: Sequence[ProjectView]) -> PortfolioCapacity:
    """Sum the per-project capacities and apply the Shape Up check across them."""
    cycles: set[str] = set()
    for v in views:
        cycles.update(v.capacity.cycles)
    return PortfolioCapacity(
        committed=sum(v.capacity.committed for v in views),
        weight=sum(v.capacity.weight for v in views),
        large_bets=sum(v.capacity.large_bets for v in views),
        uncommitted=sum(v.capacity.uncommitted for v in views),
        unsized=sum(v.capacity.unsized for v in views),
        projects_committed=sum(1 for v in views if v.capacity.committed),
        cycles=tuple(sorted(cycles)),
    )


# --------------------------------------------------------------------------- #
# Gathering — the only part that touches disk
# --------------------------------------------------------------------------- #

def feature_from_spec(
    spec: Mapping[str, Any],
    project: str,
    *,
    tasks: tuple[int, int] | None = None,
    days_since_change: int | None = None,
    today: date | None = None,
) -> Feature:
    """Build a :class:`Feature` from a spec dict plus its disk-derived signals.

    Pure: the two signals that need the filesystem are parameters, so tests can
    construct any shape without writing files. Every field is coerced, because
    a hand-edited spec can hold anything and one bad frontmatter value must not
    take the whole portfolio down.
    """
    today = today or date.today()
    return Feature(
        project=project,
        feat_id=str(spec.get("id") or "?").upper(),
        name=str(spec.get("name") or "Untitled"),
        status=str(spec.get("status") or "idea"),
        appetite=_opt_str(spec.get("appetite")),
        confidence=_opt_str(spec.get("confidence")),
        cycle=_opt_str(spec.get("cycle")),
        goal=_opt_str(spec.get("goal")),
        blocked_by=_opt_str(spec.get("blocked_by")),
        blocked_days=days_blocked(spec, today=today),
        tasks_checked=tasks[0] if tasks else None,
        tasks_total=tasks[1] if tasks else None,
        days_since_change=days_since_change,
        depends_on=_str_tuple(spec.get("depends_on")),
        updated=_opt_str(spec.get("updated")),
        path=str(spec["_path"]) if spec.get("_path") else None,
    )


def days_blocked(spec: Mapping[str, Any], *, today: date | None = None) -> int | None:
    """Days since ``blocked_at``, or None when it is absent or unparseable.

    Same convention as ``meridian guide``'s ``_stale_blocked_days``, with
    *today* injectable so the ordering can be tested without freezing the clock.
    """
    raw = spec.get("blocked_at")
    if not raw:
        return None
    try:
        return ((today or date.today()) - date.fromisoformat(str(raw))).days
    except (ValueError, TypeError):
        return None


def read_feature(
    spec: Mapping[str, Any],
    project: str,
    *,
    today: date | None = None,
    now: float | None = None,
) -> Feature:
    """:func:`feature_from_spec` with the disk signals filled in."""
    spec_path = Path(str(spec["_path"])) if spec.get("_path") else None
    feat_dir = spec_path.parent if spec_path else None

    tasks = task_progress(feat_dir) if feat_dir else None
    days = _days_since_mtime(
        [p for p in (spec_path, feat_dir / "tasks.md" if feat_dir else None) if p],
        now if now is not None else time.time(),
    )
    return feature_from_spec(
        spec, project, tasks=tasks, days_since_change=days, today=today
    )


def gather(
    entries: Sequence[ProjectEntry],
    *,
    today: date | None = None,
    now: float | None = None,
) -> Portfolio:
    """Read every tracked project once and return everything the views need.

    No repo has to be checked out or current: each project is read straight
    from its ``specs/`` directory.

    A project that cannot be read is reported and skipped — never removed from
    the registry, and never silently dropped, because a repo on an unmounted
    disk still exists. One project failing to read leaves the others ranking,
    which is the whole point of a portfolio view.
    """
    today = today or date.today()
    now = now if now is not None else time.time()

    views: list[ProjectView] = []
    skipped: list[SkippedProject] = []

    for entry in sorted(entries, key=lambda e: e.slug):
        if not entry.exists:
            skipped.append(SkippedProject(entry.slug, str(entry.path), "path not found"))
            continue
        specs_path = entry.path / "specs"
        if not specs_path.is_dir():
            skipped.append(SkippedProject(entry.slug, str(entry.path), "no specs/ directory"))
            continue
        try:
            views.append(_read_project(entry, specs_path, today=today, now=now))
        except Exception as e:  # one unreadable repo must not stop the rest
            skipped.append(
                SkippedProject(entry.slug, str(entry.path), f"could not be read ({e})")
            )

    return Portfolio(projects=tuple(views), skipped=tuple(skipped))


def _read_project(
    entry: ProjectEntry, specs_path: Path, *, today: date, now: float
) -> ProjectView:
    # The single pass over this project's specs. Counts, staleness, capacity
    # and the ranking are all derived from this one list — re-reading the
    # directory per view is what makes a ten-project dashboard feel slow.
    specs = all_specs(specs_path)
    features = tuple(read_feature(s, entry.slug, today=today, now=now) for s in specs)

    days = [f.days_since_change for f in features if f.days_since_change is not None]

    return ProjectView(
        slug=entry.slug,
        path=entry.path,
        features=features,
        counts=dict(Counter(f.status for f in features)),
        days_since_change=min(days) if days else None,
        capacity=capacity_of(features),
        # `all_specs` warns on stderr and drops a spec it cannot parse. Counting
        # the files it walked past is how the view says so out loud — a cheap
        # directory listing, not a second parse.
        unreadable_specs=max(0, spec_file_count(specs_path) - len(specs)),
    )


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def spec_file_count(specs_path: Path) -> int:
    """How many spec files are on disk, parseable or not.

    Compared against the number of specs that actually loaded, this is how a
    view says "one of these did not parse" out loud instead of quietly showing
    a shorter list.
    """
    try:
        return sum(1 for _ in specs_path.glob("FEAT-*/spec.md"))
    except OSError:  # pragma: no cover - raced deletion
        return 0


def days_since_change(feat_dir: Path, *, now: float | None = None) -> int | None:
    """Days since ``spec.md`` or ``tasks.md`` in *feat_dir* last changed.

    FEAT-028 made this public so the report's staleness heat and the terminal
    dashboard's ``chg`` column derive from the same mtimes. See
    :data:`STALENESS_NOTE` for what this number does *not* mean.
    """
    return _days_since_mtime(
        [feat_dir / "spec.md", feat_dir / "tasks.md"],
        now if now is not None else time.time(),
    )


def _days_since_mtime(paths: Iterable[Path], now: float) -> int | None:
    newest: float | None = None
    for p in paths:
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if newest is None or mtime > newest:
            newest = mtime
    if newest is None:
        return None
    return max(0, int((now - newest) // _SECONDS_PER_DAY))


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    # "~" is the YAML null the spec template writes for an unset goal.
    return text if text and text != "~" else None


def _str_tuple(value: Any) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, str):
        return (value,)
    try:
        return tuple(str(v) for v in value)
    except TypeError:  # a scalar where the schema expects a list
        return (str(value),)


def _days(n: int | None) -> str:
    if n is None:  # pragma: no cover - callers guard
        return "an unknown number of days"
    return f"{n} day" if n == 1 else f"{n} days"


def _with_age(line: str, days: int | None) -> str:
    """Append how long ago anything last changed, phrased for the distance."""
    if days is None:
        return line
    if days == 0:
        return f"{line}, changed today"
    if days == 1:
        return f"{line}, changed yesterday"
    if days >= STALE_DAYS:
        return f"{line}, nothing changed in {_days(days)}"
    return f"{line}, last change {_days(days)} ago"


def clip(text: str, width: int) -> str:
    """Collapse whitespace and shorten to *width*, marking the cut."""
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[: width - 1].rstrip() + "…"
