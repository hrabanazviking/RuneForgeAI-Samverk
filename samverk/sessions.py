"""Session tokens (S-006) — study 07 §4 as code.

- **Shape:** 256 bits from the OS CSPRNG, URL-safe encoded for the
  cookie. Only its SHA-256 hash is stored: high-entropy random values
  need no slow KDF (there is no dictionary to slow down), and a stolen
  database therefore contains **no usable session** — the slice's
  acceptance test presents the stored hashes themselves as tokens and
  is refused.
- **Two clocks:** absolute expiry (default 30 days from creation, no
  matter how active) and idle expiry (default 7 days without a
  request). Both are hard bounds, not preferences.
- **Revocation** is a tombstone: instant and total. `revoke_all` is
  the "someone may be in my account" remedy and must actually evict.
- **Commit-before-answer** (study 42): a session row is committed
  before its token is handed to the caller, so the very next request
  can rely on it.
"""

from __future__ import annotations

import base64
import hashlib
import os
import sqlite3
import time
from collections.abc import Callable

ABSOLUTE_TTL_SECONDS = 30 * 24 * 3600
IDLE_TTL_SECONDS = 7 * 24 * 3600
_TOKEN_BYTES = 32  # 256 bits


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_token() -> str:
    return base64.urlsafe_b64encode(os.urandom(_TOKEN_BYTES)).decode("ascii")


class SessionStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        absolute_ttl: int = ABSOLUTE_TTL_SECONDS,
        idle_ttl: int = IDLE_TTL_SECONDS,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._absolute = absolute_ttl
        self._idle = idle_ttl
        self._now = time_fn

    def create(self, user_id: int) -> str:
        """Create a session; return the raw token (shown once)."""
        now = int(self._now())
        token = _new_token()
        with self._conn:  # committed before the token is answered with
            self._conn.execute(
                "INSERT INTO sessions (user_id, token_hash, created_at,"
                " last_seen_at, absolute_expires_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, _hash_token(token), now, now, now + self._absolute),
            )
        return token

    def authenticate(self, token: str) -> int | None:
        """Resolve a token to its user id, enforcing both clocks and
        revocation; a successful check touches last_seen_at."""
        now = int(self._now())
        row = self._conn.execute(
            "SELECT id, user_id, last_seen_at, absolute_expires_at, revoked"
            " FROM sessions WHERE token_hash = ?",
            (_hash_token(token),),
        ).fetchone()
        if row is None or row["revoked"]:
            return None
        if now >= row["absolute_expires_at"]:
            return None
        if now - row["last_seen_at"] > self._idle:
            return None
        with self._conn:
            self._conn.execute(
                "UPDATE sessions SET last_seen_at = ? WHERE id = ?",
                (now, row["id"]),
            )
        return row["user_id"]

    def revoke(self, token: str) -> bool:
        with self._conn:
            cur = self._conn.execute(
                "UPDATE sessions SET revoked = 1 WHERE token_hash = ?",
                (_hash_token(token),),
            )
        return cur.rowcount > 0

    def revoke_all(self, user_id: int) -> int:
        with self._conn:
            cur = self._conn.execute(
                "UPDATE sessions SET revoked = 1 WHERE user_id = ? AND revoked = 0",
                (user_id,),
            )
        return cur.rowcount
