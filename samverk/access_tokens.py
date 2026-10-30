"""Personal access tokens — classic shape (S-032).

Study 09's subject, in the shape users know from classic tokens
on other forges, designed as our own:

- **Shape:** ``svk_`` + 256 bits from the OS CSPRNG, URL-safe.
  The prefix names the kind at a glance (and in a leaked log or
  a secret scanner's pattern, S-289) without revealing anything.
  Only the token's SHA-256 hash is stored — the S-006 law — so a
  stolen database contains **no usable token**: the acceptance
  battery presents the stored hashes themselves and is refused,
  and the raw token appears nowhere in the DB file.
- **Shown once.** Creation returns the raw token exactly once,
  to its creator; afterwards only its public facts exist: title,
  an identifying prefix, scopes, creation, expiry, last-used.
- **Scopes are required and closed.** A token is minted for an
  explicit, non-empty set drawn from ``CLASSIC_SCOPES``; unknown
  scopes are refused, never stored and ignored. Write scopes
  imply their read sibling (``repo:write`` answers a
  ``repo:read`` question) — ``token_allows`` is the one place
  that implication lives. Fine-grained, per-repository tokens
  are S-033's separate shape; this slice is the classic one.
- **Expiry is required.** Every token carries an expiry, at
  most one year out; a token with no expiry, a past expiry, or
  an expiry beyond the cap is refused at minting, not warned
  about. An expired token authenticates to nothing.
- **Revocation** is a tombstone, owner-only, audit-logged
  (``auth.token.create`` / ``auth.token.revoke`` — both already
  in the frozen taxonomy, and their ``detail`` carries the token
  id and scopes, never the token).
"""

from __future__ import annotations

import base64
import hashlib
import os
import sqlite3
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .accounts import AccountStore
from .audit import AuditLog

TOKEN_PREFIX = "svk_"
_TOKEN_BYTES = 32  # 256 bits
MAX_EXPIRY_SECONDS = 366 * 24 * 3600
TITLE_MAX = 100
_PREFIX_CHARS = 12  # "svk_" + 8 random chars: identifies, never authenticates

CLASSIC_SCOPES = frozenset({
    "repo:read",
    "repo:write",
    "issues:read",
    "issues:write",
    "profile:read",
    "profile:write",
})

# A write scope answers its read sibling's question.
_SCOPE_IMPLIES = {
    "repo:write": frozenset({"repo:read"}),
    "issues:write": frozenset({"issues:read"}),
    "profile:write": frozenset({"profile:read"}),
}


class AccessTokenError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class AccessToken:
    id: int
    user_id: int
    title: str
    prefix: str
    scopes: frozenset[str]
    created_at: int
    expires_at: int
    last_used_at: int | None
    revoked: bool


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_token() -> str:
    raw = base64.urlsafe_b64encode(os.urandom(_TOKEN_BYTES)).decode("ascii")
    return TOKEN_PREFIX + raw.rstrip("=")


def token_allows(token: AccessToken, scope: str) -> bool:
    """The one scope-implication seam: a token allows `scope`
    when it holds it directly or holds a write scope that
    implies it."""
    if scope in token.scopes:
        return True
    return any(scope in _SCOPE_IMPLIES.get(held, frozenset())
               for held in token.scopes)


def _validate_scopes(scopes: object) -> frozenset[str]:
    if isinstance(scopes, (str, bytes)) or not isinstance(scopes, Iterable):
        raise AccessTokenError(
            "scopes_required",
            "Choose at least one scope for the token.")
    chosen = frozenset(scopes)  # type: ignore[arg-type]
    if not chosen:
        raise AccessTokenError(
            "scopes_required",
            "Choose at least one scope for the token.")
    unknown = chosen - CLASSIC_SCOPES
    if unknown:
        raise AccessTokenError(
            "scope_unknown",
            "Unknown scope(s): " + ", ".join(sorted(unknown)) + ".")
    return chosen


class AccessTokenStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        accounts: AccountStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._audit = audit
        self._now = time_fn

    def _require_user(self, user_id: int):
        user = self._accounts.get_by_id(user_id)
        if user is None:
            raise AccessTokenError("no_such_user", "No such account.")
        return user

    def create_token(
        self, user_id: int, title: object, scopes: object,
        expires_at: object, source_ip: str | None = None,
    ) -> tuple[AccessToken, str]:
        """Mint a token; return (public facts, raw token).

        The raw token is returned here and nowhere else, ever —
        it is shown once, at creation, to its creator.
        """
        user = self._require_user(user_id)
        if not isinstance(title, str) or not title.strip():
            raise AccessTokenError("title_required", "Give the token a title.")
        title_clean = title.strip()
        if len(title_clean) > TITLE_MAX or any(
                ord(c) < 0x20 or ord(c) == 0x7F for c in title_clean):
            raise AccessTokenError("title_invalid", "That title is not valid.")
        scope_set = _validate_scopes(scopes)
        now = int(self._now())
        if not isinstance(expires_at, (int, float)) or isinstance(expires_at, bool):
            raise AccessTokenError(
                "expiry_required",
                "Every token needs an expiry date; choose one.")
        expiry = int(expires_at)  # type: ignore[arg-type]
        if expiry <= now:
            raise AccessTokenError(
                "expiry_in_past", "That expiry is already past.")
        if expiry > now + MAX_EXPIRY_SECONDS:
            raise AccessTokenError(
                "expiry_too_far",
                "A token may live at most one year; choose a nearer expiry.")
        raw = _new_token()
        with self._conn:  # committed before the token is answered with
            cur = self._conn.execute(
                "INSERT INTO access_tokens (user_id, title, token_hash,"
                " prefix, scopes, created_at, expires_at, last_used_at,"
                " revoked) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 0)",
                (user.id, title_clean, _hash_token(raw),
                 raw[:_PREFIX_CHARS], ",".join(sorted(scope_set)),
                 now, expiry))
        token = self.get_token(int(cur.lastrowid))
        assert token is not None
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user.id,
                action="auth.token.create", target_kind="user",
                target_id=str(user.id), outcome="success",
                source_ip=source_ip,
                detail={"token_id": token.id,
                        "scopes": sorted(scope_set)})
        return token, raw

    def get_token(self, token_id: int) -> AccessToken | None:
        row = self._conn.execute(
            "SELECT * FROM access_tokens WHERE id = ?",
            (token_id,)).fetchone()
        return _row_to_token(row) if row else None

    def list_tokens(self, user_id: int) -> list[AccessToken]:
        self._require_user(user_id)
        rows = self._conn.execute(
            "SELECT * FROM access_tokens WHERE user_id = ? ORDER BY id",
            (user_id,)).fetchall()
        return [_row_to_token(r) for r in rows]

    def authenticate(self, presented: object) -> AccessToken | None:
        """Resolve a presented raw token to its public facts,
        enforcing revocation and expiry; a successful check
        stamps last-used. Anything malformed, unknown, revoked,
        or expired authenticates to nothing — indistinguishably."""
        if not isinstance(presented, str) or not presented.startswith(TOKEN_PREFIX):
            return None
        now = int(self._now())
        row = self._conn.execute(
            "SELECT * FROM access_tokens WHERE token_hash = ?",
            (_hash_token(presented),)).fetchone()
        if row is None or row["revoked"]:
            return None
        if now >= row["expires_at"]:
            return None
        with self._conn:
            self._conn.execute(
                "UPDATE access_tokens SET last_used_at = ? WHERE id = ?",
                (now, row["id"]))
        fresh = self.get_token(row["id"])
        return fresh

    def revoke_token(
        self, user_id: int, token_id: int,
        source_ip: str | None = None,
    ) -> bool:
        """Owner-only revocation tombstone. Returns False when
        there is no live token with that id *on this account* —
        another account's token is indistinguishable from a
        missing one, and an already-revoked token is a no-op."""
        user = self._require_user(user_id)
        with self._conn:
            cur = self._conn.execute(
                "UPDATE access_tokens SET revoked = 1"
                " WHERE id = ? AND user_id = ? AND revoked = 0",
                (token_id, user.id))
        if cur.rowcount == 0:
            return False
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user.id,
                action="auth.token.revoke", target_kind="user",
                target_id=str(user.id), outcome="success",
                source_ip=source_ip, detail={"token_id": token_id})
        return True


def _row_to_token(row: sqlite3.Row) -> AccessToken:
    return AccessToken(
        id=row["id"], user_id=row["user_id"], title=row["title"],
        prefix=row["prefix"],
        scopes=frozenset(row["scopes"].split(",")) if row["scopes"] else frozenset(),
        created_at=row["created_at"], expires_at=row["expires_at"],
        last_used_at=row["last_used_at"], revoked=bool(row["revoked"]))
