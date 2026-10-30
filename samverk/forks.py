"""Forking (S-055).

A fork is a server-side clone with its upstream link recorded:

- **Clone, not reference.** `git clone --bare` (through S-014,
  both paths from S-013) gives the fork its own complete object
  store: deleting or rewriting the upstream can never break it.
  The `fork_of_id` column on the repository row is lineage only.
- **Read gate first.** Forking requires read access under
  S-054's one permission function. A private repository the
  actor cannot read answers as if it did not exist — its
  existence is itself private.
- **No visibility escalation.** A fork of a private source is
  private. A public source may be forked private or public;
  a private source forked "public" is refused by name.
- **Network.** `fork_count` counts direct forks; `network_for`
  walks to the root (a fork of a fork belongs to the root's
  network) and lists root + every descendant, name-sorted.
  Audited `repo.fork` (S-055 taxonomy addition).
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from .accounts import AccountStore
from .audit import AuditLog
from .permissions import can_read
from .platform_seam import ensure_dir
from .proc import run_git
from .repo_paths import RepoPathError
from .repositories import (
    Repository, RepositoryError, RepositoryStore, _validate_visibility,
    canonical_owner_repo)


class ForkError(RepositoryError):
    pass


class ForkStore:
    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 accounts: AccountStore, repositories: RepositoryStore,
                 audit: AuditLog | None = None):
        self._conn = conn
        self._data_root = Path(data_root)
        self._accounts = accounts
        self._repos = repositories
        self._audit = audit

    def fork(self, actor_user_id: int, source_owner: object,
             source_repo: object, dest_repo: object = None, *,
             visibility: str | None = None,
             source_ip: str | None = None) -> Repository:
        actor = self._accounts.get_by_id(actor_user_id)
        if actor is None:
            raise ForkError("no_such_user", "No such account.")
        source = self._repos.get_repository(source_owner, source_repo)
        # Read gate: an unreadable private repo is "not found".
        if source is None or not can_read(actor, source):
            raise ForkError("no_such_repo", "No such repository.")
        raw_dest = source.name if dest_repo is None else dest_repo
        try:
            _, _, dest_name, dest_lower = canonical_owner_repo(
                actor.username, raw_dest)
        except RepositoryError as exc:
            raise ForkError(exc.reason, str(exc)) from None
        # Destination belongs to the actor (forking into your own
        # account; org destinations arrive with Part IX orgs).
        if self._repos.get_repository(actor.username, dest_name) is not None:
            raise ForkError("repo_taken",
                            f"{actor.username}/{dest_name} already exists.")
        new_visibility = source.visibility if visibility is None \
            else _validate_visibility(visibility)
        if source.visibility == "private" and new_visibility == "public":
            raise ForkError(
                "fork_visibility_escalation",
                "A private repository cannot be forked into a public one.")
        try:
            dest_path = self._repos.path_for(actor.username, dest_name)
            src_path = self._repos.path_for(source.owner, source.name)
        except RepoPathError as exc:
            raise ForkError("repo_invalid", str(exc)) from None
        if dest_path.exists():
            raise ForkError("repo_path_exists",
                            "A directory already exists at that path.")
        ensure_dir(dest_path.parent)
        result = run_git(["clone", "--bare", str(src_path), str(dest_path)],
                         timeout=120.0)
        if result.returncode != 0:
            shutil.rmtree(dest_path, ignore_errors=True)
            raise ForkError(
                "git_clone_failed",
                "git could not clone the repository: "
                + result.stderr.decode("utf-8", "replace").strip()[:200])
        import time
        now = int(time.time())
        try:
            with self._conn:
                cur = self._conn.execute(
                    "INSERT INTO repositories (owner, owner_lower, name,"
                    " name_lower, created_by, created_at, description,"
                    " visibility, default_branch, fork_of_id)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (actor.username, actor.username_lower, dest_name,
                     dest_lower, actor.id, now,
                     source.description, new_visibility,
                     source.default_branch, source.id))
                fork_id = int(cur.lastrowid)
        except Exception:
            shutil.rmtree(dest_path, ignore_errors=True)
            raise
        fork = self._repos.get_by_id(fork_id)
        assert fork is not None
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id, action="repo.fork",
                target_kind="repo", target_id=fork.full_name,
                outcome="success", source_ip=source_ip,
                detail={"fork_of": source.full_name})
        return fork

    def fork_count(self, repo_id: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM repositories WHERE fork_of_id = ?",
            (repo_id,)).fetchone()
        return int(row["c"])

    def upstream_of(self, repo: Repository) -> Repository | None:
        if repo.fork_of_id is None:
            return None
        return self._repos.get_by_id(repo.fork_of_id)

    def network_root(self, repo: Repository) -> Repository:
        seen: set[int] = set()
        current = repo
        while current.fork_of_id is not None and current.id not in seen:
            seen.add(current.id)
            parent = self._repos.get_by_id(current.fork_of_id)
            if parent is None:  # upstream deleted: this fork is a root now
                break
            current = parent
        return current

    def network_for(self, repo: Repository) -> list[Repository]:
        root = self.network_root(repo)
        members = [root]
        frontier = [root.id]
        seen = {root.id}
        while frontier:
            rows = self._conn.execute(
                "SELECT * FROM repositories WHERE fork_of_id IN (%s)"
                % ",".join("?" * len(frontier)), frontier).fetchall()
            frontier = []
            for row in rows:
                child = self._repos.get_by_id(int(row["id"]))
                if child is not None and child.id not in seen:
                    seen.add(child.id)
                    members.append(child)
                    frontier.append(child.id)
        return sorted(members, key=lambda r: r.full_name.lower())
