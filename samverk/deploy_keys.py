"""Deploy keys (S-031) — per-repository keys, study 08 as code.

A deploy key is a machine credential bound to **exactly one
repository**, identified here by its canonical `owner/repo`
(full name, both halves passing S-013's name law — repositories
themselves arrive in Part III, and the binding is by identity,
so a key minted now names the repo it will serve then).

- **Read-only by default.** A key is created with `can_write`
  False; read/write is an *explicit grant* — the caller must
  pass `can_write=True` deliberately at creation. There is no
  later silent widening: changing the grant means deleting and
  re-adding the key (the change is then two audit rows, not an
  edit no one saw).
- **One repo, never more.** `authorize(fingerprint, owner,
  repo, write=...)` answers for the key's one repository only:
  the same fingerprint presented for any other repository is
  refused — the slice's acceptance, proven in test. A
  read-only key presented for a write is refused too.
- Keys reuse S-030's strict parser and fingerprint, and a
  fingerprint may not be both a personal key and a deploy key,
  nor a deploy key for two repositories (one credential, one
  attribution). Adding a deploy key is an act of the repo's
  owner account in this slice's data shape (repository
  collaborators arrive with Part III and inherit the store),
  and is audit-logged: adds carry `repo.settings.change`
  with the key's fingerprint and grant in `detail` — never key
  material beyond the public blob. Removal is likewise logged.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore
from .audit import AuditLog
from .repo_paths import RepoPathError, validate_owner_name, validate_repo_name
from .ssh_keys import SshKeyError, parse_public_key

TITLE_MAX = 100


class DeployKeyError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class DeployKey:
    id: int
    owner: str            # canonical owner name (lowercase)
    repo: str             # canonical repo name (lowercase)
    title: str
    key_type: str
    fingerprint: str
    can_write: bool
    created_at: int
    last_used_at: int | None

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


def canonical_repo(owner: object, repo: object) -> tuple[str, str]:
    """Validate both halves under S-013's law and return their
    canonical (lowercase) forms — repository identity in
    Samverk is case-insensitive, as account identity is."""
    try:
        owner_ok = validate_owner_name(owner)
        repo_ok = validate_repo_name(repo)
    except RepoPathError as exc:
        raise DeployKeyError("repo_invalid", str(exc)) from None
    return owner_ok.lower(), repo_ok.lower()


class DeployKeyStore:
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

    def add_key(
        self, actor_user_id: int, owner: object, repo: object,
        title: object, key_line: object, *,
        can_write: bool = False,
        source_ip: str | None = None,
    ) -> DeployKey:
        """Bind a key to one repository. The actor must be the
        owner account itself (later parts widen who may act;
        the binding law does not change)."""
        actor = self._accounts.get_by_id(actor_user_id)
        if actor is None:
            raise DeployKeyError("no_such_user", "No such account.")
        owner_c, repo_c = canonical_repo(owner, repo)
        if actor.username_lower != owner_c:
            raise DeployKeyError(
                "not_repo_owner",
                "Only the repository's owner can add its deploy keys.")
        if not isinstance(title, str) or not title.strip():
            raise DeployKeyError("title_required", "Give the key a title.")
        title_clean = title.strip()
        if len(title_clean) > TITLE_MAX or any(
                ord(c) < 0x20 or ord(c) == 0x7F for c in title_clean):
            raise DeployKeyError("title_invalid", "That title is not valid.")
        try:
            parsed = parse_public_key(key_line)
        except SshKeyError as exc:
            raise DeployKeyError(exc.reason, str(exc)) from None
        clash = self._conn.execute(
            "SELECT 'personal' AS src FROM ssh_keys WHERE fingerprint = ?"
            " UNION ALL"
            " SELECT 'deploy' FROM deploy_keys WHERE fingerprint = ?",
            (parsed.fingerprint, parsed.fingerprint)).fetchone()
        if clash is not None:
            raise DeployKeyError(
                "key_already_registered",
                "That key is already registered as a "
                + ("personal key." if clash["src"] == "personal"
                   else "deploy key."))
        import base64
        now = int(self._now())
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO deploy_keys (owner, repo, title, key_type,"
                " key_blob, fingerprint, can_write, created_at,"
                " last_used_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                (owner_c, repo_c, title_clean, parsed.key_type,
                 base64.b64encode(parsed.blob).decode("ascii"),
                 parsed.fingerprint, 1 if can_write else 0, now))
        key = self.get_key(int(cur.lastrowid))
        assert key is not None
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.settings.change", target_kind="repo",
                target_id=key.full_name, outcome="success",
                source_ip=source_ip,
                detail={"key": "deploy_key.add",
                        "fingerprint": parsed.fingerprint,
                        "can_write": bool(can_write)})
        return key

    def get_key(self, key_id: int) -> DeployKey | None:
        row = self._conn.execute(
            "SELECT * FROM deploy_keys WHERE id = ?", (key_id,)).fetchone()
        return _row_to_key(row) if row else None

    def list_keys(self, owner: object, repo: object) -> list[DeployKey]:
        owner_c, repo_c = canonical_repo(owner, repo)
        rows = self._conn.execute(
            "SELECT * FROM deploy_keys WHERE owner = ? AND repo = ?"
            " ORDER BY id", (owner_c, repo_c)).fetchall()
        return [_row_to_key(r) for r in rows]

    def authorize(
        self, fingerprint: object, owner: object, repo: object,
        *, write: bool = False,
    ) -> DeployKey | None:
        """The transport question (S-088 proves it on the wire):
        may this key act on this repository? Returns the key
        when allowed, None otherwise — another repository, an
        unknown key, or a write asked of a read-only key all
        answer the same None."""
        if not isinstance(fingerprint, str):
            return None
        try:
            owner_c, repo_c = canonical_repo(owner, repo)
        except DeployKeyError:
            return None
        row = self._conn.execute(
            "SELECT * FROM deploy_keys WHERE fingerprint = ?",
            (fingerprint,)).fetchone()
        if row is None:
            return None
        key = _row_to_key(row)
        if key.owner != owner_c or key.repo != repo_c:
            return None
        if write and not key.can_write:
            return None
        return key

    def record_use(self, key_id: int) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE deploy_keys SET last_used_at = ? WHERE id = ?",
                (int(self._now()), key_id))

    def delete_key(
        self, actor_user_id: int, key_id: int,
        source_ip: str | None = None,
    ) -> bool:
        actor = self._accounts.get_by_id(actor_user_id)
        if actor is None:
            return False
        row = self._conn.execute(
            "SELECT * FROM deploy_keys WHERE id = ?", (key_id,)).fetchone()
        if row is None or row["owner"] != actor.username_lower:
            return False
        key = _row_to_key(row)
        with self._conn:
            self._conn.execute(
                "DELETE FROM deploy_keys WHERE id = ?", (key_id,))
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.settings.change", target_kind="repo",
                target_id=key.full_name, outcome="success",
                source_ip=source_ip,
                detail={"key": "deploy_key.remove",
                        "fingerprint": key.fingerprint})
        return True


def _row_to_key(row: sqlite3.Row) -> DeployKey:
    return DeployKey(
        id=row["id"], owner=row["owner"], repo=row["repo"],
        title=row["title"], key_type=row["key_type"],
        fingerprint=row["fingerprint"], can_write=bool(row["can_write"]),
        created_at=row["created_at"], last_used_at=row["last_used_at"])
