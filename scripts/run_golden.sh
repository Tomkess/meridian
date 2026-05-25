#!/usr/bin/env bash
# scripts/run_golden.sh — run each Layer 3 golden-set skill and capture outputs
#
# Usage:
#   ./scripts/run_golden.sh          # run all skills on all fixtures
#   ./scripts/run_golden.sh spec     # run only /spec
#
# Outputs are written to tests/golden/runs/<skill>_<feat>.md
# Commit those files to establish the structural baseline for test_golden_structure.py.
#
# Requires: Claude Code CLI (`claude`) in PATH, cwd = repo root

set -euo pipefail

RUNS_DIR="tests/golden/runs"
PROJECT_DIR="tests/golden/project"
mkdir -p "$RUNS_DIR"

# Skills to run and their fixture targets
declare -A SKILLS=(
  ["spec"]="feat-901"
  ["breakdown"]="feat-902"
  ["tasks"]="feat-903"
  ["research"]="feat-902"
)

FILTER="${1:-}"  # optional: run only one skill

run_skill() {
  local skill="$1"
  local feat="$2"
  local outfile="$RUNS_DIR/${skill}_${feat}.md"

  if [[ -n "$FILTER" && "$FILTER" != "$skill" ]]; then
    return
  fi

  echo "▶  /$skill $feat  →  $outfile"
  cd "$PROJECT_DIR"
  # Run the Claude Code skill and capture output
  # claude --skill "$skill" "$feat" > "../../../$outfile" 2>&1
  # ↑ Uncomment and adjust to your Claude Code CLI invocation syntax.
  # For now, this prints a reminder to run manually.
  echo ""
  echo "  Run this in Claude Code inside $PROJECT_DIR:"
  echo "  /$skill $feat"
  echo "  Then save the output to: ../../../$outfile"
  echo ""
  cd - > /dev/null
}

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Meridian Golden-Set — Layer 3 AI Quality Eval"
echo "  Outputs → $RUNS_DIR/"
echo "═══════════════════════════════════════════════════════"
echo ""

for skill in "${!SKILLS[@]}"; do
  run_skill "$skill" "${SKILLS[$skill]}"
done

echo ""
echo "After capturing outputs, run:"
echo "  pytest tests/test_golden_structure.py -v"
echo ""
echo "Then score each output against:"
echo "  tests/golden/RUBRIC.md"
