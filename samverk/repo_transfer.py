"""Repository transfer (S-057).

Ownership moves only with the recipient's acceptance:

- **Initiate (owner-only).** The owner names a recipient
  account that exists and is not themselves. A repository
  already offered, or a recipient who already owns a repo of
  the same name, is refused by name. Nothing moves yet.
- **Accept (recipient-only).** The named recipient — and only
  they — accepts: the bare directory moves inside the one
  repositories root (a single `os.rename`, rolled back if the
  row update fails, the S-050 discipline), the row's owner
  becomes the recipient, and a **redirect** from the old
  canonical name to the new one is left behind for
  `REDIRECT_SECONDS` (90 days, the S-042 tombstone period).
- **Decline / cancel** remove the offer and move nothing.
  Audited: the completed move under the frozen `repo.transfer`
  event (detail `from_owner` / `to_owner`, per the taxonomy
  doc); offer, decline and cancel under `repo.settings.change`.
"""

from __future__ import annotations

import os
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore
from .audit import AuditLog
from .platform_seam import ensure_dir
from .repositories import Repository, RepositoryStore

REDIRECT_SECONDS = 90 * 24 * 3600


class TransferError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class PendingTransfer:
    repo_id: int
    from_owner_lower: str
    to_owner_lower: str
    requested_by: int
    created_at: int


@dataclass(frozen=True)
class RepoRedirect:
    old_full_name: str
    new_full_name: str
    expires_at: int


class RepoTransfer:
    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 accounts: AccountStore, repositories: RepositoryStore,
                 audit: AuditLog | None = None,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._data_root = Path(data_root)
        self._accounts = accounts
        self._repos = repositories
        self._audit = audit
        self._now = time_fn

    def _repo(self, owner, repo) -> Repository:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise TransferError("no_such_repo", "No such repository.")
        return current

    def pending_for(self, repo_id: int) -> PendingTransfer | None:
        row = self._conn.execute(
            "SELECT * FROM repo_transfers WHERE repo_id = ?",
            (repo_id,)).fetchone()
        if row is None:
            return None
        return PendingTransfer(
            repo_id=row["repo_id"], from_owner_lower=row["from_owner_lower"],
            to_owner_lower=row["to_owner_lower"],
            requested_by=row["requested_by"], created_at=row["created_at"])

    def initiate(self, actor_user_id: int, owner, repo,
                 recipient_username: object, *,
                 source_ip: str | None = None) -> PendingTransfer:
        actor = self._accounts.get_by_id(actor_user_id)
        if actor is None:
            raise TransferError("no_such_user", "No such account.")
        current = self._repo(owner, repo)
        if actor.username_lower != current.owner_lower:
            raise TransferError(
                "not_repo_owner", "Only the owner can transfer a repository.")
        recipient = (self._accounts.get_by_username(recipient_username)
                     if isinstance(recipient_username, str) else None)
        if recipient is None:
            raise TransferError("no_such_recipient", "No such recipient account.")
        if recipient.username_lower == current.owner_lower:
            raise TransferError(
                "transfer_to_self", "A repository cannot transfer to its owner.")
        if self.pending_for(current.id) is not None:
            raise TransferError("already_pending", "A transfer is already pending.")
        if self._repos.get_repository(
                recipient.username_lower, current.name_lower) is not None:
            raise TransferError(
                "repo_taken", "The recipient already owns a repository of that name.")
        pending = PendingTransfer(
            current.id, current.owner_lower, recipient.username_lower,
            actor.id, int(self._now()))
        with self._conn:
            self._conn.execute(
                "INSERT INTO repo_transfers (repo_id, from_owner_lower,"
                " to_owner_lower, requested_by, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (pending.repo_id, pending.from_owner_lower,
                 pending.to_owner_lower, pending.requested_by, pending.created_at))
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.settings.change", target_kind="repo",
                target_id=current.full_name, outcome="success",
                source_ip=source_ip,
                detail={"key": "transfer_request",
                        "to_owner": recipient.username})
        return pending

    def _require_recipient(self, actor_user_id: int, owner, repo):
        actor = self._accounts.get_by_id(actor_user_id)
        if actor is None:
            raise TransferError("no_such_user", "No such account.")
        current = self._repo(owner, repo)
        pending = self.pending_for(current.id)
        if pending is None:
            raise TransferError("no_pending_transfer", "No transfer is pending.")
        if actor.username_lower != pending.to_owner_lower:
            raise TransferError(
                "not_recipient", "Only the named recipient can decide this transfer.")
        return actor, current, pending

    def accept(self, actor_user_id: int, owner, repo, *,
               source_ip: str | None = None) -> Repository:
        actor, current, pending = self._require_recipient(actor_user_id, owner, repo)
        if self._repos.get_repository(
                actor.username_lower, current.name_lower) is not None:
            raise TransferError(
                "repo_taken", "You already own a repository of that name.")
        old_path = self._repos.path_for(current.owner, current.name)
        new_path = self._repos.path_for(actor.username, current.name)
        if new_path.exists():
            raise TransferError(
                "repo_path_exists", "A directory already exists at the new path.")
        ensure_dir(new_path.parent)
        os.rename(old_path, new_path)
        now = int(self._now())
        try:
            with self._conn:
                self._conn.execute(
                    "UPDATE repositories SET owner = ?, owner_lower = ?,"
                    " created_by = ? WHERE id = ?",
                    (actor.username, actor.username_lower, actor.id, current.id))
                self._conn.execute(
                    "INSERT OR REPLACE INTO repo_redirects (old_owner_lower,"
                    " old_name_lower, new_owner_lower, new_name_lower,"
                    " created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (current.owner_lower, current.name_lower,
                     actor.username_lower, current.name_lower,
                     now, now + REDIRECT_SECONDS))
                self._conn.execute(
                    "DELETE FROM repo_transfers WHERE repo_id = ?", (current.id,))
        except Exception:
            os.rename(new_path, old_path)
            raise
        moved = self._repos.get_by_id(current.id)
        assert moved is not None
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id, action="repo.transfer",
                target_kind="repo", target_id=moved.full_name,
                outcome="success", source_ip=source_ip,
                detail={"from_owner": current.owner, "to_owner": actor.username})
        return moved

    def decline(self, actor_user_id: int, owner, repo, *,
                source_ip: str | None = None) -> bool:
        actor, current, _ = self._require_recipient(actor_user_id, owner, repo)
        return self._end(actor, current, "transfer_decline", source_ip)

    def cancel(self, actor_user_id: int, owner, repo, *,
               source_ip: str | None = None) -> bool:
        actor = self._accounts.get_by_id(actor_user_id)
        if actor is None:
            raise TransferError("no_such_user", "No such account.")
        current = self._repo(owner, repo)
        if actor.username_lower != current.owner_lower:
            raise TransferError("not_repo_owner", "Only the owner can cancel.")
        if self.pending_for(current.id) is None:
            return False
        return self._end(actor, current, "transfer_cancel", source_ip)

    def _end(self, actor, current, key, source_ip) -> bool:
        with self._conn:
            self._conn.execute(
                "DELETE FROM repo_transfers WHERE repo_id = ?", (current.id,))
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.settings.change", target_kind="repo",
                target_id=current.full_name, outcome="success",
                source_ip=source_ip, detail={"key": key})
        return True

    def resolve_redirect(self, owner: object, repo: object) -> RepoRedirect | None:
        current = self._repos.get_repository(owner, repo)
        if current is not None:
            return None  # a live repo at that name shadows any redirect
        try:
            owner_lower, name_lower = str(owner).lower(), str(repo).lower()
        except Exception:
            return None
        row = self._conn.execute(
            "SELECT * FROM repo_redirects WHERE old_owner_lower = ?"
            " AND old_name_lower = ?", (owner_lower, name_lower)).fetchone()
        if row is None or int(self._now()) >= int(row["expires_at"]):
            return None
        target = self._repos.get_repository(
            row["new_owner_lower"], row["new_name_lower"])
        if target is None:
            return None
        return RepoRedirect(
            old_full_name=f"{owner}/{repo}", new_full_name=target.full_name,
            expires_at=int(row["expires_at"]))
