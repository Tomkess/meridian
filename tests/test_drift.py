"""Spec-vs-code drift detection (FEAT-017)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from meridian.drift import assess, branch_matches, changed_files, extract_criteria


class TestExtractCriteria:
    def test_parses_ac_lines(self) -> None:
        spec = """
- **AC1** — `save_spec()` writes atomically.
- **AC2** — The registry uses `tomli_w`.
"""
        criteria = extract_criteria(spec)
        assert [c.id for c in criteria] == ["AC1", "AC2"]

    def test_tolerates_dash_variants_and_suffixed_ids(self) -> None:
        spec = """
- **AC1** - `alpha_one` hyphen.
- **AC2**: `beta_two` colon.
- **AC5b** – `gamma_three` en dash.
"""
        criteria = extract_criteria(spec)
        assert [c.id for c in criteria] == ["AC1", "AC2", "AC5b"]
        assert all(c.refs for c in criteria)

    def test_wrapped_lines_are_joined(self) -> None:
        """Specs in this repo wrap constantly; a reference must not be lost."""
        spec = """
- **AC1** — Something long that wraps onto
  the next line and only then mentions `wrapped_target`.
"""
        criteria = extract_criteria(spec)
        assert "wrapped_target" in criteria[0].refs

    def test_prose_backticks_are_not_references(self) -> None:
        """`done` and `idea` appear in every spec and would match any diff."""
        spec = "- **AC1** — Status becomes `done` rather than `idea`.\n"
        criteria = extract_criteria(spec)
        assert criteria[0].refs == []
        assert criteria[0].checkable is False

    def test_recognises_code_shaped_tokens(self) -> None:
        spec = (
            "- **AC1** — `config.py`, `--dry-run`, `helper()`, `snake_case`, "
            "`module.attr` and `CamelCase` all count.\n"
        )
        refs = extract_criteria(spec)[0].refs
        for expected in ("config.py", "--dry-run", "helper()", "snake_case",
                         "module.attr", "CamelCase"):
            assert expected in refs


class TestBranchMatching:
    @pytest.mark.parametrize("branch", ["feat-017/drift", "FEAT-017/x", "wip/feat-017"])
    def test_matches_feature_branches(self, branch: str) -> None:
        assert branch_matches("FEAT-017", branch)

    @pytest.mark.parametrize("branch", ["main", "feat-013/other", "chore/close"])
    def test_rejects_unrelated_branches(self, branch: str) -> None:
        assert not branch_matches("FEAT-017", branch)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo with a main branch and a feature branch."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "seed.txt").write_text("seed\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=tmp_path, check=True)
    subprocess.run(["git", "checkout", "-qb", "feat-001/thing"], cwd=tmp_path, check=True)
    return tmp_path


def _spec(repo: Path, body: str) -> Path:
    d = repo / "specs" / "FEAT-001_thing"
    d.mkdir(parents=True, exist_ok=True)
    path = d / "spec.md"
    path.write_text(body)
    return path


class TestAssess:
    def test_flags_an_ac_nothing_implements(self, repo: Path) -> None:
        """The failure this exists to catch: planned, never built, never removed."""
        (repo / "implemented.py").write_text("def shipped_helper():\n    return 1\n")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "work"], cwd=repo, check=True)

        spec = _spec(repo, (
            "- **AC1** — `shipped_helper()` exists.\n"
            "- **AC2** — `never_built_helper()` also exists.\n"
        ))

        report = assess(spec, repo, base="main")

        assert [c.id for c in report.uncovered] == ["AC2"]

    def test_untracked_files_count_as_implementation(self, repo: Path) -> None:
        """A new feature's main module is usually untracked — git diff can't see it.

        This was the single largest source of false positives on the first live
        run: every brand-new module read as unimplemented.
        """
        (repo / "brand_new.py").write_text("def fresh_function():\n    return 2\n")

        spec = _spec(repo, "- **AC1** — `fresh_function()` exists.\n")
        report = assess(spec, repo, base="main")

        assert report.uncovered == []

    def test_file_reference_covered_by_the_file_changing(self, repo: Path) -> None:
        (repo / "touched.py").write_text("x = 1\n")

        spec = _spec(repo, "- **AC1** — `touched.py` is updated.\n")
        report = assess(spec, repo, base="main")

        assert report.uncovered == []

    def test_call_parens_are_stripped_before_matching(self, repo: Path) -> None:
        (repo / "mod.py").write_text("def some_target():\n    pass\n")

        spec = _spec(repo, "- **AC1** — `some_target()` is defined.\n")
        report = assess(spec, repo, base="main")

        assert report.uncovered == []

    def test_unjudgeable_criteria_are_separated(self, repo: Path) -> None:
        (repo / "mod.py").write_text("def real_thing():\n    pass\n")

        spec = _spec(repo, (
            "- **AC1** — `real_thing()` exists.\n"
            "- **AC2** — The output reads well and the wording is clear.\n"
        ))
        report = assess(spec, repo, base="main")

        assert [c.id for c in report.unjudgeable] == ["AC2"]
        assert [c.id for c in report.checkable] == ["AC1"]
        assert report.uncovered == []

    def test_reports_the_branch_it_is_on(self, repo: Path) -> None:
        spec = _spec(repo, "- **AC1** — `thing_one()` exists.\n")
        report = assess(spec, repo, base="main")

        assert report.branch == "feat-001/thing"
        assert report.on_feature_branch is True

    def test_unrelated_branch_is_flagged(self, repo: Path) -> None:
        subprocess.run(["git", "checkout", "-qb", "feat-999/other"], cwd=repo, check=True)
        spec = _spec(repo, "- **AC1** — `thing_one()` exists.\n")

        report = assess(spec, repo, base="main")

        assert report.on_feature_branch is False

    def test_changed_files_includes_uncommitted_work(self, repo: Path) -> None:
        (repo / "seed.txt").write_text("modified\n")
        (repo / "added.py").write_text("y = 2\n")

        files = changed_files(repo, "main")

        assert "seed.txt" in files
        assert "added.py" in files


# ── FEAT-018 hardening ──────────────────────────────────────────────────────


class TestFeatureIdResolution:
    """One validated resolver, replacing two globs that took candidates[0]."""

    def _specs(self, tmp_path: Path) -> Path:
        d = tmp_path / "specs"
        for name in ("FEAT-001_alpha", "FEAT-002_beta"):
            (d / name).mkdir(parents=True)
            (d / name / "spec.md").write_text("---\nid: x\n---\nbody\n")
        return d

    def test_resolves_a_valid_id(self, tmp_path: Path) -> None:
        from meridian.specs import find_spec

        specs = self._specs(tmp_path)
        assert find_spec(specs, "feat-001").parent.name == "FEAT-001_alpha"

    def test_glob_metacharacters_are_rejected(self, tmp_path: Path) -> None:
        """Reported repro: `close 'feat-*'` silently transitioned FEAT-002."""
        from meridian.specs import find_spec

        specs = self._specs(tmp_path)
        with pytest.raises(ValueError):
            find_spec(specs, "feat-*")

    def test_unknown_id_is_none_not_an_error(self, tmp_path: Path) -> None:
        from meridian.specs import find_spec

        assert find_spec(self._specs(tmp_path), "FEAT-404") is None

    def test_duplicate_directories_raise(self, tmp_path: Path) -> None:
        from meridian.specs import AmbiguousFeatureError, find_spec

        specs = self._specs(tmp_path)
        dupe = specs / "FEAT-001_duplicate"
        dupe.mkdir()
        (dupe / "spec.md").write_text("---\nid: x\n---\n")

        with pytest.raises(AmbiguousFeatureError):
            find_spec(specs, "FEAT-001")


class TestRegistryCellEscaping:
    def test_pipe_and_newline_do_not_break_the_table(self) -> None:
        from meridian.specs import _cell

        assert _cell("a | b") == r"a \| b"
        assert _cell("two\nlines") == "two lines"
        assert _cell(None) == ""


class TestBinaryRejection:
    def test_binary_file_is_refused(self, tmp_path: Path) -> None:
        from meridian.enrich import extract_text

        blob = tmp_path / "junk.bin"
        blob.write_bytes(bytes(range(256)) * 8)

        with pytest.raises(RuntimeError, match="does not look like text"):
            extract_text(str(blob))

    def test_real_text_still_works(self, tmp_path: Path) -> None:
        from meridian.enrich import extract_text

        doc = tmp_path / "notes.txt"
        doc.write_text("Ordinary research prose, with accents: café, naïve.\n")

        assert "café" in extract_text(str(doc))

    def test_empty_file_is_text(self, tmp_path: Path) -> None:
        from meridian.enrich import extract_text

        doc = tmp_path / "empty.txt"
        doc.write_text("")
        assert extract_text(str(doc)) == ""


class TestSunsettingAShippedFeature:
    def test_done_can_be_abandoned_directly(self) -> None:
        """Retiring a shipped feature should not walk backwards through in-progress."""
        from meridian.specs import VALID_TRANSITIONS

        assert "abandoned" in VALID_TRANSITIONS["done"]
        assert "abandoned" in VALID_TRANSITIONS["in-production"]


# ── history mode: drift after the branch is merged (FEAT-027) ─────────────── #


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _merge_feature_into_main(repo: Path, branch: str, message: str) -> None:
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "--no-ff", branch, "-m", message)


class TestHistoryMode:
    """Once merged there is no branch diff left — and that is exactly when
    `close --status done` runs drift, so the check used to be silent at the one
    moment it fires."""

    def test_merged_feature_is_still_assessed(self, repo: Path) -> None:
        (repo / "shipped.py").write_text("def shipped_helper():\n    return 1\n")
        spec = _spec(repo, "- **AC1** — `shipped_helper()` exists.\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "feat: build the thing (FEAT-001)")
        _merge_feature_into_main(repo, "feat-001/thing", "Merge FEAT-001: the thing")

        report = assess(spec, repo, base="main")

        assert report.mode == "history"
        assert report.commits, "the merge commit must be found"
        assert report.uncovered == [], "the AC's reference is in the merged diff"

    def test_merged_feature_still_flags_an_unimplemented_ac(self, repo: Path) -> None:
        """The whole point: a merged feature can still be caught drifting."""
        (repo / "shipped.py").write_text("def shipped_helper():\n    return 1\n")
        spec = _spec(
            repo,
            "- **AC1** — `shipped_helper()` exists.\n"
            "- **AC2** — `never_written()` also exists.\n",
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "feat: build the thing (FEAT-001)")
        _merge_feature_into_main(repo, "feat-001/thing", "Merge FEAT-001: the thing")

        report = assess(spec, repo, base="main")

        assert [c.id for c in report.uncovered] == ["AC2"]

    def test_squash_merge_is_found_by_the_message(self, repo: Path) -> None:
        """No merge commit exists — the feature ID in the subject is the signal."""
        _git(repo, "checkout", "-q", "main")
        (repo / "shipped.py").write_text("def shipped_helper():\n    return 1\n")
        spec = _spec(repo, "- **AC1** — `shipped_helper()` exists.\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "feat: squashed work for FEAT-001")

        report = assess(spec, repo, base="main")

        assert report.mode == "history"
        assert report.uncovered == []

    def test_nothing_anywhere_is_reported_as_nothing(self, repo: Path) -> None:
        """Not a clean bill of health — an empty search must not read as a pass."""
        _git(repo, "checkout", "-q", "main")
        spec = _spec(repo, "- **AC1** — `never_written()` exists.\n")

        report = assess(spec, repo, base="main")

        assert report.mode == "none"
        assert report.commits == []

    def test_a_sibling_spec_cannot_satisfy_an_ac(self, repo: Path) -> None:
        """The precision bug history mode introduced, and the reason
        SPEC_EXCLUDES is not just this feature's own directory.

        One commit that shapes several features drags every one of their specs
        into the diff. A sibling spec quoting `never_written()` would then let
        FEAT-001's AC match its own words through a neighbour's file — the
        self-matching failure the original exclusion existed to prevent,
        arriving through a different door.
        """
        _git(repo, "checkout", "-q", "main")
        spec = _spec(repo, "- **AC1** — `never_written()` exists.\n")
        sibling = repo / "specs" / "FEAT-002_other"
        sibling.mkdir(parents=True)
        (sibling / "spec.md").write_text(
            "- **AC1** — depends on `never_written()` from FEAT-001.\n"
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "docs: shape FEAT-001 and FEAT-002")

        report = assess(spec, repo, base="main")

        assert [c.id for c in report.uncovered] == ["AC1"], (
            "the reference exists only in a sibling spec, which is not evidence"
        )

    def test_branch_mode_still_wins_when_the_branch_has_the_work(
        self, repo: Path
    ) -> None:
        """History mode is a fallback, not a replacement."""
        (repo / "shipped.py").write_text("def shipped_helper():\n    return 1\n")
        spec = _spec(repo, "- **AC1** — `shipped_helper()` exists.\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "feat: build the thing")

        report = assess(spec, repo, base="main")

        assert report.mode == "branch"
        assert report.commits == []

    def test_spec_excludes_is_what_keeps_a_sibling_spec_out(self, repo: Path) -> None:
        """Pins the exclusion itself, not just its effect.

        The test above passes for the wrong reason if the exclusion regresses —
        an uncovered AC looks the same whether the sibling was excluded or the
        search found nothing. This compares the two exclusion sets on the same
        history, so only the widening can make it pass.
        """
        from meridian.drift import SPEC_EXCLUDES, history_diff

        _git(repo, "checkout", "-q", "main")
        _spec(repo, "- **AC1** — `never_written()` exists.\n")
        sibling = repo / "specs" / "FEAT-002_other"
        sibling.mkdir(parents=True)
        (sibling / "spec.md").write_text("mentions `never_written()` in passing\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "docs: shape FEAT-001 and FEAT-002")

        own_dir_only, _, _ = history_diff(
            repo, "FEAT-001", "main", ["specs/FEAT-001_thing"]
        )
        all_specs, _, _ = history_diff(repo, "FEAT-001", "main", list(SPEC_EXCLUDES))

        assert "never_written()" in own_dir_only, "precondition: the leak is real"
        assert "never_written()" not in all_specs
