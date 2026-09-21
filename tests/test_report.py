"""FEAT-028: the HTML report's payload, graph and escaping.

The tests that matter here are the ones that catch a *silent* regression:
the payload contract drifting away from `status --json`, an edge disappearing
because an ID case mismatched, or a feature name breaking out of the script
block. The rendered page's appearance is deliberately untested — a DOM
snapshot would break on every CSS tweak and prove nothing.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from meridian import report
from meridian.cli import app

# ── fixtures ──────────────────────────────────────────────────────────────── #

#: The twelve keys `status --json` has always emitted. Asserted as an exact set,
#: not a subset: an *extra* key is drift too, and the whole point of AC2 is that
#: no one can add one to the report without the CLI seeing it.
PAYLOAD_KEYS = {
    "id", "name", "status", "appetite", "confidence", "cycle", "goal",
    "updated", "depends_on", "enables", "blocked_by", "tasks",
}


def write_spec(
    specs_dir: Path,
    feat_id: str,
    *,
    name: str = "A feature",
    status: str = "draft",
    slug: str = "thing",
    depends_on: list[str] | None = None,
    enables: list[str] | None = None,
    goal: str | None = None,
    blocked_by: str | None = None,
    tasks: str | None = None,
) -> Path:
    """Write a spec with real frontmatter into its own FEAT-NNN_slug directory."""
    feat_dir = specs_dir / f"{feat_id.upper()}_{slug}"
    feat_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"id: {feat_id.lower()}",
        f"name: {name}",
        f"status: {status}",
        "appetite: m",
        "confidence: medium",
        "cycle: null",
        f"goal: {goal if goal is not None else 'null'}",
        "updated: '2026-09-21'",
        f"depends_on: {depends_on or []}",
        f"enables: {enables or []}",
        f"blocked_by: {blocked_by if blocked_by is not None else 'null'}",
        "---",
        "",
        "Body.",
    ]
    (feat_dir / "spec.md").write_text("\n".join(lines) + "\n")
    if tasks is not None:
        (feat_dir / "tasks.md").write_text(tasks)
    return feat_dir


def features_of(*specs: dict) -> list[dict]:
    """Minimal feature dicts for the pure graph functions."""
    return list(specs)


def feat(fid: str, depends_on=None, enables=None) -> dict:
    return {"id": fid, "depends_on": depends_on or [], "enables": enables or []}


# ── build_payload: the shared contract ────────────────────────────────────── #

class TestBuildPayload:
    def test_emits_exactly_the_documented_keys(self, mock_cfg, specs_dir):
        write_spec(specs_dir, "FEAT-001")
        payload = report.build_payload(mock_cfg)

        assert payload["project"] == "test-project"
        assert len(payload["features"]) == 1
        assert set(payload["features"][0]) == PAYLOAD_KEYS

    def test_id_is_upper_cased_from_lowercase_frontmatter(self, mock_cfg, specs_dir):
        write_spec(specs_dir, "FEAT-001")
        assert report.build_payload(mock_cfg)["features"][0]["id"] == "FEAT-001"

    def test_goal_tilde_is_not_normalised(self, mock_cfg, specs_dir):
        """`status --json` emits the raw value; normalising it here is a silent
        behaviour change for every skill that reads the CLI."""
        write_spec(specs_dir, "FEAT-001", goal="'~'")
        assert report.build_payload(mock_cfg)["features"][0]["goal"] == "~"

    def test_stub_tasks_file_yields_none_not_zero(self, mock_cfg, specs_dir):
        """A stub tasks.md with no checkboxes is "no task list", which is a
        different fact from "0 of N done" and must render differently."""
        write_spec(specs_dir, "FEAT-001", tasks="## Tasks\n\nNothing yet.\n")
        assert report.build_payload(mock_cfg)["features"][0]["tasks"] is None

    def test_task_progress_is_counted(self, mock_cfg, specs_dir):
        write_spec(
            specs_dir, "FEAT-001",
            tasks="- [x] one\n- [ ] two\n- [ ] three\n",
        )
        assert report.build_payload(mock_cfg)["features"][0]["tasks"] == {
            "checked": 1, "total": 3,
        }

    def test_accepts_a_prebuilt_specs_list(self, mock_cfg, specs_dir):
        """The report reads the specs dir once and shares the list, so passing
        it in must produce the same payload as reading it again."""
        from meridian.specs import all_specs

        write_spec(specs_dir, "FEAT-001")
        assert report.build_payload(mock_cfg) == report.build_payload(
            mock_cfg, specs=all_specs(specs_dir)
        )


class TestStatusJsonParity:
    """AC2. The test that fails the day someone re-inlines the dict in cli.py."""

    def test_status_json_equals_build_payload(self, project_dir, specs_dir, monkeypatch):
        """Runs the real CLI against a real on-disk project, so the comparison
        is against the config the command itself loads."""
        from meridian.config import load_config

        write_spec(specs_dir, "FEAT-001", depends_on=["FEAT-002"], tasks="- [x] a\n")
        write_spec(specs_dir, "FEAT-002", slug="other", status="done", goal="'~'")
        monkeypatch.chdir(project_dir)

        result = CliRunner().invoke(app, ["status", "--json"])
        assert result.exit_code == 0, result.output

        # `_emit_json` serialises with `default=str`, so the comparison is
        # against the payload round-tripped the same way — a `date` object and
        # its ISO string are the same fact, and asserting on the raw dict would
        # fail on a difference that does not exist in the CLI's output.
        expected = json.loads(
            json.dumps(report.build_payload(load_config(project_dir)), default=str)
        )
        assert json.loads(result.stdout) == expected


# ── dependency_edges ──────────────────────────────────────────────────────── #

class TestDependencyEdges:
    def test_resolved_edge(self):
        edges = report.dependency_edges(
            features_of(feat("FEAT-001", depends_on=["FEAT-002"]), feat("FEAT-002"))
        )
        assert edges == [
            {"from": "FEAT-001", "to": "FEAT-002", "kind": "depends_on",
             "dangling": False}
        ]

    def test_unknown_target_is_kept_and_flagged_dangling(self):
        """AC3. Dropping it would hide the typo in the only view that shows it."""
        edges = report.dependency_edges(
            features_of(feat("FEAT-001", depends_on=["FEAT-999"]))
        )
        assert len(edges) == 1
        assert edges[0]["to"] == "FEAT-999"
        assert edges[0]["dangling"] is True

    def test_lowercase_frontmatter_id_matches_upper_case_payload_id(self):
        """Frontmatter carries `feat-002`; the payload carries `FEAT-002`.
        Skip the normalisation and every edge reads as dangling."""
        edges = report.dependency_edges(
            features_of(feat("FEAT-001", depends_on=["feat-002"]), feat("FEAT-002"))
        )
        assert edges[0]["dangling"] is False
        assert edges[0]["to"] == "FEAT-002"

    def test_reciprocal_declaration_yields_one_edge(self):
        edges = report.dependency_edges(
            features_of(
                feat("FEAT-001", depends_on=["FEAT-002"]),
                feat("FEAT-002", enables=["FEAT-001"]),
            )
        )
        assert len(edges) == 1
        assert edges[0]["kind"] == "depends_on"

    def test_enables_only_is_stored_in_the_dependent_direction(self):
        edges = report.dependency_edges(
            features_of(feat("FEAT-001"), feat("FEAT-002", enables=["FEAT-001"]))
        )
        assert edges == [
            {"from": "FEAT-001", "to": "FEAT-002", "kind": "enables",
             "dangling": False}
        ]

    def test_self_dependency_is_dropped(self):
        assert report.dependency_edges(
            features_of(feat("FEAT-001", depends_on=["FEAT-001"]))
        ) == []

    def test_no_relationships_yields_no_edges(self):
        assert report.dependency_edges(features_of(feat("FEAT-001"))) == []


# ── rank_nodes ────────────────────────────────────────────────────────────── #

class TestRankNodes:
    def _rank(self, features):
        return report.rank_nodes(features, report.dependency_edges(features))

    def test_linear_chain(self):
        ranks = self._rank(features_of(
            feat("FEAT-001", depends_on=["FEAT-002"]),
            feat("FEAT-002", depends_on=["FEAT-003"]),
            feat("FEAT-003"),
        ))
        assert ranks["FEAT-003"] == 0
        assert ranks["FEAT-002"] == 1
        assert ranks["FEAT-001"] == 2

    def test_root_with_no_dependencies_is_rank_zero(self):
        assert self._rank(features_of(feat("FEAT-001"))) == {"FEAT-001": 0}

    def test_cycle_terminates_with_finite_ranks(self):
        """A dependency cycle is a bug in the specs. Discovering it by blowing
        the renderer's stack is the wrong way to find out."""
        ranks = self._rank(features_of(
            feat("FEAT-001", depends_on=["FEAT-002"]),
            feat("FEAT-002", depends_on=["FEAT-001"]),
        ))
        assert set(ranks) == {"FEAT-001", "FEAT-002"}
        assert all(isinstance(v, int) and v >= 0 for v in ranks.values())

    def test_dangling_target_does_not_affect_rank(self):
        ranks = self._rank(features_of(feat("FEAT-001", depends_on=["FEAT-999"])))
        assert ranks == {"FEAT-001": 0}

    def test_diamond_takes_the_longest_path(self):
        ranks = self._rank(features_of(
            feat("FEAT-001", depends_on=["FEAT-002", "FEAT-003"]),
            feat("FEAT-002", depends_on=["FEAT-004"]),
            feat("FEAT-003"),
            feat("FEAT-004"),
        ))
        assert ranks["FEAT-001"] == 2  # via FEAT-002 -> FEAT-004, not via FEAT-003


# ── build_report_payload ──────────────────────────────────────────────────── #

class TestBuildReportPayload:
    def test_features_are_identical_to_the_cli_contract(self, mock_cfg, specs_dir):
        """The superset must never mutate the list AC2 pins."""
        write_spec(specs_dir, "FEAT-001", depends_on=["FEAT-002"])
        write_spec(specs_dir, "FEAT-002", slug="other")
        assert (
            report.build_report_payload(mock_cfg)["features"]
            == report.build_payload(mock_cfg)["features"]
        )

    def test_columns_match_status_columns(self, mock_cfg, specs_dir):
        payload = report.build_report_payload(mock_cfg)
        assert [(c["status"], c["label"]) for c in payload["columns"]] == list(
            report.STATUS_COLUMNS
        )

    def test_goal_key_collapses_ungoaled_markers(self, mock_cfg, specs_dir):
        write_spec(specs_dir, "FEAT-001", goal="'~'")
        write_spec(specs_dir, "FEAT-002", slug="b", goal="goal-01")
        signals = report.build_report_payload(mock_cfg)["signals"]
        assert signals["FEAT-001"]["goal_key"] is None
        assert signals["FEAT-002"]["goal_key"] == "goal-01"

    def test_signals_carry_staleness_and_rank(self, mock_cfg, specs_dir):
        write_spec(specs_dir, "FEAT-001", depends_on=["FEAT-002"])
        write_spec(specs_dir, "FEAT-002", slug="other")
        signals = report.build_report_payload(mock_cfg)["signals"]
        assert signals["FEAT-001"]["rank"] == 1
        assert signals["FEAT-002"]["rank"] == 0
        assert signals["FEAT-001"]["days_since_change"] == 0
        assert signals["FEAT-001"]["stale"] is False

    def test_stale_flag_trips_at_the_shared_threshold(self, mock_cfg, specs_dir):
        from meridian import portfolio

        write_spec(specs_dir, "FEAT-001")
        future = report.time.time() + (portfolio.STALE_DAYS + 1) * 86400
        signals = report.build_report_payload(mock_cfg, now=future)["signals"]
        assert signals["FEAT-001"]["stale"] is True

    def test_goals_are_read_from_the_goals_directory(self, mock_cfg, specs_dir):
        from tests.conftest import make_goal

        make_goal(specs_dir, "goal-01", "Be the memory layer")
        payload = report.build_report_payload(mock_cfg)
        assert payload["goals"] == [
            {"id": "goal-01", "name": "Be the memory layer", "status": "active"}
        ]

    def test_staleness_note_travels_with_the_number(self, mock_cfg, specs_dir):
        from meridian import portfolio

        payload = report.build_report_payload(mock_cfg)
        assert payload["stale_days"] == portfolio.STALE_DAYS
        assert payload["staleness_note"] == portfolio.STALENESS_NOTE

    def test_unreadable_spec_is_counted_not_hidden(self, mock_cfg, specs_dir):
        write_spec(specs_dir, "FEAT-001")
        broken = specs_dir / "FEAT-002_broken"
        broken.mkdir()
        (broken / "spec.md").write_text("---\nid: [unclosed\n---\nbody\n")
        payload = report.build_report_payload(mock_cfg)
        assert len(payload["features"]) == 1
        assert payload["unreadable_specs"] == 1

    def test_empty_project_still_produces_a_payload(self, mock_cfg, specs_dir):
        payload = report.build_report_payload(mock_cfg)
        assert payload["features"] == []
        assert payload["edges"] == []
        assert payload["signals"] == {}


# ── read_goals ────────────────────────────────────────────────────────────── #

class TestReadGoals:
    def test_unparseable_goal_is_reported_not_raised(self, specs_dir):
        """Matches rebuild_registry's existing contract — the registry rebuild
        runs after a spec is already on disk, so raising strands the user."""
        from meridian.specs import read_goals

        (specs_dir / "goals" / "goal-99.md").write_text("---\nid: [unclosed\n---\n")
        goals = read_goals(specs_dir)
        assert goals == [{"id": "goal-99", "name": "goal-99", "status": "unparseable"}]

    def test_missing_goals_directory_is_empty_not_an_error(self, tmp_path):
        from meridian.specs import read_goals

        assert read_goals(tmp_path / "nope") == []


# ── render_html: escaping ─────────────────────────────────────────────────── #

TINY_TEMPLATE = (
    "<!doctype html><html><body><script>const DATA = "
    f"{report.PAYLOAD_START}null{report.PAYLOAD_END};</script></body></html>"
)


class TestRenderHtml:
    def test_payload_is_embedded(self):
        html = report.render_html({"project": "demo"}, TINY_TEMPLATE)
        assert '{"project":"demo"}' in html

    def test_missing_sentinel_is_an_error_not_a_silent_no_op(self):
        with pytest.raises(ValueError, match="payload sentinel"):
            report.render_html({}, "<html>no sentinel here</html>")

    @pytest.mark.parametrize(
        "hostile",
        [
            "</script><img onerror=1>",
            "</SCRIPT >",
            "name with <!-- comment open",
            "name with --> comment close",
            "back`ticks` and ${interpolation}",
        ],
    )
    def test_hostile_text_cannot_break_out_of_the_script_block(self, hostile):
        html = report.render_html(
            {"features": [{"name": hostile, "blocked_by": hostile}]}, TINY_TEMPLATE
        )
        # Exactly one script element, and nothing after the payload escaped into
        # markup: the only `</script` in the document is the template's own.
        assert len(re.findall(r"</script", html, re.IGNORECASE)) == 1
        assert "<!--" not in html
        assert "-->" not in html

    def test_escaped_payload_still_parses_as_json_in_the_browser(self):
        """`<\\/` is a valid JSON string escape, so escaping for HTML must not
        cost us a parseable payload."""
        hostile = "</script>"
        html = report.render_html({"name": hostile}, TINY_TEMPLATE)
        embedded = html.split("const DATA = ")[1].split(";</script>")[0]
        # What the browser's JSON parser would see after JS unescapes `<\/`.
        assert json.loads(embedded.replace("<\\/", "</")) == {"name": hostile}

    def test_js_line_terminators_are_escaped(self):
        """U+2028/U+2029 are legal inside a JSON string but terminate a line in
        JavaScript — unescaped, they are a syntax error in the page."""
        html = report.render_html({"name": "a b c"}, TINY_TEMPLATE)
        assert " " not in html
        assert " " not in html


# ── write_report + self-containment ───────────────────────────────────────── #

class TestWriteReport:
    def test_writes_the_page_and_creates_parents(self, mock_cfg, specs_dir):
        write_spec(specs_dir, "FEAT-001")
        out = mock_cfg.root / "nested" / "dir" / "report.html"
        written = report.write_report(mock_cfg, out)
        assert written == out
        assert out.exists()
        # The page plus the self-ignore file it drops — and nothing else.
        assert sorted(p.name for p in out.parent.iterdir()) == [
            ".gitignore", "report.html",
        ]

    def test_new_output_directory_ignores_itself(self, mock_cfg, specs_dir):
        """The ignore rule in this repo's own .gitignore only helped this repo.
        Every other project got an untracked file in `git status`, and a setup
        step per project is one nobody remembers."""
        write_spec(specs_dir, "FEAT-001")
        out = mock_cfg.root / "specs" / ".meridian" / "report.html"
        report.write_report(mock_cfg, out)
        assert (out.parent / ".gitignore").read_text().rstrip().endswith("*")

    def test_existing_directory_is_not_given_an_ignore_file(self, mock_cfg, specs_dir):
        """`--out` into a directory the user already has must not start
        ignoring their files. Only a directory this command creates is ours."""
        write_spec(specs_dir, "FEAT-001")
        target = mock_cfg.root / "mine"
        target.mkdir()
        (target / "keep.txt").write_text("mine")
        report.write_report(mock_cfg, target / "report.html")
        assert not (target / ".gitignore").exists()

    def test_an_existing_ignore_file_is_left_alone(self, mock_cfg, specs_dir):
        write_spec(specs_dir, "FEAT-001")
        out = mock_cfg.root / "fresh" / "report.html"
        report.write_report(mock_cfg, out)
        (out.parent / ".gitignore").write_text("# hand-edited\n")
        report.write_report(mock_cfg, out)
        assert (out.parent / ".gitignore").read_text() == "# hand-edited\n"

    def test_reflects_current_disk_state_with_no_caching(self, mock_cfg, specs_dir):
        """AC7. Every call re-reads the specs, so a new feature appears without
        anything having to be invalidated."""
        write_spec(specs_dir, "FEAT-001")
        out = mock_cfg.root / "r.html"
        first = report.write_report(mock_cfg, out).read_text()
        assert "FEAT-002" not in first

        write_spec(specs_dir, "FEAT-002", slug="second")
        second = report.write_report(mock_cfg, out).read_text()
        assert "FEAT-002" in second

    def test_page_has_no_external_references(self, mock_cfg, specs_dir):
        """AC1. The page must render with the network off, so nothing may be
        fetched at render time — no CDN, no webfont, no XHR.

        The patterns are attribute-scoped: a plain `https://` inside a feature
        name is legitimate content, and a blanket URL ban would forbid it.
        """
        write_spec(
            specs_dir, "FEAT-001",
            name="A feature mentioning https://example.com in prose",
        )
        html = report.write_report(mock_cfg, mock_cfg.root / "r.html").read_text()

        forbidden = {
            "external script": r"<script[^>]+\bsrc\s*=",
            "external stylesheet": r"<link[^>]+\bhref\s*=",
            "css import": r"@import",
            "remote css url": r"url\(\s*['\"]?https?:",
            "network fetch": r"\bfetch\s*\(",
            "xhr": r"XMLHttpRequest",
            "module import": r"\bimport\s+[^;]*\bfrom\s+['\"]https?:",
            "service worker": r"serviceWorker",
        }
        for label, pattern in forbidden.items():
            assert not re.search(pattern, html, re.IGNORECASE), (
                f"report page contains {label}: /{pattern}/"
            )

    def test_written_page_embeds_the_real_payload(self, mock_cfg, specs_dir):
        write_spec(specs_dir, "FEAT-001", name="Findable feature")
        html = report.write_report(mock_cfg, mock_cfg.root / "r.html").read_text()
        assert "Findable feature" in html
        assert report.PAYLOAD_START not in html  # the sentinel was consumed


class TestTemplateAsset:
    def test_template_is_locatable_via_importlib_resources(self):
        """A `Path(__file__)`-relative lookup passes in the source tree and
        fails in a wheel. This asserts the lookup the code actually uses."""
        text = report.load_template()
        assert report.PAYLOAD_START in text
        assert report.PAYLOAD_END in text

    def test_template_alone_is_a_valid_page(self):
        """The `null` default keeps the raw template openable during
        development, without running the CLI."""
        text = report.load_template()
        assert f"{report.PAYLOAD_START}null{report.PAYLOAD_END}" in text


# ── the page actually runs ────────────────────────────────────────────────── #

NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not installed")
class TestPageExecutes:
    """Execute the page's own JavaScript against a payload.

    Every other test here asserts on the *payload*. None of them would notice a
    JavaScript error in the template, which renders a blank page — the loudest
    possible failure for a user and an invisible one for the suite. This runs
    the real script blocks against a DOM stub and asserts the views appear.

    Skipped without node, so it is a second guard rather than the only one. The
    payload contract and the self-containment regexes stay pure-Python.
    """

    HARNESS = r"""
      const fs = require('fs');
      const html = fs.readFileSync(process.argv[1], 'utf8');
      const blocks = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
      let out = null;
      const document = { getElementById: () => ({ set innerHTML(v) { out = v; } }) };
      new Function('document', blocks.join('\n'))(document);
      process.stdout.write(out === null ? '' : out);
    """

    def _render(self, tmp_path: Path, payload: dict) -> str:
        page = tmp_path / "page.html"
        page.write_text(report.render_html(payload))
        proc = subprocess.run(
            [NODE, "-e", self.HARNESS, str(page)],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, f"page JS threw: {proc.stderr}"
        return proc.stdout

    def _payload(self, **over) -> dict:
        base = {
            "project": "synthetic",
            "generated_at": "2026-09-21T12:00:00+00:00",
            "meridian_version": "0.0.0",
            "stale_days": 30,
            "staleness_note": "mtimes, not git",
            "unreadable_specs": 0,
            "columns": [{"status": s, "label": lbl} for s, lbl in report.STATUS_COLUMNS],
            "goals": [
                {"id": "goal-01", "name": "First goal", "status": "active"},
                {"id": "goal-02", "name": "Goal with nothing in flight", "status": "active"},
            ],
            "features": [
                {
                    "id": "FEAT-001", "name": "Blocked thing", "status": "blocked",
                    "appetite": "m", "confidence": "low", "cycle": "2026-Q3",
                    "goal": "goal-01", "updated": "2026-09-01",
                    "depends_on": ["FEAT-999"], "enables": [],
                    "blocked_by": "waiting on an upstream API",
                    "tasks": {"checked": 2, "total": 5},
                },
                {
                    "id": "FEAT-002", "name": "Ungoaled idea", "status": "idea",
                    "appetite": "xs", "confidence": None, "cycle": None,
                    "goal": "~", "updated": "2026-08-01",
                    "depends_on": [], "enables": ["FEAT-001"],
                    "blocked_by": None, "tasks": None,
                },
                {
                    "id": "FEAT-003", "name": "Never broken down", "status": "in-progress",
                    "appetite": "l", "confidence": "high", "cycle": "2026-Q3",
                    "goal": "goal-01", "updated": "2026-09-20",
                    "depends_on": ["FEAT-002"], "enables": [],
                    "blocked_by": None, "tasks": None,
                },
                {
                    "id": "FEAT-004", "name": "Parked", "status": "abandoned",
                    "appetite": None, "confidence": None, "cycle": None,
                    "goal": None, "updated": "2026-07-01",
                    "depends_on": [], "enables": [], "blocked_by": None, "tasks": None,
                },
            ],
            "signals": {
                "FEAT-001": {"days_since_change": 45, "stale": True, "goal_key": "goal-01", "rank": 1},
                "FEAT-002": {"days_since_change": 3, "stale": False, "goal_key": None, "rank": 0},
                "FEAT-003": {"days_since_change": 20, "stale": False, "goal_key": "goal-01", "rank": 1},
                "FEAT-004": {"days_since_change": 80, "stale": True, "goal_key": None, "rank": 0},
            },
            "edges": [
                {"from": "FEAT-001", "to": "FEAT-999", "kind": "depends_on", "dangling": True},
                {"from": "FEAT-001", "to": "FEAT-002", "kind": "enables", "dangling": False},
                {"from": "FEAT-003", "to": "FEAT-002", "kind": "depends_on", "dangling": False},
            ],
        }
        base.update(over)
        return base

    def test_all_views_render(self, tmp_path):
        out = self._render(tmp_path, self._payload())
        for probe in ("Board", "Goals × features", "Dependencies", "Staleness",
                      'svg class="graph"', 'footer class="page"'):
            assert probe in out, f"missing view: {probe}"
        assert "NaN" not in out
        assert "undefined" not in out

    def test_blocked_card_shows_its_reason(self, tmp_path):
        """AC4. Without this the board sends the reader back to the spec file,
        which is the one thing it exists to save them."""
        out = self._render(tmp_path, self._payload())
        assert "waiting on an upstream API" in out

    def test_dangling_edge_is_drawn_distinguishably(self, tmp_path):
        """AC3. Kept and marked, not silently dropped."""
        out = self._render(tmp_path, self._payload())
        assert 'class="edge dangling"' in out
        assert 'class="node missing"' in out
        assert "FEAT-999" in out

    def test_goal_with_nothing_in_flight_still_has_a_row(self, tmp_path):
        """AC5. An omitted row hides the gap the matrix exists to show."""
        out = self._render(tmp_path, self._payload())
        assert "goal-02" in out
        assert 'class="cell empty"' in out
        assert 'tr class="ungoaled"' in out

    def test_task_progress_is_a_bar_and_no_list_is_distinct(self, tmp_path):
        """AC6, plus the distinction `task_progress()` makes between a stub
        tasks.md (None) and a real list with nothing ticked (0/N)."""
        out = self._render(tmp_path, self._payload())
        assert 'style="width:40%"' in out
        assert "2/5 tasks" in out
        assert "no task list" in out

    def test_empty_columns_collapse_but_keep_their_place(self, tmp_path):
        """An equal split spent two thirds of the board on states this project
        has nothing in. The column still has to be there — the gap is
        information — just not at full width."""
        out = self._render(tmp_path, self._payload())
        # idea / blocked / in-progress hold cards here; draft, done and
        # in-production do not.
        assert 'class="col empty"' in out
        # Every column is still rendered, empty or not.
        for _status, label in report.STATUS_COLUMNS:
            assert ">" + label + "<" in out
        # The track list sizes occupied columns flexibly and empty ones by token.
        assert "--cols:" in out
        assert "var(--col-empty)" in out
        assert "minmax(0,1fr)" in out

    def test_track_list_matches_the_column_order(self, tmp_path):
        """The strip has to land under the right header, so the track list is
        positional — one entry per column, in order."""
        import re

        out = self._render(tmp_path, self._payload())
        track = re.search(r'--cols:([^"]+)"', out).group(1).strip().split(" ")
        assert len(track) == len(report.STATUS_COLUMNS)
        occupied = {f["status"] for f in self._payload()["features"]}
        for (status, _label), entry in zip(report.STATUS_COLUMNS, track):
            expected = "minmax(0,1fr)" if status in occupied else "var(--col-empty)"
            assert entry == expected, f"{status} got {entry}"

    def test_board_sizing_does_not_use_an_inline_grid_property(self, tmp_path):
        """An inline `grid-template-columns` would outrank the responsive
        overrides and the board would stay six columns wide on a phone."""
        out = self._render(tmp_path, self._payload())
        assert "grid-template-columns" not in out

    def test_status_outside_the_columns_is_collapsed_not_dropped(self, tmp_path):
        out = self._render(tmp_path, self._payload())
        assert 'details class="extra"' in out
        assert "Parked" in out

    def test_hostile_text_stays_text_in_the_dom(self, tmp_path):
        payload = self._payload()
        payload["features"][0]["name"] = '</script><img onerror=alert(1)>'
        out = self._render(tmp_path, payload)
        assert "<img onerror" not in out
        assert "&lt;/script&gt;" in out

    def test_unreadable_specs_are_announced_on_the_page(self, tmp_path):
        """There is no stderr in a browser, so `all_specs`' warning has to
        surface here or a dropped spec is invisible."""
        out = self._render(tmp_path, self._payload(unreadable_specs=2))
        assert "2 spec files on disk could not be parsed" in out

    def test_empty_project_renders_an_empty_state(self, tmp_path):
        out = self._render(
            tmp_path, self._payload(features=[], signals={}, edges=[])
        )
        assert "No features yet" in out

    def test_bare_template_renders_a_prompt_not_a_crash(self, tmp_path):
        """The template's `null` default keeps it openable during development."""
        page = tmp_path / "bare.html"
        page.write_text(report.load_template())
        proc = subprocess.run(
            [NODE, "-e", self.HARNESS, str(page)], capture_output=True, text=True
        )
        assert proc.returncode == 0, proc.stderr
        assert "No payload embedded" in proc.stdout
