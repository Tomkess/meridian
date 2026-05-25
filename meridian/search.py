"""
Semantic search pipeline: query → embed → ANN → optional BGE rerank.
"""
from __future__ import annotations

from meridian.config import MeridianConfig
from meridian.enrich import embed, search_similar


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


# ─── Main search ──────────────────────────────────────────────────────────── #

def semantic_search(
    cfg: MeridianConfig,
    query: str,
    feat_id_filter: str | None = None,
    limit: int = 5,
    rerank: bool | None = None,  # None = auto (use reranker if available)
) -> list[dict]:
    """
    Embed query → ANN (top-20) → optional BGE rerank → top-limit.

    Each result dict contains:
        feat_id, source_name, chunk_idx, text, _distance, rerank_score (if reranked)
    """
    if not cfg.lancedb_path.exists():
        return []

    # 1. Embed query
    query_vec = embed(query, model=cfg.ollama_model)

    # 2. ANN — fetch more candidates when reranking
    use_rerank = _reranker_available() if rerank is None else rerank
    ann_limit = limit * 4 if use_rerank else limit
    raw = search_similar(cfg.lancedb_path, query_vec, limit=ann_limit,
                         feat_id_filter=feat_id_filter)

    if not raw:
        return []

    # 3. Rerank if available
    if use_rerank:
        try:
            passages = [r["text"] for r in raw]
            ranked = _bge_rerank(query, passages, cfg.reranker_model, top_k=limit)
            results = []
            for idx, score in ranked:
                r = dict(raw[idx])
                r["rerank_score"] = float(score)
                results.append(r)
            return results
        except (ImportError, Exception):
            pass  # fall through to raw ANN

    return raw[:limit]


def format_results(results: list[dict], query: str) -> str:
    """Plain-text formatting suitable for skill/Claude consumption."""
    if not results:
        return f'No results found for "{query}". Run `meridian enrich` to add research.'

    lines = [f'Search results for: "{query}"\n']
    for i, r in enumerate(results, 1):
        score = r.get("rerank_score", r.get("_distance"))
        score_str = f"  score={score:.3f}" if isinstance(score, float) else ""
        text_preview = r["text"][:300].replace("\n", " ").strip()
        lines.append(
            f"{i}. [{r['feat_id']}] {r['source_name']} chunk {r['chunk_idx']}{score_str}\n"
            f"   {text_preview}"
        )
    return "\n\n".join(lines)
