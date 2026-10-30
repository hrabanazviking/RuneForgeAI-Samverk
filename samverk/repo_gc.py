"""Garbage-collection scheduling (S-059).

Loose git objects accumulate with every push; left alone they
slow every read. `git gc` repacks them — but gc can take real
time on a large repository, so it must never run on a request
path (roadmap acceptance: *no request waits on gc*).

The shape here enforces that by construction:

- **Policy is a pure function** of measured facts — repository
  size, loose-object count, days since the last push activity —
  returning an interval and a level. Big or busy repositories
  are collected daily (aggressively when very large); small,
  quiet ones monthly.
- **Scheduling only records.** `assess` measures a repository
  and writes its due time into `repo_gc_state`; it spawns
  nothing. A request handler may call it freely — the worst it
  costs is a directory walk.
- **Running is a separate, off-path entry point.** `run_due`
  is called by a background worker / operator command, never
  by a request handler. It runs `git gc` through S-014's law
  for every repository whose due time has passed, records the
  outcome (ok / failed, with the next due time computed from
  the same policy), and a failed gc is recorded — never raised
  into anyone's request, never hidden.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .proc import run_git_in
from .repo_size import measure_path
from .repositories import RepositoryStore

DAY = 24 * 3600
LARGE_BYTES = 32 * 1024 * 1024
MEDIUM_BYTES = 1 * 1024 * 1024
LARGE_LOOSE = 500
MEDIUM_LOOSE = 50


@dataclass(frozen=True)
class GCPolicy:
    needed: bool
    interval_seconds: int
    level: str            # "standard" | "aggressive"
    reason: str


def gc_policy(*, total_bytes: int, loose_objects: int) -> GCPolicy:
    """The per-repo gc policy, from size/activity facts alone."""
    if loose_objects <= 0:
        return GCPolicy(False, 30 * DAY, "standard",
                        "no loose objects to pack")
    if total_bytes >= LARGE_BYTES or loose_objects >= LARGE_LOOSE:
        return GCPolicy(True, DAY, "aggressive",
                        "large or loose-heavy repository: daily aggressive gc")
    if total_bytes >= MEDIUM_BYTES or loose_objects >= MEDIUM_LOOSE:
        return GCPolicy(True, 7 * DAY, "standard",
                        "medium repository: weekly gc")
    return GCPolicy(True, 30 * DAY, "standard",
                    "small repository: monthly gc")


def count_loose_objects(repo_path: Path) -> int:
    objects = Path(repo_path) / "objects"
    count = 0
    if objects.is_dir():
        for entry in objects.iterdir():
            if (len(entry.name) == 2 and entry.is_dir()
                    and all(c in "0123456789abcdef" for c in entry.name)):
                count += sum(1 for f in entry.iterdir() if f.is_file())
    return count


@dataclass(frozen=True)
class GCState:
    repo_id: int
    last_run_at: int | None
    last_status: str | None
    next_due_at: int
    runs: int


class GCScheduler:
    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 repositories: RepositoryStore,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._data_root = Path(data_root)
        self._repos = repositories
        self._now = time_fn

    # -- measurement / scheduling (request-safe: spawns nothing) --
    def assess(self, owner, repo) -> GCState:
        """Measure one repository and record when its gc is due.

        Never runs gc: scheduling and running are separate by
        design, so no caller of this method can ever wait on gc.
        """
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise ValueError("no_such_repo")
        path = self._repos.path_for(current.owner, current.name)
        size = measure_path(path)
        policy = gc_policy(total_bytes=size.total_bytes,
                           loose_objects=count_loose_objects(path))
        now = int(self._now())
        row = self._conn.execute(
            "SELECT * FROM repo_gc_state WHERE repo_id = ?",
            (current.id,)).fetchone()
        last_run = row["last_run_at"] if row else None
        if not policy.needed:
            next_due = now + policy.interval_seconds
        elif last_run is None:
            next_due = now            # never collected and needs it: due
        else:
            next_due = int(last_run) + policy.interval_seconds
        with self._conn:
            self._conn.execute(
                "INSERT INTO repo_gc_state (repo_id, last_run_at,"
                " last_status, next_due_at, runs) VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(repo_id) DO UPDATE SET"
                " next_due_at = excluded.next_due_at",
                (current.id, last_run,
                 row["last_status"] if row else None, next_due,
                 row["runs"] if row else 0))
        return self.state_for(current.id)

    def state_for(self, repo_id: int) -> GCState:
        row = self._conn.execute(
            "SELECT * FROM repo_gc_state WHERE repo_id = ?",
            (repo_id,)).fetchone()
        if row is None:
            return GCState(repo_id, None, None, 0, 0)
        return GCState(row["repo_id"], row["last_run_at"],
                       row["last_status"], row["next_due_at"], row["runs"])

    def due_repo_ids(self, now: int | None = None) -> list[int]:
        now = int(self._now()) if now is None else now
        rows = self._conn.execute(
            "SELECT repo_id FROM repo_gc_state WHERE next_due_at <= ?"
            " AND (last_run_at IS NULL OR last_run_at < next_due_at)"
            " ORDER BY repo_id", (now,)).fetchall()
        return [r["repo_id"] for r in rows]

    # -- running (off-path only: background worker / operator) ----
    def run_due(self, now: int | None = None) -> list[tuple[int, str]]:
        """Run gc for every due repository. Returns (repo_id, status).

        This is the *only* method that spawns gc, and it is never
        called from a request handler — that separation is the
        acceptance criterion made structural.
        """
        now = int(self._now()) if now is None else now
        results: list[tuple[int, str]] = []
        for repo_id in self.due_repo_ids(now):
            current = self._repos.get_by_id(repo_id)
            if current is None:
                continue
            path = self._repos.path_for(current.owner, current.name)
            size = measure_path(path)
            policy = gc_policy(
                total_bytes=size.total_bytes,
                loose_objects=count_loose_objects(path))
            args = ["gc", "--quiet"]
            if policy.level == "aggressive":
                args.append("--aggressive")
            try:
                result = run_git_in(path, args, timeout=600.0)
                status = "ok" if result.returncode == 0 else "failed"
            except Exception:
                status = "failed"
            with self._conn:
                self._conn.execute(
                    "UPDATE repo_gc_state SET last_run_at = ?,"
                    " last_status = ?, next_due_at = ?,"
                    " runs = runs + 1 WHERE repo_id = ?",
                    (now, status, now + policy.interval_seconds, repo_id))
            results.append((repo_id, status))
        return results
