"""Sync scheduler (S-331) -- per-mirror sync intervals,
jittered, off the request path, with a manual sync-now
beside the schedule.

S-070 gave mirrors a recorded sync, S-329 made them pull
mirrors, and S-330 let them name a credential. What was
missing was *when*: a mirror synced only when someone
asked. This module is the clock, and its law is plain:

- **The founding cadence is 24 hours.** A mirror with no
  interval of its own syncs every ``86400`` seconds --
  the cadence the roadmap names as the founding one.
  ``repo_mirrors.sync_interval_seconds`` (migration 134)
  is NULL for such a mirror; a stored value is that
  mirror's own interval, set by its owner alone.
- **Jittered, never exact.** Each next sync is the
  interval plus up to ten percent more, drawn from an
  injected random source, so a fleet of mirrors created
  together does not thunder against its sources in one
  instant. The delay is always at least the interval
  and always less than 1.1 times it.
- **Off the request path.** Nothing in this module is
  called by a request handler. ``run_due`` is the
  scheduler entry point: an external runner or
  scheduler tick calls it, it syncs what is due, and
  each mirror's ``next_sync_at`` advances whether the
  sync succeeded or failed -- a broken source is
  retried next interval, never spun on hot.
- **Manual beside automatic.** ``sync_now`` is the
  owner's hand on the same road: it syncs at once,
  due or not, and the schedule resumes from that sync.
- **Credentials keep working.** Every sync -- due or
  manual -- goes through S-330's
  ``MirrorCredentialService``, so a named credential is
  resolved and scrubbed exactly as before. A
  ``credential_unavailable`` refusal counts as a failed
  run with that plain-words detail and still advances
  the schedule: never a silent unauthenticated sync,
  never a hot spin.
- **Witnessed, values never.** Setting and resetting an
  interval ride the standing ``repo.settings.change``
  verb under keys ``mirror_sync_interval.set`` /
  ``mirror_sync_interval.reset``, the detail naming the
  interval in seconds -- never any secret. No new
  taxonomy event: 138 stand.

Storage is migration 134 (schema 133 -> 134):
``repo_mirrors.sync_interval_seconds`` and
``repo_mirrors.next_sync_at`` -- times and counts only.
"""
from __future__ import annotations
import random
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from .accounts import AccountStore
from .audit import AuditLog
from .mirror_credentials import MirrorCredentialError, MirrorCredentialService
from .repositories import RepositoryStore
from .secrets import Secrets

__all__ = [
    "DEFAULT_INTERVAL_SECONDS", "ScheduledSyncResult",
    "SyncSchedule", "SyncSchedulerError",
    "SyncSchedulerService", "compute_next", "jittered_delay",
    "schedule_to_dict", "validate_interval",
]

DEFAULT_INTERVAL_SECONDS = 86400
MIN_INTERVAL_SECONDS = 60
MAX_INTERVAL_SECONDS = 30 * 86400


class SyncSchedulerError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def validate_interval(value: object) -> int:
    """Pure: one sync interval in seconds -- a whole
    number (never a bool) from one minute to thirty
    days. Anything else is refused ``interval_invalid``
    in plain words."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise SyncSchedulerError(
            "interval_invalid",
            "Sync interval: a whole number of seconds "
            f"between {MIN_INTERVAL_SECONDS} and "
            f"{MAX_INTERVAL_SECONDS}.")
    if value < MIN_INTERVAL_SECONDS or value > MAX_INTERVAL_SECONDS:
        raise SyncSchedulerError(
            "interval_invalid",
            "Sync interval: a whole number of seconds "
            f"between {MIN_INTERVAL_SECONDS} and "
            f"{MAX_INTERVAL_SECONDS}.")
    return value


def jittered_delay(interval: int, rand: float) -> int:
    """Pure: the delay before the next sync -- the
    interval plus up to ten percent jitter. ``rand`` is
    a float in [0, 1); the result is always >= interval
    and < 1.1 * interval."""
    return interval + int(interval * 0.1 * rand)


def compute_next(now: int, interval: int, rand: float) -> int:
    """Pure: the next sync moment after ``now``."""
    return int(now) + jittered_delay(interval, rand)


@dataclass(frozen=True)
class SyncSchedule:
    repo_id: int
    full_name: str
    interval_seconds: int
    stored_interval_seconds: int | None
    next_sync_at: int | None
    last_sync_at: int | None
    last_status: str | None

    @property
    def is_default_interval(self) -> bool:
        return self.stored_interval_seconds is None

    @property
    def headline(self) -> str:
        if self.is_default_interval:
            return (f"{self.full_name} syncs on the default "
                    f"interval of {self.interval_seconds} seconds "
                    "(24 hours).")
        return (f"{self.full_name} syncs every "
                f"{self.interval_seconds} seconds.")


@dataclass(frozen=True)
class ScheduledSyncResult:
    full_name: str
    status: str
    synced_at: int
    detail: str
    next_sync_at: int


def schedule_to_dict(schedule: SyncSchedule) -> dict:
    """The public facts of one schedule -- times and
    counts only, no secrets anywhere."""
    return {
        "full_name": schedule.full_name,
        "interval_seconds": schedule.interval_seconds,
        "is_default_interval": schedule.is_default_interval,
        "next_sync_at": schedule.next_sync_at,
        "last_sync_at": schedule.last_sync_at,
        "last_status": schedule.last_status,
    }


class SyncSchedulerService:
    """Per-mirror sync schedules over S-070's mirror
    records: owner-set intervals, jittered next-sync
    moments, a due-runner for an external scheduler
    tick, and a manual sync-now -- every sync through
    S-330's credential-aware road."""

    def __init__(self, conn: sqlite3.Connection,
                 data_root: Path,
                 accounts: AccountStore,
                 repositories: RepositoryStore,
                 audit: AuditLog | None = None,
                 time_fn: Callable[[], float] = time.time,
                 rand_fn: Callable[[], float] = random.random,
                 secrets: Secrets | None = None):
        self._conn = conn
        self._accounts = accounts
        self._repos = repositories
        self._audit = audit
        self._now = time_fn
        self._rand = rand_fn
        self._secrets = secrets
        self._creds = MirrorCredentialService(
            conn, data_root, accounts, repositories,
            audit=None, time_fn=time_fn)

    # -- records -------------------------------------------
    def _row_for(self, owner, repo):
        current = self._repos.get_repository(owner, repo)
        if current is None:
            return None, None
        row = self._conn.execute(
            "SELECT * FROM repo_mirrors WHERE repo_id = ?",
            (current.id,)).fetchone()
        return current, row

    @staticmethod
    def _to_schedule(current, row) -> SyncSchedule:
        stored = row["sync_interval_seconds"]
        return SyncSchedule(
            repo_id=row["repo_id"], full_name=current.full_name,
            interval_seconds=(stored if stored is not None
                              else DEFAULT_INTERVAL_SECONDS),
            stored_interval_seconds=stored,
            next_sync_at=row["next_sync_at"],
            last_sync_at=row["last_sync_at"],
            last_status=row["last_status"])

    def schedule_for(self, owner, repo) -> SyncSchedule | None:
        current, row = self._row_for(owner, repo)
        if current is None or row is None:
            return None
        return self._to_schedule(current, row)

    # -- guards ----------------------------------------------
    def _guard(self, actor_id, owner, repo) -> SyncSchedule:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise SyncSchedulerError(
                "no_such_repo", "No such repository.")
        actor = self._accounts.get_by_id(actor_id) \
            if isinstance(actor_id, int) else None
        if actor is None:
            raise SyncSchedulerError(
                "no_such_user", "No such account.")
        schedule = self.schedule_for(owner, repo)
        if schedule is None:
            raise SyncSchedulerError(
                "not_a_mirror",
                "That repository is not a mirror; only a "
                "mirror carries a sync schedule.")
        if actor.username_lower != current.owner_lower:
            raise SyncSchedulerError(
                "not_repo_owner",
                "Only the repository's owner can manage "
                "its mirror sync schedule.")
        return schedule

    def _witness(self, actor_id: int, schedule: SyncSchedule,
                 key: str, interval: int,
                 source_ip: str | None = None) -> None:
        if self._audit is None:
            return
        self._audit.append(
            actor_kind="user", actor_id=actor_id,
            action="repo.settings.change", target_kind="repo",
            target_id=schedule.full_name, outcome="success",
            source_ip=source_ip,
            detail={"key": key, "interval_seconds": interval})

    # -- interval acts -----------------------------------------
    def set_interval(self, actor_id, owner, repo, seconds,
                     source_ip: str | None = None) -> SyncSchedule:
        schedule = self._guard(actor_id, owner, repo)
        interval = validate_interval(seconds)
        nxt = compute_next(int(self._now()), interval, self._rand())
        with self._conn:
            self._conn.execute(
                "UPDATE repo_mirrors SET sync_interval_seconds = ?,"
                " next_sync_at = ? WHERE repo_id = ?",
                (interval, nxt, schedule.repo_id))
        after = self.schedule_for(owner, repo)
        assert after is not None
        self._witness(actor_id, after, "mirror_sync_interval.set",
                      interval, source_ip=source_ip)
        return after

    def reset_interval(self, actor_id, owner, repo,
                       source_ip: str | None = None) -> SyncSchedule:
        schedule = self._guard(actor_id, owner, repo)
        nxt = compute_next(int(self._now()),
                           DEFAULT_INTERVAL_SECONDS, self._rand())
        with self._conn:
            self._conn.execute(
                "UPDATE repo_mirrors SET sync_interval_seconds = NULL,"
                " next_sync_at = ? WHERE repo_id = ?",
                (nxt, schedule.repo_id))
        after = self.schedule_for(owner, repo)
        assert after is not None
        self._witness(actor_id, after, "mirror_sync_interval.reset",
                      DEFAULT_INTERVAL_SECONDS, source_ip=source_ip)
        return after

    # -- scheduling ----------------------------------------------
    def ensure_schedule(self, owner, repo) -> SyncSchedule | None:
        """Give a mirror with no next-sync moment one:
        (last sync, or creation when never synced) plus
        the jittered delay of its effective interval.
        Idempotent -- a mirror already scheduled is
        returned untouched."""
        current, row = self._row_for(owner, repo)
        if current is None or row is None:
            return None
        if row["next_sync_at"] is not None:
            return self._to_schedule(current, row)
        schedule = self._to_schedule(current, row)
        base = row["last_sync_at"] or row["created_at"]
        nxt = compute_next(int(base), schedule.interval_seconds,
                           self._rand())
        with self._conn:
            self._conn.execute(
                "UPDATE repo_mirrors SET next_sync_at = ?"
                " WHERE repo_id = ?", (nxt, schedule.repo_id))
        return self.schedule_for(owner, repo)

    def due_schedules(self, now: int | None = None) -> list[SyncSchedule]:
        """Every mirror whose next sync has fallen due,
        ordered by next_sync_at then repo_id. Mirrors
        with no schedule yet (legacy rows) are first
        given one from their creation moment plus their
        interval, so they become due-able on the same
        law as every other mirror."""
        moment = int(self._now()) if now is None else int(now)
        rows = self._conn.execute(
            "SELECT repo_id FROM repo_mirrors"
            " WHERE next_sync_at IS NULL").fetchall()
        for r in rows:
            repo_row = self._conn.execute(
                "SELECT owner, name FROM repositories WHERE id = ?",
                (r["repo_id"],)).fetchone()
            if repo_row is not None:
                self.ensure_schedule(repo_row["owner"], repo_row["name"])
        due = self._conn.execute(
            "SELECT m.* FROM repo_mirrors m"
            " WHERE m.next_sync_at IS NOT NULL AND m.next_sync_at <= ?"
            " ORDER BY m.next_sync_at, m.repo_id", (moment,)).fetchall()
        out = []
        for row in due:
            repo_row = self._conn.execute(
                "SELECT owner, name FROM repositories WHERE id = ?",
                (row["repo_id"],)).fetchone()
            current = self._repos.get_repository(
                repo_row["owner"], repo_row["name"])
            out.append(self._to_schedule(current, row))
        return out

    # -- running ---------------------------------------------------
    def _advance(self, schedule: SyncSchedule, synced_at: int) -> int:
        nxt = compute_next(int(synced_at), schedule.interval_seconds,
                           self._rand())
        with self._conn:
            self._conn.execute(
                "UPDATE repo_mirrors SET next_sync_at = ?"
                " WHERE repo_id = ?", (nxt, schedule.repo_id))
        return nxt

    def _sync_one(self, schedule: SyncSchedule) -> ScheduledSyncResult:
        owner, _, repo = schedule.full_name.partition("/")
        try:
            result = self._creds.sync_mirror(
                owner, repo, secrets=self._secrets)
            status, detail, synced_at = (
                result.status, result.detail, result.synced_at)
        except MirrorCredentialError as exc:
            status, detail = "failed", str(exc)
            synced_at = int(self._now())
            with self._conn:
                self._conn.execute(
                    "UPDATE repo_mirrors SET last_sync_at = ?,"
                    " last_status = ?, last_detail = ?,"
                    " last_objects_moved = 0"
                    " WHERE repo_id = ?",
                    (synced_at, status, detail[:200], schedule.repo_id))
        nxt = self._advance(schedule, synced_at)
        return ScheduledSyncResult(
            full_name=schedule.full_name, status=status,
            synced_at=synced_at, detail=detail, next_sync_at=nxt)

    def run_due(self, now: int | None = None,
                limit: int | None = None) -> list[ScheduledSyncResult]:
        """The scheduler entry point -- called by an
        external runner / scheduler tick, NEVER from a
        request handler. Syncs each due mirror through
        S-330's credential road and advances its next
        sync whether the run was ok or failed."""
        due = self.due_schedules(now=now)
        if limit is not None:
            due = due[:limit]
        return [self._sync_one(s) for s in due]

    def sync_now(self, actor_id, owner, repo,
                 source_ip: str | None = None) -> ScheduledSyncResult:
        """Manual sync-now beside the schedule: the
        owner syncs at once, due or not, and the
        schedule resumes from this sync."""
        schedule = self._guard(actor_id, owner, repo)
        return self._sync_one(schedule)
