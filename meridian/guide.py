"""
Dynamic project workflow advisor.

Reads the real state of the project (vision, goals, features, specs, research)
and surfaces the most important next action in the correct order.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import frontmatter

from meridian.config import MeridianConfig
from meridian.specs import CONFIDENCE_VALUES, all_specs, task_progress

_STALE_BLOCKED_DAYS = 14  # flag features blocked longer than this


# ─── Result type ──────────────────────────────────────────── #

@dataclass
class StepResult:
    number: int
    title: str
    subtitle: str                    # one-line description of what this step is
    status: str                      # "ok" | "warn" | "error"
    detail: str                      # what was found / what is missing
    next_action: str | None          # exact command or instruction to fix it
    items: list[str] | None = None   # optional inline list (e.g. feature rows)


# ─── Individual checks ────────────────────────────────────── #

def _check_vision(specs_path: Path) -> StepResult:
    vision_file = specs_path / "VISION.md"
    subtitle = "Your project's north star — everything else derives from it."

    if not vision_file.exists():
        return StepResult(
            1, "Vision", subtitle, "error",
            "No VISION.md found.",
            "Run /vision in Claude Code to write it.",
        )

    content = vision_file.read_text().strip()
    try:
        post = frontmatter.loads(content)
        body = post.content.strip()
    except Exception:
        body = content

    if len(body) < 80:
        return StepResult(
            1, "Vision", subtitle, "warn",
            "VISION.md exists but the body looks sparse — may be a placeholder.",
            "Run /vision to flesh it out.",
        )

    return StepResult(1, "Vision", subtitle, "ok", "VISION.md present with content.", None)


def _check_steering(specs_path: Path) -> StepResult:
    steering_file = specs_path / "STEERING.md"
    subtitle = "AI context layer — conventions and standards injected into every skill."

    if not steering_file.exists():
        return StepResult(
            2, "Steering", subtitle, "warn",
            "No STEERING.md — skills lack project-specific context.",
            "Create specs/STEERING.md — a template ships with Meridian, copy it from the install.",
        )

    content = steering_file.read_text().strip()
    # Template is ~300 chars with only comments; real content is substantially longer
    if len(content) < 200 or content.count("<!--") >= 3:
        return StepResult(
            2, "Steering", subtitle, "warn",
            "STEERING.md looks like an unfilled template.",
            "Edit specs/STEERING.md with your project's constraints and conventions.",
        )

    return StepResult(2, "Steering", subtitle, "ok", "STEERING.md present with content.", None)


def _check_goals(specs_path: Path) -> tuple[StepResult, list[dict]]:
    goals_dir = specs_path / "goals"
    subtitle = "Strategic bets that features map to."
    goals: list[dict] = []

    if goals_dir.exists():
        for gf in sorted(goals_dir.glob("*.md")):
            try:
                gp = frontmatter.load(str(gf))
                goals.append({
                    "id": gp.metadata.get("id", gf.stem),
                    "name": gp.metadata.get("name", gf.stem),
                    "status": gp.metadata.get("status", "active"),
                })
            except Exception:
                pass

    if not goals:
        return StepResult(
            3, "Goals", subtitle, "error",
            "No goals defined — features have nothing to map to.",
            "Run /goal new  to create your first strategic goal.",
        ), []

    items = [f"{g['id']}  {g['name']}  [{g['status']}]" for g in goals]
    return StepResult(
        3, "Goals", subtitle, "ok",
        f"{len(goals)} goal(s) defined.",
        None,
        items=items,
    ), goals


def _check_features(specs_path: Path, goals: list[dict]) -> tuple[StepResult, list[dict]]:
    subtitle = "Ideas and work items tracked through the full lifecycle."
    specs = all_specs(specs_path)
    goal_ids = {g["id"] for g in goals}

    if not specs:
        return StepResult(
            4, "Features", subtitle, "error",
            "No features captured yet.",
            'Run: meridian new "your idea"  to capture your first feature.',
        ), []

    _blank = ("~", "", "None")
    no_goal = [
        s for s in specs
        if not s.get("goal") or str(s.get("goal")).strip() in _blank
    ]
    unlinked_goal = [
        s for s in specs
        if s.get("goal") and str(s.get("goal")).strip() not in _blank
        and goal_ids and str(s.get("goal")).strip() not in goal_ids
    ]

    status_icon = {
        "idea": "💡", "draft": "📝", "in-progress": "🔨",
        "blocked": "🚫", "done": "✅", "in-production": "🚀", "abandoned": "🗑",
    }
    items = [
        f"{str(s.get('id','?')).upper()}  "
        f"{s.get('name','Untitled')[:48]}  "
        f"{status_icon.get(s.get('status','idea'), '')} {s.get('status','idea')}  "
        f"goal:{s.get('goal') or '—'}"
        for s in specs
    ]

    if no_goal:
        names = ", ".join(str(s.get("id", "?")).upper() for s in no_goal[:3])
        suffix = f" and {len(no_goal) - 3} more" if len(no_goal) > 3 else ""
        return StepResult(
            4, "Features", subtitle, "warn",
            f"{len(specs)} feature(s) captured, {len(no_goal)} without a goal "
            f"({names}{suffix}).",
            "Edit each spec's frontmatter: set  goal: <goal-id>",
            items=items,
        ), specs

    if not goals:
        return StepResult(
            4, "Features", subtitle, "warn",
            f"{len(specs)} feature(s) captured; all reference goals not yet created.",
            "Run /goal new  to create the goal files they reference.",
            items=items,
        ), specs

    if unlinked_goal:
        names = ", ".join(str(s.get("id", "?")).upper() for s in unlinked_goal[:3])
        suffix = f" and {len(unlinked_goal) - 3} more" if len(unlinked_goal) > 3 else ""
        return StepResult(
            4, "Features", subtitle, "warn",
            f"{len(specs)} feature(s) captured, {len(unlinked_goal)} reference unknown goals "
            f"({names}{suffix}).",
            "Check goal IDs in each spec's frontmatter match files in specs/goals/.",
            items=items,
        ), specs

    return StepResult(
        4, "Features", subtitle, "ok",
        f"{len(specs)} feature(s) captured, all linked to goals.",
        None,
        items=items,
    ), specs


def _check_elaboration(specs: list[dict]) -> StepResult:
    subtitle = "Structured specs with appetite, acceptance criteria, and scope."

    if not specs:
        return StepResult(5, "Specs", subtitle, "error", "No features to elaborate.", None)

    ideas = [s for s in specs if s.get("status") == "idea"]
    active_statuses = {"draft", "in-progress", "blocked"}
    no_appetite = [
        s for s in specs
        if s.get("status") in active_statuses and not s.get("appetite")
    ]
    no_confidence = [
        s for s in specs
        if s.get("status") in active_statuses
        and s.get("confidence") not in CONFIDENCE_VALUES
    ]

    if len(ideas) == len(specs):
        first = str(ideas[0].get("id", "feat-001")).upper()
        return StepResult(
            5, "Specs", subtitle, "warn",
            f"All {len(specs)} feature(s) still at 'idea' — none elaborated yet.",
            f"Run /spec  to elaborate {first} into a full structured spec.",
        )

    if no_appetite:
        names = ", ".join(str(s.get("id", "?")).upper() for s in no_appetite[:3])
        suffix = f" and {len(no_appetite) - 3} more" if len(no_appetite) > 3 else ""
        return StepResult(
            5, "Specs", subtitle, "warn",
            f"{len(no_appetite)} active feature(s) missing appetite: {names}{suffix}.",
            "Edit frontmatter: set  appetite: xs | s | m | l",
        )

    if ideas:
        names = ", ".join(str(s.get("id", "?")).upper() for s in ideas[:3])
        suffix = f" and {len(ideas) - 3} more" if len(ideas) > 3 else ""
        return StepResult(
            5, "Specs", subtitle, "warn",
            f"{len(ideas)} feature(s) still at 'idea': {names}{suffix}.",
            "Run /spec  to elaborate the next one.",
        )

    if no_confidence:
        names = ", ".join(str(s.get("id", "?")).upper() for s in no_confidence[:3])
        suffix = f" and {len(no_confidence) - 3} more" if len(no_confidence) > 3 else ""
        return StepResult(
            5, "Specs", subtitle, "warn",
            f"{len(no_confidence)} active feature(s) missing confidence rating: {names}{suffix}.",
            "Edit frontmatter: set  confidence: low | medium | high  "
            "(how well the problem is understood)",
        )

    return StepResult(
        5, "Specs", subtitle, "ok",
        f"All {len(specs)} feature(s) elaborated with appetite and confidence set.",
        None,
    )


def _check_research(specs_path: Path, specs: list[dict]) -> StepResult:
    subtitle = "PDFs, URLs, and docs attached as research corpus for features."

    if not specs:
        return StepResult(6, "Research", subtitle, "error", "No features to enrich.", None)

    no_sources = [
        str(s.get("id", "?")).upper()
        for s in specs
        if not (s.get("sources") or [])
    ]

    if len(no_sources) == len(specs):
        first = no_sources[0].lower()
        return StepResult(
            6, "Research", subtitle, "warn",
            "No features have research sources attached yet.",
            f"Run: meridian enrich {first} <pdf|url|file>",
        )

    if no_sources:
        names = ", ".join(no_sources[:3])
        suffix = f" and {len(no_sources) - 3} more" if len(no_sources) > 3 else ""
        return StepResult(
            6, "Research", subtitle, "warn",
            f"{len(no_sources)} feature(s) have no sources: {names}{suffix}.",
            f"Run: meridian enrich {no_sources[0].lower()} <pdf|url|file>",
        )

    return StepResult(
        6, "Research", subtitle, "ok",
        "All features have at least one research source.",
        None,
    )


def _stale_blocked_days(spec: dict) -> int | None:
    """Return how many days a feature has been blocked, or None if not determinable."""
    blocked_at = spec.get("blocked_at")
    if not blocked_at:
        return None
    try:
        delta = date.today() - date.fromisoformat(str(blocked_at))
        return delta.days
    except (ValueError, TypeError):
        return None


def _check_cycles(specs: list[dict]) -> StepResult:
    subtitle = "Betting cycles — what's committed this cycle vs. icebox."
    active_statuses = {"draft", "in-progress", "blocked"}
    active = [s for s in specs if s.get("status") in active_statuses]

    if not active:
        return StepResult(
            7, "Cycles", subtitle, "ok",
            "No active features to assign to a cycle.",
            None,
        )

    # Stale-blocked check takes priority — it's an active risk
    blocked = [s for s in active if s.get("status") == "blocked"]
    stale = [
        (s, days)
        for s in blocked
        if (days := _stale_blocked_days(s)) is not None and days >= _STALE_BLOCKED_DAYS
    ]
    if stale:
        stale_parts = [
            f"{str(s.get('id','?')).upper()} ({days}d — {s.get('blocked_by') or 'no reason recorded'})"
            for s, days in stale[:3]
        ]
        suffix = f" and {len(stale) - 3} more" if len(stale) > 3 else ""
        first_id = str(stale[0][0].get("id", "feat-001")).lower()
        return StepResult(
            7, "Cycles", subtitle, "warn",
            f"{len(stale)} feature(s) have been blocked for {_STALE_BLOCKED_DAYS}+ days: "
            f"{', '.join(stale_parts)}{suffix}.",
            f"Resolve the block or abandon: meridian close {first_id} --status in-progress  "
            f"(or --status abandoned --abandoned-reason <reason>)",
        )

    no_cycle = [s for s in active if not s.get("cycle")]
    if no_cycle:
        names = ", ".join(str(s.get("id", "?")).upper() for s in no_cycle[:3])
        suffix = f" and {len(no_cycle) - 3} more" if len(no_cycle) > 3 else ""
        return StepResult(
            7, "Cycles", subtitle, "warn",
            f"{len(no_cycle)} active feature(s) not assigned to any cycle: {names}{suffix}.",
            f"Run: meridian cycle {str(no_cycle[0].get('id','feat-001')).lower()} --set <cycle>  "
            "(e.g. 2026-Q2)",
        )

    cycles = {s.get("cycle") for s in active if s.get("cycle")}
    return StepResult(
        7, "Cycles", subtitle, "ok",
        f"All {len(active)} active feature(s) assigned to cycles: {', '.join(sorted(str(c) for c in cycles))}.",
        None,
    )


_TASKS_STUB = "*No tasks yet"


def _check_tasks(specs_path: Path, specs: list[dict]) -> StepResult:
    subtitle = "tasks.md — atomic work units for in-progress features."

    in_progress = [s for s in specs if s.get("status") == "in-progress"]

    if not in_progress:
        return StepResult(
            8, "Tasks", subtitle, "ok",
            "No features currently in-progress.",
            None,
        )

    no_tasks: list[str] = []
    all_done: list[str] = []

    for s in in_progress:
        feat_id = str(s.get("id", "?")).upper()
        tasks_file = Path(s["_path"]).parent / "tasks.md"
        if not tasks_file.exists():
            no_tasks.append(feat_id)
            continue
        content = tasks_file.read_text().strip()
        if content.startswith(_TASKS_STUB) or len(content) < 100:
            no_tasks.append(feat_id)
            continue
        progress = task_progress(tasks_file.parent)
        if progress is not None:
            checked, total = progress
            if checked == total:
                all_done.append(feat_id)

    if no_tasks:
        names = ", ".join(no_tasks[:3])
        suffix = f" and {len(no_tasks) - 3} more" if len(no_tasks) > 3 else ""
        return StepResult(
            8, "Tasks", subtitle, "warn",
            f"{len(no_tasks)} in-progress feature(s) have no tasks.md: {names}{suffix}.",
            "Run /tasks  to generate an atomic task list.",
        )

    if all_done:
        names = ", ".join(all_done[:3])
        suffix = f" and {len(all_done) - 3} more" if len(all_done) > 3 else ""
        return StepResult(
            8, "Tasks", subtitle, "warn",
            f"{len(all_done)} feature(s) have all tasks checked off but are still in-progress: "
            f"{names}{suffix}.",
            f"Run: meridian close {all_done[0].lower()} --status done  to mark it complete.",
        )

    return StepResult(
        8, "Tasks", subtitle, "ok",
        f"All {len(in_progress)} in-progress feature(s) have tasks.md.",
        None,
    )


# ─── Public API ───────────────────────────────────────────── #

def run_guide(cfg: MeridianConfig) -> list[StepResult]:
    """Run all project checks in order and return the results."""
    vision = _check_vision(cfg.specs_path)
    steering = _check_steering(cfg.specs_path)
    goals_check, goals = _check_goals(cfg.specs_path)
    features_check, specs = _check_features(cfg.specs_path, goals)
    elaboration = _check_elaboration(specs)
    research = _check_research(cfg.specs_path, specs)
    cycles = _check_cycles(specs)
    tasks = _check_tasks(cfg.specs_path, specs)
    return [vision, steering, goals_check, features_check, elaboration, research, cycles, tasks]


def first_action(steps: list[StepResult]) -> str | None:
    """Return the next_action from the first non-OK step."""
    for step in steps:
        if step.status != "ok" and step.next_action:
            return step.next_action
    return None
