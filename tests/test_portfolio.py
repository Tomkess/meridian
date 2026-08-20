"""Ranking and gathering for the portfolio view (FEAT-026).

The ordering rules are tested as pure functions over `Feature` values — no
files, no clock — because the ordering is the thing most likely to be changed
by accident and the hardest to notice when it is.

The gathering tests build throwaway projects under `tmp_path`. Nothing here
writes to the project registry: `ProjectEntry` values are constructed directly,
and `tests/conftest.py` already points `MERIDIAN_HOME` at a temp directory for
the whole session, so even an accidental global write cannot reach
`~/.meridian/projects.toml`.
"""
from __future__ import annotations

import os
import time
from datetime import date, timedelta
from pathlib import Path

import pytest

from meridian import portfolio
from meridian.portfolio import (
    TIER_BLOCKED,
    TIER_DRAFT,
    TIER_FINISHING,
    TIER_IDEA,
    TIER_STALLED,
    Feature,
    capacity_of,
    feature_from_spec,
    gather,
    portfolio_capacity,
    rank,
    reason,
    tier,
)
from meridian.registry import ProjectEntry

NOW = 1_800_000_000.0  # fixed clock so mtime-derived ages are exact
TODAY = date(2026, 8, 20)


# --------------------------------------------------------------------------- #
# builders
# --------------------------------------------------------------------------- #

def feat(feat_id: str = "FEAT-001", **kwargs) -> Feature:
    fields: dict = {
        "project": "alpha",
        "feat_id": feat_id,
        "name": f"Feature {feat_id}",
        "status": "in-progress",
    }
    fields.update(kwargs)
    return Feature(**fields)


def make_project(
    root: Path,
    slug: str,
    features: list[dict] | None = None,
) -> ProjectEntry:
    """A Meridian repo on disk, with spec.md/tasks.md aged by `age_days`."""
    repo = root / slug
    specs = repo / "specs"
    specs.mkdir(parents=True, exist_ok=True)
    (repo / ".meridian.toml").write_text(
        f'[meridian]\nproject = "{slug}"\nspecs_path = "specs"\n'
    )

    for i, spec in enumerate(features or [], start=1):
        spec = dict(spec)
        age = spec.pop("age_days", 0)
        tasks = spec.pop("tasks", None)   # (checked, total)
        raw = spec.pop("raw", None)       # raw spec.md text, for malformed cases
        feat_dir = specs / f"FEAT-{i:03d}_demo"
        feat_dir.mkdir(parents=True, exist_ok=True)

        spec_file = feat_dir / "spec.md"
        if raw is not None:
            spec_file.write_text(raw)
        else:
            meta = {
                "id": f"feat-{i:03d}",
                "name": spec.pop("name", f"Demo {i}"),
                "status": spec.pop("status", "idea"),
                **spec,
            }
            lines = "\n".join(f"{k}: {v}" for k, v in meta.items() if v is not None)
            spec_file.write_text(f"---\n{lines}\n---\nBody.\n")

        touched = [spec_file]
        if tasks:
            checked, total = tasks
            body = "\n".join(
                f"- [{'x' if n <= checked else ' '}] task {n}" for n in range(1, total + 1)
            )
            tasks_file = feat_dir / "tasks.md"
            tasks_file.write_text(body + "\n")
            touched.append(tasks_file)

        stamp = NOW - age * 86400
        for path in touched:
            os.utime(path, (stamp, stamp))

    return ProjectEntry(slug=slug, path=repo, purpose="", exists=True)


# --------------------------------------------------------------------------- #
# tiers
# --------------------------------------------------------------------------- #

class TestTiers:
    def test_blocked_is_the_top_tier(self) -> None:
        assert tier(feat(status="blocked")) == TIER_BLOCKED

    def test_in_progress_with_checked_tasks_is_finishing(self) -> None:
        assert tier(feat(status="in-progress", tasks_checked=3, tasks_total=8)) == TIER_FINISHING

    def test_in_progress_with_no_progress_is_stalled(self) -> None:
        """Nothing checked off is not "nearly done" — it is work in name only."""
        assert tier(feat(status="in-progress", tasks_checked=0, tasks_total=8)) == TIER_STALLED
        assert tier(feat(status="in-progress")) == TIER_STALLED

    def test_draft_and_idea(self) -> None:
        assert tier(feat(status="draft")) == TIER_DRAFT
        assert tier(feat(status="idea")) == TIER_IDEA

    @pytest.mark.parametrize("status", ["done", "in-production", "abandoned"])
    def test_outcomes_never_rank(self, status: str) -> None:
        assert tier(feat(status=status)) is None


# --------------------------------------------------------------------------- #
# ordering
# --------------------------------------------------------------------------- #

class TestOrdering:
    def test_blocked_longest_first(self) -> None:
        short = feat("FEAT-001", status="blocked", blocked_days=3)
        long = feat("FEAT-002", status="blocked", blocked_days=31)
        assert [f.feat_id for f in rank([short, long])] == ["FEAT-002", "FEAT-001"]

    def test_blocked_without_a_date_sorts_after_known_ages(self) -> None:
        """A missing blocked_at is a data gap, not an urgent one."""
        unknown = feat("FEAT-001", status="blocked")
        known = feat("FEAT-002", status="blocked", blocked_days=1)
        assert [f.feat_id for f in rank([unknown, known])] == ["FEAT-002", "FEAT-001"]

    def test_blocked_outranks_everything_else(self) -> None:
        blocked = feat("FEAT-009", status="blocked", blocked_days=0)
        nearly_done = feat("FEAT-001", status="in-progress", tasks_checked=11, tasks_total=12)
        assert rank([nearly_done, blocked])[0].feat_id == "FEAT-009"

    def test_in_progress_nearest_completion_first(self) -> None:
        near = feat("FEAT-001", status="in-progress", tasks_checked=11, tasks_total=12)
        far = feat("FEAT-002", status="in-progress", tasks_checked=2, tasks_total=20)
        assert [f.feat_id for f in rank([far, near])] == ["FEAT-001", "FEAT-002"]

    def test_equal_remaining_breaks_on_completeness(self) -> None:
        eleven_of_twelve = feat("FEAT-001", status="in-progress", tasks_checked=11, tasks_total=12)
        one_of_two = feat("FEAT-002", status="in-progress", tasks_checked=1, tasks_total=2)
        assert [f.feat_id for f in rank([one_of_two, eleven_of_twelve])] == [
            "FEAT-001", "FEAT-002",
        ]

    def test_finishing_outranks_stalled(self) -> None:
        stalled = feat("FEAT-002", status="in-progress", days_since_change=200)
        finishing = feat("FEAT-001", status="in-progress", tasks_checked=1, tasks_total=40)
        assert [f.feat_id for f in rank([stalled, finishing])] == ["FEAT-001", "FEAT-002"]

    def test_stalled_ordered_by_rot(self) -> None:
        fresh = feat("FEAT-001", status="in-progress", days_since_change=2)
        rotten = feat("FEAT-002", status="in-progress", days_since_change=90)
        assert [f.feat_id for f in rank([fresh, rotten])] == ["FEAT-002", "FEAT-001"]

    def test_draft_outranks_idea(self) -> None:
        idea = feat("FEAT-001", status="idea", days_since_change=0)
        draft = feat("FEAT-002", status="draft", days_since_change=300)
        assert [f.feat_id for f in rank([idea, draft])] == ["FEAT-002", "FEAT-001"]

    def test_inventory_is_freshest_first(self) -> None:
        """A spec shaped this week is likelier to be startable than a year-old one."""
        old = feat("FEAT-001", status="draft", days_since_change=300)
        new = feat("FEAT-002", status="draft", days_since_change=1)
        assert [f.feat_id for f in rank([old, new])] == ["FEAT-002", "FEAT-001"]

    def test_full_rule_end_to_end(self) -> None:
        features = [
            feat("FEAT-005", status="idea", days_since_change=4),
            feat("FEAT-004", status="draft", days_since_change=4),
            feat("FEAT-003", status="in-progress", days_since_change=60),
            feat("FEAT-002", status="in-progress", tasks_checked=9, tasks_total=10),
            feat("FEAT-001", status="blocked", blocked_days=31),
            feat("FEAT-099", status="done"),
        ]
        assert [f.feat_id for f in rank(features)] == [
            "FEAT-001", "FEAT-002", "FEAT-003", "FEAT-004", "FEAT-005",
        ]

    def test_ties_break_deterministically(self) -> None:
        """Same signals, different repos — the order must not depend on the disk."""
        a = feat("FEAT-001", project="zeta", status="idea", days_since_change=1)
        b = feat("FEAT-001", project="alpha", status="idea", days_since_change=1)
        assert [f.project for f in rank([a, b])] == ["alpha", "zeta"]

    def test_project_filter(self) -> None:
        a = feat("FEAT-001", project="alpha", status="blocked", blocked_days=1)
        b = feat("FEAT-002", project="beta", status="blocked", blocked_days=90)
        assert [f.feat_id for f in rank([a, b], project="alpha")] == ["FEAT-001"]


# --------------------------------------------------------------------------- #
# reasons — the row has to be able to argue its own position
# --------------------------------------------------------------------------- #

class TestReasons:
    def test_blocked_names_the_age_and_the_blocker(self) -> None:
        line = reason(feat(status="blocked", blocked_days=31, blocked_by="waiting on infra"))
        assert "blocked 31 days" in line
        assert "waiting on infra" in line

    def test_blocked_without_a_date_says_so(self) -> None:
        assert "no date recorded" in reason(feat(status="blocked"))

    def test_finishing_names_the_task_counts(self) -> None:
        line = reason(feat(status="in-progress", tasks_checked=11, tasks_total=12))
        assert line.startswith("11 of 12 tasks done")

    def test_stale_finishing_says_how_long(self) -> None:
        line = reason(feat(
            status="in-progress", tasks_checked=1, tasks_total=12, days_since_change=47,
        ))
        assert "nothing changed in 47 days" in line

    def test_stalled_names_the_rot(self) -> None:
        line = reason(feat(status="in-progress", tasks_total=8, tasks_checked=0,
                           days_since_change=47))
        assert "no tasks checked yet" in line
        assert "nothing changed in 47 days" in line

    def test_recent_change_reads_as_a_date_not_a_zero(self) -> None:
        assert "changed today" in reason(feat(status="draft", days_since_change=0))
        assert "changed yesterday" in reason(feat(status="idea", days_since_change=1))

    def test_every_ranked_row_has_a_reason(self) -> None:
        for status in portfolio.ACTIONABLE_STATUSES:
            assert reason(feat(status=status)).strip()


# --------------------------------------------------------------------------- #
# spec → Feature coercion
# --------------------------------------------------------------------------- #

class TestFeatureFromSpec:
    def test_blocked_days_from_blocked_at(self) -> None:
        spec = {"id": "feat-007", "status": "blocked",
                "blocked_at": (TODAY - timedelta(days=31)).isoformat()}
        assert feature_from_spec(spec, "alpha", today=TODAY).blocked_days == 31

    def test_unparseable_blocked_at_is_not_fatal(self) -> None:
        spec = {"id": "feat-007", "status": "blocked", "blocked_at": "last tuesday"}
        assert feature_from_spec(spec, "alpha", today=TODAY).blocked_days is None

    def test_garbage_frontmatter_still_produces_a_feature(self) -> None:
        """One hand-edited spec must not be able to take the portfolio down."""
        spec = {"id": ["feat-001"], "name": {"a": 1}, "status": 42,
                "depends_on": "feat-002", "appetite": 3}
        f = feature_from_spec(spec, "alpha", today=TODAY)
        assert f.feat_id == "['FEAT-001']"
        assert f.status == "42"
        assert f.depends_on == ("feat-002",)
        assert tier(f) is None  # an unknown status is not actionable

    def test_placeholder_goal_reads_as_unset(self) -> None:
        assert feature_from_spec({"goal": "~"}, "alpha", today=TODAY).goal is None


# --------------------------------------------------------------------------- #
# capacity
# --------------------------------------------------------------------------- #

class TestCapacity:
    def test_only_committed_active_features_count(self) -> None:
        cap = capacity_of([
            feat("FEAT-001", status="in-progress", appetite="l", cycle="2026-Q3"),
            feat("FEAT-002", status="draft", appetite="m", cycle="2026-Q3"),
            feat("FEAT-003", status="idea", appetite="l", cycle="2026-Q3"),  # not shaped
            feat("FEAT-004", status="done", appetite="l", cycle="2026-Q3"),  # already over
        ])
        assert cap.committed == 2
        assert cap.weight == pytest.approx(9.0)
        assert cap.large_bets == 1
        assert cap.cycles == ("2026-Q3",)

    def test_no_cycle_is_uncommitted_not_zero(self) -> None:
        cap = capacity_of([
            feat("FEAT-001", status="in-progress", appetite="m"),
            feat("FEAT-002", status="blocked", appetite="s"),
        ])
        assert cap.committed == 0
        assert cap.uncommitted == 2

    def test_committed_without_an_appetite_is_flagged(self) -> None:
        cap = capacity_of([feat("FEAT-001", status="draft", cycle="2026-Q3")])
        assert cap.committed == 1 and cap.unsized == 1 and cap.weight == 0.0

    def test_large_bets_are_counted_across_projects(self, tmp_path: Path) -> None:
        """Two large bets per repo is fine everywhere and ten in total."""
        views = []
        for slug in ("a", "b", "c", "d", "e"):
            entry = make_project(tmp_path, slug, [
                {"status": "in-progress", "appetite": "l", "cycle": "2026-Q3"},
                {"status": "draft", "appetite": "l", "cycle": "2026-Q3"},
            ])
            views.extend(gather([entry], today=TODAY, now=NOW).projects)

        total = portfolio_capacity(views)
        assert total.large_bets == 10
        assert total.overloaded is True
        assert all(v.capacity.large_bets <= portfolio.MAX_LARGE_BETS for v in views)


# --------------------------------------------------------------------------- #
# gathering
# --------------------------------------------------------------------------- #

class TestGather:
    def test_reads_counts_progress_and_staleness(self, tmp_path: Path) -> None:
        entry = make_project(tmp_path, "alpha", [
            {"status": "in-progress", "tasks": (11, 12), "age_days": 3},
            {"status": "idea", "age_days": 40},
        ])

        view = gather([entry], today=TODAY, now=NOW).projects[0]

        assert view.counts == {"in-progress": 1, "idea": 1}
        assert view.days_since_change == 3   # newest change in the project
        ranked = rank(view.features)
        assert ranked[0].tasks_checked == 11 and ranked[0].tasks_total == 12
        assert ranked[1].days_since_change == 40

    def test_needs_no_repo_checked_out(self, tmp_path: Path, monkeypatch) -> None:
        """The whole point: read other repos' specs from wherever you are."""
        entry = make_project(tmp_path, "alpha", [{"status": "draft"}])
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        assert rank(gather([entry], today=TODAY, now=NOW).features())

    def test_missing_path_is_reported_and_skipped(self, tmp_path: Path) -> None:
        entry = ProjectEntry(slug="gone", path=tmp_path / "gone", purpose="", exists=False)
        alive = make_project(tmp_path, "alpha", [{"status": "draft"}])

        port = gather([entry, alive], today=TODAY, now=NOW)

        assert [s.slug for s in port.skipped] == ["gone"]
        assert "not found" in port.skipped[0].why
        assert [v.slug for v in port.projects] == ["alpha"]
        # Reported, never removed — the entry is still the caller's to keep.
        assert entry.path.parent.exists()

    def test_repo_without_specs_dir_is_skipped(self, tmp_path: Path) -> None:
        bare = tmp_path / "bare"
        bare.mkdir()
        entry = ProjectEntry(slug="bare", path=bare, purpose="", exists=True)

        port = gather([entry], today=TODAY, now=NOW)

        assert port.skipped[0].why == "no specs/ directory"

    def test_malformed_spec_does_not_stop_the_ranking(self, tmp_path: Path) -> None:
        broken = make_project(tmp_path, "broken", [
            {"raw": "---\nstatus: [unclosed\nname: broken\n---\nbody\n"},
            {"status": "blocked", "blocked_at": "2026-07-01"},
        ])
        healthy = make_project(tmp_path, "healthy", [{"status": "draft"}])

        port = gather([broken, healthy], today=TODAY, now=NOW)
        ranked = rank(port.features())

        assert [v.slug for v in port.projects] == ["broken", "healthy"]
        assert [f.project for f in ranked] == ["broken", "healthy"]
        # The unreadable spec is counted, not silently dropped.
        assert port.projects[0].unreadable_specs == 1

    def test_one_bad_project_does_not_stop_the_rest(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        good = make_project(tmp_path, "good", [{"status": "draft"}])
        bad = make_project(tmp_path, "bad", [{"status": "draft"}])
        real = portfolio.all_specs

        def explode(specs_path: Path):
            if specs_path.parent.name == "bad":
                raise OSError("disk fell over")
            return real(specs_path)

        monkeypatch.setattr(portfolio, "all_specs", explode)
        port = gather([good, bad], today=TODAY, now=NOW)

        assert [v.slug for v in port.projects] == ["good"]
        assert port.skipped[0].slug == "bad" and "disk fell over" in port.skipped[0].why


# --------------------------------------------------------------------------- #
# cost
# --------------------------------------------------------------------------- #

class TestOnePass:
    def test_specs_are_parsed_once_per_project(self, tmp_path: Path, monkeypatch) -> None:
        """Counts, staleness, capacity and the ranking share one read.

        Four views over the same directory is how a ten-project dashboard turns
        into forty directory walks.
        """
        entries = [
            make_project(tmp_path, f"p{i}", [{"status": "draft"}, {"status": "idea"}])
            for i in range(4)
        ]
        calls: list[Path] = []
        real = portfolio.all_specs

        def counting(specs_path: Path):
            calls.append(specs_path)
            return real(specs_path)

        monkeypatch.setattr(portfolio, "all_specs", counting)

        port = gather(entries, today=TODAY, now=NOW)
        # Everything the two views need, derived from that one pass:
        rank(port.features())
        port.capacity()
        [v.counts for v in port.projects]
        [v.days_since_change for v in port.projects]

        assert len(calls) == len(entries) == len(set(calls))

    def test_ten_projects_of_sixty_features_is_not_a_pause(self, tmp_path: Path) -> None:
        entries = [
            make_project(tmp_path, f"p{i}", [
                {"status": "in-progress", "tasks": (n % 5, 5), "age_days": n}
                for n in range(60)
            ])
            for i in range(10)
        ]

        started = time.perf_counter()
        ordered = rank(gather(entries, today=TODAY, now=NOW).features())
        elapsed = time.perf_counter() - started

        assert len(ordered) == 600
        # Generous: the point is "no perceptible pause", not a microbenchmark.
        assert elapsed < 3.0, f"ranking 600 features took {elapsed:.2f}s"
