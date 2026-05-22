---
id: adr-003
date: 2026-05-22
status: accepted
---

# 003 — LanceDB at global path for cross-branch visibility

**Decision:** Vector index stored at `~/.meridian/lancedb/`, not inside the repo.

**Considered:** In-repo LanceDB, git subtree, global path.

**Why:** Spec markdown travels with branches (for PR context). But the vector index needs to be visible across all branches simultaneously — you want `/connect-dots` to find relationships regardless of which branch you're on. Markdown = per-branch, index = global.
