"""
Research ingestion pipeline: source → extract → chunk → embed → LanceDB.
"""
import base64
import datetime
import hashlib
import logging
import re
import shutil
import sys
from collections import defaultdict
from collections.abc import Iterator
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlparse

import httpx

from meridian.config import MeridianConfig

logger = logging.getLogger(__name__)


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


# FEAT-023: what a *directory* argument expands to. Narrow on purpose — these
# are the suffixes extract_text() handles as prose.
INGESTIBLE_SUFFIXES = frozenset({".pdf", ".txt", ".md"})


def expand_sources(sources: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
    """Expand directory arguments into the files inside them → ``(targets, failures)``.

    Each failure is ``(argument, reason)``.

    Non-recursive (AC12): recursion into a repo tree is how you accidentally
    index `node_modules`. Images are left out because an image without notes is
    not searchable — ingesting one stays a deliberate, one-at-a-time act with
    `--note`.
    """
    targets: list[str] = []
    failures: list[tuple[str, str]] = []
    for source in sources:
        path = Path(source).expanduser()
        if _is_url(source) or not path.is_dir():
            targets.append(source)
            continue
        files = sorted(
            p for p in path.iterdir()
            if p.is_file() and p.suffix.lower() in INGESTIBLE_SUFFIXES
        )
        if not files:
            failures.append((source, "no .pdf/.txt/.md files in this directory"))
        targets.extend(str(p) for p in files)
    return targets, failures


# ─── The summaries/ exclusion (FEAT-025) ──────────────────────────────────── #

#: Directory names holding text Meridian *wrote*, which must never be embedded.
#:
#: `summaries/` holds synthesis: research briefs and paper briefs produced by
#: reading the corpus. Indexing one closes a loop. The next `/research` would
#: retrieve the model's own prior conclusion, cite it as if it were evidence,
#: and write a more confident version of it; the round after that would cite
#: *that*. Confidence compounds while the underlying evidence never changes.
#:
#: The failure is silent and looks like progress — each round reads better than
#: the last, because agreement with itself is the one thing a corpus of its own
#: output guarantees. Nothing in the output says "this came from me".
#:
#: So there is no flag to index `summaries/`, and there must not be one: a flag
#: gets used on the day someone wants a brief to be searchable. A document that
#: genuinely belongs in the corpus is a *source* and goes in `sources/`.
SYNTHESIS_DIRS = frozenset({"summaries"})


def is_synthesis_path(path: str | Path) -> bool:
    """True when *path* lies inside a directory Meridian writes synthesis into.

    Checks the literal path *and* its resolved form, so a symlink from
    ``sources/`` into ``summaries/`` is caught too — that is the shape the loop
    would most plausibly take back in through a door nobody remembered.

    Only directory components count: a file merely *named* ``summaries`` is not
    synthesis.
    """
    p = Path(path).expanduser()
    parents = set(p.parent.parts)
    try:
        parents |= set(p.resolve().parent.parts)
    except OSError:  # pragma: no cover - unresolvable path, literal check stands
        pass
    return bool(parents & SYNTHESIS_DIRS)


def indexable_sources(sources_dir: Path) -> list[Path]:
    """Every file under *sources_dir* that belongs in the vector corpus.

    The single place that decides what gets embedded, so the exclusion above is
    enforced by code rather than by the shape of a glob somebody may widen
    later.

    ``*.txt`` is extracted source text; ``*.notes.md`` is screenshot prose
    (FEAT-006) and must be rebuilt too. A stray README.md — or a brief someone
    copied or symlinked in — is not research and is left out.
    """
    files = sorted(sources_dir.glob("*.txt")) + sorted(sources_dir.glob("*.notes.md"))
    return [f for f in files if not is_synthesis_path(f)]


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
    # Treat everything else as plain text — but only if it really is text.
    raw = path.read_bytes()
    if not _looks_like_text(raw):
        raise RuntimeError(
            f"{path.name} does not look like text — refusing to embed it.\n"
            "A .docx, .xlsx, archive or binary would be indexed as mojibake and "
            "then retrieved by /ask as if it were research.\n"
            "Convert it to text or PDF first."
        )
    return raw.decode("utf-8", errors="replace")


def _looks_like_text(raw: bytes, sample: int = 4096) -> bool:
    """Heuristic text sniff: no NUL bytes and mostly printable.

    FEAT-018: `enrich` accepted any file and embedded the result, so
    `head -c 2000 /dev/urandom` produced a cheerful "1 chunks embedded" and
    left retrievable garbage in the corpus.
    """
    if not raw:
        return True
    head = raw[:sample]
    if b"\x00" in head:
        return False
    printable = sum(
        1 for b in head if 32 <= b < 127 or b in (9, 10, 13) or b >= 128
    )
    return printable / len(head) > 0.85


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


# ─── Content addressing (FEAT-023) ────────────────────────────────────────── #

def hash_chunk(text: str) -> str:
    """SHA-256 of a chunk's text — the identity used for skipping and dedup.

    Hash, never mtime (AC3). A file touched but not edited hashes the same and
    must not be re-embedded; a file edited in place with a preserved mtime
    hashes differently and must be. The hash is also what makes the same text
    embedded in two features cost one Ollama call instead of two.

    The hash covers the *chunk*, not the file, because the chunk is what is
    embedded — so a one-paragraph edit re-embeds the chunks that changed and
    reuses the rest.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
    except httpx.HTTPStatusError as e:
        # FEAT-013: `raise_for_status()` sits inside this try, but only
        # ConnectError and TimeoutException were caught — so the most common
        # misconfiguration of all, a model that was never pulled, escaped as a
        # raw traceback. Observed live: `meridian index` with an unknown model
        # produced a 404 traceback instead of an actionable message.
        raise RuntimeError(
            f"Ollama rejected the embedding request for model '{model}' "
            f"(HTTP {e.response.status_code}).\n"
            f"Is the model pulled? Run: ollama pull {model}\n"
            f"To list what is available: ollama list"
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


CONTENT_HASH = "content_hash"
EMBEDDING_MODEL = "embedding_model"


class SchemaGeneration(StrEnum):
    """Which generation of the `chunks` schema wrote a table.

    There are three now, so a boolean cannot say what was found — and the
    answer decides between "raise", "migrate in place" and "use as is":

    ===============  ==============================  ==========================
    generation       columns                          handling
    ===============  ==============================  ==========================
    PRE_PROJECT      no `project`                     LegacyIndexError; only
                                                      `reindex_all` recreates
    PRE_HASH         `project`, no `content_hash`     migrated in place, rows
                                                      kept (FEAT-023 AC9)
    CURRENT          both, plus `embedding_model`     nothing to do
    ===============  ==============================  ==========================

    Detected by inspecting schema field names rather than by catching a write
    failure: LanceDB's schema-evolution APIs drift across minor versions, but
    `table.schema` is stable across the range pinned by the FEAT-005
    dependency-bounds test.
    """

    PRE_PROJECT = "pre-project"
    PRE_HASH = "pre-hash"
    CURRENT = "current"


def schema_generation(table) -> SchemaGeneration:
    """Name the schema generation of an open `chunks` table."""
    names = set(table.schema.names)
    if "project" not in names:
        return SchemaGeneration.PRE_PROJECT
    if CONTENT_HASH not in names or EMBEDDING_MODEL not in names:
        return SchemaGeneration.PRE_HASH
    return SchemaGeneration.CURRENT


def _add_hash_columns(table) -> None:
    """Add the FEAT-023 columns to a FEAT-007-era table. Additive, never destructive.

    This is the whole migration: existing rows keep their vectors and get an
    empty hash, which reads as *unknown* (re-embed once, then backfill) rather
    than *stale* (delete). Nothing is dropped, so an index shared by five repos
    stays readable by every one of them, including the ones still running the
    old Meridian.

    The alternative — drop and rebuild — is exactly what `_is_legacy_schema`
    did for the pre-FEAT-007 schema, and on 2026-08-18 it destroyed the shared
    global store because one repo happened to run `meridian index` first. A new
    column must never reach for that hammer.
    """
    missing = {
        name: "''"
        for name in (CONTENT_HASH, EMBEDDING_MODEL)
        if name not in set(table.schema.names)
    }
    if not missing:
        return
    try:
        table.add_columns(missing)
    except Exception as e:  # pragma: no cover - lancedb API drift
        raise RuntimeError(
            f"Could not add the content-hash columns to the existing index ({e}).\n"
            "The index was left untouched — no rows were deleted, and search "
            "still works.\n"
            "Update the dependencies (`uv sync`) and run `meridian index` again."
        ) from e


def _open_table(lancedb_path: Path, dim: int):
    _require_lancedb_compat()
    import lancedb
    import pyarrow as pa

    lancedb_path.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(lancedb_path))

    if "chunks" in db.table_names():
        table = db.open_table("chunks")
        generation = schema_generation(table)
        if generation is SchemaGeneration.PRE_PROJECT:
            raise LegacyIndexError()
        if generation is SchemaGeneration.PRE_HASH:
            # Migrate on the write path too, so `meridian enrich` works on an
            # old store without waiting for a full `meridian index`.
            _add_hash_columns(table)
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
        # FEAT-023. Trailing on purpose: `_add_hash_columns` appends, so a
        # migrated table and a fresh one end up with the same field order.
        pa.field(CONTENT_HASH, pa.string()),
        pa.field(EMBEDDING_MODEL, pa.string()),
    ])
    return db.create_table("chunks", schema=schema)


def _open_existing_table(lancedb_path: Path):
    """Open the `chunks` table for reading → ``(table | None, generation | None)``.

    Never creates and never migrates: `reindex_all` has to inspect the store
    *before* it embeds anything, and a read must not be the thing that changes
    the schema.
    """
    _require_lancedb_compat()
    import lancedb

    if not lancedb_path.exists():
        return None, None
    db = lancedb.connect(str(lancedb_path))
    if "chunks" not in db.table_names():
        return None, None
    table = db.open_table("chunks")
    return table, schema_generation(table)


def _scan(table, columns: list[str], predicate: str | None = None,
          limit: int | None = None) -> list[dict]:
    """Filtered, projected scan — with an explicit limit, always.

    LanceDB applies a default limit of **10** to any query that does not set
    one. `to_arrow()` reported 10 rows for a 178-row table while the 2026-08-18
    incident was being diagnosed, and was read as data loss. Every scan here
    passes a bound derived from `count_rows()`, and every column list omits
    `text`/`vector` unless the caller actually needs them.
    """
    bound = limit if limit is not None else max(table.count_rows(), 1)
    query = table.search()
    if predicate:
        query = query.where(predicate)
    return query.select(columns).limit(bound).to_list()


def _source_predicate(project: str, feat_id: str, source_name: str) -> str:
    return (
        f"project = '{_sql_quote(project)}' "
        f"AND feat_id = '{_sql_quote(feat_id)}' "
        f"AND source_name = '{_sql_quote(source_name)}'"
    )


def _stored_chunks(table, project: str) -> dict[tuple[str, str], list[tuple[int, str, str]]]:
    """``(feat_id, source_name) → [(chunk_idx, content_hash, embedding_model)]``.

    Reads neither text nor vectors, so the cost is independent of the embedding
    dimension — this runs before every rebuild. A PRE_HASH table has no hash
    columns to read, so every source comes back *unknown* and is re-embedded
    once, which is the migration (AC9).
    """
    names = set(table.schema.names)
    columns = ["feat_id", "source_name", "chunk_idx"]
    if CONTENT_HASH in names and EMBEDDING_MODEL in names:
        columns += [CONTENT_HASH, EMBEDDING_MODEL]
    index: dict[tuple[str, str], list[tuple[int, str, str]]] = defaultdict(list)
    for row in _scan(table, columns, f"project = '{_sql_quote(project)}'"):
        index[(row["feat_id"], row["source_name"])].append((
            int(row["chunk_idx"]),
            row.get(CONTENT_HASH) or "",
            row.get(EMBEDDING_MODEL) or "",
        ))
    for entries in index.values():
        entries.sort()
    return dict(index)


def _stored_source_chunks(
    table, project: str, feat_id: str, source_name: str
) -> list[tuple[int, str, str]] | None:
    """One source's stored ``(chunk_idx, hash, model)`` rows — None when unknown.

    The single-source counterpart of :func:`_stored_chunks`, so `enrich` scans
    one predicate instead of the project's whole slice.
    """
    if table is None or schema_generation(table) is not SchemaGeneration.CURRENT:
        return None
    rows = _scan(
        table,
        ["chunk_idx", CONTENT_HASH, EMBEDDING_MODEL],
        _source_predicate(project, feat_id, source_name),
    )
    if not rows:
        return None
    return sorted(
        (int(r["chunk_idx"]), r.get(CONTENT_HASH) or "", r.get(EMBEDDING_MODEL) or "")
        for r in rows
    )


def _source_is_unchanged(
    stored: list[tuple[int, str, str]] | None,
    hashes: list[str],
    model: str,
) -> bool:
    """True when the store already holds exactly these chunks, from this model.

    Conservative by construction: anything unrecognised — no rows, a different
    chunk count, an empty hash left by the migration, a vector from another
    embedding model (AC7) — answers False and costs one re-embed, never a wrong
    reuse.
    """
    if not hashes or not stored or len(stored) != len(hashes):
        return False
    return all(
        idx == i and stored_hash == hashes[i] and stored_model == model
        for i, (idx, stored_hash, stored_model) in enumerate(stored)
    )


class _VectorReuse:
    """A hash → vector cache for one embedding model.

    Scoped by model on purpose (AC7): vectors from two models are not
    comparable, so reusing one for the other would silently poison every later
    search with distances computed across incompatible spaces. The model name
    is stored beside the hash, so the scoping survives a restart.

    Serves both wastes the corpus was paying: the same chunk twice in one run
    (in-memory hit) and the same chunk already in the store from an earlier run
    or another feature (primed hit).
    """

    # Keep the generated `IN (...)` predicate a sane length.
    _BATCH = 100

    def __init__(self, model: str) -> None:
        self.model = model
        self.embedded = 0
        self.reused = 0
        self._by_hash: dict[str, list[float]] = {}

    def prime(self, table, hashes: list[str]) -> None:
        """Load any vector the store already holds for these hashes."""
        if table is None or not hashes:
            return
        names = set(table.schema.names)
        if CONTENT_HASH not in names or EMBEDDING_MODEL not in names:
            return  # PRE_HASH store: nothing is addressable yet
        wanted = [h for h in dict.fromkeys(hashes) if h not in self._by_hash]
        bound = max(table.count_rows(), 1)
        for start in range(0, len(wanted), self._BATCH):
            batch = wanted[start:start + self._BATCH]
            quoted = ", ".join(f"'{_sql_quote(h)}'" for h in batch)
            predicate = (
                f"{EMBEDDING_MODEL} = '{_sql_quote(self.model)}' "
                f"AND {CONTENT_HASH} IN ({quoted})"
            )
            for row in _scan(table, [CONTENT_HASH, "vector"], predicate, limit=bound):
                digest = row.get(CONTENT_HASH)
                if digest and digest not in self._by_hash:
                    self._by_hash[digest] = [float(v) for v in row["vector"]]

    def vectors_for(self, chunks: list[str], hashes: list[str]) -> list[list[float]]:
        """Vectors for these chunks, calling Ollama only for the ones not seen."""
        vectors: list[list[float]] = []
        for chunk, digest in zip(chunks, hashes):
            vector = self._by_hash.get(digest)
            if vector is None:
                vector = [float(v) for v in embed(chunk, model=self.model)]
                self._by_hash[digest] = vector
                self.embedded += 1
            else:
                self.reused += 1
            vectors.append(vector)
        return vectors


def upsert_chunks(
    lancedb_path: Path,
    project: str,
    feat_id: str,
    source_name: str,
    chunks: list[str],
    vectors: list[list[float]],
    embedding_model: str = "",
    hashes: list[str] | None = None,
) -> None:
    """Replace this source's rows with the given chunks.

    ``embedding_model`` and ``hashes`` are what make the next rebuild
    incremental. A row written without them is not wrong, only unrecognisable:
    it will be re-embedded once, exactly like a migrated row.
    """
    if not chunks:
        return
    digests = hashes if hashes is not None else [hash_chunk(c) for c in chunks]
    table = _open_table(lancedb_path, len(vectors[0]))
    # Remove stale entries for this source before re-adding. Scoped to the
    # project: without it, the same FEAT id plus the same filename in another
    # repo — FEAT-001 + notes.md is entirely likely — deletes that repo's rows.
    try:
        table.delete(_source_predicate(project, feat_id, source_name))
    except Exception as e:
        # FEAT-018: not silent. A failed delete leaves duplicate rows, which
        # quietly degrades every later search — the exact thing the corpus exists
        # to get right.
        logger.warning("Could not clear existing rows for %s (%s)", source_name, e)
    rows = [
        {
            "project": project,
            "feat_id": feat_id,
            "source_name": source_name,
            "chunk_idx": i,
            "text": chunk,
            "vector": [float(v) for v in vec],
            # FEAT-023: provenance stays one row per (project, feat, source,
            # chunk) — the hash removes the *embedding* cost of duplication,
            # never the record of where the text came from (AC8).
            CONTENT_HASH: digest,
            EMBEDDING_MODEL: embedding_model,
        }
        for i, (chunk, vec, digest) in enumerate(zip(chunks, vectors, digests))
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
    if schema_generation(table) is SchemaGeneration.PRE_PROJECT:
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
    """FEAT-018: one validated resolver, shared with the CLI."""
    from meridian.specs import find_spec

    found = find_spec(cfg.specs_path, feat_id_norm)
    if found is None:
        raise FileNotFoundError(f"No spec found for {feat_id_norm}")
    return found


def _append_sources(spec_path: Path, refs: list[str]) -> None:
    """Add ``sources/...`` refs to spec frontmatter, skipping ones already there."""
    # FEAT-013: locked read-modify-write. Appending is especially race-prone —
    # two concurrent enrichments each read the old list and one loses its entry.
    from meridian.specs import edit_spec

    with edit_spec(spec_path) as data:
        sources_list = list(data.get("sources") or [])
        added = [r for r in refs if r not in sources_list]
        if added:
            data["sources"] = sources_list + added


def _refuse_synthesis(source: str) -> None:
    """Stop an ingest that would feed Meridian's own writing back into the corpus.

    ``reindex_all`` cannot reach ``summaries/``, but ``enrich`` can be pointed
    anywhere — and pointing it at a research brief is the one realistic way the
    loop described on :data:`SYNTHESIS_DIRS` gets built. It is refused here
    rather than warned about, because a warning is read once and the chunks
    stay forever.
    """
    if _is_url(source):
        return
    if is_synthesis_path(source):
        raise RuntimeError(
            f"{Path(source).name} lives in summaries/, which holds Meridian's "
            "own synthesis — refusing to index it.\n"
            "An indexed brief becomes evidence for the next brief, and the "
            "result reads better every round while resting on nothing new.\n"
            "If this document really is a source, move it into sources/ first."
        )


def enrich_feature(
    cfg: MeridianConfig, feat_id: str, source: str, refresh: bool = False
) -> dict:
    """Ingest one source into a feature's corpus.

    Returns ``feat_id``, ``source``, ``chunks`` (the source's chunk count),
    ``embedded`` and ``reused`` (how those chunks were paid for), plus
    ``skipped``/``reason`` when nothing had to be embedded.

    ``refresh`` applies to URL sources only: a URL already fetched into
    ``sources/`` is *not* re-fetched without it. The fetch is the one part of
    ingestion that leaves the machine, and re-running a batch to pick up one new
    paper should not re-crawl twenty sites (AC15).
    """
    feat_id_norm = feat_id.upper()
    _refuse_synthesis(source)
    spec_path = _find_spec_path(cfg, feat_id_norm)
    feat_dir = spec_path.parent

    # 1. Extract — unless this URL is already on disk and no refresh was asked for.
    if _is_url(source):
        cached = feat_dir / "sources" / _source_filename(source)
        if cached.exists() and not refresh:
            _append_sources(spec_path, [f"sources/{cached.name}"])
            return {
                "feat_id": feat_id_norm,
                "source": cached.name,
                "chunks": len(chunk_text(cached.read_text(errors="replace"))),
                "embedded": 0,
                "reused": 0,
                "skipped": True,
                "reason": "already fetched — pass --refresh to re-fetch",
            }
    text = extract_text(source)

    # 2. Save source file
    filename = save_source(feat_dir, source, text)

    # 3. Chunk + hash
    chunks = chunk_text(text)
    hashes = [hash_chunk(c) for c in chunks]

    # 4. Nothing to do when the store already holds exactly these chunks.
    table, generation = _open_existing_table(cfg.lancedb_path)
    stored = _stored_source_chunks(table, cfg.project, feat_id_norm, filename)
    if _source_is_unchanged(stored, hashes, cfg.ollama_model):
        _append_sources(spec_path, [f"sources/{filename}"])
        return {
            "feat_id": feat_id_norm,
            "source": filename,
            "chunks": len(chunks),
            "embedded": 0,
            "reused": len(chunks),
            "skipped": True,
            "reason": "unchanged since the last ingest",
        }

    # 5. Embed what is not already embedded — the same paper in a second
    #    feature reuses the stored vectors and still gets its own rows (AC6/AC8).
    reuse = _VectorReuse(cfg.ollama_model)
    if generation is SchemaGeneration.CURRENT:
        reuse.prime(table, hashes)
    vectors = reuse.vectors_for(chunks, hashes)

    # 6. Store in LanceDB
    upsert_chunks(
        cfg.lancedb_path, cfg.project, feat_id_norm, filename, chunks, vectors,
        embedding_model=cfg.ollama_model, hashes=hashes,
    )

    # 7. Update spec frontmatter sources list
    _append_sources(spec_path, [f"sources/{filename}"])

    return {
        "feat_id": feat_id_norm,
        "source": filename,
        "chunks": len(chunks),
        "embedded": reuse.embedded,
        "reused": reuse.reused,
        "skipped": False,
        "reason": None,
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
        # The sidecar is the prose that actually gets embedded, so a brief
        # passed as --note-file is the same loop by another route.
        _refuse_synthesis(str(note_path))
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
    hashes = [hash_chunk(c) for c in chunks]
    reuse = _VectorReuse(cfg.ollama_model)
    table, generation = _open_existing_table(cfg.lancedb_path)
    if generation is SchemaGeneration.CURRENT:
        # Re-ingesting the same screenshot with an unchanged note is the common
        # case here — the notes rarely move, only the surrounding spec does.
        reuse.prime(table, hashes)
    vectors = reuse.vectors_for(chunks, hashes)

    # 5. Store, keyed on the sidecar so re-ingest replaces rather than duplicates.
    upsert_chunks(
        cfg.lancedb_path, cfg.project, feat_id_norm, sidecar_name, chunks, vectors,
        embedding_model=cfg.ollama_model, hashes=hashes,
    )

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


def _iter_source_files(specs_path: Path) -> Iterator[tuple[str, Path]]:
    """Yield ``(feat_id, path)`` for every indexable source file under specs/.

    Delegates to :func:`indexable_sources` rather than repeating its glob.
    FEAT-023 and FEAT-025 were built in parallel and each grew its own copy of
    "which files are corpus"; two copies is how the symlink case (a brief linked
    into ``sources/``) gets caught by one and missed by the other. There is one
    decider — see :data:`SYNTHESIS_DIRS` for why that matters.
    """
    for sources_dir in sorted(specs_path.glob("FEAT-*/sources")):
        feat_id = sources_dir.parent.name.split("_")[0]
        for src_file in indexable_sources(sources_dir):
            yield feat_id, src_file


def _chunks_for_source(feat_id: str, src_file: Path) -> list[str]:
    text = src_file.read_text(errors="replace")
    if src_file.name.endswith(".notes.md"):
        # Re-embed the stored reading; never call a describer again, so the
        # chunk count and the sidecar bytes stay stable across rebuilds.
        return notes_chunks(text, _sidecar_image_ref(src_file), feat_id)
    return chunk_text(text)


def reindex_all(cfg: MeridianConfig) -> dict:
    """Rebuild *this project's* slice of the LanceDB index from its sources.

    **Incremental** (FEAT-023): a source whose every chunk hash is already in
    the store, from the same embedding model, is left exactly where it is — not
    re-embedded, not even rewritten. A no-op rebuild makes zero Ollama calls,
    which is what lets the corpus grow: before this, maintaining 178 chunks cost
    178 round-trips *per rebuild*, so the hundredth document was paid for again
    every time.

    Embeds everything **before** deleting anything. FEAT-013: the delete used to
    come first, so a rebuild with Ollama unreachable destroyed the project's
    whole corpus and then reported that it had not rebuilt the index — verified
    as 4 chunks in, an error message, exit 0, 0 chunks out. That ordering still
    holds, and now covers the migration too (AC10).

    Returns:
      ``sources``/``chunks``  — the corpus this project now has indexed
      ``skipped``             — sources left untouched (unchanged)
      ``skipped_chunks``      — their chunk count
      ``embedded``            — chunks actually sent to Ollama
      ``reused``              — chunks whose vector came from the cache or store
      ``changed``             — sources re-embedded because their hashes moved
      ``migration``           — None | "backfilled" | "recreated"
      ``migrated``            — True only for "recreated", which wipes other
                                projects' rows and means each of them must run
                                `meridian index --vectors-only` once to repopulate
    """
    _require_lancedb_compat()
    import lancedb

    table, generation = _open_existing_table(cfg.lancedb_path)
    # A pre-FEAT-007 table carries no project on any row, so nothing in it can
    # be attributed, reused, or selectively deleted.
    recreate = generation is SchemaGeneration.PRE_PROJECT
    stored = {} if (table is None or recreate) else _stored_chunks(table, cfg.project)

    # ── 1. chunk and hash every source; decide what actually needs embedding
    plans: list[tuple[str, str, list[str], list[str]]] = []
    present: set[tuple[str, str]] = set()
    total_sources = total_chunks = skipped_sources = skipped_chunks = 0
    changed: list[str] = []
    for feat_id, src_file in _iter_source_files(cfg.specs_path):
        chunks = _chunks_for_source(feat_id, src_file)
        hashes = [hash_chunk(c) for c in chunks]
        key = (feat_id, src_file.name)
        present.add(key)
        total_sources += 1
        total_chunks += len(chunks)
        if _source_is_unchanged(stored.get(key), hashes, cfg.ollama_model):
            skipped_sources += 1
            skipped_chunks += len(chunks)
            continue
        if key in stored:
            changed.append(f"{feat_id}/{src_file.name}")
        plans.append((feat_id, src_file.name, chunks, hashes))

    # ── 2. embed what is left; any failure raises before we touch the store
    reuse = _VectorReuse(cfg.ollama_model)
    if not recreate:
        reuse.prime(table, [h for _f, _n, _c, hs in plans for h in hs])
    pending: list[tuple[str, str, list[str], list[str], list[list[float]]]] = [
        (feat_id, name, chunks, hashes, reuse.vectors_for(chunks, hashes))
        for feat_id, name, chunks, hashes in plans
    ]

    # ── 3. only now is it safe to change the store
    migration: str | None = None
    if recreate:
        # Recreating is the documented recovery path for a pre-project table:
        # chunks are derived data, rebuildable from each feature's sources/.
        lancedb.connect(str(cfg.lancedb_path)).drop_table("chunks")
        migration = "recreated"
        table = None
    elif generation is SchemaGeneration.PRE_HASH:
        # Additive. Every row keeps its vector; the empty hash reads as
        # "unknown", which is why this rebuild re-embedded the corpus once
        # and the next one will not (AC9).
        _add_hash_columns(table)
        migration = "backfilled"

    # Sources that no longer exist on disk lose their rows — the same clearing
    # the old whole-project delete did, narrowed so that skipped sources keep
    # theirs. Every remaining source is replaced by upsert_chunks below.
    if table is not None:
        for feat_id, source_name in sorted(set(stored) - present):
            try:
                table.delete(_source_predicate(cfg.project, feat_id, source_name))
            except Exception as e:
                # Not silent: a failed delete leaves rows for a source that no
                # longer exists, which quietly degrades every later search.
                logger.warning("Could not clear rows for %s/%s (%s)", feat_id, source_name, e)

    # ── 4. write the already-computed embeddings
    for feat_id, source_name, chunks, hashes, vectors in pending:
        upsert_chunks(
            cfg.lancedb_path, cfg.project, feat_id, source_name, chunks, vectors,
            embedding_model=cfg.ollama_model, hashes=hashes,
        )

    return {
        "sources": total_sources,
        "chunks": total_chunks,
        "skipped": skipped_sources,
        "skipped_chunks": skipped_chunks,
        "embedded": reuse.embedded,
        "reused": reuse.reused,
        "changed": changed,
        "migration": migration,
        "migrated": migration == "recreated",
    }
