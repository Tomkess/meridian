"""
Research ingestion pipeline: source → extract → chunk → embed → LanceDB.
"""
import shutil
from pathlib import Path
from urllib.parse import urlparse

import httpx

from meridian.config import MeridianConfig


# ─── Text extraction ──────────────────────────────────────────────────────── #

def _is_url(s: str) -> bool:
    return s.startswith(("http://", "https://"))


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError("pypdf required: pip install pypdf")
    reader = PdfReader(str(path))
    pages = [p.extract_text() for p in reader.pages if p.extract_text()]
    return "\n\n".join(pages)


def _extract_url(url: str) -> str:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        raise RuntimeError("beautifulsoup4 required: pip install beautifulsoup4")
    resp = httpx.get(url, follow_redirects=True, timeout=30,
                     headers={"User-Agent": "Mozilla/5.0 meridian/0.1"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "aside", "header"]):
        tag.decompose()
    lines = [ln.strip() for ln in soup.get_text(separator="\n").splitlines() if ln.strip()]
    return "\n".join(lines)


def extract_text(source: str) -> str:
    if _is_url(source):
        return _extract_url(source)
    path = Path(source).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Source not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(path)
    # Treat everything else as plain text
    return path.read_text(errors="replace")


# ─── Chunking ─────────────────────────────────────────────────────────────── #

def chunk_text(text: str, max_words: int = 200, overlap: int = 25) -> list[str]:
    words = text.split()
    chunks, start = [], 0
    while start < len(words):
        end = min(start + max_words, len(words))
        chunk = " ".join(words[start:end]).strip()
        if len(chunk) > 80:
            chunks.append(chunk)
        start += max_words - overlap
    return chunks


# ─── Ollama embeddings ────────────────────────────────────────────────────── #

def embed(text: str, model: str, base_url: str = "http://localhost:11434") -> list[float]:
    """
    Embed text via Ollama. Supports both API shapes:
      - >=0.2.0: POST /api/embed        {"model", "input"}  → {"embeddings": [[...]]}
      - <0.2.0:  POST /api/embeddings   {"model", "prompt"} → {"embedding": [...]}
    Tries the new endpoint first, falls back to legacy on 404/400.
    """
    try:
        resp = httpx.post(
            f"{base_url}/api/embed",
            json={"model": model, "input": text},
            timeout=60,
        )
        if resp.status_code in (400, 404):
            # Fall back to legacy endpoint
            resp = httpx.post(
                f"{base_url}/api/embeddings",
                json={"model": model, "prompt": text},
                timeout=60,
            )
        resp.raise_for_status()
        data = resp.json()
        if "embeddings" in data:
            return data["embeddings"][0]
        return data["embedding"]
    except httpx.ConnectError:
        raise RuntimeError(
            f"Cannot connect to Ollama at {base_url}.\n"
            "Is Ollama running? Start it with: ollama serve\n"
            f"Is the model pulled? Run: ollama pull {model}"
        )


# ─── LanceDB storage ──────────────────────────────────────────────────────── #

def _open_table(lancedb_path: Path, dim: int):
    import lancedb
    import pyarrow as pa

    lancedb_path.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(lancedb_path))

    if "chunks" in db.table_names():
        return db.open_table("chunks")

    schema = pa.schema([
        pa.field("feat_id", pa.string()),
        pa.field("source_name", pa.string()),
        pa.field("chunk_idx", pa.int32()),
        pa.field("text", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), dim)),
    ])
    return db.create_table("chunks", schema=schema)


def upsert_chunks(
    lancedb_path: Path,
    feat_id: str,
    source_name: str,
    chunks: list[str],
    vectors: list[list[float]],
) -> None:
    if not chunks:
        return
    table = _open_table(lancedb_path, len(vectors[0]))
    # Remove stale entries for this source before re-adding
    try:
        table.delete(f"feat_id = '{feat_id}' AND source_name = '{source_name}'")
    except Exception:
        pass
    rows = [
        {
            "feat_id": feat_id,
            "source_name": source_name,
            "chunk_idx": i,
            "text": chunk,
            "vector": [float(v) for v in vec],
        }
        for i, (chunk, vec) in enumerate(zip(chunks, vectors))
    ]
    table.add(rows)


def search_similar(
    lancedb_path: Path,
    query_vector: list[float],
    limit: int = 10,
    feat_id_filter: str | None = None,
) -> list[dict]:
    """ANN search, optionally filtered to a single feature."""
    import lancedb

    if not lancedb_path.exists():
        return []
    db = lancedb.connect(str(lancedb_path))
    if "chunks" not in db.table_names():
        return []
    table = db.open_table("chunks")
    q = table.search(query_vector).limit(limit)
    if feat_id_filter:
        q = q.where(f"feat_id = '{feat_id_filter.upper()}'")
    return q.to_list()


# ─── File management ──────────────────────────────────────────────────────── #

def _source_filename(source: str) -> str:
    if _is_url(source):
        p = urlparse(source)
        slug = (p.netloc + p.path).replace("/", "_").replace(".", "_").strip("_")
        return slug[:60] + ".txt"
    return Path(source).expanduser().name


def save_source(feat_dir: Path, source: str, text: str) -> str:
    """Copy/save the source into feat_dir/sources/. Returns the filename stored."""
    sources_dir = feat_dir / "sources"
    sources_dir.mkdir(exist_ok=True)

    if _is_url(source):
        filename = _source_filename(source)
        (sources_dir / filename).write_text(text)
        return filename

    src = Path(source).expanduser()
    dest = sources_dir / src.name
    if src != dest:
        shutil.copy2(src, dest)
    # Always save extracted plain-text alongside non-txt files
    if src.suffix.lower() != ".txt":
        (sources_dir / (src.stem + ".txt")).write_text(text)
    return src.name


# ─── Main pipeline ────────────────────────────────────────────────────────── #

def enrich_feature(cfg: MeridianConfig, feat_id: str, source: str) -> dict:
    feat_id_norm = feat_id.upper()
    candidates = list(cfg.specs_path.glob(f"{feat_id_norm}_*/spec.md"))
    if not candidates:
        raise FileNotFoundError(f"No spec found for {feat_id_norm}")
    spec_path = candidates[0]
    feat_dir = spec_path.parent

    # 1. Extract
    text = extract_text(source)

    # 2. Save source file
    filename = save_source(feat_dir, source, text)

    # 3. Chunk
    chunks = chunk_text(text)

    # 4. Embed each chunk
    vectors = [embed(c, model=cfg.ollama_model) for c in chunks]

    # 5. Store in LanceDB
    upsert_chunks(cfg.lancedb_path, feat_id_norm, filename, chunks, vectors)

    # 6. Update spec frontmatter sources list
    from meridian.specs import load_spec, save_spec
    data = load_spec(spec_path)
    sources_list = list(data.get("sources") or [])
    ref = f"sources/{filename}"
    if ref not in sources_list:
        sources_list.append(ref)
        data["sources"] = sources_list
        save_spec(spec_path, data)

    return {
        "feat_id": feat_id_norm,
        "source": filename,
        "chunks": len(chunks),
    }


def reindex_all(cfg: MeridianConfig) -> dict:
    """Drop and rebuild the entire LanceDB index from all sources."""
    import lancedb

    if cfg.lancedb_path.exists():
        db = lancedb.connect(str(cfg.lancedb_path))
        if "chunks" in db.table_names():
            db.drop_table("chunks")

    total_chunks = 0
    total_sources = 0
    for sources_dir in sorted(cfg.specs_path.glob("FEAT-*/sources")):
        feat_id = sources_dir.parent.name.split("_")[0]
        for txt_file in sorted(sources_dir.glob("*.txt")):
            text = txt_file.read_text(errors="replace")
            chunks = chunk_text(text)
            vectors = [embed(c, model=cfg.ollama_model) for c in chunks]
            upsert_chunks(cfg.lancedb_path, feat_id, txt_file.name, chunks, vectors)
            total_chunks += len(chunks)
            total_sources += 1

    return {"sources": total_sources, "chunks": total_chunks}
