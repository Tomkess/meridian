import re
import unicodedata
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich import box
from rich.text import Text

from meridian.config import load_config
from meridian.specs import (
    all_specs,
    create_spec,
    load_spec,
    rebuild_registry,
    save_spec,
    task_progress,
    transition_spec,
    VALID_STATUSES,
    VALID_TRANSITIONS,
    APPETITE_VALUES,
    APPETITE_LABELS,
    CONFIDENCE_VALUES,
)

app = typer.Typer(
    name="meridian",
    help="Navigate your codebase with purpose.",
    no_args_is_help=True,
)

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

@app.command()
def status():
    """Show full feature dashboard with lifecycle states."""
    cfg = _config()
    specs = all_specs(cfg.specs_path)

    if not specs:
        console.print("[dim]No features found. Run [bold]meridian new[/bold] to capture an idea.[/dim]")
        raise typer.Exit(0)

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

        table.add_row(
            feat_id, name, goal, status_text,
            appetite_val, conf_display, cycle_val, updated,
        )

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
    goal: Optional[str] = typer.Option(None, "--goal", "-g", help="Goal ID to link (e.g. goal-01)"),
    appetite: Optional[str] = typer.Option(
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
    blocked_by: Optional[str] = typer.Option(None, "--blocked-by", help="Reason or feat ID (required when status=blocked)"),
    abandoned_reason: Optional[str] = typer.Option(None, "--abandoned-reason", help="Why this feature was killed (stored for future revive context)"),
    confidence: Optional[str] = typer.Option(
        None, "--confidence", "-c",
        help=f"Update problem confidence: {' | '.join(CONFIDENCE_VALUES)}",
    ),
):
    """Transition a feature's lifecycle state."""
    cfg = _config()
    spec_path = _find_spec(cfg, feature_id)

    if status == "blocked" and not blocked_by:
        console.print("[red]Error:[/red] --blocked-by is required when transitioning to 'blocked'.")
        raise typer.Exit(1)

    if confidence and confidence not in CONFIDENCE_VALUES:
        console.print(
            f"[red]Error:[/red] Invalid confidence '{confidence}'. "
            f"Valid: {', '.join(CONFIDENCE_VALUES)}"
        )
        raise typer.Exit(1)

    try:
        data = transition_spec(spec_path, status)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    if status == "blocked" and blocked_by:
        data["blocked_by"] = blocked_by
        save_spec(spec_path, data)

    if status == "abandoned" and abandoned_reason:
        data["abandoned_reason"] = abandoned_reason
        save_spec(spec_path, data)

    if confidence:
        data["confidence"] = confidence
        save_spec(spec_path, data)

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
    set_cycle: Optional[str] = typer.Option(None, "--set", "-s", help="Assign to a cycle (e.g. 2026-Q2)"),
    clear: bool = typer.Option(False, "--clear", help="Remove from any cycle"),
):
    """Assign or clear a feature's planning cycle (betting table)."""
    cfg = _config()
    feat_id_norm = feature_id.upper()
    spec_path = _find_spec(cfg, feature_id)
    data = load_spec(spec_path)

    if not clear and not set_cycle:
        current = data.get("cycle") or "none"
        console.print(f"  [bold]{feat_id_norm}[/bold] cycle: [blue]{current}[/blue]")
        return

    data["cycle"] = None if clear else set_cycle
    save_spec(spec_path, data)
    rebuild_registry(cfg.specs_path)

    if clear:
        console.print(f"[green]✓[/green] [bold]{feat_id_norm}[/bold] removed from cycle")
    else:
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
# enrich  (stub — LanceDB/Ollama layer comes next)
# --------------------------------------------------------------------------- #

@app.command()
def enrich(
    feature_id: str = typer.Argument(..., help="Feature ID (e.g. feat-007)"),
    source: str = typer.Argument(..., help="Path to PDF/text file or URL"),
):
    """Ingest a PDF, URL, or text file into a feature's research corpus."""
    from meridian.enrich import enrich_feature
    cfg = _config()
    with console.status(f"Extracting and embedding [bold]{source}[/bold]…"):
        try:
            result = enrich_feature(cfg, feature_id, source)
        except FileNotFoundError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1)
        except RuntimeError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1)

    chunks = result["chunks"]
    if chunks == 0:
        console.print(
            f"[yellow]⚠[/yellow]  [bold]{result['feat_id']}[/bold] ← {result['source']} "
            f"([dim]0 chunks — source may be too short or empty[/dim])"
        )
    else:
        console.print(
            f"[green]✓[/green] [bold]{result['feat_id']}[/bold] ← {result['source']} "
            f"([dim]{chunks} chunks embedded[/dim])"
        )


# --------------------------------------------------------------------------- #
# search
# --------------------------------------------------------------------------- #

@app.command()
def search(
    query: str = typer.Argument(..., help="Natural language search query"),
    feat: Optional[str] = typer.Option(None, "--feat", "-f", help="Filter to a specific feature ID"),
    limit: int = typer.Option(5, "--limit", "-n", help="Max results to return"),
    no_rerank: bool = typer.Option(False, "--no-rerank", help="Skip BGE reranker (faster)"),
):
    """Semantic search across all enriched research in the vector index."""
    from meridian.search import semantic_search, _reranker_available
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
            )
        except RuntimeError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1)

    if not results:
        console.print(
            "[dim]No results. Run [bold]meridian enrich <feat-id> <source>[/bold] to index research.[/dim]"
        )
        raise typer.Exit(0)

    console.print(f'\n[bold]Results for[/bold] "{query}"{reranker_note}\n')
    for i, r in enumerate(results, 1):
        score = r.get("rerank_score", r.get("_distance"))
        score_str = f"  [dim]score {score:.3f}[/dim]" if isinstance(score, float) else ""
        preview = r["text"][:200].replace("\n", " ").strip()
        console.print(
            f"[bold]{i}.[/bold] [blue]{r['feat_id']}[/blue] "
            f"[dim]{r['source_name']} ·chunk {r['chunk_idx']}[/dim]{score_str}"
        )
        console.print(f"   {preview}")
        console.print()


# --------------------------------------------------------------------------- #
# sync-jobs  (stub — Databricks layer)
# --------------------------------------------------------------------------- #

@app.command("sync-jobs")
def sync_jobs():
    """Auto-link Databricks jobs to specs by name convention."""
    console.print("[yellow]sync-jobs[/yellow] not yet implemented.")


# --------------------------------------------------------------------------- #
# index  (stub — LanceDB layer)
# --------------------------------------------------------------------------- #

@app.command()
def index():
    """Rebuild the LanceDB vector index and refresh REGISTRY.md."""
    from meridian.enrich import reindex_all
    cfg = _config()
    rebuild_registry(cfg.specs_path)
    console.print("[green]✓[/green] REGISTRY.md rebuilt.")
    with console.status("Re-embedding all sources…"):
        try:
            result = reindex_all(cfg)
            console.print(
                f"[green]✓[/green] Index rebuilt — "
                f"[bold]{result['sources']}[/bold] sources, "
                f"[bold]{result['chunks']}[/bold] chunks."
            )
        except RuntimeError as e:
            console.print(f"[yellow]Warning:[/yellow] {e}")
            console.print("REGISTRY.md was refreshed but vector index was not rebuilt.")


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
# guide  — dynamic project workflow advisor
# --------------------------------------------------------------------------- #

@app.command()
def guide():
    """Show what's set up in this project and what to do next."""
    from meridian.guide import run_guide, first_action

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
    console.print(_box_row(f"[yellow]/vision[/yellow]    [dim]→[/dim]  VISION.md  [dim](north star)[/dim]"))
    console.print(_box_row(f"[yellow]/goal new[/yellow]  [dim]→[/dim]  goals/goal-NN.md"))
    console.print(_box_bot())

    console.print(_connector())
    console.print(_connector())

    # 2 · CAPTURE  (keep content ≤ _HELP_W-2 visible chars)
    console.print(_box_top("2 · CAPTURE", "bold blue"))
    console.print(_box_row(
        f"[cyan]meridian new[/cyan] [dim]\"idea\" --appetite m[/dim]"
        f"  [dim]→[/dim]  spec.md  [green](💡 idea)[/green]"
    ))
    console.print(_box_bot())

    console.print(_connector())
    console.print(_connector(f"[yellow]/spec[/yellow]  [yellow]/breakdown[/yellow]"))

    # 3 · ELABORATE
    console.print(_box_top("3 · ELABORATE", "bold yellow"))
    console.print(_box_row(
        f"[yellow]/spec[/yellow]  [dim]→[/dim]  spec.md  [dim](requirements + ACs)[/dim]"
    ))
    console.print(_box_row(
        f"[yellow]/breakdown[/yellow]  [dim]→[/dim]  breakdown.md  [dim](technical design)[/dim]"
    ))
    console.print(_box_row(
        f"[cyan]meridian enrich[/cyan] FEAT-NNN <src>  [dim]→[/dim]  LanceDB"
    ))
    console.print(_box_bot())

    console.print(_connector())
    console.print(_connector(f"[yellow]/tasks[/yellow]  [yellow]/plan[/yellow]"))

    # 4 · PLAN
    console.print(_box_top("4 · PLAN", "bold cyan"))
    console.print(_box_row(
        f"[yellow]/tasks[/yellow]  [dim]→[/dim]  tasks.md  [dim](Pre: preconditions)[/dim]  [yellow](🔨 in-progress)[/yellow]"
    ))
    console.print(_box_row(
        f"[yellow]/plan[/yellow]   [dim]→[/dim]  plan.md   [dim](phased strategy — optional)[/dim]"
    ))
    console.print(_box_bot())

    console.print(_connector())
    console.print(_connector(f"[dim]build, commit…[/dim]"))

    # 5 · BUILD
    console.print(_box_top("5 · BUILD", "bold yellow"))
    console.print(_box_row(
        f"[yellow]/challenge[/yellow]  [yellow]/connect-dots[/yellow]  [cyan]meridian search[/cyan]  [yellow](🔨 building)[/yellow]"
    ))
    console.print(_box_bot())

    console.print(_connector())
    console.print(_connector(f"[cyan]meridian close[/cyan] --status done"))

    # 6 · SHIP
    console.print(_box_top("6 · SHIP", "bold green"))
    console.print(_box_row(
        f"[cyan]meridian transition[/cyan] --from-merge <branch>  [green](🚀 live)[/green]"
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
        ('meridian search "drift detection"',
         'Semantic search across all research (+ --feat, --limit, --no-rerank)'),
        ('meridian index',
         'Rebuild REGISTRY.md + full vector index'),
        ('meridian transition --from-merge feat-007/slug',
         'Auto-transition to in-production after merge (branch must contain feat-NNN)'),
        ('meridian guide',
         '8-step project advisor: vision → steering → goals → features → specs → research → cycles → tasks'),
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
        "  specs_path     = \"specs\"                      # where FEAT-NNN/ dirs live\n"
        "  lancedb_path   = \"~/.meridian/lancedb\"        # vector store (global by default)\n"
        "  ollama_model   = \"mxbai-embed-large\"          # embedding model\n"
        "  reranker_model = \"BAAI/bge-reranker-v2-m3\"   # optional cross-encoder\n"
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
        "    sources/               ← raw PDFs, text, downloaded pages\n"
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
