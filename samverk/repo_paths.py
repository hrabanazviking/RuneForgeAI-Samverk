"""Repository path resolution (S-013).

The one mapping from repository *names* to disk *paths*. Every later
slice that touches a repository on disk — bare-repo creation (S-049),
HTTP and SSH transport, mirroring (Part XVII) — resolves through
here, so the traversal law lives in exactly one place and no handler
ever joins a user-supplied name onto a filesystem path itself.

Two defences, both applied, either one sufficient on its own:

1. **Name law.** Owner and repository names are validated against a
   strict allowlist shape before they ever meet the filesystem:
   ASCII letters, digits, hyphen, underscore, and single dots;
   must start with a letter or digit; no ``..`` anywhere; no path
   separators, spaces, control characters, or absolute forms; no
   trailing dot (Windows would silently strip it, aliasing two
   names to one path); Windows device names (``CON``, ``PRN``,
   ``AUX``, ``NUL``, ``COM1``…``LPT9``, with or without an
   extension) refused on every platform, because a repository
   checked out or mirrored onto a Windows machine must not become
   a device. A repository name's single trailing ``.git`` is
   canonicalised away — ``foo`` and ``foo.git`` are the same
   repository, and the storage suffix is added by this module.

2. **Containment law.** The candidate path is fully resolved
   (symlinks followed, via `pathlib`) and must land strictly inside
   the resolved repositories root. A symlink planted inside the
   tree — as an owner directory, or as the repository path itself —
   that points outside the root is therefore refused at resolve
   time, even though its *name* was perfectly legal. Resolution
   happens on every call, never cached, so a symlink swapped in
   after a first check is still caught at use.

The layout this module owns: ``<data_root>/repos/<owner>/<repo>.git``
(bare-repository storage, Part III). Nothing here creates
directories; creation is the caller's deliberate act (S-049).
"""

from __future__ import annotations

import re
from pathlib import Path

OWNER_MAX_LENGTH = 39
REPO_MAX_LENGTH = 100

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# Windows reserved device names: refused as a whole name or as the
# stem before the first dot, on every OS (cross-platform law).
_WINDOWS_DEVICES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


class RepoPathError(ValueError):
    """A name or path refused by the S-013 law; `reason` is a
    stable machine-readable code."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


def _validate_name(name: object, *, max_length: int, kind: str) -> str:
    if not isinstance(name, str) or not name:
        raise RepoPathError("empty_name", f"{kind} name is empty")
    if len(name) > max_length:
        raise RepoPathError("name_too_long", f"{kind} name exceeds {max_length} chars")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in name):
        raise RepoPathError("control_character", f"{kind} name {name!r}")
    if "/" in name or "\\" in name:
        raise RepoPathError("path_separator", f"{kind} name {name!r}")
    if ".." in name:
        raise RepoPathError("dotdot", f"{kind} name {name!r}")
    if name.endswith("."):
        raise RepoPathError("trailing_dot", f"{kind} name {name!r}")
    if not _NAME_RE.match(name):
        raise RepoPathError("bad_characters", f"{kind} name {name!r}")
    stem = name.split(".", 1)[0].upper()
    if stem in _WINDOWS_DEVICES:
        raise RepoPathError("reserved_name", f"{kind} name {name!r}")
    return name


def validate_owner_name(name: object) -> str:
    """Return *name* if it is a lawful owner name, else raise
    RepoPathError."""
    return _validate_name(name, max_length=OWNER_MAX_LENGTH, kind="owner")


def validate_repo_name(name: object) -> str:
    """Return the canonical repository name (a single trailing
    ``.git`` stripped) if lawful, else raise RepoPathError."""
    if isinstance(name, str) and name.lower().endswith(".git") and len(name) > 4:
        name = name[:-4]
    return _validate_name(name, max_length=REPO_MAX_LENGTH, kind="repository")


def repos_root(data_root: Path) -> Path:
    """The directory every repository lives under."""
    return Path(data_root) / "repos"


def _contained(root: Path, candidate: Path) -> Path:
    """Resolve both paths and require *candidate* to land strictly
    inside *root*; return the resolved candidate."""
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    if resolved == resolved_root or resolved_root not in resolved.parents:
        raise RepoPathError(
            "escapes_root", f"{candidate} resolves outside {root}")
    return resolved


def owner_dir(data_root: Path, owner: object) -> Path:
    """The resolved directory holding *owner*'s repositories."""
    owner = validate_owner_name(owner)
    root = repos_root(data_root)
    return _contained(root, root / owner)


def repo_path(data_root: Path, owner: object, repo: object) -> Path:
    """The resolved bare-repository path for ``owner/repo``.

    Raises RepoPathError for an unlawful name or a resolution that
    escapes the repositories root (planted symlink). The path need
    not exist yet — resolution follows whatever symlinks *do*
    exist along it, which is what makes the escape battery pass
    for not-yet-created repositories too.
    """
    owner = validate_owner_name(owner)
    repo = validate_repo_name(repo)
    root = repos_root(data_root)
    return _contained(root, root / owner / f"{repo}.git")
