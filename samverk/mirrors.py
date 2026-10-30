"""Mirror storage layout (S-070).

A mirror is **an ordinary bare repository plus a mirror
record** — deliberately no second storage engine. The
repository lives at the same S-013 path, in the same
`repositories` table, measured by the same S-058 walk, read
by the same S-051/S-052 object and ref services, and bound
by the same S-054 permissions as every other repository.
The only mirror-specific facts — where it mirrors from, and
how the last sync ended — live in `repo_mirrors`.

- **Sources** are the two shapes S-069/S-014's seams trust:
  a remote URL (validated; credentials inside a URL are
  refused there, so a stored source can never hold a
  secret) or an absolute local `Path` naming an existing
  repository on this instance's disk.
- **Sync** is one fetch through the dedicated seam
  (`run_git_fetch_from`: every head and tag, pruned) — the
  mirror converges to its source, and the outcome is
  *recorded, never hidden*: `last_status` / `last_detail` /
  `last_sync_at` are written for failures exactly as for
  successes, and a failed sync leaves the mirror's existing
  content untouched and readable.
- Part XVII (the mirror duty for Volmarr's original
  repositories) builds on this layout; scheduling and
  fleet policy are that part's, not this slice's.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore
from .audit import AuditLog
from .proc import ProcRefused, run_git_fetch_from, validate_remote_url
from .repositories import Repository, RepositoryStore


class MirrorError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Mirror:
    repo_id: int
    full_name: str
    source: str
    source_kind: str              # "url" | "local"
    created_at: int
    last_sync_at: int | None
    last_status: str | None       # "ok" | "failed" | None (never synced)
    last_detail: str | None


@dataclass(frozen=True)
class SyncResult:
    full_name: str
    status: str                   # "ok" | "failed"
    synced_at: int
    detail: str


class MirrorService:
    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 accounts: AccountStore, repositories: RepositoryStore,
                 audit: AuditLog | None = None,
                 time_fn: Callable[[], float] = time.time,
                 fetch_timeout: float = 120.0):
        self._conn = conn
        self._data_root = Path(data_root)
        self._accounts = accounts
        self._repos = repositories
        self._audit = audit
        self._now = time_fn
        self._fetch_timeout = fetch_timeout

    # -- source law --------------------------------------------------
    @staticmethod
    def _validate_source(source: object) -> tuple[str, str]:
        """Return (stored_source, kind) or raise MirrorError."""
        if isinstance(source, Path):
            if not source.is_absolute() or not source.is_dir():
                raise MirrorError(
                    "source_invalid",
                    "A local mirror source must be an existing "
                    "repository directory given as a full path.")
            return str(source), "local"
        try:
            return validate_remote_url(source), "url"
        except ProcRefused as exc:
            raise MirrorError("source_invalid", str(exc)) from None

    # -- record --------------------------------------------------------
    def _repo(self, owner, repo) -> Repository:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise MirrorError("no_such_repo", "No such repository.")
        return current

    def _require_owner(self, actor_user_id: int, current: Repository):
        actor = self._accounts.get_by_id(actor_user_id)
        if actor is None:
            raise MirrorError("no_such_user", "No such account.")
        if actor.username_lower != current.owner_lower:
            raise MirrorError(
                "not_repo_owner",
                "Only the repository's owner can manage its mirror.")
        return actor

    def mirror_for(self, owner, repo) -> Mirror | None:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            return None
        row = self._conn.execute(
            "SELECT * FROM repo_mirrors WHERE repo_id = ?",
            (current.id,)).fetchone()
        if row is None:
            return None
        return Mirror(
            repo_id=row["repo_id"], full_name=current.full_name,
            source=row["source"], source_kind=row["source_kind"],
            created_at=row["created_at"], last_sync_at=row["last_sync_at"],
            last_status=row["last_status"], last_detail=row["last_detail"])

    def is_mirror(self, owner, repo) -> bool:
        return self.mirror_for(owner, repo) is not None

    # -- creation ------------------------------------------------------
    def create_mirror(self, actor_user_id: int, owner: object, repo: object,
                      source: object, *, visibility: str = "private",
                      source_ip: str | None = None) -> Mirror:
        """Create an ordinary (empty) repository and mark it a
        mirror of `source`. Content arrives with `sync_mirror`."""
        stored, kind = self._validate_source(source)
        created = self._repos.create_repository(
            actor_user_id, owner, repo, visibility=visibility,
            source_ip=source_ip)
        with self._conn:
            self._conn.execute(
                "INSERT INTO repo_mirrors (repo_id, source, source_kind,"
                " created_at) VALUES (?, ?, ?, ?)",
                (created.id, stored, kind, int(self._now())))
        mirror = self.mirror_for(created.owner, created.name)
        assert mirror is not None
        return mirror

    def attach_mirror(self, actor_user_id: int, owner, repo, source: object,
                      *, source_ip: str | None = None) -> Mirror:
        """Mark an existing repository as a mirror of `source`."""
        current = self._repo(owner, repo)
        actor = self._require_owner(actor_user_id, current)
        stored, kind = self._validate_source(source)
        if self.mirror_for(owner, repo) is not None:
            raise MirrorError(
                "mirror_exists",
                f"{current.full_name} already has a mirror source; "
                "detach it before attaching another.")
        with self._conn:
            self._conn.execute(
                "INSERT INTO repo_mirrors (repo_id, source, source_kind,"
                " created_at) VALUES (?, ?, ?, ?)",
                (current.id, stored, kind, int(self._now())))
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.settings.change", target_kind="repo",
                target_id=current.full_name, outcome="success",
                source_ip=source_ip,
                detail={"key": "mirror_source", "kind": kind})
        mirror = self.mirror_for(owner, repo)
        assert mirror is not None
        return mirror

    def detach_mirror(self, actor_user_id: int, owner, repo) -> None:
        """Remove the mirror record; the repository and its
        content stay exactly as they are (it simply stops
        being a mirror)."""
        current = self._repo(owner, repo)
        self._require_owner(actor_user_id, current)
        with self._conn:
            self._conn.execute(
                "DELETE FROM repo_mirrors WHERE repo_id = ?",
                (current.id,))

    # -- sync ------------------------------------------------------------
    def sync_mirror(self, owner, repo, *, token: str | None = None) -> SyncResult:
        """Fetch the mirror's source into it and record the
        outcome — success and failure alike."""
        current = self._repo(owner, repo)
        mirror = self.mirror_for(owner, repo)
        if mirror is None:
            raise MirrorError(
                "not_a_mirror", f"{current.full_name} is not a mirror.")
        source: str | Path = (Path(mirror.source)
                              if mirror.source_kind == "local"
                              else mirror.source)
        path = self._repos.path_for(current.owner, current.name)
        now = int(self._now())
        try:
            result = run_git_fetch_from(
                path, source, timeout=self._fetch_timeout, token=token)
            if result.returncode == 0:
                status, detail = "ok", "fetch completed"
            else:
                status = "failed"
                detail = result.stderr.decode(
                    "utf-8", "replace").strip()[:200] or "fetch failed"
        except Exception as exc:  # recorded, never hidden, never raised
            status, detail = "failed", f"{type(exc).__name__}: {exc}"[:200]
        with self._conn:
            self._conn.execute(
                "UPDATE repo_mirrors SET last_sync_at = ?, last_status = ?,"
                " last_detail = ? WHERE repo_id = ?",
                (now, status, detail, current.id))
        return SyncResult(full_name=current.full_name, status=status,
                          synced_at=now, detail=detail)
