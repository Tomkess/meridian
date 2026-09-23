#!/usr/bin/env bash
#
# Cut a Meridian release.
#
#   scripts/release.sh patch|minor|major     # bump from the current version
#   scripts/release.sh 0.3.0                 # set an explicit version
#   scripts/release.sh patch --dry-run       # show what would happen
#
# Everything runs locally. No GitHub Actions minutes are consumed: `gh release
# create` is a REST call, not a workflow. That matters here because this repo is
# private and its Actions quota is unavailable.
#
# The version lives in exactly one place — `version` in pyproject.toml, bumped by
# `uv version`. meridian/__init__.py reads it back from installed metadata.
#
# Every check runs through `uv run --locked`, so the gate uses the pinned
# dependency set rather than whatever interpreter happens to be on PATH.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BUMP="${1:-}"
DRY_RUN=""
[[ "${2:-}" == "--dry-run" ]] && DRY_RUN="1"

die() { printf '\033[31merror:\033[0m %s\n' "$1" >&2; exit 1; }
step() { printf '\033[1m==>\033[0m %s\n' "$1"; }
run() { if [[ -n "$DRY_RUN" ]]; then printf '   would run: %s\n' "$*"; else "$@"; fi; }

[[ -n "$BUMP" ]] || die "usage: scripts/release.sh patch|minor|major|X.Y.Z [--dry-run]"

command -v uv >/dev/null || die "uv is required — https://docs.astral.sh/uv/"

CURRENT="$(uv version --short)"

# Let uv compute the next version so there is no second implementation of
# semver to keep correct. --dry-run prints "name old => new".
case "$BUMP" in
  major|minor|patch)
    NEXT="$(uv version --bump "$BUMP" --dry-run --short 2>/dev/null | tail -1)"
    ;;
  *)
    [[ "$BUMP" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] \
      || die "not a bump keyword or X.Y.Z version: $BUMP"
    NEXT="$BUMP"
    ;;
esac
[[ -n "$NEXT" ]] || die "could not determine the next version"

TAG="v${NEXT}"
step "Releasing ${CURRENT} → ${NEXT}"

# ── preflight ──────────────────────────────────────────────────────────────── #
# A release must be reproducible from what is on the default branch, so refuse
# to cut one from a feature branch or a dirty tree.

step "Preflight"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
[[ "$BRANCH" == "main" ]] || die "on branch '$BRANCH' — release from main"
[[ -z "$(git status --porcelain)" ]] || die "working tree is dirty — commit or stash first"

git fetch --quiet origin main
[[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/main)" ]] \
  || die "main is not in sync with origin/main — pull or push first"

if git rev-parse "$TAG" >/dev/null 2>&1; then
  die "tag $TAG already exists"
fi

# A stale lock means the gate below would not be testing what ships.
uv lock --check >/dev/null 2>&1 || die "uv.lock is out of date — run 'uv lock' and commit it"

# ── quality gate ───────────────────────────────────────────────────────────── #
# CI cannot run on this repo (private, Actions billing), so this is the only gate.

step "Tests, lint, types (locked environment)"
uv run --locked python -m pytest tests/ -q
uv run --locked ruff check meridian tests
uv run --locked mypy meridian

# ── bump ───────────────────────────────────────────────────────────────────── #

step "Bumping version"
run uv version "$NEXT"

step "Updating CHANGELOG.md"
if [[ -z "$DRY_RUN" ]]; then
  python3 - "$NEXT" <<'PY'
import datetime, pathlib, subprocess, sys

version = sys.argv[1]
path = pathlib.Path("CHANGELOG.md")
text = path.read_text() if path.exists() else "# Changelog\n\n"

previous = subprocess.run(
    ["git", "describe", "--tags", "--abbrev=0"],
    capture_output=True, text=True,
).stdout.strip()
rng = f"{previous}..HEAD" if previous else "HEAD"
log = subprocess.run(
    ["git", "log", rng, "--no-merges", "--pretty=- %s"],
    capture_output=True, text=True,
).stdout.strip() or "- (no changes recorded)"

entry = f"## {version} — {datetime.date.today().isoformat()}\n\n{log}\n\n"
marker = "# Changelog\n\n"
text = text.replace(marker, marker + entry, 1) if marker in text else marker + entry + text
path.write_text(text)
PY
  printf '   review the generated section before continuing\n'
else
  printf '   would prepend a section for %s\n' "$NEXT"
fi

# ── commit, tag, push, release ─────────────────────────────────────────────── #

step "Commit and tag"
run git add pyproject.toml uv.lock CHANGELOG.md
run git commit -m "chore: release ${TAG}"
run git tag -a "$TAG" -m "Meridian ${TAG}"
run git push origin main
run git push origin "$TAG"

step "GitHub release"
run gh release create "$TAG" --title "Meridian ${TAG}" --generate-notes

# ── after ──────────────────────────────────────────────────────────────────── #

cat <<EOF

$(printf '\033[32m✓\033[0m') ${TAG} released.

Next:
  meridian install                        # refresh ~/.claude/commands/meridian/

Skills install globally and are gitignored in consumer repos (ADR-007), so
there are no per-repo skill PRs to open — one install covers every project on
this machine.

Note: your local install is editable (uv tool install --editable), so this
machine already runs the new code. Other machines install with:

  uv tool install git+https://github.com/Tomkess/meridian@${TAG}
EOF
