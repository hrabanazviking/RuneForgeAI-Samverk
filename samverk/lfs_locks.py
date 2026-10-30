"""LFS locking (S-062).

Git LFS locks keep two editors from rewriting the same
unmergeable binary at once. The lock API (public LFS spec):

- `POST /locks` — lock a *path* (locks name files, not
  objects: the same content may live at many paths, but a
  path has one editor at a time).
- `GET /locks` — list, filterable by path or id.
- `POST /locks/verify` — the push-time split every client
  asks for: *ours* (locks the caller holds) and *theirs*.
- `POST /locks/<id>/unlock` — release; the lock's owner may
  always release their own, and a repository admin may
  force-release another's only by saying so (`force`).

Rules: locking needs write permission (S-054's one
function); listing and verifying need read. A path already
locked — by anyone, including the caller — refuses with
the existing lock named, so a client can show exactly who
holds it. Lock ids are 128-bit random hex: unguessable,
never sequential.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .accounts import AccountStore
from .lfs_api import LFSApiError
from .permissions import can_admin, can_read, can_write
from .repositories import Repository, RepositoryStore

MAX_PATH = 1024


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


class LFSLockError(LFSApiError):
    pass


def _lock_dict(row) -> dict:
    return {"id": row["id"], "path": row["path"],
            "locked_at": _iso(row["locked_at"]),
            "owner": {"name": row["owner_name"]}}


class LFSLocking:
    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 accounts: AccountStore, repositories: RepositoryStore,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._data_root = Path(data_root)
        self._accounts = accounts
        self._repos = repositories
        self._now = time_fn

    # -- helpers ---------------------------------------------------
    def _repo_and_actor(self, actor_user_id, owner, repo, *, need: str):
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise LFSLockError("no_such_repo", "No such repository.", 404)
        actor = (self._accounts.get_by_id(actor_user_id)
                 if actor_user_id is not None else None)
        check = {"read": can_read, "write": can_write,
                 "admin": can_admin}[need]
        if not check(actor, current):
            raise LFSLockError("no_such_repo", "No such repository.", 404)
        return actor, current

    @staticmethod
    def _validate_path(path: object) -> str:
        if (not isinstance(path, str) or not path or len(path) > MAX_PATH
                or path.startswith("/") or "\\" in path
                or any(part in ("..",) for part in path.split("/"))):
            raise LFSLockError("path_invalid", "That lock path is not valid.")
        return path

    def _row(self, repo_id: int, *, path=None, lock_id=None):
        if lock_id is not None:
            return self._conn.execute(
                "SELECT * FROM lfs_locks WHERE repo_id = ? AND id = ?",
                (repo_id, lock_id)).fetchone()
        return self._conn.execute(
            "SELECT * FROM lfs_locks WHERE repo_id = ? AND path = ?",
            (repo_id, path)).fetchone()

    # -- the operations ---------------------------------------------
    def lock(self, actor_user_id, owner, repo, path) -> dict:
        actor, current = self._repo_and_actor(actor_user_id, owner, repo,
                                              need="write")
        path = self._validate_path(path)
        existing = self._row(current.id, path=path)
        if existing is not None:
            err = LFSLockError(
                "already_locked",
                f"{path} is already locked by {existing['owner_name']}.",
                403)
            err.existing = _lock_dict(existing)  # type: ignore[attr-defined]
            raise err
        lock_id = secrets.token_hex(16)
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "INSERT INTO lfs_locks (id, repo_id, path, owner_user_id,"
                " owner_name, locked_at) VALUES (?, ?, ?, ?, ?, ?)",
                (lock_id, current.id, path, actor.id, actor.username, now))
        return _lock_dict(self._row(current.id, lock_id=lock_id))

    def unlock(self, actor_user_id, owner, repo, lock_id,
               *, force: bool = False) -> dict:
        actor, current = self._repo_and_actor(actor_user_id, owner, repo,
                                              need="read")
        row = self._row(current.id, lock_id=lock_id)
        if row is None:
            raise LFSLockError("no_such_lock", "No such lock.", 404)
        mine = actor is not None and actor.id == row["owner_user_id"]
        if not mine and not (force and can_admin(actor, current)):
            raise LFSLockError(
                "not_lock_owner",
                "Only the lock's owner can release it (an admin may force).",
                403)
        with self._conn:
            self._conn.execute(
                "DELETE FROM lfs_locks WHERE repo_id = ? AND id = ?",
                (current.id, lock_id))
        return _lock_dict(row)

    def list_locks(self, actor_user_id, owner, repo, *,
                   path=None, lock_id=None) -> list[dict]:
        _, current = self._repo_and_actor(actor_user_id, owner, repo,
                                          need="read")
        sql = "SELECT * FROM lfs_locks WHERE repo_id = ?"
        args: list = [current.id]
        if path is not None:
            sql += " AND path = ?"; args.append(path)
        if lock_id is not None:
            sql += " AND id = ?"; args.append(lock_id)
        sql += " ORDER BY locked_at, id"
        return [_lock_dict(r) for r in self._conn.execute(sql, args)]

    def verify(self, actor_user_id, owner, repo) -> dict:
        actor, current = self._repo_and_actor(actor_user_id, owner, repo,
                                              need="read")
        ours, theirs = [], []
        for row in self._conn.execute(
                "SELECT * FROM lfs_locks WHERE repo_id = ?"
                " ORDER BY locked_at, id", (current.id,)):
            (ours if actor is not None
             and row["owner_user_id"] == actor.id else theirs).append(
                _lock_dict(row))
        return {"ours": ours, "theirs": theirs}

    # -- HTTP adapter (called by lfs_api.make_lfs_handler) ---------
    def _owner_repo(self, handler) -> tuple[str, str]:
        parts = urlparse(handler.path).path.split("/")
        return parts[1], parts[2]

    def handle_post(self, handler, api) -> None:
        owner, repo = self._owner_repo(handler)
        raw = handler._body()
        body = json.loads(raw.decode("utf-8") or "{}")
        actor = handler._actor()
        path = urlparse(handler.path).path
        if path.endswith("/locks"):
            created = self.lock(actor, owner, repo, body.get("path"))
            handler._json(201, {"lock": created})
        elif path.endswith("/locks/verify"):
            handler._json(200, self.verify(actor, owner, repo))
        elif path.endswith("/unlock"):
            lock_id = path.split("/")[-2]
            released = self.unlock(actor, owner, repo, lock_id,
                                   force=bool(body.get("force")))
            handler._json(200, {"lock": released})
        else:
            handler._json(404, {"message": "Not found."})

    def handle_get(self, handler, api) -> None:
        owner, repo = self._owner_repo(handler)
        query = parse_qs(urlparse(handler.path).query)
        locks = self.list_locks(
            handler._actor(), owner, repo,
            path=query.get("path", [None])[0],
            lock_id=query.get("id", [None])[0])
        handler._json(200, {"locks": locks})
