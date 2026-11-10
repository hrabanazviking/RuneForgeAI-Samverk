"""Webhook delivery log and redelivery (S-251).

Delivery log and redelivery -- admins and owners
inspect attempts (request/response, timing) and
redeliver in one click (findability law). S-250's
worker queued deliveries in the outbox and
recorded every attempt redacted -- status code or
redacted transport error, duration, stamps -- in
`webhook_delivery_attempts`, precisely so this
slice could read history instead of a summary.
This module is that reading face, plus the one
click that queues a delivery again.

- **Who may look is S-248's gate, never a new
  one.** A delivery belongs to its subscription,
  and a subscription belongs to a repository or
  an organization, so the log answers to exactly
  the people who may manage that subscription:
  for a repository delivery, a holder of the
  admin rung in the repository (S-190) or a site
  admin; for an organization delivery, an owner
  of the organization (S-186) or a site admin.
  Everyone else is refused by name --
  `admin_required` under a repository they can
  see but not administer, the uniform
  `repo_not_found` under one they cannot see at
  all (a private repository's existence is
  private, S-054's law), and `not_org_owner`
  under an organization. Anonymous callers are
  refused `authentication_required` before any
  row is read for them, and a delivery whose
  subscription is gone answers only to a site
  admin: with no parent left to judge standing
  by, the gate fails closed rather than open.
- **What an inspection shows.** One delivery,
  whole: its key, its event verb, the address it
  was (or will be) sent to, its standing in
  words, its attempts against the stated five,
  and every attempt in the order it was made --
  its number, the request's answer (the HTTP
  status code, or the redacted transport error
  and no code), how long it took in
  milliseconds, and when it started and
  finished. Timing is the attempts' own stamps
  and durations; nothing is recomputed or
  guessed. What was never stored is never shown:
  response bodies were discarded by the worker
  unread, the frozen payload is the receiver's
  copy and is not rendered, and no secret and no
  digest appears on any view -- a subscription
  is named only by whether a secret is set, in
  words. Lists run newest first, per repository
  or per organization, with an optional standing
  filter judged against S-250's own standings.
- **Redelivery is a new delivery.** One click
  (`redeliver`) queues a FRESH row in the same
  outbox: the same frozen payload (the event as
  it was witnessed, never re-derived), the same
  subscription and event, the address snapshotted
  from the subscription as it stands NOW (a new
  enqueue snapshots anew -- S-250's law), a new
  delivery key (`<stem>-redelivery-<n>`, numbered
  per subscription x event so a receiver can
  dedupe a redelivery exactly as it dedupes a
  retry), standing `queued`, due at once, with
  zero attempts burned. The original row is
  never touched: its standing, its attempts and
  its stamps stay exactly the history the log
  shows, and the new row names its parent in
  `redelivery_of`, so any delivery's lineage is
  readable from the log itself. Migration 98
  carries the lineage (schema 97 to 98):
  `redelivery_of` and `redelivery_number` join
  `webhook_deliveries`, and the exactly-once
  index widens to (subscription, event,
  redelivery number) -- number 0 is the original
  enqueue, still exactly-once under S-250's law;
  each redelivery takes the next number.
- **Only a finished delivery redelivers.** A
  delivery still `queued` or `retrying` is
  refused `delivery_not_redeliverable` -- it is
  already on its way, and a second copy would
  double-send what the outbox law queued once.
  A `delivered` or `dead` delivery may be
  redelivered any number of times; each click is
  one new row. A delivery whose subscription was
  deleted is refused `subscription_gone` --
  there is no one left to sign for or to snapshot
  an address from. Redelivery itself attempts
  nothing: the S-250 worker carries the new row
  on its next run, off the request path, exactly
  like any queued delivery.
- **Witnessing rides the standing verbs.** A
  redelivery is a manager's act, witnessed like
  S-248's subscription changes and with no new
  taxonomy event -- 131 stand: a repository
  redelivery rides `repo.settings.change` with
  the key `webhook.redeliver` named (the road
  S-248's updates travel), an organization
  redelivery rides `auth.organization.update`
  with `fields` `webhooks` and action `redeliver`.
  The detail carries the host and the original
  delivery's key -- never the payload, never a
  secret. Inspections are pure reads: they write
  nothing and audit nothing. Refusals write and
  audit nothing.
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .organization_members import OrgMembershipStore
from .organizations import OrganizationStore
from .permission_engine import PermissionEngine
from .repositories import RepositoryStore
from .team_permissions import role_covers
from .webhook_delivery import (
    DELIVERY_STATUSES, MAX_ATTEMPTS, DeliveryAttempt,
    WebhookDelivery, WebhookDeliveryStore, delivery_key_for)

__all__ = [
    "REDELIVERABLE_STATUSES", "DeliveryLogEntry",
    "DeliveryLogStore", "WebhookDeliveryLogError",
    "can_inspect", "decide_redelivery",
    "redelivery_key_for", "render_delivery_log_entry",
    "render_delivery_log_page",
]

#: The standings a delivery may be redelivered
#: from: it has finished -- it was delivered, or
#: it dead-lettered. A standing delivery is
#: already on its way and never redelivers.
REDELIVERABLE_STATUSES = ("delivered", "dead")


class WebhookDeliveryLogError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


# -- the pure law -----------------------------------


def can_inspect(*, is_site_admin: bool, level: str,
                repo_role: str | None = None,
                org_role: str | None = None) -> bool:
    """Pure: whether a standing grants inspection
    of one delivery -- a site admin anywhere; the
    admin rung (S-190) for a repository delivery;
    an owner's seat (S-186) for an organization
    delivery. Every other standing, and every
    unknown level, answers False: the gate fails
    closed."""
    if is_site_admin:
        return True
    if level == "repository":
        return role_covers(repo_role, "admin")
    if level == "organization":
        return org_role == "owner"
    return False


def decide_redelivery(status: object,
                      subscription_present: bool) -> None:
    """Pure: judge one redelivery, raising
    `WebhookDeliveryLogError` by name when it may
    not proceed and answering None when it may.
    A missing subscription is `subscription_gone`
    (checked first: it explains every standing);
    a delivery still on its way is
    `delivery_not_redeliverable`; a standing the
    outbox never named is the same refusal -- an
    unknown standing is not a finished one."""
    if not subscription_present:
        raise WebhookDeliveryLogError(
            "subscription_gone",
            "The subscription this delivery belonged "
            "to is gone; there is nothing to "
            "redeliver through.")
    if status not in REDELIVERABLE_STATUSES:
        raise WebhookDeliveryLogError(
            "delivery_not_redeliverable",
            "Only a finished delivery -- delivered "
            "or dead-lettered -- can be redelivered; "
            "this one is still on its way.")


def redelivery_key_for(event_id: int, webhook_id: int,
                       redelivery_number: int) -> str:
    """Pure: one redelivery's delivery key -- the
    delivery stem S-250 names (`evt-<event id>-
    hook-<subscription id>`) plus its redelivery
    number, so every redelivery of one event to
    one subscription carries its own key and a
    receiver can dedupe each copy."""
    stem = delivery_key_for(event_id, webhook_id)
    return f"{stem}-redelivery-{int(redelivery_number)}"


# -- the records -------------------------------------


@dataclass(frozen=True)
class DeliveryLogEntry:
    """One delivery as the log shows it: the
    delivery itself (S-250's record), the
    subscription it belongs to named by level and
    parent (never by secret -- only whether one
    is set, in words), its lineage (the delivery
    it redelivers, when it is one), and every
    attempt in the order it was made."""
    delivery: WebhookDelivery
    level: str
    parent_name: str
    parent_key: str
    subscription_active: bool | None
    subscription_has_secret: bool | None
    redelivery_of: int | None
    redelivery_number: int
    attempts: tuple[DeliveryAttempt, ...]

    @property
    def is_redelivery(self) -> bool:
        return self.redelivery_number > 0

    @property
    def redeliverable(self) -> bool:
        """Whether one click may redeliver this
        delivery now: it has finished, and its
        subscription still stands."""
        return (self.delivery.status in REDELIVERABLE_STATUSES
                and self.subscription_active is not None)

    @property
    def total_duration_ms(self) -> int:
        """The attempts' own durations, summed:
        the total time the receivers took, said
        from the recorded rows only."""
        return sum(a.duration_ms for a in self.attempts)

    @property
    def secret_words(self) -> str:
        if self.subscription_has_secret is None:
            return "subscription gone"
        if self.subscription_has_secret:
            return "a secret is set (never shown)"
        return "no secret set"

    @property
    def words(self) -> str:
        """The log entry said in plain words: what
        delivery, for which parent, its standing,
        every attempt's outcome and timing in
        order, and whether it can be redelivered."""
        d = self.delivery
        text = (
            f"Delivery {d.delivery_key} ({d.verb}) "
            f"for {self.parent_name}: "
            f"{d.status_words}, {d.attempts} of "
            f"{MAX_ATTEMPTS} attempts used; "
            f"{self.secret_words}.")
        if self.is_redelivery:
            text += (
                f" This is redelivery "
                f"{self.redelivery_number} of delivery "
                f"{self.redelivery_of}.")
        if self.attempts:
            said = "; ".join(a.words for a in self.attempts)
            text += (
                f" Attempts: {said}. Total attempt "
                f"time: {self.total_duration_ms} ms.")
        else:
            text += " No attempts yet."
        if self.redeliverable:
            text += " It can be redelivered."
        return text


# -- the store ---------------------------------------


class DeliveryLogStore:
    """The delivery log and the redelivery door
    over migration 97's outbox and migration 98's
    lineage columns, gated by S-248's own
    standings (S-190's admin rung, S-186's owners,
    site admins). Inspections commit nothing;
    a redelivery commits its new row before its
    answer and is witnessed on the standing verbs
    (see the module docstring)."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        organizations: OrganizationStore,
        accounts: AccountStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._orgs = organizations
        self._accounts = accounts
        self._audit = audit
        self._now = time_fn
        self._members = OrgMembershipStore(
            conn, accounts, audit=None, time_fn=time_fn)
        self._engine = PermissionEngine(
            conn, accounts, audit=None, time_fn=time_fn)
        self._deliveries = WebhookDeliveryStore(
            conn, repositories, organizations, accounts,
            time_fn=time_fn)

    # -- views --------------------------------------

    def _entry(self, row: sqlite3.Row) -> DeliveryLogEntry:
        hook = self._conn.execute(
            "SELECT * FROM webhooks WHERE id = ?",
            (int(row["webhook_id"]),)).fetchone()
        delivery = WebhookDeliveryStore._view(row)
        attempts = self._deliveries.attempts_for(delivery.id)
        if hook is None:
            return DeliveryLogEntry(
                delivery=delivery, level="", parent_name="",
                parent_key="", subscription_active=None,
                subscription_has_secret=None,
                redelivery_of=row["redelivery_of"],
                redelivery_number=int(row["redelivery_number"]),
                attempts=attempts)
        return DeliveryLogEntry(
            delivery=delivery, level=hook["level"],
            parent_name=hook["parent_name"],
            parent_key=hook["parent_key"],
            subscription_active=bool(hook["active"]),
            subscription_has_secret=bool(hook["secret_digest"]),
            redelivery_of=row["redelivery_of"],
            redelivery_number=int(row["redelivery_number"]),
            attempts=attempts)

    def _delivery_row(self, delivery_id: object) -> sqlite3.Row:
        """One delivery row by id: a missing id, or
        one of the wrong shape, is the one
        `delivery_not_found` -- the same answer
        whatever the caller may or may not see, so
        the log never confirms an id's existence to
        a caller who has not passed the gate."""
        if isinstance(delivery_id, bool) or not isinstance(
                delivery_id, int):
            raise WebhookDeliveryLogError(
                "delivery_not_found", "No such delivery.")
        row = self._conn.execute(
            "SELECT * FROM webhook_deliveries WHERE id = ?",
            (int(delivery_id),)).fetchone()
        if row is None:
            raise WebhookDeliveryLogError(
                "delivery_not_found", "No such delivery.")
        return row

    # -- the gate -------------------------------------

    @staticmethod
    def _require_user(user: User | None) -> User:
        if user is None:
            raise WebhookDeliveryLogError(
                "authentication_required",
                "Sign in to inspect webhook deliveries.")
        return user

    def _gate(self, user: User, row: sqlite3.Row) -> sqlite3.Row | None:
        """Judge *user*'s standing over one
        delivery, through its subscription's
        parent, answering the subscription row (or
        None when the subscription is gone and a
        site admin is looking). Refusals fail
        closed with named reasons: a repository
        the caller cannot see at all is the uniform
        `repo_not_found`; one they can see below
        admin is `admin_required`; an organization
        they do not own is `not_org_owner`; and a
        delivery with no subscription left answers
        only to a site admin -- everyone else is
        refused `admin_required`, the closed door."""
        hook = self._conn.execute(
            "SELECT * FROM webhooks WHERE id = ?",
            (int(row["webhook_id"]),)).fetchone()
        if hook is None:
            if user.is_admin:
                return None
            raise WebhookDeliveryLogError(
                "admin_required",
                "This delivery's subscription is gone; "
                "only a site admin can inspect it.")
        if hook["level"] == "repository":
            owner, _, name = hook["parent_key"].partition("/")
            repo = self._repos.get_repository(owner, name)
            if repo is None:
                raise WebhookDeliveryLogError(
                    "repo_not_found", "No such repository.")
            role = self._engine.resolve(user, repo).role
            if role is None:
                raise WebhookDeliveryLogError(
                    "repo_not_found", "No such repository.")
            if not can_inspect(is_site_admin=user.is_admin,
                               level="repository", repo_role=role):
                raise WebhookDeliveryLogError(
                    "admin_required",
                    "The delivery log needs admin on the "
                    "repository.")
            return hook
        org = self._orgs.get_by_id(int(hook["org_id"]))
        if org is None:
            raise WebhookDeliveryLogError(
                "org_not_found", "No such organization.")
        org_role = self._members.role_for(user.id, org.id)
        if not can_inspect(is_site_admin=user.is_admin,
                           level="organization",
                           org_role=org_role):
            raise WebhookDeliveryLogError(
                "not_org_owner",
                "The delivery log needs an owner of the "
                "organization.")
        return hook

    # -- inspections ----------------------------------

    def get_log_entry(self, user: User | None,
                      delivery_id: object) -> DeliveryLogEntry:
        """One delivery, whole, with every attempt:
        the caller passes the delivery's gate
        (admin on its repository, owner of its
        organization, or site admin) or is refused
        by name. A pure read."""
        actor = self._require_user(user)
        row = self._delivery_row(delivery_id)
        self._gate(actor, row)
        return self._entry(row)

    def _list(self, hook_ids: list[int], status: object,
              limit: int) -> tuple[DeliveryLogEntry, ...]:
        if status is not None and status not in DELIVERY_STATUSES:
            raise WebhookDeliveryLogError(
                "delivery_status_invalid",
                "A delivery standing is one of: "
                + ", ".join(DELIVERY_STATUSES) + ".")
        if not hook_ids:
            return ()
        clamped = max(1, min(int(limit), 500))
        marks = ",".join("?" for _ in hook_ids)
        sql = ("SELECT * FROM webhook_deliveries"
               f" WHERE webhook_id IN ({marks})")
        params: list = list(hook_ids)
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(clamped)
        rows = self._conn.execute(sql, params).fetchall()
        return tuple(self._entry(r) for r in rows)

    def log_for_repository(self, user: User | None, owner: object,
                           repo: object, *, status: object = None,
                           limit: int = 100,
                           ) -> tuple[DeliveryLogEntry, ...]:
        """One repository's delivery log, newest
        first: every delivery of every subscription
        the repository holds, each with its
        attempts. The gate is S-248's repository
        gate -- unseen is `repo_not_found`, seen
        below admin is `admin_required`."""
        actor = self._require_user(user)
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise WebhookDeliveryLogError(
                "repo_not_found", "No such repository.")
        role = self._engine.resolve(actor, current).role
        if role is None:
            raise WebhookDeliveryLogError(
                "repo_not_found", "No such repository.")
        if not can_inspect(is_site_admin=actor.is_admin,
                           level="repository", repo_role=role):
            raise WebhookDeliveryLogError(
                "admin_required",
                "The delivery log needs admin on the "
                "repository.")
        hooks = self._conn.execute(
            "SELECT id FROM webhooks"
            " WHERE level = 'repository' AND repo_id = ?",
            (current.id,)).fetchall()
        return self._list([int(h["id"]) for h in hooks],
                          status, limit)

    def log_for_organization(self, user: User | None, org: object,
                             *, status: object = None,
                             limit: int = 100,
                             ) -> tuple[DeliveryLogEntry, ...]:
        """One organization's delivery log, newest
        first: every delivery of every subscription
        the organization holds, each with its
        attempts. The gate is S-248's organization
        gate -- an owner or a site admin; anyone
        else is `not_org_owner`."""
        actor = self._require_user(user)
        current = self._orgs.get_by_name(org)
        if current is None:
            raise WebhookDeliveryLogError(
                "org_not_found", "No such organization.")
        org_role = self._members.role_for(actor.id, current.id)
        if not can_inspect(is_site_admin=actor.is_admin,
                           level="organization",
                           org_role=org_role):
            raise WebhookDeliveryLogError(
                "not_org_owner",
                "The delivery log needs an owner of the "
                "organization.")
        hooks = self._conn.execute(
            "SELECT id FROM webhooks"
            " WHERE level = 'organization' AND org_id = ?",
            (current.id,)).fetchall()
        return self._list([int(h["id"]) for h in hooks],
                          status, limit)

    def counts_for(self, entries: Iterable[DeliveryLogEntry],
                   ) -> dict[str, int]:
        """The standings said in numbers over a log
        already read: a count for every standing in
        S-250's DELIVERY_STATUSES, zeroes included."""
        found = {status: 0 for status in DELIVERY_STATUSES}
        for entry in entries:
            if entry.delivery.status in found:
                found[entry.delivery.status] += 1
        return found

    # -- redelivery -----------------------------------

    def _witness(self, user: User, hook: sqlite3.Row,
                 original: WebhookDelivery,
                 source_ip: str | None) -> None:
        """One redelivery, witnessed on the
        standing verbs (see the module docstring):
        the detail carries the host and the
        original delivery's key -- never the
        payload, never a secret."""
        if self._audit is None:
            return
        if hook["level"] == "repository":
            self._audit.append(
                actor_kind="user", actor_id=user.id,
                action="repo.settings.change",
                target_kind="repo",
                target_id=hook["parent_name"],
                outcome="success", source_ip=source_ip,
                detail={"key": "webhook.redeliver",
                        "host": hook["host"],
                        "delivery": original.delivery_key})
        else:
            self._audit.append(
                actor_kind="user", actor_id=user.id,
                action="auth.organization.update",
                target_kind="organization",
                target_id=hook["parent_key"],
                outcome="success", source_ip=source_ip,
                detail={"fields": "webhooks",
                        "action": "redeliver",
                        "host": hook["host"],
                        "delivery": original.delivery_key})

    def redeliver(self, user: User | None, delivery_id: object,
                  source_ip: str | None = None,
                  ) -> DeliveryLogEntry:
        """Redeliver one finished delivery in one
        call: queue a fresh delivery row for the
        same subscription and event, carrying the
        original's frozen payload, snapshotting
        the subscription's address as it stands
        now, keyed with the next redelivery number,
        and naming the original in `redelivery_of`.
        The caller passes the same gate as
        inspection; the original row is never
        touched, nothing is attempted here -- the
        S-250 worker carries the new row -- and the
        new row commits before its answer, which is
        the new delivery's own log entry (no
        attempts yet)."""
        actor = self._require_user(user)
        row = self._delivery_row(delivery_id)
        hook = self._gate(actor, row)
        original = WebhookDeliveryStore._view(row)
        decide_redelivery(original.status, hook is not None)
        assert hook is not None  # decided above
        now = int(self._now())
        found = self._conn.execute(
            "SELECT COALESCE(MAX(redelivery_number), 0) AS n"
            " FROM webhook_deliveries"
            " WHERE webhook_id = ? AND event_id = ?",
            (original.webhook_id, original.event_id)).fetchone()
        number = int(found["n"]) + 1
        key = redelivery_key_for(
            original.event_id, original.webhook_id, number)
        with self._conn:  # commits before the answer
            cur = self._conn.execute(
                "INSERT INTO webhook_deliveries"
                " (webhook_id, event_id, verb, delivery_key,"
                " url, host, payload_json, status, attempts,"
                " next_attempt_at, last_status_code, last_error,"
                " created_at, updated_at, delivered_at, dead_at,"
                " redelivery_of, redelivery_number)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', 0, ?,"
                " NULL, '', ?, ?, NULL, NULL, ?, ?)",
                (original.webhook_id, original.event_id,
                 original.verb, key, hook["url"], hook["host"],
                 original.payload_json, now, now, now,
                 original.id, number))
            new_id = int(cur.lastrowid)
        fresh = self._conn.execute(
            "SELECT * FROM webhook_deliveries WHERE id = ?",
            (new_id,)).fetchone()
        entry = self._entry(fresh)
        self._witness(actor, hook, original, source_ip)
        return entry


# -- renders -------------------------------------------


def render_delivery_log_entry(entry: DeliveryLogEntry) -> str:
    """One delivery's log, rendered whole: its
    key, parent, event and address, its standing
    in words, every attempt in order with its
    answer and timing, its lineage when it is a
    redelivery, and -- when it has finished and
    its subscription stands -- the one-click
    redelivery control, a real form with the
    action said in words on its button. A
    delivery that cannot be redelivered says why
    in words instead of showing a dead control.
    Every value passes through S-010; the payload
    is never rendered and no secret or digest is
    ever present to be escaped."""
    d = entry.delivery
    parts = ["<li>"]
    parts.append(
        f"<strong>{escape_html_text(d.delivery_key)}</strong> "
        f"({escape_html_text(d.verb)}) for "
        f"{escape_html_text(entry.parent_name)} to "
        f"{escape_html_text(d.url)} -- "
        f"{escape_html_text(d.status_words)}, "
        f"{d.attempts} of {MAX_ATTEMPTS} attempts used; "
        f"{escape_html_text(entry.secret_words)}.")
    if entry.is_redelivery:
        parts.append(
            f" This is redelivery {entry.redelivery_number} "
            f"of delivery {entry.redelivery_of}.")
    if entry.attempts:
        parts.append("<ul>")
        for attempt in entry.attempts:
            parts.append(
                "<li>"
                f"{escape_html_text(attempt.words)} "
                f"Started at {attempt.started_at}, "
                f"finished at {attempt.finished_at}."
                "</li>")
        parts.append("</ul>")
        parts.append(
            f"<p>Total attempt time: "
            f"{entry.total_duration_ms} ms.</p>")
    else:
        parts.append("<p>No attempts yet.</p>")
    if entry.redeliverable:
        parts.append(
            f'<form method="post" '
            f'action="/webhooks/deliveries/{d.id}/redeliver">'
            f'<button type="submit">Redeliver delivery '
            f"{escape_html_text(d.delivery_key)}</button>"
            "</form>")
    elif entry.subscription_active is None:
        parts.append(
            "<p>This delivery cannot be redelivered: "
            "its subscription is gone.</p>")
    elif d.status in ("queued", "retrying"):
        parts.append(
            "<p>This delivery cannot be redelivered "
            "yet: it is still on its way.</p>")
    parts.append("</li>")
    return "\n".join(parts)


def render_delivery_log_page(
        title: str,
        entries: Iterable[DeliveryLogEntry]) -> str:
    """A delivery log rendered as a page under a
    title: every entry whole (see
    `render_delivery_log_entry`). An empty log
    teaches the model instead of showing a blank:
    deliveries are queued off the request path
    when an event matches a subscription, attempted
    by the delivery worker, and finished deliveries
    can be redelivered from this log in one click."""
    rows = list(entries)
    parts = [f"<h2>{escape_html_text(title)}</h2>"]
    if not rows:
        parts.append(
            "<p>No webhook deliveries yet. When an "
            "event matches a subscription, a delivery "
            "is queued for it off the request path and "
            "the delivery worker attempts it; every "
            "attempt will be listed here with its "
            "answer and timing, and a finished "
            "delivery can be redelivered from this "
            "log in one click.</p>")
        return "\n".join(parts)
    parts.append("<ul>")
    for entry in rows:
        parts.append(render_delivery_log_entry(entry))
    parts.append("</ul>")
    return "\n".join(parts)
