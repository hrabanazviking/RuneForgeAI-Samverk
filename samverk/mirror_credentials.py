"""Mirror credentials (S-330) -- tokens for private
sources, stored under S-003's secrets law, referenced
by the mirror, never embedded in stored URLs or logs.

S-329's pull mirrors strip any credential that arrives
inside a URL at the door, and said real credential
support was this slice's, under S-003. This module is
that support, and S-003's law shapes it whole:

- **Referenced, never stored.** A mirror credential is
  a *reference*: the NAME of an instance secret
  (S-003's shape -- a capital letter, then capitals,
  digits and underscores, e.g. ``MIRROR_GITHUB_TOKEN``),
  held in ``repo_mirrors.credential_name`` (migration
  133). The token itself is never in the database --
  neither plaintext nor encoded. It lives only where
  S-003 keeps instance secrets: in memory, loaded from
  the environment or a mode-600 secrets file. A stolen
  database therefore holds no usable mirror token --
  the battery sweeps the DB file for a seeded token
  and finds none -- and a stored source URL is never
  touched: it carries no userinfo when S-329 stored
  it, and naming a credential does not put one there.
- **One reference per mirror.** Only a mirror
  (S-070 / S-329) may hold one; setting a standing
  reference replaces it in place, and clearing
  withdraws it (the column returns to NULL). A mirror
  with no reference syncs exactly as before.
- **Stewards only.** Setting and clearing are guarded
  exactly as S-070 guards mirror management: the
  repository's owner alone (a site admin who is not
  the owner is refused ``not_repo_owner``, as
  ``attach_mirror`` refuses). Anyone else is refused
  before anything is stored.
- **Resolution fails closed.** ``resolve_token`` is
  the forge's own internal act at sync time: with no
  reference it returns None; with a reference whose
  secret is not loaded (no ``Secrets`` holder, or the
  holder does not carry the name) it refuses
  ``credential_unavailable``, naming the secret --
  never a value -- so a credentialed mirror never
  syncs silently unauthenticated, and ``sync_mirror``
  refuses *before* any fetch is attempted.
- **The only road out is the fetch seam.** A resolved
  token travels S-070 / proc's askpass seam (the fetch
  child's environment, never argv, never the URL).
  No listing, record, dict or repr ever carries a
  value, and a sync's recorded detail is scrubbed of
  the token before it stands in the mirror record.
- **Witnessed, values never.** Setting and clearing
  ride the standing ``repo.settings.change`` verb,
  each detail naming the act under ``key``
  (``mirror_credential.set`` /
  ``mirror_credential.clear``) with the secret's
  NAME, never a value. No new taxonomy event:
  138 stand.

Storage is migration 133 (schema 132 -> 133):
``repo_mirrors.credential_name`` -- the reference,
and the whole of what the column can hold.
"""
from __future__ import annotations
import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from .accounts import AccountStore
from .audit import AuditLog
from .mirrors import MirrorService
from .repositories import RepositoryStore
from .secrets import Secrets

__all__ = [
    "MirrorCredential", "MirrorCredentialError",
    "MirrorCredentialService", "credential_to_dict",
    "validate_secret_name",
]

_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class MirrorCredentialError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class MirrorCredential:
    repo_id: int
    full_name: str
    secret_name: str | None

    @property
    def has_credential(self) -> bool:
        return self.secret_name is not None

    @property
    def headline(self) -> str:
        if self.secret_name is None:
            return (f"{self.full_name} is a mirror with "
                    "no stored credential.")
        return (f"{self.full_name} is a mirror whose source "
                f"credential is the instance secret "
                f"{self.secret_name}.")


def validate_secret_name(name: object) -> str:
    """Pure: one credential reference -- an S-003
    instance-secret name (a capital letter, then
    capitals, digits and underscores). Anything else
    -- a lowercase word, a URL, a token itself -- is
    refused ``secret_name_invalid`` in words: a value
    can never be smuggled into the reference column."""
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise MirrorCredentialError(
            "secret_name_invalid",
            "Mirror credential: the NAME of an instance "
            "secret (S-003) -- a capital letter, then "
            "capitals, digits and underscores. The token "
            "itself is never stored.")
    return name


def credential_to_dict(cred: MirrorCredential) -> dict:
    """The public facts of one mirror credential: the
    reference only -- never a value."""
    return {
        "full_name": cred.full_name,
        "secret_name": cred.secret_name,
        "has_credential": cred.has_credential,
    }


class MirrorCredentialService:
    """Mirror credentials over S-070's mirror records:
    naming, clearing, resolving and syncing, guarded
    by the mirror's owner, witnessed on the standing
    verb, with values only ever in memory."""

    def __init__(self, conn: sqlite3.Connection,
                 data_root: Path,
                 accounts: AccountStore,
                 repositories: RepositoryStore,
                 audit: AuditLog | None = None,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._accounts = accounts
        self._repos = repositories
        self._audit = audit
        self._now = time_fn
        self._mirrors = MirrorService(
            conn, data_root, accounts, repositories, audit=None,
            time_fn=time_fn)

    # -- records -----------------------------------------------
    def credential_for(self, owner, repo) -> MirrorCredential | None:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            return None
        row = self._conn.execute(
            "SELECT repo_id, credential_name FROM repo_mirrors"
            " WHERE repo_id = ?", (current.id,)).fetchone()
        if row is None:
            return None
        return MirrorCredential(
            repo_id=row["repo_id"], full_name=current.full_name,
            secret_name=row["credential_name"])

    def has_credential(self, owner, repo) -> bool:
        cred = self.credential_for(owner, repo)
        return bool(cred and cred.has_credential)

    # -- guards --------------------------------------------------
    def _guard(self, actor_id, owner, repo) -> MirrorCredential:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise MirrorCredentialError(
                "no_such_repo", "No such repository.")
        actor = self._accounts.get_by_id(actor_id) \
            if isinstance(actor_id, int) else None
        if actor is None:
            raise MirrorCredentialError(
                "no_such_user", "No such account.")
        cred = self.credential_for(owner, repo)
        if cred is None:
            raise MirrorCredentialError(
                "not_a_mirror",
                "That repository is not a mirror; only a "
                "mirror holds a source credential.")
        if actor.username_lower != current.owner_lower:
            raise MirrorCredentialError(
                "not_repo_owner",
                "Only the repository's owner can manage "
                "its mirror credential.")
        return cred

    def _witness(self, actor_id: int, cred: MirrorCredential,
                 key: str, source_ip: str | None = None) -> None:
        if self._audit is None:
            return
        self._audit.append(
            actor_kind="user", actor_id=actor_id,
            action="repo.settings.change", target_kind="repo",
            target_id=cred.full_name, outcome="success",
            source_ip=source_ip,
            detail={"key": key, "secret_name": cred.secret_name})

    # -- acts ------------------------------------------------------
    def set_credential(self, actor_id, owner, repo, secret_name: object,
                       *, source_ip: str | None = None) -> MirrorCredential:
        cred = self._guard(actor_id, owner, repo)
        name = validate_secret_name(secret_name)
        with self._conn:
            self._conn.execute(
                "UPDATE repo_mirrors SET credential_name = ?"
                " WHERE repo_id = ?", (name, cred.repo_id))
        after = self.credential_for(owner, repo)
        assert after is not None
        self._witness(actor_id, after, "mirror_credential.set",
                      source_ip=source_ip)
        return after

    def clear_credential(self, actor_id, owner, repo,
                         *, source_ip: str | None = None) -> MirrorCredential:
        cred = self._guard(actor_id, owner, repo)
        with self._conn:
            self._conn.execute(
                "UPDATE repo_mirrors SET credential_name = NULL"
                " WHERE repo_id = ?", (cred.repo_id,))
        after = self.credential_for(owner, repo)
        assert after is not None
        self._witness(actor_id, cred, "mirror_credential.clear",
                      source_ip=source_ip)
        return after

    # -- resolution --------------------------------------------------
    def resolve_token(self, owner, repo,
                      secrets: Secrets | None) -> str | None:
        """The forge's own internal act at sync time:
        the token for one mirror, or None when it holds
        no credential. A named-but-unloaded secret is
        refused ``credential_unavailable`` -- fail
        closed, the secret named, a value never."""
        cred = self.credential_for(owner, repo)
        if cred is None or cred.secret_name is None:
            return None
        value = secrets.get(cred.secret_name) if secrets is not None else None
        if value is None:
            raise MirrorCredentialError(
                "credential_unavailable",
                f"The mirror credential {cred.secret_name} is "
                "named but its secret is not loaded; provide "
                "it through the environment or the secrets "
                "file (S-003) before syncing.")
        return value

    # -- sync -----------------------------------------------------------
    def sync_mirror(self, owner, repo, *,
                    secrets: Secrets | None = None):
        """Sync one mirror, resolving its credential
        first: a named-but-unloaded secret refuses
        before any fetch is attempted. The outcome is
        S-070's own SyncResult, its recorded detail
        scrubbed of the token before it stands."""
        token = self.resolve_token(owner, repo, secrets)
        result = self._mirrors.sync_mirror(owner, repo, token=token)
        if token and token in (result.detail or ""):
            clean = result.detail.replace(token, "[REDACTED]")
            current = self._repos.get_repository(owner, repo)
            with self._conn:
                self._conn.execute(
                    "UPDATE repo_mirrors SET last_detail = ?"
                    " WHERE repo_id = ?", (clean, current.id))
            result = type(result)(
                full_name=result.full_name, status=result.status,
                synced_at=result.synced_at, detail=clean)
        return result
