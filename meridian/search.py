"""
Semantic search pipeline: query → embed → ANN → optional BGE rerank.

FEAT-024 adds a second pass over *other* projects' rows — prior art — which is
ranked separately and never interleaved with the local results. See
``search_with_prior_art`` for why the two are kept apart.
"""
from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from meridian.config import MeridianConfig
from meridian.enrich import embed, search_similar
from meridian.registry import ProjectEntry, all_projects
from meridian.specs import feat_display_name

logger = logging.getLogger(__name__)

# FEAT-024 defaults. Small on purpose: prior art is a lead to follow, not a
# reading list, and every extra row costs an agent context it would rather
# spend on the local corpus.
PRIOR_ART_LIMIT = 5
PRIOR_ART_PER_PROJECT = 2

# The foreign pass is filtered and capped in Python, so it has to over-fetch:
# LanceDB returns the globally nearest rows, and the corpus is uneven enough
# (73 chunks in one project, 2 in another) that a small window can be filled
# entirely by the biggest repo. Widened once if the window came back saturated.
_MIN_CANDIDATE_POOL = 40
_POOL_WIDENINGS = 1


# ─── Reranker ─────────────────────────────────────────────────────────────── #

def _bge_rerank(
    query: str,
    passages: list[str],
    model_name: str,
    top_k: int,
) -> list[tuple[int, float]]:
    """Cross-encoder rerank. Raises ImportError if sentence-transformers absent."""
    from sentence_transformers import CrossEncoder  # optional heavy dep
    model = CrossEncoder(model_name)
    scores = model.predict([(query, p) for p in passages])
    ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
    return ranked[:top_k]


def _reranker_available() -> bool:
    try:
        import sentence_transformers  # noqa: F401
        return True
    except ImportError:
        return False


def _rerank_rows(
    query: str,
    rows: list[dict],
    model_name: str,
    top_k: int,
) -> list[dict] | None:
    """Reorder *rows* with the cross-encoder, or ``None`` when it cannot run.

    ``None`` — rather than the untouched rows — so the caller can tell "the
    reranker declined" from "the reranker ranked them this way", and fall back
    to raw ANN order deliberately.
    """
    if not rows:
        return []
    try:
        ranked = _bge_rerank(query, [r["text"] for r in rows], model_name, top_k=top_k)
    except ImportError:
        return None  # sentence-transformers not installed
    except Exception as e:
        # V4: surface reranker failures so they are visible with MERIDIAN_DEBUG=1
        logger.warning("BGE reranker failed (%s) — falling back to ANN results", e)
        return None
    out = []
    for idx, score in ranked:
        r = dict(rows[idx])
        r["rerank_score"] = float(score)
        out.append(r)
    return out


# ─── Main search ──────────────────────────────────────────────────────────── #

def semantic_search(
    cfg: MeridianConfig,
    query: str,
    feat_id_filter: str | None = None,
    limit: int = 5,
    rerank: bool | None = None,  # None = auto (use reranker if available)
    all_projects: bool = False,
) -> list[dict]:
    """
    Embed query → ANN (top-20) → optional BGE rerank → top-limit.

    Scoped to ``cfg.project`` unless *all_projects* is set: the LanceDB store is
    shared by every Meridian install, so an unscoped query returns other repos'
    research as if it were this one's.

    Each result dict contains:
        project, feat_id, source_name, chunk_idx, text, _distance,
        rerank_score (if reranked)
    """
    if not cfg.lancedb_path.exists():
        return []

    # 1. Embed query
    query_vec = embed(query, model=cfg.ollama_model)

    # 2/3. ANN, then rerank if available
    use_rerank = _reranker_available() if rerank is None else rerank
    return _ann_then_rerank(
        cfg, query, query_vec,
        limit=limit,
        use_rerank=use_rerank,
        feat_id_filter=feat_id_filter,
        project=None if all_projects else cfg.project,
    )


def _ann_then_rerank(
    cfg: MeridianConfig,
    query: str,
    query_vec: list[float],
    *,
    limit: int,
    use_rerank: bool,
    feat_id_filter: str | None,
    project: str | None,
) -> list[dict]:
    """One ANN window, optionally reranked. Shared by both retrieval passes."""
    ann_limit = limit * 4 if use_rerank else limit
    raw = search_similar(cfg.lancedb_path, query_vec, limit=ann_limit,
                         feat_id_filter=feat_id_filter,
                         project=project)
    if not raw:
        return []
    if use_rerank:
        reranked = _rerank_rows(query, raw, cfg.reranker_model, top_k=limit)
        if reranked is not None:
            return reranked
    return raw[:limit]


# ─── Prior art (FEAT-024) ─────────────────────────────────────────────────── #


def _score_kind(hit: dict) -> str | None:
    """Which field carries this hit's relevance, or None if it carries neither."""
    for key in ("rerank_score", "_distance"):
        value = hit.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return key
    return None


def relevance_bar(local_hits: list[dict]) -> tuple[str, float] | None:
    """The bar a foreign hit must clear: the *weakest local hit shown*.

    "The same relevance bar applied locally" (AC4) has to mean something
    concrete, and there is no absolute distance threshold to lean on — the
    numbers only mean anything relative to this query and this embedding space.
    So the bar is the least relevant row this repo's own corpus was allowed to
    show: a foreign hit earns its place only by being at least that relevant.

    Returns ``None`` when there are no local hits, which deliberately admits
    every foreign candidate. A repo with no research of its own is exactly when
    prior art is worth the most, and there is no local evidence to calibrate
    against. The per-project cap and the section limit still apply.

    Both passes are scored the same way — same query vector, same table, and
    the same reranker decision — so the comparison is like for like.
    """
    scored = [(kind, float(h[kind])) for h in local_hits if (kind := _score_kind(h))]
    if not scored:
        return None
    kind = scored[0][0]
    values = [v for k, v in scored if k == kind]
    # rerank_score: higher is better → the weakest is the smallest.
    # _distance:    lower  is better → the weakest is the largest.
    return (kind, min(values)) if kind == "rerank_score" else (kind, max(values))


def clears_bar(hit: dict, bar: tuple[str, float] | None) -> bool:
    """True if *hit* is at least as relevant as *bar*.

    A hit scored on a different axis than the bar is kept rather than dropped:
    silently discarding research because two passes disagreed about which
    number to compare would look exactly like the feature being broken.
    """
    if bar is None:
        return True
    kind, threshold = bar
    value = hit.get(kind)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return True
    return float(value) >= threshold if kind == "rerank_score" else float(value) <= threshold


def _cap_per_project(hits: list[dict], *, limit: int, per_project: int) -> list[dict]:
    """Take the best *limit* hits, no more than *per_project* from any one repo.

    Without the cap a 73-chunk repo fills the whole section and the other four
    projects are invisible — which is the corpus we actually have.
    """
    taken: dict[str, int] = {}
    out: list[dict] = []
    for hit in hits:
        slug = str(hit.get("project") or "")
        if per_project > 0 and taken.get(slug, 0) >= per_project:
            continue
        taken[slug] = taken.get(slug, 0) + 1
        out.append(hit)
        if len(out) >= limit:
            break
    return out


def _prior_art_pass(
    cfg: MeridianConfig,
    query: str,
    query_vec: list[float],
    *,
    limit: int,
    per_project: int,
    use_rerank: bool,
    bar: tuple[str, float] | None,
) -> list[dict]:
    """Rank other projects' rows on their own, then filter and cap.

    No ``feat_id_filter``: a feature ID only means something inside the project
    that wrote it (FEAT-001 currently exists in three repos), so scoping the
    foreign pass by a local one would filter on a coincidence of numbering.
    """
    if limit <= 0:
        return []
    pool = max(_MIN_CANDIDATE_POOL, limit * max(per_project, 1) * 4)
    selected: list[dict] = []
    for _ in range(_POOL_WIDENINGS + 1):
        raw = search_similar(cfg.lancedb_path, query_vec, limit=pool, project=None)
        foreign = [r for r in raw if r.get("project") != cfg.project]
        if use_rerank and foreign:
            reranked = _rerank_rows(query, foreign, cfg.reranker_model, top_k=len(foreign))
            if reranked is not None:
                foreign = reranked
        selected = _cap_per_project(
            [h for h in foreign if clears_bar(h, bar)],
            limit=limit, per_project=per_project,
        )
        if len(selected) >= limit or len(raw) < pool:
            break  # enough, or the store had nothing more to give
        pool *= 4
    return selected


# ─── Attribution: turning a foreign hit into something openable ───────────── #

UNTRACKED_PROJECT = "project is not tracked in ~/.meridian/projects.toml"
MISSING_REPO_PATH = "the repo path in the registry no longer exists"
MISSING_FEATURE_DIR = "no matching feature directory in that repo"


class FeatureLocator:
    """Resolve ``(project slug, feat id)`` to an absolute feature directory.

    A chunk of text from an unnamed repo is trivia; the registry is what turns
    it into somewhere to go. Registry reads are done once and directory layouts
    memoised, so a section of hits costs one pass over ``projects.toml``.
    """

    def __init__(self, entries: list[ProjectEntry] | None = None) -> None:
        # entries=None reads the registry — and lets RegistryUnreadableError
        # out. A corrupt registry must never read as "nothing is tracked"
        # (FEAT-013); callers that already handled it pass their own list.
        source = all_projects() if entries is None else entries
        self._entries = {e.slug: e for e in source}
        self._specs_dirname: dict[Path, str] = {}

    def _specs_dir(self, repo: Path) -> Path:
        """Where that repo keeps its specs — it may not be ``specs/``."""
        cached = self._specs_dirname.get(repo)
        if cached is None:
            cached = "specs"
            config = repo / ".meridian.toml"
            try:
                with open(config, "rb") as f:
                    raw = tomllib.load(f)
                cached = str(raw.get("meridian", {}).get("specs_path") or "specs")
            except (OSError, tomllib.TOMLDecodeError, AttributeError):
                pass  # no readable config — the default is the safe guess
            self._specs_dirname[repo] = cached
        return repo / cached

    def locate(self, project: str, feat_id: str) -> tuple[Path | None, Path | None, str | None]:
        """Return ``(repo_path, feature_dir, unresolvable_reason)``."""
        entry = self._entries.get(project)
        if entry is None:
            return None, None, UNTRACKED_PROJECT
        repo = entry.path
        if not repo.is_dir():
            # Reported, never hidden: the research is real, the disk moved.
            return repo, None, MISSING_REPO_PATH
        specs = self._specs_dir(repo)
        for candidate in (feat_id, feat_id.upper(), feat_id.lower()):
            if not candidate:
                continue
            matches = sorted(p for p in specs.glob(f"{candidate}_*") if p.is_dir())
            if matches:
                return repo, matches[0], None
            exact = specs / candidate
            if exact.is_dir():
                return repo, exact, None
        return repo, None, MISSING_FEATURE_DIR


def attribute_prior_art(
    hits: list[dict],
    entries: list[ProjectEntry] | None = None,
    locator: FeatureLocator | None = None,
) -> list[dict]:
    """Add repo and feature paths to each foreign hit.

    Every hit comes back, resolvable or not (AC7). Each gains::

        project_path, feat_path, resolvable, unresolvable_reason
    """
    resolver = locator or FeatureLocator(entries)
    out = []
    for hit in hits:
        repo, feat_dir, reason = resolver.locate(
            str(hit.get("project") or ""), str(hit.get("feat_id") or "")
        )
        row = dict(hit)
        row["project_path"] = str(repo) if repo is not None else None
        row["feat_path"] = str(feat_dir) if feat_dir is not None else None
        row["resolvable"] = feat_dir is not None
        row["unresolvable_reason"] = reason
        out.append(row)
    return out


@dataclass
class PriorArtResults:
    """Two separately ranked sections. They are never merged."""

    local: list[dict] = field(default_factory=list)
    prior_art: list[dict] = field(default_factory=list)
    bar: tuple[str, float] | None = None


def search_with_prior_art(
    cfg: MeridianConfig,
    query: str,
    *,
    feat_id_filter: str | None = None,
    limit: int = 5,
    prior_art_limit: int = PRIOR_ART_LIMIT,
    per_project: int = PRIOR_ART_PER_PROJECT,
    rerank: bool | None = None,
    entries: list[ProjectEntry] | None = None,
) -> PriorArtResults:
    """Local hits first and complete, then a separate prior-art section.

    The two are ranked apart rather than merged because the shared corpus is
    wildly uneven — 73 chunks in one project against 2 in another — so a single
    relevance ordering is won on volume by whichever repo has written the most,
    and a search run from the small repo returns almost nothing of its own.
    Separation also matches how the answer is used: this project's research is
    context, another project's is a lead.

    One embed call feeds both passes.
    """
    if not cfg.lancedb_path.exists():
        return PriorArtResults()

    query_vec = embed(query, model=cfg.ollama_model)
    use_rerank = _reranker_available() if rerank is None else rerank

    local = _ann_then_rerank(
        cfg, query, query_vec,
        limit=limit, use_rerank=use_rerank,
        feat_id_filter=feat_id_filter, project=cfg.project,
    )
    if prior_art_limit <= 0:
        return PriorArtResults(local=local)

    bar = relevance_bar(local)
    foreign = _prior_art_pass(
        cfg, query, query_vec,
        limit=prior_art_limit, per_project=per_project,
        use_rerank=use_rerank, bar=bar,
    )
    return PriorArtResults(
        local=local,
        prior_art=attribute_prior_art(foreign, entries),
        bar=bar,
    )


def result_label(result: dict, cfg: MeridianConfig | None = None) -> str:
    """Human label for one hit, never mis-attributing a foreign row.

    A feat_id only means something inside the project that wrote it. Resolving
    another repo's FEAT-003 against the local specs directory would render it
    with the local FEAT-003's name — wrong provenance presented as fact — so
    foreign rows are labelled ``<project>/FEAT-003`` and left unresolved.
    """
    feat_id = result["feat_id"]
    if cfg is None:
        return feat_id
    row_project = result.get("project")
    if row_project and row_project != cfg.project:
        return f"{row_project}/{feat_id}"
    return feat_display_name(cfg.specs_path, feat_id)


def format_results(
    results: list[dict],
    query: str,
    cfg: MeridianConfig | None = None,
) -> str:
    """Plain-text formatting suitable for skill/Claude consumption.

    Pass *cfg* to include the human-readable feature name alongside the
    feat_id.  When *cfg* is absent the bare feat_id is used (backward-
    compatible with callers that don't have a config available).
    """
    if not results:
        return f'No results found for "{query}". Run `meridian enrich` to add research.'

    lines = [f'Search results for: "{query}"\n']
    for i, r in enumerate(results, 1):
        score = r.get("rerank_score", r.get("_distance"))
        score_str = f"  score={score:.3f}" if isinstance(score, float) else ""
        text_preview = r["text"][:300].replace("\n", " ").strip()
        label = result_label(r, cfg)
        lines.append(
            f"{i}. [{label}] {r['source_name']} chunk {r['chunk_idx']}{score_str}\n"
            f"   {text_preview}"
        )
    return "\n\n".join(lines)
