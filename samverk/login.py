"""Login and logout (S-027).

The password's one job (study 07 §2): buying a browser session.

- **Generic failure.** Every refusal — no such user, wrong
  password, account still pending, account suspended — returns
  the same `LoginFailed` with the same message ("Invalid
  username or password") and, internally, costs a password
  verification either way: an attempt on a nonexistent user
  verifies against a fixed decoy hash, so neither the answer
  nor its timing enumerates accounts (study 07 §3.4).
- **Throttling** is S-005's `LoginThrottle` keyed by the
  canonical username: failures delay, never lock; a success
  clears the account's failure state. A throttled attempt is
  refused before any password work and audited as a failure.
- **Upgrade on login:** a successful verify against an outdated
  hash transparently rehashes at current parameters (S-004).
- **Audit:** success is `auth.login.success`, every failure is
  `auth.login.failure` with the attempted name (study 35 §4's
  recorded caveat applies — the name attempted, never a
  password), logout is `auth.logout`.
- **Logout** revokes the session token itself (S-006
  tombstone): the cookie the user arrived with buys nothing
  afterwards. Logging out an unknown token is a quiet no-op —
  the end state the user wants already holds.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable

from .accounts import AccountStore
from .audit import AuditLog
from .passwords import hash_password, verify_and_upgrade
from .sessions import SessionStore
from .throttle import LoginThrottle

GENERIC_FAILURE = "Invalid username or password."

# A real scrypt hash of a password nobody has: verifying against
# it costs the same work as a real account, so timing cannot
# distinguish "no such user" from "wrong password".
_DECOY_HASH = hash_password("decoy password for timing only")


class LoginFailed(Exception):
    """The one and only login refusal a caller ever sees."""

    def __init__(self, retry_after_seconds: float = 0.0):
        super().__init__(GENERIC_FAILURE)
        self.retry_after_seconds = retry_after_seconds


class LoginService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        accounts: AccountStore,
        sessions: SessionStore,
        audit: AuditLog | None = None,
        throttle: LoginThrottle | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._sessions = sessions
        self._audit = audit
        self._throttle = throttle if throttle is not None else LoginThrottle()
        self._now = time_fn

    def _audit_failure(self, username: str, source_ip: str | None,
                       reason: str) -> None:
        if self._audit is not None:
            self._audit.append(
                actor_kind="anonymous", action="auth.login.failure",
                target_kind="user", outcome="denied",
                source_ip=source_ip,
                detail={"attempted_user": username, "reason": reason})

    def login(
        self, username: object, password: object,
        source_ip: str | None = None,
        device_label: str | None = None,
    ) -> str:
        """Verify credentials; on success return a fresh session
        token (S-006). Every failure raises LoginFailed with the
        generic message."""
        attempted = username.strip() if isinstance(username, str) else ""
        key = attempted.lower()
        candidate = password if isinstance(password, str) else ""

        wait = self._throttle.retry_after(key) if key else 0.0
        if wait > 0:
            self._audit_failure(attempted, source_ip, "throttled")
            raise LoginFailed(retry_after_seconds=wait)

        user = self._accounts.get_by_username(attempted) if attempted else None
        stored = (self._accounts.password_hash_for(user.id)
                  if user is not None else _DECOY_HASH)
        ok, upgrade = verify_and_upgrade(candidate, stored or _DECOY_HASH)

        if user is None or not ok:
            delay = self._throttle.record_failure(key or attempted)
            self._audit_failure(
                attempted, source_ip,
                "bad_credentials" if user is not None else "no_such_user")
            raise LoginFailed(retry_after_seconds=delay)
        if user.status != "active":
            delay = self._throttle.record_failure(key)
            self._audit_failure(attempted, source_ip, f"status_{user.status}")
            raise LoginFailed(retry_after_seconds=delay)

        if upgrade is not None:
            self._accounts.set_password_hash(user.id, upgrade)
        self._throttle.record_success(key)
        token = self._sessions.create(
            user.id, device_label=device_label, source_ip=source_ip)
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user.id,
                action="auth.login.success", target_kind="user",
                target_id=str(user.id), outcome="success",
                source_ip=source_ip, detail={"method": "password"})
        return token

    def logout(self, token: object, source_ip: str | None = None) -> bool:
        """Revoke the session this token names. Returns True when
        a live session was ended."""
        if not isinstance(token, str) or not token:
            return False
        user_id = self._sessions.authenticate(token)
        revoked = self._sessions.revoke(token)
        if revoked and self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user_id,
                action="auth.logout", target_kind="user",
                target_id=str(user_id) if user_id else None,
                outcome="success", source_ip=source_ip)
        return revoked

    def authenticate_session(self, token: object) -> int | None:
        """Resolve a session token to its user id (S-006 clocks
        and revocation enforced there)."""
        if not isinstance(token, str) or not token:
            return None
        return self._sessions.authenticate(token)
