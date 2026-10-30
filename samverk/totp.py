"""Two-factor TOTP enrolment (S-035) — study 10 as code,
RFC 6238 / RFC 4226 (public specifications) as the algorithm.

- **Algorithm:** HMAC-SHA1 TOTP, 30-second step, 6 digits —
  the shape every authenticator application implements, so
  enrolment interoperates rather than inventing a dialect.
  Codes are accepted within one step either side of now
  (clock skew is real), but **each counter may be spent only
  once**: the last spent counter is stored, and any code at
  or below it is refused — a photographed code is not a
  reusable key.
- **The secret** is 160 bits from the OS CSPRNG, shown to the
  owner exactly two lawful ways: the provisioning URI
  (`otpauth://…`, which authenticator apps turn into the QR
  code) and the same Base32 secret for manual entry. The UI
  layer renders the QR from the URI; no QR library is admitted
  for what is a presentation of a string.
- **At rest the secret is encrypted, never plain and never
  hashed** (verification needs the secret itself, so hashing
  is impossible — that is what makes custody matter). The
  cipher is an HMAC-SHA256 keystream keyed by a caller-supplied
  256-bit instance key (custodied per S-020 in production
  wiring), with a fresh random nonce per enrolment, stored as
  `v1:<base64 nonce+ciphertext>`. A stolen database alone
  therefore yields no usable second factor — the DB-leak test
  sweeps the file for the plaintext secret. With **no key
  supplied, enrolment refuses** (`encryption_unavailable`):
  fail-closed, like every other Samverk seam.
- **Enabling is a step-up act:** `begin_enrolment` requires
  the same fresh-re-auth seam S-030 introduced (S-036 supplies
  the real verifier), failing closed without it. Enrolment
  starts *pending*; only `confirm_enrolment` with a live code
  activates it, audited `auth.twofactor.enable`
  (`{"method": "totp"}`, already in the frozen taxonomy).
  Re-beginning while pending replaces the pending secret;
  replacing a *confirmed* credential is refused — disable
  first (S-036's sudo-gated act, in that slice's surface).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import sqlite3
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote

from .accounts import AccountStore
from .audit import AuditLog
from .throttle import constant_time_equal

STEP_SECONDS = 30
DIGITS = 6
SECRET_BYTES = 20  # 160 bits, the RFC 4226 recommended length
WINDOW = 1  # one step either side, for clock skew
_KEY_BYTES = 32
_NONCE_BYTES = 16


class TotpError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Enrolment:
    secret_base32: str      # manual-entry form, shown once per begin
    provisioning_uri: str   # otpauth:// URI; the QR encodes this


def hotp(secret: bytes, counter: int) -> str:
    """RFC 4226 HOTP as a zero-padded 6-digit string."""
    digest = hmac.new(
        secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10 ** DIGITS)).zfill(DIGITS)


def totp_at(secret: bytes, timestamp: float) -> str:
    return hotp(secret, int(timestamp // STEP_SECONDS))


def generate_secret() -> tuple[bytes, str]:
    raw = os.urandom(SECRET_BYTES)
    return raw, base64.b32encode(raw).decode("ascii")


def provisioning_uri(username: str, secret_base32: str,
                     issuer: str = "Samverk") -> str:
    label = f"{quote(issuer, safe='')}:{quote(username, safe='')}"
    return (
        f"otpauth://totp/{label}?secret={secret_base32}"
        f"&issuer={quote(issuer, safe='')}"
        f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}")


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    block = 0
    while len(out) < length:
        out.extend(hmac.new(
            key, nonce + struct.pack(">I", block), hashlib.sha256
        ).digest())
        block += 1
    return bytes(out[:length])


def encrypt_secret(key: bytes, plaintext: str) -> str:
    nonce = os.urandom(_NONCE_BYTES)
    data = plaintext.encode("ascii")
    stream = _keystream(key, nonce, len(data))
    cipher = bytes(a ^ b for a, b in zip(data, stream))
    return "v1:" + base64.b64encode(nonce + cipher).decode("ascii")


def decrypt_secret(key: bytes, stored: str) -> str:
    if not stored.startswith("v1:"):
        raise TotpError("secret_unreadable",
                        "The stored two-factor secret is unreadable.")
    try:
        blob = base64.b64decode(stored[3:], validate=True)
    except ValueError:
        raise TotpError(
            "secret_unreadable",
            "The stored two-factor secret is unreadable.") from None
    nonce, cipher = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
    stream = _keystream(key, nonce, len(cipher))
    try:
        return bytes(a ^ b for a, b in zip(cipher, stream)).decode("ascii")
    except UnicodeDecodeError:
        raise TotpError(
            "secret_unreadable",
            "The stored two-factor secret is unreadable.") from None


def _normalise_code(code: object) -> str | None:
    if not isinstance(code, str):
        return None
    cleaned = code.replace(" ", "")
    if len(cleaned) != DIGITS or not cleaned.isdigit():
        return None
    return cleaned


class TotpStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        accounts: AccountStore,
        audit: AuditLog | None = None,
        encryption_key: bytes | None = None,
        reauth_verifier: Callable[[int], bool] | None = None,
        issuer: str = "Samverk",
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._audit = audit
        self._key = encryption_key
        self._reauth = reauth_verifier
        self._issuer = issuer
        self._now = time_fn

    # -- helpers -------------------------------------------------
    def _require_user(self, user_id: int):
        user = self._accounts.get_by_id(user_id)
        if user is None:
            raise TotpError("no_such_user", "No such account.")
        return user

    def _row(self, user_id: int) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM totp_credentials WHERE user_id = ?",
            (user_id,)).fetchone()

    def _secret_of(self, row: sqlite3.Row) -> bytes:
        if self._key is None:
            raise TotpError(
                "encryption_unavailable",
                "Two-factor storage is not configured on this instance.")
        return base64.b32decode(decrypt_secret(self._key, row["secret_enc"]))

    def _match_counter(self, secret: bytes, code: str,
                       after_counter: int) -> int | None:
        """The counter *code* belongs to, within the skew window
        and strictly after *after_counter* (replay law), or None."""
        current = int(self._now() // STEP_SECONDS)
        for counter in range(current - WINDOW, current + WINDOW + 1):
            if counter <= after_counter:
                continue
            if constant_time_equal(hotp(secret, counter), code):
                return counter
        return None

    # -- enrolment -----------------------------------------------
    def begin_enrolment(self, user_id: int) -> Enrolment:
        """Start (or restart a pending) enrolment. Step-up law:
        the re-auth seam must answer yes, first."""
        user = self._require_user(user_id)
        if self._reauth is None or not self._reauth(user.id):
            raise TotpError(
                "sudo_required",
                "Enabling two-factor needs a fresh password "
                "confirmation; confirm and try again.")
        if self._key is None or len(self._key) != _KEY_BYTES:
            raise TotpError(
                "encryption_unavailable",
                "Two-factor storage is not configured on this instance.")
        row = self._row(user.id)
        if row is not None and row["confirmed"]:
            raise TotpError(
                "already_enabled",
                "Two-factor is already on; disable it before "
                "enrolling a new authenticator.")
        _, secret_b32 = generate_secret()
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "INSERT INTO totp_credentials (user_id, secret_enc,"
                " confirmed, created_at, confirmed_at, last_counter)"
                " VALUES (?, ?, 0, ?, NULL, -1)"
                " ON CONFLICT(user_id) DO UPDATE SET"
                " secret_enc = excluded.secret_enc, confirmed = 0,"
                " created_at = excluded.created_at,"
                " confirmed_at = NULL, last_counter = -1",
                (user.id, encrypt_secret(self._key, secret_b32), now))
        return Enrolment(
            secret_base32=secret_b32,
            provisioning_uri=provisioning_uri(
                user.username, secret_b32, self._issuer))

    def confirm_enrolment(self, user_id: int, code: object,
                          source_ip: str | None = None) -> bool:
        """Activate a pending enrolment with a live code.
        Returns False for a wrong/expired/replayed code —
        indistinguishably, like every Samverk refusal."""
        user = self._require_user(user_id)
        cleaned = _normalise_code(code)
        row = self._row(user.id)
        if cleaned is None or row is None or row["confirmed"]:
            return False
        counter = self._match_counter(
            self._secret_of(row), cleaned, row["last_counter"])
        if counter is None:
            return False
        with self._conn:
            self._conn.execute(
                "UPDATE totp_credentials SET confirmed = 1,"
                " confirmed_at = ?, last_counter = ? WHERE user_id = ?",
                (int(self._now()), counter, user.id))
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user.id,
                action="auth.twofactor.enable", target_kind="user",
                target_id=str(user.id), outcome="success",
                source_ip=source_ip, detail={"method": "totp"})
        return True

    # -- use -------------------------------------------------------
    def is_enabled(self, user_id: int) -> bool:
        row = self._row(user_id)
        return bool(row is not None and row["confirmed"])

    def verify_code(self, user_id: int, code: object) -> bool:
        """The login-time check: a live, unspent code from a
        confirmed credential. Success spends the counter."""
        cleaned = _normalise_code(code)
        row = self._row(user_id)
        if cleaned is None or row is None or not row["confirmed"]:
            return False
        counter = self._match_counter(
            self._secret_of(row), cleaned, row["last_counter"])
        if counter is None:
            return False
        with self._conn:
            self._conn.execute(
                "UPDATE totp_credentials SET last_counter = ?"
                " WHERE user_id = ?",
                (counter, user_id))
        return True

    def remove(self, user_id: int) -> bool:
        """Delete the credential (the disable act's storage half;
        the sudo gate lives in the calling surface). Audited
        `auth.twofactor.disable` when a confirmed credential
        actually goes away."""
        row = self._row(user_id)
        if row is None:
            return False
        was_confirmed = bool(row["confirmed"])
        with self._conn:
            self._conn.execute(
                "DELETE FROM totp_credentials WHERE user_id = ?",
                (user_id,))
        if was_confirmed and self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user_id,
                action="auth.twofactor.disable", target_kind="user",
                target_id=str(user_id), outcome="success")
        return True
