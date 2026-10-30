"""Issue events out (S-139).

Every issue mutation emits an event for Part XI's feeds
and Part XII's webhooks. This slice builds the outbound
store those parts consume, on the pattern S-090 set for
pushes and S-127/S-131 set for derived records:

- **Derived from the witness, exactly once.** Every
  Part VI mutation already writes exactly one audit row
  (the slices' standing law: real changes only, retries
  quiet). The outbox materialises those rows — one
  outbound event per audit row, keyed by its audit
  `seq` under a UNIQUE constraint, inserted with
  OR IGNORE — so syncing twice emits nothing twice,
  a refused or rolled-back mutation (which never
  reached the audit log) emits nothing at all, and a
  mutation that somehow escaped auditing would be a
  visible gap between the two records, never a silent
  second truth. S-221 completes Part XI's canonical
  event store over this shape; the transports in
  Part XII read from here.
- **The verb set is the issue family.** An event's verb
  is its audit action, for every `repo.issue.*`,
  `repo.label.*`, and `repo.milestone.*` action plus
  `repo.pull_request.create` — computed from the frozen
  taxonomy, so a new issue-family act joins the outbox
  the day its event is added, and nothing outside the
  family (signups, pushes, repo creation, issue
  *templates*, which are repository configuration) can
  leak in. Personal, unaudited acts (saved filters)
  and derived records (cross-references) are not
  mutations and emit nothing — named here so the
  boundary is a decision, not an omission.
- **Details are the audit's safe specifics.** The
  payload detail is the audit row's own detail (numbers,
  names, reasons — never titles, bodies, or secrets,
  per the taxonomy's per-event contract), carried
  unchanged.
- **The webhook payload shape is Samverk's own**
  (Part XII's S-247 maps these verbs to its documented
  payloads): `event` (the verb), `action` (its final
  segment), `repository` (full name), `number` (the
  numbered item, when the detail names one), `actor`
  (the acting account's name), `detail`, `occurred_at`,
  and `delivery_id` (`evt-<outbox id>`, stable across
  redelivery so a receiver can dedupe).
- **Reads ride the repository's gate.** Listing a
  repo's outbound events syncs that repo first — a read
  is never stale — and requires read access; a stranger
  to a private repository gets the uniform
  `repo_not_found`.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from .accounts import AccountStore, User
from .permissions import can_read
from .repositories import Repository, RepositoryStore
from .taxonomy import REPO_EVENTS

ISSUE_EVENT_VERBS = frozenset(
    verb for verb in REPO_EVENTS
    if verb.startswith("repo.issue.")
    or verb.startswith("repo.label.")
    or verb.startswith("repo.milestone.")
    or verb == "repo.pull_request.create")


class IssueEventOutError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class OutboundEvent:
    id: int
    audit_seq: int
    repo_id: int
    repository: str      # full name
    actor_id: int | None
    actor: str           # display case; '' when unknown
    verb: str
    target_id: str
    detail: dict
    created_at: int

    @property
    def action(self) -> str:
        return self.verb.rsplit(".", 1)[-1]

    @property
    def number(self) -> int | None:
        value = self.detail.get("number")
        return int(value) if isinstance(value, int) else None


def webhook_payload(event: OutboundEvent) -> dict:
    """The event as a webhook payload — Samverk's own
    shape, stable fields, detail carried unchanged."""
    return {
        "delivery_id": f"evt-{event.id}",
        "event": event.verb,
        "action": event.action,
        "repository": event.repository,
        "number": event.number,
        "actor": event.actor or None,
        "detail": event.detail,
        "occurred_at": event.created_at,
    }


def payload_json(event: OutboundEvent) -> str:
    """The payload as canonical JSON (sorted keys, tight
    separators) — the bytes a signing road would sign."""
    return json.dumps(webhook_payload(event), sort_keys=True,
                      separators=(",", ":"))


class IssueEventOutbox:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts

    # -- materialisation -------------------------------------------
    def sync_repo(self, owner: object, repo: object) -> int:
        """Materialise this repository's audited issue
        mutations into the outbox; returns how many events
        were newly emitted (0 on a re-sync — exactly-once
        is the UNIQUE audit_seq doing its work)."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise IssueEventOutError(
                "repo_not_found", "No such repository.")
        return self._sync(current)

    def sync_all(self) -> int:
        """Materialise every repository's new events;
        returns the total newly emitted."""
        total = 0
        rows = self._conn.execute(
            "SELECT id FROM repositories ORDER BY id").fetchall()
        for row in rows:
            current = self._repos.get_by_id(int(row["id"]))
            if current is not None:
                total += self._sync(current)
        return total

    def _sync(self, current: Repository) -> int:
        verbs = sorted(ISSUE_EVENT_VERBS)
        placeholders = ", ".join("?" for _ in verbs)
        rows = self._conn.execute(
            f"SELECT seq, ts, actor_id, action, target_id, detail"
            f" FROM audit_log WHERE action IN ({placeholders})"
            " AND (target_id = ? OR substr(target_id, 1, ?) = ?)"
            " ORDER BY seq",
            (*verbs, current.full_name, len(current.full_name) + 1,
             current.full_name + "#")).fetchall()
        emitted = 0
        with self._conn:  # the batch lands whole, or not at all
            for row in rows:
                cur = self._conn.execute(
                    "INSERT OR IGNORE INTO issue_event_outbox"
                    " (audit_seq, repo_id, actor_id, verb, target_id,"
                    " detail_json, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (int(row["seq"]), current.id, row["actor_id"],
                     row["action"], row["target_id"],
                     row["detail"] or "{}", int(row["ts"])))
                emitted += int(cur.rowcount)
        return emitted

    # -- reads -------------------------------------------------------
    def list_events(self, viewer: User | None, owner: object,
                    repo: object, *, limit: int = 100
                    ) -> list[OutboundEvent]:
        """This repository's outbound events, oldest first.
        Syncs first, so the answer is never stale; read
        access is the gate."""
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise IssueEventOutError(
                "repo_not_found", "No such repository.")
        self._sync(current)
        clamped = max(1, min(int(limit), 500))
        rows = self._conn.execute(
            "SELECT * FROM issue_event_outbox WHERE repo_id = ?"
            " ORDER BY id LIMIT ?", (current.id, clamped)).fetchall()
        return [self._to_event(r, current) for r in rows]

    def count_for_repo(self, viewer: User | None, owner: object,
                       repo: object) -> int:
        return len(self.list_events(viewer, owner, repo, limit=500))

    def _to_event(self, row: sqlite3.Row,
                  current: Repository) -> OutboundEvent:
        try:
            detail = json.loads(row["detail_json"] or "{}")
        except ValueError:
            detail = {}
        actor = (self._accounts.get_by_id(int(row["actor_id"]))
                 if row["actor_id"] else None)
        return OutboundEvent(
            id=int(row["id"]), audit_seq=int(row["audit_seq"]),
            repo_id=current.id, repository=current.full_name,
            actor_id=row["actor_id"],
            actor=actor.username if actor else "",
            verb=row["verb"], target_id=row["target_id"],
            detail=detail if isinstance(detail, dict) else {},
            created_at=int(row["created_at"]))
