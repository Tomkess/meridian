"""Citations — naming one chunk of research so a claim can be checked (FEAT-025).

A citation is `project:FEAT-NNN:source_name#chunk_idx`. Those four fields are
already the identity of a row in the LanceDB `chunks` table, so a citation needs
no schema change and no new column. Inventing a citation key would create a
*second* identity for the same row, and two identities can disagree.

The value of a citation is entirely in whether it resolves. A brief whose
citations cannot be checked is prose with decoration on it, so
:func:`resolve_citation` raises rather than degrades: a chunk that is no longer
in the store means the evidence moved and every conclusion drawn from it is
unverified.

Deliberately free of ``typer`` and ``rich`` — the CLI renders, this module
resolves. That keeps every failure mode reachable from a unit test.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meridian.config import MeridianConfig

# The canonical shape, quoted in error messages and in the skill prompts.
CITATION_FORMAT = "project:FEAT-NNN:source_name#chunk_idx"

_FEAT_ID = re.compile(r"^FEAT-\d+$", re.IGNORECASE)

# Wrapping a citation in backticks or brackets is how it appears inside a
# markdown brief; accept a pasted one either way.
_WRAPPERS = "`[]<>()"


# ─── Errors ───────────────────────────────────────────────────────────────── #


class CitationError(RuntimeError):
    """Base for every way a citation can fail to resolve."""


class CitationFormatError(CitationError):
    """The string is not a citation at all."""


class CitationProjectError(CitationError):
    """The citation names a project this machine cannot reach.

    Distinct from :class:`CitationMissingError` on purpose. "I cannot see that
    project" and "that chunk is gone" call for opposite responses — one is fixed
    by `meridian register`, the other means the evidence really did move.
    """


class CitationMissingError(CitationError):
    """The project is reachable but holds no such chunk."""


# ─── The citation itself ──────────────────────────────────────────────────── #


@dataclass(frozen=True)
class Citation:
    project: str
    feat_id: str
    source_name: str
    chunk_idx: int

    def __str__(self) -> str:
        return f"{self.project}:{self.feat_id}:{self.source_name}#{self.chunk_idx}"


@dataclass(frozen=True)
class ResolvedChunk:
    """A citation resolved back to the row it names."""

    citation: Citation
    text: str
    #: Where the source file should be. ``None`` when the feature directory
    #: cannot be located at all.
    source_path: Path | None
    #: Repo root of the project that owns the chunk.
    project_root: Path | None

    @property
    def source_exists(self) -> bool:
        return self.source_path is not None and self.source_path.exists()


def format_citation(row: Mapping[str, Any]) -> str:
    """Render the citation for one search-result row.

    Takes the row shape produced by ``search.semantic_search`` — and by
    ``enrich.search_similar`` beneath it — so search output and stored rows can
    never drift into disagreeing about what names a chunk.
    """
    missing = [f for f in ("project", "feat_id", "source_name") if not row.get(f)]
    if row.get("chunk_idx") is None:
        missing.append("chunk_idx")
    if missing:
        raise CitationFormatError(
            f"Cannot build a citation — the row is missing: {', '.join(missing)}."
        )
    return str(
        Citation(
            project=str(row["project"]),
            feat_id=str(row["feat_id"]).upper(),
            source_name=str(row["source_name"]),
            chunk_idx=int(row["chunk_idx"]),
        )
    )


def parse_citation(text: str) -> Citation:
    """Parse a citation string, raising :class:`CitationFormatError` if it isn't one.

    Splits left-to-right for the two leading fields and right-to-left for the
    chunk index, because a source name is a filename and may legitimately
    contain both ``:`` (a URL slug carrying a port) and ``#``.
    """
    raw = text.strip().strip(_WRAPPERS).strip()
    if not raw:
        raise CitationFormatError(f"Empty citation. Expected {CITATION_FORMAT}.")

    project, sep, rest = raw.partition(":")
    if not sep or not project or any(c.isspace() for c in project):
        raise CitationFormatError(
            f"'{text}' is not a citation — no project. Expected {CITATION_FORMAT}."
        )

    feat_id, sep, rest = rest.partition(":")
    if not sep or not _FEAT_ID.match(feat_id.strip()):
        raise CitationFormatError(
            f"'{text}' is not a citation — '{feat_id}' is not a feature ID. "
            f"Expected {CITATION_FORMAT}."
        )

    source_name, sep, idx = rest.rpartition("#")
    if not sep or not source_name.strip():
        raise CitationFormatError(
            f"'{text}' is not a citation — no source_name#chunk_idx. "
            f"Expected {CITATION_FORMAT}."
        )
    if not idx.strip().isdigit():
        raise CitationFormatError(
            f"'{text}' is not a citation — chunk index '{idx}' is not a number. "
            f"Expected {CITATION_FORMAT}."
        )

    return Citation(
        project=project,
        feat_id=feat_id.strip().upper(),
        source_name=source_name.strip(),
        chunk_idx=int(idx),
    )


# ─── Resolution ───────────────────────────────────────────────────────────── #


def _lookup_chunk(lancedb_path: Path, citation: Citation) -> str | None:
    """Fetch the one row a citation names, or None.

    Uses ``search().where(...)`` rather than ``to_arrow()``: the latter reads a
    single fragment and silently under-reports (10 rows for a 178-row table),
    which for a lookup would read as "the evidence is gone".
    """
    from meridian.enrich import (
        LegacyIndexError,
        _require_lancedb_compat,
        _sql_quote,
    )

    _require_lancedb_compat()
    import lancedb

    if not lancedb_path.exists():
        return None
    db = lancedb.connect(str(lancedb_path))
    if "chunks" not in db.table_names():
        return None
    table = db.open_table("chunks")
    if "project" not in set(table.schema.names):
        raise LegacyIndexError()

    predicate = (
        f"project = '{_sql_quote(citation.project)}' "
        f"AND feat_id = '{_sql_quote(citation.feat_id)}' "
        f"AND source_name = '{_sql_quote(citation.source_name)}' "
        f"AND chunk_idx = {citation.chunk_idx}"
    )
    rows = table.search().where(predicate).limit(1).to_list()
    if not rows:
        return None
    return str(rows[0].get("text", ""))


def _source_path(specs_path: Path, citation: Citation) -> Path | None:
    """Where the cited source file lives, or None if the feature is not on disk."""
    from meridian.specs import AmbiguousFeatureError, find_spec

    try:
        spec = find_spec(specs_path, citation.feat_id)
    except (ValueError, AmbiguousFeatureError):
        return None
    if spec is None:
        return None
    return spec.parent / "sources" / citation.source_name


def _foreign_target(citation: Citation) -> tuple[Path, Path, Path]:
    """Resolve another project's (lancedb_path, specs_path, root) via the registry.

    A foreign citation is only checkable if this machine knows where that repo
    is. Saying "chunk missing" when the truth is "I have never heard of that
    project" would send the reader looking for evidence that is fine.
    """
    from meridian.config import load_config
    from meridian.registry import RegistryUnreadableError, find_project

    try:
        entry = find_project(citation.project)
    except RegistryUnreadableError as e:
        raise CitationProjectError(str(e)) from e

    if entry is None:
        raise CitationProjectError(
            f"Project '{citation.project}' is not tracked on this machine, so "
            f"'{citation}' cannot be checked here. Register it with "
            f"`meridian register` from that repo, then retry."
        )
    if not entry.path.is_dir():
        raise CitationProjectError(
            f"Project '{citation.project}' is tracked at {entry.path}, which no "
            f"longer resolves. The chunk may be fine — the repo just is not "
            f"there. Re-register it from its new location."
        )
    try:
        foreign = load_config(entry.path)
    except FileNotFoundError as e:
        raise CitationProjectError(
            f"Project '{citation.project}' is tracked at {entry.path}, but that "
            f"directory has no .meridian.toml, so its index cannot be located."
        ) from e
    return foreign.lancedb_path, foreign.specs_path, foreign.root


def resolve_citation(citation: Citation, cfg: MeridianConfig) -> ResolvedChunk:
    """Resolve a citation to the chunk it names.

    Three distinct failures, deliberately not collapsed into one:

    ==========================  ==============================================
    condition                   raised
    ==========================  ==============================================
    project not reachable       :class:`CitationProjectError`
    project fine, chunk gone    :class:`CitationMissingError`
    chunk fine, file moved      *nothing* — resolves, ``source_exists`` False
    ==========================  ==============================================

    The last is not an error: the cited text is right here, so the claim is
    still checkable. Only the convenience pointer to the file went stale.
    """
    if citation.project == cfg.project:
        lancedb_path, specs_path, root = cfg.lancedb_path, cfg.specs_path, cfg.root
    else:
        lancedb_path, specs_path, root = _foreign_target(citation)

    text = _lookup_chunk(lancedb_path, citation)
    if text is None:
        raise CitationMissingError(
            f"No chunk matches '{citation}'. The index holds no "
            f"{citation.source_name}#{citation.chunk_idx} for {citation.feat_id} "
            f"in project '{citation.project}' — the evidence moved, so anything "
            f"resting on this citation is unverified. Re-run `meridian index` in "
            f"that project if the source is still on disk."
        )

    return ResolvedChunk(
        citation=citation,
        text=text,
        source_path=_source_path(specs_path, citation),
        project_root=root,
    )


def resolve(text: str, cfg: MeridianConfig) -> ResolvedChunk:
    """Parse and resolve in one step — what the CLI calls."""
    return resolve_citation(parse_citation(text), cfg)
