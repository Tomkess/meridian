import logging
import os
import re
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import typer
from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from meridian import __version__
from meridian.config import load_config, slugify_project
from meridian.specs import (
    APPETITE_LABELS,
    APPETITE_VALUES,
    CONFIDENCE_VALUES,
    VALID_STATUSES,
    all_specs,
    create_spec,
    load_spec,
    rebuild_registry,
    save_spec,
    task_progress,
    transition_spec,
)

# P6: set MERIDIAN_DEBUG=1 to see library-level warnings (Databricks errors, rerank failures, etc.)
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

# ── Help diagram helpers ───────────────────────────────────────────────────── #

_HELP_W = 62  # inner box width between │ and │


def _vlen(s: str) -> int:
    """Display width after stripping Rich markup — accounts for wide chars."""
    plain = re.sub(r"\[/?[a-zA-Z0-9 _#:.!]+\]", "", s).replace("\\[", "[")
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in plain)


def _box_top(label: str, color: str = "bold") -> str:
    inner = f"─ [{color}]{label}[/{color}] "
    return f"  [dim]┌[/dim]{inner}[dim]{'─' * (_HELP_W - _vlen(inner))}┐[/dim]"


def _box_row(content: str) -> str:
    pad = max(0, _HELP_W - 2 - _vlen(content))
    return f"  [dim]│[/dim]  {content}{' ' * pad}[dim]│[/dim]"


def _box_bot() -> str:
    return f"  [dim]└{'─' * _HELP_W}┘[/dim]"


def _connector(label: str = "") -> str:
    prefix = "  [dim]             │[/dim]"
    return f"{prefix}  {label}" if label else prefix


# ── Spec lookup helper ────────────────────────────────────────────────────── #

def _find_spec(cfg, feature_id: str, *, silent: bool = False) -> Path | None:
    """Locate spec.md for a feature. Exits with error unless silent=True."""
    feat_id_norm = feature_id.upper()
    candidates = list(cfg.specs_path.glob(f"{feat_id_norm}_*/spec.md"))
    if not candidates:
        if silent:
            return None
        console.print(f"[red]Error:[/red] No spec found for [bold]{feat_id_norm}[/bold].")
        raise typer.Exit(1)
    return candidates[0]

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
    from meridian.registry import all_projects

    entries = all_projects()
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
):
    """Show full feature dashboard with lifecycle states."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from meridian.databricks import (
        latest_run_state,
        latest_task_states,
        run_state_display,
        task_run_display,
    )

    if all_projects:
        _status_all()
        raise typer.Exit(0)

    cfg = _config()
    specs = all_specs(cfg.specs_path)

    if not specs:
        console.print("[dim]No features found. Run [bold]meridian new[/bold] to capture an idea.[/dim]")
        raise typer.Exit(0)

    # ── Pre-fetch Databricks job/task states ───────────────────────────────
    # Only when at least one spec has a scheduler.job_id set.
    # Each entry: (feat_id_upper, job_id, task_keys_or_None)
    job_linked: list[tuple[str, int, list[str] | None]] = []
    for s in specs:
        sched = s.get("scheduler")
        if isinstance(sched, dict) and sched.get("job_id"):
            task_keys = sched.get("task_keys") or None
            if isinstance(task_keys, list) and not task_keys:
                task_keys = None
            job_linked.append((
                str(s.get("id", "?")).upper(),
                int(sched["job_id"]),
                task_keys,
            ))

    has_jobs = bool(job_linked)
    job_states: dict[str, str] = {}  # feat_id_upper → display string

    if has_jobs:
        def _fetch(feat_id: str, job_id: int, task_keys: list[str] | None) -> tuple[str, str]:
            # P5: timeout comes from .meridian.toml [databricks] status_timeout (default 8s)
            t = cfg.databricks_status_timeout
            if task_keys:
                states = latest_task_states(cfg, job_id, task_keys, timeout=t)
                return feat_id, task_run_display(states, task_keys)
            else:
                state = latest_run_state(cfg, job_id, timeout=t)
                return feat_id, run_state_display(state)

        with console.status("Fetching job statuses…"):
            with ThreadPoolExecutor(max_workers=min(8, len(job_linked))) as pool:
                futures = {
                    pool.submit(_fetch, fid, jid, tkeys): fid
                    for fid, jid, tkeys in job_linked
                }
                for f in as_completed(futures):
                    fid, display = f.result()
                    job_states[fid] = display

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
    if has_jobs:
        table.add_column("Job", min_width=14)

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

        row = [feat_id, name, goal, status_text, appetite_val, conf_display, cycle_val, updated]
        if has_jobs:
            row.append(job_states.get(feat_id, "[dim]∅[/dim]"))
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
    console.print(f"[green]✓[/green] [bold]{feat_id_display}[/bold] → [bold]{status}[/bold]")

    if status == "abandoned" and not abandoned_reason:
        console.print(
            "  [dim]Tip: add [bold]--abandoned-reason[/bold] to record why — "
            "helps if you revive this feature later.[/dim]"
        )

    # Spec drift reminder when marking done
    if status == "done":
        console.print(
            "  [dim]Reminder: review [bold]spec.md[/bold] and update it to reflect "
            "what was actually built — specs drift during implementation.[/dim]"
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
    data = load_spec(spec_path)

    if not clear and not set_cycle:
        current = data.get("cycle") or "none"
        console.print(f"  [bold]{feat_id_norm}[/bold] cycle: [blue]{current}[/blue]")
        return

    # G1: warn on non-standard cycle IDs (typos like "2026Q2" instead of "2026-Q2")
    _CYCLE_PATTERN = re.compile(r"^\d{4}-Q[1-4]$")
    if set_cycle and not _CYCLE_PATTERN.match(set_cycle):
        console.print(
            f"  [dim]Note: [bold]{set_cycle}[/bold] is an unusual cycle format — "
            "expected e.g. [bold]2026-Q2[/bold]. Any string is accepted but check for typos.[/dim]"
        )

    data["cycle"] = None if clear else set_cycle
    save_spec(spec_path, data)
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
# link-job  — Databricks integration
# --------------------------------------------------------------------------- #

@app.command("link-job")
def link_job(
    feature_id: str = typer.Argument(..., help="Feature ID (e.g. feat-007 or FEAT-007)"),
    job: str = typer.Argument(..., help="Databricks job ID (numeric) or job name"),
    task: list[str] | None = typer.Option(
        None, "--task", "-t",
        help="Task key within the job (repeat for multiple). Omit to track the whole job.",
    ),
):
    """Link a Databricks job (and optionally specific tasks) to a feature spec."""
    from meridian.databricks import DatabricksError, resolve_job

    cfg = _config()
    spec_path = _find_spec(cfg, feature_id)
    assert spec_path is not None  # _find_spec exits when silent=False

    with console.status(f"Resolving job [bold]{job}[/bold]…"):
        try:
            job_id, job_name = resolve_job(cfg, job)
        except DatabricksError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1)

    task_keys = list(task) if task else []
    scheduler: dict = {"job_id": job_id, "job_name": job_name}
    if task_keys:
        scheduler["task_keys"] = task_keys

    data = load_spec(spec_path)
    data["scheduler"] = scheduler
    save_spec(spec_path, data)
    rebuild_registry(cfg.specs_path)

    feat_id_str = str(data.get("id", feature_id)).upper()
    task_note = f" [dim]tasks: {', '.join(task_keys)}[/dim]" if task_keys else ""
    console.print(
        f"[green]✓[/green] Linked [bold]{feat_id_str}[/bold] → "
        f"Databricks job [bold]{job_name}[/bold] [dim](id: {job_id})[/dim]{task_note}"
    )


@app.command("unlink-job")
def unlink_job(
    feature_id: str = typer.Argument(..., help="Feature ID (e.g. feat-007 or FEAT-007)"),
):
    """Remove the Databricks job link from a feature spec."""
    cfg = _config()
    spec_path = _find_spec(cfg, feature_id)
    assert spec_path is not None  # _find_spec exits when silent=False
    data = load_spec(spec_path)

    if not data.get("scheduler"):
        console.print(f"[dim]{feature_id.upper()} has no job linked.[/dim]")
        raise typer.Exit(0)

    old = data["scheduler"]
    old_name = old.get("job_name", str(old.get("job_id", "?"))) if isinstance(old, dict) else str(old)
    data["scheduler"] = None
    save_spec(spec_path, data)
    rebuild_registry(cfg.specs_path)

    feat_id_str = str(data.get("id", feature_id)).upper()
    console.print(f"[green]✓[/green] Unlinked [bold]{feat_id_str}[/bold] (was: {old_name})")


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
            console.print(f"[yellow]Warning:[/yellow] {e}")
            console.print("Vector index was not rebuilt.")


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
def guide():
    """Show what's set up in this project and what to do next."""
    from meridian.guide import first_action, run_guide

    cfg = _config()
    steps = run_guide(cfg)

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
        "\n"
        "[databricks]\n"
        'host      = ""\n'
        'token_env = "DATABRICKS_TOKEN"\n'
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
    from meridian.registry import derive_purpose
    from meridian.registry import register as register_entry

    cfg = _config()
    slug = (name or cfg.project).strip().lower()
    text = purpose or derive_purpose(cfg.specs_path, cfg.root.name)

    entry = register_entry(slug, cfg.root, text)
    console.print(f"[green]✓[/green] Tracking [bold]{entry.slug}[/bold] → [dim]{entry.path}[/dim]")
    if entry.purpose:
        console.print(f"  {entry.purpose}")
    console.print("  [dim]See everything with [bold]meridian status --all[/bold].[/dim]")


@app.command()
def projects():
    """List every tracked project."""
    from meridian.registry import all_projects

    entries = all_projects()
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
# skill sync helpers (FEAT-010)
# --------------------------------------------------------------------------- #

@dataclass
class SkillSync:
    """What a skill install did, or would do."""
    new: list[str]
    changed: list[str]     # present but differs from the bundled version
    current: list[str]     # byte-identical, nothing to do
    written: int

    @property
    def pending(self) -> int:
        """Files that differ and were not written (needs --force)."""
        return len(self.changed)


def _bundled_skills_dir() -> Path:
    import meridian as _meridian_pkg

    return Path(_meridian_pkg.__file__).parent / "skills" / "commands"


def _sync_skills(dest: Path, *, force: bool, dry_run: bool) -> SkillSync:
    """Copy bundled skills into *dest*, reporting drift.

    Compares content rather than mere existence: "already installed" hides the
    case that actually matters after an upgrade — a skill that is present but
    stale. An outdated file is only overwritten with --force, so a project that
    deliberately customised a skill is never silently clobbered.
    """
    import shutil

    src_dir = _bundled_skills_dir()
    new: list[str] = []
    changed: list[str] = []
    current: list[str] = []
    written = 0

    if not dry_run:
        dest.mkdir(parents=True, exist_ok=True)

    for skill in sorted(src_dir.glob("*.md")):
        target = dest / skill.name
        if not target.exists():
            new.append(skill.stem)
        elif target.read_bytes() == skill.read_bytes():
            current.append(skill.stem)
            continue
        else:
            changed.append(skill.stem)
            if not force:
                continue

        if not dry_run:
            shutil.copy2(skill, target)
        written += 1

    return SkillSync(new=new, changed=changed, current=current, written=written)


def _git(args: list[str], cwd: Path, timeout: int = 60):
    """Run git, capturing output. Never raises on a non-zero exit."""
    import subprocess

    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout
    )


def _default_branch(repo: Path) -> str | None:
    """The remote's default branch, e.g. 'main'. None when there is no remote."""
    r = _git(["symbolic-ref", "refs/remotes/origin/HEAD"], repo)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip().rsplit("/", 1)[-1]
    # Fall back to asking the remote directly — refs/remotes/origin/HEAD is not
    # always present on a clone made with --single-branch.
    r = _git(["remote", "show", "origin"], repo, timeout=30)
    if r.returncode == 0:
        for line in r.stdout.splitlines():
            if "HEAD branch:" in line:
                return line.split(":", 1)[1].strip()
    return None


def _open_skill_pr(entry, version: str, *, dry_run: bool) -> tuple[str, str]:
    """Propose a skill update to one repo as a pull request.

    Returns (status, detail) for the summary table.

    The copy happens inside a throwaway git worktree, never the repo's own
    working tree: these are ten repos the user may have work in progress in, and
    silently mutating a checkout — or moving its HEAD — is exactly the failure
    this project has already been bitten by.
    """
    import shutil
    import subprocess
    import tempfile

    if not (entry.path / ".git").exists():
        return "skipped", "not a git repository"

    if _git(["remote", "get-url", "origin"], entry.path).returncode != 0:
        return "skipped", "no 'origin' remote"

    base = _default_branch(entry.path)
    if base is None:
        return "skipped", "could not resolve the default branch"

    branch = f"chore/meridian-skills-{version}"

    fetch = _git(["fetch", "origin", base], entry.path, timeout=120)
    if fetch.returncode != 0:
        return "failed", f"fetch failed: {fetch.stderr.strip().splitlines()[-1:] or ''}"

    if dry_run:
        return "would open", f"{branch} → {base}"

    tmp = Path(tempfile.mkdtemp(prefix="meridian-skills-"))
    worktree = tmp / "wt"
    try:
        add = _git(
            ["worktree", "add", "--detach", str(worktree), f"origin/{base}"],
            entry.path, timeout=120,
        )
        if add.returncode != 0:
            return "failed", f"worktree: {add.stderr.strip().splitlines()[-1:] or ''}"

        _git(["checkout", "-B", branch], worktree)
        result = _sync_skills(
            worktree / ".claude" / "commands" / "meridian", force=True, dry_run=False
        )
        if not result.written:
            return "current", "skills already match"

        _git(["add", ".claude/commands/meridian"], worktree)
        if not _git(["diff", "--cached", "--quiet"], worktree).returncode:
            return "current", "no net change"

        message = (
            f"chore: update Meridian skills to {version}\n\n"
            f"{len(result.new)} added, {len(result.changed)} updated. "
            "Generated by `meridian install --all --pr`.\n"
        )
        commit = _git(["commit", "-m", message], worktree)
        if commit.returncode != 0:
            return "failed", "commit failed"

        push = _git(["push", "-u", "origin", branch, "--force-with-lease"], worktree, timeout=180)
        if push.returncode != 0:
            return "failed", f"push failed: {(push.stderr.strip().splitlines() or [''])[-1]}"

        existing = subprocess.run(
            ["gh", "pr", "list", "--head", branch, "--json", "url", "--jq", ".[0].url"],
            cwd=worktree, capture_output=True, text=True, timeout=60,
        )
        if existing.returncode == 0 and existing.stdout.strip():
            return "updated", existing.stdout.strip()

        pr = subprocess.run(
            ["gh", "pr", "create", "--base", base, "--head", branch,
             "--title", f"chore: update Meridian skills to {version}",
             "--body",
             f"Syncs `.claude/commands/meridian/` with Meridian {version}.\n\n"
             f"- {len(result.new)} skill(s) added\n"
             f"- {len(result.changed)} skill(s) updated\n\n"
             "Opened by `meridian install --all --pr`.\n"],
            cwd=worktree, capture_output=True, text=True, timeout=120,
        )
        if pr.returncode != 0:
            return "failed", (pr.stderr.strip().splitlines() or ["gh pr create failed"])[-1]
        return "opened", pr.stdout.strip().splitlines()[-1] if pr.stdout.strip() else branch

    except (OSError, subprocess.SubprocessError) as e:
        return "failed", str(e)
    finally:
        _git(["worktree", "remove", "--force", str(worktree)], entry.path)
        shutil.rmtree(tmp, ignore_errors=True)


def _install_prs_to_all(*, dry_run: bool) -> None:
    """Open a skill-update PR in every tracked project (FEAT-010)."""
    from meridian import __version__
    from meridian.registry import all_projects

    entries = all_projects()
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
    for entry in sorted(entries, key=lambda e: e.slug):
        if not entry.exists:
            table.add_row(entry.slug, "[yellow]skipped[/yellow]", "path not found")
            continue
        with console.status(f"  {entry.slug}…"):
            status_text, detail = _open_skill_pr(entry, version, dry_run=dry_run)
        style = styles.get(status_text, "")
        table.add_row(entry.slug, f"[{style}]{status_text}[/{style}]", detail)

    console.print(table)
    console.print(
        "  [dim]Each repo's working tree is untouched — the update is built in a "
        "temporary worktree and proposed as a PR.[/dim]"
    )


def _install_to_all(*, force: bool, dry_run: bool) -> None:
    """Refresh skills in every tracked project (FEAT-010).

    The point of the project registry: after upgrading meridian, one command
    brings every repo's committed skills up to date instead of ten manual
    `--project` runs.
    """
    from meridian.registry import all_projects

    entries = all_projects()
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

    for entry in sorted(entries, key=lambda e: e.slug):
        if not entry.exists:
            table.add_row(entry.slug, "·", "·", "·", "[yellow]path not found — skipped[/yellow]")
            continue

        dest = entry.path / ".claude" / "commands" / "meridian"
        try:
            result = _sync_skills(dest, force=force, dry_run=dry_run)
        except OSError as e:
            table.add_row(entry.slug, "·", "·", "·", f"[red]{e.strerror or e}[/red]")
            continue

        total_written += result.written
        note = ""
        if result.changed and not force:
            total_pending += result.pending
            note = f"[yellow]{result.pending} outdated — needs --force[/yellow]"
        table.add_row(
            entry.slug,
            str(len(result.new)) if result.new else "[dim]·[/dim]",
            str(len(result.changed)) if result.changed else "[dim]·[/dim]",
            str(len(result.current)) if result.current else "[dim]·[/dim]",
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
            _install_prs_to_all(dry_run=dry_run)
        else:
            _install_to_all(force=force, dry_run=dry_run)
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

    result = _sync_skills(dest, force=force, dry_run=dry_run)

    for name in result.new:
        console.print(f"  [green]+[/green] {name}")
    for name in result.changed:
        marker = "[yellow]~[/yellow]" if not force else "[green]↑[/green]"
        console.print(f"  {marker} {name}" + ("" if force else "  [dim](outdated)[/dim]"))
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
# help  — static manual
# --------------------------------------------------------------------------- #

@app.command(name="help")
def help_cmd():
    """Show the Meridian manual — commands, workflow, and config reference."""
    console.print()
    console.rule("[bold]Meridian — Navigate your codebase with purpose[/bold]")

    # ── Workflow diagram ───────────────────────────────────────────────────── #
    console.print()
    console.print("  [bold]How it works[/bold]")
    console.print()

    # 1 · STRATEGY
    console.print(_box_top("1 · STRATEGY", "bold magenta"))
    console.print(_box_row("[yellow]/vision[/yellow]    [dim]→[/dim]  VISION.md  [dim](north star)[/dim]"))
    console.print(_box_row("[yellow]/goal new[/yellow]  [dim]→[/dim]  goals/goal-NN.md"))
    console.print(_box_bot())

    console.print(_connector())
    console.print(_connector())

    # 2 · CAPTURE  (keep content ≤ _HELP_W-2 visible chars)
    console.print(_box_top("2 · CAPTURE", "bold blue"))
    console.print(_box_row(
        "[cyan]meridian new[/cyan] [dim]\"idea\" --appetite m[/dim]"
        "  [dim]→[/dim]  spec.md  [green](💡 idea)[/green]"
    ))
    console.print(_box_bot())

    console.print(_connector())
    console.print(_connector("[yellow]/spec[/yellow]  [yellow]/breakdown[/yellow]"))

    # 3 · ELABORATE
    console.print(_box_top("3 · ELABORATE", "bold yellow"))
    console.print(_box_row(
        "[yellow]/spec[/yellow]  [dim]→[/dim]  spec.md  [dim](requirements + ACs)[/dim]"
    ))
    console.print(_box_row(
        "[yellow]/breakdown[/yellow]  [dim]→[/dim]  breakdown.md  [dim](technical design)[/dim]"
    ))
    console.print(_box_row(
        "[cyan]meridian enrich[/cyan] FEAT-NNN <src>  [dim]→[/dim]  LanceDB"
    ))
    console.print(_box_bot())

    console.print(_connector())
    console.print(_connector("[yellow]/tasks[/yellow]  [yellow]/plan[/yellow]"))

    # 4 · PLAN
    console.print(_box_top("4 · PLAN", "bold cyan"))
    console.print(_box_row(
        "[yellow]/tasks[/yellow]  [dim]→[/dim]  tasks.md  [dim](Pre: preconditions)[/dim]  [yellow](🔨 in-progress)[/yellow]"
    ))
    console.print(_box_row(
        "[yellow]/plan[/yellow]   [dim]→[/dim]  plan.md   [dim](phased strategy — optional)[/dim]"
    ))
    console.print(_box_bot())

    console.print(_connector())
    console.print(_connector("[dim]build, commit…[/dim]"))

    # 5 · BUILD
    console.print(_box_top("5 · BUILD", "bold yellow"))
    console.print(_box_row(
        "[yellow]/challenge[/yellow]  [yellow]/connect-dots[/yellow]  [cyan]meridian search[/cyan]  [yellow](🔨 building)[/yellow]"
    ))
    console.print(_box_bot())

    console.print(_connector())
    console.print(_connector("[cyan]meridian close[/cyan] --status done"))

    # 6 · SHIP
    console.print(_box_top("6 · SHIP", "bold green"))
    console.print(_box_row(
        "[cyan]meridian transition[/cyan] --from-merge <branch>  [green](🚀 live)[/green]"
    ))
    console.print(_box_bot())

    console.print()
    console.print(
        "  [dim]CLI commands [cyan]cyan[/cyan] — handle operations.  "
        "Slash commands [yellow]yellow[/yellow] — handle reasoning.[/dim]"
    )

    # ── Overview ──────────────────────────────────────────────────────────── #
    console.print()
    console.print(
        "  Meridian is a spec-first, AI-native development OS: "
        "[bold]capture → shape → plan → build → ship[/bold].\n"
        "  It lives inside your project as a CLI tool ([bold]meridian[/bold]) "
        "plus Claude Code slash commands ([bold]/spec[/bold], [bold]/tasks[/bold], …).\n"
        "  The [bold]CLI[/bold] handles operations (create, transition, search, enrich, cycle).\n"
        "  The [bold]skills[/bold] handle reasoning (elaborate, decompose, plan, challenge, decide).\n"
        "  [bold]STEERING.md[/bold] injects project context into every skill run."
    )

    # ── Lifecycle ─────────────────────────────────────────────────────────── #
    console.print()
    console.print("  [bold]Lifecycle states[/bold]")
    console.print()
    lifecycle_table = Table(box=box.SIMPLE, show_header=False, pad_edge=False, show_edge=False)
    lifecycle_table.add_column("State", style="bold", min_width=16)
    lifecycle_table.add_column("Meaning")
    lifecycle_table.add_column("Next", style="dim")
    rows = [
        ("💡 idea",          "Raw capture — stub spec, no ACs yet",                "→ draft  (run /spec)"),
        ("📝 draft",         "Spec elaborated; breakdown + tasks pending",          "→ in-progress  (run /tasks)"),
        ("🔨 in-progress",   "Tasks generated; actively being built",               "→ blocked | done"),
        ("🚫 blocked",       "Waiting on something external",                       "→ in-progress"),
        ("✅ done",           "Built, not yet released — review spec.md for drift", "→ in-production"),
        ("🚀 in-production", "Live",                                                "→ done (rollback)"),
        ("🗑  abandoned",    "Will not be built",                                   "→ idea (revive)"),
    ]
    for state, meaning, nxt in rows:
        lifecycle_table.add_row(state, meaning, nxt)
    console.print(lifecycle_table)

    # ── CLI commands ──────────────────────────────────────────────────────── #
    console.print()
    console.print("  [bold]CLI commands[/bold]")
    console.print()
    cli_table = Table(box=box.SIMPLE, show_header=True, header_style="bold dim",
                      pad_edge=False, show_edge=False)
    cli_table.add_column("Command", min_width=42)
    cli_table.add_column("What it does")
    cli_cmds = [
        ('meridian status',
         'Dashboard: status, task progress [N/M], confidence, cycle, deps'),
        ('meridian new "idea text"',
         'Quick-capture a new idea, create stub spec'),
        ('meridian new "idea" --goal goal-01 --appetite m',
         'Capture idea linked to a goal with appetite (xs|s|m|l)'),
        ('meridian close feat-007 --status done',
         'Transition lifecycle state; prints spec-drift reminder at done'),
        ('meridian close feat-007 --status blocked --blocked-by <reason>',
         'Block with reason — sets blocked_at for staleness tracking'),
        ('meridian close feat-007 --status abandoned --abandoned-reason <r>',
         'Abandon with reason — persists through revive for future context'),
        ('meridian close feat-007 --confidence high',
         'Update problem confidence: low | medium | high'),
        ('meridian cycle feat-007 --set 2026-Q2',
         'Assign to cycle; warns when cycle is overloaded'),
        ('meridian cycle feat-007 --clear',
         'Remove feature from any cycle'),
        ('meridian enrich feat-007 report.pdf',
         'Ingest PDF/URL/file into feature research corpus'),
        ('meridian enrich feat-007 shot.png --note "what is wrong"',
         'Ingest a screenshot + notes sidecar (image copied, notes embedded)'),
        ('meridian enrich feat-007 --latest-screenshot --note "…"',
         'Same, taking the newest image from the OS screenshot directory'),
        ('meridian enrich feat-007 --from-clipboard --note "…"',
         'Same, taking the image from the clipboard (macOS)'),
        ('meridian enrich feat-007 shot.png --note-file notes.md',
         'Read notes (and any agent visual reading) from a sidecar file'),
        ('meridian enrich feat-007 shot.png --note "…" --vision',
         'Fallback: also describe the image with the configured Ollama vision model'),
        ('meridian install --all',
         "Push skills into every tracked repo (+ --force, --dry-run)"),
        ('meridian install --all --pr',
         'Propose the skill update as a PR per repo — working trees untouched'),
        ('meridian register',
         'Track this repo so it shows up in the cross-project dashboard'),
        ('meridian projects',
         'List every tracked project'),
        ('meridian status --all',
         'Cross-project dashboard: every tracked repo at a glance'),
        ('meridian search "drift detection"',
         'Semantic search across this project\'s research (+ --feat, --limit, --no-rerank)'),
        ('meridian search "drift detection" --all-projects',
         'Widen the search to every Meridian project sharing the index'),
        ('meridian index',
         "Rebuild REGISTRY.md + this project's vector index"),
        ('meridian index --vectors-only',
         'Rebuild vectors only — leaves REGISTRY.md untouched (safe in other repos)'),
        ('meridian transition --from-merge feat-007/slug',
         'Auto-transition to in-production after merge (branch must contain feat-NNN)'),
        ('meridian revive feat-007',
         'Revive an abandoned feature back to idea state (preserves abandoned_reason)'),
        ('meridian guide',
         '8-step project advisor: vision → steering → goals → features → specs → research → cycles → tasks'),
        ('meridian init',
         'Bootstrap Meridian in a new project: .meridian.toml + specs/ + .claude/commands/meridian/'),
        ('meridian install',
         'Install skills globally (~/.claude/commands/meridian/) as /meridian:<name>; --project to pin, --force to refresh'),
        ('meridian help',
         'This manual'),
    ]
    for cmd, desc in cli_cmds:
        cli_table.add_row(f"[cyan]{cmd}[/cyan]", desc)
    console.print(cli_table)

    # ── Slash commands ─────────────────────────────────────────────────────── #
    console.print()
    console.print("  [bold]Claude Code slash commands[/bold]")
    console.print()
    skill_table = Table(box=box.SIMPLE, show_header=True, header_style="bold dim",
                        pad_edge=False, show_edge=False)
    skill_table.add_column("Command", min_width=20)
    skill_table.add_column("What it does")
    skills = [
        ("/vision",        "Read or update the project north star"),
        ("/goal new",      "Create a validated strategic goal (6 checks)"),
        ("/idea",          "Capture idea, map to goal, set appetite"),
        ("/spec",          "Elaborate idea → spec.md with ACs; reads STEERING.md; sets status→draft"),
        ("/breakdown",     "Technical design → breakdown.md; reads STEERING.md"),
        ("/tasks",         "Ordered task list → tasks.md with Pre: preconditions; sets status→in-progress"),
        ("/plan",          "Phased strategy → plan.md (for 'l' appetite features)"),
        ("/roadmap",       "Goals × features × gaps view"),
        ("/connect-dots",  "Surface cross-feature overlaps and dependencies"),
        ("/challenge",     "Stress-test a feature against the vision"),
        ("/decision",      "Write an Architecture Decision Record (ADR)"),
        ("/ask",           "RAG Q&A — answer a question from enriched research"),
        ("/research",      "Deep synthesis of all enriched sources for a feature"),
        ("/brief",         "One-page paper brief (≤550 words) → summaries/"),
    ]
    for cmd, desc in skills:
        skill_table.add_row(f"[cyan]{cmd}[/cyan]", desc)
    console.print(skill_table)

    # ── Spec frontmatter fields ───────────────────────────────────────────── #
    console.print()
    console.print("  [bold]Spec frontmatter fields[/bold]")
    console.print()
    fm_table = Table(box=box.SIMPLE, show_header=True, header_style="bold dim",
                     pad_edge=False, show_edge=False)
    fm_table.add_column("Field", min_width=14)
    fm_table.add_column("Values")
    fm_table.add_column("Purpose")
    fm_rows = [
        ("status",      "idea|draft|in-progress|blocked|done|in-production|abandoned",
         "Lifecycle state (guarded transitions)"),
        ("appetite",    "xs | s | m | l",
         "How much time this is worth — set before writing spec"),
        ("confidence",  "low | medium | high",
         "How well the problem is understood (hill chart proxy)"),
        ("cycle",       "e.g. 2026-Q2",
         "Planning cycle this is bet on; set with meridian cycle"),
        ("depends_on",  "list of feat IDs",
         "Explicit dependencies — surfaced in meridian status"),
        ("enables",     "list of feat IDs",
         "Features this unlocks — surfaced in meridian status"),
        ("blocked_by",  "string or feat ID",
         "Required when status: blocked"),
        ("blocked_at",  "ISO date",
         "Set automatically on block; cleared on unblock (staleness detection)"),
        ("abandoned_reason", "string",
         "Why it was killed — persists through revive for future context"),
        ("abandoned_at", "ISO date",
         "Set automatically on abandon; cleared on revive"),
    ]
    for field, values, purpose in fm_rows:
        fm_table.add_row(f"[cyan]{field}[/cyan]", f"[dim]{values}[/dim]", purpose)
    console.print(fm_table)

    # ── Config ────────────────────────────────────────────────────────────── #
    console.print()
    console.print("  [bold]Config — .meridian.toml[/bold]")
    console.print()
    toml_example = (
        r"  \[meridian]" + "\n"
        "  project        = \"my-repo\"                    # scopes this repo in the shared index\n"
        "  specs_path     = \"specs\"                      # where FEAT-NNN/ dirs live\n"
        "  lancedb_path   = \"~/.meridian/lancedb\"        # vector store (global by default)\n"
        "  ollama_model   = \"mxbai-embed-large\"          # embedding model\n"
        "  reranker_model = \"BAAI/bge-reranker-v2-m3\"   # optional cross-encoder\n"
        "  ollama_vision_model = \"\"                     # optional: fallback screenshot describer\n"
        "\n"
        r"  \[databricks]" + "\n"
        "  host      = \"https://your-workspace.azuredatabricks.net\"\n"
        "  token_env = \"DATABRICKS_TOKEN\"                # env var holding the PAT"
    )
    console.print(f"  [dim]{toml_example}[/dim]")

    # ── Specs structure ───────────────────────────────────────────────────── #
    console.print()
    console.print("  [bold]Specs directory layout[/bold]")
    console.print()
    console.print(
        "  [dim]"
        "specs/\n"
        "  VISION.md                ← project north star\n"
        "  STEERING.md              ← AI context: conventions + standards\n"
        "  CYCLES.md                ← current betting cycle + icebox\n"
        "  SKILLS.md                ← workflow guide\n"
        "  REGISTRY.md              ← auto-generated feature index\n"
        "  goals/                   ← one .md per strategic goal\n"
        "  decisions/               ← Architecture Decision Records\n"
        "  FEAT-NNN_slug/\n"
        "    spec.md                ← requirements + acceptance criteria\n"
        "    breakdown.md           ← technical design\n"
        "    tasks.md               ← atomic work units (AI-executable)\n"
        "    plan.md                ← phased strategy (optional)\n"
        "    sources/               ← raw PDFs, text, pages, screenshots + .notes.md sidecars\n"
        "    summaries/             ← AI-generated summaries"
        "[/dim]"
    )

    console.print()
    console.rule()
    console.print(
        "\n  [dim]Run [bold]meridian guide[/bold] to check your project's setup status.[/dim]\n"
    )


if __name__ == "__main__":
    app()
