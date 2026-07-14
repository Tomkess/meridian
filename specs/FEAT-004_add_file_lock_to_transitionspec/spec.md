---
abandoned_at: null
abandoned_reason: null
appetite: xs
blocked_at: null
blocked_by: null
confidence: null
created: '2026-07-14'
cycle: null
depends_on: []
enables: []
goal: '~'
id: feat-004
name: Add file lock to transition_spec() to prevent frontmatter corruption under concurrent
  multi-agent/worktree writes
scheduler: null
sources: []
status: done
tags: []
updated: '2026-07-14'
---

## What was built

`spec_lock(spec_path)` context manager in `meridian/specs.py` — an advisory
exclusive lock (`fcntl.flock`) that serializes the read-modify-write in
`transition_spec`. The whole load → validate → mutate → save cycle now runs
under the lock, so two agents transitioning the same feature concurrently can
no longer interleave and drop an update (last-writer-wins).

Design notes:
- Lock file lives in the system temp dir, keyed by a hash of the spec's
  absolute path — no repo pollution, and distinct specs never block each other.
- Degrades to a no-op on platforms without `fcntl` (e.g. Windows); acceptable
  for the single-user case, where contention only arises under parallel
  multi-agent / worktree workflows on POSIX.

Tests: `tests/test_spec_lock.py` (6). The mutual-exclusion test races 25 threads
through a deliberately non-atomic increment — verified it lands 25/25 with the
lock and loses updates (final=3, plus half-write crashes) without it, so the
test genuinely proves the fix. Suite 321 passed / 22 skipped; ruff + mypy clean.
