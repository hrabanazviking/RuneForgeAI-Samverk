"""Repository quotas (S-068).

A quota is a byte limit on what a repository may hold,
**enforced at receive time**: the receive path (Part IV's
receive-pack, gated at S-089) asks before it accepts new
objects, and a push that would take the repository over its
limit is refused *before* anything lands, with a message
that says — in plain numbers — how much the repository
holds, what its limit is, and how much the push tried to
add. No silent truncation, no half-accepted push.

- **Usage is measured, never estimated**: the same S-058
  filesystem walk (git objects + LFS + other) the owner
  sees in size accounting, so the number enforced is the
  number displayed.
- **Two levels, explicit only**: a per-repository quota
  (set by the owner or a site admin) wins; otherwise the
  instance default applies when an admin has set one;
  otherwise the repository is unlimited. A quota is never
  invented by the system.
- **Refusal is a decision object first** (`check_receive`)
  so surfaces can show the state before a push, and an
  exception second (`enforce_receive`, raising
  `QuotaError` with the same message) for the receive path
  itself.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore
from .audit import AuditLog
from .repo_size import measure_path
from .repositories import Repository, RepositoryStore

DEFAULT_QUOTA_SETTING = "repo_quota_default_bytes"


class QuotaError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class ReceiveDecision:
    allowed: bool
    full_name: str
    usage_bytes: int
    quota_bytes: int | None       # None = unlimited
    incoming_bytes: int
    message: str


def _validate_quota(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise QuotaError(
            "quota_invalid",
            "A quota is a whole number of bytes, zero or more.")
    return value


def _validate_incoming(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise QuotaError(
            "incoming_invalid",
            "An incoming size is a whole number of bytes, zero or more.")
    return value


class QuotaService:
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

    # -- lookups ---------------------------------------------------
    def _repo(self, owner, repo) -> Repository:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise QuotaError("no_such_repo", "No such repository.")
        return current

    def usage_bytes(self, owner, repo) -> int:
        current = self._repo(owner, repo)
        path = self._repos.path_for(current.owner, current.name)
        return measure_path(path).total_bytes

    def repo_quota(self, owner, repo) -> int | None:
        """The per-repository quota alone (None when unset)."""
        current = self._repo(owner, repo)
        row = self._conn.execute(
            "SELECT quota_bytes FROM repo_quotas WHERE repo_id = ?",
            (current.id,)).fetchone()
        return int(row["quota_bytes"]) if row else None

    def default_quota(self) -> int | None:
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (DEFAULT_QUOTA_SETTING,)).fetchone()
        return int(row["value"]) if row else None

    def effective_quota(self, owner, repo) -> int | None:
        """Per-repo quota wins; instance default next; else none."""
        per_repo = self.repo_quota(owner, repo)
        return per_repo if per_repo is not None else self.default_quota()

    # -- setting quotas ---------------------------------------------
    def _require_owner_or_admin(self, actor_user_id: int,
                                current: Repository):
        actor = self._accounts.get_by_id(actor_user_id)
        if actor is None:
            raise QuotaError("no_such_user", "No such account.")
        if not (actor.is_admin
                or actor.username_lower == current.owner_lower):
            raise QuotaError(
                "permission_denied",
                "Only the repository's owner or a site admin "
                "can set its quota.")
        return actor

    def set_repo_quota(self, actor_user_id: int, owner, repo,
                       quota_bytes: int | None, *,
                       source_ip: str | None = None) -> int | None:
        """Set (or, with None, clear) a repository's quota."""
        current = self._repo(owner, repo)
        actor = self._require_owner_or_admin(actor_user_id, current)
        with self._conn:
            if quota_bytes is None:
                self._conn.execute(
                    "DELETE FROM repo_quotas WHERE repo_id = ?",
                    (current.id,))
            else:
                quota = _validate_quota(quota_bytes)
                self._conn.execute(
                    "INSERT INTO repo_quotas (repo_id, quota_bytes,"
                    " updated_at) VALUES (?, ?, ?)"
                    " ON CONFLICT(repo_id) DO UPDATE SET"
                    " quota_bytes = excluded.quota_bytes,"
                    " updated_at = excluded.updated_at",
                    (current.id, quota, int(self._now())))
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.settings.change", target_kind="repo",
                target_id=current.full_name, outcome="success",
                source_ip=source_ip,
                detail={"key": "quota_bytes", "quota": quota_bytes})
        return self.effective_quota(owner, repo)

    def set_default_quota(self, actor_user_id: int,
                          quota_bytes: int | None) -> int | None:
        """Set (or clear) the instance-wide default. Admins only."""
        actor = self._accounts.get_by_id(actor_user_id)
        if actor is None:
            raise QuotaError("no_such_user", "No such account.")
        if not actor.is_admin:
            raise QuotaError(
                "permission_denied",
                "Only a site admin can set the instance default quota.")
        with self._conn:
            if quota_bytes is None:
                self._conn.execute(
                    "DELETE FROM settings WHERE key = ?",
                    (DEFAULT_QUOTA_SETTING,))
            else:
                self._conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?)"
                    " ON CONFLICT(key) DO UPDATE SET"
                    " value = excluded.value",
                    (DEFAULT_QUOTA_SETTING,
                     str(_validate_quota(quota_bytes))))
        return self.default_quota()

    # -- receive-time enforcement ------------------------------------
    def check_receive(self, owner, repo, incoming_bytes: int) -> ReceiveDecision:
        """Would accepting `incoming_bytes` keep the repo in quota?"""
        current = self._repo(owner, repo)
        incoming = _validate_incoming(incoming_bytes)
        usage = self.usage_bytes(owner, repo)
        quota = self.effective_quota(owner, repo)
        if quota is None:
            return ReceiveDecision(
                allowed=True, full_name=current.full_name,
                usage_bytes=usage, quota_bytes=None,
                incoming_bytes=incoming,
                message=f"{current.full_name} has no quota; "
                        f"it currently holds {usage} bytes.")
        if usage + incoming <= quota:
            return ReceiveDecision(
                allowed=True, full_name=current.full_name,
                usage_bytes=usage, quota_bytes=quota,
                incoming_bytes=incoming,
                message=f"{current.full_name} holds {usage} of "
                        f"{quota} bytes; this push adds {incoming}.")
        return ReceiveDecision(
            allowed=False, full_name=current.full_name,
            usage_bytes=usage, quota_bytes=quota,
            incoming_bytes=incoming,
            message=(
                f"Repository quota exceeded for {current.full_name}: "
                f"it holds {usage} bytes of its {quota}-byte quota, "
                f"and this push adds {incoming} bytes. "
                "Remove or shrink content, or ask the repository's "
                "owner or a site admin to raise the quota."))

    def enforce_receive(self, owner, repo, incoming_bytes: int) -> ReceiveDecision:
        """The receive path's gate: returns the decision when the
        push fits, raises `QuotaError` carrying the plain refusal
        message when it does not — before any object is accepted."""
        decision = self.check_receive(owner, repo, incoming_bytes)
        if not decision.allowed:
            raise QuotaError("quota_exceeded", decision.message)
        return decision
