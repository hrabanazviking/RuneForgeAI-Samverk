"""Webhook delivery worker (S-250).

Delivery worker -- queued deliveries with
exponential backoff, dead-letter after the stated
attempts, all off the request path. S-247 stated
the payload, S-248 built the subscriptions that
receive it and the routing that matches them, and
S-249 stated how a delivery is signed; this slice
is the worker that carries the payload to the
address: an outbox, a retry law, and a dead-letter
rest, and nothing on any request path.

- **The outbox is the queue.** Migration 97's
  `webhook_deliveries` holds one row per
  subscription x event, UNIQUE on the pair, so
  enqueueing the same event for the same
  subscription twice returns the standing row and
  queues nothing twice -- exactly-once enqueue,
  the S-227 law. A row freezes what it will
  carry: the payload is S-247's `payload_json`,
  computed once at enqueue, and the delivery
  address (and its host) is snapshotted from the
  subscription at enqueue, so editing a
  subscription later never redirects a payload
  already queued, and a retry delivers the event
  as it was witnessed, not as the store stands
  now. Attempts are rows of their own in
  `webhook_delivery_attempts` -- one per try,
  with its number, its stamps, its status code
  or redacted error and its duration -- because
  S-251's delivery log reads history, not a
  summary a worker overwrote.
- **Routing is S-248's, never re-derived.**
  `enqueue_event` asks the subscription store's
  own `subscriptions_for_event` who receives an
  event and enqueues exactly for them: inactive
  subscriptions and non-matching filters queue
  nothing, and a withheld or unknown verb queues
  nothing anywhere (the routing already answers
  empty for it). This module invents no second
  matching law.
- **The stated attempts are five.** A delivery
  is attempted at most `MAX_ATTEMPTS` (5) times.
  A 2xx answer delivers it. Every other outcome
  -- any other HTTP status (429 and 5xx
  included), a transport error, a timeout --
  is a failure that retries under the backoff
  law until the fifth failure, which rests the
  delivery `dead`: the dead-letter. A dead
  delivery is kept, with its attempts and its
  last error, never silently dropped; S-251
  gives owners the log and the redelivery door.
  Two standings end a delivery without burning
  attempts, said honestly on the row: a
  subscription deleted before its attempt rests
  the delivery dead with `subscription_gone`
  (there is no one left to sign for, S-248's
  rotation law made deletion the successor's
  birth), and a subscription inactive at attempt
  time is skipped for that run -- no attempt is
  counted, the delivery stands queued for a
  later run, exactly as S-248's standing says.
- **Backoff is exponential, capped, jittered.**
  The pure `backoff_delay` states the law: after
  failure number n the wait is
  min(60 * 2**(n-1), 3600) seconds -- 60, 120,
  240, 480, 960, then the one-hour cap. The
  worker adds jitter from an injected seam (by
  default a uniform draw in [0, delay/4]) so a
  fleet of failing hooks does not retry in
  lockstep (research 22); tests inject the seam
  and pin the bare law exactly. A delivery is
  due when its standing is `queued` or
  `retrying` and its `next_attempt_at` has come;
  the worker takes due deliveries oldest-due
  first, at most `BATCH_LIMIT` per run.
- **Signing is S-249's road, at attempt time.**
  Every attempt signs the frozen payload bytes
  fresh through S-249's `delivery_headers`,
  keyed by the subscription's *current* stored
  digest: a subscription with no secret delivers
  unsigned (no header, never a fake one), and a
  deleted subscription signs for no one (above).
  Beside the signature, an attempt carries
  `Content-Type: application/json`,
  `X-Samverk-Event` (the verb) and
  `X-Samverk-Delivery` (the delivery key,
  `evt-<event id>-hook-<subscription id>`:
  stable across every retry of this delivery,
  so a receiver that got the payload but whose
  answer was lost can dedupe the retry -- a
  timeout is ambiguous, research 22, and the
  key is the honest answer to it). The payload's
  own `delivery_id` stays S-247's `evt-<event
  id>`; the key names this subscription's copy.
- **Outcomes are recorded redacted.** An attempt
  records a status code, or for a transport
  failure the error `transport_<class>` -- the
  exception's class name and nothing it carried;
  a delivery's `last_error` is `http_<code>` or
  that same transport reason. Response bodies
  are read capped and discarded, never stored:
  a body can echo anything, including words
  that look like secrets, and the log is not a
  place for them. No secret and no digest ever
  appears on a delivery view or a render.
- **The transport is a seam; the default does
  not follow redirects.** A transport is a
  callable (url, body bytes, headers, timeout)
  answering a `TransportResult` status; tests
  inject fakes and no test touches the network.
  The real `http_transport` POSTs over urllib
  with a 10-second timeout and redirects
  disabled -- a 3xx is the receiver's answer,
  judged like any other status, never a road
  to a second address the subscription did not
  name (research 22's SSRF note).
- **All off the request path.** Nothing here is
  wired into the web server and no request ever
  enqueues or attempts a delivery: enqueueing is
  the embedding operator's call (a mutation's
  own path ends at the witness; the event store
  and this outbox are read and filled off-path,
  S-221/S-235's shape), and `run_due` is the
  worker -- an operator or scheduler runs
  `python3 -m samverk.webhook_delivery <db-path>
  <repos-root>`, which drains one due batch and
  prints the run's honest account. Delivery is
  bookkeeping over acts already witnessed, so
  this slice audits nothing and adds no taxonomy
  event: 131 stand. One migration: 97 creates
  the outbox and its attempts (schema 96 to 97).
"""
from __future__ import annotations

import random
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore
from .escaping import escape_html_text
from .event_store import CanonicalEvent
from .organizations import OrganizationStore
from .repositories import RepositoryStore
from .webhook_events import payload_json
from .webhook_signing import delivery_headers
from .webhook_subscriptions import (
    WebhookSubscription, WebhookSubscriptionStore)

__all__ = [
    "BATCH_LIMIT", "BASE_DELAY_SECONDS", "DELIVERY_STATUSES",
    "DELIVERY_TIMEOUT_SECONDS", "EVENT_HEADER", "DELIVERY_HEADER",
    "MAX_ATTEMPTS", "MAX_DELAY_SECONDS", "DeliveryAttempt",
    "DeliveryRun", "Transport", "TransportResult", "WebhookDelivery",
    "WebhookDeliveryError", "WebhookDeliveryStore", "backoff_delay",
    "build_delivery_headers", "delivery_key_for", "http_transport",
    "main", "render_delivery", "render_delivery_attempt",
    "render_deliveries",
]

#: The stated attempts: a delivery is tried at
#: most this many times before it dead-letters.
MAX_ATTEMPTS = 5

#: The backoff law's base: the wait after the
#: first failure, doubling per failure...
BASE_DELAY_SECONDS = 60

#: ...and its cap: no wait ever exceeds an hour.
MAX_DELAY_SECONDS = 3600

#: How long one attempt waits on its receiver.
DELIVERY_TIMEOUT_SECONDS = 10.0

#: How many due deliveries one worker run drains.
BATCH_LIMIT = 100

#: How much of a response body the default
#: transport reads before discarding it unread
#: (the body is never stored; the read only lets
#: the connection finish honestly).
RESPONSE_READ_LIMIT = 65536

#: The header naming the event verb on a delivery.
EVENT_HEADER = "X-Samverk-Event"

#: The header naming this delivery (stable across
#: its retries) on a delivery.
DELIVERY_HEADER = "X-Samverk-Delivery"

#: The standings a delivery may rest in, in the
#: order a life runs: waiting, waiting to retry,
#: delivered, dead-lettered.
DELIVERY_STATUSES = ("queued", "retrying", "delivered", "dead")

_DUE_STATUSES = ("queued", "retrying")


class WebhookDeliveryError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


# -- the pure law -----------------------------------


def backoff_delay(failed_attempts: object) -> int:
    """Pure: the seconds to wait after failure
    number *failed_attempts* (1 for the first
    failure): BASE doubled per failure, capped at
    MAX -- 60, 120, 240, 480, 960, 1920, then
    3600 for every later failure. The count is
    judged whole: anything but a positive integer
    is refused `webhook_attempts_invalid`, because
    a backoff computed from a guessed count would
    schedule a lie. Jitter is the worker's seam,
    never part of this law."""
    if (isinstance(failed_attempts, bool)
            or not isinstance(failed_attempts, int)
            or failed_attempts < 1):
        raise WebhookDeliveryError(
            "webhook_attempts_invalid",
            "A backoff is counted from a positive "
            "number of failed attempts.")
    return min(
        BASE_DELAY_SECONDS * (2 ** (failed_attempts - 1)),
        MAX_DELAY_SECONDS)


def delivery_key_for(event_id: int, webhook_id: int) -> str:
    """Pure: one delivery's stable key -- the
    event's own S-247 delivery id stem plus the
    subscription it is a copy for. The same key
    rides every retry of the delivery, so a
    receiver can dedupe a retry of a payload it
    already accepted."""
    return f"evt-{int(event_id)}-hook-{int(webhook_id)}"


def build_delivery_headers(stored_digest: object, body: object,
                           verb: str, delivery_key: str,
                           ) -> dict[str, str]:
    """Pure: the headers one attempt carries --
    S-249's signature header when the subscription
    has a secret (an empty mapping's worth when
    it has none: unsigned stays unsigned), the
    JSON content type, and the two naming headers
    (the event verb, and this delivery's stable
    key). Signing is judged entirely by S-249's
    `delivery_headers`; a malformed stored digest
    is refused there, by its own name."""
    headers = dict(delivery_headers(body, stored_digest))
    headers["Content-Type"] = "application/json"
    headers[EVENT_HEADER] = str(verb)
    headers[DELIVERY_HEADER] = str(delivery_key)
    return headers


def _transport_error_name(exc: BaseException) -> str:
    """The redacted transport error for one
    failure: `transport_` plus the exception's
    class name, letters/digits/underscore only --
    never the message, which can carry the
    address, the payload, or worse."""
    name = "".join(
        c for c in type(exc).__name__ if c.isalnum() or c == "_")
    return f"transport_{name or 'Error'}"


# -- the records -------------------------------------


@dataclass(frozen=True)
class WebhookDelivery:
    """One queued delivery as every face shows it:
    which subscription's copy of which event, to
    the address snapshotted at enqueue, its
    standing, how many attempts it has burned of
    the stated five, when the next attempt falls
    due, the last attempt's redacted outcome, and
    its stamps. The frozen payload rides the
    record for the worker and S-251's faces; no
    secret and no digest is ever on a view --
    signing reads the subscription row itself."""
    id: int
    webhook_id: int
    event_id: int
    verb: str
    delivery_key: str
    url: str
    host: str
    payload_json: str
    status: str
    attempts: int
    next_attempt_at: int
    last_status_code: int | None
    last_error: str
    created_at: int
    updated_at: int
    delivered_at: int | None
    dead_at: int | None

    @property
    def status_words(self) -> str:
        return {
            "queued": "queued, never attempted",
            "retrying": "waiting to retry",
            "delivered": "delivered",
            "dead": "dead-lettered",
        }.get(self.status, self.status)

    @property
    def words(self) -> str:
        """The delivery said in plain words: what
        event, to where, its standing and its
        attempts against the stated five, and its
        last outcome when it has one."""
        text = (
            f"Delivery {self.delivery_key} "
            f"({self.verb}) to {self.url}: "
            f"{self.status_words}, {self.attempts} of "
            f"{MAX_ATTEMPTS} attempts used.")
        if self.last_error:
            text += f" Last outcome: {self.last_error}."
        elif self.last_status_code is not None:
            text += (
                f" Last answer: HTTP "
                f"{self.last_status_code}.")
        return text


@dataclass(frozen=True)
class DeliveryAttempt:
    """One attempt at one delivery, as S-251's log
    will show it: its number within the delivery,
    the answer it got (a status code, or a
    redacted transport error and no code), how
    long it took, and its stamps."""
    id: int
    delivery_id: int
    attempt_number: int
    status_code: int | None
    error: str
    duration_ms: int
    started_at: int
    finished_at: int

    @property
    def outcome_words(self) -> str:
        if self.error:
            return self.error
        return f"HTTP {self.status_code}"

    @property
    def words(self) -> str:
        return (
            f"Attempt {self.attempt_number}: "
            f"{self.outcome_words}, "
            f"{self.duration_ms} ms.")


@dataclass(frozen=True)
class DeliveryRun:
    """One worker run's honest account: how many
    deliveries were due, how many were attempted,
    and how the attempts landed -- delivered,
    scheduled to retry, dead-lettered -- plus the
    due deliveries skipped because their
    subscription stands inactive."""
    due: int
    attempted: int
    delivered: int
    retried: int
    dead: int
    skipped_inactive: int

    @property
    def words(self) -> str:
        return (
            f"Webhook delivery run: {self.due} due, "
            f"{self.attempted} attempted, "
            f"{self.delivered} delivered, "
            f"{self.retried} to retry, "
            f"{self.dead} dead-lettered, "
            f"{self.skipped_inactive} skipped "
            f"(subscription inactive).")


# -- the transport seam -------------------------------


@dataclass(frozen=True)
class TransportResult:
    """What a transport answers: the receiver's
    HTTP status code, and nothing else -- the body
    is never carried back, so it can never leak
    into a log."""
    status_code: int


#: A transport: (url, body bytes, headers, timeout
#: seconds) -> the receiver's status. Raising is a
#: transport failure, judged by the worker.
Transport = Callable[[str, bytes, dict, float], TransportResult]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Redirects refused as a following road: a
    3xx is returned as the receiver's answer (the
    opener raises it as an HTTPError, which
    `http_transport` reads as a status), never a
    road to an address the subscription did not
    name."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_transport(url: str, body: bytes, headers: dict,
                   timeout: float) -> TransportResult:
    """The real transport: one POST over urllib,
    redirects disabled, the response body read
    capped and discarded. An HTTP error status is
    an answer, not an exception; a connection or
    timeout failure raises, and the worker judges
    it a transport failure."""
    request = urllib.request.Request(
        url, data=body, headers=dict(headers), method="POST")
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            response.read(RESPONSE_READ_LIMIT)
            return TransportResult(status_code=int(response.status))
    except urllib.error.HTTPError as exc:
        try:
            exc.read(RESPONSE_READ_LIMIT)
        except Exception:
            pass
        return TransportResult(status_code=int(exc.code))


# -- the store ---------------------------------------


class WebhookDeliveryStore:
    """The delivery outbox and worker over
    migration 97, routed by S-248's subscription
    store and signed by S-249's road. Enqueueing
    and every attempt commit before their answer;
    nothing here audits (delivery witnesses no
    mutation of its own) and nothing here runs on
    a request path -- `run_due` is the worker, run
    by an operator or a scheduler."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        organizations: OrganizationStore,
        accounts: AccountStore,
        transport: Transport | None = None,
        time_fn: Callable[[], float] = time.time,
        jitter_fn: Callable[[int], float] | None = None,
    ):
        self._conn = conn
        self._transport = transport or http_transport
        self._now = time_fn
        self._jitter = jitter_fn if jitter_fn is not None else (
            lambda delay: random.uniform(0.0, delay / 4.0))
        self._hooks = WebhookSubscriptionStore(
            conn, repositories, organizations, accounts,
            audit=None, time_fn=time_fn)

    # -- views --------------------------------------

    @staticmethod
    def _view(row: sqlite3.Row) -> WebhookDelivery:
        return WebhookDelivery(
            id=int(row["id"]), webhook_id=int(row["webhook_id"]),
            event_id=int(row["event_id"]), verb=row["verb"],
            delivery_key=row["delivery_key"], url=row["url"],
            host=row["host"], payload_json=row["payload_json"],
            status=row["status"], attempts=int(row["attempts"]),
            next_attempt_at=int(row["next_attempt_at"]),
            last_status_code=row["last_status_code"],
            last_error=row["last_error"],
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]),
            delivered_at=row["delivered_at"],
            dead_at=row["dead_at"])

    @staticmethod
    def _attempt_view(row: sqlite3.Row) -> DeliveryAttempt:
        return DeliveryAttempt(
            id=int(row["id"]), delivery_id=int(row["delivery_id"]),
            attempt_number=int(row["attempt_number"]),
            status_code=row["status_code"], error=row["error"],
            duration_ms=int(row["duration_ms"]),
            started_at=int(row["started_at"]),
            finished_at=int(row["finished_at"]))

    def _row(self, delivery_id: int) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM webhook_deliveries WHERE id = ?",
            (int(delivery_id),)).fetchone()

    def _subscription_row(self, webhook_id: int) -> sqlite3.Row | None:
        """The subscription row itself (its current
        standing and stored digest), read from
        S-248's table: the worker judges standing
        and signs from what stands now, while the
        delivery's address and payload stay frozen
        at enqueue."""
        return self._conn.execute(
            "SELECT * FROM webhooks WHERE id = ?",
            (int(webhook_id),)).fetchone()

    # -- enqueue --------------------------------------

    def enqueue_delivery(self, event: CanonicalEvent,
                         subscription: WebhookSubscription,
                         ) -> tuple[WebhookDelivery, bool]:
        """Queue one event for one subscription:
        ``(delivery, created)``. The payload is
        frozen from S-247's `payload_json` (a
        withheld or unknown verb is refused there,
        by its own names, and queues nothing) and
        the address is snapshotted from the
        subscription. A standing delivery for the
        pair is returned unchanged with `created`
        False -- the UNIQUE pair is the
        exactly-once law. Commits before the
        answer."""
        payload_text = payload_json(event)
        now = int(self._now())
        key = delivery_key_for(event.id, subscription.id)
        with self._conn:  # commits before the answer
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO webhook_deliveries"
                " (webhook_id, event_id, verb, delivery_key,"
                " url, host, payload_json, status, attempts,"
                " next_attempt_at, last_status_code, last_error,"
                " created_at, updated_at, delivered_at, dead_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', 0, ?,"
                " NULL, '', ?, ?, NULL, NULL)",
                (subscription.id, int(event.id), event.verb, key,
                 subscription.url, subscription.host, payload_text,
                 now, now, now))
            created = cur.rowcount > 0
        row = self._conn.execute(
            "SELECT * FROM webhook_deliveries"
            " WHERE webhook_id = ? AND event_id = ?"
            " AND redelivery_number = 0",
            (subscription.id, int(event.id))).fetchone()
        assert row is not None
        return (self._view(row), created)

    def enqueue_event(self, event: CanonicalEvent,
                      ) -> tuple[WebhookDelivery, ...]:
        """Queue one event for every subscription
        S-248's routing says receives it, in
        routing order: the deliveries standing for
        the event afterwards (newly queued and
        already standing alike). A withheld or
        unknown verb, and an event no active
        subscription matches, queue nothing and
        answer empty -- routing is the whole law."""
        subscriptions = self._hooks.subscriptions_for_event(event)
        return tuple(
            self.enqueue_delivery(event, sub)[0]
            for sub in subscriptions)

    # -- reads -----------------------------------------

    def get_delivery(self, delivery_id: object) -> WebhookDelivery:
        """One delivery by id: a missing id, or one
        of the wrong shape, is `delivery_not_found`
        -- the log's readers (S-251) judge access;
        this read is the outbox's own."""
        if (isinstance(delivery_id, bool)
                or not isinstance(delivery_id, int)):
            raise WebhookDeliveryError(
                "delivery_not_found", "No such delivery.")
        row = self._row(delivery_id)
        if row is None:
            raise WebhookDeliveryError(
                "delivery_not_found", "No such delivery.")
        return self._view(row)

    def deliveries_for_subscription(self, webhook_id: object, *,
                                    limit: int = 100,
                                    ) -> tuple[WebhookDelivery, ...]:
        """One subscription's deliveries, newest
        first. A webhook id of the wrong shape
        answers empty, like one with no deliveries."""
        if (isinstance(webhook_id, bool)
                or not isinstance(webhook_id, int)):
            return ()
        clamped = max(1, min(int(limit), 500))
        rows = self._conn.execute(
            "SELECT * FROM webhook_deliveries"
            " WHERE webhook_id = ? ORDER BY id DESC LIMIT ?",
            (int(webhook_id), clamped)).fetchall()
        return tuple(self._view(r) for r in rows)

    def deliveries_for_event(self, event_id: object,
                             ) -> tuple[WebhookDelivery, ...]:
        """Every delivery of one event, in enqueue
        order. An event id of the wrong shape
        answers empty."""
        if isinstance(event_id, bool) or not isinstance(event_id, int):
            return ()
        rows = self._conn.execute(
            "SELECT * FROM webhook_deliveries"
            " WHERE event_id = ? ORDER BY id",
            (int(event_id),)).fetchall()
        return tuple(self._view(r) for r in rows)

    def dead_letters(self, *, limit: int = 100,
                     ) -> tuple[WebhookDelivery, ...]:
        """The dead-letter rest: every delivery
        that exhausted its stated attempts (or lost
        its subscription), newest-dead first --
        kept, never dropped, for S-251's faces."""
        clamped = max(1, min(int(limit), 500))
        rows = self._conn.execute(
            "SELECT * FROM webhook_deliveries"
            " WHERE status = 'dead'"
            " ORDER BY dead_at DESC, id DESC LIMIT ?",
            (clamped,)).fetchall()
        return tuple(self._view(r) for r in rows)

    def attempts_for(self, delivery_id: object,
                     ) -> tuple[DeliveryAttempt, ...]:
        """One delivery's attempts, in the order
        they were made -- the delivery log's raw
        material (S-251 renders it). A missing
        delivery is `delivery_not_found`, exactly
        as `get_delivery` judges it."""
        delivery = self.get_delivery(delivery_id)
        rows = self._conn.execute(
            "SELECT * FROM webhook_delivery_attempts"
            " WHERE delivery_id = ? ORDER BY id",
            (delivery.id,)).fetchall()
        return tuple(self._attempt_view(r) for r in rows)

    def counts(self) -> dict[str, int]:
        """The queue said in numbers: a count for
        every standing in DELIVERY_STATUSES,
        zeroes included -- the worker's dashboard
        fact, read live."""
        found = {status: 0 for status in DELIVERY_STATUSES}
        rows = self._conn.execute(
            "SELECT status, COUNT(*) AS n FROM webhook_deliveries"
            " GROUP BY status").fetchall()
        for row in rows:
            if row["status"] in found:
                found[row["status"]] = int(row["n"])
        return found

    # -- the worker ------------------------------------

    def due_deliveries(self, now: object = None, *,
                       limit: int = BATCH_LIMIT,
                       ) -> tuple[WebhookDelivery, ...]:
        """The deliveries this moment owes an
        attempt: standing `queued` or `retrying`
        with `next_attempt_at` come, oldest-due
        first. A pure read -- taking the list
        attempts nothing."""
        moment = int(self._now()) if now is None else int(now)  # type: ignore[arg-type]
        clamped = max(1, min(int(limit), 500))
        rows = self._conn.execute(
            "SELECT * FROM webhook_deliveries"
            " WHERE status IN ('queued', 'retrying')"
            " AND next_attempt_at <= ?"
            " ORDER BY next_attempt_at, id LIMIT ?",
            (moment, clamped)).fetchall()
        return tuple(self._view(r) for r in rows)

    def run_due(self, now: object = None, *,
                limit: int = BATCH_LIMIT) -> DeliveryRun:
        """The worker: attempt every due delivery
        once, oldest-due first, and answer the
        run's honest account. Each attempt commits
        before the next begins, so a worker stopped
        mid-run loses nothing already answered --
        standing rows say exactly what happened.
        A subscription deleted since enqueue rests
        its delivery dead (`subscription_gone`, no
        attempt burned); a subscription inactive
        now is skipped with no attempt counted."""
        moment = int(self._now()) if now is None else int(now)  # type: ignore[arg-type]
        due = self.due_deliveries(moment, limit=limit)
        attempted = delivered = retried = dead = skipped = 0
        for delivery in due:
            sub_row = self._subscription_row(delivery.webhook_id)
            if sub_row is None:
                self._rest_dead(delivery, "subscription_gone", moment)
                dead += 1
                continue
            if not int(sub_row["active"]):
                skipped += 1
                continue
            attempted += 1
            outcome = self._attempt(delivery, sub_row)
            if outcome == "delivered":
                delivered += 1
            elif outcome == "dead":
                dead += 1
            else:
                retried += 1
        return DeliveryRun(
            due=len(due), attempted=attempted, delivered=delivered,
            retried=retried, dead=dead, skipped_inactive=skipped)

    def _rest_dead(self, delivery: WebhookDelivery, error: str,
                   moment: int) -> None:
        """Rest one delivery dead without an attempt
        (its subscription is gone): the reason is
        kept on the row, in the open. Commits
        before the run moves on."""
        with self._conn:
            self._conn.execute(
                "UPDATE webhook_deliveries SET status = 'dead',"
                " last_error = ?, dead_at = ?, updated_at = ?"
                " WHERE id = ?",
                (error, moment, moment, delivery.id))

    def _attempt(self, delivery: WebhookDelivery,
                 sub_row: sqlite3.Row) -> str:
        """One attempt at one delivery: sign the
        frozen payload through S-249 with the
        subscription's current digest, hand the
        bytes to the transport, record the attempt
        row and the delivery's new standing in one
        commit, and answer the outcome in a word
        ('delivered' / 'retrying' / 'dead'). A
        transport that raises is a failure like
        any other -- the worker never raises into
        its run."""
        attempt_number = delivery.attempts + 1
        body = delivery.payload_json.encode("utf-8")
        headers = build_delivery_headers(
            sub_row["secret_digest"], delivery.payload_json,
            delivery.verb, delivery.delivery_key)
        started = int(self._now())
        status_code: int | None = None
        error = ""
        try:
            result = self._transport(
                delivery.url, body, headers,
                DELIVERY_TIMEOUT_SECONDS)
            status_code = int(result.status_code)
            if not 200 <= status_code <= 299:
                error = f"http_{status_code}"
        except Exception as exc:  # a failure, judged -- never raised
            error = _transport_error_name(exc)
        finished = int(self._now())
        duration_ms = max(0, int((finished - started) * 1000))
        success = not error
        with self._conn:  # the attempt and its standing land whole
            self._conn.execute(
                "INSERT INTO webhook_delivery_attempts"
                " (delivery_id, attempt_number, status_code,"
                " error, duration_ms, started_at, finished_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (delivery.id, attempt_number, status_code,
                 error, duration_ms, started, finished))
            if success:
                self._conn.execute(
                    "UPDATE webhook_deliveries SET status = 'delivered',"
                    " attempts = ?, last_status_code = ?,"
                    " last_error = '', delivered_at = ?,"
                    " updated_at = ? WHERE id = ?",
                    (attempt_number, status_code, finished, finished,
                     delivery.id))
                return "delivered"
            if attempt_number >= MAX_ATTEMPTS:
                self._conn.execute(
                    "UPDATE webhook_deliveries SET status = 'dead',"
                    " attempts = ?, last_status_code = ?,"
                    " last_error = ?, dead_at = ?,"
                    " updated_at = ? WHERE id = ?",
                    (attempt_number, status_code, error, finished,
                     finished, delivery.id))
                return "dead"
            delay = backoff_delay(attempt_number)
            jitter = max(0.0, float(self._jitter(delay)))
            next_at = finished + delay + int(jitter)
            self._conn.execute(
                "UPDATE webhook_deliveries SET status = 'retrying',"
                " attempts = ?, last_status_code = ?,"
                " last_error = ?, next_attempt_at = ?,"
                " updated_at = ? WHERE id = ?",
                (attempt_number, status_code, error, next_at,
                 finished, delivery.id))
            return "retrying"


# -- renders -------------------------------------------


def render_delivery(delivery: WebhookDelivery) -> str:
    """One delivery, rendered: its key, its event,
    its address and its standing in words -- every
    value through S-010, the payload itself never
    rendered (it is the receiver's copy, not a
    page's content), and no secret or digest ever
    present to be escaped."""
    return (
        "<li>"
        f"<strong>{escape_html_text(delivery.delivery_key)}</strong> "
        f"({escape_html_text(delivery.verb)}) to "
        f"{escape_html_text(delivery.url)} -- "
        f"{escape_html_text(delivery.status_words)}, "
        f"{delivery.attempts} of {MAX_ATTEMPTS} attempts used."
        "</li>")


def render_delivery_attempt(attempt: DeliveryAttempt) -> str:
    """One attempt, rendered in plain words: its
    number, its outcome and its duration."""
    return (
        "<li>"
        f"{escape_html_text(attempt.words)}"
        "</li>")


def render_deliveries(title: str,
                      deliveries: Iterable[WebhookDelivery]) -> str:
    """Deliveries rendered as a list under a
    title; an empty list teaches the worker's
    model instead of showing a blank: deliveries
    are queued off the request path and attempted
    by the delivery worker, never while anyone
    browses."""
    rows = list(deliveries)
    parts = [f"<h2>{escape_html_text(title)}</h2>"]
    if not rows:
        parts.append(
            "<p>No webhook deliveries yet. When an "
            "event matches a subscription, a delivery "
            "is queued for it off the request path; "
            "the delivery worker attempts it, retries "
            "failures with exponential backoff, and "
            f"dead-letters it after {MAX_ATTEMPTS} "
            "failed attempts.</p>")
        return "\n".join(parts)
    parts.append("<ul>")
    for delivery in rows:
        parts.append(render_delivery(delivery))
    parts.append("</ul>")
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    """The worker's command line, run by an
    operator or a scheduler -- the off-request-path
    entry: ``python3 -m samverk.webhook_delivery
    <db-path> <repos-root>`` drains one due batch
    with the real transport and prints the run's
    honest account."""
    from . import db
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: python3 -m samverk.webhook_delivery "
              "<db-path> <repos-root>")
        return 2
    conn = db.init_db(Path(args[0]))
    accounts = AccountStore(conn)
    repos = RepositoryStore(conn, Path(args[1]), accounts)
    orgs = OrganizationStore(conn, accounts)
    store = WebhookDeliveryStore(conn, repos, orgs, accounts)
    run = store.run_due()
    print(run.words)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
