"""Commit graph caches (S-072).

Derived data — commit counts, contributor lists, branch and
tag counts — is too expensive to recompute on every browse of
a busy repository, and too important to serve stale without
knowing it. This cache holds it under one discipline, the
same off-path shape as S-059's gc scheduler:

- **The fingerprint is the refs.** A cache row is keyed by a
  SHA-256 over every ref name + oid (sorted). Any push that
  moves a ref changes the fingerprint; a cached row whose
  fingerprint no longer matches the live refs is *stale* and
  is never served as current.
- **Reading never computes.** `cached_stats` only reads the
  stored row and compares fingerprints (one `for-each-ref`
  spawn, S-052). The heavy walk — `git log --all` over every
  commit — happens only in `refresh`, the off-path entry
  point a background worker or a push hook calls.
- **Invalidation is explicit.** `invalidate` (the call the
  receive path makes on push) drops the row at once; even
  without it, the fingerprint comparison alone refuses to
  serve a stale row. Belt and braces, deliberately.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .proc import run_git_in
from .refs import RefStore
from .repositories import Repository, RepositoryStore


class GraphCacheError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class GraphStats:
    full_name: str
    commit_count: int
    contributors: tuple[str, ...]
    branch_count: int
    tag_count: int
    fingerprint: str
    computed_at: int


def refs_fingerprint(repo_path: Path) -> str:
    """SHA-256 over the sorted (ref, oid) set — the cache key."""
    refs = RefStore(repo_path).list_refs()
    digest = hashlib.sha256()
    for ref in sorted(refs, key=lambda r: r.name):
        digest.update(f"{ref.name} {ref.oid}\n".encode())
    return digest.hexdigest()


class GraphCache:
    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 repositories: RepositoryStore,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._data_root = Path(data_root)
        self._repos = repositories
        self._now = time_fn

    def _repo(self, owner, repo) -> Repository:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise GraphCacheError("no_such_repo", "No such repository.")
        return current

    # -- read path (never computes the walk) ----------------------
    def cached_stats(self, owner, repo) -> GraphStats | None:
        """The stored stats, or None when absent or stale.

        Staleness is proven by fingerprint, not by age: a row
        whose fingerprint differs from the live refs answers
        None exactly as a missing row does.
        """
        current = self._repo(owner, repo)
        row = self._conn.execute(
            "SELECT * FROM repo_graph_cache WHERE repo_id = ?",
            (current.id,)).fetchone()
        if row is None:
            return None
        path = self._repos.path_for(current.owner, current.name)
        if row["fingerprint"] != refs_fingerprint(path):
            return None
        return GraphStats(
            full_name=current.full_name,
            commit_count=row["commit_count"],
            contributors=tuple(json.loads(row["contributors"])),
            branch_count=row["branch_count"], tag_count=row["tag_count"],
            fingerprint=row["fingerprint"], computed_at=row["computed_at"])

    def is_stale(self, owner, repo) -> bool:
        return self.cached_stats(owner, repo) is None

    # -- invalidation (the push path's call) -----------------------
    def invalidate(self, owner, repo) -> None:
        current = self._repo(owner, repo)
        with self._conn:
            self._conn.execute(
                "DELETE FROM repo_graph_cache WHERE repo_id = ?",
                (current.id,))

    # -- off-path computation ---------------------------------------
    def refresh(self, owner, repo) -> GraphStats:
        """Compute the derived data and store it. Off-path only:
        this walks the whole reachable history."""
        current = self._repo(owner, repo)
        path = self._repos.path_for(current.owner, current.name)
        refs = RefStore(path).list_refs()
        fingerprint = refs_fingerprint(path)
        branch_count = sum(1 for r in refs if r.is_branch)
        tag_count = sum(1 for r in refs if r.is_tag)
        commit_count, contributors = self._walk(path)
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "INSERT INTO repo_graph_cache (repo_id, fingerprint,"
                " commit_count, contributors, branch_count, tag_count,"
                " computed_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(repo_id) DO UPDATE SET"
                " fingerprint = excluded.fingerprint,"
                " commit_count = excluded.commit_count,"
                " contributors = excluded.contributors,"
                " branch_count = excluded.branch_count,"
                " tag_count = excluded.tag_count,"
                " computed_at = excluded.computed_at",
                (current.id, fingerprint, commit_count,
                 json.dumps(list(contributors)), branch_count, tag_count, now))
        return GraphStats(
            full_name=current.full_name, commit_count=commit_count,
            contributors=contributors, branch_count=branch_count,
            tag_count=tag_count, fingerprint=fingerprint, computed_at=now)

    @staticmethod
    def _walk(path: Path) -> tuple[int, tuple[str, ...]]:
        result = run_git_in(
            path, ["log", "--all", "--format=%H%x00%an <%ae>"],
            timeout=120.0)
        if result.returncode != 0:
            # An empty repository has no walkable history: that
            # is zero commits, honestly, not an error.
            return 0, ()
        seen: set[str] = set()
        authors: set[str] = set()
        for line in result.stdout.decode("utf-8", "replace").splitlines():
            oid, _, author = line.partition("\x00")
            if oid and oid not in seen:
                seen.add(oid)
                if author:
                    authors.add(author)
        return len(seen), tuple(sorted(authors))
