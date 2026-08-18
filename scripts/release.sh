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
# The version lives in exactly one place — meridian/__init__.py — and
# pyproject.toml reads it via [tool.setuptools.dynamic].

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

CURRENT="$(python3 -c 'import re,pathlib; print(re.search(r"\"(.+?)\"", pathlib.Path("meridian/__init__.py").read_text()).group(1))')"

NEXT="$(python3 - "$CURRENT" "$BUMP" <<'PY'
import sys
current, bump = sys.argv[1], sys.argv[2]
major, minor, patch = (int(p) for p in current.split("."))
if bump == "major":
    major, minor, patch = major + 1, 0, 0
elif bump == "minor":
    minor, patch = minor + 1, 0
elif bump == "patch":
    patch += 1
else:
    parts = bump.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        sys.exit(f"not a bump keyword or X.Y.Z version: {bump}")
    major, minor, patch = (int(p) for p in parts)
print(f"{major}.{minor}.{patch}")
PY
)"

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

# ── quality gate ───────────────────────────────────────────────────────────── #
# CI cannot run on this repo (private, Actions billing), so this is the only gate.

step "Tests, lint, types"
python3 -m pytest tests/ -q
python3 -m ruff check meridian tests
python3 -m mypy meridian

# ── bump ───────────────────────────────────────────────────────────────────── #

step "Bumping meridian/__init__.py"
if [[ -z "$DRY_RUN" ]]; then
  python3 - "$NEXT" <<'PY'
import pathlib, re, sys
path = pathlib.Path("meridian/__init__.py")
path.write_text(re.sub(r'__version__ = "[^"]+"', f'__version__ = "{sys.argv[1]}"', path.read_text()))
PY
else
  printf '   would set __version__ = "%s"\n' "$NEXT"
fi

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
run git add meridian/__init__.py CHANGELOG.md
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
  meridian install --all --pr --dry-run   # preview skill PRs into tracked repos
  meridian install --all --pr             # open them

Note: your local install is editable (uv tool install --editable), so this
machine already runs the new code. Other machines install with:

  uv tool install git+https://github.com/Tomkess/meridian@${TAG}
EOF
