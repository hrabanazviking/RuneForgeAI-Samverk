"""Password hashing (S-004) — study 07's decisions as code.

- **Algorithm:** scrypt via the stdlib `hashlib` — memory-hard, and
  stdlib-first (no dependency admitted; the S-017 register records
  this choice and the Argon2id revisit condition: if `argon2-cffi` is
  ever admitted for another reason, this module gains it as the
  preferred algorithm through the same self-describing format).
- **Per-user salt:** 128 bits from the OS CSPRNG, unique per password.
- **Self-describing storage:** `scrypt$n$r$p$salt_b64$digest_b64` —
  parameters travel with the hash, so cost can rise without
  invalidating existing rows.
- **Upgrade on login:** `verify_and_upgrade` returns a replacement
  hash whenever the stored one uses an old algorithm or weaker
  parameters; the caller persists it. Legacy `pbkdf2-sha256` rows
  verify (so old accounts can log in once) and always upgrade.
- **Comparison** is constant-time (`hmac.compare_digest`); S-005
  formalises the primitive for all callers.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass

_ALGO_SCRYPT = "scrypt"
_ALGO_LEGACY = "pbkdf2-sha256"
_SALT_BYTES = 16


@dataclass(frozen=True)
class ScryptParams:
    n: int = 32768  # CPU/memory cost (2^15); ~32 MiB at r=8
    r: int = 8
    p: int = 1
    dklen: int = 32


CURRENT = ScryptParams()


def _scrypt(password: bytes, salt: bytes, params: ScryptParams) -> bytes:
    return hashlib.scrypt(
        password, salt=salt, n=params.n, r=params.r, p=params.p,
        dklen=params.dklen,
        maxmem=128 * params.n * params.r * params.p * 2,
    )


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"), validate=True)


def hash_password(password: str) -> str:
    """Hash *password* at current parameters with a fresh salt."""
    salt = os.urandom(_SALT_BYTES)
    dk = _scrypt(password.encode("utf-8"), salt, CURRENT)
    return (f"{_ALGO_SCRYPT}${CURRENT.n}${CURRENT.r}${CURRENT.p}"
            f"${_b64(salt)}${_b64(dk)}")


def _parse(stored: str) -> tuple[str, list[str]] | None:
    parts = stored.split("$")
    if len(parts) < 2:
        return None
    return parts[0], parts[1:]


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verification. Malformed rows fail closed."""
    parsed = _parse(stored)
    if parsed is None:
        return False
    algo, rest = parsed
    try:
        if algo == _ALGO_SCRYPT:
            n, r, p = (int(rest[0]), int(rest[1]), int(rest[2]))
            salt, expected = _unb64(rest[3]), _unb64(rest[4])
            dk = _scrypt(password.encode("utf-8"), salt,
                         ScryptParams(n=n, r=r, p=p, dklen=len(expected)))
            return hmac.compare_digest(dk, expected)
        if algo == _ALGO_LEGACY:
            iterations = int(rest[0])
            salt, expected = _unb64(rest[1]), _unb64(rest[2])
            dk = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), salt, iterations,
                dklen=len(expected))
            return hmac.compare_digest(dk, expected)
    except (ValueError, IndexError, OverflowError):
        return False
    return False


def needs_upgrade(stored: str) -> bool:
    """True when *stored* is not a current-parameter scrypt hash."""
    parsed = _parse(stored)
    if parsed is None:
        return True
    algo, rest = parsed
    if algo != _ALGO_SCRYPT:
        return True
    try:
        n, r, p = (int(rest[0]), int(rest[1]), int(rest[2]))
    except (ValueError, IndexError):
        return True
    return (n, r, p) != (CURRENT.n, CURRENT.r, CURRENT.p)


def verify_and_upgrade(password: str, stored: str) -> tuple[bool, str | None]:
    """Verify; on success, also return a fresh current hash when the
    stored one is outdated (the hash-upgrade-on-login path)."""
    if not verify_password(password, stored):
        return False, None
    if needs_upgrade(stored):
        return True, hash_password(password)
    return True, None
