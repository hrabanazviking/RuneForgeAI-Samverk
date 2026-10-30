"""Post-receive push events (S-090).

Every accepted push emits **one canonical event** into this
store: who pushed, by which transport, and exactly which refs
moved with their commit ranges (old oid → new oid; a zero old
oid is a creation, a zero new oid a deletion). This store is
the seed of Part XI's event store — activity feeds (S-234),
webhooks, and notifications all read from here rather than
re-deriving push history from reflogs or audit rows.

Separation of duties, named:

- The **audit log** (S-007) is the tamper-evident witness: it
  records that a push happened, at the threat model's level.
- This **event store** is the product record: the ref ranges a
  feed needs to say "3 commits landed on main". It is ordinary
  data — queryable, listable per repository, newest first.

Events are recorded only for *accepted* pushes (the transports
call `record_push` after the pack program exits 0 and the new
refs are read back, so the ranges recorded are the ranges that
actually landed — computed by diffing refs before/after, never
by trusting the client's request). A failed or refused push
records nothing here.

The store also offers a **post-receive hook handler**
(`post_receive_handler`) so the S-067 seam can feed the same
store: a `HookRunner` post-receive run carrying `RefUpdate`s
lands as the identical event shape.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .hooks import HookContext, RefUpdate
from .repositories import RepositoryStore

_OID_RE = re.compile(r"^[0-9a-f]{40}$|^[0-9a-f]{64}$")
TRANSPORTS = frozenset({"http", "ssh", "local"})
ACTOR_KINDS = frozenset({"user", "deploy_key", "system"})


class PushEventError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def update_kind(update: RefUpdate) -> str:
    """created | deleted | updated, from the zero-oid law."""
    if set(update.old_oid) == {"0"}:
        return "created"
    if set(update.new_oid) == {"0"}:
        return "deleted"
    return "updated"


def _validate_update(update: object) -> RefUpdate:
    if not isinstance(update, RefUpdate):
        raise PushEventError(
            "update_invalid", f"Not a ref update: {update!r}")
    for oid in (update.old_oid, update.new_oid):
        if not isinstance(oid, str) or not _OID_RE.match(oid.lower()):
            raise PushEventError(
                "update_invalid", f"Not an object id: {oid!r}")
    if update.old_oid == update.new_oid:
        raise PushEventError(
            "update_invalid",
            f"Ref {update.ref!r} does not move ({update.old_oid}); "
            "a push event records movement, not stillness.")
    return update


@dataclass(frozen=True)
class PushEvent:
    id: int
    full_name: str
    repo_id: int
    actor_kind: str
    actor_id: int | None
    transport: str
    updates: tuple[RefUpdate, ...]
    created_at: int

    @property
    def refs(self) -> tuple[str, ...]:
        return tuple(u.ref for u in self.updates)


class PushEventStore:
    def __init__(self, conn: sqlite3.Connection,
                 repositories: RepositoryStore,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._repos = repositories
        self._now = time_fn

    def record_push(self, owner, repo, *, actor_kind: str,
                    actor_id: int | None, transport: str,
                    updates) -> PushEvent:
        """Record one accepted push; commit before answering."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise PushEventError("repo_not_found", "No such repository.")
        if actor_kind not in ACTOR_KINDS:
            raise PushEventError(
                "actor_invalid", f"Unknown actor kind: {actor_kind!r}")
        if transport not in TRANSPORTS:
            raise PushEventError(
                "transport_invalid", f"Unknown transport: {transport!r}")
        checked = tuple(_validate_update(u) for u in updates)
        if not checked:
            raise PushEventError(
                "updates_empty",
                "An accepted push moves at least one ref; "
                "an empty range records no event.")
        refs_json = json.dumps(
            [{"ref": u.ref, "old": u.old_oid, "new": u.new_oid}
             for u in checked],
            sort_keys=True, separators=(",", ":"))
        created_at = int(self._now())
        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO push_events (repo_id, actor_kind, actor_id,"
                " transport, refs, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (current.id, actor_kind, actor_id, transport,
                 refs_json, created_at))
            event_id = int(cursor.lastrowid)
        return PushEvent(
            id=event_id, full_name=current.full_name, repo_id=current.id,
            actor_kind=actor_kind, actor_id=actor_id,
            transport=transport, updates=checked, created_at=created_at)

    # -- reads ------------------------------------------------------
    def _to_event(self, row: sqlite3.Row, full_name: str) -> PushEvent:
        raw = json.loads(row["refs"])
        updates = tuple(
            RefUpdate(ref=item["ref"], old_oid=item["old"],
                      new_oid=item["new"]) for item in raw)
        return PushEvent(
            id=int(row["id"]), full_name=full_name,
            repo_id=int(row["repo_id"]), actor_kind=row["actor_kind"],
            actor_id=row["actor_id"], transport=row["transport"],
            updates=updates, created_at=int(row["created_at"]))

    def list_for_repo(self, owner, repo, *, limit: int = 100
                      ) -> tuple[PushEvent, ...]:
        """Newest first; a missing repo is named, never faked."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise PushEventError("repo_not_found", "No such repository.")
        clamped = max(1, min(int(limit), 500))
        rows = self._conn.execute(
            "SELECT * FROM push_events WHERE repo_id = ?"
            " ORDER BY id DESC LIMIT ?",
            (current.id, clamped)).fetchall()
        return tuple(self._to_event(r, current.full_name) for r in rows)

    def count_for_repo(self, owner, repo) -> int:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise PushEventError("repo_not_found", "No such repository.")
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM push_events WHERE repo_id = ?",
            (current.id,)).fetchone()
        return int(row["n"])

    # -- the S-067 post-receive seam ---------------------------------
    def post_receive_handler(self, *, transport: str = "local",
                             actor_kind: str = "user",
                             actor_id: int | None = None
                             ) -> Callable[[HookContext], bool]:
        """A HookRunner post-receive handler recording the push
        described by its context (repo as canonical owner/name,
        updates as RefUpdates). A context with no updates records
        nothing and still succeeds — post-receive never vetoes."""
        def handler(context: HookContext) -> bool:
            if not context.updates:
                return True
            owner, _, repo = context.repo.partition("/")
            self.record_push(
                owner, repo, actor_kind=actor_kind, actor_id=actor_id,
                transport=transport, updates=context.updates)
            return True
        return handler


def diff_refs(before: dict[str, str], after: dict[str, str]
              ) -> tuple[RefUpdate, ...]:
    """Ref ranges from a before/after ref map (the transports'
    way of learning what a push actually did): created refs get
    a zero old oid, deleted refs a zero new oid."""
    updates: list[RefUpdate] = []
    zero = "0" * 40
    for ref in sorted(set(before) | set(after)):
        old, new = before.get(ref), after.get(ref)
        if old == new:
            continue
        width = len(new or old or zero)
        updates.append(RefUpdate(
            ref=ref, old_oid=old or "0" * width,
            new_oid=new or "0" * width))
    return tuple(updates)
