"""
meridian/databricks.py — thin Databricks Jobs API client.

No SDK dependency — just httpx. Reads host + token from MeridianConfig.
"""

from __future__ import annotations

import os
from typing import Optional

import httpx as requests  # httpx is already a meridian dep; alias keeps the call sites unchanged

from meridian.config import MeridianConfig


class DatabricksError(Exception):
    pass


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #

def _base(cfg: MeridianConfig) -> str:
    host = cfg.databricks_host.rstrip("/")
    if not host:
        raise DatabricksError(
            "databricks.host is not set in .meridian.toml.\n"
            "Add:  [databricks]\n"
            "      host = \"https://your-workspace.azuredatabricks.net\""
        )
    return host


def _headers(cfg: MeridianConfig) -> dict[str, str]:
    token_ref = cfg.databricks_token_env
    # token_env can be an env var name ("DATABRICKS_TOKEN") *or* a literal token
    # value ("dapi…"). Try env var first; fall back to using the value directly.
    token = os.environ.get(token_ref, "") or token_ref
    if not token:
        raise DatabricksError(
            "Databricks token not set. Set token_env in .meridian.toml "
            "to an env var name or a literal token value."
        )
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# State normalisation
# --------------------------------------------------------------------------- #

# Priority order for aggregation: RUNNING > FAILED = TIMEDOUT > CANCELED > SUCCESS > PENDING
_STATE_PRIORITY: dict[str, int] = {
    "RUNNING":   5,
    "FAILED":    4,
    "TIMEDOUT":  4,
    "CANCELED":  3,
    "SUCCESS":   2,
    "PENDING":   1,
}


def _normalise_task_state(life: str, result: str) -> str:
    """Map raw life_cycle_state + result_state into a single normalised token."""
    if life in ("PENDING", "RUNNING", "TERMINATING", "BLOCKED"):
        return "RUNNING"
    return result or life  # TERMINATED → result_state; others fall back to life


def _aggregate_states(states: list[str]) -> str:
    """Return the worst state across a list (highest priority wins)."""
    if not states:
        return "UNKNOWN"
    return max(states, key=lambda s: _STATE_PRIORITY.get(s.upper(), 0))


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def resolve_job(cfg: MeridianConfig, id_or_name: str) -> tuple[int, str]:
    """
    Given a job ID (numeric string) or job name, return (job_id, job_name).

    Tries numeric ID first. Falls back to name search with exact match.
    Raises DatabricksError if not found or ambiguous.
    """
    base = _base(cfg)
    headers = _headers(cfg)

    # ── Numeric job ID ──────────────────────────────────────────────────────
    if id_or_name.isdigit():
        job_id = int(id_or_name)
        resp = requests.get(
            f"{base}/api/2.1/jobs/get",
            params={"job_id": job_id},
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 200:
            job_name = resp.json().get("settings", {}).get("name", str(job_id))
            return (job_id, job_name)
        raise DatabricksError(
            f"Job ID {job_id} not found (HTTP {resp.status_code})."
        )

    # ── Name lookup ─────────────────────────────────────────────────────────
    resp = requests.get(
        f"{base}/api/2.1/jobs/list",
        params={"name": id_or_name},
        headers=headers,
        timeout=10,
    )
    if resp.status_code != 200:
        raise DatabricksError(
            f"Databricks API error: {resp.status_code} — {resp.text[:200]}"
        )

    jobs = resp.json().get("jobs", [])
    # Exact name match (the API does prefix/substring search)
    matches = [j for j in jobs if j.get("settings", {}).get("name") == id_or_name]

    if not matches:
        raise DatabricksError(f"No Databricks job found with name '{id_or_name}'.")
    if len(matches) > 1:
        ids = ", ".join(str(j["job_id"]) for j in matches)
        raise DatabricksError(
            f"Multiple jobs named '{id_or_name}': {ids}. Pass a numeric job ID instead."
        )

    j = matches[0]
    return (j["job_id"], j.get("settings", {}).get("name", id_or_name))


def latest_run_state(
    cfg: MeridianConfig, job_id: int, timeout: int = 5
) -> Optional[str]:
    """
    Return the normalised state of the most recent run for job_id, or None.

    When task_keys are not relevant — tracks the overall job run state.
    """
    try:
        base = _base(cfg)
        headers = _headers(cfg)
        resp = requests.get(
            f"{base}/api/2.1/jobs/runs/list",
            params={"job_id": job_id, "limit": 1, "active_only": "false"},
            headers=headers,
            timeout=timeout,
        )
        if resp.status_code != 200:
            return None
        runs = resp.json().get("runs", [])
        if not runs:
            return None
        run = runs[0]
        life = run.get("state", {}).get("life_cycle_state", "")
        result = run.get("state", {}).get("result_state", "")
        return _normalise_task_state(life, result)
    except Exception:
        return None


def latest_task_states(
    cfg: MeridianConfig,
    job_id: int,
    task_keys: list[str],
    timeout: int = 8,
) -> dict[str, Optional[str]]:
    """
    Return a mapping of task_key → normalised state for the most recent run.

    Requires two API calls: runs/list to get the latest run_id, then
    runs/get to fetch per-task states.

    Returns {} (empty) on any error so callers can degrade gracefully.
    """
    try:
        base = _base(cfg)
        headers = _headers(cfg)

        # Step 1: get latest run_id
        r1 = requests.get(
            f"{base}/api/2.1/jobs/runs/list",
            params={"job_id": job_id, "limit": 1, "active_only": "false"},
            headers=headers,
            timeout=timeout,
        )
        if r1.status_code != 200:
            return {}
        runs = r1.json().get("runs", [])
        if not runs:
            return {}
        run_id = runs[0]["run_id"]

        # Step 2: get full run detail with per-task states
        r2 = requests.get(
            f"{base}/api/2.1/jobs/runs/get",
            params={"run_id": run_id},
            headers=headers,
            timeout=timeout,
        )
        if r2.status_code != 200:
            return {}

        task_list = r2.json().get("tasks", [])
        result: dict[str, Optional[str]] = {}
        for t in task_list:
            key = t.get("task_key", "")
            if key in task_keys:
                life = t.get("state", {}).get("life_cycle_state", "")
                res = t.get("state", {}).get("result_state", "")
                result[key] = _normalise_task_state(life, res)

        # Tasks not found in the run get None
        for k in task_keys:
            if k not in result:
                result[k] = None

        return result
    except Exception:
        return {}


def task_run_display(
    task_states: dict[str, Optional[str]],
    task_keys: list[str],
) -> str:
    """
    Aggregate per-task states into a compact display string.

      All success   →  ✅ 3/3
      Some failed   →  ❌ 1/3
      Any running   →  🔄 running
      Unknown/empty →  ∅
    """
    if not task_states:
        return "[dim]∅[/dim]"

    states = [task_states.get(k) for k in task_keys]
    known = [s for s in states if s is not None]
    n = len(task_keys)

    if not known:
        return "[dim]∅[/dim]"

    agg = _aggregate_states(known)
    agg_upper = agg.upper()

    if agg_upper == "RUNNING":
        return "[cyan]🔄 running[/cyan]"
    if agg_upper in ("FAILED", "TIMEDOUT"):
        failed = sum(1 for s in known if s and s.upper() in ("FAILED", "TIMEDOUT"))
        return f"[red]❌ {failed}/{n}[/red]"
    if agg_upper == "CANCELED":
        return "[dim]✗ canceled[/dim]"
    if agg_upper == "SUCCESS":
        ok = sum(1 for s in known if s and s.upper() == "SUCCESS")
        color = "green" if ok == n else "yellow"
        return f"[{color}]✅ {ok}/{n}[/{color}]"
    return f"[dim]{agg}[/dim]"


def run_state_display(state: Optional[str]) -> str:
    """Map a raw overall-run state to a coloured display string (Rich markup)."""
    if state is None:
        return "[dim]∅[/dim]"
    mapping: dict[str, str] = {
        "SUCCESS":  "[green]✅ Success[/green]",
        "FAILED":   "[red]❌ Failed[/red]",
        "TIMEDOUT": "[yellow]⏱ Timeout[/yellow]",
        "CANCELED": "[dim]✗ Canceled[/dim]",
        "RUNNING":  "[cyan]🔄 Running[/cyan]",
        "PENDING":  "[dim]⏳ Pending[/dim]",
    }
    return mapping.get(state.upper(), f"[dim]{state}[/dim]")
