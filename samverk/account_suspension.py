"""Account suspension (S-044).

Suspension is an admin act with a reason, a record, and a
way back — never a quiet deletion:

- **Admin only, reason required.** `suspend` demands an
  acting account with `is_admin`, a non-empty reason (kept
  on the record and in the audit detail), and refuses to
  suspend the admin's own account or an account that is not
  currently active.
- **Effect:** the account's status becomes `suspended`
  (login already refuses non-active accounts generically,
  S-027) and all its live sessions are revoked at once.
- **Content policy:** a suspended account's content is
  *hidden* — `is_content_visible` is the one seam surfaces
  consult — but nothing is deleted: profile, keys, tokens
  and every other row remain exactly where they were, so
  `unsuspend` restores the account whole.
- **Record:** every suspend/unsuspend lands in
  `account_suspensions` (migration 20) and in the audit log
  under S-044's `admin.user.suspend` / `admin.user.unsuspend`.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore
from .audit import AuditLog
from .sessions import SessionStore

REASON_MAX = 500


class SuspensionError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class SuspensionRecord:
    id: int
    user_id: int
    action: str          # suspend | unsuspend
    reason: str | None
    actor_id: int
    created_at: int


class AccountSuspension:
    def __init__(
        self,
        conn: sqlite3.Connection,
        accounts: AccountStore,
        sessions: SessionStore | None = None,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._sessions = sessions
        self._audit = audit
        self._now = time_fn

    def _require_admin(self, admin_id: int):
        admin = self._accounts.get_by_id(admin_id)
        if admin is None or not admin.is_admin:
            raise SuspensionError(
                "not_admin", "Only an instance admin can do that.")
        return admin

    def _require_user(self, user_id: int):
        user = self._accounts.get_by_id(user_id)
        if user is None:
            raise SuspensionError("no_such_user", "No such account.")
        return user

    def _clean_reason(self, reason: object, *, required: bool) -> str | None:
        if reason is None:
            if required:
                raise SuspensionError(
                    "reason_required", "A suspension needs a reason.")
            return None
        if not isinstance(reason, str) or not reason.strip():
            if required:
                raise SuspensionError(
                    "reason_required", "A suspension needs a reason.")
            return None
        text = reason.strip()
        if len(text) > REASON_MAX:
            raise SuspensionError(
                "reason_too_long", "That reason is too long.")
        return text

    def suspend(self, admin_id: int, user_id: int, reason: object,
                *, source_ip: str | None = None) -> SuspensionRecord:
        self._require_admin(admin_id)
        user = self._require_user(user_id)
        if admin_id == user_id:
            raise SuspensionError(
                "cannot_suspend_self",
                "An admin cannot suspend their own account.")
        if user.status != "active":
            raise SuspensionError(
                "not_active",
                f"Only an active account can be suspended "
                f"(this one is {user.status}).")
        text = self._clean_reason(reason, required=True)
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "UPDATE users SET status = 'suspended' WHERE id = ?",
                (user_id,))
            cur = self._conn.execute(
                "INSERT INTO account_suspensions"
                " (user_id, action, reason, actor_id, created_at)"
                " VALUES (?, 'suspend', ?, ?, ?)",
                (user_id, text, admin_id, now))
            record_id = int(cur.lastrowid)
        if self._sessions is not None:
            self._sessions.revoke_all(user_id)
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=admin_id,
                action="admin.user.suspend", target_kind="user",
                target_id=str(user_id), outcome="success",
                source_ip=source_ip, detail={"reason": text})
        return SuspensionRecord(record_id, user_id, "suspend",
                                text, admin_id, now)

    def unsuspend(self, admin_id: int, user_id: int,
                  reason: object = None,
                  *, source_ip: str | None = None) -> SuspensionRecord:
        self._require_admin(admin_id)
        user = self._require_user(user_id)
        if user.status != "suspended":
            raise SuspensionError(
                "not_suspended", "That account is not suspended.")
        text = self._clean_reason(reason, required=False)
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "UPDATE users SET status = 'active' WHERE id = ?",
                (user_id,))
            cur = self._conn.execute(
                "INSERT INTO account_suspensions"
                " (user_id, action, reason, actor_id, created_at)"
                " VALUES (?, 'unsuspend', ?, ?, ?)",
                (user_id, text, admin_id, now))
            record_id = int(cur.lastrowid)
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=admin_id,
                action="admin.user.unsuspend", target_kind="user",
                target_id=str(user_id), outcome="success",
                source_ip=source_ip,
                detail={"reason": text} if text else None)
        return SuspensionRecord(record_id, user_id, "unsuspend",
                                text, admin_id, now)

    def is_suspended(self, user_id: int) -> bool:
        user = self._accounts.get_by_id(user_id)
        return user is not None and user.status == "suspended"

    def is_content_visible(self, user_id: int) -> bool:
        """The content policy seam: suspended accounts' content
        is hidden; everyone else who exists is visible. The
        content itself is never touched by suspension."""
        user = self._accounts.get_by_id(user_id)
        return user is not None and user.status != "suspended"

    def history(self, user_id: int) -> list[SuspensionRecord]:
        rows = self._conn.execute(
            "SELECT * FROM account_suspensions WHERE user_id = ?"
            " ORDER BY id", (user_id,)).fetchall()
        return [SuspensionRecord(
            id=r["id"], user_id=r["user_id"], action=r["action"],
            reason=r["reason"], actor_id=r["actor_id"],
            created_at=r["created_at"]) for r in rows]

    def current_reason(self, user_id: int) -> str | None:
        if not self.is_suspended(user_id):
            return None
        hist = self.history(user_id)
        for rec in reversed(hist):
            if rec.action == "suspend":
                return rec.reason
        return None
