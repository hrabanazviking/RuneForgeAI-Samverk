"""SSH keys (S-030) — personal keys, study 08 as code.

- **Parsing is strict.** A key line is `<type> <base64-blob>
  [comment]`; the type must be an admitted algorithm
  (ed25519, ecdsa-sha2-nistp256/384/521, rsa), the blob must
  base64-decode strictly, and the blob's own first length-
  prefixed string must name the *same* algorithm — a blob
  wearing another algorithm's label is refused. Legacy
  `ssh-dss` is not admitted.
- **Fingerprint** is the OpenSSH shape: `SHA256:<base64 of the
  blob's SHA-256, padding stripped>` — safe to show and log,
  and what the audit rows carry (never the key material beyond
  the public blob itself, which is public by nature).
- **Adding a key requires sudo-mode re-authentication.** This
  slice takes a `reauth_verifier` seam — a callable answering
  "has this user freshly re-authenticated?" — which S-036
  (sudo mode) supplies for real. The seam **fails closed**:
  with no verifier wired, or a verifier that answers no, the
  add is refused `sudo_required` and stores nothing. S-036's
  battery will exercise the real verifier against this seam.
- Keys are listed with fingerprint, title, created and
  **last-used** shown (last-used starts empty and is stamped
  by `record_use`, which the transport slices call when a key
  authenticates). One account cannot register the same key
  twice, and the same key may not be registered to two
  accounts (a shared credential is an attribution hole).
  Deletion is by id, owner-only, audit-logged
  (`auth.ssh_key.add` / `auth.ssh_key.remove`).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import sqlite3
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore
from .audit import AuditLog

ADMITTED_KEY_TYPES = frozenset({
    "ssh-ed25519",
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
    "ssh-rsa",
})
TITLE_MAX = 100


class SshKeyError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class SshKey:
    id: int
    user_id: int
    title: str
    key_type: str
    fingerprint: str
    created_at: int
    last_used_at: int | None


@dataclass(frozen=True)
class ParsedKey:
    key_type: str
    blob: bytes
    fingerprint: str
    comment: str | None


def fingerprint_of(blob: bytes) -> str:
    digest = base64.b64encode(hashlib.sha256(blob).digest())
    return "SHA256:" + digest.decode("ascii").rstrip("=")


def parse_public_key(line: object) -> ParsedKey:
    """Parse one OpenSSH public-key line, strictly, or raise
    SshKeyError with a stable reason."""
    if not isinstance(line, str) or not line.strip():
        raise SshKeyError("key_required", "Paste a public key.")
    parts = line.strip().split(None, 2)
    if len(parts) < 2:
        raise SshKeyError(
            "key_malformed",
            "That does not look like an OpenSSH public key line.")
    key_type, encoded = parts[0], parts[1]
    comment = parts[2].strip() if len(parts) == 3 else None
    if key_type not in ADMITTED_KEY_TYPES:
        raise SshKeyError(
            "key_type_not_admitted",
            "That key type is not accepted on this instance.")
    try:
        blob = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise SshKeyError(
            "key_malformed",
            "That does not look like an OpenSSH public key line.") from None
    # The blob's first field is a length-prefixed string naming
    # the algorithm; it must agree with the outer label.
    if len(blob) < 4:
        raise SshKeyError("key_malformed", "That key is too short to be real.")
    (name_len,) = struct.unpack(">I", blob[:4])
    if name_len == 0 or 4 + name_len > len(blob):
        raise SshKeyError("key_malformed", "That key is malformed.")
    try:
        inner_type = blob[4:4 + name_len].decode("ascii")
    except UnicodeDecodeError:
        raise SshKeyError("key_malformed", "That key is malformed.") from None
    if inner_type != key_type:
        raise SshKeyError(
            "key_malformed",
            "That key's contents do not match its stated type.")
    # A key blob carries at least one field after its name.
    if 4 + name_len == len(blob):
        raise SshKeyError("key_malformed", "That key carries no key material.")
    return ParsedKey(
        key_type=key_type, blob=blob,
        fingerprint=fingerprint_of(blob), comment=comment)


class SshKeyStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        accounts: AccountStore,
        audit: AuditLog | None = None,
        reauth_verifier: Callable[[int], bool] | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._audit = audit
        self._reauth = reauth_verifier
        self._now = time_fn

    def _require_user(self, user_id: int):
        user = self._accounts.get_by_id(user_id)
        if user is None:
            raise SshKeyError("no_such_user", "No such account.")
        return user

    def add_key(
        self, user_id: int, title: object, key_line: object,
        source_ip: str | None = None,
    ) -> SshKey:
        """Add a personal key. Acceptance gate: sudo-mode
        re-auth (the S-036 seam) must answer yes, first."""
        user = self._require_user(user_id)
        if self._reauth is None or not self._reauth(user.id):
            raise SshKeyError(
                "sudo_required",
                "Adding an SSH key needs a fresh password "
                "confirmation; confirm and try again.")
        if not isinstance(title, str) or not title.strip():
            raise SshKeyError("title_required", "Give the key a title.")
        title_clean = title.strip()
        if len(title_clean) > TITLE_MAX or any(
                ord(c) < 0x20 or ord(c) == 0x7F for c in title_clean):
            raise SshKeyError("title_invalid", "That title is not valid.")
        parsed = parse_public_key(key_line)
        existing = self._conn.execute(
            "SELECT user_id FROM ssh_keys WHERE fingerprint = ?",
            (parsed.fingerprint,)).fetchone()
        if existing is not None:
            if existing["user_id"] == user.id:
                raise SshKeyError(
                    "key_already_registered",
                    "That key is already on your account.")
            raise SshKeyError(
                "key_already_registered",
                "That key is already registered to an account.")
        now = int(self._now())
        blob_b64 = base64.b64encode(parsed.blob).decode("ascii")
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO ssh_keys (user_id, title, key_type,"
                " key_blob, fingerprint, created_at, last_used_at)"
                " VALUES (?, ?, ?, ?, ?, ?, NULL)",
                (user.id, title_clean, parsed.key_type, blob_b64,
                 parsed.fingerprint, now))
        key = self.get_key(int(cur.lastrowid))
        assert key is not None
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user.id,
                action="auth.ssh_key.add", target_kind="user",
                target_id=str(user.id), outcome="success",
                source_ip=source_ip,
                detail={"fingerprint": parsed.fingerprint})
        return key

    def get_key(self, key_id: int) -> SshKey | None:
        row = self._conn.execute(
            "SELECT * FROM ssh_keys WHERE id = ?", (key_id,)).fetchone()
        return _row_to_key(row) if row else None

    def list_keys(self, user_id: int) -> list[SshKey]:
        self._require_user(user_id)
        rows = self._conn.execute(
            "SELECT * FROM ssh_keys WHERE user_id = ? ORDER BY id",
            (user_id,)).fetchall()
        return [_row_to_key(r) for r in rows]

    def find_by_fingerprint(self, fingerprint: str) -> SshKey | None:
        row = self._conn.execute(
            "SELECT * FROM ssh_keys WHERE fingerprint = ?",
            (fingerprint,)).fetchone()
        return _row_to_key(row) if row else None

    def record_use(self, key_id: int) -> None:
        """Stamp last-used; called by the transport when a key
        authenticates (Part III)."""
        with self._conn:
            self._conn.execute(
                "UPDATE ssh_keys SET last_used_at = ? WHERE id = ?",
                (int(self._now()), key_id))

    def delete_key(
        self, user_id: int, key_id: int,
        source_ip: str | None = None,
    ) -> bool:
        """Owner-only delete. Returns False when there is no such
        key *on this account* — another account's key is
        indistinguishable from a missing one."""
        user = self._require_user(user_id)
        row = self._conn.execute(
            "SELECT fingerprint FROM ssh_keys"
            " WHERE id = ? AND user_id = ?",
            (key_id, user.id)).fetchone()
        if row is None:
            return False
        with self._conn:
            self._conn.execute(
                "DELETE FROM ssh_keys WHERE id = ?", (key_id,))
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user.id,
                action="auth.ssh_key.remove", target_kind="user",
                target_id=str(user.id), outcome="success",
                source_ip=source_ip,
                detail={"fingerprint": row["fingerprint"]})
        return True


def _row_to_key(row: sqlite3.Row) -> SshKey:
    return SshKey(
        id=row["id"], user_id=row["user_id"], title=row["title"],
        key_type=row["key_type"], fingerprint=row["fingerprint"],
        created_at=row["created_at"], last_used_at=row["last_used_at"])
