"""Account deletion (S-043).

Deletion is the most irreversible act an account can take, so
it is built as a process, not a button:

- **Inventory first.** `inventory(user_id)` counts everything
  the account holds across every store — sessions, keys,
  tokens, passkeys, recovery codes, profile, devices, linked
  identities and the rest — so the person sees, in numbers,
  exactly what the act will destroy *before* they confirm.
- **Typed confirmation.** The request must type the account's
  own username; anything else refuses and schedules nothing.
- **Sudo gate.** The request requires fresh re-authentication
  through the same fail-closed seam S-030/S-035 consume
  (S-036 supplies the real verifier); no verifier, no deletion.
- **Grace period.** A request sets the account to
  `pending_deletion` (login already refuses non-active
  accounts, S-027) and schedules execution `GRACE_SECONDS`
  (7 days) later. Inside grace, `cancel` restores the account
  whole — nothing has been destroyed yet.
- **Execution is the irreversible step**, and only it: after
  grace, `execute_due` / `finalize` deletes every per-user
  row across every table and the user row itself, in one
  transaction, and leaves the username tombstoned for 90 days
  (S-042's period) so the name cannot be instantly
  re-registered for impersonation. The audit log is *not*
  deleted — it is the instance's witness (study 35), and the
  request / cancel / execute steps are all audit-logged
  under S-043's taxonomy additions.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import TOMBSTONE_SECONDS, AccountStore
from .audit import AuditLog

GRACE_SECONDS = 7 * 24 * 3600

# Every per-user table execution must clear. The users row
# goes last; the audit log is deliberately absent (see above).
_USER_TABLES = (
    "sessions", "ssh_keys", "access_tokens",
    "fine_grained_tokens", "totp_credentials", "recovery_codes",
    "passkey_credentials", "passkey_challenges", "profiles",
    "known_devices", "signin_notifications", "sudo_grants",
    "email_verification_tokens", "password_reset_tokens",
    "external_identities", "account_suspensions",
    "account_deletions",
)


class DeletionError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class DeletionInventory:
    user_id: int
    username: str
    status: str
    counts: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.counts.values())


@dataclass(frozen=True)
class PendingDeletion:
    user_id: int
    requested_at: int
    scheduled_at: int


class AccountDeletion:
    def __init__(
        self,
        conn: sqlite3.Connection,
        accounts: AccountStore,
        audit: AuditLog | None = None,
        grace_seconds: int = GRACE_SECONDS,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._audit = audit
        self._grace = grace_seconds
        self._now = time_fn

    def _require_user(self, user_id: int):
        user = self._accounts.get_by_id(user_id)
        if user is None:
            raise DeletionError("no_such_user", "No such account.")
        return user

    def inventory(self, user_id: int) -> DeletionInventory:
        user = self._require_user(user_id)
        counts: dict[str, int] = {}
        for table in _USER_TABLES:
            if table == "account_deletions":
                continue
            # passkey_challenges.user_id is nullable; the count
            # is still this account's rows only.
            row = self._conn.execute(
                f"SELECT COUNT(*) AS c FROM {table} WHERE user_id = ?",
                (user_id,)).fetchone()
            counts[table] = int(row["c"])
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM username_tombstones"
            " WHERE user_id = ?", (user_id,)).fetchone()
        counts["username_tombstones"] = int(row["c"])
        return DeletionInventory(
            user_id=user.id, username=user.username,
            status=user.status, counts=counts)

    def pending_for(self, user_id: int) -> PendingDeletion | None:
        row = self._conn.execute(
            "SELECT * FROM account_deletions WHERE user_id = ?",
            (user_id,)).fetchone()
        if row is None:
            return None
        return PendingDeletion(
            user_id=row["user_id"], requested_at=row["requested_at"],
            scheduled_at=row["scheduled_at"])

    def request(
        self, user_id: int, typed_confirmation: object,
        reauth_verifier: Callable[[int], bool] | None = None,
        *, source_ip: str | None = None,
    ) -> PendingDeletion:
        user = self._require_user(user_id)
        if self.pending_for(user_id) is not None:
            raise DeletionError(
                "already_pending",
                "Deletion is already scheduled for this account.")
        if (not isinstance(typed_confirmation, str)
                or typed_confirmation.strip().lower()
                != user.username_lower):
            raise DeletionError(
                "confirmation_mismatch",
                "Type your username exactly to confirm deletion.")
        if reauth_verifier is None or not reauth_verifier(user_id):
            raise DeletionError(
                "sudo_required",
                "Deletion needs a fresh password confirmation; "
                "confirm and try again.")
        now = int(self._now())
        scheduled = now + self._grace
        with self._conn:
            self._conn.execute(
                "INSERT INTO account_deletions"
                " (user_id, requested_at, scheduled_at)"
                " VALUES (?, ?, ?)", (user_id, now, scheduled))
            self._conn.execute(
                "UPDATE users SET status = 'pending_deletion'"
                " WHERE id = ?", (user_id,))
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user_id,
                action="auth.deletion.request", target_kind="user",
                target_id=str(user_id), outcome="success",
                source_ip=source_ip, detail={"scheduled_at": scheduled})
        return PendingDeletion(user_id, now, scheduled)

    def cancel(self, user_id: int, *,
               source_ip: str | None = None) -> bool:
        if self.pending_for(user_id) is None:
            return False
        with self._conn:
            self._conn.execute(
                "DELETE FROM account_deletions WHERE user_id = ?",
                (user_id,))
            self._conn.execute(
                "UPDATE users SET status = 'active' WHERE id = ?"
                " AND status = 'pending_deletion'", (user_id,))
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user_id,
                action="auth.deletion.cancel", target_kind="user",
                target_id=str(user_id), outcome="success",
                source_ip=source_ip)
        return True

    def finalize(self, user_id: int, *,
                 source_ip: str | None = None) -> bool:
        """Execute one pending deletion whose grace has run
        out. Not due (or not pending) answers False and
        destroys nothing."""
        pending = self.pending_for(user_id)
        if pending is None or int(self._now()) < pending.scheduled_at:
            return False
        user = self._require_user(user_id)
        now = int(self._now())
        with self._conn:
            for table in _USER_TABLES:
                self._conn.execute(
                    f"DELETE FROM {table} WHERE user_id = ?",
                    (user_id,))
            self._conn.execute(
                "DELETE FROM username_tombstones WHERE user_id = ?",
                (user_id,))
            # Hold the name against instant impersonation.
            self._conn.execute(
                "INSERT INTO username_tombstones (old_lower,"
                " user_id, old_display, renamed_at, expires_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (user.username_lower, user_id, user.username,
                 now, now + TOMBSTONE_SECONDS))
            self._conn.execute(
                "DELETE FROM users WHERE id = ?", (user_id,))
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user_id,
                action="auth.deletion.execute", target_kind="user",
                target_id=str(user_id), outcome="success",
                source_ip=source_ip, detail={"username": user.username})
        return True

    def execute_due(self) -> list[int]:
        rows = self._conn.execute(
            "SELECT user_id FROM account_deletions"
            " WHERE scheduled_at <= ? ORDER BY user_id",
            (int(self._now()),)).fetchall()
        done = []
        for row in rows:
            if self.finalize(int(row["user_id"])):
                done.append(int(row["user_id"]))
        return done
