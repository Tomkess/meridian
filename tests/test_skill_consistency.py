"""Unit tests for the skill-consistency engine (scripts/skill_consistency.py).

These cover the pure structural comparison — the half of FEAT-003 that does not
require invoking the Claude Code CLI. The actual twice-over skill runs are driven
by the module's CLI (`--skill/--feat`) and exercised interactively.

Run:  .venv/bin/pytest tests/test_skill_consistency.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

# The harness lives in scripts/, which is not an installed package.
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from skill_consistency import (  # noqa: E402
    compare_texts,
    extract_structure,
)

# ── fixtures ─────────────────────────────────────────────────────────────── #

RUN_A = """\
---
id: feat-901
status: draft
appetite: xs
---

## Problem
The users cannot foo the bar.

## Acceptance Criteria
- Given X, when Y, then Z.

## Out of Scope
Nothing here.
"""

# Same structure, entirely different prose + heading wording/numbering variance.
RUN_B_CONSISTENT = """\
---
id: feat-901
status: draft
appetite: xs
---

## 1. Problem
A completely different sentence describing the same trouble.

## Acceptance Criteria:
- Given A, when B, then C.

## Out of scope
Different words, same section.
"""

# A section was dropped.
RUN_B_MISSING_SECTION = """\
---
id: feat-901
status: draft
appetite: xs
---

## Problem
Text.

## Acceptance Criteria
- Given X, when Y, then Z.
"""

# An extra section appeared + a frontmatter key was added.
RUN_B_EXTRA = """\
---
id: feat-901
status: draft
appetite: xs
confidence: low
---

## Problem
Text.

## Acceptance Criteria
- ac

## Out of Scope
x

## Risks
new section
"""

# Same sections, reordered.
RUN_B_REORDERED = """\
---
id: feat-901
status: draft
appetite: xs
---

## Acceptance Criteria
- ac

## Problem
Text.

## Out of Scope
x
"""


# ── extract_structure ───────────────────────────────────────────────────── #


class TestExtractStructure:
    def test_frontmatter_keys(self) -> None:
        s = extract_structure(RUN_A)
        assert s.frontmatter_keys == {"id", "status", "appetite"}

    def test_sections_normalized_and_ordered(self) -> None:
        s = extract_structure(RUN_A)
        assert s.sections == ("problem", "acceptance criteria", "out of scope")

    def test_numbering_and_trailing_punctuation_stripped(self) -> None:
        s = extract_structure(RUN_B_CONSISTENT)
        # "## 1. Problem" → "problem"; "## Acceptance Criteria:" → "acceptance criteria"
        assert s.sections == ("problem", "acceptance criteria", "out of scope")

    def test_no_frontmatter_yields_empty_keys(self) -> None:
        s = extract_structure("## Only\nbody, no frontmatter\n")
        assert s.frontmatter_keys == frozenset()
        assert s.sections == ("only",)

    def test_indented_keys_are_not_top_level(self) -> None:
        text = "---\nid: x\nnested:\n  child: y\n---\n## H\n"
        s = extract_structure(text)
        assert s.frontmatter_keys == {"id", "nested"}
        assert "child" not in s.frontmatter_keys

    def test_title_feature_name_tail_is_stripped(self) -> None:
        # Two runs title the same doc with different free-form feature names;
        # only the stem before "— FEAT-NNN:" is structural.
        a = extract_structure("## Technical Breakdown — FEAT-902: Auto-transition watcher\n")
        b = extract_structure("## Technical Breakdown — FEAT-902: Add `meridian watch`\n")
        assert a.sections == ("technical breakdown",)
        assert a.sections == b.sections

    def test_non_title_hyphenated_heading_is_preserved(self) -> None:
        # A real section heading with a hyphen but no feat-id tail is untouched.
        s = extract_structure("## Cross-feature connections\n")
        assert s.sections == ("cross-feature connections",)


# ── compare_texts ────────────────────────────────────────────────────────── #


class TestCompareTexts:
    def test_identical_structure_is_consistent(self) -> None:
        report = compare_texts(RUN_A, RUN_B_CONSISTENT)
        assert report.consistent, report.render()

    def test_missing_section_flagged(self) -> None:
        report = compare_texts(RUN_A, RUN_B_MISSING_SECTION)
        assert not report.consistent
        assert "out of scope" in report.missing_sections
        assert report.extra_sections == []

    def test_extra_section_and_frontmatter_key_flagged(self) -> None:
        report = compare_texts(RUN_A, RUN_B_EXTRA)
        assert not report.consistent
        assert "risks" in report.extra_sections
        assert "confidence" in report.frontmatter_only_in_b

    def test_reordering_flagged_when_set_matches(self) -> None:
        report = compare_texts(RUN_A, RUN_B_REORDERED)
        assert not report.consistent
        assert report.order_changed
        # Same set of sections, so no missing/extra.
        assert report.missing_sections == []
        assert report.extra_sections == []

    def test_self_comparison_is_consistent(self) -> None:
        report = compare_texts(RUN_A, RUN_A)
        assert report.consistent
        assert not report.order_changed

    def test_render_mentions_labels(self) -> None:
        report = compare_texts(RUN_A, RUN_B_MISSING_SECTION)
        out = report.render("spec#1", "spec#2")
        assert "spec#1" in out and "spec#2" in out
