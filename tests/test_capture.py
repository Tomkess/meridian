"""Tests for meridian/capture.py — screenshot-directory and clipboard seams (FEAT-006).

Both seams shell out to macOS binaries, so `subprocess.run` is patched throughout.
The cases that matter are the *observed* ones: `defaults` exits non-zero when the
screenshot location has never been set, and `clipboard info` on a text clipboard
reports no image class at all.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from meridian import capture


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


# ── screenshot_dir ───────────────────────────────────────────────────────── #


class TestScreenshotDir:
    def test_honours_configured_location(self, tmp_path: Path):
        configured = tmp_path / "Shots"
        configured.mkdir()
        with patch.object(capture.sys, "platform", "darwin"), \
             patch.object(capture, "_run", return_value=_proc(0, f"{configured}\n")):
            assert capture.screenshot_dir() == configured

    def test_unset_defaults_key_falls_back_to_desktop(self, tmp_path: Path):
        desktop = tmp_path / "Desktop"
        desktop.mkdir()
        # `defaults read` exits 1 with "does not exist" when the key was never
        # set — the normal case, not an error.
        with patch.object(capture.sys, "platform", "darwin"), \
             patch.object(capture, "_run", return_value=_proc(1, "", "does not exist")), \
             patch.object(capture, "_FALLBACK_DIRS", (str(desktop),)):
            assert capture.screenshot_dir() == desktop

    def test_configured_but_missing_dir_falls_through(self, tmp_path: Path):
        pictures = tmp_path / "Pictures" / "Screenshots"
        pictures.mkdir(parents=True)
        with patch.object(capture.sys, "platform", "darwin"), \
             patch.object(capture, "_run", return_value=_proc(0, str(tmp_path / "gone"))), \
             patch.object(capture, "_FALLBACK_DIRS", (str(tmp_path / "nope"), str(pictures))):
            assert capture.screenshot_dir() == pictures

    def test_no_directory_found_names_everything_tried(self, tmp_path: Path):
        with patch.object(capture.sys, "platform", "darwin"), \
             patch.object(capture, "_run", return_value=_proc(1)), \
             patch.object(capture, "_FALLBACK_DIRS", (str(tmp_path / "a"), str(tmp_path / "b"))):
            with pytest.raises(RuntimeError) as exc:
                capture.screenshot_dir()
        assert "a" in str(exc.value) and "b" in str(exc.value)

    def test_non_darwin_skips_defaults(self, tmp_path: Path):
        desktop = tmp_path / "Desktop"
        desktop.mkdir()
        run = MagicMock()
        with patch.object(capture.sys, "platform", "linux"), \
             patch.object(capture, "_run", run), \
             patch.object(capture, "_FALLBACK_DIRS", (str(desktop),)):
            assert capture.screenshot_dir() == desktop
        run.assert_not_called()


# ── latest_screenshot ────────────────────────────────────────────────────── #


class TestLatestScreenshot:
    def _image(self, directory: Path, name: str, mtime: float) -> Path:
        path = directory / name
        path.write_bytes(b"\x89PNG")
        import os
        os.utime(path, (mtime, mtime))
        return path

    def test_returns_newest_image_with_age(self, tmp_path: Path):
        import time
        now = time.time()
        self._image(tmp_path, "old.png", now - 3600)
        newest = self._image(tmp_path, "new.png", now - 30)
        path, age = capture.latest_screenshot(tmp_path)
        assert path == newest
        assert 0 <= age < 300

    def test_non_image_files_ignored(self, tmp_path: Path):
        import time
        now = time.time()
        png = self._image(tmp_path, "shot.png", now - 600)
        # Newer, but not an image.
        (tmp_path / "notes.txt").write_text("hi")
        path, _ = capture.latest_screenshot(tmp_path)
        assert path == png

    def test_subdirectories_not_descended(self, tmp_path: Path):
        import time
        now = time.time()
        png = self._image(tmp_path, "shot.png", now - 600)
        nested = tmp_path / "nested"
        nested.mkdir()
        self._image(nested, "newer.png", now)
        path, _ = capture.latest_screenshot(tmp_path)
        assert path == png

    def test_empty_directory_names_the_directory(self, tmp_path: Path):
        with pytest.raises(RuntimeError, match=str(tmp_path)):
            capture.latest_screenshot(tmp_path)


# ── clipboard_image ──────────────────────────────────────────────────────── #


class TestClipboardImage:
    def test_text_clipboard_reports_no_image(self, tmp_path: Path):
        # Observed real-world output for a text clipboard: no image class.
        text_info = "«class HTML», 12214, «class utf8», 1390, string, 17"
        with patch.object(capture.sys, "platform", "darwin"), \
             patch.object(capture, "_run", return_value=_proc(0, text_info)):
            with pytest.raises(RuntimeError, match="no image"):
                capture.clipboard_image(tmp_path / "out.png")

    def test_png_clipboard_is_written(self, tmp_path: Path):
        dest = tmp_path / "out.png"

        def fake_run(cmd, timeout=5):
            if cmd[-1] == "clipboard info":
                return _proc(0, "«class PNGf», 4096")
            dest.write_bytes(b"\x89PNG")
            return _proc(0)

        with patch.object(capture.sys, "platform", "darwin"), \
             patch.object(capture, "_run", side_effect=fake_run):
            assert capture.clipboard_image(dest) == dest
        assert dest.read_bytes().startswith(b"\x89PNG")

    def test_extraction_failure_points_at_latest_screenshot(self, tmp_path: Path):
        def fake_run(cmd, timeout=5):
            if cmd[-1] == "clipboard info":
                return _proc(0, "«class PNGf», 4096")
            return _proc(1, "", "osascript: write failed")

        with patch.object(capture.sys, "platform", "darwin"), \
             patch.object(capture, "_run", side_effect=fake_run):
            with pytest.raises(RuntimeError, match="--latest-screenshot"):
                capture.clipboard_image(tmp_path / "out.png")

    def test_non_darwin_refuses_immediately(self, tmp_path: Path):
        run = MagicMock()
        with patch.object(capture.sys, "platform", "linux"), patch.object(capture, "_run", run):
            with pytest.raises(RuntimeError, match="macOS-only"):
                capture.clipboard_image(tmp_path / "out.png")
        run.assert_not_called()


# ── _run error mapping ───────────────────────────────────────────────────── #


class TestRunHelper:
    def test_missing_binary_becomes_actionable_runtime_error(self):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            with pytest.raises(RuntimeError, match="explicit image path"):
                capture._run(["defaults", "read", "x"])

    def test_timeout_becomes_actionable_runtime_error(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("defaults", 5)):
            with pytest.raises(RuntimeError, match="did not respond"):
                capture._run(["defaults", "read", "x"])
