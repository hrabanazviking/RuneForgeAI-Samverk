"""Two-factor enforcement policy (S-038).

An instance may require two-factor for its administrators —
the accounts whose compromise costs the most. The policy's
shape is deliberately honest:

- **Scope today is the instance.** Organisation scopes are
  refused with a named reason (`org_scope_not_available`):
  organisations themselves land in a later part, and a policy
  engine that pretended to evaluate org adminship it cannot
  see would be a claim, not a control.
- **Grace period, honestly counted.** Turning the requirement
  on starts the grace clock *once* (re-saving the policy does
  not restart it — no perpetual grace by re-clicking). Inside
  grace, an admin without two-factor is **warned, not
  blocked**, and the warning names when the grace ends.
  After it, `is_blocked` answers True and login surfaces
  refuse until enrolment completes.
- **Satisfaction is a fact, not a promise:** an admin with a
  confirmed S-035 credential is compliant; everyone the
  policy does not name (non-admins, or any account while the
  policy is off) is simply outside it.
- The policy lives in the instance `settings` table (three
  keys, written together in one transaction) and every change
  is audited `admin.settings.change` with the key named —
  never silently.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore
from .audit import AuditLog
from .totp import TotpStore

DEFAULT_GRACE_SECONDS = 7 * 24 * 3600
_KEY_ON = "twofactor.require_admins"
_KEY_START = "twofactor.grace_started_at"
_KEY_GRACE = "twofactor.grace_seconds"


class PolicyError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class PolicyStatus:
    user_id: int
    is_admin: bool
    twofactor_enabled: bool
    required: bool        # the policy names this account
    compliant: bool       # not required, or two-factor is on
    in_grace: bool
    grace_ends_at: int | None
    blocked: bool
    warning: str | None   # honest words for the account, or None


class TwoFactorPolicy:
    def __init__(
        self,
        conn: sqlite3.Connection,
        accounts: AccountStore,
        totp: TotpStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._totp = totp
        self._audit = audit
        self._now = time_fn

    # -- storage ---------------------------------------------------
    def _get(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def _requirement(self) -> tuple[bool, int | None, int]:
        on = self._get(_KEY_ON) == "1"
        start = self._get(_KEY_START)
        grace = self._get(_KEY_GRACE)
        return (
            on,
            int(start) if start is not None else None,
            int(grace) if grace is not None else DEFAULT_GRACE_SECONDS,
        )

    # -- administration ---------------------------------------------
    def set_requirement(
        self,
        require_admins: bool,
        grace_seconds: int = DEFAULT_GRACE_SECONDS,
        *,
        scope: str = "instance",
        actor_id: int | None = None,
        source_ip: str | None = None,
    ) -> None:
        if scope != "instance":
            raise PolicyError(
                "org_scope_not_available",
                "Organisation two-factor policy lands with "
                "organisations themselves; only the instance "
                "scope exists yet.")
        if grace_seconds < 0:
            raise PolicyError("grace_invalid",
                              "A grace period cannot be negative.")
        on, start, _ = self._requirement()
        now = int(self._now())
        with self._conn:
            if require_admins:
                # The clock starts when the requirement first
                # turns on; re-saving never restarts it.
                started = start if (on and start is not None) else now
                rows = [(_KEY_ON, "1"), (_KEY_START, str(started)),
                        (_KEY_GRACE, str(grace_seconds))]
            else:
                rows = [(_KEY_ON, "0"), (_KEY_START, str(now)),
                        (_KEY_GRACE, str(grace_seconds))]
            self._conn.executemany(
                "INSERT INTO settings (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                rows)
        if self._audit is not None:
            self._audit.append(
                actor_kind="user" if actor_id else "operator",
                actor_id=actor_id,
                action="admin.settings.change", target_kind="instance",
                target_id="twofactor", outcome="success",
                source_ip=source_ip,
                detail={"key": _KEY_ON,
                        "to": "1" if require_admins else "0"})

    # -- evaluation ---------------------------------------------------
    def status_for(self, user_id: int) -> PolicyStatus:
        user = self._accounts.get_by_id(user_id)
        if user is None:
            raise PolicyError("no_such_user", "No such account.")
        enabled = self._totp.is_enabled(user.id)
        on, start, grace = self._requirement()
        required = bool(on and user.is_admin)
        compliant = (not required) or enabled
        grace_ends = (start + grace) if (required and start is not None) else None
        now = int(self._now())
        in_grace = bool(
            required and not enabled and grace_ends is not None
            and now < grace_ends)
        blocked = bool(required and not enabled and not in_grace)
        warning = None
        if required and not enabled:
            if in_grace:
                days = max(1, (grace_ends - now + 86399) // 86400)  # type: ignore[operator]
                warning = (
                    "This instance requires two-factor "
                    "authentication for administrators. Yours is "
                    f"not on yet; you have {days} day(s) of grace "
                    "left to enable it before sign-in is refused.")
            else:
                warning = (
                    "This instance requires two-factor "
                    "authentication for administrators and the "
                    "grace period has ended. Enable two-factor "
                    "to continue.")
        return PolicyStatus(
            user_id=user.id, is_admin=user.is_admin,
            twofactor_enabled=enabled, required=required,
            compliant=compliant, in_grace=in_grace,
            grace_ends_at=grace_ends if required else None,
            blocked=blocked, warning=warning)

    def is_blocked(self, user_id: int) -> bool:
        return self.status_for(user_id).blocked
