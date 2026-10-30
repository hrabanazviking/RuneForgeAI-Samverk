"""Password change and reset (S-028) — study 07 §3.6 as code.

- **Change** requires the current password. It is the
  "someone may be in my account" remedy, so on success it
  **revokes every session** the account holds — the changer
  signs in again with the new password, and anyone else is
  simply out. Audited as `auth.password.change`.
- **Reset** is for when the current password is lost:
  - *By email, where mail is configured:* `request_reset`
    always answers the same way whether or not the account
    exists (no enumeration), and only an existing active
    account with an email actually gets a token — 256-bit,
    stored only as a SHA-256 hash (S-006 law), **single-use,
    expiring in one hour**, a fresh request retiring older ones.
  - *By operator, where mail is not configured:* the operator
    mints a token host-side (`issue_operator_reset`) and hands
    it over out of band; redemption is the same code path, and
    the audit row records `via: operator`.
  - Redemption validates the new password against S-025's
    policy *before* consuming the token, so a refused password
    does not burn the letter. On success the token is spent,
    the password is replaced, and **all sessions are revoked**.
    Audited as `auth.password.reset`.
- A wrong current password on change answers generically and
  changes nothing — no session dies, no hash moves.
"""

from __future__ import annotations

import base64
import hashlib
import os
import sqlite3
import time
from collections.abc import Callable

from .accounts import AccountStore, RegistrationError, validate_password
from .audit import AuditLog
from .passwords import hash_password, verify_password
from .sessions import SessionStore

RESET_TTL_SECONDS = 3600  # one hour, per study 07 §3.6
_TOKEN_BYTES = 32  # 256 bits

Mailer = Callable[[str, str], None]


class PasswordError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_token() -> str:
    return base64.urlsafe_b64encode(os.urandom(_TOKEN_BYTES)).decode("ascii")


class PasswordService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        accounts: AccountStore,
        sessions: SessionStore,
        audit: AuditLog | None = None,
        mailer: Mailer | None = None,
        ttl: int = RESET_TTL_SECONDS,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._sessions = sessions
        self._audit = audit
        self._mailer = mailer
        self._ttl = ttl
        self._now = time_fn

    # -- change ----------------------------------------------------
    def change_password(
        self, user_id: int, current_password: object,
        new_password: object, source_ip: str | None = None,
    ) -> int:
        """Change with proof of the current password; returns the
        number of sessions revoked (all of them)."""
        user = self._accounts.get_by_id(user_id)
        stored = (self._accounts.password_hash_for(user_id)
                  if user is not None else None)
        candidate = (current_password if isinstance(current_password, str)
                     else "")
        if user is None or stored is None or not verify_password(candidate, stored):
            raise PasswordError(
                "bad_current_password",
                "That current password is not correct.")
        try:
            new_password = validate_password(new_password, user.username)
        except RegistrationError as exc:
            raise PasswordError(exc.reason, str(exc)) from None
        self._accounts.set_password_hash(user.id, hash_password(new_password))
        revoked = self._sessions.revoke_all(user.id)
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user.id,
                action="auth.password.change", target_kind="user",
                target_id=str(user.id), outcome="success",
                source_ip=source_ip)
        return revoked

    # -- reset: issuance --------------------------------------------
    def _mint(self, user_id: int, via: str) -> str:
        now = int(self._now())
        token = _new_token()
        with self._conn:
            self._conn.execute(
                "UPDATE password_reset_tokens SET used_at = ?"
                " WHERE user_id = ? AND used_at IS NULL",
                (now, user_id))
            self._conn.execute(
                "INSERT INTO password_reset_tokens"
                " (user_id, token_hash, via, created_at, expires_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (user_id, _hash_token(token), via, now, now + self._ttl))
        return token

    def request_reset(
        self, identifier: object, source_ip: str | None = None,
    ) -> bool:
        """Ask for a reset letter. Always returns True — the
        answer never reveals whether an account exists. A letter
        is actually sent only for an existing, active account
        with an email, and only when a mailer is configured."""
        if not isinstance(identifier, str) or not identifier.strip():
            return True
        user = (self._accounts.get_by_username(identifier)
                or self._accounts.get_by_email(identifier))
        if (user is None or user.status != "active" or not user.email
                or self._mailer is None):
            return True
        token = self._mint(user.id, via="email")
        self._mailer(user.email, token)
        return True

    def issue_operator_reset(
        self, user_id: int, *, operator_id: int,
        source_ip: str | None = None,
    ) -> str:
        """The no-mail road: mint a token host-side and return it
        to the operator, who hands it over out of band. The raw
        token touches no database and no log."""
        user = self._accounts.get_by_id(user_id)
        if user is None:
            raise PasswordError("no_such_user", "No such account.")
        return self._mint(user.id, via="operator")

    # -- reset: redemption -------------------------------------------
    def reset_password(
        self, token: object, new_password: object,
        source_ip: str | None = None,
    ) -> int:
        """Redeem a reset token; returns the user id. Single-use,
        expiring; on success every session is revoked."""
        def fail() -> PasswordError:
            return PasswordError(
                "invalid_or_expired",
                "That reset link is invalid or has expired.")

        if not isinstance(token, str) or not token:
            raise fail()
        row = self._conn.execute(
            "SELECT id, user_id, via, expires_at, used_at"
            " FROM password_reset_tokens WHERE token_hash = ?",
            (_hash_token(token),)).fetchone()
        now = int(self._now())
        if row is None or row["used_at"] is not None or now >= row["expires_at"]:
            raise fail()
        user = self._accounts.get_by_id(row["user_id"])
        if user is None:
            raise fail()
        try:
            new_password = validate_password(new_password, user.username)
        except RegistrationError as exc:
            # A refused password does not burn the token.
            raise PasswordError(exc.reason, str(exc)) from None
        with self._conn:
            self._conn.execute(
                "UPDATE password_reset_tokens SET used_at = ?"
                " WHERE id = ?", (now, row["id"]))
        self._accounts.set_password_hash(user.id, hash_password(new_password))
        self._sessions.revoke_all(user.id)
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user.id,
                action="auth.password.reset", target_kind="user",
                target_id=str(user.id), outcome="success",
                source_ip=source_ip, detail={"via": row["via"]})
        return user.id
