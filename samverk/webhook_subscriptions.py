"""Webhook subscriptions (S-248).

Repo and org level, event filters, active/inactive,
secret set at creation and never shown again.
S-247 mapped the event store's verbs to webhook
payloads and stated the scope law; this slice is
the subscription store built on that taxonomy:
who receives which events, at what address, under
what secret. S-249 signs these subscriptions'
payloads, S-250 delivers to them, S-251 keeps
their delivery log; none of them invents its own
subscription record.

- **Two levels, one record.** A subscription
  lives at repository level (it receives its own
  repository's events) or organization level (it
  receives the events of the organization's
  repositories, plus the organization-scope
  events). Migration 96's `webhooks`
  holds both in one table, the level named on the
  row (the table is named for the hook, not the
  subscription, because S-202's billing audit
  forbids billing-shaped names for tables -- a
  webhook subscription is not a billing
  subscription, S-225's law); a row names exactly
  one parent -- a
  repository id or an organization id, never
  both, never neither.
- **Filters are S-247's vocabulary, judged at
  the door.** A filter names event verbs and/or
  categories from `samverk/webhook_events.py`,
  stored as chosen -- the verbs picked, the
  categories picked -- and expanded to the
  effective verb set only when matching, so the
  record always shows what the person actually
  chose. An unknown verb is refused
  `webhook_event_unknown` and an unknown category
  `webhook_category_unknown` (S-247's reasons,
  verbatim); a verb or category the taxonomy
  withholds is refused
  `webhook_event_not_deliverable` /
  `webhook_category_not_deliverable`; an
  organization-scope verb on a repository
  subscription is refused
  `webhook_event_scope_mismatch`, because no
  repository hook ever carries those verbs
  (S-247's scope law). A filter naming nothing
  is refused `webhook_filter_required`: a hook
  subscribed to nothing is a mistake, not a
  standing. Every refusal stores nothing.
- **Permission is S-190's, and the org owners'.**
  Managing a repository's subscriptions needs
  the `admin` rung in that repository, resolved
  through S-190's `PermissionEngine` and nothing
  else: a missing repository, or one the caller
  holds no role in, answers the uniform
  `repo_not_found`; a caller who can see the
  repository but stands below admin is refused
  `admin_required`, in words. Managing an
  organization's subscriptions needs an owner of
  the organization (S-186's `role_for`), or a
  site admin under the house stewardship road:
  a missing organization is `org_not_found`, a
  member who is not an owner (or a stranger) is
  refused `not_org_owner`. An anonymous caller
  is refused `authentication_required` on every
  face. A subscription id is always read scoped
  by its parent in the query itself, so an id
  named under the wrong parent answers
  `subscription_not_found`.
- **The secret is set at creation and never
  shown again.** A subscription may carry a
  secret, handed in at creation only. Only its
  SHA-256 digest is stored -- the S-006 law, as
  S-032's tokens keep it -- so a stolen database
  holds no usable webhook secret, and no face
  ever returns the secret or its digest: every
  view carries only `has_secret`, said in words.
  `verify_secret` answers whether a candidate
  matches, comparing digests in constant time;
  that is the only question any face may ask of
  it. There is no update path for the secret:
  changing it means deleting the subscription
  and creating its successor, so the change is
  two witnessed rows, never a silent edit
  (S-031's deploy-key law).
- **Active and inactive, honestly.** A
  subscription is created active unless its
  creator says otherwise, and may be switched
  either way; an inactive subscription matches
  nothing and receives nothing, and its standing
  is said in words on every face, never by
  colour or icon alone. Re-setting the held
  standing, and an update that changes nothing,
  are quiet no-ops: no row moves and nothing is
  witnessed (the S-149 settings pattern).
- **Matching is the delivery law S-247
  promised.** The pure `decide_match` judges one
  subscription against one event: the
  subscription must be active, the verb
  deliverable and inside the subscription's
  effective filter, and the event's home must be
  the subscription's own -- a repository
  subscription matches only its own repository's
  events; an organization subscription matches
  its organization's repositories' events and,
  for organization-scope verbs, events targeted
  at the organization itself. A repository
  subscription never matches an
  organization-scope event. `subscriptions_for_event`
  gathers the standing matches for one canonical
  event, in creation order; S-250 delivers to
  exactly that set.
- **Witnessed by the verbs that already stand.**
  No new taxonomy event: 131 stand (33 auth /
  85 repo / 13 admin). A repository
  subscription's creation appends
  `repo.webhook.add` and its deletion
  `repo.webhook.remove`, each carrying the
  target host only -- never the secret, never
  the full URL. A real update (address, filter
  or standing) rides `repo.settings.change`
  with the key `webhook.update` named, as
  S-031's deploy keys ride it. Organization
  subscriptions ride `auth.organization.update`
  with `fields` `webhooks` and the action named
  (`add` / `update` / `remove`), the road
  S-186's membership and S-192's defaults
  already travel. Refusals and quiet no-ops
  witness nothing. Every write commits before
  its answer.

One migration: 96 creates `webhooks`
(schema 95 to 96).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urlparse

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .event_store import CanonicalEvent
from .organization_members import OrgMembershipStore
from .organizations import Organization, OrganizationStore
from .permission_engine import PermissionEngine
from .repositories import Repository, RepositoryStore
from .team_permissions import role_covers
from .webhook_events import (
    WEBHOOK_EVENTS, WebhookEventsError, get_webhook_event,
    verbs_for_category)

__all__ = [
    "LEVELS", "SECRET_MAX", "URL_MAX", "WebhookSubscription",
    "WebhookSubscriptionError", "WebhookSubscriptionStore",
    "decide_match", "expand_filter", "secret_digest",
    "secret_matches", "validate_active", "validate_category_filter",
    "validate_event_filter", "validate_filter", "validate_level",
    "validate_secret", "validate_webhook_url",
    "render_webhook_subscription", "render_webhook_subscriptions",
]

#: The two levels a subscription may live at, in
#: the order a person looks for them.
LEVELS = ("repository", "organization")

_LEVEL_WORDS = {
    "repository": "repository",
    "organization": "organization",
}

# The scopes of S-247's law each level may carry:
# a repository hook carries repository scope
# only; an organization hook carries repository
# scope (its repositories' events) and
# organization scope.
_LEVEL_SCOPES = {
    "repository": ("repository",),
    "organization": ("repository", "organization"),
}

URL_MAX = 500
SECRET_MAX = 200


class WebhookSubscriptionError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


# -- pure validators --------------------------------


def validate_level(level: object) -> str:
    """Pure: the stored level for *level*, or a
    refusal naming the honest set of two."""
    if not isinstance(level, str) or level not in LEVELS:
        raise WebhookSubscriptionError(
            "webhook_level_invalid",
            "A webhook subscription lives at "
            "repository level or organization level.")
    return level


def validate_webhook_url(url: object) -> str:
    """Pure: the delivery address, judged whole.
    It must be a real http(s) URL naming a host:
    no other scheme, no embedded credentials (an
    address that carries its own secret would
    leak it into every page and log), no fragment,
    no spaces or controls, at most URL_MAX
    characters. Anything else is refused
    `webhook_url_invalid`; a missing address is
    `webhook_url_required`. The address is stored
    as given (stripped of surrounding space)."""
    if url is None:
        raise WebhookSubscriptionError(
            "webhook_url_required",
            "Give the webhook an address to deliver to.")
    if not isinstance(url, str):
        raise WebhookSubscriptionError(
            "webhook_url_invalid", "That webhook address is not valid.")
    text = url.strip()
    if not text:
        raise WebhookSubscriptionError(
            "webhook_url_required",
            "Give the webhook an address to deliver to.")
    if len(text) > URL_MAX or any(
            ord(c) < 0x21 or ord(c) == 0x7F for c in text):
        raise WebhookSubscriptionError(
            "webhook_url_invalid", "That webhook address is not valid.")
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise WebhookSubscriptionError(
            "webhook_url_invalid",
            "A webhook address must start with http:// or "
            "https:// and name a host.")
    if parsed.username or parsed.password:
        raise WebhookSubscriptionError(
            "webhook_url_invalid",
            "A webhook address must not carry credentials; "
            "the subscription's secret is set separately.")
    if parsed.fragment:
        raise WebhookSubscriptionError(
            "webhook_url_invalid",
            "A webhook address must not carry a fragment.")
    return text


def validate_secret(secret: object) -> str | None:
    """Pure: the secret as handed in, or None for
    no secret. A secret is judged verbatim --
    never stripped, because its spaces are its
    own -- but an empty or all-space secret, one
    carrying controls, a non-string, or one over
    SECRET_MAX is refused `webhook_secret_invalid`.
    Only the digest of what this returns is ever
    stored."""
    if secret is None:
        return None
    if not isinstance(secret, str) or not secret.strip():
        raise WebhookSubscriptionError(
            "webhook_secret_invalid",
            "A webhook secret must be text with real content.")
    if len(secret) > SECRET_MAX or any(
            ord(c) < 0x20 or ord(c) == 0x7F for c in secret):
        raise WebhookSubscriptionError(
            "webhook_secret_invalid",
            "That webhook secret is not valid "
            f"(at most {SECRET_MAX} characters, no controls).")
    return secret


def secret_digest(secret: str) -> str:
    """Pure: the only stored form of a secret --
    its SHA-256 hex digest (the S-006 law)."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def secret_matches(stored_digest: object, candidate: object) -> bool:
    """Pure: whether *candidate* is the secret
    whose digest is *stored_digest*, compared in
    constant time. A subscription with no secret
    (empty digest) matches nothing, and a
    non-string candidate matches nothing."""
    if not isinstance(stored_digest, str) or not stored_digest:
        return False
    if not isinstance(candidate, str) or not candidate:
        return False
    return hmac.compare_digest(
        stored_digest, secret_digest(candidate))


def _filter_items(values: object, kind: str) -> list:
    """The raw filter entries as a list, or a
    refusal: a filter is a set of names, and a
    bare string is one name mistaken for a set."""
    if values is None:
        return []
    if isinstance(values, (str, bytes)) or not isinstance(
            values, Iterable):
        raise WebhookSubscriptionError(
            f"webhook_{kind}_invalid",
            f"Webhook {kind} filters are a set of names.")
    return list(values)


def validate_event_filter(events: object, level: str) -> tuple[str, ...]:
    """Pure: the chosen verbs for *level*, in the
    taxonomy's document order, each judged against
    S-247's ruling: unknown is
    `webhook_event_unknown`, withheld is
    `webhook_event_not_deliverable`, and a
    deliverable verb outside the level's scopes
    is `webhook_event_scope_mismatch`."""
    scopes = _LEVEL_SCOPES[level]
    chosen: set[str] = set()
    for item in _filter_items(events, "events"):
        try:
            spec = get_webhook_event(item)
        except WebhookEventsError:
            raise WebhookSubscriptionError(
                "webhook_event_unknown",
                "No such event-store verb is mapped: "
                f"{item!r}.") from None
        if not spec.deliverable:
            raise WebhookSubscriptionError(
                "webhook_event_not_deliverable",
                f"The event {spec.verb} is never delivered "
                "as a webhook.")
        if spec.scope not in scopes:
            raise WebhookSubscriptionError(
                "webhook_event_scope_mismatch",
                f"The event {spec.verb} is "
                f"{spec.scope} scope; a {level} subscription "
                "cannot carry it.")
        chosen.add(spec.verb)
    return tuple(
        spec.verb for spec in WEBHOOK_EVENTS if spec.verb in chosen)


def validate_category_filter(
        categories: object, level: str) -> tuple[str, ...]:
    """Pure: the chosen categories for *level*, in
    the taxonomy's document order, each judged
    against S-247's ruling: unknown is
    `webhook_category_unknown`; a category none of
    whose verbs this level may carry (the withheld
    families, and `organization` at repository
    level) is `webhook_category_not_deliverable`."""
    scopes = _LEVEL_SCOPES[level]
    chosen: set[str] = set()
    for item in _filter_items(categories, "categories"):
        try:
            verbs = verbs_for_category(item)
        except WebhookEventsError:
            raise WebhookSubscriptionError(
                "webhook_category_unknown",
                f"No such webhook category: {item!r}.") from None
        carryable = [
            verb for verb in verbs
            if get_webhook_event(verb).scope in scopes]
        if not carryable:
            raise WebhookSubscriptionError(
                "webhook_category_not_deliverable",
                f"The category {item} names no event a "
                f"{level} subscription may carry.")
        chosen.add(item)  # type: ignore[arg-type]
    return tuple(
        category for category in dict.fromkeys(
            spec.category for spec in WEBHOOK_EVENTS)
        if category in chosen)


def validate_filter(events: object, categories: object,
                    level: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Pure: a whole filter for *level* -- the
    chosen verbs and the chosen categories, each
    judged by its own validator. A filter naming
    nothing at all is refused
    `webhook_filter_required`."""
    clean_level = validate_level(level)
    clean_events = validate_event_filter(events, clean_level)
    clean_categories = validate_category_filter(categories, clean_level)
    if not clean_events and not clean_categories:
        raise WebhookSubscriptionError(
            "webhook_filter_required",
            "Choose at least one event or category for "
            "the subscription to carry.")
    return clean_events, clean_categories


def expand_filter(events: Iterable[str], categories: Iterable[str],
                  level: str) -> tuple[str, ...]:
    """Pure: the effective verb set of a stored
    filter at *level*: the chosen verbs plus every
    verb of the chosen categories that this level
    may carry, in the taxonomy's document order.
    Withheld verbs are never in an expansion --
    validation already refused the categories
    that name only those."""
    scopes = _LEVEL_SCOPES[level]
    chosen = set(events)
    for category in categories:
        for verb in verbs_for_category(category):
            if get_webhook_event(verb).scope in scopes:
                chosen.add(verb)
    return tuple(
        spec.verb for spec in WEBHOOK_EVENTS
        if spec.verb in chosen and spec.deliverable)


def validate_active(active: object) -> bool:
    """Pure: the stored standing for *active*. A
    standing is a real boolean; anything else is
    refused `webhook_active_invalid` -- a truthy
    string is not a standing anyone chose."""
    if not isinstance(active, bool):
        raise WebhookSubscriptionError(
            "webhook_active_invalid",
            "A webhook subscription is active or inactive; "
            "say which with a true or false.")
    return active


# -- the view ---------------------------------------


@dataclass(frozen=True)
class WebhookSubscription:
    """One subscription as every face shows it:
    its level and parent, its address and host,
    the filter as chosen (verbs and categories),
    its standing, whether a secret is set -- the
    secret itself and its digest are never on a
    view -- and its stamps. The parent's canonical
    key (`owner/name` for a repository, the name
    for an organization) rides beside its display
    name, because routing answers to the key."""
    id: int
    level: str               # repository | organization
    repo_id: int | None
    org_id: int | None
    parent_name: str         # display: owner/name, or the org name
    parent_key: str          # canonical: owner/name lower, or org name_lower
    url: str
    host: str
    events: tuple[str, ...]
    categories: tuple[str, ...]
    active: bool
    has_secret: bool
    created_by: int
    created_at: int
    updated_at: int

    @property
    def level_words(self) -> str:
        return _LEVEL_WORDS.get(self.level, self.level)

    @property
    def state_words(self) -> str:
        return "active" if self.active else "inactive"

    @property
    def secret_words(self) -> str:
        if self.has_secret:
            return "a secret is set (never shown)"
        return "no secret set"

    @property
    def effective_events(self) -> tuple[str, ...]:
        """The verbs this subscription may carry:
        its stored filter, expanded at its level."""
        return expand_filter(self.events, self.categories, self.level)

    @property
    def words(self) -> str:
        """The subscription said in plain words:
        where it lives, where it delivers, what it
        carries, and its standing -- state and
        secret always in words."""
        picked = list(self.events) + [
            f"category:{name}" for name in self.categories]
        return (
            f"{self.level_words} webhook for {self.parent_name} "
            f"delivering to {self.url} ({self.state_words}): "
            f"carries {', '.join(picked)}; {self.secret_words}.")


def decide_match(subscription: WebhookSubscription, verb: object,
                 *, repo_id: int | None = None,
                 org_id: int | None = None,
                 org_key: str | None = None) -> bool:
    """Pure: whether *subscription* receives one
    event named *verb*, whose home the caller
    names by id: `repo_id` for a repository event,
    and for an organization event the owning
    organization as `org_id` (repository-scope
    verbs) or `org_key` (organization-scope verbs,
    whose target is the organization itself). The
    subscription must be active, the verb
    deliverable and in its effective filter, and
    the home its own: a repository subscription
    answers only to its repository's id, and
    never to an organization-scope verb."""
    if not subscription.active:
        return False
    try:
        spec = get_webhook_event(verb)
    except WebhookEventsError:
        return False
    if not spec.deliverable:
        return False
    if verb not in subscription.effective_events:
        return False
    if subscription.level == "repository":
        return (spec.scope == "repository"
                and repo_id is not None
                and subscription.repo_id == repo_id)
    if spec.scope == "organization":
        return (org_key is not None
                and subscription.parent_key == org_key)
    return org_id is not None and subscription.org_id == org_id


# -- the store --------------------------------------


class WebhookSubscriptionStore:
    """Webhook subscriptions over migration 96's
    `webhooks`, judged through
    S-247's taxonomy (filters), S-190's engine
    (repository admin) and S-186's membership
    (organization owners). Every write is
    parent-scoped, commits before its answer,
    and is witnessed with the taxonomy's standing
    verbs -- see the module docstring."""

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

    # -- guards and resolution ----------------------

    @staticmethod
    def _require_user(user: User | None) -> User:
        if user is None:
            raise WebhookSubscriptionError(
                "authentication_required",
                "Sign in to manage webhook subscriptions.")
        return user

    def _resolve_repo(self, user: User, owner: object,
                      repo: object) -> Repository:
        """The repository, under S-190's admin
        gate: missing, or held at no role, is the
        uniform `repo_not_found`; a visible
        repository below admin is `admin_required`,
        said in words."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise WebhookSubscriptionError(
                "repo_not_found", "No such repository.")
        role = self._engine.resolve(user, current).role
        if role is None:
            raise WebhookSubscriptionError(
                "repo_not_found", "No such repository.")
        if not role_covers(role, "admin"):
            raise WebhookSubscriptionError(
                "admin_required",
                "Webhook subscriptions need admin on the "
                "repository.")
        return current

    def _resolve_org(self, user: User,
                     org: object) -> Organization:
        """The organization, under the owners'
        gate: missing is `org_not_found`; an owner
        (S-186) or a site admin may manage its
        subscriptions, anyone else is refused
        `not_org_owner`."""
        current = self._orgs.get_by_name(org)
        if current is None:
            raise WebhookSubscriptionError(
                "org_not_found", "No such organization.")
        if user.is_admin:
            return current
        if self._members.role_for(user.id, current.id) != "owner":
            raise WebhookSubscriptionError(
                "not_org_owner",
                "Webhook subscriptions need an owner of the "
                "organization.")
        return current

    def _row(self, level: str, parent_id: int,
             subscription_id: object) -> sqlite3.Row:
        """One row, scoped by its parent in the
        query itself: an id of the wrong shape, a
        missing id, or an id living under another
        parent is the one `subscription_not_found`."""
        if isinstance(subscription_id, bool) or not isinstance(
                subscription_id, int):
            raise WebhookSubscriptionError(
                "subscription_not_found",
                "No such webhook subscription.")
        column = "repo_id" if level == "repository" else "org_id"
        row = self._conn.execute(
            f"SELECT * FROM webhooks"
            f" WHERE id = ? AND level = ? AND {column} = ?",
            (subscription_id, level, parent_id)).fetchone()
        if row is None:
            raise WebhookSubscriptionError(
                "subscription_not_found",
                "No such webhook subscription.")
        return row

    def _view(self, row: sqlite3.Row) -> WebhookSubscription:
        try:
            events = tuple(json.loads(row["events_json"]))
        except (ValueError, TypeError):
            events = ()
        try:
            categories = tuple(json.loads(row["categories_json"]))
        except (ValueError, TypeError):
            categories = ()
        return WebhookSubscription(
            id=int(row["id"]), level=row["level"],
            repo_id=row["repo_id"], org_id=row["org_id"],
            parent_name=row["parent_name"],
            parent_key=row["parent_key"],
            url=row["url"], host=row["host"],
            events=tuple(str(v) for v in events),
            categories=tuple(str(c) for c in categories),
            active=bool(row["active"]),
            has_secret=bool(row["secret_digest"]),
            created_by=int(row["created_by"]),
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]))

    def _rows(self, level: str, parent_id: int) -> list[sqlite3.Row]:
        column = "repo_id" if level == "repository" else "org_id"
        return self._conn.execute(
            f"SELECT * FROM webhooks"
            f" WHERE level = ? AND {column} = ? ORDER BY id",
            (level, parent_id)).fetchall()

    # -- witnessing ---------------------------------

    def _witness(self, user: User, level: str, action: str,
                 parent_name: str, parent_key: str, host: str,
                 source_ip: str | None) -> None:
        """One successful change, witnessed with
        the standing verbs: repository changes
        under their repo.* verbs (updates under
        `repo.settings.change`, the key named),
        organization changes under
        `auth.organization.update` with `fields`
        `webhooks`. The detail carries the host
        only -- never the secret, never the full
        address."""
        if self._audit is None:
            return
        if level == "repository":
            verb = {
                "add": "repo.webhook.add",
                "remove": "repo.webhook.remove",
                "update": "repo.settings.change",
            }[action]
            detail = ({"host": host} if action != "update"
                      else {"key": "webhook.update", "host": host})
            self._audit.append(
                actor_kind="user", actor_id=user.id, action=verb,
                target_kind="repo", target_id=parent_name,
                outcome="success", source_ip=source_ip,
                detail=detail)
        else:
            self._audit.append(
                actor_kind="user", actor_id=user.id,
                action="auth.organization.update",
                target_kind="organization", target_id=parent_key,
                outcome="success", source_ip=source_ip,
                detail={"fields": "webhooks", "action": action,
                        "host": host})

    # -- creation -----------------------------------

    def _create(self, user: User | None, level: str,
                parent_id: int, parent_name: str, parent_key: str,
                url: object, events: object, categories: object,
                secret: object, active: object,
                source_ip: str | None) -> WebhookSubscription:
        actor = self._require_user(user)
        clean_url = validate_webhook_url(url)
        clean_events, clean_categories = validate_filter(
            events, categories, level)
        clean_secret = validate_secret(secret)
        clean_active = validate_active(active)
        host = urlparse(clean_url).hostname or ""
        digest = secret_digest(clean_secret) if clean_secret else ""
        now = int(self._now())
        with self._conn:  # commits before the answer
            cur = self._conn.execute(
                "INSERT INTO webhooks"
                " (level, repo_id, org_id, parent_name, parent_key,"
                " url, host, events_json, categories_json, active,"
                " secret_digest, created_by, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (level,
                 parent_id if level == "repository" else None,
                 parent_id if level == "organization" else None,
                 parent_name, parent_key, clean_url, host,
                 json.dumps(list(clean_events)),
                 json.dumps(list(clean_categories)),
                 1 if clean_active else 0, digest, actor.id,
                 now, now))
            row_id = int(cur.lastrowid)
        row = self._conn.execute(
            "SELECT * FROM webhooks WHERE id = ?",
            (row_id,)).fetchone()
        view = self._view(row)
        self._witness(actor, level, "add", parent_name, parent_key,
                      host, source_ip)
        return view

    def create_repository_subscription(
            self, user: User | None, owner: object, repo: object,
            url: object, events: object = (),
            categories: object = (), secret: object = None,
            active: object = True,
            source_ip: str | None = None) -> WebhookSubscription:
        """Create one repository subscription: the
        caller holds admin in the repository
        (S-190); the address, the filter and the
        secret are judged at the door, and the
        secret is stored only as its digest."""
        actor = self._require_user(user)
        current = self._resolve_repo(actor, owner, repo)
        return self._create(
            actor, "repository", current.id, current.full_name,
            current.full_name.lower(), url, events, categories,
            secret, active, source_ip)

    def create_organization_subscription(
            self, user: User | None, org: object,
            url: object, events: object = (),
            categories: object = (), secret: object = None,
            active: object = True,
            source_ip: str | None = None) -> WebhookSubscription:
        """Create one organization subscription:
        the caller is an owner of the organization
        (or a site admin); organization-scope
        events may be chosen here, and here only."""
        actor = self._require_user(user)
        current = self._resolve_org(actor, org)
        return self._create(
            actor, "organization", current.id, current.name,
            current.name_lower, url, events, categories,
            secret, active, source_ip)

    # -- reads --------------------------------------

    def get_repository_subscription(
            self, user: User | None, owner: object, repo: object,
            subscription_id: object) -> WebhookSubscription:
        actor = self._require_user(user)
        current = self._resolve_repo(actor, owner, repo)
        return self._view(
            self._row("repository", current.id, subscription_id))

    def list_repository_subscriptions(
            self, user: User | None, owner: object,
            repo: object) -> tuple[WebhookSubscription, ...]:
        actor = self._require_user(user)
        current = self._resolve_repo(actor, owner, repo)
        return tuple(
            self._view(row)
            for row in self._rows("repository", current.id))

    def get_organization_subscription(
            self, user: User | None, org: object,
            subscription_id: object) -> WebhookSubscription:
        actor = self._require_user(user)
        current = self._resolve_org(actor, org)
        return self._view(
            self._row("organization", current.id, subscription_id))

    def list_organization_subscriptions(
            self, user: User | None,
            org: object) -> tuple[WebhookSubscription, ...]:
        actor = self._require_user(user)
        current = self._resolve_org(actor, org)
        return tuple(
            self._view(row)
            for row in self._rows("organization", current.id))

    # -- updates ------------------------------------

    def _update(self, user: User, level: str, parent_id: int,
                parent_name: str, parent_key: str,
                subscription_id: object, url: object,
                events: object, categories: object,
                active: object,
                source_ip: str | None) -> WebhookSubscription:
        """The one update road: a passed address,
        filter or standing is re-judged at the
        door (the secret has no update road -- see
        the module docstring); an update that
        changes nothing is a quiet no-op, storing
        nothing and witnessing nothing."""
        row = self._row(level, parent_id, subscription_id)
        current = self._view(row)
        clean_url = (current.url if url is None
                     else validate_webhook_url(url))
        if events is None and categories is None:
            clean_events, clean_categories = (
                current.events, current.categories)
        else:
            clean_events, clean_categories = validate_filter(
                events if events is not None else (),
                categories if categories is not None else (),
                level)
        clean_active = (current.active if active is None
                        else validate_active(active))
        if (clean_url == current.url
                and clean_events == current.events
                and clean_categories == current.categories
                and clean_active == current.active):
            return current
        host = urlparse(clean_url).hostname or ""
        now = int(self._now())
        with self._conn:  # commits before the answer
            self._conn.execute(
                "UPDATE webhooks"
                " SET url = ?, host = ?, events_json = ?,"
                " categories_json = ?, active = ?, updated_at = ?"
                " WHERE id = ?",
                (clean_url, host, json.dumps(list(clean_events)),
                 json.dumps(list(clean_categories)),
                 1 if clean_active else 0, now, current.id))
        view = self._view(
            self._row(level, parent_id, subscription_id))
        self._witness(user, level, "update", parent_name,
                      parent_key, host, source_ip)
        return view

    def update_repository_subscription(
            self, user: User | None, owner: object, repo: object,
            subscription_id: object, *, url: object = None,
            events: object = None, categories: object = None,
            active: object = None,
            source_ip: str | None = None) -> WebhookSubscription:
        actor = self._require_user(user)
        current = self._resolve_repo(actor, owner, repo)
        return self._update(
            actor, "repository", current.id, current.full_name,
            current.full_name.lower(), subscription_id, url,
            events, categories, active, source_ip)

    def update_organization_subscription(
            self, user: User | None, org: object,
            subscription_id: object, *, url: object = None,
            events: object = None, categories: object = None,
            active: object = None,
            source_ip: str | None = None) -> WebhookSubscription:
        actor = self._require_user(user)
        current = self._resolve_org(actor, org)
        return self._update(
            actor, "organization", current.id, current.name,
            current.name_lower, subscription_id, url,
            events, categories, active, source_ip)

    def set_repository_subscription_active(
            self, user: User | None, owner: object, repo: object,
            subscription_id: object, active: object,
            source_ip: str | None = None) -> WebhookSubscription:
        """Switch one repository subscription's
        standing; re-setting the held standing is
        a quiet no-op."""
        return self.update_repository_subscription(
            user, owner, repo, subscription_id, active=active,
            source_ip=source_ip)

    def set_organization_subscription_active(
            self, user: User | None, org: object,
            subscription_id: object, active: object,
            source_ip: str | None = None) -> WebhookSubscription:
        """Switch one organization subscription's
        standing; re-setting the held standing is
        a quiet no-op."""
        return self.update_organization_subscription(
            user, org, subscription_id, active=active,
            source_ip=source_ip)

    # -- deletion -----------------------------------

    def _delete(self, user: User, level: str, parent_id: int,
                parent_name: str, parent_key: str,
                subscription_id: object,
                source_ip: str | None) -> WebhookSubscription:
        row = self._row(level, parent_id, subscription_id)
        view = self._view(row)
        with self._conn:  # commits before the answer
            self._conn.execute(
                "DELETE FROM webhooks WHERE id = ?",
                (view.id,))
        self._witness(user, level, "remove", parent_name,
                      parent_key, view.host, source_ip)
        return view

    def delete_repository_subscription(
            self, user: User | None, owner: object, repo: object,
            subscription_id: object,
            source_ip: str | None = None) -> WebhookSubscription:
        """Delete one repository subscription and
        answer its last standing; the deletion is
        witnessed `repo.webhook.remove`."""
        actor = self._require_user(user)
        current = self._resolve_repo(actor, owner, repo)
        return self._delete(
            actor, "repository", current.id, current.full_name,
            current.full_name.lower(), subscription_id, source_ip)

    def delete_organization_subscription(
            self, user: User | None, org: object,
            subscription_id: object,
            source_ip: str | None = None) -> WebhookSubscription:
        """Delete one organization subscription and
        answer its last standing."""
        actor = self._require_user(user)
        current = self._resolve_org(actor, org)
        return self._delete(
            actor, "organization", current.id, current.name,
            current.name_lower, subscription_id, source_ip)

    # -- the secret's one question -------------------

    def _verify_secret(self, user: User, level: str,
                       parent_id: int, subscription_id: object,
                       candidate: object) -> bool:
        row = self._row(level, parent_id, subscription_id)
        return secret_matches(row["secret_digest"], candidate)

    def verify_repository_secret(
            self, user: User | None, owner: object, repo: object,
            subscription_id: object, candidate: object) -> bool:
        """Whether *candidate* is the secret of one
        repository subscription. The secret itself
        is never answered -- only this yes or no,
        under the same admin gate as every face."""
        actor = self._require_user(user)
        current = self._resolve_repo(actor, owner, repo)
        return self._verify_secret(
            actor, "repository", current.id, subscription_id,
            candidate)

    def verify_organization_secret(
            self, user: User | None, org: object,
            subscription_id: object, candidate: object) -> bool:
        """Whether *candidate* is the secret of one
        organization subscription (owners' gate)."""
        actor = self._require_user(user)
        current = self._resolve_org(actor, org)
        return self._verify_secret(
            actor, "organization", current.id, subscription_id,
            candidate)

    # -- delivery routing (S-250's seam) -------------

    def subscriptions_for_event(
            self, event: CanonicalEvent) -> tuple[WebhookSubscription, ...]:
        """The standing subscriptions that receive
        one canonical event, in creation order:
        the event's repository's own hooks, and the
        hooks of the organization that owns that
        repository; for an organization-scope
        event, the hooks of the organization it
        targets. Judged subscription by
        subscription through the pure `decide_match`;
        a withheld or unknown verb matches nothing."""
        try:
            spec = get_webhook_event(event.verb)
        except WebhookEventsError:
            return ()
        if not spec.deliverable:
            return ()
        repo = None
        if event.repository:
            parts = event.repository.split("/", 1)
            if len(parts) == 2:
                repo = self._repos.get_repository(parts[0], parts[1])
        org = (self._orgs.get_by_name(repo.owner)
               if repo is not None else None)
        org_key = (event.target_id.lower()
                   if spec.scope == "organization" and event.target_id
                   else None)
        found: list[WebhookSubscription] = []
        rows = self._conn.execute(
            "SELECT * FROM webhooks"
            " WHERE active = 1 ORDER BY id").fetchall()
        for row in rows:
            view = self._view(row)
            if decide_match(
                    view, event.verb,
                    repo_id=repo.id if repo is not None else None,
                    org_id=org.id if org is not None else None,
                    org_key=org_key):
                found.append(view)
        return tuple(found)


# -- renderers --------------------------------------


def render_webhook_subscription(sub: WebhookSubscription) -> str:
    """One subscription, rendered: its parent, its
    address, its filter as chosen, its standing
    and its secret's standing -- every state in
    words, every value through S-010, and the
    secret itself never present to be escaped."""
    picked = list(sub.events) + [
        f"category:{name}" for name in sub.categories]
    return (
        "<li>"
        f"<strong>{escape_html_text(sub.parent_name)}</strong> "
        f"({escape_html_text(sub.level_words)}): "
        f"{escape_html_text(sub.url)} -- "
        f"{escape_html_text(sub.state_words)}; carries "
        f"{escape_html_text(', '.join(picked))}; "
        f"{escape_html_text(sub.secret_words)}."
        "</li>")


def render_webhook_subscriptions(
        title: str,
        subscriptions: Iterable[WebhookSubscription]) -> str:
    """One parent's subscriptions, rendered as a
    list under its title; an empty list teaches
    what a subscription is instead of showing a
    blank."""
    subs = list(subscriptions)
    parts = [f"<h2>{escape_html_text(title)}</h2>"]
    if not subs:
        parts.append(
            "<p>No webhook subscriptions yet. A "
            "subscription delivers this scope's events "
            "to one address, under the events or "
            "categories it names.</p>")
        return "\n".join(parts)
    parts.append("<ul>")
    for sub in subs:
        parts.append(render_webhook_subscription(sub))
    parts.append("</ul>")
    return "\n".join(parts)
