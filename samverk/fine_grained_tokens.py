"""Fine-grained tokens (S-033) — one repository, named
permissions.

Where S-032's classic token carries broad scopes across the
account, a fine-grained token is bound at minting to **exactly
one repository** (canonical owner/repo under S-013's law, the
S-031 binding shape) and to an explicit set of **per-resource
permissions**:

    contents:read | contents:write
    issues:read   | issues:write
    pull_requests:read | pull_requests:write
    metadata:read           (always held — see below)

- **The permission matrix is the contract.** ``authorize``
  answers one question — may this token do `permission` on
  `owner/repo`? — and answers None for everything else:
  another repository (even the same owner's), another owner,
  a permission not granted, a write asked where only read was
  granted. A write permission implies its read sibling, and
  only its own (``contents:write`` says nothing about issues).
- **metadata:read is mandatory.** Reading a repository's basic
  facts is the floor every token stands on, so minting adds it
  to the stored set whether or not the caller listed it — the
  stored set is the truth the matrix is tested against, never
  a hidden extra.
- Everything else is S-032's law, unchanged: ``svkf_`` +
  256-bit CSPRNG, **shown once**, only the SHA-256 hash stored,
  **expiry required** (at most one year), revocation a
  tombstone, creation and revocation audit-logged as
  ``auth.token.create`` / ``auth.token.revoke`` with the repo
  and permissions in `detail` — never the token.
"""

from __future__ import annotations

import base64
import hashlib
import os
import sqlite3
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .access_tokens import MAX_EXPIRY_SECONDS
from .accounts import AccountStore
from .audit import AuditLog
from .deploy_keys import DeployKeyError, canonical_repo

TOKEN_PREFIX = "svkf_"
_TOKEN_BYTES = 32  # 256 bits
TITLE_MAX = 100
_PREFIX_CHARS = 13  # "svkf_" + 8 random chars

FINE_PERMISSIONS = frozenset({
    "contents:read",
    "contents:write",
    "issues:read",
    "issues:write",
    "pull_requests:read",
    "pull_requests:write",
    "metadata:read",
})
MANDATORY_PERMISSIONS = frozenset({"metadata:read"})


class FineTokenError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class FineToken:
    id: int
    user_id: int
    owner: str
    repo: str
    title: str
    prefix: str
    permissions: frozenset[str]
    created_at: int
    expires_at: int
    last_used_at: int | None
    revoked: bool

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_token() -> str:
    raw = base64.urlsafe_b64encode(os.urandom(_TOKEN_BYTES)).decode("ascii")
    return TOKEN_PREFIX + raw.rstrip("=")


def permission_allows(token: FineToken, permission: str) -> bool:
    if permission in token.permissions:
        return True
    if permission.endswith(":read"):
        return (permission[:-len(":read")] + ":write") in token.permissions
    return False


def _validate_permissions(permissions: object) -> frozenset[str]:
    if isinstance(permissions, (str, bytes)) or not isinstance(permissions, Iterable):
        raise FineTokenError(
            "permissions_required",
            "Choose at least one permission for the token.")
    chosen = frozenset(permissions)  # type: ignore[arg-type]
    if not chosen:
        raise FineTokenError(
            "permissions_required",
            "Choose at least one permission for the token.")
    unknown = chosen - FINE_PERMISSIONS
    if unknown:
        raise FineTokenError(
            "permission_unknown",
            "Unknown permission(s): " + ", ".join(sorted(unknown)) + ".")
    return chosen | MANDATORY_PERMISSIONS


class FineTokenStore:
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
            raise FineTokenError("no_such_user", "No such account.")
        return user

    def _canonical(self, owner: object, repo: object) -> tuple[str, str]:
        try:
            return canonical_repo(owner, repo)
        except DeployKeyError as exc:
            raise FineTokenError(exc.reason, str(exc)) from None

    def create_token(
        self, user_id: int, owner: object, repo: object,
        title: object, permissions: object, expires_at: object,
        source_ip: str | None = None,
    ) -> tuple[FineToken, str]:
        """Mint a token bound to one repository; return
        (public facts, raw token) — the raw token shown once."""
        user = self._require_user(user_id)
        owner_c, repo_c = self._canonical(owner, repo)
        if not isinstance(title, str) or not title.strip():
            raise FineTokenError("title_required", "Give the token a title.")
        title_clean = title.strip()
        if len(title_clean) > TITLE_MAX or any(
                ord(c) < 0x20 or ord(c) == 0x7F for c in title_clean):
            raise FineTokenError("title_invalid", "That title is not valid.")
        perm_set = _validate_permissions(permissions)
        now = int(self._now())
        if not isinstance(expires_at, (int, float)) or isinstance(expires_at, bool):
            raise FineTokenError(
                "expiry_required",
                "Every token needs an expiry date; choose one.")
        expiry = int(expires_at)  # type: ignore[arg-type]
        if expiry <= now:
            raise FineTokenError(
                "expiry_in_past", "That expiry is already past.")
        if expiry > now + MAX_EXPIRY_SECONDS:
            raise FineTokenError(
                "expiry_too_far",
                "A token may live at most one year; choose a nearer expiry.")
        raw = _new_token()
        with self._conn:  # committed before the token is answered with
            cur = self._conn.execute(
                "INSERT INTO fine_grained_tokens (user_id, owner, repo,"
                " title, token_hash, prefix, permissions, created_at,"
                " expires_at, last_used_at, revoked)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0)",
                (user.id, owner_c, repo_c, title_clean, _hash_token(raw),
                 raw[:_PREFIX_CHARS], ",".join(sorted(perm_set)),
                 now, expiry))
        token = self.get_token(int(cur.lastrowid))
        assert token is not None
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user.id,
                action="auth.token.create", target_kind="repo",
                target_id=token.full_name, outcome="success",
                source_ip=source_ip,
                detail={"token_id": token.id, "kind": "fine_grained",
                        "permissions": sorted(perm_set)})
        return token, raw

    def get_token(self, token_id: int) -> FineToken | None:
        row = self._conn.execute(
            "SELECT * FROM fine_grained_tokens WHERE id = ?",
            (token_id,)).fetchone()
        return _row_to_token(row) if row else None

    def list_tokens(self, user_id: int) -> list[FineToken]:
        self._require_user(user_id)
        rows = self._conn.execute(
            "SELECT * FROM fine_grained_tokens WHERE user_id = ?"
            " ORDER BY id", (user_id,)).fetchall()
        return [_row_to_token(r) for r in rows]

    def list_for_repo(self, owner: object, repo: object) -> list[FineToken]:
        owner_c, repo_c = self._canonical(owner, repo)
        rows = self._conn.execute(
            "SELECT * FROM fine_grained_tokens WHERE owner = ? AND repo = ?"
            " ORDER BY id", (owner_c, repo_c)).fetchall()
        return [_row_to_token(r) for r in rows]

    def authenticate(self, presented: object) -> FineToken | None:
        """Resolve a raw token, enforcing revocation and expiry
        and stamping last-used; anything else answers None."""
        if not isinstance(presented, str) or not presented.startswith(TOKEN_PREFIX):
            return None
        now = int(self._now())
        row = self._conn.execute(
            "SELECT * FROM fine_grained_tokens WHERE token_hash = ?",
            (_hash_token(presented),)).fetchone()
        if row is None or row["revoked"] or now >= row["expires_at"]:
            return None
        with self._conn:
            self._conn.execute(
                "UPDATE fine_grained_tokens SET last_used_at = ?"
                " WHERE id = ?", (now, row["id"]))
        return self.get_token(row["id"])

    def authorize(
        self, presented: object, owner: object, repo: object,
        permission: object,
    ) -> FineToken | None:
        """The permission-matrix question: the token, when it
        may do `permission` on exactly this repository; None
        for every other answer — wrong repo, wrong owner,
        ungranted or unknown permission, dead token."""
        if not isinstance(permission, str) or permission not in FINE_PERMISSIONS:
            return None
        try:
            owner_c, repo_c = canonical_repo(owner, repo)
        except DeployKeyError:
            return None
        token = self.authenticate(presented)
        if token is None:
            return None
        if token.owner != owner_c or token.repo != repo_c:
            return None
        if not permission_allows(token, permission):
            return None
        return token

    def revoke_token(
        self, user_id: int, token_id: int,
        source_ip: str | None = None,
    ) -> bool:
        """Owner-only revocation tombstone, as S-032."""
        user = self._require_user(user_id)
        with self._conn:
            cur = self._conn.execute(
                "UPDATE fine_grained_tokens SET revoked = 1"
                " WHERE id = ? AND user_id = ? AND revoked = 0",
                (token_id, user.id))
        if cur.rowcount == 0:
            return False
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user.id,
                action="auth.token.revoke", target_kind="user",
                target_id=str(user.id), outcome="success",
                source_ip=source_ip,
                detail={"token_id": token_id, "kind": "fine_grained"})
        return True


def _row_to_token(row: sqlite3.Row) -> FineToken:
    return FineToken(
        id=row["id"], user_id=row["user_id"], owner=row["owner"],
        repo=row["repo"], title=row["title"], prefix=row["prefix"],
        permissions=frozenset(row["permissions"].split(","))
        if row["permissions"] else frozenset(),
        created_at=row["created_at"], expires_at=row["expires_at"],
        last_used_at=row["last_used_at"], revoked=bool(row["revoked"]))
