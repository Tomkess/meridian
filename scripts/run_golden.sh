#!/usr/bin/env bash
# scripts/run_golden.sh — capture Layer 3 golden-set skill outputs.
#
# Runs each Meridian skill headlessly via the Claude Code CLI against an
# ISOLATED copy of the fixture project and writes the produced artifact to
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
#
# ISOLATION: the fixture is copied to a temp dir OUTSIDE the repo and run with
# a clean $HOME, so (a) skill file-writes never touch the tracked fixture, and
# (b) the global ~/.claude memory/plugins can't bias the run (nested runs
# otherwise inherit this repo's real FEAT-001..005 context and misread the
# fixture's FEAT-901..903). Each skill's artifact is copied back into runs/.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNS_DIR="$REPO_ROOT/tests/golden/runs"
FIXTURE_SRC="$REPO_ROOT/tests/golden/project"
BUNDLED_SKILLS="$REPO_ROOT/meridian/skills/commands"
ASSETS_DIR="$REPO_ROOT/tests/golden/research_assets"   # staged sources to enrich

FILTER="${1:-}"       # optional: run only one skill
DRY_RUN="${DRY_RUN:-}"

# skill : fixture feature id : artifact path relative to the fixture root
#         [: prompt override]
# - "STDOUT" as the artifact captures the skill's printed output, not a file.
# - The optional 4th field overrides the invocation (default: "/<skill> <feat>");
#   the output file is always runs/<skill>_<feat>.md. Used for skills like /ask
#   that take a free-text question rather than a bare feature id.
PLAN=(
  "spec:feat-901:specs/FEAT-901_xs_idea/spec.md"
  "breakdown:feat-902:specs/FEAT-902_m_draft/breakdown.md"
  "tasks:feat-904:specs/FEAT-904_m_ready_for_tasks/tasks.md"
  "research:feat-902:STDOUT"
  "ask:feat-902:STDOUT:/meridian:ask what are the key risks for feat-902? --feat feat-902"
)

mkdir -p "$RUNS_DIR"

if [[ -z "$DRY_RUN" ]] && ! command -v claude >/dev/null 2>&1; then
  echo "ERROR: 'claude' CLI not found in PATH." >&2
  echo "Install Claude Code, or run with DRY_RUN=1 to preview the commands." >&2
  exit 1
fi

# Isolated sandbox: fixture copy + clean HOME. Cleaned up on exit.
SANDBOX="" ; CLEAN_HOME=""
cleanup() { [[ -n "$SANDBOX" ]] && rm -rf "$SANDBOX" "$CLEAN_HOME" 2>/dev/null || true; }
trap cleanup EXIT

provision() {
  SANDBOX="$(mktemp -d "${TMPDIR:-/tmp}/meridian-golden.XXXXXX")"
  CLEAN_HOME="$(mktemp -d "${TMPDIR:-/tmp}/meridian-home.XXXXXX")"
  cp -R "$FIXTURE_SRC/specs" "$SANDBOX/"
  [[ -f "$FIXTURE_SRC/.meridian.toml" ]] && cp "$FIXTURE_SRC/.meridian.toml" "$SANDBOX/"
  mkdir -p "$SANDBOX/.claude/commands/meridian"
  cp "$BUNDLED_SKILLS"/*.md "$SANDBOX/.claude/commands/meridian/"

  # /research and /ask need a populated vector corpus (they halt / find nothing
  # otherwise). Enrich the staged research assets into their feature, then index.
  # Assets live OUTSIDE the fixture's sources/ (enrich copies them in + embeds);
  # layout is tests/golden/research_assets/<feat-id>/<file>. The corpus writes to
  # the sandbox-relative lancedb_path, so the child `claude`'s `meridian search`
  # reads exactly what we just wrote — no HOME coupling. Requires Ollama.
  if [[ -z "$FILTER" || "$FILTER" == research || "$FILTER" == ask ]]; then
    if command -v meridian >/dev/null 2>&1 && [[ -d "$ASSETS_DIR" ]]; then
      local sfile featid
      while IFS= read -r -d '' sfile; do
        featid="$(basename "$(dirname "$sfile")")"   # feat-902
        echo "   enrich $featid ← ${sfile#"$REPO_ROOT"/}"
        ( cd "$SANDBOX" && meridian enrich "$featid" "$sfile" >/dev/null 2>&1 ) \
          || echo "   WARN: enrich failed for $featid ($sfile)" >&2
      done < <(find "$ASSETS_DIR" -type f -print0)
      ( cd "$SANDBOX" && meridian index >/dev/null 2>&1 ) \
        || echo "   WARN: index failed — corpus may be empty" >&2
    elif [[ ! -d "$ASSETS_DIR" ]]; then
      echo "   WARN: no research_assets/ — /research and /ask find no corpus" >&2
    else
      echo "   WARN: meridian not on PATH; /research and /ask find no corpus" >&2
    fi
  fi
}

capture() {
  local skill="$1" feat="$2" artifact="$3"
  local prompt="${4:-/meridian:$skill $feat}"
  local outfile="$RUNS_DIR/${skill}_${feat}.md"
  [[ -n "$FILTER" && "$FILTER" != "$skill" ]] && return 0

  echo "▶  $prompt  →  ${outfile#"$REPO_ROOT"/}  (artifact: $artifact)"
  if [[ -n "$DRY_RUN" ]]; then
    echo "   env -i PATH HOME=<clean> ANTHROPIC_API_KEY claude -p \"$prompt\" (in \$SANDBOX)"
    return 0
  fi

  # Clean HOME + minimal env; the skill's model: frontmatter is honored by the CLI.
  ( cd "$SANDBOX" && env -i \
      PATH="$PATH" HOME="$CLEAN_HOME" ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}" \
      claude -p "$prompt" --output-format text --dangerously-skip-permissions \
      < /dev/null ) > "$SANDBOX/.stdout" 2>"$outfile.err" || {
        echo "   FAILED — see ${outfile}.err" >&2 ; return 1 ; }

  if [[ "$artifact" == "STDOUT" ]]; then
    cp "$SANDBOX/.stdout" "$outfile"
  elif [[ -f "$SANDBOX/$artifact" ]]; then
    cp "$SANDBOX/$artifact" "$outfile"
  else
    echo "   WARN: expected artifact not found ($artifact); saving stdout instead" >&2
    cp "$SANDBOX/.stdout" "$outfile"
  fi
  rm -f "$outfile.err"
  echo "   captured $(wc -c < "$outfile" | tr -d ' ') bytes"
}

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Meridian Golden-Set — Layer 3 AI Quality Eval"
echo "  Isolated sandbox + clean HOME   Outputs → ${RUNS_DIR#"$REPO_ROOT"/}/"
[[ -n "$DRY_RUN" ]] && echo "  DRY RUN — no skills invoked"
echo "═══════════════════════════════════════════════════════"
echo ""

[[ -z "$DRY_RUN" ]] && provision

rc=0
for entry in "${PLAN[@]}"; do
  IFS=":" read -r skill feat artifact prompt <<< "$entry"
  capture "$skill" "$feat" "$artifact" "$prompt" || rc=1
done

echo ""
if [[ -n "$DRY_RUN" ]]; then
  echo "Dry run complete. Re-run without DRY_RUN=1 to capture."
else
  echo "Capture complete. Next:"
  echo "  pytest tests/test_golden_structure.py -v   # validate structure"
  echo "  git add tests/golden/runs/ && commit       # establish the baseline"
  echo "  Then score outputs against tests/golden/RUBRIC.md"
fi
exit $rc
