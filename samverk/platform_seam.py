"""The platform seam.

Every platform touchpoint in Samverk — paths, OS identity, directory
creation — goes through this module and nowhere else (roadmap virtue 6;
research/45-cross-platform-architecture.md; threat model TB8). No other
module reads ``sys.platform`` or guesses at OS conventions, so nothing
is born platform-locked and Part XXII can audit portability in exactly
one place.

The seam is deliberately small in S-002: OS identification, the default
data-root location per OS convention, and directory creation. Process,
signal, and locking primitives join it in the slices that first need
them — named here so nobody builds them elsewhere:

    LANDED: process creation lives in samverk/proc.py (S-014) —
    it needed its policy home (allowlists) first.
    FUTURE: lock_file()  — advisory file locking (Part III)
    FUTURE: service_*()  — service-manager integration (Part XVIII)
"""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

__all__ = [
    "os_name",
    "machine",
    "data_root_default",
    "ensure_dir",
    "secret_file_is_private",
]


def os_name() -> str:
    """Return the Samverk OS family: 'linux', 'windows', or 'macos'.

    Other unix-likes report 'linux'-family only when they truly are
    Linux; unknown platforms raise rather than silently guessing,
    because a wrong guess here becomes a security bug at TB8.
    """
    p = sys.platform
    if p.startswith("linux"):
        return "linux"
    if p == "win32":
        return "windows"
    if p == "darwin":
        return "macos"
    raise RuntimeError(f"unsupported platform: {sys.platform!r}")


def machine() -> str:
    """Return the CPU architecture string (e.g. 'x86_64', 'aarch64')."""
    return platform.machine()


def data_root_default() -> Path:
    """The default data root for this OS, per its own conventions.

    Linux:   $XDG_DATA_HOME/samverk or ~/.local/share/samverk
    Windows: %LOCALAPPDATA%/Samverk
    macOS:   ~/Library/Application Support/Samverk
    """
    home = Path.home()
    family = os_name()
    if family == "windows":
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else home / "AppData" / "Local"
        return root / "Samverk"
    if family == "macos":
        return home / "Library" / "Application Support" / "Samverk"
    base = os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else home / ".local" / "share"
    return root / "samverk"


def ensure_dir(path: Path) -> Path:
    """Create *path* (and parents) if missing; return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def secret_file_is_private(path: Path) -> bool:
    """True when *path* is readable only by its owner.

    POSIX: no group/other permission bits may be set (mode 600 or
    stricter). Windows: POSIX modes do not exist; ACL verification is
    an install-time concern (Part XVIII), so this returns True and the
    difference is named here rather than hidden — the S-003 battery
    checks the POSIX behaviour on POSIX platforms only.
    """
    if os_name() == "windows":
        return True
    return path.stat().st_mode & 0o077 == 0
