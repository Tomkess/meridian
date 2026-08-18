"""Capture file format and inbox listing (FEAT-008)."""
import datetime
import os
from pathlib import Path

import pytest

from meridian.home import icebox_dir, inbox_dir, processed_dir
from meridian.inbox import (
    archive,
    find_capture,
    list_captures,
    read_capture,
    write_capture,
)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch) -> Path:
    """Never touch the real ~/.meridian — it has been wiped once already."""
    home = tmp_path / "meridian-home"
    monkeypatch.setenv("MERIDIAN_HOME", str(home))
    return home


def _drop(name: str, body: str) -> Path:
    path = inbox_dir() / name
    path.write_text(body)
    return path


class TestReadCapture:
    def test_bare_text_is_valid(self) -> None:
        """AC2: a bare line dropped in by any tool is a legitimate capture."""
        path = _drop("2026-08-18T164500.md", "just an idea\n")
        c = read_capture(path)
        assert c.text == "just an idea"
        assert c.project is None
        assert c.hint_source is None
        assert c.is_routable

    def test_frontmatter_project_is_explicit_hint(self) -> None:
        path = _drop("2026-08-18T164500.md", "---\nproject: Meridian\n---\nbody text\n")
        c = read_capture(path)
        assert c.project == "meridian"
        assert c.hint_source == "frontmatter"
        assert c.text == "body text"

    def test_optional_fields_parsed(self) -> None:
        path = _drop(
            "2026-08-18T164500.md",
            "---\ngoal: goal-01\nappetite: s\n---\nbody\n",
        )
        c = read_capture(path)
        assert c.goal == "goal-01"
        assert c.appetite == "s"

    def test_malformed_frontmatter_degrades_to_body(self) -> None:
        """Losing an idea to a YAML typo is worse than losing its metadata."""
        path = _drop("2026-08-18T164500.md", "---\n: : not yaml :\n---\nstill here\n")
        c = read_capture(path)
        assert "still here" in c.text
        assert c.project is None

    def test_hashtag_is_routing_hint(self) -> None:
        path = _drop("2026-08-18T164500.md", "add retries to the scraper #bet365-apify-scraper\n")
        c = read_capture(path)
        assert c.project == "bet365-apify-scraper"
        assert c.hint_source == "hashtag"

    def test_first_hashtag_wins(self) -> None:
        path = _drop("2026-08-18T164500.md", "idea #meridian and also #portfolio\n")
        assert read_capture(path).project == "meridian"

    def test_numeric_hash_is_not_a_hint(self) -> None:
        """`#1` in prose must not be read as a project name."""
        path = _drop("2026-08-18T164500.md", "fix issue #1 and #2026 planning\n")
        assert read_capture(path).project is None

    def test_frontmatter_beats_hashtag(self) -> None:
        path = _drop(
            "2026-08-18T164500.md",
            "---\nproject: meridian\n---\nbody mentioning #portfolio\n",
        )
        c = read_capture(path)
        assert c.project == "meridian"
        assert c.hint_source == "frontmatter"

    def test_timestamp_from_filename(self) -> None:
        path = _drop("2026-08-18T164500.md", "idea\n")
        c = read_capture(path)
        assert c.created == datetime.datetime(2026, 8, 18, 16, 45, 0)

    def test_timestamp_falls_back_to_mtime(self) -> None:
        path = _drop("not-a-timestamp.md", "idea\n")
        os.utime(path, (1_600_000_000, 1_600_000_000))
        c = read_capture(path)
        assert c.created == datetime.datetime.fromtimestamp(1_600_000_000)

    def test_whitespace_only_is_not_routable(self) -> None:
        """AC20: reported and skipped, not routed."""
        path = _drop("2026-08-18T164500.md", "   \n\n")
        assert read_capture(path).is_routable is False

    def test_first_line_skips_blanks(self) -> None:
        path = _drop("2026-08-18T164500.md", "\n\n  real first line\nsecond\n")
        assert read_capture(path).first_line == "real first line"


class TestWriteCapture:
    def test_writes_and_reads_back(self) -> None:
        path = write_capture("an idea from the phone")
        assert path.exists()
        assert read_capture(path).text == "an idea from the phone"

    def test_explicit_project_written_as_frontmatter(self) -> None:
        path = write_capture("scoped idea", project="meridian")
        c = read_capture(path)
        assert c.project == "meridian"
        assert c.hint_source == "frontmatter"

    def test_same_second_captures_both_survive(self) -> None:
        """One file per capture — a second write must not overwrite the first."""
        now = datetime.datetime(2026, 8, 18, 16, 45, 0)
        first = write_capture("first", now=now)
        second = write_capture("second", now=now)

        assert first != second
        assert read_capture(first).text == "first"
        assert read_capture(second).text == "second"


class TestListCaptures:
    def test_sorted_oldest_first(self) -> None:
        _drop("2026-08-18T170000.md", "later\n")
        _drop("2026-08-18T164500.md", "earlier\n")
        assert [c.text for c in list_captures()] == ["earlier", "later"]

    def test_archived_subdirs_excluded(self) -> None:
        _drop("2026-08-18T164500.md", "pending\n")
        (processed_dir() / "2026-01-01T000000.md").write_text("done\n")
        (icebox_dir() / "2026-01-02T000000.md").write_text("dropped\n")

        assert [c.text for c in list_captures()] == ["pending"]

    def test_empty_inbox(self) -> None:
        assert list_captures() == []

    def test_find_by_id(self) -> None:
        _drop("2026-08-18T164500.md", "target\n")
        assert find_capture("2026-08-18T164500").text == "target"
        assert find_capture("nope") is None


class TestArchive:
    def test_moves_out_of_pending(self) -> None:
        _drop("2026-08-18T164500.md", "idea\n")
        capture = list_captures()[0]

        moved = archive(capture, processed_dir())

        assert moved.parent == processed_dir()
        assert not capture.path.exists()
        assert list_captures() == []

    def test_never_overwrites_existing_archive(self) -> None:
        (processed_dir() / "2026-08-18T164500.md").write_text("older archived\n")
        _drop("2026-08-18T164500.md", "newer\n")
        capture = list_captures()[0]

        moved = archive(capture, processed_dir())

        assert moved.name != "2026-08-18T164500.md"
        assert (processed_dir() / "2026-08-18T164500.md").read_text() == "older archived\n"
        assert moved.read_text().strip() == "newer"
