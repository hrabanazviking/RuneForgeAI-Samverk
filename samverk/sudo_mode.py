"""Sudo mode (S-036) — fresh re-authentication for sensitive acts.

Sensitive actions (SSH/token creation, 2FA changes, deletion)
must not ride on a session that may be hours old and possibly
borrowed: the account's *password*, re-entered, buys a short
freshness window, and only inside that window do those acts
proceed.

- **Grant:** `grant(user_id, password, session_token)` verifies
  the password against S-004's stored hash (with S-027's
  decoy-hash timing discipline for unknown accounts, and the
  upgrade-on-success persistence login uses) and records a
  grant expiring `WINDOW_SECONDS` (15 minutes) later. A wrong
  password raises the same generic `SudoFailed` as an unknown
  account and records nothing.
- **Binding:** a grant belongs to one *session*, keyed by the
  session token's SHA-256 — the raw token never touches this
  table (the S-006 law), so a stolen grant row re-authenticates
  no one, and freshness on one device says nothing about
  another. Expired grants answer False and are swept on sight.
- **The seam, fulfilled:** `as_verifier(session_token)` returns
  exactly the `Callable[[int], bool]` that S-030's SSH keys,
  S-035's TOTP enrolment, and later sensitive stores take as
  their `reauth_verifier` — failing closed when no grant
  exists. This slice's battery exercises the real verifier
  through S-030's key-add gate, as S-030 promised.
- `require_fresh` is the raising form for surfaces that prefer
  an exception; `revoke` ends a grant early (logout's natural
  companion, though session revocation already orphans it).
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Callable

from .accounts import AccountStore
from .passwords import hash_password, verify_and_upgrade

WINDOW_SECONDS = 15 * 60

# A real scrypt hash of a password no account has, so verifying
# an unknown account costs the same work as a real one (the
# S-027 decoy discipline).
_DECOY_HASH = hash_password("decoy password for timing only")


class SudoFailed(Exception):
    """The one refusal: generic, whatever the cause."""


class SudoRequiredError(Exception):
    """Raised by require_fresh when no live grant exists."""


def _session_hash(session_token: str) -> str:
    return hashlib.sha256(session_token.encode("utf-8")).hexdigest()


class SudoMode:
    def __init__(
        self,
        conn: sqlite3.Connection,
        accounts: AccountStore,
        window_seconds: int = WINDOW_SECONDS,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._window = window_seconds
        self._now = time_fn

    def grant(self, user_id: int, password: object,
              session_token: str) -> int:
        """Verify the password and open the window for this
        session; returns the expiry timestamp. Any failure is
        the generic SudoFailed and grants nothing."""
        if not isinstance(password, str) or not session_token:
            raise SudoFailed("Password confirmation failed.")
        stored = self._accounts.password_hash_for(user_id)
        ok, upgrade = verify_and_upgrade(
            password, stored if stored is not None else _DECOY_HASH)
        if stored is None or not ok:
            raise SudoFailed("Password confirmation failed.")
        if upgrade is not None:
            self._accounts.set_password_hash(user_id, upgrade)
        now = int(self._now())
        expires = now + self._window
        with self._conn:  # committed before the grant is answered with
            self._conn.execute(
                "INSERT INTO sudo_grants (user_id, session_hash,"
                " granted_at, expires_at) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(user_id, session_hash) DO UPDATE SET"
                " granted_at = excluded.granted_at,"
                " expires_at = excluded.expires_at",
                (user_id, _session_hash(session_token), now, expires))
        return expires

    def expires_at(self, user_id: int,
                   session_token: str) -> int | None:
        if not session_token:
            return None
        row = self._conn.execute(
            "SELECT expires_at FROM sudo_grants"
            " WHERE user_id = ? AND session_hash = ?",
            (user_id, _session_hash(session_token))).fetchone()
        if row is None:
            return None
        if int(self._now()) >= row["expires_at"]:
            self.revoke(user_id, session_token)
            return None
        return row["expires_at"]

    def is_fresh(self, user_id: int, session_token: str) -> bool:
        return self.expires_at(user_id, session_token) is not None

    def require_fresh(self, user_id: int, session_token: str) -> None:
        if not self.is_fresh(user_id, session_token):
            raise SudoRequiredError(
                "This action needs a fresh password confirmation; "
                "confirm and try again.")

    def revoke(self, user_id: int, session_token: str) -> bool:
        if not session_token:
            return False
        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM sudo_grants"
                " WHERE user_id = ? AND session_hash = ?",
                (user_id, _session_hash(session_token)))
        return cur.rowcount > 0

    def as_verifier(self, session_token: str) -> Callable[[int], bool]:
        """The re-auth seam every sensitive store consumes:
        answers 'is this user freshly re-authenticated *on this
        session*?' — and nothing without a live grant."""
        def verify(user_id: int) -> bool:
            return self.is_fresh(user_id, session_token)
        return verify
