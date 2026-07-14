#!/usr/bin/env python3
"""Skill-consistency check — Layer 3 regression harness.

A skill prompt is *consistent* if two independent runs produce the same
document **structure** (frontmatter keys + section headings), even when the
prose differs. Structural drift between runs means the prompt is ambiguous and
should be tightened.

This module exposes pure functions (`extract_structure`, `compare_structures`)
that are unit-tested in tests/test_skill_consistency.py, plus a CLI:

  # Compare two already-captured outputs:
  python scripts/skill_consistency.py --compare a.md b.md

  # Run a skill twice via the Claude Code CLI and compare (needs `claude`):
  python scripts/skill_consistency.py --skill spec --feat feat-901

Exit code is 0 when consistent, 1 when structural drift is detected — so it
drops straight into CI or a pre-commit hook.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# ── structure extraction ─────────────────────────────────────────────────── #

_FM_FENCE = re.compile(r"^---\s*$", re.MULTILINE)
_FM_KEY = re.compile(r"^([A-Za-z0-9_-]+):", re.MULTILINE)
_HEADING = re.compile(r"^(#{2,3})\s+(.+?)\s*$", re.MULTILINE)


def _normalize_heading(text: str) -> str:
    """Lower-case, collapse whitespace, and drop trailing punctuation.

    Wording is allowed to vary; we compare the semantic heading. Any inline
    numbering ("1. Overview") is stripped so re-ordered numbering doesn't read
    as a structural change on its own.
    """
    text = re.sub(r"\s+", " ", text).strip().lower()
    text = re.sub(r"^\d+[.)]\s*", "", text)  # leading "1. " / "2) "
    return text.rstrip(":.").strip()


def _frontmatter_keys(text: str) -> frozenset[str]:
    """Return the top-level frontmatter keys, or empty set if no frontmatter."""
    fences = list(_FM_FENCE.finditer(text))
    if len(fences) < 2 or fences[0].start() != 0:
        return frozenset()
    block = text[fences[0].end() : fences[1].start()]
    # Only top-level keys (no leading indentation).
    return frozenset(
        m.group(1)
        for line in block.splitlines()
        if (m := _FM_KEY.match(line))
    )


@dataclass(frozen=True)
class Structure:
    """The structural fingerprint of a skill output."""

    frontmatter_keys: frozenset[str]
    sections: tuple[str, ...]  # normalized ## / ### headings, in document order

    @property
    def section_set(self) -> frozenset[str]:
        return frozenset(self.sections)


def extract_structure(text: str) -> Structure:
    headings = tuple(
        _normalize_heading(m.group(2)) for m in _HEADING.finditer(text)
    )
    return Structure(
        frontmatter_keys=_frontmatter_keys(text),
        sections=headings,
    )


# ── comparison ───────────────────────────────────────────────────────────── #


@dataclass
class ConsistencyReport:
    missing_sections: list[str] = field(default_factory=list)  # in a, not in b
    extra_sections: list[str] = field(default_factory=list)  # in b, not in a
    frontmatter_only_in_a: list[str] = field(default_factory=list)
    frontmatter_only_in_b: list[str] = field(default_factory=list)
    order_changed: bool = False

    @property
    def consistent(self) -> bool:
        return not (
            self.missing_sections
            or self.extra_sections
            or self.frontmatter_only_in_a
            or self.frontmatter_only_in_b
            or self.order_changed
        )

    def render(self, label_a: str = "run A", label_b: str = "run B") -> str:
        if self.consistent:
            return f"✓ consistent — {label_a} and {label_b} share the same structure"
        lines = [f"✗ structural drift between {label_a} and {label_b}:"]
        if self.missing_sections:
            lines.append(f"  sections only in {label_a}: {self.missing_sections}")
        if self.extra_sections:
            lines.append(f"  sections only in {label_b}: {self.extra_sections}")
        if self.frontmatter_only_in_a:
            lines.append(f"  frontmatter keys only in {label_a}: {self.frontmatter_only_in_a}")
        if self.frontmatter_only_in_b:
            lines.append(f"  frontmatter keys only in {label_b}: {self.frontmatter_only_in_b}")
        if self.order_changed:
            lines.append("  section order differs (same set, different sequence)")
        return "\n".join(lines)


def compare_structures(a: Structure, b: Structure) -> ConsistencyReport:
    report = ConsistencyReport(
        missing_sections=sorted(a.section_set - b.section_set),
        extra_sections=sorted(b.section_set - a.section_set),
        frontmatter_only_in_a=sorted(a.frontmatter_keys - b.frontmatter_keys),
        frontmatter_only_in_b=sorted(b.frontmatter_keys - a.frontmatter_keys),
    )
    # Order only matters when both runs contain the same set of sections.
    if a.section_set == b.section_set and a.sections != b.sections:
        report.order_changed = True
    return report


def compare_texts(text_a: str, text_b: str) -> ConsistencyReport:
    return compare_structures(extract_structure(text_a), extract_structure(text_b))


# ── CLI ──────────────────────────────────────────────────────────────────── #

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PROJECT = REPO_ROOT / "tests" / "golden" / "project"


def _run_skill_headless(skill: str, feat: str) -> str:
    """Invoke a skill twice-over via the Claude Code CLI; return stdout."""
    cmd = [
        "claude",
        "-p",
        f"/{skill} {feat}",
        "--output-format",
        "text",
        "--dangerously-skip-permissions",
        "--add-dir",
        str(FIXTURE_PROJECT),
    ]
    result = subprocess.run(
        cmd, cwd=FIXTURE_PROJECT, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude run failed:\n{result.stderr}")
    return result.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--compare",
        nargs=2,
        metavar=("A", "B"),
        help="compare two existing output files",
    )
    group.add_argument("--skill", help="skill to run twice (needs --feat)")
    parser.add_argument("--feat", help="fixture feature id for --skill")
    args = parser.parse_args(argv)

    if args.compare:
        a_path, b_path = (Path(p) for p in args.compare)
        report = compare_texts(a_path.read_text(), b_path.read_text())
        label_a, label_b = a_path.name, b_path.name
    else:
        if not args.feat:
            parser.error("--skill requires --feat")
        run_a = _run_skill_headless(args.skill, args.feat)
        run_b = _run_skill_headless(args.skill, args.feat)
        # Persist the two runs so a failure is inspectable.
        tmp = Path(tempfile.mkdtemp(prefix="skill-consistency-"))
        (tmp / "run_a.md").write_text(run_a)
        (tmp / "run_b.md").write_text(run_b)
        report = compare_texts(run_a, run_b)
        label_a, label_b = f"{args.skill}#1", f"{args.skill}#2"
        print(f"(runs saved to {tmp})")

    print(report.render(label_a, label_b))
    return 0 if report.consistent else 1


if __name__ == "__main__":
    sys.exit(main())
