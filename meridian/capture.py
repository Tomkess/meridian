"""
Screenshot capture seams (FEAT-006).

An image attached in a Claude Code chat reaches the agent as base64 with no
filesystem path, and Claude Code keeps no on-disk attachment cache — so an agent
can *see* a screenshot it cannot *copy*. The file is on disk, though: macOS
writes screenshots straight into the screenshot directory. This module finds it.

macOS-first by design; other platforms fall back to a directory chain and
otherwise expect an explicit path.
"""
import subprocess
import sys
from pathlib import Path

from meridian.enrich import IMAGE_SUFFIXES

# Where to look when `defaults` has no screenshot location set.
_FALLBACK_DIRS = ("~/Desktop", "~/Pictures/Screenshots")

# Clipboard flavours that mean "there is an image here".
_IMAGE_CLIPBOARD_CLASSES = ("PNGf", "TIFF")


def _run(cmd: list[str], timeout: int = 5) -> subprocess.CompletedProcess:
    """Run a helper binary, converting environment failures into RuntimeError."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise RuntimeError(
            f"`{cmd[0]}` is not available on this system — pass an explicit image path "
            f"to `meridian enrich` instead."
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"`{cmd[0]}` did not respond within {timeout}s — pass an explicit image path "
            f"to `meridian enrich` instead."
        )


def screenshot_dir() -> Path:
    """Return the directory the OS saves screenshots into.

    On macOS, ``com.apple.screencapture location`` is authoritative *when set*.
    An unset key makes `defaults` exit non-zero with "does not exist" — that is
    the normal case, not an error, so it falls through to ~/Desktop.
    """
    tried: list[str] = []

    if sys.platform == "darwin":
        proc = _run(["defaults", "read", "com.apple.screencapture", "location"])
        if proc.returncode == 0:
            configured = Path(proc.stdout.strip()).expanduser()
            if configured.is_dir():
                return configured
            tried.append(str(configured))

    for candidate in _FALLBACK_DIRS:
        path = Path(candidate).expanduser()
        if path.is_dir():
            return path
        tried.append(str(path))

    raise RuntimeError(
        "Could not find a screenshot directory. Tried: "
        + ", ".join(tried)
        + ".\nPass the image path explicitly instead of --latest-screenshot."
    )


def latest_screenshot(directory: Path | None = None) -> tuple[Path, float]:
    """Newest image in the screenshot directory, with its age in seconds.

    The age is returned rather than judged — the CLI decides what is stale
    enough to warn about, and always reports which file it picked.
    """
    import time

    search_dir = directory if directory is not None else screenshot_dir()
    images = [
        p for p in search_dir.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
    ]
    if not images:
        raise RuntimeError(
            f"No images found in {search_dir}. Take a screenshot first, "
            f"or pass the image path explicitly."
        )
    newest = max(images, key=lambda p: p.stat().st_mtime)
    age = max(0.0, time.time() - newest.stat().st_mtime)
    return newest, age


def clipboard_image(dest: Path) -> Path:
    """Write the clipboard's image to ``dest``. macOS only.

    Probes the clipboard's flavours first: a text clipboard reports only classes
    like «class HTML»/«class utf8»/string, and asking for image data in that
    state produces a confusing AppleScript error rather than a useful one.
    """
    if sys.platform != "darwin":
        raise RuntimeError(
            "--from-clipboard is macOS-only. Use --latest-screenshot or pass an "
            "explicit image path."
        )

    info = _run(["osascript", "-e", "clipboard info"])
    if info.returncode != 0 or not any(c in info.stdout for c in _IMAGE_CLIPBOARD_CLASSES):
        raise RuntimeError(
            "Clipboard holds no image. Copy a screenshot first "
            "(Cmd+Ctrl+Shift+4), or use --latest-screenshot."
        )

    dest.parent.mkdir(parents=True, exist_ok=True)
    script = (
        f'set f to open for access POSIX file "{dest}" with write permission\n'
        "write (the clipboard as «class PNGf») to f\n"
        "close access f"
    )
    proc = _run(["osascript", "-e", script], timeout=30)
    if proc.returncode != 0 or not dest.exists():
        raise RuntimeError(
            f"Could not read the image out of the clipboard: {proc.stderr.strip()}\n"
            "Use --latest-screenshot instead."
        )
    return dest
