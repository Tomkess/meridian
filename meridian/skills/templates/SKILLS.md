# Meridian Workflow Guide

## Mental Model

Meridian is spec-first and AI-native: **purpose flows from vision → goal → spec → tasks → code**.
The spec is the primary artifact. Code is derived from it.

```
specs/
  VISION.md     ← one-paragraph north star
  STEERING.md   ← AI context: injected into every skill
  CYCLES.md     ← betting cycle + icebox
  goals/        ← strategic bets (1–3 year horizons)
  FEAT-NNN/     ← spec → breakdown → tasks → build
```

---

## Workflow

### 1. Set your north star
```
/vision
```
Write or update `specs/VISION.md`. One paragraph. Do this once, revisit rarely.

### 2. Set project AI context
Edit `specs/STEERING.md` with:
- Architecture constraints (rules that apply to all features)
- Coding standards and naming conventions
- Domain glossary (project-specific terms)
- AI behavior notes (how Claude should work in this codebase)

This file is injected into every `/spec`, `/breakdown`, and `/tasks` run.

### 3. Define strategic goals
```
/goal new
```
Guided conversation. Runs 6 checks: alignment, overlap, conflict, scope, measurability, coverage.

### 4. Capture an idea
```
/idea
```
Freeform. Maps to a goal, asks for appetite, writes `specs/FEAT-NNN_name/spec.md` as an idea stub
and creates `specs/FEAT-NNN_name/tasks.md` (empty). Or capture directly:
```
meridian new "idea text" --goal goal-01 --appetite m
```

**Appetite scale:**
| Value | Time box |
|---|---|
| `xs` | < 1 day |
| `s`  | 1–3 days |
| `m`  | 1–2 weeks |
| `l`  | 2–6 weeks |

### 5. Enrich with research
```
meridian enrich feat-007 ~/Downloads/paper.pdf
meridian enrich feat-007 https://arxiv.org/abs/xxxx
```
Ingests source, extracts text, indexes into LanceDB vector store.

> **Timing is flexible:** research can happen before spec elaboration (to inform shaping)
> or after (to validate decisions). Both patterns are valid — `/spec` reads enriched sources either way.

### 6. Check relationships
```
```
Surfaces overlaps, dependencies, and synergies with existing specs and goals.

### 7. Elaborate the spec
```
/spec feat-007
```
Turns a draft idea into a structured spec: Summary, Appetite, Acceptance Criteria (Given/When/Then),
Scope, Out of Scope, Risks, Dependencies, Open Questions. Reads STEERING.md and prompts for appetite
if not set. Sets status → `draft`.

### 8. Break it down
```
/breakdown feat-007
```
Technical design: Components, Data Model, Integration Points, Test Strategy, Implementation Order.
Writes `breakdown.md`. Does **not** transition status — that happens after `/tasks`.

### 9. Generate tasks
```
/tasks feat-007
```
Produces an ordered, atomic, AI-executable task list from spec + breakdown. Each task is 1–4 hours.
Writes `tasks.md`. Sets status → `in-progress`.

### 10. Plan phases (optional)
```
```
Phased strategy for larger features (appetite `l` or multi-team). Writes `plan.md`. Optional — skip
for xs/s appetite features where tasks.md is sufficient.

### 11. Track status
```
meridian status
```
Dashboard: all features × lifecycle state × task progress [N/M] × appetite × confidence × cycle × dependencies.

### 12. Assign to a cycle
```
meridian cycle feat-007 --set 2026-Q2
```
Bet on the feature for a planning cycle. Update `specs/CYCLES.md` with the full cycle plan.

### 13. Close a feature
```
meridian close feat-007 --status done               # prompts to review spec.md for drift
meridian close feat-007 --status in-production
meridian close feat-007 --status blocked --blocked-by <reason>
meridian close feat-007 --confidence high            # update problem confidence separately
```

---

## Lifecycle

```
💡 idea  →  📝 draft  →  🔨 in-progress  →  ✅ done  →  🚀 in-production
                              ↕
                           🚫 blocked
                              ↓
                         🗑  abandoned  →  (revive → 💡 idea)
```

| Status | Meaning | Transition trigger |
|---|---|---|
| `idea` | Captured stub — spec.md exists, no ACs yet | Run `/spec` |
| `draft` | Spec elaborated; breakdown + tasks pending | Run `/breakdown` then `/tasks` |
| `in-progress` | Tasks generated; actively being built | `meridian close --status done` |
| `blocked` | Waiting on something external | `meridian close --status in-progress` |
| `done` | Built, not yet released | `meridian close --status in-production` |
| `in-production` | Live | Auto via `meridian transition --from-merge` |
| `abandoned` | Will not be built | `meridian close --status idea` (revive) |

---

## Artifacts per feature

| File | Produced by | Answers |
|---|---|---|
| `spec.md` | `/spec` | **What** — requirements, ACs, appetite, confidence |
| `breakdown.md` | `/breakdown` | **How** — architecture, data model, components |
| `tasks.md` | `/tasks` | **Work units** — ordered, checkable, AI-executable; each task has `Pre:` precondition |
| `sources/` | `meridian enrich` | Raw research corpus |
| `summaries/` | `/spec`, `/brief` | AI-generated summaries; `*-brief.md` = one-page paper briefs |

---

## All Commands

| CLI | Purpose |
|---|---|
| `meridian status` | Full dashboard (ID, name, goal, status [N/M], appetite, confidence, cycle, deps) |
| `meridian new "idea" --goal g --appetite m` | Quick-capture idea |
| `meridian close <feat> --status <s>` | Lifecycle transition (prints drift reminder at `done`) |
| `meridian close <feat> --status blocked --blocked-by <reason>` | Block with an explicit reason (sets `blocked_at`) |
| `meridian close <feat> --status abandoned --abandoned-reason <r>` | Abandon with reason — persists through revive |
| `meridian close <feat> --confidence <c>` | Set problem confidence: `low \| medium \| high` |
| `meridian cycle <feat> --set 2026-Q2` | Assign to planning cycle |
| `meridian cycle <feat> --clear` | Remove from cycle |
| `meridian enrich <feat> <source>` | Add research source |
| `meridian search "query"` | Semantic search across research |
| `meridian index` | Rebuild REGISTRY.md + vector index |
| `meridian transition --from-merge <branch>` | Auto-transition after git merge |
| `meridian guide` | Project setup advisor |

| Slash Command | Purpose |
|---|---|
| `/vision` | Read/update north star |
| `/goal new` | Create validated goal |
| `/goal review` | Re-validate all goals |
| `/idea` | Capture + map idea to goal (asks appetite) |
| `/spec` | Elaborate into structured spec + ACs |
| `/breakdown` | Technical decomposition → breakdown.md |
| `/tasks` | Atomic task list → tasks.md (triggers in-progress) |
| `/decision` | Write ADR |
| `/ask [question]` | RAG Q&A — answer a question from enriched research |
| `/research <feat>` | Deep synthesis — what we know, gaps, next actions |
| `/brief <feat> [source]` | One-page paper brief (≤ 550 words, A4) → summaries/ |
