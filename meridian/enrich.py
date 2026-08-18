"""
Research ingestion pipeline: source → extract → chunk → embed → LanceDB.
"""
import base64
import datetime
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

from meridian.config import MeridianConfig


def _require_lancedb_compat(version_info: tuple[int, ...] | None = None) -> None:
    """Fail loudly on Python versions where LanceDB's native extension segfaults.

    lancedb 0.19.0's compiled extension hard-crashes (SIGSEGV, no traceback) on
    Python 3.14. Raise a clear RuntimeError *before* any native call instead —
    the CLI catches it and the rest of Meridian keeps working. Lift the ceiling
    (here and the requires-python cap in pyproject.toml) once lancedb ships a
    3.14-compatible wheel.

    ``version_info`` is injectable for testing; it defaults to the running
    interpreter's ``sys.version_info``.
    """
    vi = version_info if version_info is not None else sys.version_info
    if vi[:2] >= (3, 14):
        raise RuntimeError(
            f"The vector index (LanceDB) does not support Python "
            f"{vi[0]}.{vi[1]} — its native extension segfaults. Reinstall "
            f"Meridian on Python 3.13, e.g. "
            f"`uv tool install meridian --python 3.13 --force`."
        )

# ─── Text extraction ──────────────────────────────────────────────────────── #

def _is_url(s: str) -> bool:
    return s.startswith(("http://", "https://"))


# FEAT-006: screenshots are ingested as image + notes sidecar, never as text.
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})


def is_image_source(source: str) -> bool:
    """True when ``source`` is a local image file path.

    URLs are excluded on purpose — remote ingest stays text-only (a page that
    happens to end in ``.png`` is still fetched through the HTML extractor).
    """
    if _is_url(source):
        return False
    return Path(source).expanduser().suffix.lower() in IMAGE_SUFFIXES


def slug_image_name(name: str) -> str:
    """Normalise an image filename into a stable, path-safe slug.

    macOS screenshots arrive as ``Screenshot 2026-08-18 at 15.40.59.png``;
    clipboard captures arrive with no useful name at all. The slug becomes the
    LanceDB ``source_name``, so it must be *deterministic*: the same input always
    yields the same slug, which is what lets ``upsert_chunks`` replace a
    re-ingested screenshot's chunks instead of duplicating them.

        Screenshot 2026-08-18 at 15.40.59.png → screenshot-2026-08-18-154059.png
    """
    path = Path(name)
    suffix = path.suffix.lower()
    stem = path.stem.lower()
    # Drop the filler word macOS puts between date and time.
    words = [w for w in re.split(r"[^a-z0-9]+", stem) if w and w != "at"]
    slug = "-".join(words).strip("-")
    return f"{slug or 'image'}{suffix}"


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
    if suffix in IMAGE_SUFFIXES:
        # FEAT-006: without this guard the fallback below read image bytes as
        # text and embedded the garbage. Screenshots go through
        # ingest_screenshot(), which needs prose to embed.
        raise RuntimeError(
            f"{path.name} is an image — it needs notes to be searchable.\n"
            "Ingest it with:  meridian enrich <feat-id> "
            f"{path.name} --note \"what is wrong\"\n"
            "Or point --note-file at a sidecar file holding the notes."
        )
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

def _sanitize_for_embed(text: str) -> str:
    """Sanitize text for Ollama embedding.

    Ollama returns 400/500 for chunks containing certain unicode characters
    (e.g. math symbols extracted from PDFs). Strip non-ASCII as a safe fallback
    — semantic meaning is preserved well enough for vector similarity.
    """
    return text.encode("ascii", errors="ignore").decode("ascii").strip()


def embed(text: str, model: str, base_url: str = "http://localhost:11434") -> list[float]:
    """
    Embed text via Ollama. Supports both API shapes:
      - >=0.2.0: POST /api/embed        {"model", "input"}  → {"embeddings": [[...]]}
      - <0.2.0:  POST /api/embeddings   {"model", "prompt"} → {"embedding": [...]}
    Tries the new endpoint first, falls back to legacy on 404/400.
    If the chunk contains unicode that Ollama can't handle, retries with
    ASCII-sanitized text.
    """
    try:
        resp = httpx.post(
            f"{base_url}/api/embed",
            json={"model": model, "input": text},
            timeout=60,
        )
        if resp.status_code in (400, 404, 500):
            # Retry with sanitized text before falling back to legacy endpoint.
            # Certain unicode characters (e.g. math symbols from PDFs) cause 400/500.
            sanitized = _sanitize_for_embed(text)
            resp = httpx.post(
                f"{base_url}/api/embed",
                json={"model": model, "input": sanitized},
                timeout=60,
            )
        if resp.status_code in (400, 404):
            # Fall back to legacy endpoint (<0.2.0)
            resp = httpx.post(
                f"{base_url}/api/embeddings",
                json={"model": model, "prompt": _sanitize_for_embed(text)},
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
    except httpx.TimeoutException:
        # B2: surface timeout as a friendly message rather than a raw exception
        raise RuntimeError(
            f"Ollama timed out while embedding (model: {model}).\n"
            "The model may still be loading — wait a moment and retry.\n"
            f"To check: ollama run {model} \"hello\""
        )


# ─── LanceDB storage ──────────────────────────────────────────────────────── #

MIGRATION_HINT = (
    "The vector index predates per-project scoping and must be rebuilt. "
    "Run `meridian index` here, and once in every other Meridian project — "
    "chunks are derived from each feature's sources/, so nothing is lost."
)


class LegacyIndexError(RuntimeError):
    """Raised when the `chunks` table predates the FEAT-007 `project` column.

    Subclasses RuntimeError so existing CLI handlers degrade gracefully rather
    than traceback, while callers that care can catch this specifically and
    print the migration hint.
    """

    def __init__(self, message: str = MIGRATION_HINT):
        super().__init__(message)


def _sql_quote(value: str) -> str:
    """Escape a value for embedding in a LanceDB predicate.

    B1: user-supplied names reach these predicates — "O'Reilly_report.pdf", a
    URL with an apostrophe, or a project slug taken from a directory name.
    """
    return value.replace("'", "''")


def _is_legacy_schema(table) -> bool:
    """True when the table predates the `project` column.

    Detected by inspecting schema field names rather than by catching a write
    failure: LanceDB's schema-evolution APIs drift across minor versions, but
    `table.schema` is stable across the range pinned by the FEAT-005
    dependency-bounds test.
    """
    return "project" not in set(table.schema.names)


def _open_table(lancedb_path: Path, dim: int):
    _require_lancedb_compat()
    import lancedb
    import pyarrow as pa

    lancedb_path.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(lancedb_path))

    if "chunks" in db.table_names():
        table = db.open_table("chunks")
        if _is_legacy_schema(table):
            raise LegacyIndexError()
        return table

    schema = pa.schema([
        # FEAT-007: `project` scopes every row to the repo that wrote it. The
        # index is shared across all installs, so without this a rebuild in one
        # repo silently destroys another's research.
        pa.field("project", pa.string()),
        pa.field("feat_id", pa.string()),
        pa.field("source_name", pa.string()),
        pa.field("chunk_idx", pa.int32()),
        pa.field("text", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), dim)),
    ])
    return db.create_table("chunks", schema=schema)


def upsert_chunks(
    lancedb_path: Path,
    project: str,
    feat_id: str,
    source_name: str,
    chunks: list[str],
    vectors: list[list[float]],
) -> None:
    if not chunks:
        return
    table = _open_table(lancedb_path, len(vectors[0]))
    # Remove stale entries for this source before re-adding. Scoped to the
    # project: without it, the same FEAT id plus the same filename in another
    # repo — FEAT-001 + notes.md is entirely likely — deletes that repo's rows.
    predicate = (
        f"project = '{_sql_quote(project)}' "
        f"AND feat_id = '{_sql_quote(feat_id)}' "
        f"AND source_name = '{_sql_quote(source_name)}'"
    )
    try:
        table.delete(predicate)
    except Exception:
        pass
    rows = [
        {
            "project": project,
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
    project: str | None = None,
) -> list[dict]:
    """ANN search, optionally filtered to a single feature and/or project.

    ``project=None`` searches every project in the shared index. Callers that
    answer questions about *this* repo must pass a project — see
    ``search.semantic_search``, which scopes by default.
    """
    _require_lancedb_compat()
    import lancedb

    if not lancedb_path.exists():
        return []
    db = lancedb.connect(str(lancedb_path))
    if "chunks" not in db.table_names():
        return []
    table = db.open_table("chunks")
    if _is_legacy_schema(table):
        raise LegacyIndexError()

    clauses = []
    if feat_id_filter:
        clauses.append(f"feat_id = '{_sql_quote(feat_id_filter.upper())}'")
    if project:
        clauses.append(f"project = '{_sql_quote(project)}'")

    q = table.search(query_vector).limit(limit)
    if clauses:
        q = q.where(" AND ".join(clauses))
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


# ─── Screenshots: sidecar notes (FEAT-006) ────────────────────────────────── #

_NOTES_HEADING = "## Notes"
_READING_HEADING = "## Visual reading"


def render_sidecar(
    image_name: str,
    feat_id: str,
    notes: str,
    reading: str | None = None,
    described_by: str | None = None,
) -> str:
    """Render the ``<slug>.notes.md`` sidecar for a screenshot.

    Deliberately author-agnostic: the ``## Visual reading`` section reads the
    same whether an agent that saw the image wrote it or a local Ollama model
    did. ``described_by`` records which ("claude-opus-5 (agent)",
    "ollama:qwen2.5vl:7b"), so a reader can weigh it.

    The header lines are part of the embedded text, which is how a chunk
    retrieved by /ask carries the path back to the actual image.
    """
    today = datetime.date.today().isoformat()
    lines = [
        f"# Screenshot notes — {image_name}",
        "",
        f"- Image: sources/{image_name}",
        f"- Feature: {feat_id.upper()}",
        f"- Captured: {today}",
    ]
    if described_by:
        lines.append(f"- Described by: {described_by}")
    lines += ["", _NOTES_HEADING, "", notes.strip()]
    if reading:
        lines += ["", _READING_HEADING, "", reading.strip()]
    return "\n".join(lines) + "\n"


def parse_sidecar(text: str) -> tuple[str, str | None, str | None]:
    """Inverse of :func:`render_sidecar` → ``(notes, reading, described_by)``.

    A plain note file with no ``## Notes`` heading is returned whole as the
    notes, so ``--note-file some-scratch.txt`` works as well as a full sidecar.

    ``reading is not None`` is the signal that suppresses the Ollama fallback:
    a reading written by an agent is never overwritten by the local model.
    """
    described_by = None
    match = re.search(r"^- Described by:\s*(.+)$", text, re.MULTILINE)
    if match:
        described_by = match.group(1).strip()

    if _NOTES_HEADING not in text:
        return text.strip(), None, described_by

    after_notes = text.split(_NOTES_HEADING, 1)[1]
    if _READING_HEADING in after_notes:
        notes_part, reading_part = after_notes.split(_READING_HEADING, 1)
        reading: str | None = reading_part.strip() or None
    else:
        notes_part, reading = after_notes, None
    return notes_part.strip(), reading, described_by


def notes_chunks(sidecar_text: str, image_ref: str, feat_id: str) -> list[str]:
    """Chunk a sidecar for embedding, tagging every chunk with the image path.

    The single chunking path for screenshots — used by both ingest and
    ``reindex_all``, so a rebuild reproduces exactly the same chunks.

    Two deviations from plain :func:`chunk_text`:
      * a short note (below chunk_text's 80-character floor) still yields one
        chunk rather than vanishing;
      * every chunk is prefixed with the image reference, so a hit retrieved in
        isolation still tells the reader which screenshot it describes.
    """
    stripped = sidecar_text.strip()
    if not stripped:
        return []
    chunks = chunk_text(stripped) or [stripped]
    prefix = f"[Screenshot {image_ref} · {feat_id.upper()}]\n"
    return [prefix + c for c in chunks]


def caption_image(
    path: Path,
    model: str,
    base_url: str = "http://localhost:11434",
) -> str:
    """Describe an image with a local Ollama vision model.

    The *fallback* describer, for headless runs with no agent in the loop. An
    agent that can see the screenshot reads labels and values far more reliably,
    so this is opt-in via `--vision` and never overwrites an existing reading.
    """
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    prompt = (
        "Describe this screenshot of a data application in 2-4 sentences. "
        "State visible labels, numbers, and anything that looks broken or empty. "
        "Do not speculate about causes."
    )
    try:
        resp = httpx.post(
            f"{base_url}/api/generate",
            json={"model": model, "prompt": prompt, "images": [encoded], "stream": False},
            timeout=180,
        )
    except httpx.ConnectError:
        raise RuntimeError(
            f"Cannot connect to Ollama at {base_url} for the vision caption.\n"
            "Is Ollama running? Start it with: ollama serve"
        )
    except httpx.TimeoutException:
        raise RuntimeError(
            f"Vision model {model} timed out while describing {path.name}.\n"
            "The model may still be loading — wait a moment and retry."
        )

    if resp.status_code == 404 or "not found" in resp.text.lower():
        raise RuntimeError(
            f"Vision model '{model}' is not available in Ollama.\n"
            f"Pull it with: ollama pull {model}"
        )
    resp.raise_for_status()
    return str(resp.json().get("response", "")).strip()


def save_screenshot(
    feat_dir: Path,
    image: Path,
    sidecar_text: str,
    slug: str,
) -> tuple[str, str]:
    """Copy the image into sources/ under ``slug`` and write its notes sidecar.

    Does *not* reuse :func:`save_source`: that writes a ``<stem>.txt`` companion
    for every non-.txt source, which for an image is exactly the binary-as-text
    corruption this feature removes.
    """
    sources_dir = feat_dir / "sources"
    sources_dir.mkdir(exist_ok=True)

    dest = sources_dir / slug
    src = image.expanduser()
    # Re-ingesting a file already sitting in sources/ must not copy onto itself.
    if not (dest.exists() and src.resolve() == dest.resolve()):
        shutil.copy2(src, dest)

    sidecar_name = f"{Path(slug).stem}.notes.md"
    (sources_dir / sidecar_name).write_text(sidecar_text)
    return slug, sidecar_name


# ─── Main pipeline ────────────────────────────────────────────────────────── #

def _find_spec_path(cfg: MeridianConfig, feat_id_norm: str) -> Path:
    candidates = list(cfg.specs_path.glob(f"{feat_id_norm}_*/spec.md"))
    if not candidates:
        raise FileNotFoundError(f"No spec found for {feat_id_norm}")
    return candidates[0]


def _append_sources(spec_path: Path, refs: list[str]) -> None:
    """Add ``sources/...`` refs to spec frontmatter, skipping ones already there."""
    from meridian.specs import load_spec, save_spec
    data = load_spec(spec_path)
    sources_list = list(data.get("sources") or [])
    added = [r for r in refs if r not in sources_list]
    if not added:
        return
    data["sources"] = sources_list + added
    save_spec(spec_path, data)


def enrich_feature(cfg: MeridianConfig, feat_id: str, source: str) -> dict:
    feat_id_norm = feat_id.upper()
    spec_path = _find_spec_path(cfg, feat_id_norm)
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
    upsert_chunks(cfg.lancedb_path, cfg.project, feat_id_norm, filename, chunks, vectors)

    # 6. Update spec frontmatter sources list
    _append_sources(spec_path, [f"sources/{filename}"])

    return {
        "feat_id": feat_id_norm,
        "source": filename,
        "chunks": len(chunks),
    }


def ingest_screenshot(
    cfg: MeridianConfig,
    feat_id: str,
    image: str | Path,
    note: str | None = None,
    note_file: str | Path | None = None,
    vision: bool = False,
) -> dict:
    """Ingest a screenshot as image + searchable notes sidecar.

    The image is copied byte-identical into ``sources/``; the prose about it is
    what gets chunked and embedded. Every chunk carries the image path so a
    retrieving agent can open the screenshot the notes describe.

    Describer precedence — an existing reading always wins:

    ==========================  =========  ================================
    sidecar has visual reading?  --vision?  result
    ==========================  =========  ================================
    yes                          either    kept verbatim, no Ollama call
    no                           yes       Ollama attempted, degrades to warn
    no                           no        notes only
    ==========================  =========  ================================
    """
    feat_id_norm = feat_id.upper()
    spec_path = _find_spec_path(cfg, feat_id_norm)
    feat_dir = spec_path.parent

    img_path = Path(image).expanduser()
    if not img_path.exists():
        raise FileNotFoundError(f"Source not found: {img_path}")

    warnings: list[str] = []

    # 1. Resolve notes — and any reading a caller (agent) already wrote.
    reading: str | None = None
    described_by: str | None = None
    if note_file is not None:
        note_path = Path(note_file).expanduser()
        if not note_path.exists():
            raise FileNotFoundError(f"Note file not found: {note_path}")
        notes, reading, described_by = parse_sidecar(note_path.read_text(errors="replace"))
    elif note is not None:
        notes = note
    else:
        raise RuntimeError(
            f"{img_path.name} is an image — it needs notes to be searchable.\n"
            "Pass --note \"what is wrong\" or --note-file <path>."
        )

    if not notes.strip():
        raise RuntimeError("The note is empty — nothing to embed. Nothing was written.")

    # 2. Optional Ollama fallback describer. Never overwrites an existing reading.
    if vision and reading is not None:
        warnings.append(
            "--vision skipped: the sidecar already carries a visual reading "
            f"({described_by or 'author unknown'})."
        )
    elif vision and not cfg.ollama_vision_model:
        warnings.append(
            "--vision skipped: no vision model configured. Set "
            "ollama_vision_model in .meridian.toml (e.g. \"qwen2.5vl:7b\")."
        )
    elif vision:
        try:
            reading = caption_image(img_path, model=cfg.ollama_vision_model)
            described_by = f"ollama:{cfg.ollama_vision_model}"
        except RuntimeError as e:
            warnings.append(f"Vision caption failed, notes ingested without it — {e}")

    # 3. Write image + sidecar under a deterministic slug.
    slug = slug_image_name(img_path.name)
    sidecar_text = render_sidecar(
        image_name=slug,
        feat_id=feat_id_norm,
        notes=notes,
        reading=reading,
        described_by=described_by,
    )
    image_name, sidecar_name = save_screenshot(feat_dir, img_path, sidecar_text, slug)

    # 4. Chunk + embed the prose (the image itself is never embedded).
    chunks = notes_chunks(sidecar_text, f"sources/{image_name}", feat_id_norm)
    vectors = [embed(c, model=cfg.ollama_model) for c in chunks]

    # 5. Store, keyed on the sidecar so re-ingest replaces rather than duplicates.
    upsert_chunks(cfg.lancedb_path, cfg.project, feat_id_norm, sidecar_name, chunks, vectors)

    # 6. Both the image and its notes are sources of record.
    _append_sources(spec_path, [f"sources/{image_name}", f"sources/{sidecar_name}"])

    return {
        "feat_id": feat_id_norm,
        "source": image_name,
        "sidecar": sidecar_name,
        "chunks": len(chunks),
        "described_by": described_by,
        "warnings": warnings,
    }


def _sidecar_image_ref(sidecar_path: Path) -> str:
    """Recover the ``sources/<image>`` reference a sidecar describes.

    Prefers the header line written by :func:`render_sidecar`; falls back to the
    sibling image file that shares the sidecar's stem, so a hand-written sidecar
    without a header still points somewhere real.
    """
    text = sidecar_path.read_text(errors="replace")
    match = re.search(r"^- Image:\s*(.+)$", text, re.MULTILINE)
    if match:
        return match.group(1).strip()

    stem = sidecar_path.name[: -len(".notes.md")]
    for sibling in sorted(sidecar_path.parent.iterdir()):
        if sibling.stem == stem and sibling.suffix.lower() in IMAGE_SUFFIXES:
            return f"sources/{sibling.name}"
    return f"sources/{stem}"


def reindex_all(cfg: MeridianConfig) -> dict:
    """Rebuild *this project's* slice of the LanceDB index from its sources.

    Returns ``sources``, ``chunks``, and ``migrated`` — the last is True when a
    pre-FEAT-007 table was recreated, which wipes other projects' rows and means
    each of them must run `meridian index` once to repopulate.
    """
    _require_lancedb_compat()
    import lancedb

    migrated = False
    if cfg.lancedb_path.exists():
        db = lancedb.connect(str(cfg.lancedb_path))
        if "chunks" in db.table_names():
            table = db.open_table("chunks")
            if _is_legacy_schema(table):
                # Pre-FEAT-007 rows carry no project, so there is no way to know
                # which repo wrote them and no way to keep only ours. Recreating
                # is the documented recovery path: chunks are derived data,
                # rebuildable from each feature's sources/.
                db.drop_table("chunks")
                migrated = True
            else:
                # The whole point of FEAT-007: clear only our own rows and leave
                # every other project's research intact.
                try:
                    table.delete(f"project = '{_sql_quote(cfg.project)}'")
                except Exception:
                    pass

    total_chunks = 0
    total_sources = 0
    for sources_dir in sorted(cfg.specs_path.glob("FEAT-*/sources")):
        feat_id = sources_dir.parent.name.split("_")[0]
        # FEAT-006: *.notes.md carries screenshot prose, so it must be rebuilt
        # too — but only that pattern. A stray README.md or summaries/ file in
        # sources/ is not research and must not be indexed.
        files = sorted(sources_dir.glob("*.txt")) + sorted(sources_dir.glob("*.notes.md"))
        for src_file in files:
            text = src_file.read_text(errors="replace")
            if src_file.name.endswith(".notes.md"):
                # Re-embed the stored reading; never call a describer again, so
                # the chunk count and the sidecar bytes stay stable across rebuilds.
                chunks = notes_chunks(text, _sidecar_image_ref(src_file), feat_id)
            else:
                chunks = chunk_text(text)
            vectors = [embed(c, model=cfg.ollama_model) for c in chunks]
            upsert_chunks(cfg.lancedb_path, cfg.project, feat_id, src_file.name,
                          chunks, vectors)
            total_chunks += len(chunks)
            total_sources += 1

    return {"sources": total_sources, "chunks": total_chunks, "migrated": migrated}
