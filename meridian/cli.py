import logging
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import typer
from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from meridian import __version__
from meridian.config import load_config, slugify_project
from meridian.skilldist import open_skill_prs, sync_all, sync_skills
from meridian.specs import (
    APPETITE_LABELS,
    APPETITE_VALUES,
    CONFIDENCE_VALUES,
    VALID_STATUSES,
    AmbiguousFeatureError,
    all_specs,
    create_spec,
    edit_spec,
    find_spec,
    load_spec,
    rebuild_registry,
    task_progress,
    transition_spec,
)

# P6: set MERIDIAN_DEBUG=1 to see library-level warnings (rerank failures, registry writes, etc.)
if os.environ.get("MERIDIAN_DEBUG"):
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(name)s [%(levelname)s] %(message)s",
    )

app = typer.Typer(
    name="meridian",
    help="Navigate your codebase with purpose.",
    no_args_is_help=True,
    invoke_without_command=True,
)


# P2: --version flag
def _version_callback(value: bool) -> None:
    if value:
        console_out = Console()
        console_out.print(f"meridian {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool | None = typer.Option(
        None,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Navigate your codebase with purpose."""

console = Console()

# ── Spec lookup helper ────────────────────────────────────────────────────── #

def _find_spec(cfg, feature_id: str, *, silent: bool = False) -> Path | None:
    """Locate spec.md for a feature. Exits with error unless silent=True."""
    try:
        found = find_spec(cfg.specs_path, feature_id)
    except (ValueError, AmbiguousFeatureError) as e:
        if silent:
            return None
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    if found is None:
        if silent:
            return None
        console.print(
            f"[red]Error:[/red] No spec found for [bold]{feature_id.upper()}[/bold]."
        )
        raise typer.Exit(1)
    return found

STATUS_STYLE: dict[str, str] = {
    "idea":          "dim",
    "draft":         "blue",
    "in-progress":   "yellow",
    "blocked":       "bold red",
    "done":          "green",
    "in-production": "bold green",
    "abandoned":     "dim red",
}


def _styled_status(status: str) -> Text:
    style = STATUS_STYLE.get(status, "")
    return Text(status, style=style)


def _config():
    try:
        return load_config()
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


# ── Cycle capacity helpers ────────────────────────────────────────────────── #

# Weighted effort units (arbitrary but proportional to appetite labels)
_APPETITE_WEIGHT: dict[str, float] = {"xs": 0.5, "s": 1.0, "m": 3.0, "l": 6.0}
_CYCLE_WARN_THRESHOLD = 12.0  # ≈ 2 full "l" features


def _cycle_capacity_summary(specs_dir: Path, cycle_id: str) -> tuple[str, bool]:
    """Return (summary_line, is_overloaded) for a cycle after an assignment change.

    Only counts committed features (draft/in-progress/blocked). Idea-stage features
    are excluded — they haven't been shaped yet so their appetite isn't reliable.
    """
    active_statuses = {"draft", "in-progress", "blocked"}
    specs = all_specs(specs_dir)
    in_cycle = [
        s for s in specs
        if s.get("cycle") == cycle_id and s.get("status", "idea") in active_statuses
    ]
    if not in_cycle:
        return (f"Cycle [bold]{cycle_id}[/bold]: 0 features", False)

    weight = sum(_APPETITE_WEIGHT.get(s.get("appetite") or "", 0.0) for s in in_cycle)
    counts: dict[str, int] = {}
    for s in in_cycle:
        a = s.get("appetite") or "?"
        counts[a] = counts.get(a, 0) + 1
    parts = ", ".join(f"{v}×{k}" for k, v in sorted(counts.items()))
    summary = f"Cycle [bold]{cycle_id}[/bold]: {len(in_cycle)} features ({parts})"
    return (summary, weight > _CYCLE_WARN_THRESHOLD)


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #

# (frontmatter status, column header) — headers kept short so the dashboard
# fits a normal terminal without squeezing the project name.
_STATUS_COLUMNS = (
    ("idea", "idea"),
    ("draft", "draft"),
    ("in-progress", "prog"),
    ("blocked", "blkd"),
    ("done", "done"),
    ("in-production", "prod"),
)


def _emit_json(payload) -> None:
    """Print a JSON document and exit 0.

    FEAT-015: skills shell out to this CLI and then parse Rich's box-drawing
    out of the agent's context window. Structured output means they branch on
    data instead of prose. Written straight to stdout — Rich would wrap and
    colour it.

    Compact rather than indented, measured on this repo's own dashboard:
    table 5,912 bytes, indented JSON 5,876, compact 4,246. Pretty-printing
    gave back none of the saving. Pipe through `python -m json.tool` when a
    human needs to read it.
    """
    import json

    print(json.dumps(payload, separators=(",", ":"), default=str))
    raise typer.Exit(0)


def _tracked_projects():
    """Read the registry, turning an unreadable one into a clear error.

    FEAT-013: a corrupt registry used to read as "no projects tracked", which
    then invited the user to run `register` — the very command that would
    overwrite it. Now it stops, names the file, and points at the backup.
    """
    from meridian.registry import RegistryUnreadableError, all_projects

    try:
        return all_projects()
    except RegistryUnreadableError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


def _project_summary(specs_path: Path) -> dict[str, int]:
    """Count features by status for one project."""
    counts: dict[str, int] = {}
    for spec in all_specs(specs_path):
        key = str(spec.get("status", "idea"))
        counts[key] = counts.get(key, 0) + 1
    return counts


def _status_all() -> None:
    """Cross-project dashboard (FEAT-009).

    The per-repo dashboard cannot answer "what is in flight everywhere", which
    is the question that actually matters once Meridian is installed in ten
    projects. Reads each tracked repo's specs directly — no repo needs to be
    checked out or current.
    """
    entries = _tracked_projects()
    if not entries:
        console.print(
            "[dim]No projects tracked. Run [bold]meridian register[/bold] in each repo.[/dim]"
        )
        raise typer.Exit(0)

    table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
    # The project name is the row's identity — it must never be the thing that
    # gets truncated, so it is no_wrap with a floor and Purpose absorbs the slack.
    # Explicit widths rather than letting Rich negotiate: a ratio column silently
    # starves the count columns to zero, and no_wrap alone shrinks the project
    # name, which is the row's identity and must stay readable. Purpose is left
    # out entirely — it pushed the table past 80 columns and truncated the
    # headers, and `meridian projects` already shows it.
    table.add_column("Project", no_wrap=True, min_width=20)
    for _label, header in _STATUS_COLUMNS:
        table.add_column(header, justify="right", no_wrap=True, width=5)

    totals: dict[str, int] = {}
    unreadable = []

    for entry in sorted(entries, key=lambda e: e.slug):
        if not entry.exists:
            unreadable.append((entry.slug, "path not found"))
            continue
        specs_path = entry.path / "specs"
        if not specs_path.is_dir():
            unreadable.append((entry.slug, "no specs/ directory"))
            continue

        counts = _project_summary(specs_path)
        for k, v in counts.items():
            totals[k] = totals.get(k, 0) + v

        cells = []
        for label, _header in _STATUS_COLUMNS:
            n = counts.get(label, 0)
            if n == 0:
                cells.append("[dim]·[/dim]")
            elif label == "blocked":
                cells.append(f"[bold red]{n}[/bold red]")
            elif label == "in-progress":
                cells.append(f"[yellow]{n}[/yellow]")
            else:
                cells.append(str(n))
        table.add_row(entry.slug, *cells)

    console.print()
    console.print(table)

    active = totals.get("in-progress", 0)
    blocked = totals.get("blocked", 0)
    summary = f"  [dim]{sum(totals.values())} features across {len(entries)} projects"
    if active:
        summary += f" · [yellow]{active} in progress[/yellow][dim]"
    if blocked:
        summary += f" · [bold red]{blocked} blocked[/bold red][dim]"
    console.print(summary + "[/dim]")

    for slug, why in unreadable:
        console.print(f"  [yellow]⚠[/yellow]  [bold]{slug}[/bold] skipped — {why}")


@app.command()
def status(
    all_projects: bool = typer.Option(
        False, "--all", "-a",
        help="Show every tracked project instead of only this one",
    ),
    as_json: bool = typer.Option(
        False, "--json",
        help="Emit machine-readable JSON instead of a table",
    ),
):
    """Show full feature dashboard with lifecycle states."""
    if all_projects:
        if as_json:
            _emit_json({
                "projects": [
                    {
                        "slug": e.slug,
                        "path": str(e.path),
                        "purpose": e.purpose,
                        "exists": e.exists,
                        "counts": _project_summary(e.path / "specs")
                        if e.exists and (e.path / "specs").is_dir() else None,
                    }
                    for e in sorted(_tracked_projects(), key=lambda e: e.slug)
                ]
            })
        _status_all()
        raise typer.Exit(0)

    if as_json:
        cfg_json = _config()
        _emit_json({
            "project": cfg_json.project,
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
                for s in all_specs(cfg_json.specs_path)
            ],
        })

    cfg = _config()
    specs = all_specs(cfg.specs_path)

    if not specs:
        console.print("[dim]No features found. Run [bold]meridian new[/bold] to capture an idea.[/dim]")
        raise typer.Exit(0)

    # ── Build table ────────────────────────────────────────────────────────
    table = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold",
        pad_edge=False,
    )
    table.add_column("ID", style="bold", min_width=8)
    table.add_column("Name", min_width=28)
    table.add_column("Goal", min_width=10)
    table.add_column("Status", min_width=18)
    table.add_column("App", min_width=4)
    table.add_column("Conf", min_width=4)
    table.add_column("Cycle", min_width=8)
    table.add_column("Updated", min_width=10)

    counts: dict[str, int] = {}
    deps_warnings: list[str] = []

    for s in specs:
        feat_id = str(s.get("id", "?")).upper()
        name = str(s.get("name", "Untitled"))
        goal = str(s.get("goal") or "—")
        status_val = str(s.get("status", "idea"))
        appetite_val = str(s.get("appetite") or "—")
        confidence_val = str(s.get("confidence") or "—")
        cycle_val = str(s.get("cycle") or "—")
        updated = str(s.get("updated", "—"))
        counts[status_val] = counts.get(status_val, 0) + 1

        # Task progress inline with status for in-progress features
        status_text = _styled_status(status_val)
        if status_val == "in-progress":
            spec_path = s.get("_path")
            if spec_path is not None:
                progress = task_progress(Path(spec_path).parent)
                if progress is not None:
                    checked, total = progress
                    pct_style = "green" if checked == total else "yellow"
                    status_text = Text.assemble(
                        _styled_status(status_val),
                        (" [", "dim"),
                        (f"{checked}/{total}", pct_style),
                        ("]", "dim"),
                    )

        # Confidence styling
        conf_style = {"low": "red", "medium": "yellow", "high": "green"}.get(
            s.get("confidence") or "", "dim"
        )
        conf_display = Text(confidence_val, style=conf_style)

        # Typed as the union Rich accepts: the list mixes str and Text, and an
        # untyped list[object] is not assignable to add_row's parameter.
        row: list[str | Text] = [
            feat_id, name, goal, status_text, appetite_val, conf_display, cycle_val, updated,
        ]
        table.add_row(*row)

        # Collect dependency warnings
        depends_on = s.get("depends_on") or []
        enables = s.get("enables") or []
        if depends_on or enables:
            dep_parts = []
            if depends_on:
                dep_parts.append(f"needs {', '.join(str(d).upper() for d in depends_on)}")
            if enables:
                dep_parts.append(f"enables {', '.join(str(e).upper() for e in enables)}")
            deps_warnings.append(f"  [bold]{feat_id}[/bold] — {'; '.join(dep_parts)}")

    console.print()
    console.print("[bold]Meridian — Feature Dashboard[/bold]")
    console.print(table)

    summary_parts = [f"[bold]{v}[/bold] {k}" for k, v in sorted(counts.items())]
    console.print("  " + "  ·  ".join(summary_parts))

    if deps_warnings:
        console.print()
        console.print("  [bold dim]Dependencies[/bold dim]")
        for w in deps_warnings:
            console.print(w)

    # Cycle capacity summary — one line per cycle with load indicator
    cycle_loads: dict[str, list[dict]] = {}
    active_statuses = {"draft", "in-progress", "blocked"}
    for s in specs:
        c = s.get("cycle")
        if c and s.get("status", "idea") in active_statuses:
            cycle_loads.setdefault(c, []).append(s)

    if cycle_loads:
        console.print()
        console.print("  [bold dim]Cycle load[/bold dim]")
        for cycle_id in sorted(cycle_loads):
            cycle_specs = cycle_loads[cycle_id]
            weight = sum(_APPETITE_WEIGHT.get(s.get("appetite") or "", 0.0) for s in cycle_specs)
            counts_a: dict[str, int] = {}
            for s in cycle_specs:
                a = s.get("appetite") or "?"
                counts_a[a] = counts_a.get(a, 0) + 1
            parts = ", ".join(f"{v}×{k}" for k, v in sorted(counts_a.items()))
            overloaded = weight > _CYCLE_WARN_THRESHOLD
            indicator = "[yellow]⚠ [/yellow]" if overloaded else "  "
            console.print(f"{indicator}[bold]{cycle_id}[/bold]  {len(cycle_specs)} features ({parts})")

    console.print()


# --------------------------------------------------------------------------- #
# new
# --------------------------------------------------------------------------- #

@app.command()
def new(
    idea: str = typer.Argument(..., help="Idea text to capture"),
    goal: str | None = typer.Option(None, "--goal", "-g", help="Goal ID to link (e.g. goal-01)"),
    appetite: str | None = typer.Option(
        None, "--appetite", "-a",
        help=f"Time appetite: {' | '.join(APPETITE_VALUES)}",
    ),
):
    """Quick-capture a new idea and write a stub spec."""
    if appetite and appetite not in APPETITE_VALUES:
        console.print(
            f"[red]Error:[/red] Invalid appetite '{appetite}'. "
            f"Valid: {', '.join(APPETITE_VALUES)}"
        )
        raise typer.Exit(1)

    cfg = _config()

    # B6: warn immediately if the referenced goal doesn't exist yet
    if goal:
        goal_file = cfg.specs_path / "goals" / f"{goal}.md"
        if not goal_file.exists():
            console.print(
                f"  [yellow]⚠[/yellow]  Goal [bold]{goal}[/bold] not found in specs/goals/ — "
                "check the ID or run [bold]/goal new[/bold] to create it first. "
                "The spec will still be created with this goal reference."
            )

    spec_path = create_spec(cfg.specs_path, idea, goal, appetite)
    rebuild_registry(cfg.specs_path)

    feat_dir = spec_path.parent
    feat_id = feat_dir.name.split("_")[0]
    console.print(f"[green]✓[/green] Created [bold]{feat_id}[/bold] → {feat_dir.relative_to(cfg.root)}/spec.md")
    if goal:
        console.print(f"  Linked to goal: [blue]{goal}[/blue]")
    if appetite:
        label = APPETITE_LABELS.get(appetite, appetite)
        console.print(f"  Appetite: [blue]{appetite}[/blue] ({label})")
    console.print(
        f"  Run [bold]/spec[/bold] to elaborate, "
        f"or [bold]meridian enrich {feat_id.lower()} <source>[/bold] to add research."
    )


# --------------------------------------------------------------------------- #
# close
# --------------------------------------------------------------------------- #

@app.command()
def close(
    feature_id: str = typer.Argument(..., help="Feature ID (e.g. feat-007 or FEAT-007)"),
    status: str = typer.Option(..., "--status", "-s", help=f"Target status: {', '.join(VALID_STATUSES)}"),
    blocked_by: str | None = typer.Option(None, "--blocked-by", help="Reason or feat ID (required when status=blocked)"),
    abandoned_reason: str | None = typer.Option(None, "--abandoned-reason", help="Why this feature was killed (stored for future revive context)"),
    confidence: str | None = typer.Option(
        None, "--confidence", "-c",
        help=f"Update problem confidence: {' | '.join(CONFIDENCE_VALUES)}",
    ),
):
    """Transition a feature's lifecycle state."""
    cfg = _config()
    spec_path = _find_spec(cfg, feature_id)
    assert spec_path is not None  # _find_spec exits when silent=False

    if status == "blocked" and not blocked_by:
        console.print("[red]Error:[/red] --blocked-by is required when transitioning to 'blocked'.")
        raise typer.Exit(1)

    if confidence and confidence not in CONFIDENCE_VALUES:
        console.print(
            f"[red]Error:[/red] Invalid confidence '{confidence}'. "
            f"Valid: {', '.join(CONFIDENCE_VALUES)}"
        )
        raise typer.Exit(1)

    # B3: collect all extra fields and apply them in a single save via transition_spec
    extra: dict = {}
    if status == "blocked" and blocked_by:
        extra["blocked_by"] = blocked_by
    if status == "abandoned" and abandoned_reason:
        extra["abandoned_reason"] = abandoned_reason
    if confidence:
        extra["confidence"] = confidence

    try:
        data = transition_spec(spec_path, status, extra=extra or None)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    rebuild_registry(cfg.specs_path)
    feat_id_display = data.get("id", feature_id).upper()
    if data.get("_unchanged"):
        # FEAT-015: already in the target state is success, so a retrying agent
        # is not stuck. Say so plainly rather than implying work was done.
        console.print(
            f"[green]✓[/green] [bold]{feat_id_display}[/bold] already [bold]{status}[/bold]"
        )
        raise typer.Exit(0)
    console.print(f"[green]✓[/green] [bold]{feat_id_display}[/bold] → [bold]{status}[/bold]")

    if status == "abandoned" and not abandoned_reason:
        console.print(
            "  [dim]Tip: add [bold]--abandoned-reason[/bold] to record why — "
            "helps if you revive this feature later.[/dim]"
        )

    # FEAT-017: measure drift rather than printing a reminder nobody acts on.
    if status == "done":
        from meridian.drift import assess

        try:
            report = assess(spec_path, cfg.root)
        except Exception:  # pragma: no cover - never block a transition on this
            report = None
        if report is not None and report.criteria:
            _render_drift(report, verbose=False)
        else:
            console.print(
                "  [dim]Review [bold]spec.md[/bold] and update it to reflect what was "
                "actually built — specs drift during implementation.[/dim]"
            )


# --------------------------------------------------------------------------- #
# cycle
# --------------------------------------------------------------------------- #

@app.command()
def cycle(
    feature_id: str = typer.Argument(..., help="Feature ID (e.g. feat-007)"),
    set_cycle: str | None = typer.Option(None, "--set", "-s", help="Assign to a cycle (e.g. 2026-Q2)"),
    clear: bool = typer.Option(False, "--clear", help="Remove from any cycle"),
):
    """Assign or clear a feature's planning cycle (betting table)."""
    cfg = _config()
    feat_id_norm = feature_id.upper()
    spec_path = _find_spec(cfg, feature_id)
    assert spec_path is not None  # _find_spec exits when silent=False
    if not clear and not set_cycle:
        current = load_spec(spec_path).get("cycle") or "none"
        console.print(f"  [bold]{feat_id_norm}[/bold] cycle: [blue]{current}[/blue]")
        return

    # G1: warn on non-standard cycle IDs (typos like "2026Q2" instead of "2026-Q2")
    _CYCLE_PATTERN = re.compile(r"^\d{4}-Q[1-4]$")
    if set_cycle and not _CYCLE_PATTERN.match(set_cycle):
        console.print(
            f"  [dim]Note: [bold]{set_cycle}[/bold] is an unusual cycle format — "
            "expected e.g. [bold]2026-Q2[/bold]. Any string is accepted but check for typos.[/dim]"
        )

    # FEAT-013: locked read-modify-write — an unlocked load/save here raced with
    # `close` and destroyed whole specs.
    with edit_spec(spec_path) as data:
        data["cycle"] = None if clear else set_cycle
    rebuild_registry(cfg.specs_path)

    if clear:
        console.print(f"[green]✓[/green] [bold]{feat_id_norm}[/bold] removed from cycle")
    else:
        assert set_cycle is not None  # only reached when not clear and set_cycle was provided
        console.print(f"[green]✓[/green] [bold]{feat_id_norm}[/bold] → cycle [blue]{set_cycle}[/blue]")
        summary, overloaded = _cycle_capacity_summary(cfg.specs_path, set_cycle)
        if overloaded:
            console.print(f"  [yellow]⚠[/yellow]  {summary}")
            console.print(
                "  [dim]Cycle looks heavy — consider moving some features to icebox "
                "or next cycle. Shape Up recommends ≤2 large bets per cycle.[/dim]"
            )
        else:
            console.print(f"  [dim]{summary}[/dim]")


# --------------------------------------------------------------------------- #
# enrich
# --------------------------------------------------------------------------- #

_STALE_SCREENSHOT_SECONDS = 600  # warn above this, never refuse


def _stdin_is_tty() -> bool:
    """Whether we can prompt the user. A seam: test runners swap sys.stdin out."""
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _resolve_capture(latest_screenshot_flag: bool, from_clipboard: bool) -> str:
    """Turn a capture flag into a concrete image path, reporting what was picked.

    A silently-chosen screenshot is the worst failure mode here, so the resolved
    filename and its age are always printed before anything is embedded.
    """
    from meridian.capture import clipboard_image, latest_screenshot

    if latest_screenshot_flag:
        path, age = latest_screenshot()
        minutes = int(age // 60)
        age_label = f"{minutes}m old" if minutes else "just now"
        console.print(
            f"[dim]Using[/dim] [bold]{path.name}[/bold] [dim]({age_label}) "
            f"from {path.parent}[/dim]"
        )
        if age > _STALE_SCREENSHOT_SECONDS:
            console.print(
                f"[yellow]⚠[/yellow]  that screenshot is {minutes}m old — "
                f"take a fresh one if this is not the right image."
            )
        return str(path)

    # Lowercase, dash-separated: slug_image_name() would otherwise rewrite an
    # ISO "T" to "t", so the name printed here would not match the file on disk.
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    dest = Path(tempfile.gettempdir()) / f"clipboard-{stamp}.png"
    path = clipboard_image(dest)
    console.print(f"[dim]Using clipboard image →[/dim] [bold]{path.name}[/bold]")
    return str(path)


@app.command()
def enrich(
    feature_id: str = typer.Argument(..., help="Feature ID (e.g. feat-007)"),
    source: str | None = typer.Argument(
        None,
        help="Path to PDF/text/image file or URL (omit when using a capture flag)",
    ),
    note: str | None = typer.Option(
        None, "--note", "-n",
        help="Note describing the screenshot (required for image sources)",
    ),
    note_file: Path | None = typer.Option(
        None, "--note-file",
        help="Read the note (and any existing visual reading) from a sidecar file",
    ),
    latest_screenshot: bool = typer.Option(
        False, "--latest-screenshot",
        help="Ingest the newest image from the OS screenshot directory",
    ),
    from_clipboard: bool = typer.Option(
        False, "--from-clipboard",
        help="Ingest the image currently in the clipboard (macOS)",
    ),
    vision: bool = typer.Option(
        False, "--vision/--no-vision",
        help="Fallback: describe the image with the configured Ollama vision model",
    ),
):
    """Ingest a PDF, URL, text file, or annotated screenshot into a feature's research corpus."""
    from meridian.enrich import enrich_feature, ingest_screenshot, is_image_source

    # ── Argument validation, before touching disk ───────────────────────────
    if latest_screenshot and from_clipboard:
        console.print("[red]Error:[/red] --latest-screenshot and --from-clipboard are mutually exclusive.")
        raise typer.Exit(1)
    if (latest_screenshot or from_clipboard) and source:
        flag = "--latest-screenshot" if latest_screenshot else "--from-clipboard"
        console.print(
            f"[red]Error:[/red] pass either a source path or {flag}, not both."
        )
        raise typer.Exit(1)
    if not source and not (latest_screenshot or from_clipboard):
        console.print(
            "[red]Error:[/red] give a source (PDF/URL/text/image path) or use "
            "--latest-screenshot / --from-clipboard."
        )
        raise typer.Exit(1)
    if note is not None and note_file is not None:
        console.print("[red]Error:[/red] pass either --note or --note-file, not both.")
        raise typer.Exit(1)

    cfg = _config()

    # ── Capture ────────────────────────────────────────────────────────────
    if latest_screenshot or from_clipboard:
        try:
            source = _resolve_capture(latest_screenshot, from_clipboard)
        except RuntimeError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1)

    assert source is not None  # validation above guarantees this

    # ── Non-image sources keep the original path, untouched ────────────────
    if not is_image_source(source):
        if note or note_file or vision:
            console.print(
                "[yellow]⚠[/yellow]  --note/--note-file/--vision apply to images only — "
                "ignored for this source."
            )
        with console.status(f"Extracting and embedding [bold]{source}[/bold]…"):
            try:
                result = enrich_feature(cfg, feature_id, source)
            except FileNotFoundError as e:
                console.print(f"[red]Error:[/red] {e}")
                raise typer.Exit(1)
            except RuntimeError as e:
                console.print(f"[red]Error:[/red] {e}")
                raise typer.Exit(1)
        _report_enrich(result)
        return

    # ── Screenshot path: notes are mandatory ───────────────────────────────
    if note is None and note_file is None:
        if not _stdin_is_tty():
            console.print(
                "[red]Error:[/red] an image needs notes to be searchable.\n"
                "  Pass [bold]--note[/bold] \"what is wrong\" or "
                "[bold]--note-file[/bold] <path>."
            )
            raise typer.Exit(1)
        typed = typer.prompt("Note describing this screenshot", default="")
        if not typed.strip():
            console.print("[yellow]Aborted[/yellow] — empty note, nothing was written.")
            raise typer.Exit(1)
        note = typed

    with console.status(f"Embedding notes for [bold]{Path(source).name}[/bold]…"):
        try:
            result = ingest_screenshot(
                cfg, feature_id, source,
                note=note, note_file=note_file, vision=vision,
            )
        except FileNotFoundError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1)
        except RuntimeError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1)

    for warning in result.get("warnings", []):
        console.print(f"[yellow]⚠[/yellow]  {warning}")
    _report_enrich(result)


def _report_enrich(result: dict) -> None:
    """Print the success (or 0-chunk) line for either enrich path."""
    chunks = result["chunks"]
    target = result["source"]
    if result.get("sidecar"):
        target = f"{result['source']} + {result['sidecar']}"
    described = f" · described by {result['described_by']}" if result.get("described_by") else ""

    if chunks == 0:
        console.print(
            f"[yellow]⚠[/yellow]  [bold]{result['feat_id']}[/bold] ← {target} "
            f"([dim]0 chunks — source may be too short or empty[/dim])"
        )
    else:
        console.print(
            f"[green]✓[/green] [bold]{result['feat_id']}[/bold] ← {target} "
            f"([dim]{chunks} chunks embedded{described}[/dim])"
        )


# --------------------------------------------------------------------------- #
# search
# --------------------------------------------------------------------------- #

@app.command()
def search(
    query: str = typer.Argument(..., help="Natural language search query"),
    feat: str | None = typer.Option(None, "--feat", "-f", help="Filter to a specific feature ID"),
    limit: int = typer.Option(5, "--limit", "-n", help="Max results to return"),
    no_rerank: bool = typer.Option(False, "--no-rerank", help="Skip BGE reranker (faster)"),
    all_projects: bool = typer.Option(
        False, "--all-projects",
        help="Search every Meridian project's research, not just this one",
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON instead of a report",
    ),
):
    """Semantic search across this project's enriched research."""
    from meridian.enrich import LegacyIndexError
    from meridian.search import _reranker_available, result_label, semantic_search
    cfg = _config()

    rerank = not no_rerank
    reranker_note = ""
    if rerank and not _reranker_available():
        rerank = False
        reranker_note = " [dim](no reranker — install sentence-transformers for better ranking)[/dim]"

    with console.status(f"Searching: [bold]{query}[/bold]…"):
        try:
            results = semantic_search(
                cfg, query,
                feat_id_filter=feat.upper() if feat else None,
                limit=limit,
                rerank=rerank,
                all_projects=all_projects,
            )
        except LegacyIndexError as e:
            # Not a failure of this query — the index just predates per-project
            # scoping. Exit 0 with the remediation, so scripts and skills that
            # shell out don't treat a migration as a crash.
            console.print(f"[yellow]⚠[/yellow]  {e}")
            raise typer.Exit(0)
        except RuntimeError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1)

    if as_json:
        _emit_json({
            "query": query,
            "project": None if all_projects else cfg.project,
            "results": [
                {
                    "project": r.get("project"),
                    "feat_id": r.get("feat_id"),
                    "label": result_label(r, cfg),
                    "source_name": r.get("source_name"),
                    "chunk_idx": r.get("chunk_idx"),
                    "score": r.get("rerank_score", r.get("_distance")),
                    "text": r.get("text"),
                }
                for r in results
            ],
        })

    if not results:
        scope_hint = (
            "" if all_projects
            else f" [dim]Searching [bold]{cfg.project}[/bold] only — add --all-projects to widen.[/dim]"
        )
        console.print(
            "[dim]No results. Run [bold]meridian enrich <feat-id> <source>[/bold] to index research.[/dim]"
            + scope_hint
        )
        raise typer.Exit(0)

    scope_note = " [dim](all projects)[/dim]" if all_projects else ""
    console.print(f'\n[bold]Results for[/bold] "{query}"{scope_note}{reranker_note}\n')
    for i, r in enumerate(results, 1):
        score = r.get("rerank_score", r.get("_distance"))
        score_str = f"  [dim]score {score:.3f}[/dim]" if isinstance(score, float) else ""
        preview = r["text"][:200].replace("\n", " ").strip()
        name = result_label(r, cfg)
        console.print(
            f"[bold]{i}.[/bold] [blue]{name}[/blue] "
            f"[dim]{r['source_name']} ·chunk {r['chunk_idx']}[/dim]{score_str}"
        )
        console.print(f"   {preview}")
        console.print()



# --------------------------------------------------------------------------- #
# index
# --------------------------------------------------------------------------- #

@app.command()
def index(
    vectors_only: bool = typer.Option(
        False, "--vectors-only",
        help="Rebuild only this project's vectors; leave REGISTRY.md untouched",
    ),
):
    """Rebuild the LanceDB vector index and refresh REGISTRY.md."""
    from meridian.enrich import reindex_all
    cfg = _config()
    if not vectors_only:
        rebuild_registry(cfg.specs_path)
        console.print("[green]✓[/green] REGISTRY.md rebuilt.")
    with console.status("Re-embedding all sources…"):
        try:
            result = reindex_all(cfg)
            console.print(
                f"[green]✓[/green] Index rebuilt for [bold]{cfg.project}[/bold] — "
                f"[bold]{result['sources']}[/bold] sources, "
                f"[bold]{result['chunks']}[/bold] chunks."
            )
            if result.get("migrated"):
                console.print(
                    "[yellow]⚠[/yellow]  The old index had no project column and was "
                    "recreated. Other Meridian projects' chunks were dropped with it — "
                    "run [bold]meridian index --vectors-only[/bold] once in each to "
                    "repopulate [dim](sources/ is the source of truth, so nothing is "
                    "lost; --vectors-only leaves their REGISTRY.md untouched)[/dim]."
                )
        except RuntimeError as e:
            # FEAT-013: this used to print a reassuring message and exit 0 while
            # the corpus had already been deleted. Embedding now happens before
            # any delete, so the existing rows really are intact — and the exit
            # code says something failed, so a wrapper or agent can see it.
            console.print(f"[red]Error:[/red] {e}")
            console.print(
                "  [dim]Index unchanged — existing chunks were left in place.[/dim]"
            )
            raise typer.Exit(1)


# --------------------------------------------------------------------------- #
# drift  — do the acceptance criteria still describe the code? (FEAT-017)
# --------------------------------------------------------------------------- #

def _render_drift(report, *, verbose: bool = True) -> int:
    """Print a drift report. Returns the number of suspicious criteria."""
    if not report.criteria:
        console.print(
            f"  [dim]{report.feat_id} has no acceptance criteria to check.[/dim]"
        )
        return 0

    if not report.changed_files:
        console.print(
            f"  [yellow]⚠[/yellow]  No changes against [bold]{report.base}[/bold] — "
            "nothing to compare the criteria to."
        )
        return 0

    if not report.on_feature_branch:
        # Comparing one feature's criteria against another feature's diff
        # produces confident nonsense, so refuse rather than mislead.
        console.print(
            f"  [yellow]⚠[/yellow]  Current branch is [bold]{report.branch}[/bold], "
            f"which does not look like {report.feat_id}'s branch."
        )
        console.print(
            f"  [dim]Check out the branch that built {report.feat_id} — comparing its "
            "criteria against unrelated changes says nothing.[/dim]"
        )
        return 0

    uncovered = report.uncovered
    checkable = report.checkable

    if uncovered:
        console.print(
            f"  [yellow]⚠[/yellow]  {len(uncovered)} of {len(checkable)} checkable "
            f"criteria name nothing found in this branch's diff:"
        )
        for criterion in uncovered:
            refs = ", ".join(f"[cyan]{r}[/cyan]" for r in criterion.refs)
            console.print(f"     [bold]{criterion.id}[/bold]  {criterion.text[:88]}")
            console.print(f"        [dim]looked for:[/dim] {refs}")
    else:
        console.print(
            f"  [green]✓[/green] All {len(checkable)} checkable criteria reference "
            f"something this branch touched."
        )

    if verbose and report.unjudgeable:
        console.print(
            f"  [dim]{len(report.unjudgeable)} criteria name nothing concrete and "
            "cannot be checked automatically.[/dim]"
        )
    if uncovered:
        console.print(
            "  [dim]A heuristic, not a verdict — an AC can be satisfied by code that "
            "uses different words. Read the ones listed.[/dim]"
        )
    return len(uncovered)


@app.command()
def drift(
    feature_id: str = typer.Argument(..., help="Feature ID (e.g. feat-013)"),
    base: str = typer.Option("main", "--base", "-b", help="Branch to diff against"),
    as_json: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON instead of a report",
    ),
) -> None:
    """Check whether a feature's acceptance criteria match what its branch changed.

    Meridian's premise is that a spec stays true; this is the first thing that
    actually measures it. Each AC names functions, files and flags in backticks —
    if none of them appears anywhere in the diff, the AC is worth re-reading.

    Deliberately a heuristic. It reliably catches the common failure: an AC
    written during planning, never built, never removed from the spec.
    """
    from meridian.drift import assess

    cfg = _config()
    spec_path = _find_spec(cfg, feature_id)
    assert spec_path is not None  # _find_spec exits when silent=False

    report = assess(spec_path, cfg.root, base=base)

    if as_json:
        _emit_json({
            "feat_id": report.feat_id,
            "base": report.base,
            "changed_files": report.changed_files,
            "criteria": [
                {
                    "id": c.id,
                    "text": c.text,
                    "refs": c.refs,
                    "hits": c.hits,
                    "covered": c.covered,
                    "checkable": c.checkable,
                }
                for c in report.criteria
            ],
            "uncovered": [c.id for c in report.uncovered],
        })

    console.print()
    console.print(
        f"  [bold]{report.feat_id}[/bold] — {len(report.criteria)} criteria vs "
        f"{len(report.changed_files)} changed file(s) against [bold]{base}[/bold]"
    )
    console.print()
    _render_drift(report)
    console.print()


# --------------------------------------------------------------------------- #
# transition  (git hook helper)
# --------------------------------------------------------------------------- #

@app.command()
def transition(
    from_merge: str = typer.Option(..., "--from-merge", help="Branch name that was merged"),
):
    """Auto-transition features to in-production after a merge."""
    cfg = _config()
    match = re.search(r"feat-(\d+)", from_merge, re.IGNORECASE)
    if not match:
        console.print(f"[dim]No FEAT ID found in branch name '{from_merge}'. Nothing to transition.[/dim]")
        console.print(
            "  [dim]Tip: name branches [bold]feat-NNN/slug[/bold] (e.g. feat-007/add-search) "
            "so auto-transition works on merge.[/dim]"
        )
        raise typer.Exit(0)

    feat_id = f"FEAT-{match.group(1).zfill(3)}"
    spec_path = _find_spec(cfg, feat_id, silent=True)
    if spec_path is None:
        console.print(f"[dim]{feat_id} not found in specs. Nothing to transition.[/dim]")
        raise typer.Exit(0)

    try:
        transition_spec(spec_path, "in-production")
        rebuild_registry(cfg.specs_path)
        console.print(f"[green]✓[/green] [bold]{feat_id}[/bold] → [bold]in-production[/bold] (merged: {from_merge})")
    except ValueError as e:
        console.print(f"[yellow]Notice:[/yellow] {e}")


# --------------------------------------------------------------------------- #
# revive  — convenience alias for transitioning abandoned → idea
# --------------------------------------------------------------------------- #

@app.command()
def revive(
    feature_id: str = typer.Argument(..., help="Feature ID to revive (must be abandoned)"),
):
    """Revive an abandoned feature — returns it to idea state.

    Equivalent to `meridian close <id> --status idea` but semantically clearer.
    The previous abandoned_reason is preserved and printed as a reminder.
    """
    cfg = _config()
    spec_path = _find_spec(cfg, feature_id)
    assert spec_path is not None  # _find_spec exits when silent=False

    try:
        data = transition_spec(spec_path, "idea")
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    rebuild_registry(cfg.specs_path)
    feat_id_display = str(data.get("id", feature_id)).upper()
    if data.get("_unchanged"):
        # FEAT-015: already in the target state — say so rather than implying a
        # revival happened. Reviving something that was never abandoned is a
        # no-op, not an error.
        console.print(f"[green]✓[/green] [bold]{feat_id_display}[/bold] is already [bold]idea[/bold]")
        raise typer.Exit(0)
    console.print(f"[green]✓[/green] [bold]{feat_id_display}[/bold] revived → [bold]idea[/bold]")

    if data.get("abandoned_reason"):
        console.print(
            f"  [dim]Previous abandonment reason: {data['abandoned_reason']}[/dim]"
        )
    console.print(
        f"  Run [bold]/spec {feat_id_display.lower()}[/bold] to re-elaborate from scratch, "
        "or [bold]/tasks[/bold] if the spec is still valid."
    )


# --------------------------------------------------------------------------- #
# guide  — dynamic project workflow advisor
# --------------------------------------------------------------------------- #

@app.command()
def guide(
    as_json: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON instead of a report",
    ),
):
    """Show what's set up in this project and what to do next."""
    from meridian.guide import first_action, run_guide

    cfg = _config()
    steps = run_guide(cfg)

    if as_json:
        _emit_json({
            "project": cfg.project,
            "steps": [
                {
                    "number": s.number,
                    "title": s.title,
                    "status": s.status,
                    "detail": s.detail,
                    "next_action": s.next_action,
                }
                for s in steps
            ],
            "next_action": first_action(steps),
        })

    STATUS_ICON = {"ok": "[green]✅[/green]", "warn": "[yellow]⚠️ [/yellow]", "error": "[red]❌[/red]"}
    STATUS_LABEL = {"ok": "green", "warn": "yellow", "error": "red"}

    console.print()
    console.rule("[bold]Meridian Project Guide[/bold]")

    for step in steps:
        icon = STATUS_ICON[step.status]
        color = STATUS_LABEL[step.status]

        console.print()
        console.print(
            f"  [bold]Step {step.number} · {step.title}[/bold]  {icon}"
        )
        console.print(f"  [dim]{step.subtitle}[/dim]")
        console.print(f"  [{color}]{step.detail}[/{color}]")

        if step.items:
            for item in step.items:
                console.print(f"    [dim]·[/dim] {item}")

        if step.next_action:
            console.print(f"  [bold]→[/bold] {step.next_action}")

    console.print()
    console.rule()

    action = first_action(steps)
    if action:
        console.print(f"\n  [bold]Start here →[/bold] {action}\n")
    else:
        console.print("\n  [bold green]Project fully set up — you're good to go! 🚀[/bold green]\n")


# --------------------------------------------------------------------------- #
# init  — bootstrap a new project
# --------------------------------------------------------------------------- #

@app.command(name="init")
def init_project(
    path: str | None = typer.Option(
        None, "--path", "-p",
        help="Project root to initialise (default: current directory).",
    ),
    force: bool = typer.Option(
        False, "--force",
        help="Overwrite existing files if already initialised.",
    ),
) -> None:
    """Bootstrap Meridian in a new project.

    Creates .meridian.toml, the specs/ directory structure, and copies the
    Claude Code skill files into .claude/commands/meridian/.  Run once per project.
    """
    import shutil

    import meridian as _meridian_pkg

    root = Path(path).resolve() if path else Path.cwd()
    toml_path = root / ".meridian.toml"
    _SKILLS_DIR = Path(_meridian_pkg.__file__).parent / "skills"

    if toml_path.exists() and not force:
        console.print(
            f"[yellow]Warning:[/yellow] {toml_path} already exists.\n"
            "  Run with [bold]--force[/bold] to overwrite, or skip [bold]meridian init[/bold] "
            "if this project is already set up."
        )
        raise typer.Exit(1)

    console.print()
    console.print(f"  Initialising Meridian in [bold]{root}[/bold]")
    console.print()

    # ── .meridian.toml ─────────────────────────────────────────────────────
    toml_content = (
        "[meridian]\n"
        f'project        = "{slugify_project(root.name)}"'
        "   # scopes this repo's rows in the shared index\n"
        'specs_path     = "specs"\n'
        'lancedb_path   = "~/.meridian/lancedb"\n'
        'ollama_model   = "mxbai-embed-large"\n'
        'reranker_model = "BAAI/bge-reranker-v2-m3"\n'
        'ollama_vision_model = ""   # optional: fallback describer for `enrich --vision`\n'
    )
    toml_path.write_text(toml_content)
    console.print("  [green]✓[/green] .meridian.toml")

    # ── specs/ structure ───────────────────────────────────────────────────
    specs_dir = root / "specs"
    specs_dir.mkdir(exist_ok=True)
    (specs_dir / "goals").mkdir(exist_ok=True)
    (specs_dir / "decisions").mkdir(exist_ok=True)

    templates_src = _SKILLS_DIR / "templates"
    for tmpl in sorted(templates_src.glob("*.md")):
        dest = specs_dir / tmpl.name
        if dest.exists() and not force:
            console.print(f"  [dim]  skip  specs/{tmpl.name} (already exists)[/dim]")
        else:
            shutil.copy2(tmpl, dest)
            console.print(f"  [green]✓[/green] specs/{tmpl.name}")

    console.print("  [green]✓[/green] specs/goals/")
    console.print("  [green]✓[/green] specs/decisions/")

    # ── .claude/commands/meridian/ (skill files, namespaced) ───────────────
    claude_dir = root / ".claude" / "commands" / "meridian"
    claude_dir.mkdir(parents=True, exist_ok=True)

    commands_src = _SKILLS_DIR / "commands"
    for skill in sorted(commands_src.glob("*.md")):
        dest = claude_dir / skill.name
        if dest.exists() and not force:
            console.print(f"  [dim]  skip  .claude/commands/meridian/{skill.name} (already exists)[/dim]")
        else:
            shutil.copy2(skill, dest)

    console.print(f"  [green]✓[/green] .claude/commands/meridian/ ({len(list(commands_src.glob('*.md')))} skills)")

    # ── summary ────────────────────────────────────────────────────────────
    console.print()
    console.print("  [bold green]Meridian initialised. ✓[/bold green]")
    _register_project(root)
    console.print()
    console.print("  [bold]Next steps:[/bold]")
    console.print("  1. Write your north star:         [cyan]/meridian:vision[/cyan]")
    console.print("  2. Fill in AI context:            edit [bold]specs/STEERING.md[/bold]")
    console.print("  3. Create a strategic goal:       [cyan]/meridian:goal new[/cyan]")
    console.print("  4. Capture your first idea:       [cyan]/meridian:idea[/cyan]  or  "
                  "[cyan]meridian new \"idea text\" --appetite m[/cyan]")
    console.print()
    console.print("  [dim]Run [bold]meridian guide[/bold] at any time to check setup status.[/dim]")
    console.print()


# --------------------------------------------------------------------------- #
# register / projects  — multi-project tracking (FEAT-009)
# --------------------------------------------------------------------------- #

def _register_project(root: Path, *, quiet: bool = False) -> None:
    """Record this repo in the global registry.

    Best-effort when called from `init`: a registry write must never be the
    reason project setup fails.
    """
    from meridian.config import slugify_project
    from meridian.registry import derive_purpose, register

    try:
        specs_path = root / "specs"
        purpose = derive_purpose(specs_path, root.name)
        entry = register(slugify_project(root.name), root, purpose)
        if not quiet:
            console.print(
                f"  [green]✓[/green] Tracking as [bold]{entry.slug}[/bold] "
                f"[dim](meridian status --all)[/dim]"
            )
    except Exception as e:  # pragma: no cover - defensive
        console.print(f"  [yellow]⚠[/yellow]  Could not update the project registry: {e}")


@app.command()
def register(
    name: str | None = typer.Option(
        None, "--name", "-n",
        help="Override the project slug (defaults to the repo directory name)",
    ),
    purpose: str | None = typer.Option(
        None, "--purpose", "-p", help="One-line description shown in the dashboard",
    ),
):
    """Track this repo in the global project registry."""
    from meridian.registry import RegistryUnreadableError, derive_purpose
    from meridian.registry import register as register_entry

    cfg = _config()
    slug = (name or cfg.project).strip().lower()
    text = purpose or derive_purpose(cfg.specs_path, cfg.root.name)

    try:
        entry = register_entry(slug, cfg.root, text)
    except RegistryUnreadableError as e:
        # Refusing is the point: writing here is what used to delete every
        # other project.
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] Tracking [bold]{entry.slug}[/bold] → [dim]{entry.path}[/dim]")
    if entry.purpose:
        console.print(f"  {entry.purpose}")
    console.print("  [dim]See everything with [bold]meridian status --all[/bold].[/dim]")


@app.command()
def projects(
    as_json: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON instead of a table",
    ),
):
    """List every tracked project."""
    entries = _tracked_projects()
    if as_json:
        _emit_json({
            "projects": [
                {"slug": e.slug, "path": str(e.path), "purpose": e.purpose,
                 "exists": e.exists}
                for e in entries
            ]
        })
    if not entries:
        console.print(
            "[dim]No projects tracked. Run [bold]meridian register[/bold] in each repo.[/dim]"
        )
        raise typer.Exit(0)

    table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
    table.add_column("Project")
    table.add_column("Purpose")
    table.add_column("Path", overflow="fold")
    table.add_column("")

    for e in entries:
        mark = "[green]✓[/green]" if e.exists else "[red]missing[/red]"
        table.add_row(e.slug, e.purpose or "[dim]—[/dim]", str(e.path), mark)

    console.print()
    console.print(table)
    stale = [e for e in entries if not e.exists]
    if stale:
        console.print(
            f"  [yellow]⚠[/yellow]  {len(stale)} tracked path(s) not found — "
            "moved, renamed, or on an unmounted disk. Entries are kept, not deleted."
        )


# --------------------------------------------------------------------------- #
# skill sync rendering (FEAT-010; extracted to meridian/skilldist.py in FEAT-020)
#
# Everything that touches another repository lives in `meridian.skilldist` and
# returns data. What is left here is presentation: tables, styles, totals and
# the exit codes.
# --------------------------------------------------------------------------- #

def _install_prs_to_all(*, dry_run: bool, prune: bool = False) -> None:
    """Open a skill-update PR in every tracked project (FEAT-010)."""
    entries = _tracked_projects()
    if not entries:
        console.print(
            "[dim]No projects tracked. Run [bold]meridian register[/bold] in each repo.[/dim]"
        )
        raise typer.Exit(0)

    version = f"v{__version__}"
    console.print()
    verb = "Previewing skill PRs" if dry_run else "Opening skill PRs"
    console.print(f"  {verb} — [bold]{len(entries)} tracked project(s)[/bold], {version}")
    console.print()

    table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
    table.add_column("Project", no_wrap=True, min_width=20)
    table.add_column("Result", no_wrap=True, width=10)
    table.add_column("", overflow="fold")

    styles = {
        "opened": "green", "updated": "green", "would open": "cyan",
        "current": "dim", "skipped": "yellow", "failed": "red",
    }
    outcomes = open_skill_prs(
        entries, version, dry_run=dry_run, prune=prune,
        progress=lambda slug: console.status(f"  {slug}…"),
    )
    for outcome in outcomes:
        style = styles.get(outcome.status, "")
        table.add_row(outcome.slug, f"[{style}]{outcome.status}[/{style}]", outcome.detail)

    console.print(table)
    console.print(
        "  [dim]Each repo's working tree is untouched — the update is built in a "
        "temporary worktree and proposed as a PR.[/dim]"
    )


def _install_to_all(*, force: bool, dry_run: bool, prune: bool = False) -> None:
    """Render `install --all` — the sync itself lives in `skilldist.sync_all`."""
    entries = _tracked_projects()
    if not entries:
        console.print(
            "[dim]No projects tracked. Run [bold]meridian register[/bold] in each repo.[/dim]"
        )
        raise typer.Exit(0)

    console.print()
    header = "Previewing skill sync" if dry_run else "Syncing skills"
    console.print(f"  {header} — [bold]{len(entries)} tracked project(s)[/bold]")
    console.print()

    table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
    table.add_column("Project", no_wrap=True, min_width=20)
    table.add_column("new", justify="right", width=5)
    table.add_column("upd", justify="right", width=5)
    table.add_column("same", justify="right", width=6)
    table.add_column("", overflow="fold")

    total_written = 0
    total_pending = 0

    for outcome in sync_all(entries, force=force, dry_run=dry_run, prune=prune):
        if outcome.status != "synced":
            colour = "yellow" if outcome.status == "skipped" else "red"
            table.add_row(
                outcome.slug, "·", "·", "·", f"[{colour}]{outcome.detail}[/{colour}]"
            )
            continue

        total_written += outcome.written
        note = ""
        if outcome.changed and not force:
            total_pending += outcome.changed
            note = f"[yellow]{outcome.changed} outdated — needs --force[/yellow]"
        table.add_row(
            outcome.slug,
            str(outcome.new) if outcome.new else "[dim]·[/dim]",
            str(outcome.changed) if outcome.changed else "[dim]·[/dim]",
            str(outcome.current) if outcome.current else "[dim]·[/dim]",
            note,
        )

    console.print(table)
    verb = "would be written" if dry_run else "written"
    console.print(f"  [dim]{total_written} file(s) {verb}[/dim]")
    if total_pending and not force:
        console.print(
            f"  [yellow]⚠[/yellow]  {total_pending} outdated skill(s) left alone — "
            "re-run with [bold]--force[/bold] to update."
        )
    if not dry_run and total_written:
        console.print(
            "  [dim]Skills are committed per repo, so review and commit the changes there.[/dim]"
        )


# --------------------------------------------------------------------------- #
# install  — distribute skill files (global or project), namespaced
# --------------------------------------------------------------------------- #

@app.command(name="install")
def install_skills(
    project: bool = typer.Option(
        False, "--project",
        help="Install into ./.claude/commands/meridian/ instead of the global "
             "~/.claude/commands/meridian/.",
    ),
    path: str | None = typer.Option(
        None, "--path", "-p",
        help="Project root (used with --project). Default: current directory.",
    ),
    all_projects: bool = typer.Option(
        False, "--all",
        help="Install into every tracked project (see `meridian projects`).",
    ),
    force: bool = typer.Option(
        False, "--force",
        help="Overwrite skill files that already exist.",
    ),
    pr: bool = typer.Option(
        False, "--pr",
        help="With --all: propose the update as a pull request in each repo "
             "instead of writing to their working trees.",
    ),
    prune: bool = typer.Option(
        False, "--prune",
        help="Also remove skills that no longer ship with Meridian.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Report what would change without writing anything.",
    ),
) -> None:
    """Install Meridian's Claude Code skills, namespaced as /meridian:<name>.

    By default installs globally into ~/.claude/commands/meridian/ so the skills
    are available in every project.  Use --project to pin skills to one
    repository, or --all to refresh every tracked project at once — the usual
    move after upgrading the package.
    """
    if all_projects:
        if pr:
            _install_prs_to_all(dry_run=dry_run, prune=prune)
        else:
            _install_to_all(force=force, dry_run=dry_run, prune=prune)
        return

    if pr:
        console.print("[red]Error:[/red] --pr requires --all.")
        raise typer.Exit(1)

    if project:
        root = Path(path).resolve() if path else Path.cwd()
        dest = root / ".claude" / "commands" / "meridian"
        scope_label = f"project ({root})"
    else:
        if path:
            console.print(
                "[yellow]Note:[/yellow] --path is ignored without --project; "
                "installing globally."
            )
        dest = Path.home() / ".claude" / "commands" / "meridian"
        scope_label = "global (~/.claude/commands/meridian/)"

    console.print()
    console.print(f"  Installing Meridian skills — [bold]{scope_label}[/bold]")
    console.print()

    result = sync_skills(dest, force=force, dry_run=dry_run, prune=prune)

    for name in result.new:
        console.print(f"  [green]+[/green] {name}")
    for name in result.changed:
        marker = "[yellow]~[/yellow]" if not force else "[green]↑[/green]"
        console.print(f"  {marker} {name}" + ("" if force else "  [dim](outdated)[/dim]"))
    for name in result.removed:
        console.print(f"  [red]-[/red] {name}  [dim](no longer ships with Meridian)[/dim]")
    if result.current:
        console.print(f"  [dim]  {len(result.current)} already up to date[/dim]")

    console.print()
    verb = "would be written" if dry_run else "written"
    console.print(
        f"  [green]✓[/green] {result.written} skill(s) {verb} → [bold]{dest}[/bold]"
    )
    if result.changed and not force and not dry_run:
        console.print(
            f"  [yellow]⚠[/yellow]  {len(result.changed)} skill(s) are outdated — "
            "re-run with [bold]--force[/bold] to update them."
        )
    console.print()
    console.print(
        "  Invoke them in Claude Code as [cyan]/meridian:spec[/cyan], "
        "[cyan]/meridian:idea[/cyan], [cyan]/meridian:tasks[/cyan], …"
    )

# --------------------------------------------------------------------------- #
# help  — derived from the registered commands, so it cannot drift
# --------------------------------------------------------------------------- #

@app.command(name="help")
def help_cmd():
    """List every command, generated from the app itself.

    FEAT-014: this was a 309-line hand-written manual — 16% of cli.py — and it
    had already drifted: `link-job` and `unlink-job` were registered commands
    that appeared nowhere in it. Deriving the list from the Typer app makes that
    class of drift impossible. Use `meridian <command> --help` for flags.
    """
    console.print()
    console.print("  [bold]Meridian[/bold] — navigate your codebase with purpose")
    console.print()

    table = Table(box=box.SIMPLE, show_header=False, pad_edge=False)
    table.add_column("Command", style="cyan", no_wrap=True, min_width=22)
    table.add_column("What it does")

    # Registration order, deliberately: it follows the workflow (status → new →
    # close → …) rather than the alphabet. Sorting by `name` would also be a
    # no-op, since `@app.command()` leaves it None and Typer derives it later.
    for command in app.registered_commands:
        name = command.name or (command.callback.__name__.replace("_", "-")
                                if command.callback else "?")
        doc = (command.help or (command.callback.__doc__ or "")).strip().splitlines()
        table.add_row(f"meridian {name}", doc[0] if doc else "")

    console.print(table)
    console.print()
    console.print("  [dim]Flags for any command:[/dim] [cyan]meridian <command> --help[/cyan]")
    console.print("  [dim]Skills run in Claude Code as[/dim] [cyan]/meridian:spec[/cyan][dim], "
                  "[/dim][cyan]/meridian:tasks[/cyan][dim], …[/dim]")
    console.print()


# --------------------------------------------------------------------------- #
# entry point  — the only place an unexpected exception should surface
# --------------------------------------------------------------------------- #

def main() -> None:
    """Console-script entry point with a single top-level error handler.

    FEAT-015: four ordinary conditions — a corrupt .meridian.toml, an unreadable
    spec, a dead URL, an unpulled model — reached the user as ~40 lines of Rich
    traceback. For a CLI that is mostly driven by an agent, a traceback is far
    harder to recover from than one line naming the problem, and it costs a
    great deal more context to read.

    Typer's own exits pass straight through; anything unexpected becomes a
    one-line error. Set MERIDIAN_DEBUG=1 to get the traceback back.
    """
    try:
        app()
    except (typer.Exit, typer.Abort, SystemExit):
        raise
    except KeyboardInterrupt:
        console.print("\n[dim]Interrupted.[/dim]")
        raise SystemExit(130)
    except Exception as e:
        if os.environ.get("MERIDIAN_DEBUG"):
            raise
        console.print(f"[red]Error:[/red] {_friendly(e)}")
        console.print(
            "  [dim]Set [bold]MERIDIAN_DEBUG=1[/bold] for the full traceback.[/dim]"
        )
        raise SystemExit(1)


def _friendly(e: BaseException) -> str:
    """One line describing *e*, naming the file or URL wherever we know it."""
    import tomllib

    if isinstance(e, tomllib.TOMLDecodeError):
        return f".meridian.toml is not valid TOML — {e}"
    if isinstance(e, PermissionError):
        return f"Permission denied: {e.filename or e}"
    if isinstance(e, FileNotFoundError):
        return f"File not found: {e.filename or e}"
    if isinstance(e, IsADirectoryError):
        return f"Expected a file but found a directory: {e.filename or e}"
    if isinstance(e, OSError):
        return f"{e.strerror or e}{f': {e.filename}' if e.filename else ''}"

    import httpx

    if isinstance(e, httpx.HTTPStatusError):
        return (
            f"{e.request.url} returned HTTP {e.response.status_code}"
        )
    if isinstance(e, httpx.ConnectError):
        return f"Could not connect to {e.request.url if e.request else 'the server'}"
    if isinstance(e, httpx.TimeoutException):
        return f"Timed out reaching {e.request.url if e.request else 'the server'}"
    if isinstance(e, httpx.HTTPError):
        return f"Network error: {e}"

    message = str(e).strip()
    return message or f"{type(e).__name__} (no message)"
