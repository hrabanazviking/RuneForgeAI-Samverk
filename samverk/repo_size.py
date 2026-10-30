"""Repository size accounting (S-058).

What a repository costs the instance, measured honestly:

- **Git objects** — every byte under the bare repo's `objects/`
  directory (loose + packed; git's own layout decides).
- **LFS objects** — every byte under the bare repo's `lfs/`
  directory, the per-repo LFS layout S-060 will fill. Absent
  until then, and reported as 0, never invented.
- **Other** — everything else in the bare repo (refs, hooks,
  config, and any future release assets stored alongside):
  counted, so the categories always sum to the total.
- **Total** — the whole bare directory, walked file by file.
  Symlinks are not followed (a link's own size, not its
  target's), so a planted link cannot inflate or hide bytes.

Shown to owners and site admins only (roadmap S-058): anyone
else is refused, and a private repo's size never leaks to a
stranger. No caching here — S-072's derived-data cache owns
off-path computation when browsing needs it at scale.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore
from .repositories import Repository, RepositoryStore


class SizeError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class RepoSize:
    full_name: str
    total_bytes: int
    git_objects_bytes: int
    lfs_bytes: int
    other_bytes: int
    file_count: int

    @property
    def object_store_bytes(self) -> int:
        return self.git_objects_bytes


def measure_path(path: Path) -> RepoSize:
    """Measure one bare-repo directory (pure filesystem walk)."""
    total = git_bytes = lfs_bytes = other = files = 0
    root = Path(path)
    if root.is_dir():
        for entry in root.rglob("*"):
            if entry.is_symlink() or not entry.is_file():
                continue
            try:
                size = entry.stat().st_size
            except OSError:
                continue
            files += 1
            total += size
            rel = entry.relative_to(root)
            top = rel.parts[0] if rel.parts else ""
            if top == "objects":
                git_bytes += size
            elif top == "lfs":
                lfs_bytes += size
            else:
                other += size
    return RepoSize(
        full_name="", total_bytes=total, git_objects_bytes=git_bytes,
        lfs_bytes=lfs_bytes, other_bytes=other, file_count=files)


class RepoSizeAccounting:
    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 accounts: AccountStore, repositories: RepositoryStore):
        self._conn = conn
        self._accounts = accounts
        self._repos = repositories

    def _authorised_repo(self, actor_user_id: int, owner, repo) -> Repository:
        actor = self._accounts.get_by_id(actor_user_id)
        if actor is None:
            raise SizeError("no_such_user", "No such account.")
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise SizeError("no_such_repo", "No such repository.")
        if not (actor.is_admin or actor.username_lower == current.owner_lower):
            raise SizeError(
                "permission_denied",
                "Repository sizes are shown to owners and admins.")
        return current

    def size_for(self, actor_user_id: int, owner, repo) -> RepoSize:
        current = self._authorised_repo(actor_user_id, owner, repo)
        measured = measure_path(self._repos.path_for(current.owner, current.name))
        return RepoSize(
            full_name=current.full_name, total_bytes=measured.total_bytes,
            git_objects_bytes=measured.git_objects_bytes,
            lfs_bytes=measured.lfs_bytes, other_bytes=measured.other_bytes,
            file_count=measured.file_count)

    def sizes_for_owner(self, actor_user_id: int, owner) -> list[RepoSize]:
        return [self.size_for(actor_user_id, r.owner, r.name)
                for r in self._repos.list_for_owner(owner)]
