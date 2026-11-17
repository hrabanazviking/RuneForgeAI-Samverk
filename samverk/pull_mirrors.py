"""Pull mirrors (S-329).

A pull mirror is created as a mirror of any git URL -- and the
repository does **not** advertise itself as ready until its first
sync completes. Creation and readiness are separate facts, kept
separate on purpose:

- The repository row and its bare directory exist from the moment
  of creation (S-070's law: a mirror is an ordinary repository plus
  a mirror record; no second storage engine). An owner can find
  the repo, see that it is a mirror, and see exactly where its
  first sync stands.
- Readiness is earned, never assumed. The mirror's state lives in
  S-070's own ``repo_mirrors.last_status`` column, extended with
  two honest pre-first-sync values -- no migration, so the schema
  stays where S-324 left it:

      ``pending``  created; the first sync has not run yet
      ``syncing``  a sync (first or later) is running right now
      ``ok``       the last sync succeeded -- the mirror is ready
      ``failed``   the last sync failed; the mirror is NOT ready,
                   and its record says why in plain words

  A legacy S-070 mirror that has never synced (``last_status``
  NULL) reads as ``pending`` here too: it has not completed a
  first sync, so it must not advertise ready either.

- The first sync runs as part of creation (``create_pull_mirror``
  is begin + first sync). It is also available in two steps --
  ``begin_pull_mirror`` then ``complete_first_sync`` -- so a UI or
  a scheduler can show the pending state while the sync runs.
  A failed first sync leaves the repository in place, state
  ``failed``, ready False: a failed mirror never looks healthy,
  and a later ``sync_pull_mirror`` can still bring it ready.

URL law. Remote schemes are S-069's (https, http, git, ssh),
validated by ``validate_remote_url`` -- with one deliberate
difference from the import seam: a URL that arrives carrying
credentials inside it (``https://user:secret@host/repo.git``) is
not refused, it is **stripped**. The userinfo is removed before
the URL is stored, fetched, audited, or named in any error, so a
credential can never leak into the mirror record, a log, or a
process list through this slice. (Real credential support is
S-330's, under S-003's secrets law -- never the URL.) A
``file://`` URL names a repository on this instance's own disk
and is stored as a local source, exactly like a ``Path`` source;
``ext::``, scp-like strings, relative paths, fragments, and
leading dashes are refused in plain words.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse, urlunparse

from .accounts import AccountStore
from .audit import AuditLog
from .mirrors import MirrorError, MirrorService
from .proc import REMOTE_URL_SCHEMES, ProcRefused, validate_remote_url
from .repositories import RepositoryError, RepositoryStore

PENDING = "pending"
SYNCING = "syncing"
READY = "ready"
FAILED = "failed"

_STATE_WORDS = {
    PENDING: "waiting for its first sync",
    SYNCING: "syncing from its source",
    READY: "ready",
    FAILED: "its last sync failed",
}


class PullMirrorError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class PullMirror:
    repo_id: int
    full_name: str
    source: str
    source_kind: str          # "url" | "local"
    state: str                # PENDING | SYNCING | READY | FAILED
    created_at: int
    last_sync_at: int | None
    last_detail: str | None
    credential_stripped: bool = False

    @property
    def ready(self) -> bool:
        """The one advertisement law: ready only after a first
        sync has completed successfully."""
        return self.state == READY

    @property
    def headline(self) -> str:
        return (f"{self.full_name} is a pull mirror of its source; "
                f"it is {_STATE_WORDS[self.state]}.")


@dataclass(frozen=True)
class FirstSyncResult:
    full_name: str
    state: str                # READY | FAILED
    synced_at: int
    detail: str

    @property
    def ready(self) -> bool:
        return self.state == READY


def _state_of(last_status: str | None) -> str:
    if last_status == "ok":
        return READY
    if last_status == "failed":
        return FAILED
    if last_status == SYNCING:
        return SYNCING
    return PENDING


def sanitize_git_url(source: object) -> tuple[str | Path, str, bool]:
    """Return (stored_source, kind, credential_stripped).

    The stored source never carries userinfo: credentials inside
    a URL are stripped here, at the door, and nowhere downstream
    ever sees them. Raises PullMirrorError in plain words.
    """
    if isinstance(source, Path):
        if not source.is_absolute() or not source.is_dir():
            raise PullMirrorError(
                "source_invalid",
                "A local mirror source must be an existing "
                "repository directory given as a full path.")
        return source, "local", False
    if not isinstance(source, str) or not source:
        raise PullMirrorError("source_invalid", "Empty mirror source.")
    if source.startswith("-") or any(
            ord(c) <= 0x20 or ord(c) == 0x7F for c in source):
        raise PullMirrorError(
            "source_invalid",
            "The mirror source carries whitespace or controls, "
            "or starts with a dash.")
    if source.startswith("file://"):
        parsed = urlparse(source)
        if parsed.netloc not in ("", "localhost"):
            raise PullMirrorError(
                "source_invalid",
                "A file:// mirror source must name a path on "
                "this instance, not another host.")
        path = Path(unquote(parsed.path))
        if not path.is_absolute() or not path.is_dir():
            raise PullMirrorError(
                "source_invalid",
                "A file:// mirror source must name an existing "
                "repository directory on this instance.")
        return path, "local", False
    if "://" not in source:
        raise PullMirrorError(
            "source_invalid",
            "The mirror source must be a git URL (https, http, "
            "git, or ssh) or a file:// URL on this instance.")
    parsed = urlparse(source)
    if parsed.scheme not in REMOTE_URL_SCHEMES:
        raise PullMirrorError(
            "source_invalid",
            f"Scheme {parsed.scheme!r} is not a remote git "
            "transport this instance will pull from.")
    if parsed.fragment:
        raise PullMirrorError(
            "source_invalid", "The mirror source carries a fragment.")
    stripped = bool(parsed.username or parsed.password)
    host = parsed.hostname or ""
    if not host:
        raise PullMirrorError(
            "source_invalid", "The mirror source has no host.")
    try:
        port = parsed.port
    except ValueError:
        raise PullMirrorError(
            "source_invalid",
            "The mirror source carries an invalid port.") from None
    netloc = f"[{host}]" if ":" in host and not host.startswith("[") else host
    if port is not None:
        netloc = f"{netloc}:{port}"
    clean = urlunparse((parsed.scheme, netloc, parsed.path, "",
                        parsed.query, ""))
    try:
        return validate_remote_url(clean), "url", stripped
    except ProcRefused as exc:
        raise PullMirrorError("source_invalid", str(exc)) from None


class PullMirrorService:
    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 accounts: AccountStore, repositories: RepositoryStore,
                 audit: AuditLog | None = None,
                 time_fn: Callable[[], float] = time.time,
                 fetch_timeout: float = 120.0):
        self._conn = conn
        self._mirrors = MirrorService(
            conn, data_root, accounts, repositories, audit=None,
            time_fn=time_fn, fetch_timeout=fetch_timeout)
        self._repos = repositories
        self._now = time_fn
        self._stripped: dict[int, bool] = {}

    # -- records ---------------------------------------------------
    def pull_mirror_for(self, owner, repo) -> PullMirror | None:
        mirror = self._mirrors.mirror_for(owner, repo)
        if mirror is None:
            return None
        return PullMirror(
            repo_id=mirror.repo_id, full_name=mirror.full_name,
            source=mirror.source, source_kind=mirror.source_kind,
            state=_state_of(mirror.last_status),
            created_at=mirror.created_at,
            last_sync_at=mirror.last_sync_at,
            last_detail=mirror.last_detail,
            credential_stripped=self._stripped.get(mirror.repo_id, False))

    def is_pull_mirror(self, owner, repo) -> bool:
        return self.pull_mirror_for(owner, repo) is not None

    def is_ready(self, owner, repo) -> bool:
        mirror = self.pull_mirror_for(owner, repo)
        return bool(mirror and mirror.ready)

    def advertisement(self, owner, repo) -> PullMirror | None:
        """What the repo may advertise about itself: the record,
        whose ``ready`` is True only after a completed first sync."""
        return self.pull_mirror_for(owner, repo)

    def list_pull_mirrors(self, owner) -> list[PullMirror]:
        found = []
        for repo in self._repos.list_for_owner(owner):
            mirror = self.pull_mirror_for(repo.owner, repo.name)
            if mirror is not None:
                found.append(mirror)
        return found

    # -- state writes ------------------------------------------------
    def _set_status(self, repo_id: int, status: str,
                    detail: str | None = None) -> None:
        with self._conn:
            if detail is None:
                self._conn.execute(
                    "UPDATE repo_mirrors SET last_status = ? "
                    "WHERE repo_id = ?", (status, repo_id))
            else:
                self._conn.execute(
                    "UPDATE repo_mirrors SET last_status = ?, "
                    "last_detail = ? WHERE repo_id = ?",
                    (status, detail, repo_id))

    # -- creation ----------------------------------------------------
    def begin_pull_mirror(self, actor_user_id: int, owner, repo,
                          source: object, *,
                          visibility: str = "private",
                          source_ip: str | None = None) -> PullMirror:
        """Create the repository as a pull mirror, state pending.

        The repo exists after this call; it does not advertise
        ready. Creation rides RepositoryStore's own ``repo.create``
        audit (inside create_repository) -- no new taxonomy event.
        """
        stored, kind, stripped = sanitize_git_url(source)
        try:
            mirror = self._mirrors.create_mirror(
                actor_user_id, owner, repo, stored,
                visibility=visibility, source_ip=source_ip)
        except (MirrorError, RepositoryError) as exc:
            raise PullMirrorError(exc.reason, str(exc)) from None
        self._stripped[mirror.repo_id] = stripped
        self._set_status(mirror.repo_id, PENDING,
                         "created; first sync has not run yet")
        created = self.pull_mirror_for(owner, repo)
        assert created is not None
        return created

    def complete_first_sync(self, owner, repo) -> FirstSyncResult:
        return self._sync(owner, repo)

    def sync_pull_mirror(self, owner, repo) -> FirstSyncResult:
        """Run a sync now (first or later) and record its outcome."""
        return self._sync(owner, repo)

    def _sync(self, owner, repo) -> FirstSyncResult:
        current = self.pull_mirror_for(owner, repo)
        if current is None:
            raise PullMirrorError(
                "not_a_mirror",
                "That repository is not a pull mirror.")
        self._set_status(current.repo_id, SYNCING, "sync running")
        result = self._mirrors.sync_mirror(owner, repo)
        state = READY if result.status == "ok" else FAILED
        return FirstSyncResult(
            full_name=result.full_name, state=state,
            synced_at=result.synced_at, detail=result.detail)

    def create_pull_mirror(self, actor_user_id: int, owner, repo,
                           source: object, *,
                           visibility: str = "private",
                           source_ip: str | None = None) -> PullMirror:
        """Create a pull mirror and run its first sync before
        returning: the returned record advertises ready only when
        that first sync actually completed."""
        created = self.begin_pull_mirror(
            actor_user_id, owner, repo, source,
            visibility=visibility, source_ip=source_ip)
        self._sync(owner, repo)
        after = self.pull_mirror_for(owner, repo)
        assert after is not None
        return after
