"""Repository deletion (S-056).

Deletion is a process, not a button (the S-043 shape, for repos):

- **Owner-only, sudo-gated.** Requesting deletion requires the
  repository's owner and a fresh re-authentication verifier
  (S-036 supplies the real one); no verifier, no request.
- **Tombstone + grace.** A request records a pending deletion
  with a 7-day grace (`GRACE_SECONDS`, injectable for tests).
  During grace the repository and its disk are untouched and
  `cancel` (owner-only) restores it whole.
- **Disk reclaimed only after.** `finalize` / `execute_due`
  run only at or after the scheduled time: the metadata row
  goes, the bare directory is removed, and forks of the deleted
  repository — independent clones since S-055 — survive with
  their upstream link cleared (they become network roots).
  Audited: request/cancel under `repo.settings.change`,
  execution under the frozen `repo.delete` event.
"""

from __future__ import annotations

import shutil
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore
from .audit import AuditLog
from .repositories import RepositoryStore

GRACE_SECONDS = 7 * 24 * 3600


class RepoDeletionError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class PendingRepoDeletion:
    repo_id: int
    requested_by: int
    requested_at: int
    scheduled_at: int


class RepoDeletion:
    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 accounts: AccountStore, repositories: RepositoryStore,
                 audit: AuditLog | None = None,
                 grace_seconds: int = GRACE_SECONDS,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._data_root = Path(data_root)
        self._accounts = accounts
        self._repos = repositories
        self._audit = audit
        self._grace = grace_seconds
        self._now = time_fn

    def _require_owner(self, actor_user_id: int, owner, repo):
        actor = self._accounts.get_by_id(actor_user_id)
        if actor is None:
            raise RepoDeletionError("no_such_user", "No such account.")
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise RepoDeletionError("no_such_repo", "No such repository.")
        if actor.username_lower != current.owner_lower:
            raise RepoDeletionError(
                "not_repo_owner", "Only the repository's owner can delete it.")
        return actor, current

    def pending_for(self, repo_id: int) -> PendingRepoDeletion | None:
        row = self._conn.execute(
            "SELECT * FROM repo_deletions WHERE repo_id = ?",
            (repo_id,)).fetchone()
        if row is None:
            return None
        return PendingRepoDeletion(
            repo_id=row["repo_id"], requested_by=row["requested_by"],
            requested_at=row["requested_at"], scheduled_at=row["scheduled_at"])

    def is_pending(self, owner, repo) -> bool:
        current = self._repos.get_repository(owner, repo)
        return current is not None and self.pending_for(current.id) is not None

    def request(self, actor_user_id: int, owner, repo,
                reauth_verifier: Callable[[int], bool] | None = None,
                *, source_ip: str | None = None) -> PendingRepoDeletion:
        actor, current = self._require_owner(actor_user_id, owner, repo)
        if self.pending_for(current.id) is not None:
            raise RepoDeletionError(
                "already_pending", "Deletion is already scheduled.")
        if reauth_verifier is None or not reauth_verifier(actor_user_id):
            raise RepoDeletionError(
                "sudo_required",
                "Deletion needs a fresh password confirmation.")
        now = int(self._now())
        pending = PendingRepoDeletion(current.id, actor.id, now, now + self._grace)
        with self._conn:
            self._conn.execute(
                "INSERT INTO repo_deletions (repo_id, requested_by,"
                " requested_at, scheduled_at) VALUES (?, ?, ?, ?)",
                (pending.repo_id, pending.requested_by,
                 pending.requested_at, pending.scheduled_at))
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.settings.change", target_kind="repo",
                target_id=current.full_name, outcome="success",
                source_ip=source_ip,
                detail={"key": "deletion_request",
                        "scheduled_at": pending.scheduled_at})
        return pending

    def cancel(self, actor_user_id: int, owner, repo,
               *, source_ip: str | None = None) -> bool:
        actor, current = self._require_owner(actor_user_id, owner, repo)
        if self.pending_for(current.id) is None:
            return False
        with self._conn:
            self._conn.execute(
                "DELETE FROM repo_deletions WHERE repo_id = ?", (current.id,))
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.settings.change", target_kind="repo",
                target_id=current.full_name, outcome="success",
                source_ip=source_ip, detail={"key": "deletion_cancel"})
        return True

    def finalize(self, repo_id: int, *, source_ip: str | None = None) -> bool:
        pending = self.pending_for(repo_id)
        if pending is None or int(self._now()) < pending.scheduled_at:
            return False
        current = self._repos.get_by_id(repo_id)
        if current is None:
            with self._conn:
                self._conn.execute(
                    "DELETE FROM repo_deletions WHERE repo_id = ?", (repo_id,))
            return False
        path = self._repos.path_for(current.owner, current.name)
        with self._conn:
            self._conn.execute(
                "UPDATE repositories SET fork_of_id = NULL WHERE fork_of_id = ?",
                (repo_id,))
            self._conn.execute(
                "DELETE FROM repo_deletions WHERE repo_id = ?", (repo_id,))
            # S-057: a pending transfer offer dies with its repo.
            self._conn.execute(
                "DELETE FROM repo_transfers WHERE repo_id = ?", (repo_id,))
            self._conn.execute(
                "DELETE FROM repositories WHERE id = ?", (repo_id,))
        shutil.rmtree(path, ignore_errors=True)
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=pending.requested_by,
                action="repo.delete", target_kind="repo",
                target_id=current.full_name, outcome="success",
                source_ip=source_ip)
        return True

    def execute_due(self) -> list[int]:
        rows = self._conn.execute(
            "SELECT repo_id FROM repo_deletions WHERE scheduled_at <= ?"
            " ORDER BY repo_id", (int(self._now()),)).fetchall()
        return [int(r["repo_id"]) for r in rows
                if self.finalize(int(r["repo_id"]))]
