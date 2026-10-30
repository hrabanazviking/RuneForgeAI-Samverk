"""Email verification (S-026).

Two roads to a verified account, chosen by what the instance
actually has:

1. **Token flow — when SMTP is configured.** `request_verification`
   mints a 256-bit token, stores only its SHA-256 hash (the S-006
   law: a stolen database holds no usable token), hands the raw
   token to the operator's mailer seam exactly once, and
   `verify(token)` redeems it: single-use, expiring (24 h), and
   on success the account's email is marked verified and a
   `pending_verification` account becomes active.
2. **Operator-approval path — when it is not.** With no mailer,
   no token is minted or pretended: the account waits
   `pending_approval` and `approve_user` is the operator's word,
   recorded in the audit log as `admin.user.approve` with the
   operator's id. An account with no email at all can only ever
   take this road — there is nothing to send a token to.

Both roads are audit-logged: verification success and failure
are `auth.email.verify` (outcome distinguishes), approval is
`admin.user.approve`. A failed redemption answers generically —
invalid, expired, and already-used tokens are indistinguishable
to the caller, so the endpoint cannot be used to probe which
tokens ever existed.

The mailer is a seam, not an SMTP client: a callable taking
``(email_address, raw_token)``. Wiring a real SMTP transport is
an operator/integration concern (Part XVIII installs); this
slice owns the token law both roads stand on.
"""

from __future__ import annotations

import base64
import hashlib
import os
import sqlite3
import time
from collections.abc import Callable

from .accounts import AccountStore, User
from .audit import AuditLog

VERIFICATION_TTL_SECONDS = 24 * 3600
_TOKEN_BYTES = 32  # 256 bits

Mailer = Callable[[str, str], None]


class VerificationError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_token() -> str:
    return base64.urlsafe_b64encode(os.urandom(_TOKEN_BYTES)).decode("ascii")


class EmailVerification:
    def __init__(
        self,
        conn: sqlite3.Connection,
        accounts: AccountStore,
        audit: AuditLog | None = None,
        mailer: Mailer | None = None,
        ttl: int = VERIFICATION_TTL_SECONDS,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._audit = audit
        self._mailer = mailer
        self._ttl = ttl
        self._now = time_fn

    @property
    def smtp_configured(self) -> bool:
        return self._mailer is not None

    def request_verification(
        self, user_id: int, source_ip: str | None = None,
    ) -> bool:
        """Start the token flow. Returns True when a token was
        sent; False when this instance has no mailer and the
        account must take the operator-approval road instead."""
        user = self._accounts.get_by_id(user_id)
        if user is None:
            raise VerificationError("no_such_user", "No such account.")
        if user.email is None:
            raise VerificationError(
                "no_email",
                "This account has no email address to verify; an "
                "operator must approve it instead.")
        if self._mailer is None:
            if user.status == "pending_verification":
                self._accounts.set_status(user.id, "pending_approval")
            return False
        now = int(self._now())
        token = _new_token()
        with self._conn:
            # A fresh request retires every earlier unused token:
            # only the newest letter counts.
            self._conn.execute(
                "UPDATE email_verification_tokens SET used_at = ?"
                " WHERE user_id = ? AND used_at IS NULL",
                (now, user.id))
            self._conn.execute(
                "INSERT INTO email_verification_tokens"
                " (user_id, token_hash, created_at, expires_at)"
                " VALUES (?, ?, ?, ?)",
                (user.id, _hash_token(token), now, now + self._ttl))
        self._mailer(user.email, token)
        return True

    def verify(self, token: object, source_ip: str | None = None) -> User:
        """Redeem a token: single-use, expiring, hashed at rest."""
        def fail(user_id: int | None = None) -> VerificationError:
            if self._audit is not None:
                self._audit.append(
                    actor_kind="anonymous", action="auth.email.verify",
                    target_kind="user",
                    target_id=str(user_id) if user_id else None,
                    outcome="denied", source_ip=source_ip,
                    detail={"reason": "invalid_or_expired"})
            return VerificationError(
                "invalid_or_expired",
                "That verification link is invalid or has expired.")

        if not isinstance(token, str) or not token:
            raise fail()
        row = self._conn.execute(
            "SELECT id, user_id, expires_at, used_at"
            " FROM email_verification_tokens WHERE token_hash = ?",
            (_hash_token(token),)).fetchone()
        now = int(self._now())
        if row is None or row["used_at"] is not None or now >= row["expires_at"]:
            raise fail(row["user_id"] if row else None)
        with self._conn:
            self._conn.execute(
                "UPDATE email_verification_tokens SET used_at = ?"
                " WHERE id = ?", (now, row["id"]))
        self._accounts.set_email_verified(row["user_id"], True)
        user = self._accounts.get_by_id(row["user_id"])
        assert user is not None
        if user.status == "pending_verification":
            self._accounts.set_status(user.id, "active")
            user = self._accounts.get_by_id(user.id)
            assert user is not None
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user.id,
                action="auth.email.verify", target_kind="user",
                target_id=str(user.id), outcome="success",
                source_ip=source_ip)
        return user

    def approve_user(
        self, user_id: int, *, operator_id: int,
        source_ip: str | None = None,
    ) -> User:
        """The operator road: approve a pending account. Audited
        as an admin act, with the operator named as the actor."""
        user = self._accounts.get_by_id(user_id)
        if user is None:
            raise VerificationError("no_such_user", "No such account.")
        if user.status == "active":
            raise VerificationError(
                "already_active", "That account is already active.")
        self._accounts.set_status(user.id, "active")
        if self._audit is not None:
            self._audit.append(
                actor_kind="admin", actor_id=operator_id,
                action="admin.user.approve", target_kind="user",
                target_id=str(user.id), outcome="success",
                source_ip=source_ip,
                detail={"from_status": user.status})
        approved = self._accounts.get_by_id(user.id)
        assert approved is not None
        return approved
