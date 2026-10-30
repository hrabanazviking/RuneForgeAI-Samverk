"""Recovery codes (S-037) — the sovereign way back in.

When the authenticator is lost, recovery codes are the
difference between an owner locked out of their own instance
and an owner with a paper key. The law:

- **A set is ten codes**, each ten characters from an
  unambiguous alphabet (no 0/O, 1/I/L — a code read aloud or
  copied from paper must not be guessable-ambiguous),
  displayed grouped `XXXXX-XXXXX`, drawn from the CSPRNG.
- **Shown once, stored hashed.** Generation returns the
  plaintext set exactly once; the database holds only
  SHA-256 hashes (a code is high-entropy, so no slow KDF is
  needed — the S-006 law). The DB-leak test sweeps the file
  for every plaintext code.
- **Single-use.** Redemption stamps `used_at`; the same code
  presented again — by anyone — answers the same generic
  False as a wrong code.
- **Regeneration invalidates the old set, loudly.** Generating
  deletes every prior code (spent or not) inside the same
  transaction that mints the new set, and the result reports
  how many codes died, so the surface can tell the owner in
  plain words: *your old codes no longer work*. Both the
  generation (count + invalidated count, never the codes)
  and each redemption are audit-logged (S-037's append-only
  taxonomy additions `auth.recovery.generate` /
  `auth.recovery.use`).
- **Gates:** a set exists only for an account with two-factor
  actually enabled (S-035), and generating one is a sudo-mode
  act through the standing re-auth seam, failing closed.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore
from .audit import AuditLog
from .totp import TotpStore

CODES_PER_SET = 10
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_CHARS = 10


class RecoveryError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class GeneratedSet:
    codes: tuple[str, ...]   # plaintext, shown once
    invalidated: int         # how many old codes died for this set


def _new_code() -> str:
    raw = "".join(secrets.choice(_CODE_ALPHABET)
                  for _ in range(_CODE_CHARS))
    return f"{raw[:5]}-{raw[5:]}"


def normalise_code(code: object) -> str | None:
    if not isinstance(code, str):
        return None
    cleaned = code.replace("-", "").replace(" ", "").upper()
    if len(cleaned) != _CODE_CHARS or any(
            c not in _CODE_ALPHABET for c in cleaned):
        return None
    return cleaned


def _hash_code(normalised: str) -> str:
    return hashlib.sha256(normalised.encode("ascii")).hexdigest()


class RecoveryCodeStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        accounts: AccountStore,
        totp: TotpStore,
        audit: AuditLog | None = None,
        reauth_verifier: Callable[[int], bool] | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._totp = totp
        self._audit = audit
        self._reauth = reauth_verifier
        self._now = time_fn

    def generate(self, user_id: int,
                 source_ip: str | None = None) -> GeneratedSet:
        """Mint a fresh set, invalidating the old one loudly.
        Sudo-gated; requires confirmed two-factor."""
        user = self._accounts.get_by_id(user_id)
        if user is None:
            raise RecoveryError("no_such_user", "No such account.")
        if self._reauth is None or not self._reauth(user.id):
            raise RecoveryError(
                "sudo_required",
                "Generating recovery codes needs a fresh password "
                "confirmation; confirm and try again.")
        if not self._totp.is_enabled(user.id):
            raise RecoveryError(
                "twofactor_required",
                "Recovery codes exist to guard two-factor; enable "
                "two-factor first.")
        codes = tuple(_new_code() for _ in range(CODES_PER_SET))
        now = int(self._now())
        with self._conn:  # old set dies and new set lands together
            cur = self._conn.execute(
                "DELETE FROM recovery_codes WHERE user_id = ?",
                (user.id,))
            invalidated = cur.rowcount
            self._conn.executemany(
                "INSERT INTO recovery_codes (user_id, code_hash,"
                " created_at, used_at) VALUES (?, ?, ?, NULL)",
                [(user.id, _hash_code(normalise_code(c)), now)  # type: ignore[arg-type]
                 for c in codes])
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user.id,
                action="auth.recovery.generate", target_kind="user",
                target_id=str(user.id), outcome="success",
                source_ip=source_ip,
                detail={"count": len(codes),
                        "invalidated": invalidated})
        return GeneratedSet(codes=codes, invalidated=invalidated)

    def redeem(self, user_id: int, code: object,
               source_ip: str | None = None) -> bool:
        """Spend one code. True exactly once per code; every
        failure — wrong, spent, malformed, another account's —
        is the same False."""
        normalised = normalise_code(code)
        if normalised is None:
            return False
        digest = _hash_code(normalised)
        row = self._conn.execute(
            "SELECT id, used_at FROM recovery_codes"
            " WHERE user_id = ? AND code_hash = ?",
            (user_id, digest)).fetchone()
        if row is None or row["used_at"] is not None:
            return False
        with self._conn:
            cur = self._conn.execute(
                "UPDATE recovery_codes SET used_at = ?"
                " WHERE id = ? AND used_at IS NULL",
                (int(self._now()), row["id"]))
        if cur.rowcount == 0:  # a race spent it first
            return False
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user_id,
                action="auth.recovery.use", target_kind="user",
                target_id=str(user_id), outcome="success",
                source_ip=source_ip)
        return True

    def remaining(self, user_id: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM recovery_codes"
            " WHERE user_id = ? AND used_at IS NULL",
            (user_id,)).fetchone()
        return int(row["n"])
