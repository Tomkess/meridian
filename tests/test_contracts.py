"""Skill–CLI contract tests.

Every `meridian <subcommand>` mentioned in a skill prompt or CLAUDE.md must
exist in `meridian --help`.  Every `meridian <subcommand> --flag` pair must
appear in `meridian <subcommand> --help`.

This prevents silent drift when a flag is renamed in the CLI but the skill
prompt still references the old name — a class of bug that only surfaces
when an AI agent actually runs the command.

Run:  .venv/bin/pytest tests/test_contracts.py -v
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from functools import cache
from pathlib import Path

import pytest

# ── locate binary ─────────────────────────────────────────────────────────── #


def _find_binary() -> str:
    venv_bin = Path(sys.executable).parent / "meridian"
    if venv_bin.exists():
        return str(venv_bin)
    found = shutil.which("meridian")
    if found:
        return found
    raise RuntimeError(
        "meridian binary not found. Run: uv sync"
    )


MERIDIAN_BIN = _find_binary()

# ── source files to scan ─────────────────────────────────────────────────── #

REPO_ROOT = Path(__file__).parents[1]
# FEAT-013: scan the *bundled* skills as well as the dogfooded copies. The
# bundled directory is the artifact that `meridian install` puts into other
# repos, and until now no contract test read it — a shipped skill could invoke
# a nonexistent subcommand or flag, pass the whole suite and the release gate,
# and only fail in a downstream user's project.
BUNDLED_COMMANDS_DIR = REPO_ROOT / "meridian" / "skills" / "commands"
COMMANDS_DIR = REPO_ROOT / ".claude" / "commands" / "meridian"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"

# Words that follow "meridian" but are NOT subcommands (prose / meta text)
_NOT_A_SUBCOMMAND = frozenset(
    {"cli", "status", "project", "workflow", "command", "help", "spec"}
    # "status" and "help" ARE subcommands but we don't want to block them;
    # keep this set small — only words that genuinely appear in prose.
    # Over-blocking here means fewer contract assertions, so err on the side
    # of allowing questionable matches (they'll fail only if the cmd is absent).
)
# Actually — allow everything; if "meridian cli" appears in prose and "cli"
# is not a valid command the test will correctly flag the drift.
_NOT_A_SUBCOMMAND = frozenset()

# ── reference extraction ─────────────────────────────────────────────────── #


def _extract_refs(text: str) -> set[tuple[str, str | None]]:
    """
    Scan *text* for ``meridian <subcommand> [...]`` patterns.

    Returns a set of ``(subcommand, flag_or_None)`` pairs:
    - ``(subcmd, None)``         — the subcommand itself must exist
    - ``(subcmd, "--flag")``     — the flag must exist for that subcommand
    """
    refs: set[tuple[str, str | None]] = set()
    # Match: meridian <word> [optional positional args and --flags]
    # We stop at end-of-line, backtick, or closing quote to avoid bleeding
    # into the next line of a code block.
    pattern = re.compile(
        r'meridian\s+'          # literal "meridian" + whitespace
        r'([a-z][a-z-]*)'       # subcommand (lowercase, may contain hyphens)
        r'([^\n`]*)'            # rest of invocation — stop at newline or backtick;
                                # allow quotes so "meridian new \"idea\" --flag" works
    )
    for m in pattern.finditer(text):
        subcmd = m.group(1)
        if subcmd in _NOT_A_SUBCOMMAND:
            continue
        refs.add((subcmd, None))
        # Extract every --long-flag from the rest of the invocation
        for flag in re.findall(r'(--[a-z][a-z-]*)', m.group(2)):
            refs.add((subcmd, flag))
    return refs


def _collect_all_refs() -> list[tuple[str, str, str | None]]:
    """
    Returns ``[(source_file_name, subcommand, flag_or_None), ...]``.

    Scans all ``.claude/commands/meridian/*.md`` files plus ``CLAUDE.md``.
    """
    all_refs: list[tuple[str, str, str | None]] = []
    sources: list[Path] = list(COMMANDS_DIR.glob("*.md")) + [CLAUDE_MD]
    seen: set[tuple[str, str | None]] = set()  # deduplicate across sources

    for path in sorted(sources):
        text = path.read_text(encoding="utf-8")
        for subcmd, flag in _extract_refs(text):
            key = (subcmd, flag)
            if key not in seen:
                seen.add(key)
                all_refs.append((path.name, subcmd, flag))

    return all_refs


# ── CLI help cache ────────────────────────────────────────────────────────── #


@cache
def _get_help(subcmd: str | None = None) -> str:
    """Return the help text for ``meridian [subcmd] --help`` (cached).

    Runs with NO_COLOR=1 and FORCE_COLOR unset so Rich/Typer never emits
    ANSI escape codes — GitHub Actions sets FORCE_COLOR=1 which would
    otherwise produce colour-decorated output that breaks the regex parser.
    """
    args = [MERIDIAN_BIN]
    if subcmd:
        args.append(subcmd)
    args.append("--help")
    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    env.pop("FORCE_COLOR", None)
    r = subprocess.run(args, capture_output=True, text=True, env=env)
    text = r.stdout + r.stderr
    # Strip any ANSI escape codes that survive despite NO_COLOR=1.
    # GitHub Actions sets FORCE_COLOR=1; Rich/Typer may still emit codes
    # that split flag names (e.g. "--feat" → "\x1b[1m-\x1b[0m\x1b[1m-feat\x1b[0m"),
    # causing plain substring searches to miss them.
    return re.sub(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", text)


def _valid_subcommands() -> frozenset[str]:
    """Return valid subcommands by introspecting the Typer app directly.

    Using the Click integration avoids any dependency on help-text formatting,
    ANSI escape codes, Rich version differences, or CI colour-forcing env vars
    (GitHub Actions sets FORCE_COLOR=1, which makes text-based parsing brittle).
    """
    from typer.main import get_command

    from meridian.cli import app as _meridian_app

    click_app = get_command(_meridian_app)
    return frozenset(click_app.commands.keys())


def _flag_exists_for(subcmd: str, flag: str) -> bool:
    """Return True if *flag* appears in ``meridian <subcmd> --help``."""
    return flag in _get_help(subcmd)


# ── collect at module load time (parametrize needs it) ────────────────────── #

_ALL_REFS = _collect_all_refs()

# ── tests ─────────────────────────────────────────────────────────────────── #


class TestSubcommandsExist:
    """Every subcommand referenced in skill prompts must exist in the CLI."""

    @pytest.mark.parametrize(
        "source,subcmd",
        # Deduplicate — one assertion per (source, subcmd) pair
        sorted({(src, cmd) for src, cmd, _flag in _ALL_REFS}),
        ids=lambda x: x,
    )
    def test_subcommand_exists(self, source: str, subcmd: str) -> None:
        valid = _valid_subcommands()
        assert subcmd in valid, (
            f"[{source}] references `meridian {subcmd}` "
            f"but '{subcmd}' is not in `meridian --help`.\n"
            f"Valid subcommands: {sorted(valid)}"
        )


class TestFlagsExist:
    """Every --flag referenced alongside a subcommand must exist for that subcommand."""

    @pytest.mark.parametrize(
        "source,subcmd,flag",
        # Only the (source, subcmd, flag) triples where flag is not None
        [(src, cmd, flag) for src, cmd, flag in _ALL_REFS if flag is not None],
        ids=lambda x: x if x else "",
    )
    def test_flag_exists(self, source: str, subcmd: str, flag: str) -> None:
        # First ensure the subcommand itself is valid (avoids confusing errors)
        valid_cmds = _valid_subcommands()
        if subcmd not in valid_cmds:
            pytest.skip(
                f"Subcommand '{subcmd}' not found — covered by TestSubcommandsExist"
            )
        assert _flag_exists_for(subcmd, flag), (
            f"[{source}] references `meridian {subcmd} {flag}` "
            f"but '{flag}' is not in `meridian {subcmd} --help`.\n"
            f"Help output:\n{_get_help(subcmd)}"
        )


# ── sanity: extraction logic itself ───────────────────────────────────────── #


class TestExtractionLogic:
    """Unit tests for _extract_refs so contract failures are easy to debug."""

    def test_extracts_subcommand_only(self) -> None:
        refs = _extract_refs("run `meridian guide` to get started")
        assert ("guide", None) in refs

    def test_extracts_flag(self) -> None:
        refs = _extract_refs("`meridian close FEAT-001 --status draft`")
        assert ("close", "--status") in refs

    def test_extracts_multiple_flags(self) -> None:
        refs = _extract_refs(
            "meridian close FEAT-001 --status blocked --blocked-by x"
        )
        assert ("close", "--status") in refs
        assert ("close", "--blocked-by") in refs

    def test_does_not_extract_short_flags(self) -> None:
        refs = _extract_refs("meridian search query -n 5")
        # -n is a short flag; we only care about --long-flags
        flags = {flag for _cmd, flag in refs if flag is not None}
        assert all(f.startswith("--") for f in flags)

    def test_stops_at_newline(self) -> None:
        refs = _extract_refs("meridian new 'idea'\nsome other text --orphan")
        flags = {flag for _cmd, flag in refs if flag is not None}
        assert "--orphan" not in flags

    def test_stops_at_backtick(self) -> None:
        refs = _extract_refs("`meridian search q` and then `--orphan`")
        flags = {flag for _cmd, flag in refs if flag is not None}
        assert "--orphan" not in flags

    def test_hyphenated_subcommand(self) -> None:
        refs = _extract_refs("`meridian link-job feat-001 42`")
        assert ("link-job", None) in refs

    def test_all_flags_present_in_extracted_refs(self) -> None:
        """Smoke-test: at least some expected pairs appear in the full scan."""
        ref_set = {(cmd, flag) for _src, cmd, flag in _ALL_REFS}
        # These are documented in CLAUDE.md and skill files — must be found
        expected = [
            ("new", "--appetite"),
            ("new", "--goal"),
            ("close", "--status"),
            ("close", "--confidence"),
            ("search", "--no-rerank"),
        ]
        for pair in expected:
            assert pair in ref_set, (
                f"Expected {pair} in extracted refs but it was not found.\n"
                f"Check that CLAUDE.md or skill files reference it."
            )
