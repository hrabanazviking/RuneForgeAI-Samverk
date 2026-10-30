"""Identity linking — data shape only (S-045).

An account may link external identities: a named provider
plus that provider's principal id for this person. The
first provider is **Samtal** (`PROVIDER_SAMTAL`), Volmarr's
chat village, whose seat ids are the natural principal.

**Shape only, by the roadmap's own word:** this slice stores
and resolves links. It contains no seam, no sync, no login
by external identity, and no federation — the Samtal seam
itself is Part XIX, and federation is refused permanently.
Nothing here speaks to another server.

Law of the shape:
- Provider names are lowercase slug names (letters, digits,
  hyphens), so the provider vocabulary stays clean.
- One link per (account, provider), and one account per
  (provider, external id): an external principal can never
  be claimed by two accounts, and re-linking a provider is
  an unlink + link, both on the audit record
  (`auth.identity.link` / `auth.identity.unlink`, detail
  carrying the provider only).
- The external id is an identifier, not a credential: it is
  stored as given (trimmed, length-capped) and confers no
  authentication power whatsoever in this slice.
"""

from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore
from .audit import AuditLog

PROVIDER_SAMTAL = "samtal"
PROVIDER_MAX = 39
EXTERNAL_ID_MAX = 200

_PROVIDER_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$")


class IdentityLinkError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class ExternalIdentity:
    id: int
    user_id: int
    provider: str
    external_id: str
    created_at: int


def _clean_provider(provider: object) -> str:
    if (not isinstance(provider, str)
            or len(provider) > PROVIDER_MAX
            or not _PROVIDER_RE.match(provider.strip().lower())):
        raise IdentityLinkError(
            "provider_invalid",
            "Provider names use lowercase letters, digits and hyphens.")
    return provider.strip().lower()


def _clean_external_id(external_id: object) -> str:
    if not isinstance(external_id, str) or not external_id.strip():
        raise IdentityLinkError(
            "external_id_required", "An external identity needs an id.")
    text = external_id.strip()
    if len(text) > EXTERNAL_ID_MAX or any(
            ord(c) < 0x20 or ord(c) == 0x7F for c in text):
        raise IdentityLinkError(
            "external_id_invalid", "That external id is not valid.")
    return text


class IdentityLinkStore:
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

    def link(self, user_id: int, provider: object, external_id: object,
             *, source_ip: str | None = None) -> ExternalIdentity:
        if self._accounts.get_by_id(user_id) is None:
            raise IdentityLinkError("no_such_user", "No such account.")
        prov = _clean_provider(provider)
        ext = _clean_external_id(external_id)
        holder = self.resolve(prov, ext)
        if holder is not None and holder != user_id:
            raise IdentityLinkError(
                "already_claimed",
                "That external identity is linked to another account.")
        if self.get(user_id, prov) is not None:
            raise IdentityLinkError(
                "provider_already_linked",
                "This account already links that provider; "
                "unlink it first to change the link.")
        now = int(self._now())
        try:
            with self._conn:
                cur = self._conn.execute(
                    "INSERT INTO external_identities"
                    " (user_id, provider, external_id, created_at)"
                    " VALUES (?, ?, ?, ?)", (user_id, prov, ext, now))
        except sqlite3.IntegrityError:
            raise IdentityLinkError(
                "already_claimed",
                "That external identity is already linked.") from None
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user_id,
                action="auth.identity.link", target_kind="user",
                target_id=str(user_id), outcome="success",
                source_ip=source_ip, detail={"provider": prov})
        return ExternalIdentity(int(cur.lastrowid), user_id, prov, ext, now)

    def unlink(self, user_id: int, provider: object,
               *, source_ip: str | None = None) -> bool:
        prov = _clean_provider(provider)
        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM external_identities"
                " WHERE user_id = ? AND provider = ?",
                (user_id, prov))
        if cur.rowcount == 0:
            return False
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user_id,
                action="auth.identity.unlink", target_kind="user",
                target_id=str(user_id), outcome="success",
                source_ip=source_ip, detail={"provider": prov})
        return True

    def get(self, user_id: int, provider: object) -> ExternalIdentity | None:
        try:
            prov = _clean_provider(provider)
        except IdentityLinkError:
            return None
        row = self._conn.execute(
            "SELECT * FROM external_identities"
            " WHERE user_id = ? AND provider = ?",
            (user_id, prov)).fetchone()
        return self._row(row) if row else None

    def list_for_user(self, user_id: int) -> list[ExternalIdentity]:
        rows = self._conn.execute(
            "SELECT * FROM external_identities WHERE user_id = ?"
            " ORDER BY provider", (user_id,)).fetchall()
        return [self._row(r) for r in rows]

    def resolve(self, provider: object, external_id: object) -> int | None:
        """Which account (if any) claims this external
        principal — resolution of the shape, nothing more."""
        try:
            prov = _clean_provider(provider)
            ext = _clean_external_id(external_id)
        except IdentityLinkError:
            return None
        row = self._conn.execute(
            "SELECT user_id FROM external_identities"
            " WHERE provider = ? AND external_id = ?",
            (prov, ext)).fetchone()
        return int(row["user_id"]) if row else None

    @staticmethod
    def _row(row: sqlite3.Row) -> ExternalIdentity:
        return ExternalIdentity(
            id=row["id"], user_id=row["user_id"],
            provider=row["provider"], external_id=row["external_id"],
            created_at=row["created_at"])
