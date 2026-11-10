"""Webhook ping and test events (S-252).

Webhook ping and test events -- a synthetic event
on demand so integrations can be proven before
they matter. S-247 stated the payload, S-248
built the subscriptions, S-249 stated the
signing, S-250 built the delivery worker and
S-251 its log; this slice is the on-demand
synthetic sender that proves a subscription's
whole road -- address, signing, the worker, the
log -- without waiting for a real mutation, and
without faking one.

- **Synthetic, and said so everywhere.** A ping
  or test event is NOT a canonical event: nothing
  is written to S-221's event store, no audit verb
  is spent on the payload itself, and the payload
  carries its standing in the open -- its detail
  holds `synthetic: true` and `test: true`, a
  ping's event name is the literal `ping` (no
  taxonomy verb claims it), and a test event
  carries a real deliverable verb's name with
  sample detail (below). A receiver can always
  tell a proof from the thing it proves. The
  taxonomy is untouched: 131 verbs stand
  (33 auth / 85 repo / 13 admin), and S-247's
  audit still ratifies -- `ping` is not added to
  it, because a ping is not an event the store
  witnessed.
- **The payload is S-247's envelope, unchanged.**
  Both kinds answer a dict with exactly
  `PAYLOAD_FIELDS`, in envelope order: a ping's
  `delivery_id` is `ping-<ping id>`, a test
  event's is `test-<ping id>` -- stable for that
  proof, unique per proof, and never of the
  `evt-<event id>` shape a real event carries, so
  a receiver's dedupe can never confuse a proof
  with a witnessed delivery. The bytes queued are
  the canonical JSON of that envelope (sorted
  keys, tight separators), exactly the bytes
  S-249 signs and S-250 delivers.
- **A ping proves the road.** Its detail is
  fixed: the kind, a plain-words message, and the
  synthetic markers. It names its subscription's
  parent as target (the repository, or the
  organization) and the sender as actor. If a
  ping is delivered, the address answers, the
  signature verifies (when a secret is set), and
  the worker and the log both work -- proven
  before any real event matters.
- **A test event proves one verb.** The sender
  names one verb from S-247's taxonomy; the
  payload carries that verb, its action, and
  sample detail built by one stated rule from
  the verb's own S-247 detail contract: the
  `number` key samples as 1, every other key as
  the words `test-<key>` -- safe specifics only,
  never a title, a body, a token or a secret
  (S-018's law). Judged at the door by S-247's
  own names: an unknown verb is
  `webhook_event_unknown`, a withheld verb is
  `webhook_event_not_deliverable`, and an
  organization-scope verb named for a repository
  subscription is `webhook_event_scope_mismatch`
  (no repository hook ever carries those verbs,
  S-247's scope law). A test event is sent to
  the ONE subscription named, whatever its
  filter holds: the sender chose that
  subscription and that verb, and a proof that
  silently obeyed the filter would prove the
  filter, not the integration. Routing real
  events stays S-248's law, untouched.
- **Delivery is S-250's outbox, entered
  directly.** A send queues ONE fresh row in
  `webhook_deliveries` -- the frozen payload, the
  address snapshotted from the subscription as
  it stands now, standing `queued`, due at
  once, zero attempts -- keyed `ping-<ping id>-
  hook-<subscription id>` (or `test-...`), with
  the row's `event_id` the negative of the ping
  id: canonical event ids are positive, so a
  synthetic delivery can never collide with, or
  be mistaken for, a witnessed event's delivery,
  and each send is its own row (a ping is a
  proof demanded now, never exactly-once
  deduped against an earlier proof). The S-250
  worker carries the row on its next run like
  any delivery -- signed through S-249 with the
  subscription's current digest, the event
  header naming `ping` or the test verb -- and
  S-251's log shows it like any delivery. This
  module attempts nothing itself.
- **An inactive subscription proves nothing, so
  it is refused.** A send to an inactive
  subscription is refused `subscription_inactive`,
  in words: the worker would skip it (S-250's
  law) and the proof would silently never
  arrive. Reactivate the subscription (S-248)
  and send again. Refusals of every kind queue
  nothing and witness nothing.
- **Who may send is S-248's gate, never a new
  one.** Sending for a repository subscription
  needs the admin rung in that repository
  (S-190) or a site admin; for an organization
  subscription, an owner of the organization
  (S-186) or a site admin. Anonymous callers are
  refused `authentication_required` before any
  row is read; a repository the caller cannot
  see answers the uniform `repo_not_found`, one
  they can see below admin answers
  `admin_required`; a missing organization is
  `org_not_found` and a non-owner
  `not_org_owner`; a subscription id named under
  the wrong parent answers
  `subscription_not_found`, because the read is
  scoped by its parent in the query itself.
  Reading the ping history answers to the same
  gate; a ping whose subscription is gone
  answers only to a site admin (the gate fails
  closed, S-251's law).
- **Witnessed on the standing verbs.** A send
  is a manager's act, witnessed like S-248's
  subscription changes and S-251's redeliveries,
  with no new taxonomy event: a repository send
  rides `repo.settings.change` with the key
  `webhook.ping` or `webhook.test` named, an
  organization send rides
  `auth.organization.update` with `fields`
  `webhooks` and action `ping` or `test`. The
  detail carries the host, the delivery key and,
  for a test event, the verb -- never the
  payload, never a secret. Reads witness
  nothing. Every send commits its ping row and
  its delivery row whole, before its answer.

One migration: 99 creates `webhook_pings`
(schema 98 to 99) -- one row per send, naming
its subscription, its kind and verb, the outbox
delivery it queued, who sent it and when; the
history every face here reads.
"""
from __future__ import annotations

import json
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
from .webhook_delivery import WebhookDelivery, WebhookDeliveryStore
from .webhook_delivery_log import can_inspect
from .webhook_events import (
    PAYLOAD_FIELDS, WebhookEventSpec, WebhookEventsError,
    get_webhook_event)

__all__ = [
    "KINDS", "PING_EVENT", "PING_MESSAGE", "WebhookPing",
    "WebhookPingError", "WebhookPingStore",
    "build_ping_payload", "build_test_payload",
    "decide_send", "ping_delivery_key_for", "ping_payload_json",
    "sample_detail", "test_delivery_key_for",
    "validate_ping_kind", "validate_test_verb",
    "render_webhook_ping", "render_webhook_pings",
]

#: The two synthetic kinds a sender may demand,
#: in the order a person looks for them: the
#: road itself, then one verb over it.
KINDS = ("ping", "test")

#: A ping's event name: the literal word, claimed
#: by no taxonomy verb, so a receiver (and a log
#: reader) can never mistake the proof for an
#: event the store witnessed.
PING_EVENT = "ping"

#: A ping's message, said in plain words in its
#: detail: what this delivery is and what its
#: arrival proves.
PING_MESSAGE = (
    "Samverk webhook ping: if this delivery "
    "arrived, the address answers, the signature "
    "verifies (when a secret is set), and the "
    "delivery worker and log work -- proven "
    "before a real event matters.")


class WebhookPingError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


# -- pure law ---------------------------------------


def validate_ping_kind(kind: object) -> str:
    """Pure: the stored kind for *kind*, or a
    refusal naming the honest set of two."""
    if not isinstance(kind, str) or kind not in KINDS:
        raise WebhookPingError(
            "webhook_ping_kind_invalid",
            "A synthetic send is a ping or a test "
            "event; say which.")
    return kind


def decide_send(active: object) -> None:
    """Pure: judge one send against its
    subscription's standing, raising
    `subscription_inactive` when the subscription
    stands inactive -- the worker would skip its
    delivery and the proof would silently never
    arrive, so the send is refused in words
    instead. An active subscription answers
    None: the send may proceed."""
    if not active:
        raise WebhookPingError(
            "subscription_inactive",
            "This subscription is inactive: a "
            "ping or test event sent to it would "
            "never be attempted. Reactivate the "
            "subscription and send again.")


def validate_test_verb(verb: object, level: str) -> WebhookEventSpec:
    """Pure: one test event's verb, judged by
    S-247's own taxonomy and names: unknown is
    `webhook_event_unknown`, withheld is
    `webhook_event_not_deliverable`, and an
    organization-scope verb named for a
    repository subscription is
    `webhook_event_scope_mismatch`. Answers the
    verb's spec, for its action and detail
    contract."""
    try:
        spec = get_webhook_event(verb)
    except WebhookEventsError as exc:
        raise WebhookPingError(exc.reason, str(exc)) from exc
    if not spec.deliverable:
        raise WebhookPingError(
            "webhook_event_not_deliverable",
            "This event is never delivered as a "
            "webhook, so it cannot be tested as "
            "one.")
    if level == "repository" and spec.scope == "organization":
        raise WebhookPingError(
            "webhook_event_scope_mismatch",
            "An organization event cannot be "
            "tested through a repository "
            "subscription: no repository hook "
            "ever carries it.")
    return spec


def sample_detail(spec: WebhookEventSpec) -> dict:
    """Pure: one test event's detail, built from
    the verb's own S-247 detail contract by one
    stated rule -- the `number` key samples as
    the integer 1, every other key as the words
    `test-<key>` -- under the synthetic markers
    every proof carries. Safe specifics only:
    no title, body, token or secret can appear,
    because no key's sample is read from
    anywhere."""
    detail: dict = {"synthetic": True, "test": True}
    for field in spec.detail_fields:
        detail[field] = 1 if field == "number" else f"test-{field}"
    return detail


def _envelope(*, delivery_id: str, event: str, action: str,
              actor: str, level: str, parent_name: str,
              parent_key: str, detail: dict,
              occurred_at: int) -> dict:
    """One synthetic payload in S-247's envelope:
    exactly PAYLOAD_FIELDS, in envelope order.
    The target is the subscription's parent (the
    repository's full name, or the organization's
    key); the repository field names the
    repository for a repository parent and is
    None for an organization parent, whose proof
    belongs to no single repository."""
    if level == "repository":
        target: str | None = parent_name
        repository: str | None = parent_key
        refs = [f"repo:{parent_key}"]
    else:
        target = parent_key
        repository = None
        refs = [f"org:{parent_key}"]
    return {
        "delivery_id": delivery_id,
        "event": event,
        "action": action,
        "actor": actor or None,
        "target": target,
        "repository": repository,
        "number": None,
        "refs": refs,
        "detail": detail,
        "occurred_at": int(occurred_at),
    }


def ping_delivery_key_for(ping_id: int, webhook_id: int) -> str:
    """Pure: one ping's delivery key -- its own
    stem, never S-250's `evt-` stem, so a receiver
    dedupes a proof as a proof."""
    return f"ping-{int(ping_id)}-hook-{int(webhook_id)}"


def test_delivery_key_for(ping_id: int, webhook_id: int) -> str:
    """Pure: one test event's delivery key, on
    the same law as a ping's."""
    return f"test-{int(ping_id)}-hook-{int(webhook_id)}"


def build_ping_payload(*, ping_id: int, actor: str, level: str,
                       parent_name: str, parent_key: str,
                       occurred_at: int) -> dict:
    """Pure: one ping's payload -- S-247's
    envelope carrying the literal `ping` event,
    the sender as actor, the subscription's
    parent as target, and the fixed detail: the
    kind, the plain-words message, and the
    synthetic markers."""
    return _envelope(
        delivery_id=f"ping-{int(ping_id)}", event=PING_EVENT,
        action=PING_EVENT, actor=actor, level=level,
        parent_name=parent_name, parent_key=parent_key,
        detail={"kind": "ping", "message": PING_MESSAGE,
                "synthetic": True, "test": True},
        occurred_at=occurred_at)


def build_test_payload(*, ping_id: int, spec: WebhookEventSpec,
                       actor: str, level: str, parent_name: str,
                       parent_key: str, occurred_at: int) -> dict:
    """Pure: one test event's payload -- S-247's
    envelope carrying the named verb, its action,
    and the sample detail its contract earns."""
    return _envelope(
        delivery_id=f"test-{int(ping_id)}", event=spec.verb,
        action=spec.action, actor=actor, level=level,
        parent_name=parent_name, parent_key=parent_key,
        detail=sample_detail(spec), occurred_at=occurred_at)


def ping_payload_json(payload: dict) -> str:
    """The payload as canonical JSON (sorted
    keys, tight separators) -- the exact bytes
    queued, signed and delivered."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


# -- the record --------------------------------------


@dataclass(frozen=True)
class WebhookPing:
    """One synthetic send as every face shows it:
    the ping row (its kind, its verb, who sent it
    and when), its subscription named by level
    and parent (never by secret -- only whether
    one is set, in words), and the outbox delivery
    it queued, whole. Every ping is synthetic by
    construction; the record says so in words."""
    id: int
    webhook_id: int
    kind: str
    verb: str
    delivery_key: str
    actor_id: int
    created_at: int
    level: str
    parent_name: str
    parent_key: str
    url: str
    host: str
    subscription_active: bool | None
    subscription_has_secret: bool | None
    delivery: WebhookDelivery

    @property
    def synthetic(self) -> bool:
        return True

    @property
    def is_test_event(self) -> bool:
        return self.kind == "test"

    @property
    def kind_words(self) -> str:
        if self.kind == "ping":
            return "webhook ping"
        return f"test event ({self.verb})"

    @property
    def secret_words(self) -> str:
        if self.subscription_has_secret is None:
            return "subscription gone"
        if self.subscription_has_secret:
            return "a secret is set (never shown)"
        return "no secret set"

    @property
    def words(self) -> str:
        """The send said in plain words: what
        proof, for which parent, to where, its
        delivery's standing, and that it is
        synthetic -- a proof, not a witnessed
        event."""
        d = self.delivery
        return (
            f"Synthetic {self.kind_words} "
            f"{self.delivery_key} for "
            f"{self.parent_name} to {self.url}: "
            f"{d.status_words}, {d.attempts} of 5 "
            f"attempts used; {self.secret_words}. "
            f"This is a test delivery, not a real "
            f"{self.verb} event.")


# -- the store ----------------------------------------


class WebhookPingStore:
    """The synthetic sender over migration 99's
    `webhook_pings` and S-250's outbox, gated by
    S-248's own standings (S-190's admin rung,
    S-186's owners, site admins). A send commits
    its ping row and its delivery row whole
    before its answer and is witnessed on the
    standing verbs (see the module docstring);
    reads commit and witness nothing."""

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

    def _view(self, row: sqlite3.Row) -> WebhookPing:
        hook = self._conn.execute(
            "SELECT * FROM webhooks WHERE id = ?",
            (int(row["webhook_id"]),)).fetchone()
        delivery = self._deliveries.get_delivery(
            int(row["delivery_id"]))
        if hook is None:
            return WebhookPing(
                id=int(row["id"]),
                webhook_id=int(row["webhook_id"]),
                kind=row["kind"], verb=row["verb"],
                delivery_key=row["delivery_key"],
                actor_id=int(row["actor_id"]),
                created_at=int(row["created_at"]),
                level="", parent_name="", parent_key="",
                url=delivery.url, host=delivery.host,
                subscription_active=None,
                subscription_has_secret=None,
                delivery=delivery)
        return WebhookPing(
            id=int(row["id"]),
            webhook_id=int(row["webhook_id"]),
            kind=row["kind"], verb=row["verb"],
            delivery_key=row["delivery_key"],
            actor_id=int(row["actor_id"]),
            created_at=int(row["created_at"]),
            level=hook["level"],
            parent_name=hook["parent_name"],
            parent_key=hook["parent_key"],
            url=hook["url"], host=hook["host"],
            subscription_active=bool(hook["active"]),
            subscription_has_secret=bool(hook["secret_digest"]),
            delivery=delivery)

    # -- the gate -------------------------------------

    @staticmethod
    def _require_user(user: User | None) -> User:
        if user is None:
            raise WebhookPingError(
                "authentication_required",
                "Sign in to send a webhook ping or "
                "test event.")
        return user

    def _resolve_repo(self, user: User, owner: object, repo: object):
        """The repository under S-248's gate:
        missing, or held at no role, is the
        uniform `repo_not_found`; visible below
        admin is `admin_required`."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise WebhookPingError(
                "repo_not_found", "No such repository.")
        role = self._engine.resolve(user, current).role
        if role is None:
            raise WebhookPingError(
                "repo_not_found", "No such repository.")
        if not can_inspect(is_site_admin=user.is_admin,
                           level="repository", repo_role=role):
            raise WebhookPingError(
                "admin_required",
                "Sending a webhook ping or test "
                "event needs admin on the repository.")
        return current

    def _resolve_org(self, user: User, org: object):
        """The organization under S-248's gate: a
        missing organization is `org_not_found`;
        anyone but an owner or a site admin is
        `not_org_owner`."""
        current = self._orgs.get_by_name(org)
        if current is None:
            raise WebhookPingError(
                "org_not_found", "No such organization.")
        org_role = self._members.role_for(user.id, current.id)
        if not can_inspect(is_site_admin=user.is_admin,
                           level="organization",
                           org_role=org_role):
            raise WebhookPingError(
                "not_org_owner",
                "Sending a webhook ping or test "
                "event needs an owner of the "
                "organization.")
        return current

    def _subscription_row(self, level: str, parent_id: int,
                          subscription_id: object) -> sqlite3.Row:
        """One subscription row, read scoped by
        its parent in the query itself: an id of
        the wrong shape, a missing id, or one
        named under the wrong parent answers the
        one `subscription_not_found`."""
        if (isinstance(subscription_id, bool)
                or not isinstance(subscription_id, int)):
            raise WebhookPingError(
                "subscription_not_found",
                "No such webhook subscription.")
        column = "repo_id" if level == "repository" else "org_id"
        row = self._conn.execute(
            "SELECT * FROM webhooks WHERE level = ?"
            f" AND {column} = ? AND id = ?",
            (level, int(parent_id), int(subscription_id))).fetchone()
        if row is None:
            raise WebhookPingError(
                "subscription_not_found",
                "No such webhook subscription.")
        return row

    def _gate_ping(self, user: User, row: sqlite3.Row) -> None:
        """Judge *user*'s standing over one
        standing ping, through its subscription's
        parent -- the same gate as a send. A ping
        whose subscription is gone answers only
        to a site admin; everyone else is refused
        `admin_required`, the closed door."""
        hook = self._conn.execute(
            "SELECT * FROM webhooks WHERE id = ?",
            (int(row["webhook_id"]),)).fetchone()
        if hook is None:
            if user.is_admin:
                return
            raise WebhookPingError(
                "admin_required",
                "This ping's subscription is gone; "
                "only a site admin can inspect it.")
        if hook["level"] == "repository":
            owner, _, name = hook["parent_key"].partition("/")
            repo = self._repos.get_repository(owner, name)
            if repo is None:
                raise WebhookPingError(
                    "repo_not_found", "No such repository.")
            role = self._engine.resolve(user, repo).role
            if role is None:
                raise WebhookPingError(
                    "repo_not_found", "No such repository.")
            if not can_inspect(is_site_admin=user.is_admin,
                               level="repository", repo_role=role):
                raise WebhookPingError(
                    "admin_required",
                    "Webhook pings need admin on the "
                    "repository.")
            return
        org = self._orgs.get_by_id(int(hook["org_id"]))
        if org is None:
            raise WebhookPingError(
                "org_not_found", "No such organization.")
        org_role = self._members.role_for(user.id, org.id)
        if not can_inspect(is_site_admin=user.is_admin,
                           level="organization",
                           org_role=org_role):
            raise WebhookPingError(
                "not_org_owner",
                "Webhook pings need an owner of the "
                "organization.")

    # -- sends -----------------------------------------

    def _witness(self, user: User, hook: sqlite3.Row, kind: str,
                 verb: str, delivery_key: str,
                 source_ip: str | None) -> None:
        """One send, witnessed on the standing
        verbs (see the module docstring): the
        detail carries the host and the delivery
        key, and a test event's verb -- never the
        payload, never a secret."""
        if self._audit is None:
            return
        if hook["level"] == "repository":
            detail = {"key": f"webhook.{kind}",
                      "host": hook["host"],
                      "delivery": delivery_key}
            if kind == "test":
                detail["verb"] = verb
            self._audit.append(
                actor_kind="user", actor_id=user.id,
                action="repo.settings.change",
                target_kind="repo",
                target_id=hook["parent_name"],
                outcome="success", source_ip=source_ip,
                detail=detail)
        else:
            detail = {"fields": "webhooks", "action": kind,
                      "host": hook["host"],
                      "delivery": delivery_key}
            if kind == "test":
                detail["verb"] = verb
            self._audit.append(
                actor_kind="user", actor_id=user.id,
                action="auth.organization.update",
                target_kind="organization",
                target_id=hook["parent_key"],
                outcome="success", source_ip=source_ip,
                detail=detail)

    def _send(self, user: User, hook: sqlite3.Row, kind: str,
              verb: str, spec: WebhookEventSpec | None,
              source_ip: str | None) -> WebhookPing:
        """The one send road: judge the standing,
        mint the ping row and its outbox delivery
        in one commit, witness, and answer the
        ping whole. The delivery is queued, never
        attempted here -- the S-250 worker carries
        it off the request path."""
        decide_send(bool(hook["active"]))
        now = int(self._now())
        with self._conn:  # the ping and its delivery land whole
            cur = self._conn.execute(
                "INSERT INTO webhook_pings"
                " (webhook_id, kind, verb, delivery_id,"
                " delivery_key, actor_id, created_at)"
                " VALUES (?, ?, ?, 0, '', ?, ?)",
                (int(hook["id"]), kind, verb, user.id, now))
            ping_id = int(cur.lastrowid)
            if kind == "ping":
                payload = build_ping_payload(
                    ping_id=ping_id, actor=user.username,
                    level=hook["level"],
                    parent_name=hook["parent_name"],
                    parent_key=hook["parent_key"],
                    occurred_at=now)
                key = ping_delivery_key_for(ping_id, int(hook["id"]))
            else:
                assert spec is not None  # judged at the door
                payload = build_test_payload(
                    ping_id=ping_id, spec=spec,
                    actor=user.username, level=hook["level"],
                    parent_name=hook["parent_name"],
                    parent_key=hook["parent_key"],
                    occurred_at=now)
                key = test_delivery_key_for(ping_id, int(hook["id"]))
            cur = self._conn.execute(
                "INSERT INTO webhook_deliveries"
                " (webhook_id, event_id, verb, delivery_key,"
                " url, host, payload_json, status, attempts,"
                " next_attempt_at, last_status_code, last_error,"
                " created_at, updated_at, delivered_at, dead_at,"
                " redelivery_of, redelivery_number)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', 0, ?,"
                " NULL, '', ?, ?, NULL, NULL, NULL, 0)",
                (int(hook["id"]), -ping_id, verb, key,
                 hook["url"], hook["host"],
                 ping_payload_json(payload), now, now, now))
            delivery_id = int(cur.lastrowid)
            self._conn.execute(
                "UPDATE webhook_pings SET delivery_id = ?,"
                " delivery_key = ? WHERE id = ?",
                (delivery_id, key, ping_id))
        row = self._conn.execute(
            "SELECT * FROM webhook_pings WHERE id = ?",
            (ping_id,)).fetchone()
        ping = self._view(row)
        self._witness(user, hook, kind, verb, key, source_ip)
        return ping

    def send_repository_ping(self, user: User | None, owner: object,
                             repo: object, subscription_id: object,
                             source_ip: str | None = None,
                             ) -> WebhookPing:
        """Send a ping to one repository
        subscription, on demand: the caller holds
        admin in the repository (S-190) or is a
        site admin, the subscription stands
        active, and one synthetic `ping` delivery
        is queued for the worker."""
        actor = self._require_user(user)
        current = self._resolve_repo(actor, owner, repo)
        hook = self._subscription_row(
            "repository", current.id, subscription_id)
        return self._send(actor, hook, "ping", PING_EVENT, None,
                          source_ip)

    def send_organization_ping(self, user: User | None, org: object,
                               subscription_id: object,
                               source_ip: str | None = None,
                               ) -> WebhookPing:
        """Send a ping to one organization
        subscription, on demand: the caller owns
        the organization (S-186) or is a site
        admin, the subscription stands active, and
        one synthetic `ping` delivery is queued
        for the worker."""
        actor = self._require_user(user)
        current = self._resolve_org(actor, org)
        hook = self._subscription_row(
            "organization", current.id, subscription_id)
        return self._send(actor, hook, "ping", PING_EVENT, None,
                          source_ip)

    def send_repository_test_event(
            self, user: User | None, owner: object, repo: object,
            subscription_id: object, verb: object,
            source_ip: str | None = None) -> WebhookPing:
        """Send a synthetic test event for one
        named verb to one repository subscription:
        the verb is judged by S-247's taxonomy at
        the door (unknown, withheld and
        organization-scope verbs refused by their
        own names), and the proof goes to this
        subscription whatever its filter holds."""
        actor = self._require_user(user)
        current = self._resolve_repo(actor, owner, repo)
        hook = self._subscription_row(
            "repository", current.id, subscription_id)
        spec = validate_test_verb(verb, "repository")
        return self._send(actor, hook, "test", spec.verb, spec,
                          source_ip)

    def send_organization_test_event(
            self, user: User | None, org: object,
            subscription_id: object, verb: object,
            source_ip: str | None = None) -> WebhookPing:
        """Send a synthetic test event for one
        named verb to one organization
        subscription: repository-scope and
        organization-scope verbs alike may be
        proven here; withheld and unknown verbs
        are refused by S-247's own names."""
        actor = self._require_user(user)
        current = self._resolve_org(actor, org)
        hook = self._subscription_row(
            "organization", current.id, subscription_id)
        spec = validate_test_verb(verb, "organization")
        return self._send(actor, hook, "test", spec.verb, spec,
                          source_ip)

    # -- reads -----------------------------------------

    def _ping_row(self, ping_id: object) -> sqlite3.Row:
        """One ping row by id: a missing id, or
        one of the wrong shape, is the one
        `webhook_ping_not_found` -- the same
        answer whatever the caller may see."""
        if isinstance(ping_id, bool) or not isinstance(ping_id, int):
            raise WebhookPingError(
                "webhook_ping_not_found", "No such webhook ping.")
        row = self._conn.execute(
            "SELECT * FROM webhook_pings WHERE id = ?",
            (int(ping_id),)).fetchone()
        if row is None:
            raise WebhookPingError(
                "webhook_ping_not_found", "No such webhook ping.")
        return row

    def get_ping(self, user: User | None,
                 ping_id: object) -> WebhookPing:
        """One synthetic send, whole, with the
        delivery it queued: the caller passes the
        send's own gate or is refused by name. A
        pure read."""
        actor = self._require_user(user)
        row = self._ping_row(ping_id)
        self._gate_ping(actor, row)
        return self._view(row)

    def _list(self, hook_ids: list[int],
              limit: int) -> tuple[WebhookPing, ...]:
        if not hook_ids:
            return ()
        clamped = max(1, min(int(limit), 500))
        marks = ",".join("?" for _ in hook_ids)
        rows = self._conn.execute(
            "SELECT * FROM webhook_pings"
            f" WHERE webhook_id IN ({marks})"
            " ORDER BY id DESC LIMIT ?",
            (*hook_ids, clamped)).fetchall()
        return tuple(self._view(r) for r in rows)

    def pings_for_repository(self, user: User | None, owner: object,
                             repo: object, *, limit: int = 100,
                             ) -> tuple[WebhookPing, ...]:
        """One repository's synthetic sends, newest
        first: every ping and test event sent to
        every subscription the repository holds,
        each with the delivery it queued. The gate
        is S-248's repository gate."""
        actor = self._require_user(user)
        current = self._resolve_repo(actor, owner, repo)
        hooks = self._conn.execute(
            "SELECT id FROM webhooks"
            " WHERE level = 'repository' AND repo_id = ?",
            (current.id,)).fetchall()
        return self._list([int(h["id"]) for h in hooks], limit)

    def pings_for_organization(self, user: User | None, org: object,
                               *, limit: int = 100,
                               ) -> tuple[WebhookPing, ...]:
        """One organization's synthetic sends,
        newest first, under S-248's organization
        gate: an owner or a site admin."""
        actor = self._require_user(user)
        current = self._resolve_org(actor, org)
        hooks = self._conn.execute(
            "SELECT id FROM webhooks"
            " WHERE level = 'organization' AND org_id = ?",
            (current.id,)).fetchall()
        return self._list([int(h["id"]) for h in hooks], limit)

    def counts_for(self, pings: Iterable[WebhookPing],
                   ) -> dict[str, int]:
        """The kinds said in numbers over a history
        already read: a count for every kind in
        KINDS, zeroes included."""
        found = {kind: 0 for kind in KINDS}
        for ping in pings:
            if ping.kind in found:
                found[ping.kind] += 1
        return found


# -- renders -------------------------------------------


def render_webhook_ping(ping: WebhookPing) -> str:
    """One synthetic send, rendered whole: its
    kind and key, its parent and address, that it
    is synthetic said in words, its delivery's
    standing and attempts, and whether a secret
    is set -- in words. Every value passes
    through S-010; the payload is never rendered
    and no secret or digest is ever present to be
    escaped."""
    d = ping.delivery
    return (
        "<li>"
        f"<strong>{escape_html_text(ping.delivery_key)}</strong> "
        f"({escape_html_text(ping.kind_words)}) for "
        f"{escape_html_text(ping.parent_name)} to "
        f"{escape_html_text(ping.url)} -- synthetic test "
        f"delivery, not a real {escape_html_text(ping.verb)} "
        f"event: {escape_html_text(d.status_words)}, "
        f"{d.attempts} of 5 attempts used; "
        f"{escape_html_text(ping.secret_words)}."
        "</li>")


def render_webhook_pings(
        title: str, pings: Iterable[WebhookPing]) -> str:
    """A synthetic-send history rendered as a
    page under a title: every send whole (see
    `render_webhook_ping`). An empty history
    teaches the model instead of showing a blank:
    a ping or a test event can be sent on demand
    from a subscription, is queued for the
    delivery worker, and lands in the delivery
    log when attempted."""
    rows = list(pings)
    parts = [f"<h2>{escape_html_text(title)}</h2>"]
    if not rows:
        parts.append(
            "<p>No webhook pings or test events "
            "sent yet. A subscription's managers "
            "can send a ping -- or a test event for "
            "one named event -- on demand: the "
            "synthetic delivery is queued for the "
            "delivery worker and appears in the "
            "delivery log when attempted, proving "
            "the integration before a real event "
            "matters.</p>")
        return "\n".join(parts)
    parts.append("<ul>")
    for ping in rows:
        parts.append(render_webhook_ping(ping))
    parts.append("</ul>")
    return "\n".join(parts)
