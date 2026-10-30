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
from dataclasses import dataclass

ABSOLUTE_TTL_SECONDS = 30 * 24 * 3600
IDLE_TTL_SECONDS = 7 * 24 * 3600
_TOKEN_BYTES = 32  # 256 bits


@dataclass(frozen=True)
class SessionInfo:
    """One session as its owner may see it (S-040). The token
    and its hash are never part of this view."""
    id: int
    user_id: int
    created_at: int
    last_seen_at: int
    absolute_expires_at: int
    revoked: bool
    device_label: str | None
    source_ip: str | None


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

    @property
    def idle_ttl(self) -> int:
        return self._idle

    @property
    def absolute_ttl(self) -> int:
        return self._absolute

    def create(self, user_id: int, device_label: str | None = None,
               source_ip: str | None = None) -> str:
        """Create a session; return the raw token (shown once).
        The device label and source address (S-040) are the
        owner's recognition aids in the session list."""
        now = int(self._now())
        token = _new_token()
        with self._conn:  # committed before the token is answered with
            self._conn.execute(
                "INSERT INTO sessions (user_id, token_hash, created_at,"
                " last_seen_at, absolute_expires_at, device_label,"
                " source_ip) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, _hash_token(token), now, now, now + self._absolute,
                 device_label, source_ip),
            )
        return token

    def list_for_user(self, user_id: int) -> list[SessionInfo]:
        """Every session the account has, oldest first —
        revoked and expired rows included, so the management
        page can show honest status words (S-040)."""
        rows = self._conn.execute(
            "SELECT id, user_id, created_at, last_seen_at,"
            " absolute_expires_at, revoked, device_label, source_ip"
            " FROM sessions WHERE user_id = ? ORDER BY id",
            (user_id,)).fetchall()
        return [SessionInfo(
            id=r["id"], user_id=r["user_id"],
            created_at=r["created_at"], last_seen_at=r["last_seen_at"],
            absolute_expires_at=r["absolute_expires_at"],
            revoked=bool(r["revoked"]), device_label=r["device_label"],
            source_ip=r["source_ip"]) for r in rows]

    def id_for_token(self, token: str) -> int | None:
        row = self._conn.execute(
            "SELECT id FROM sessions WHERE token_hash = ?",
            (_hash_token(token),)).fetchone()
        return int(row["id"]) if row else None

    def revoke_by_id(self, user_id: int, session_id: int) -> bool:
        """Tombstone one session, owner-scoped in the query
        itself: another account's id answers False and changes
        nothing. True only when this call did the revoking."""
        with self._conn:
            cur = self._conn.execute(
                "UPDATE sessions SET revoked = 1 WHERE id = ?"
                " AND user_id = ? AND revoked = 0",
                (session_id, user_id),
            )
        return cur.rowcount > 0

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
        """Tombstone a live session; True only when this call did
        the revoking (an already-revoked token reports False — a
        double logout is a no-op, found by the S-027 battery)."""
        with self._conn:
            cur = self._conn.execute(
                "UPDATE sessions SET revoked = 1 WHERE token_hash = ?"
                " AND revoked = 0",
                (_hash_token(token),),
            )
        return cur.rowcount > 0

    def revoke_all(self, user_id: int,
                   except_id: int | None = None) -> int:
        """Tombstone every live session of the account; with
        `except_id`, that one session (the owner's current
        one, S-040) survives the sweep."""
        with self._conn:
            if except_id is None:
                cur = self._conn.execute(
                    "UPDATE sessions SET revoked = 1"
                    " WHERE user_id = ? AND revoked = 0",
                    (user_id,),
                )
            else:
                cur = self._conn.execute(
                    "UPDATE sessions SET revoked = 1"
                    " WHERE user_id = ? AND revoked = 0 AND id != ?",
                    (user_id, except_id),
                )
        return cur.rowcount
