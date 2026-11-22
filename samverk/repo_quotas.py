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

S-354 widens this point, it does not build beside it: the
same `check_receive` now also judges a **per-user quota**
-- the owner's repositories measured together with the
same S-058 walk -- so a push is refused at this one point
when *either* limit would break, repo first, then user,
and the refusal names the level that bit, in plain
numbers. A per-user quota is explicit only, like the
repo levels: an admin-set per-user value wins, otherwise
an admin-set instance user default applies, otherwise
the user is unlimited. Per-user values ride the settings
table (`user_quota_bytes:<owner>` and
`user_quota_default_bytes`); no migration, no new store.
Only a site admin may set a user quota -- an owner
raising their own ceiling would be no ceiling at all --
and every change is audit-logged under the frozen
`admin.settings.change` verb with the key named. The
owner-visible surface lives in `samverk.quotas`.
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
DEFAULT_USER_QUOTA_SETTING = "user_quota_default_bytes"
USER_QUOTA_SETTING_PREFIX = "user_quota_bytes:"


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
    user_usage_bytes: int | None = None
    user_quota_bytes: int | None = None
    blocked_by: str = "none"  # "none" | "repository" | "user"


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


def decide_user_quota(owner_display: str, full_name: str,
                      user_usage: int, user_quota: int | None,
                      incoming: int) -> tuple[bool, str]:
    """The pure per-user judgement (S-354): would this
    push keep the owner's repositories, taken together,
    within the owner's quota? Plain words either way."""
    if user_quota is None:
        return True, (
            f"{owner_display} has no user quota; their "
            f"repositories hold {user_usage} bytes in total.")
    if user_usage + incoming <= user_quota:
        return True, (
            f"{owner_display}'s repositories hold {user_usage} of "
            f"{user_quota} bytes; this push adds {incoming}.")
    return False, (
        f"User quota exceeded for {owner_display}: their "
        f"repositories hold {user_usage} bytes of their "
        f"{user_quota}-byte user quota, and this push to "
        f"{full_name} adds {incoming} bytes. Remove or shrink "
        "content in any of their repositories, or ask a site "
        "admin to raise the user quota.")


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

    # -- per-user quotas (S-354) --------------------------------
    def _user(self, owner):
        user = self._accounts.get_by_username(owner)
        if user is None:
            raise QuotaError("no_such_user", "No such account.")
        return user

    def user_usage_bytes(self, owner) -> int:
        """Every repository the owner holds, measured with
        the same S-058 walk the per-repo number uses."""
        total = 0
        for current in self._repos.list_for_owner(owner):
            path = self._repos.path_for(current.owner, current.name)
            total += measure_path(path).total_bytes
        return total

    def user_quota(self, owner) -> int | None:
        """The explicit per-user quota alone (None unset)."""
        user = self._user(owner)
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (USER_QUOTA_SETTING_PREFIX + user.username_lower,)).fetchone()
        return int(row["value"]) if row else None

    def default_user_quota(self) -> int | None:
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (DEFAULT_USER_QUOTA_SETTING,)).fetchone()
        return int(row["value"]) if row else None

    def effective_user_quota(self, owner) -> int | None:
        """Per-user quota wins; instance user default next;
        otherwise the user is unlimited."""
        per_user = self.user_quota(owner)
        return per_user if per_user is not None else self.default_user_quota()

    def _require_admin(self, actor_user_id: int):
        actor = self._accounts.get_by_id(actor_user_id)
        if actor is None:
            raise QuotaError("no_such_user", "No such account.")
        if not actor.is_admin:
            raise QuotaError(
                "permission_denied",
                "Only a site admin can set a user quota.")
        return actor

    def set_user_quota(self, actor_user_id: int, owner,
                       quota_bytes: int | None, *,
                       source_ip: str | None = None) -> int | None:
        """Set (or, with None, clear) one user's quota.
        Admins only; audit-logged `admin.settings.change`."""
        user = self._user(owner)
        actor = self._require_admin(actor_user_id)
        key = USER_QUOTA_SETTING_PREFIX + user.username_lower
        with self._conn:
            if quota_bytes is None:
                self._conn.execute(
                    "DELETE FROM settings WHERE key = ?", (key,))
            else:
                self._conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?)"
                    " ON CONFLICT(key) DO UPDATE SET"
                    " value = excluded.value",
                    (key, str(_validate_quota(quota_bytes))))
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="admin.settings.change", target_kind="user",
                target_id=user.username_lower, outcome="success",
                source_ip=source_ip,
                detail={"key": "user_quota_bytes",
                        "quota": quota_bytes})
        return self.effective_user_quota(owner)

    def set_default_user_quota(self, actor_user_id: int,
                               quota_bytes: int | None, *,
                               source_ip: str | None = None) -> int | None:
        """Set (or clear) the instance user default. Admins
        only; audit-logged `admin.settings.change`."""
        actor = self._require_admin(actor_user_id)
        with self._conn:
            if quota_bytes is None:
                self._conn.execute(
                    "DELETE FROM settings WHERE key = ?",
                    (DEFAULT_USER_QUOTA_SETTING,))
            else:
                self._conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?)"
                    " ON CONFLICT(key) DO UPDATE SET"
                    " value = excluded.value",
                    (DEFAULT_USER_QUOTA_SETTING,
                     str(_validate_quota(quota_bytes))))
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="admin.settings.change", target_kind="instance",
                target_id="quotas", outcome="success",
                source_ip=source_ip,
                detail={"key": DEFAULT_USER_QUOTA_SETTING,
                        "quota": quota_bytes})
        return self.default_user_quota()

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
        """Would accepting `incoming_bytes` keep the repo in
        quota -- and its owner within the user quota (S-354)?
        Both levels are judged at this one point, repo first."""
        current = self._repo(owner, repo)
        incoming = _validate_incoming(incoming_bytes)
        usage = self.usage_bytes(owner, repo)
        quota = self.effective_quota(owner, repo)
        user_usage = self.user_usage_bytes(owner)
        user_quota = self.effective_user_quota(owner)
        if quota is not None and usage + incoming > quota:
            return ReceiveDecision(
                allowed=False, full_name=current.full_name,
                usage_bytes=usage, quota_bytes=quota,
                incoming_bytes=incoming,
                message=(
                    f"Repository quota exceeded for {current.full_name}: "
                    f"it holds {usage} bytes of its {quota}-byte quota, "
                    f"and this push adds {incoming} bytes. "
                    "Remove or shrink content, or ask the repository's "
                    "owner or a site admin to raise the quota."),
                user_usage_bytes=user_usage,
                user_quota_bytes=user_quota, blocked_by="repository")
        user_ok, user_message = decide_user_quota(
            current.owner, current.full_name, user_usage,
            user_quota, incoming)
        if not user_ok:
            return ReceiveDecision(
                allowed=False, full_name=current.full_name,
                usage_bytes=usage, quota_bytes=quota,
                incoming_bytes=incoming, message=user_message,
                user_usage_bytes=user_usage,
                user_quota_bytes=user_quota, blocked_by="user")
        if quota is None and user_quota is None:
            message = (f"{current.full_name} has no quota; "
                       f"it currently holds {usage} bytes.")
        elif quota is None:
            message = user_message
        elif user_quota is None:
            message = (f"{current.full_name} holds {usage} of "
                       f"{quota} bytes; this push adds {incoming}.")
        else:
            message = (f"{current.full_name} holds {usage} of "
                       f"{quota} bytes; this push adds {incoming}. "
                       + user_message)
        return ReceiveDecision(
            allowed=True, full_name=current.full_name,
            usage_bytes=usage, quota_bytes=quota,
            incoming_bytes=incoming, message=message,
            user_usage_bytes=user_usage,
            user_quota_bytes=user_quota, blocked_by="none")

    def enforce_receive(self, owner, repo, incoming_bytes: int) -> ReceiveDecision:
        """The receive path's gate: returns the decision when the
        push fits, raises `QuotaError` carrying the plain refusal
        message when it does not — before any object is accepted."""
        decision = self.check_receive(owner, repo, incoming_bytes)
        if not decision.allowed:
            raise QuotaError("quota_exceeded", decision.message)
        return decision
