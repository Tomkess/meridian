---
id: adr-004
date: 2026-05-22
status: accepted
---

# 004 — CLI owns ops, skills own reasoning

**Decision:** `meridian` CLI handles all file system and vector store operations. Claude Code slash commands handle all AI reasoning. Skills may shell out to CLI, never the reverse.

**Considered:** Skills doing everything, CLI doing everything, hybrid.

**Why:** Clean dependency direction. CLI is testable, scriptable, hookable without Claude. Skills focus purely on reasoning quality. Prevents circular dependencies and makes each layer independently improvable.
