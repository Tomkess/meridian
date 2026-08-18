"""Suggest which project a captured idea belongs to (FEAT-008).

This is only possible because FEAT-007 put a ``project`` column on the shared
LanceDB index. Embedding a capture and querying the store unscoped returns hits
from every repo; each hit is a vote for its project. The column that stops repos
clobbering each other is the same one that lets a captured idea find its home.

Suggestions are advisory. Nothing here files anything — a human always names the
target (spec AC18).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from meridian.inbox import Capture
from meridian.registry import ProjectEntry

logger = logging.getLogger(__name__)

TOP_N = 3


@dataclass
class Suggestion:
    slug: str
    score: float
    basis: str  # "explicit" | "index" | "purpose"


def _score_from_distance(distance: float | None) -> float:
    """Turn a LanceDB L2 distance into a similarity-ish score in (0, 1].

    Monotonic and bounded, which is all that ranking needs. Deliberately not
    presented as a probability — a low-confidence hit must read as low
    confidence, not as a recommendation.
    """
    if distance is None:
        return 0.0
    return 1.0 / (1.0 + max(0.0, float(distance)))


def suggest(
    capture: Capture,
    entries: list[ProjectEntry],
    lancedb_path: Path,
    ollama_model: str,
    *,
    limit: int = TOP_N,
) -> list[Suggestion]:
    """Rank candidate projects for a capture, best first.

    Takes the store path and model directly rather than a ``MeridianConfig``:
    triage is a machine-global operation and must work from any directory,
    including outside every repo. Requiring a config would make suggestions
    silently vanish exactly where the inbox is most likely to be read.

    An explicit hint short-circuits before any embedding call: routing a capture
    the user already labelled must not require Ollama to be running.
    """
    if capture.project:
        return [Suggestion(slug=capture.project, score=1.0, basis="explicit")]

    if not capture.is_routable or not entries:
        return []

    from meridian.enrich import embed, search_similar

    try:
        vector = embed(capture.text, model=ollama_model)
    except Exception as e:
        # Ollama down, model missing, index unreadable — triage must still list
        # and route captures manually.
        logger.warning("Could not embed capture for routing (%s)", e)
        return []

    known = {e.slug for e in entries}
    scores: dict[str, float] = {}

    try:
        hits = search_similar(lancedb_path, vector, limit=50, project=None)
    except Exception as e:
        logger.warning("Could not query the shared index for routing (%s)", e)
        hits = []

    for hit in hits:
        slug = hit.get("project")
        if not slug or slug not in known:
            continue
        # Best single hit per project, not a sum: one strongly matching chunk is
        # a better signal than a project that happens to have more rows.
        scores[slug] = max(scores.get(slug, 0.0), _score_from_distance(hit.get("_distance")))

    ranked = [Suggestion(slug=s, score=v, basis="index") for s, v in scores.items()]

    # AC12: a project with nothing indexed must not be permanently unroutable.
    unindexed = [e for e in entries if e.slug not in scores and e.purpose]
    if unindexed:
        ranked.extend(_purpose_suggestions(unindexed, vector, ollama_model))

    ranked.sort(key=lambda s: s.score, reverse=True)
    return ranked[:limit]


def _purpose_suggestions(
    entries: list[ProjectEntry],
    vector: list[float],
    ollama_model: str,
) -> list[Suggestion]:
    """Score projects with no indexed research against their registry purpose."""
    from meridian.enrich import embed

    out = []
    for entry in entries:
        try:
            purpose_vec = embed(entry.purpose, model=ollama_model)
        except Exception:
            continue
        out.append(Suggestion(
            slug=entry.slug,
            score=_cosine(vector, purpose_vec),
            basis="purpose",
        ))
    return out


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if not na or not nb:
        return 0.0
    # Clamp to [0, 1]: negative similarity is no signal, not anti-signal.
    return max(0.0, dot / (na * nb))
