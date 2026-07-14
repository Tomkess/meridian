"""Layer 3 structural tests — validate captured golden-set skill outputs.

These tests run against committed output files in ``tests/golden/runs/``.
They check *structure* only (required sections, frontmatter fields, Per:
lines) — not LLM content quality. That judgment belongs to the human rubric
in ``tests/golden/RUBRIC.md``.

Workflow:
  1. Run skills manually using ``scripts/run_golden.sh`` (or in Claude Code).
  2. Save each output to ``tests/golden/runs/<skill>_<feat>.md``.
  3. Commit the files — these become the structural baseline.
  4. On every subsequent CI run, this test suite validates the structure.
  5. When a skill prompt changes, re-run the skill, diff the output, update
     the committed baseline intentionally.

All tests skip when the corresponding run file is absent.
"""

from __future__ import annotations

import re
from pathlib import Path

import frontmatter
import pytest

RUNS = Path(__file__).parent / "golden" / "runs"
PROJECT = Path(__file__).parent / "golden" / "project" / "specs"


# ── helpers ───────────────────────────────────────────────────────────────── #


def _run(skill: str, feat: str) -> str | None:
    """Return run file content, or None if not yet captured."""
    p = RUNS / f"{skill}_{feat}.md"
    return p.read_text(encoding="utf-8") if p.exists() else None


def _has_section(text: str, heading: str) -> bool:
    """True if a markdown ## or ### heading with *heading* text exists.

    Skills legitimately place sections at either level — e.g. /spec uses ##
    sections, while /breakdown nests ### subsections under a single ##
    "Technical Breakdown" title (see meridian/skills/commands/breakdown.md).
    The skill template is the authoritative contract, so accept both.
    """
    return bool(
        re.search(rf"^#{{2,3}}\s+{re.escape(heading)}", text, re.MULTILINE | re.IGNORECASE)
    )


def _sections(text: str) -> list[str]:
    """Return all ## section headings in the text."""
    return re.findall(r"^##\s+(.+)$", text, re.MULTILINE)


def _tasks(text: str) -> list[str]:
    """Return all task lines (lines starting with '- [ ]' or '- [x]')."""
    return re.findall(r"^- \[[ x]\].*$", text, re.MULTILINE)


def _pre_lines(text: str) -> list[str]:
    """Return all 'Pre:' precondition lines in a tasks file."""
    return re.findall(r"^\s+Pre:.*$", text, re.MULTILINE)


# ── /spec output: FEAT-901 (xs/idea) ─────────────────────────────────────── #


class TestSpecOutput:
    """Structural checks for /spec run on FEAT-901 (xs/idea)."""

    REQUIRED_SECTIONS = [
        "Summary",
        "Appetite",
        "Acceptance Criteria",
        "Scope",
        "Out of Scope",
        "Key Risks",
        "Dependencies",
        "Open Questions",
    ]

    @pytest.fixture
    def output(self) -> str:
        text = _run("spec", "feat-901")
        if text is None:
            pytest.skip(
                "No captured output. Run /spec feat-901 and save to "
                "tests/golden/runs/spec_feat-901.md"
            )
        return text

    def test_all_required_sections_present(self, output: str) -> None:
        missing = [s for s in self.REQUIRED_SECTIONS if not _has_section(output, s)]
        assert not missing, f"Missing sections: {missing}"

    def test_acceptance_criteria_uses_given_when_then(self, output: str) -> None:
        # At least one AC must use Given/When/Then format
        assert re.search(r"given\b", output, re.IGNORECASE), (
            "No 'Given' found in output — ACs must use Given/When/Then format"
        )
        assert re.search(r"\bwhen\b", output, re.IGNORECASE), (
            "No 'when' found in output — ACs must use Given/When/Then format"
        )
        assert re.search(r"\bthen\b", output, re.IGNORECASE), (
            "No 'then' found in output — ACs must use Given/When/Then format"
        )

    def test_output_sets_confidence_field(self, output: str) -> None:
        # The spec output should set confidence (either in frontmatter or as CLI instruction)
        assert re.search(r"confidence", output, re.IGNORECASE), (
            "Output does not mention 'confidence' — spec should set or prompt for it"
        )

    def test_no_raw_tracebacks(self, output: str) -> None:
        assert "Traceback" not in output, "Output contains a Python traceback"

    def test_at_least_two_acs(self, output: str) -> None:
        acs = re.findall(r"- \[ \].*given", output, re.IGNORECASE)
        assert len(acs) >= 2, (
            f"Only {len(acs)} Given/When/Then AC(s) found — expected at least 2"
        )


# ── /breakdown output: FEAT-902 (m/draft) ────────────────────────────────── #


class TestBreakdownOutput:
    """Structural checks for /breakdown run on FEAT-902 (m/draft)."""

    @pytest.fixture
    def output(self) -> str:
        text = _run("breakdown", "feat-902")
        if text is None:
            pytest.skip(
                "No captured output. Run /breakdown feat-902 and save to "
                "tests/golden/runs/breakdown_feat-902.md"
            )
        return text

    def test_components_section_present(self, output: str) -> None:
        assert _has_section(output, "Components"), "Missing '## Components' section"

    def test_components_table_has_rows(self, output: str) -> None:
        # Markdown table: at least 3 data rows after header + separator
        rows = re.findall(r"^\|[^|]+\|[^|]+\|[^|]+\|", output, re.MULTILINE)
        # Subtract header row and separator row
        data_rows = [r for r in rows if not re.search(r"\|\s*-+\s*\|", r)]
        assert len(data_rows) >= 4, (  # header + 3 components minimum
            f"Components table has only {len(data_rows) - 1} data rows (expected ≥ 3)"
        )

    def test_implementation_order_section_present(self, output: str) -> None:
        assert _has_section(output, "Implementation Order"), (
            "Missing '## Implementation Order' section"
        )

    def test_implementation_order_is_numbered(self, output: str) -> None:
        numbered = re.findall(r"^\d+\.", output, re.MULTILINE)
        assert len(numbered) >= 3, (
            f"Implementation Order has {len(numbered)} numbered steps (expected ≥ 3)"
        )

    def test_test_strategy_section_present(self, output: str) -> None:
        assert _has_section(output, "Test Strategy"), "Missing '## Test Strategy' section"

    def test_effort_labels_present(self, output: str) -> None:
        # Each component should have an effort label: XS, S, M, L, or XL
        effort_labels = re.findall(r"\b(XS|S|M|L|XL)\b", output)
        assert len(effort_labels) >= 3, (
            f"Only {len(effort_labels)} effort label(s) found (expected ≥ 3, one per component)"
        )

    def test_no_raw_tracebacks(self, output: str) -> None:
        assert "Traceback" not in output


# ── /tasks output: FEAT-903 (l/in-progress — regenerate) ─────────────────── #


class TestTasksOutput:
    """Structural checks for /tasks run on FEAT-903 (l/in-progress)."""

    @pytest.fixture
    def output(self) -> str:
        text = _run("tasks", "feat-903")
        if text is None:
            pytest.skip(
                "No captured output. Run /tasks feat-903 and save to "
                "tests/golden/runs/tasks_feat-903.md"
            )
        return text

    def test_tasks_present(self, output: str) -> None:
        tasks = _tasks(output)
        assert len(tasks) >= 5, f"Only {len(tasks)} tasks found (expected ≥ 5 for appetite `l`)"

    def test_every_task_has_pre_line(self, output: str) -> None:
        tasks = _tasks(output)
        pre_lines = _pre_lines(output)
        assert len(pre_lines) >= len(tasks), (
            f"{len(tasks)} tasks but only {len(pre_lines)} Pre: lines — "
            "every task must have a Pre: precondition"
        )

    def test_pre_none_appears_for_first_task(self, output: str) -> None:
        # At least one task should have "Pre: none" (the first/standalone tasks)
        assert re.search(r"Pre:\s+none", output, re.IGNORECASE), (
            "No 'Pre: none' found — the first task (or standalone tasks) must use 'Pre: none'"
        )

    def test_ac_references_present(self, output: str) -> None:
        # At least some tasks should reference ACs
        ac_refs = re.findall(r"AC:\s*#\d+", output)
        assert len(ac_refs) >= 3, (
            f"Only {len(ac_refs)} AC reference(s) found — tasks should reference ACs"
        )

    def test_no_raw_tracebacks(self, output: str) -> None:
        assert "Traceback" not in output


# ── /research output: FEAT-902 ────────────────────────────────────────────── #


class TestResearchOutput:
    """Structural checks for /research run on FEAT-902 (m/draft)."""

    @pytest.fixture
    def output(self) -> str:
        text = _run("research", "feat-902")
        if text is None:
            pytest.skip(
                "No captured output. Run /research feat-902 and save to "
                "tests/golden/runs/research_feat-902.md"
            )
        return text

    def test_cross_feature_section_present(self, output: str) -> None:
        # Section may be titled "Cross-feature", "Related features", "Dependencies", etc.
        has_cross = any(
            re.search(pattern, output, re.IGNORECASE)
            for pattern in [
                r"cross.feature",
                r"related features?",
                r"## dependencies",
                r"## related",
            ]
        )
        assert has_cross, (
            "No cross-feature section found — /research must identify related features"
        )

    def test_next_actions_present(self, output: str) -> None:
        has_actions = any(
            re.search(pattern, output, re.IGNORECASE)
            for pattern in [
                r"next.actions?",
                r"next.steps?",
                r"## actions?",
                r"## recommendations?",
            ]
        )
        assert has_actions, "No next-actions section found — /research must suggest next steps"

    def test_no_raw_tracebacks(self, output: str) -> None:
        assert "Traceback" not in output


# ── /ask output: FEAT-902 ─────────────────────────────────────────────────── #


class TestAskOutput:
    """Structural checks for /ask run on FEAT-902."""

    @pytest.fixture
    def output(self) -> str:
        text = _run("ask", "feat-902")
        if text is None:
            pytest.skip(
                "No captured output. Run /ask 'what are the risks for feat-902?' "
                "and save to tests/golden/runs/ask_feat-902.md"
            )
        return text

    def test_cites_source_or_section(self, output: str) -> None:
        # Answer should cite a spec section, chunk, or source name
        has_cite = any(
            re.search(pattern, output, re.IGNORECASE)
            for pattern in [r"key risks", r"spec", r"chunk", r"source", r"feat-902"]
        )
        assert has_cite, "Answer does not appear to cite any source or spec section"

    def test_no_raw_tracebacks(self, output: str) -> None:
        assert "Traceback" not in output


# ── fixture integrity (always runs) ──────────────────────────────────────── #


class TestFixtures:
    """The fixture features themselves should be well-formed.

    These run on every CI invocation — no captured output needed.
    """

    @pytest.mark.parametrize("feat_dir", sorted(PROJECT.glob("FEAT-*")))
    def test_spec_has_required_frontmatter(self, feat_dir: Path) -> None:
        spec = feat_dir / "spec.md"
        assert spec.exists(), f"{feat_dir.name} has no spec.md"
        fm = dict(frontmatter.loads(spec.read_text()).metadata)
        for field in ("id", "status", "appetite"):
            assert field in fm, f"{feat_dir.name}/spec.md missing frontmatter field: {field}"

    def test_feat_901_is_idea(self) -> None:
        spec = PROJECT / "FEAT-901_xs_idea" / "spec.md"
        fm = dict(frontmatter.loads(spec.read_text()).metadata)
        assert fm["status"] == "idea"
        assert fm["appetite"] == "xs"

    def test_feat_902_is_draft(self) -> None:
        spec = PROJECT / "FEAT-902_m_draft" / "spec.md"
        fm = dict(frontmatter.loads(spec.read_text()).metadata)
        assert fm["status"] == "draft"
        assert fm["appetite"] == "m"

    def test_feat_903_is_in_progress_with_tasks(self) -> None:
        spec = PROJECT / "FEAT-903_l_in_progress" / "spec.md"
        tasks = PROJECT / "FEAT-903_l_in_progress" / "tasks.md"
        fm = dict(frontmatter.loads(spec.read_text()).metadata)
        assert fm["status"] == "in-progress"
        assert fm["appetite"] == "l"
        assert tasks.exists()

    def test_feat_903_tasks_have_pre_lines(self) -> None:
        tasks_text = (PROJECT / "FEAT-903_l_in_progress" / "tasks.md").read_text()
        task_list = _tasks(tasks_text)
        pre_list = _pre_lines(tasks_text)
        assert len(pre_list) >= len(task_list), (
            "Fixture tasks.md must have a Pre: line for every task "
            "(golden set depends on this as a correct baseline)"
        )
