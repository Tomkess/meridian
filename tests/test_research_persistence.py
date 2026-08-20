"""Research persists, with citations that resolve (FEAT-025, AC5–AC9 + AC14).

AC5–AC9 are enforced by a *prompt*, and prompts drift. There is no way to unit
test what an LLM writes, so this file tests the two things that can be tested:

  * the contract in the skill text — a prompt edit that deletes the citation
    rule, the inference label, or the "never modify an earlier brief" rule
    fails here rather than in six months' worth of unverifiable briefs;
  * the format of any citation that appears in a captured golden run — so the
    next capture is checked against the same parser `meridian cite` uses.

That is a weaker guard than a captured run, and the spec says so. See the
"citation discipline" section of tests/golden/RUBRIC.md for the regression-
critical behaviour and the standing re-capture.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from meridian.citations import CITATION_FORMAT, parse_citation

REPO_ROOT = Path(__file__).parents[1]
BUNDLED = REPO_ROOT / "meridian" / "skills" / "commands"
RUNS = Path(__file__).parent / "golden" / "runs"
RUBRIC = Path(__file__).parent / "golden" / "RUBRIC.md"

RESEARCH = BUNDLED / "research.md"
BRIEF = BUNDLED / "brief.md"

# Anything shaped like a citation: <project>:FEAT-NNN:<source>#<idx>.
CITATION_SHAPED = re.compile(r"\b([\w.-]+:FEAT-\d+:[^\s`\]]+#\d+)")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _squash(text: str) -> str:
    """Collapse whitespace, so a rule wrapping across lines still matches."""
    return re.sub(r"\s+", " ", text)


# ── AC5: /research writes a dated brief ───────────────────────────────────── #


class TestResearchWritesADatedBrief:
    def test_names_the_dated_path(self) -> None:
        assert "summaries/research-YYYY-MM-DD.md" in _text(RESEARCH)

    @pytest.mark.parametrize("section", ["Key findings", "Research gaps",
                                         "Recommended next actions"])
    def test_output_format_still_carries_the_required_sections(
        self, section: str
    ) -> None:
        assert section in _text(RESEARCH)

    def test_the_brief_is_written_not_only_printed(self) -> None:
        text = _text(RESEARCH)
        assert "Write the brief to" in text
        assert "Print the same content to the conversation" in text


# ── AC7: same-day updates; earlier briefs are immutable ───────────────────── #


class TestDatedAndAdditive:
    def test_same_day_rerun_rewrites_that_days_file(self) -> None:
        text = _text(RESEARCH)
        assert "If that file already exists" in text
        assert "supersedes" in text

    def test_an_earlier_brief_is_never_modified(self) -> None:
        text = _text(RESEARCH)
        assert "Never modify a `research-*.md` from any earlier date" in text
        # The reason, not just the rule — a rule without one gets optimised away.
        assert "diffed against" in text

    def test_brief_skill_also_refuses_to_touch_research_files(self) -> None:
        """/brief writes into the same directory /research does."""
        assert "never modify a `research-*.md`" in _squash(_text(BRIEF))


# ── AC6 / AC8: cite, or say it is an inference ────────────────────────────── #


@pytest.mark.parametrize("skill", [RESEARCH, BRIEF], ids=lambda p: p.name)
class TestCitationDiscipline:
    def test_states_the_citation_format(self, skill: Path) -> None:
        assert CITATION_FORMAT in _text(skill), (
            f"{skill.name} must name the citation format verbatim — a skill that "
            "invents its own format produces citations meridian cite cannot resolve"
        )

    def test_requires_a_citation_on_every_factual_claim(self, skill: Path) -> None:
        text = _text(skill).lower()
        assert "every factual claim" in text

    def test_labels_uncited_claims_as_inferences(self, skill: Path) -> None:
        assert "*(inference — no supporting chunk)*" in _text(skill), (
            f"{skill.name} dropped the inference label. An uncited claim that is "
            "not labelled reads exactly like a cited one."
        )

    def test_forbids_citing_synthesis(self, skill: Path) -> None:
        text = _text(skill)
        assert "Never cite a file in `summaries/`" in text, (
            f"{skill.name} must forbid citing summaries/ — citing synthesis is "
            "the loop that manufactures confidence out of nothing"
        )

    def test_checks_a_citation_before_writing(self, skill: Path) -> None:
        assert 'meridian cite "<citation>"' in _text(skill)

    def test_takes_citation_fields_from_json_search_output(self, skill: Path) -> None:
        """Hand-copied fields drift; --json carries the four identity fields."""
        assert "--json" in _text(skill)


# ── AC9: the spec points at the reasoning ─────────────────────────────────── #


@pytest.mark.parametrize("skill", [RESEARCH, BRIEF], ids=lambda p: p.name)
class TestSpecRecordsTheBriefs:
    def test_writes_a_briefs_frontmatter_list(self, skill: Path) -> None:
        text = _text(skill)
        assert "briefs:" in text
        assert "frontmatter" in text

    def test_does_not_pollute_the_sources_list(self, skill: Path) -> None:
        """`sources:` lists inputs. A brief is output; mixing them would make the
        next reindex look like it lost sources."""
        assert "leave `sources:` alone" in _squash(_text(skill))


# ── AC14: the golden gate ─────────────────────────────────────────────────── #


class TestGoldenGate:
    def test_rubric_names_the_regression_critical_behaviour(self) -> None:
        rubric = _text(RUBRIC)
        assert "Regression-critical behaviour" in rubric
        assert "cites rather than asserts" in rubric
        assert "labelled an inference" in rubric

    def test_research_still_has_a_captured_run(self) -> None:
        """The coverage gate in test_golden_structure.py depends on this file."""
        assert list(RUNS.glob("research_*.md")), "no /research capture at all"

    @pytest.mark.parametrize("run", sorted(RUNS.glob("*.md")), ids=lambda p: p.name)
    def test_every_citation_in_a_captured_run_parses(self, run: Path) -> None:
        """Guards the *next* capture: a citation the resolver cannot read is
        worse than no citation, because it looks checkable."""
        for match in CITATION_SHAPED.findall(_text(run)):
            parse_citation(match)  # raises CitationFormatError if malformed
