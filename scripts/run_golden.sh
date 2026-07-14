#!/usr/bin/env bash
# scripts/run_golden.sh — capture Layer 3 golden-set skill outputs.
#
# Runs each Meridian skill headlessly via the Claude Code CLI against the fixture
# project in tests/golden/project and writes the output to
# tests/golden/runs/<skill>_<feat>.md. Commit those files to establish the
# structural baseline that tests/test_golden_structure.py validates.
#
# Usage:
#   ./scripts/run_golden.sh                # capture all skills
#   ./scripts/run_golden.sh spec           # capture only /spec
#   DRY_RUN=1 ./scripts/run_golden.sh      # print the plan; invoke nothing
#
# Requires: `claude` (Claude Code CLI) in PATH, cwd = repo root.
# Ollama must be running for skills that embed/search (e.g. /research).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNS_DIR="$REPO_ROOT/tests/golden/runs"
PROJECT_DIR="$REPO_ROOT/tests/golden/project"
BUNDLED_SKILLS="$REPO_ROOT/meridian/skills/commands"

FILTER="${1:-}"       # optional: run only one skill
DRY_RUN="${DRY_RUN:-}"

# skill → fixture feature id (bash 3.2-compatible: parallel entries "skill:feat")
SKILL_FEATURES=(
  "spec:feat-901"
  "breakdown:feat-902"
  "tasks:feat-903"
  "research:feat-902"
)

mkdir -p "$RUNS_DIR"

# ── preflight ──────────────────────────────────────────────────────────────
if [[ -z "$DRY_RUN" ]] && ! command -v claude >/dev/null 2>&1; then
  echo "ERROR: 'claude' CLI not found in PATH." >&2
  echo "Install Claude Code, or run with DRY_RUN=1 to preview the commands." >&2
  exit 1
fi

# ── ensure the fixture project can resolve the skills + meridian config ──────
# The skills live in .claude/commands/ and call the `meridian` CLI, which needs
# a .meridian.toml. Provision both into the fixture so /spec etc. resolve there.
provision_fixture() {
  mkdir -p "$PROJECT_DIR/.claude/commands"
  cp "$BUNDLED_SKILLS"/*.md "$PROJECT_DIR/.claude/commands/"

  if [[ ! -f "$PROJECT_DIR/.meridian.toml" ]]; then
    cat > "$PROJECT_DIR/.meridian.toml" <<'TOML'
[meridian]
specs_path   = "specs"
lancedb_path = "~/.meridian/lancedb-golden"
ollama_model = "mxbai-embed-large"

[databricks]
host      = ""
token_env = "DATABRICKS_TOKEN"
TOML
  fi
}

capture() {
  local skill="$1" feat="$2"
  local outfile="$RUNS_DIR/${skill}_${feat}.md"

  if [[ -n "$FILTER" && "$FILTER" != "$skill" ]]; then
    return
  fi

  # The skill's model: frontmatter is honored by the CLI, so no --model here.
  # --dangerously-skip-permissions lets the skill read specs / run meridian
  # without interactive prompts; the fixture is a throwaway sandbox.
  local -a cmd=(
    claude -p "/$skill $feat"
    --output-format text
    --dangerously-skip-permissions
    --add-dir "$PROJECT_DIR"
  )

  echo "▶  /$skill $feat  →  ${outfile#"$REPO_ROOT"/}"
  if [[ -n "$DRY_RUN" ]]; then
    echo "   (cd $PROJECT_DIR && ${cmd[*]}) > $outfile"
    return
  fi

  ( cd "$PROJECT_DIR" && "${cmd[@]}" ) > "$outfile" 2>"$outfile.err" || {
    echo "   FAILED — see ${outfile}.err" >&2
    return 1
  }
  rm -f "$outfile.err"
}

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Meridian Golden-Set — Layer 3 AI Quality Eval"
echo "  Fixture: ${PROJECT_DIR#"$REPO_ROOT"/}    Outputs → ${RUNS_DIR#"$REPO_ROOT"/}/"
[[ -n "$DRY_RUN" ]] && echo "  DRY RUN — no skills invoked"
echo "═══════════════════════════════════════════════════════"
echo ""

if [[ -z "$DRY_RUN" ]]; then
  provision_fixture
else
  echo "would provision: $PROJECT_DIR/.claude/commands/ (+ .meridian.toml)"
  echo ""
fi

rc=0
for entry in "${SKILL_FEATURES[@]}"; do
  capture "${entry%%:*}" "${entry##*:}" || rc=1
done

echo ""
if [[ -n "$DRY_RUN" ]]; then
  echo "Dry run complete. Re-run without DRY_RUN=1 to capture."
else
  echo "Capture complete. Next:"
  echo "  pytest tests/test_golden_structure.py -v   # validate structure"
  echo "  python scripts/skill_consistency.py --skill spec --feat feat-901"
  echo "                                             # check run-to-run consistency"
  echo "  Then score outputs against tests/golden/RUBRIC.md"
fi
exit $rc
