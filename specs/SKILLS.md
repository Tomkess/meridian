# Meridian Workflow Guide

## The Stack

```
VISION.md          ← one paragraph north star
  └── goals/       ← strategic bets, 1-3 year horizons
        └── specs/ ← feature implementations
```

## Workflow

### 1. Set your north star
```
/vision
```
Write or update `specs/VISION.md`. Do this once, revisit rarely.

### 2. Define strategic goals
```
/goal new
```
Guided conversation. Runs 6 checks: alignment, overlap, conflict, scope, measurability, coverage.

### 3. Capture an idea
```
/idea
```
Freeform. Maps to a goal. Writes `specs/FEAT-NNN_name/spec.md` as a draft.

### 4. Enrich with research
```
meridian enrich feat-007 ~/Downloads/paper.pdf
meridian enrich feat-007 https://arxiv.org/abs/xxxx
meridian enrich feat-007 ~/Downloads/screenshot.png
```
Ingests source, extracts text, summarizes, indexes into LanceDB.

### 5. Check relationships
```
/connect-dots
```
Surfaces overlaps, dependencies, and synergies with existing specs and goals.

### 6. Elaborate the spec
```
/spec
```
Turns a draft idea into a structured spec with acceptance criteria, scope, risks.

### 7. Break it down
```
/breakdown
```
Technical decomposition — components, dependencies, effort.

### 8. Plan implementation
```
/plan
```
Phased implementation plan ready to execute.

### 9. Track status
```
meridian status
```
Dashboard: all features × lifecycle state × Databricks job health.

### 10. Close a feature
```
meridian close feat-007 --status done
meridian close feat-007 --status in-production
```

## Lifecycle

```
idea → draft → in-progress → done → in-production
                    ↓                     ↑
                 blocked            (auto on merge)
                    ↓
                abandoned
```

`in-production` = merged to master AND/OR scheduled in Databricks.

## All Commands

| CLI | Purpose |
|---|---|
| `meridian status` | Full dashboard |
| `meridian enrich <feat> <source>` | Add research source |
| `meridian close <feat> --status <s>` | Lifecycle transition |
| `meridian sync-jobs` | Auto-link Databricks jobs |
| `meridian index` | Rebuild vector index |
| `meridian new "<idea>"` | Quick-capture idea |

| Slash Command | Purpose |
|---|---|
| `/vision` | Read/update north star |
| `/goal new` | Create validated goal |
| `/goal review` | Re-validate all goals |
| `/idea` | Capture + map idea to goal |
| `/spec` | Elaborate into structured spec |
| `/connect-dots` | Cross-feature awareness |
| `/breakdown` | Technical decomposition |
| `/plan` | Phased implementation plan |
| `/roadmap` | Goals × features × gaps |
| `/challenge` | Stress-test against vision |
| `/decision` | Write ADR |
