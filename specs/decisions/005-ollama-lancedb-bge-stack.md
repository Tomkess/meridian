---
id: adr-005
date: 2026-05-22
status: accepted
---

# 005 — Ollama + LanceDB + bge-reranker stack

**Decision:** Use Ollama `mxbai-embed-large` for embeddings, LanceDB for vector store, `BAAI/bge-reranker-v2-m3` for reranking.

**Considered:** OpenAI embeddings (cost, API dependency), ChromaDB (less performant), FAISS (no metadata), cloud vector stores (infra overhead).

**Why:** Fully local, no cost, no API keys. M4 Pro handles mxbai-embed-large comfortably. Two-stage retrieval (ANN top-20 → rerank → top-3) gives much better signal than cosine similarity alone. LanceDB is file-based with zero server overhead.
