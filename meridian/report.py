"""Static HTML report over one project's specs (FEAT-028).

Two jobs live here, and the split matters:

:func:`build_payload` is the **contract** — the exact dict
``meridian status --json`` emits. It was inlined in ``cli.py`` until FEAT-028,
where two copies of it would have been the obvious way to build a report and
the obvious way to let the report and the CLI drift apart. Every skill that
shells out to ``status --json`` depends on this shape, so adding or renaming a
key here is a breaking change.

:func:`build_report_payload` is the **superset** the HTML consumes. It calls
``build_payload`` and appends sibling keys — goals, columns, edges, per-feature
signals. It never touches the ``features`` list it was handed, which is what
lets both consumers read one payload without the report's needs leaking into
the CLI's contract.

Deliberately absent: any import of ``meridian.search`` or ``meridian.index``.
The vector store is global and shared across every Meridian install (STEERING),
and a read-only rendering command has no business opening it. Keeping it out
also means ``meridian report`` imports without the lancedb native extension.
"""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Any

from meridian import __version__, portfolio
from meridian.specs import all_specs, atomic_write, read_goals, task_progress

# ── Presentation constants ────────────────────────────────────────────────── #

#: (frontmatter status, short column header). The terminal dashboard's columns
#: and the report's kanban columns are the same list by construction — AC4
#: requires them to match, and two tuples in two modules would not stay matched.
#: Headers are kept short because the terminal table has to fit 80 columns.
#:
#: ``abandoned`` is intentionally absent. It is a real status in
#: ``specs.VALID_STATUSES`` but not a column anyone works out of, so the report
#: renders those features in a collapsed section below the board. Dropping them
#: entirely would be the same silent-omission bug ``_project_json`` avoids by
#: keeping unreadable projects in the payload.
STATUS_COLUMNS = (
    ("idea", "idea"),
    ("draft", "draft"),
    ("in-progress", "prog"),
    ("blocked", "blkd"),
    ("done", "done"),
    ("in-production", "prod"),
)

#: Where `meridian report` writes unless `--out` says otherwise. Relative to
#: the project root, and git-ignored — the report is derived from tracked specs,
#: so committing it would only produce merge conflicts on a generated file.
DEFAULT_OUT_RELATIVE = Path("specs") / ".meridian" / "report.html"

#: The template carries this token exactly once, inside a `<script>` block:
#:     const DATA = /*__MERIDIAN_PAYLOAD__*/null/*__END_MERIDIAN_PAYLOAD__*/;
#: A sentinel comment rather than `str.format` or `string.Template`, because the
#: template is full of CSS braces and `$` is legal in JS identifiers — both of
#: those substitution schemes would eat parts of the page. Keeping a valid
#: `null` default means the template file is itself a loadable HTML page and can
#: be opened during development without running the CLI.
PAYLOAD_START = "/*__MERIDIAN_PAYLOAD__*/"
PAYLOAD_END = "/*__END_MERIDIAN_PAYLOAD__*/"

TEMPLATE_PACKAGE = "meridian"
TEMPLATE_NAME = "report.html.tmpl"


# ── The shared CLI contract ───────────────────────────────────────────────── #

def build_payload(cfg, *, specs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The payload ``meridian status --json`` emits, for one project.

    Frozen by FEAT-028's AC2: ``status --json`` and the HTML report both call
    this, and a test asserts the CLI's stdout equals this dict round-tripped
    through JSON. Note ``goal`` is passed through **raw** — ``'~'`` stays
    ``'~'`` — because that is what the shipped CLI emits and normalising it
    here would silently change a documented output. The report normalises it
    one layer up, in ``signals[id].goal_key``.

    *specs* lets a caller that has already read the specs directory hand the
    list in rather than paying for a second walk. It must be the output of
    ``all_specs`` — the ``_path`` key is required.
    """
    if specs is None:
        specs = all_specs(cfg.specs_path)
    return {
        "project": cfg.project,
        "features": [
            {
                "id": str(s.get("id", "")).upper(),
                "name": s.get("name"),
                "status": s.get("status", "idea"),
                "appetite": s.get("appetite"),
                "confidence": s.get("confidence"),
                "cycle": s.get("cycle"),
                "goal": s.get("goal"),
                "updated": s.get("updated"),
                "depends_on": s.get("depends_on") or [],
                "enables": s.get("enables") or [],
                "blocked_by": s.get("blocked_by"),
                "tasks": (
                    {"checked": tp[0], "total": tp[1]}
                    if (tp := task_progress(Path(str(s["_path"])).parent)) else None
                ),
            }
            for s in specs
        ],
    }


# ── Dependency graph ──────────────────────────────────────────────────────── #

def _norm_id(value: Any) -> str:
    """``feat-028`` and ``FEAT-028`` are the same feature.

    Frontmatter carries the lowercase form and the payload carries the upper,
    so any matching that skips this silently reports every edge as dangling.
    """
    return str(value).strip().upper()


def dependency_edges(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Resolve ``depends_on``/``enables`` into a deduplicated edge list.

    Every edge is stored in one canonical direction — ``from`` depends on
    ``to`` — so ``A: depends_on [B]`` and ``B: enables [A]`` describe the same
    relationship and produce one edge, not two overlapping ones. ``kind``
    records which side declared it, preferring the dependent's own
    ``depends_on`` when both did.

    An edge whose ``to`` is not a known feature is marked ``dangling`` and
    **kept** (AC3). A typo'd dependency that vanishes from the graph is worse
    than one drawn oddly: the graph is the only place it would ever be noticed.
    """
    known = {_norm_id(f["id"]) for f in features}
    edges: dict[tuple[str, str], dict[str, Any]] = {}

    def add(dependent: str, dependency: str, kind: str) -> None:
        if dependent == dependency:  # a self-dependency is noise, not a relationship
            return
        key = (dependent, dependency)
        existing = edges.get(key)
        if existing is not None:
            # Both sides declared it. `depends_on` wins: it is the dependent's
            # own statement about what it needs, and it is the direction the
            # rank layout walks.
            if kind == "depends_on":
                existing["kind"] = "depends_on"
            return
        edges[key] = {
            "from": dependent,
            "to": dependency,
            "kind": kind,
            "dangling": dependency not in known,
        }

    for feature in features:
        fid = _norm_id(feature["id"])
        for target in feature.get("depends_on") or []:
            add(fid, _norm_id(target), "depends_on")
        # `A enables B` means B depends on A — same edge, stated from the other end.
        for target in feature.get("enables") or []:
            add(_norm_id(target), fid, "enables")

    return [edges[k] for k in sorted(edges)]


def rank_nodes(
    features: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> dict[str, int]:
    """Longest dependency depth per feature — the graph's x-column.

    Rank 0 is a feature that depends on nothing; rank N depends on something of
    rank N-1. Deterministic and columnar by design: the spec's risk table names
    graph layout as the one place this feature quietly becomes a two-week job,
    and a force-directed simulation is exactly how that happens.

    Iterative rather than recursive, with a visiting set, so a ``depends_on``
    cycle terminates with finite ranks instead of blowing the stack. A cycle is
    a bug in the specs, but a renderer is the wrong place to discover it by
    crashing.
    """
    ids = [_norm_id(f["id"]) for f in features]
    deps: dict[str, list[str]] = {i: [] for i in ids}
    for edge in edges:
        if edge["dangling"]:
            continue
        src, dst = edge["from"], edge["to"]
        if src in deps and dst in deps:
            deps[src].append(dst)

    ranks: dict[str, int] = {}
    for start in ids:
        if start in ranks:
            continue
        visiting: set[str] = set()
        stack: list[tuple[str, bool]] = [(start, False)]
        while stack:
            node, expanded = stack.pop()
            if expanded:
                visiting.discard(node)
                ranks[node] = max(
                    (ranks[d] + 1 for d in deps[node] if d in ranks), default=0
                )
                continue
            if node in visiting:
                # Cycle. Break it here with a provisional 0; the expansion pass
                # still runs and yields a finite rank for every node involved.
                ranks.setdefault(node, 0)
                continue
            if node in ranks:
                continue
            visiting.add(node)
            stack.append((node, True))
            for dep in deps[node]:
                if dep not in ranks:
                    stack.append((dep, False))

    return ranks


# ── The report superset ───────────────────────────────────────────────────── #

def _goal_key(raw: Any) -> str | None:
    """Normalise a goal reference for grouping.

    ``'~'`` is Meridian's "deliberately ungoaled" marker and an empty string is
    an unset field; both belong in the matrix's *ungoaled* row rather than
    inventing a goal named ``~``.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if text in ("", "~", "—"):
        return None
    return text


def build_report_payload(cfg, *, now: float | None = None) -> dict[str, Any]:
    """:func:`build_payload` plus everything only the HTML needs.

    ``features`` is passed through untouched — the report's extras live in
    sibling keys (``signals`` keyed by feature ID, ``edges``, ``goals``,
    ``columns``) precisely so the contract AC2 pins stays pinned. If a value
    belongs *per feature* and the CLI does not already emit it, it goes in
    ``signals``, never into a feature dict.
    """
    now = now if now is not None else time.time()
    specs_path = Path(cfg.specs_path)

    # One walk of the specs directory, shared with build_payload. The feature
    # dicts deliberately carry no `_path`, so staleness is read here from the
    # specs list rather than by globbing a directory name back out of an ID.
    specs = all_specs(specs_path)
    payload = build_payload(cfg, specs=specs)
    features = payload["features"]

    edges = dependency_edges(features)
    ranks = rank_nodes(features, edges)

    feat_dirs = {
        _norm_id(s.get("id", "")): Path(str(s["_path"])).parent
        for s in specs
        if s.get("_path")
    }

    signals: dict[str, Any] = {}
    for feature in features:
        fid = _norm_id(feature["id"])
        feat_dir = feat_dirs.get(fid)
        days = portfolio.days_since_change(feat_dir, now=now) if feat_dir else None
        signals[fid] = {
            "days_since_change": days,
            "stale": days is not None and days >= portfolio.STALE_DAYS,
            "goal_key": _goal_key(feature.get("goal")),
            "rank": ranks.get(fid, 0),
        }

    loaded = len(features)
    on_disk = portfolio.spec_file_count(specs_path)

    return {
        **payload,
        "generated_at": datetime.fromtimestamp(now, tz=UTC).isoformat(
            timespec="seconds"
        ),
        "meridian_version": __version__,
        "stale_days": portfolio.STALE_DAYS,
        # The caveat travels with the number. A staleness figure whose limits
        # are hidden gets trusted further than it deserves — the terminal
        # dashboard prints this note for the same reason.
        "staleness_note": portfolio.STALENESS_NOTE,
        "columns": [{"status": s, "label": label} for s, label in STATUS_COLUMNS],
        "goals": read_goals(specs_path),
        "signals": signals,
        "edges": edges,
        # `all_specs` warns on stderr and drops a spec it cannot parse. In a
        # browser there is no stderr to notice, so the count travels into the
        # page and the footer says so.
        "unreadable_specs": max(0, on_disk - loaded),
    }


# ── Rendering ─────────────────────────────────────────────────────────────── #

def load_template() -> str:
    """Read the packaged template.

    ``importlib.resources`` rather than ``Path(__file__).parent`` so the lookup
    works from a zip-imported install. A ``__file__``-relative path passes every
    test in the source tree and fails only once installed, which is the failure
    AC9 exists to catch.
    """
    return (files(TEMPLATE_PACKAGE) / "templates" / TEMPLATE_NAME).read_text(
        encoding="utf-8"
    )


def render_html(payload: dict[str, Any], template: str | None = None) -> str:
    """Embed *payload* in the template and return the finished page.

    The JSON is escaped for the one context that can break out of a ``<script>``
    block: a literal ``</script`` anywhere in the data — a feature name, a
    ``blocked_by`` reason, a goal title — would end the block early and spill
    the rest of the payload into the document as markup. ``<!--`` and ``-->``
    get the same treatment because an HTML comment opened inside a script block
    swallows the code that follows it.
    """
    if template is None:
        template = load_template()

    if PAYLOAD_START not in template or PAYLOAD_END not in template:
        raise ValueError(
            f"Template is missing the payload sentinel "
            f"({PAYLOAD_START} ... {PAYLOAD_END})"
        )

    encoded = (
        json.dumps(payload, separators=(",", ":"), default=str)
        .replace("</", "<\\/")
        .replace("<!--", "<\\!--")
        .replace("-->", "--\\>")
        .replace(" ", "\\u2028")  # JS line terminators, legal in JSON strings
        .replace(" ", "\\u2029")
    )

    head, _, rest = template.partition(PAYLOAD_START)
    _, _, tail = rest.partition(PAYLOAD_END)
    return f"{head}{encoded}{tail}"


def write_report(cfg, out_path: Path, *, now: float | None = None) -> Path:
    """Build, render and atomically write the report. Returns the written path.

    No caching layer anywhere: every call re-reads ``all_specs()``, so the page
    cannot show a state the specs no longer hold (AC7). The write goes through
    ``specs.atomic_write`` so a browser reloading mid-write sees the old page or
    the new one, never a half-written document.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(out_path, render_html(build_report_payload(cfg, now=now)))
    return out_path
