## Technical Breakdown — FEAT-008: Capture ideas away from the PC into a global inbox and triage them into the right project

The controlling constraint is that **capture and triage run in different worlds**. Capture may
run anywhere on the machine, including outside any Meridian repo, so it cannot call
`load_config()` — that raises `FileNotFoundError` without a `.meridian.toml`. Triage needs to
reach *into* arbitrary repos, so it cannot assume the current one. Everything below follows
from that split: a new "global" layer that knows about the machine, sitting beside the existing
per-repo layer that knows about one project.

### Components

| Component | What it does | New or existing? | Effort (S/M/L) |
|---|---|---|---|
| `meridian/home.py` | Resolves `~/.meridian` (honouring `MERIDIAN_HOME` for tests), creates `inbox/`, `inbox/.processed/`, `inbox/.icebox/` on demand. The only module that may be imported without a repo present. | New | S |
| `meridian/inbox.py` | Capture file read/write. `write_capture(text) -> Path`, `read_capture(path) -> Capture`, `list_captures() -> list[Capture]`, `archive(path, dest)`. Parses optional frontmatter and `#slug` hashtags; infers timestamp from filename then mtime. | New | M |
| `meridian/registry.py` | `~/.meridian/projects.toml` read/write. `register(slug, path, purpose)`, `all_projects() -> list[ProjectEntry]`, each entry flagged `exists: bool`. Never deletes a stale entry. | New | S |
| `meridian/routing.py` | Suggestion engine. Embeds capture text once, queries the shared store unscoped, aggregates hit scores per project, falls back to registry `purpose` embeddings for projects with no rows. Returns ranked `Suggestion` list. | New | M |
| `meridian/cli.py` — `capture` | `meridian capture "<text>"`. Must **not** call `_config()`. | Existing (modify) | S |
| `meridian/cli.py` — `inbox` | `inbox` (list), `inbox route <id> --project <slug>`, `inbox drop <id>`. | Existing (modify) | M |
| `meridian/cli.py` — `projects` | Lists registry entries with resolve status. | Existing (modify) | S |
| `meridian/cli.py` — `init`/`install` | Register the repo on setup, keyed by the FEAT-007 slug. | Existing (modify) | S |
| `meridian/specs.py` — `create_spec` | Reused as-is by `inbox route` to write the spec into the target repo. No signature change expected. | Existing | S |
| Tests | `test_inbox.py`, `test_registry.py`, `test_routing.py`, plus CLI cases. | New | M |

### Data Model

**Capture file** — `~/.meridian/inbox/2026-08-18T164500.md`

Frontmatter is entirely optional (AC2); a bare line of text is a valid capture.

```markdown
---
project: meridian      # optional — explicit routing hint (AC3)
goal: goal-01          # optional
appetite: s            # optional
created: '2026-08-18'  # optional — inferred from filename, then mtime
---
Idea body. May contain #meridian as an inline routing hint (AC4).
```

```python
@dataclass
class Capture:
    path: Path
    text: str                    # body, frontmatter stripped
    created: datetime            # filename → mtime fallback
    project: str | None          # frontmatter or #hashtag; None = needs routing
    goal: str | None
    appetite: str | None
    hint_source: str | None      # "frontmatter" | "hashtag" | None — drives the `explicit` label
```

**Project registry** — `~/.meridian/projects.toml`

```toml
[[project]]
slug    = "meridian"
path    = "/Users/petertomko/gd_projects/meridian"
purpose = "AI-driven development workflow system"
```

```python
@dataclass
class ProjectEntry:
    slug: str
    path: Path
    purpose: str
    exists: bool        # computed at load; stale entries are reported, never dropped (AC8)
```

**Suggestion** (in-memory only — nothing persisted)

```python
@dataclass
class Suggestion:
    slug: str
    score: float
    basis: str          # "index" | "purpose" | "explicit"
```

No change to the LanceDB `chunks` schema. Captures are **not** embedded into the research
corpus — unrouted noise must stay out of it (spec Open Questions).

### Integration Points

- **FEAT-007 `project` column** — the routing signal. `search_similar(..., project=None)`
  spans projects; each hit's `project` field is the vote. Without FEAT-007 this feature has no
  mechanism at all, which is why `depends_on: [feat-007]`.
- **Ollama `mxbai-embed-large`** via `enrich.embed()`. One embed call per capture during
  triage, not at capture time — capture must stay instant and must work offline.
- **`specs.create_spec()`** — reused by `inbox route` so routed ideas are indistinguishable
  from `meridian new` ones.
- **`specs.rebuild_registry()`** — must run in the *target* repo after routing, not the current one.
- **git** — `inbox route` shells out to `git status --porcelain` in the target repo to warn on a
  dirty tree (AC19). Advisory only; never blocks.
- **`meridian status`** — reads the pending inbox count (spec Open Question, leaning yes).

### Test Strategy

**Unit**
- `inbox.py`: frontmatter present/absent/malformed; hashtag extraction incl. multiple and
  none; timestamp inference from filename then mtime; whitespace-only capture rejected (AC20).
- `registry.py`: register/update-in-place (AC7), stale path flagged not dropped (AC8),
  missing and malformed TOML.
- `routing.py`: score aggregation per project with a stubbed `search_similar`; explicit hint
  short-circuits before any embed call (AC13); `purpose` fallback for a project with no rows (AC12).

**Integration**
- Round trip: `capture` → `inbox` lists it → `route` → spec exists in target repo, capture in
  `.processed/`, original file gone from `inbox/` (AC14).
- Idempotency: `route` twice on the same id fails cleanly, no duplicate spec (AC17).
- Isolation: routing into repo A leaves repo B untouched.
- **`capture` runs with no `.meridian.toml` anywhere up the tree** (AC5) — the failure mode
  most likely to be missed, since every existing CLI test runs inside a fixture repo.

**Manual**
- Real capture from a scratch directory, real triage in this repo.

All tests set `MERIDIAN_HOME` to `tmp_path`. No test may touch the developer's real
`~/.meridian` — the FEAT-007 wipe is the cautionary precedent.

### Total Effort Estimate

| Component | Effort |
|---|---|
| `home.py` | S |
| `inbox.py` | M |
| `registry.py` | S |
| `routing.py` | M |
| CLI commands (4) | M |
| Tests | M |

**Overall:** M — consistent with the spec's `m` appetite. The risk of overrun is `routing.py`;
if scoring proves fiddly, ship `inbox`/`route` with explicit `--project` only and add
suggestions second. Capture plus triage without suggestions is already the whole value.

### Implementation Order

1. **`home.py`** — everything else needs the paths, and it must import without a repo.
2. **`inbox.py`** — the file format is the contract; adapters and triage both depend on it.
3. **`meridian capture`** — makes the feature usable end-to-end before any routing exists.
4. **`registry.py`** + `init`/`install` registration — triage cannot find repos without it.
5. **`meridian projects`** — cheap, and makes the registry inspectable while building triage.
6. **`meridian inbox`** (list) — with `explicit` hints only; no suggestions yet.
7. **`inbox route` / `inbox drop`** — the archive-not-delete paths, plus the dirty-tree warning.
8. **`routing.py`** + wire suggestions into `inbox` — the part that can be cut under pressure.
9. **`meridian status` pending count**, docs (`CLAUDE.md`, `meridian help`), STEERING note.

Steps 1–7 deliver a complete, useful feature. Step 8 is the upgrade from "file it yourself"
to "confirm the suggestion".
