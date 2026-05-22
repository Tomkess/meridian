---
id: adr-002
date: 2026-05-22
status: accepted
---

# 002 — Specs folder travels with the branch

**Decision:** Spec markdown files live in `specs/` inside the repo and travel with feature branches.

**Considered:** Dedicated specs branch, external wiki, standalone repo.

**Why:** Specs are reviewable in PRs, versionable in git, and provide context for the code they describe. A spec and its implementation live and die together on the same branch.
