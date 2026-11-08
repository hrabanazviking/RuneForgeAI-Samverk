"""Index health (S-215).

Admin-visible index state, lag, and rebuild trigger;
lag is shown, never hidden — Part X's operations door
over the S-205 index architecture, written from
research file 18. S-205 fixed the state itself (the
per-(repository, kind) freshness, the queue, the
generation rebuilds) and said plainly that its own
rebuild request is an internal seam whose
admin-facing, audited door is this slice. This slice
builds exactly that door: the health read and the
rebuild trigger. It invents no second state.

- **Admin-visible means site admins only.** Every
  face — one repository's health, the whole
  instance's health, and the rebuild trigger —
  demands a real account with `is_admin` (an unknown
  viewer answers `no_such_user`, a signed-in
  non-admin `not_site_admin`), checked before any
  index row is read. Repository visibility grants
  nothing here: this is the operator's page, not a
  reader's, so a private repository's *freshness*
  (never its content — no title, snippet, or
  document text is ever read) is an admin fact like
  its disk usage.
- **The state shown is S-205's own.** A repository's
  health is its four `IndexState` rows exactly as
  `SearchIndexStore.states_for_repo` reports them —
  status in words, generation, high-water mark,
  document count, last error — and the queue's
  position is `queue_snapshot`. This module stores
  nothing and caches nothing: every read is computed
  from the index tables as they stand, so the page
  cannot drift from the worker's truth.
- **Lag is shown, never hidden.** Lag is a computed
  age, never an asserted one: the instance lag is
  the queue snapshot's own `lag_seconds` (the age of
  the oldest waiting job), and each repository
  carries its own lag the same way — the age of its
  oldest waiting job, 0 when nothing waits. Lag is
  rendered on every page, including when it is 0 and
  when a kind has never been indexed: an index that
  is behind says so in numbers and in words, and an
  index that has never run says `never`, it does not
  borrow the word `current`.
- **The worst status leads.** Each repository's four
  kinds fold into one headline status by the pure
  `decide_worst_status`, in the honesty order
  `failed` > `stale` > `indexing` > `queued` >
  `never` > `current`: one failed kind makes the
  repository failed on the page, however green the
  other three stand. The instance folds the same
  way, and counts how many repositories stand fully
  current and how many stand behind (`stale` or
  `failed` at the headline).
- **The rebuild trigger is S-205's rebuild,**
  **audited.** `request_rebuild` delegates to
  `SearchIndexStore.request_rebuild` — one kind, or
  every kind when none is named — so the generation
  law (the old generation served whole until the new
  one completes) is S-205's mechanism, not a second
  one. The trigger is a witnessed act: it appends
  `admin.index.rebuild` (target the repository,
  detail naming the kinds and the generation each
  rebuild carries) after the rebuild is enqueued,
  and a store built without an audit log refuses
  `audit_required` before anything is enqueued —
  an unaudited rebuild must not happen (the S-179
  fail-closed law). Refused triggers — wrong viewer,
  unknown repository, unknown kind — enqueue nothing
  and audit nothing.
- **One new audit event.** `admin.index.rebuild` is
  this slice's addition to the taxonomy (append-only,
  per S-008): 123 events stand: 31 auth / 79 repo /
  13 admin. Health reads audit nothing — reading the
  operator's page mutates no shared record. No
  migration: the health door reads migration 80's
  tables and writes only through S-205's store, so
  schema stays 84.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .index_architecture import (
    INDEX_KINDS, IndexJob, IndexState, QueueSnapshot,
    SearchIndexError, SearchIndexStore)

__all__ = [
    "STATUS_ORDER", "IndexHealth", "IndexHealthError",
    "InstanceIndexHealth", "RepoIndexHealth",
    "decide_worst_status", "lag_seconds_for",
    "render_index_health_page", "render_repo_index_health_page",
]

# The honesty order, worst first: the headline status
# of a folded set is its worst member's status.
STATUS_ORDER = (
    "failed", "stale", "indexing", "queued", "never", "current")

_STATUS_RANK = {status: rank for rank, status in enumerate(STATUS_ORDER)}

_STATUS_WORDS = {
    "never": "never indexed",
    "queued": "waiting to be indexed",
    "indexing": "being indexed now",
    "current": "up to date",
    "stale": "behind — a rebuild or retry is owed",
    "failed": "indexing failed — see the recorded error",
}


class IndexHealthError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def decide_worst_status(statuses) -> str:
    """The pure folding law: the worst status in a
    set, by STATUS_ORDER. An empty set folds to
    `never` — nothing known is not `current`."""
    worst = None
    worst_rank = None
    for status in statuses:
        if status not in _STATUS_RANK:
            status = "never"
        rank = _STATUS_RANK[status]
        if worst_rank is None or rank < worst_rank:
            worst, worst_rank = status, rank
    return worst if worst is not None else "never"


def lag_seconds_for(oldest_pending_at, now) -> int:
    """The pure lag law: the age of the oldest waiting
    job, in whole seconds. Nothing waiting is a lag of
    0 — said as 0, never omitted — and a clock behind
    the enqueue time clamps to 0 rather than going
    negative."""
    if oldest_pending_at is None:
        return 0
    return max(0, int(now) - int(oldest_pending_at))


@dataclass(frozen=True)
class RepoIndexHealth:
    """One repository's index health: its identity,
    S-205's four states as they stand, its waiting
    work in counts, its own lag, and its folded
    headline status."""
    repo_id: int
    full_name: str
    states: tuple[IndexState, ...]
    pending: int
    running: int
    dead: int
    oldest_pending_at: int | None
    lag_seconds: int
    worst_status: str

    @property
    def document_count(self) -> int:
        return sum(state.document_count for state in self.states)

    @property
    def is_current(self) -> bool:
        return self.worst_status == "current"


@dataclass(frozen=True)
class InstanceIndexHealth:
    """The whole instance's index health: S-205's
    queue snapshot (whose lag is the instance lag),
    every repository's health in directory order, and
    the folded counts the admin page leads with."""
    queue: QueueSnapshot
    repos: tuple[RepoIndexHealth, ...]

    @property
    def lag_seconds(self) -> int:
        return self.queue.lag_seconds

    @property
    def worst_status(self) -> str:
        return decide_worst_status(
            repo.worst_status for repo in self.repos)

    @property
    def current_count(self) -> int:
        return sum(1 for repo in self.repos if repo.is_current)

    @property
    def behind_count(self) -> int:
        return sum(
            1 for repo in self.repos
            if repo.worst_status in ("stale", "failed"))

    @property
    def document_count(self) -> int:
        return sum(repo.document_count for repo in self.repos)


class IndexHealth:
    """The admin health door over S-205's store: the
    per-repository read, the instance read, and the
    audited rebuild trigger. Every face checks the
    viewer is a site admin before reading anything."""

    def __init__(
        self, conn: sqlite3.Connection, accounts: AccountStore,
        index: SearchIndexStore, audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._index = index
        self._audit = audit
        self._now = time_fn

    # -- guards --------------------------------------
    def _require_admin(self, viewer_id: object) -> User:
        viewer = None
        if isinstance(viewer_id, int) and not isinstance(viewer_id, bool):
            viewer = self._accounts.get_by_id(viewer_id)
        if viewer is None:
            raise IndexHealthError(
                "no_such_user", "No such account.")
        if not viewer.is_admin:
            raise IndexHealthError(
                "not_site_admin",
                "Only a site admin can see index health.")
        return viewer

    # -- the per-repository read ----------------------
    def _job_facts(self, repo_id: int) -> tuple[int, int, int, int | None]:
        """One repository's waiting work, read from
        migration 80's queue as it stands: (pending,
        running, dead, oldest pending enqueue time)."""
        counts = {"pending": 0, "running": 0, "dead": 0}
        for row in self._conn.execute(
                "SELECT status, COUNT(*) AS c FROM index_jobs"
                " WHERE repo_id = ? GROUP BY status",
                (repo_id,)).fetchall():
            if row["status"] in counts:
                counts[row["status"]] = int(row["c"])
        oldest = self._conn.execute(
            "SELECT MIN(enqueued_at) AS m FROM index_jobs"
            " WHERE repo_id = ? AND status = 'pending'",
            (repo_id,)).fetchone()["m"]
        return counts["pending"], counts["running"], counts["dead"], oldest

    def _health_for(self, repo_id: int, owner: str, name: str,
                    states: tuple[IndexState, ...]) -> RepoIndexHealth:
        pending, running, dead, oldest = self._job_facts(repo_id)
        return RepoIndexHealth(
            repo_id=repo_id, full_name=f"{owner}/{name}",
            states=states, pending=pending, running=running, dead=dead,
            oldest_pending_at=oldest,
            lag_seconds=lag_seconds_for(oldest, self._now()),
            worst_status=decide_worst_status(
                state.status for state in states))

    def repo_health(self, viewer_id: object, owner: object,
                    repo: object) -> RepoIndexHealth:
        """One repository's health, for a site admin.
        An unknown repository answers `repo_not_found`
        (S-205's own refusal, carried through)."""
        self._require_admin(viewer_id)
        try:
            states = self._index.states_for_repo(owner, repo)
        except SearchIndexError as exc:
            raise IndexHealthError(exc.reason, str(exc)) from exc
        first = states[0]
        row = self._conn.execute(
            "SELECT owner, name FROM repositories WHERE id = ?",
            (first.repo_id,)).fetchone()
        return self._health_for(
            first.repo_id, row["owner"], row["name"], states)

    # -- the instance read -----------------------------
    def instance_health(self, viewer_id: object) -> InstanceIndexHealth:
        """Every repository's health, in directory
        order (owner, then name), with the queue
        snapshot S-205 computes. An instance with no
        repositories is a health with no rows — its
        queue lag still reads, and still shows."""
        self._require_admin(viewer_id)
        repos: list[RepoIndexHealth] = []
        for row in self._conn.execute(
                "SELECT id, owner, name FROM repositories"
                " ORDER BY owner_lower, name_lower").fetchall():
            states = self._index.states_for_repo(row["owner"], row["name"])
            repos.append(self._health_for(
                int(row["id"]), row["owner"], row["name"], states))
        return InstanceIndexHealth(
            queue=self._index.queue_snapshot(), repos=tuple(repos))

    # -- the rebuild trigger -----------------------------
    def request_rebuild(self, viewer_id: object, owner: object,
                        repo: object, *, kind: object = None,
                        source_ip: str | None = None,
                        ) -> tuple[IndexJob, ...]:
        """Trigger S-205's rebuild of one kind (or of
        every kind when none is named) for one
        repository, as a site admin, and witness it:
        one `admin.index.rebuild` entry naming the
        kinds and the generation each carries. The
        audit check comes first — a store without an
        audit log refuses `audit_required` before
        anything is enqueued."""
        admin = self._require_admin(viewer_id)
        if self._audit is None:
            raise IndexHealthError(
                "audit_required",
                "A rebuild must be audit-logged; this store "
                "has no audit log, so no rebuild was started.")
        try:
            jobs = self._index.request_rebuild(owner, repo, kind=kind)
            states = self._index.states_for_repo(owner, repo)
        except SearchIndexError as exc:
            raise IndexHealthError(exc.reason, str(exc)) from exc
        row = self._conn.execute(
            "SELECT owner, name FROM repositories WHERE id = ?",
            (states[0].repo_id,)).fetchone()
        full_name = f"{row['owner']}/{row['name']}"
        self._audit.append(
            actor_kind="user", actor_id=admin.id,
            action="admin.index.rebuild", target_kind="repository",
            target_id=full_name, outcome="success",
            source_ip=source_ip,
            detail={
                "kinds": [job.kind for job in jobs],
                "generations": [job.generation for job in jobs],
                "jobs": [job.id for job in jobs]})
        return jobs


def _state_lines(states: tuple[IndexState, ...]) -> list[str]:
    parts = []
    for state in states:
        words = _STATUS_WORDS.get(state.status, state.status)
        line = (
            f"<li><strong>{escape_html_text(state.kind)}</strong> — "
            f"{escape_html_text(words)}; "
            f"{state.document_count} documents indexed; "
            f"generation {state.generation}")
        if state.high_water:
            line += f"; high-water mark {escape_html_text(state.high_water)}"
        if state.last_error:
            line += f"; last error: {escape_html_text(state.last_error)}"
        parts.append(line + "</li>")
    return parts


def render_repo_index_health_page(health: RepoIndexHealth) -> str:
    """One repository's health, in words: the folded
    headline, the lag in seconds (always, even 0),
    the waiting work, and each kind's S-205 state.
    Freshness is said in text, never colour alone;
    every name through S-010."""
    words = _STATUS_WORDS.get(health.worst_status, health.worst_status)
    parts = [
        f"<h1>Index health — {escape_html_text(health.full_name)}</h1>",
        f"<p>Overall: {escape_html_text(words)}.</p>",
        f"<p>Index lag: {health.lag_seconds} seconds "
        f"({health.pending} waiting, {health.running} running, "
        f"{health.dead} dead).</p>",
        "<ul>",
        *_state_lines(health.states),
        "</ul>",
    ]
    return "\n".join(parts)


def render_index_health_page(health: InstanceIndexHealth) -> str:
    """The instance's health, in words: the queue and
    its lag first (always, even 0), the folded counts,
    then every repository with its headline status,
    its own lag, and its document count — a repository
    that is behind is named here, never averaged away.
    Every name through S-010."""
    queue = health.queue
    words = _STATUS_WORDS.get(health.worst_status, health.worst_status)
    parts = [
        "<h1>Index health</h1>",
        f"<p>Index lag: {queue.lag_seconds} seconds — "
        f"{queue.pending} waiting, {queue.running} running, "
        f"{queue.done} done, {queue.dead} dead.</p>",
        f"<p>{len(health.repos)} repositories; "
        f"{health.current_count} up to date; "
        f"{health.behind_count} behind; "
        f"{health.document_count} documents indexed; "
        f"overall: {escape_html_text(words)}.</p>",
    ]
    if not health.repos:
        parts.append(
            "<p>No repositories yet — there is nothing to index.</p>")
    else:
        parts.append("<ul>")
        for repo in health.repos:
            rwords = _STATUS_WORDS.get(
                repo.worst_status, repo.worst_status)
            parts.append(
                f"<li><strong>{escape_html_text(repo.full_name)}</strong>"
                f" — {escape_html_text(rwords)}; "
                f"lag {repo.lag_seconds} seconds; "
                f"{repo.document_count} documents indexed</li>")
        parts.append("</ul>")
    return "\n".join(parts)
