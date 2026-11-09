"""Events API (S-231).

The feed as a Part XII resource with the same
permission filtering: S-229's three activity feeds
(user, repository, instance public activity) and
S-221's single canonical event, answered as
JSON-safe data a script can consume, instead of as
pages a person reads. S-237 will ratify Samverk's
`/api/v1` contract and S-245 will land the search
face of it; this slice lands the events contract
itself, in the shape S-216 set for API faces.

- **The same filtering, literally.** `EventsAPI`
  owns no visibility law of its own: it builds
  S-229's `ActivityFeedStore` and judges every
  event through that store's own per-event filter
  (S-190's `PermissionEngine` over S-209's law),
  gathers through its sync-first reader, takes its
  scope sentences from its `feed_scope`, and reads
  a single event through S-221's `EventStore`
  under that store's own visibility law. The API
  cannot drift from the feeds it stands behind --
  a repository event a reader cannot read
  contributes no row, no target, and no count here,
  exactly as on the page, and the battery proves
  the agreement feed by feed: for the same reader
  and the same bound, the API's event ids are the
  feed's event ids, in the same order.
- **A machine shape, honestly bounded.** Every
  feed payload is plain JSON-safe data (dicts,
  lists, strings, numbers, booleans, nulls -- it
  round-trips through `json` unchanged): the feed's
  kind, its subject, its honest scope sentence,
  the filtered `total` tallied before the cap, the
  `returned` count the cap allowed, a `complete`
  flag that says plainly whether the cap truncated
  the feed, the `limit` that was honoured, and the
  events, newest first. One event is S-221's
  payload shape (`event_payload`: delivery id,
  verb, action, actor, target, repository, number,
  refs, detail, occurred_at) carried unchanged on
  its shared keys, extended with the resource's own
  addressing facts a script needs to walk the API
  (the event `id`, `actor_id`, `actor_kind`,
  `target_kind`, and the witnessed `outcome`).
  The capped shape is joined by a paged one:
  since S-239 the same three feeds answer as
  `*_page` calls through that slice's cursor
  engine (filtering first, paging second, the
  page size inside S-239's own bounds), and
  the single event answers conditionally
  through `get_event_conditional`. A caller
  who needs more than the cap (default 100,
  at most 500, the feeds' own bounds) is
  still told so by `complete` on the capped
  shape, never silently short-changed.
- **Refusals a script can branch on.** A refused
  call raises `EventsAPIError` carrying a
  machine-branchable reason: the stores' own
  reasons verbatim (`no_such_user` for an unknown
  actor, the uniform `repo_not_found` for a missing
  or unreadable repository, `event_not_found` for
  a missing or invisible event), `limit_invalid`
  for a limit that is not an integer inside the
  feeds' bounds, and `filter_invalid` for a verb
  filter that is not a non-empty string.
  `error_to_dict` renders any refusal in
  S-240's one problem format (type, title,
  status, detail, error id) through
  samverk/error_shape.py -- the shape every
  endpoint and the web UI's refusals now use.
- **Stateless, like an API should be.** An API
  read records nothing and audits nothing: the
  only write a read can cause is S-221's own
  sync-first materialisation, which is the feeds'
  standing never-stale law, not a record of the
  read. No migration, no audit event of its own:
  schema stays 92 and 127 events stand -- 31 auth /
  83 repo / 13 admin.
- **Anonymous callers read as the web's
  anonymous.** A missing viewer is the feeds' own
  anonymous: public facts only, through the same
  permission gate -- never a back door around it.
  The public feed stays public for everyone: its
  viewer is accepted for a uniform call shape and
  then deliberately not consulted, exactly as
  S-229 rules, so a site administrator receives
  the same public-only payload as a stranger.
"""

from __future__ import annotations

import json
import sqlite3

from .accounts import AccountStore, User
from .activity_feeds import (
    ActivityFeedError, ActivityFeedStore, feed_scope, in_public_feed)
from .event_store import (
    CanonicalEvent, EventStore, EventStoreError, event_payload)
from .api_pagination import (
    DEFAULT_PAGE_SIZE, ApiPaginationError,
    conditional_response, paginate)
from .error_shape import problem_from_error, problem_to_dict
from .repositories import RepositoryStore

__all__ = [
    "DEFAULT_LIMIT", "MAX_LIMIT", "EventsAPI", "EventsAPIError",
    "error_to_dict", "event_to_dict", "feed_to_dict",
    "feed_page_to_dict", "feed_to_json",
]

# The feeds' own bounds (S-229 clamps to the same
# window): an API limit lives inside them or is
# refused -- a contract does not silently clamp a
# caller's stated bound the way a page may.
DEFAULT_LIMIT = 100
MAX_LIMIT = 500


class EventsAPIError(ValueError):
    """One refused API call: a machine-branchable
    reason with its human detail."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def error_to_dict(exc: EventsAPIError) -> dict:
    """One refusal as data, in S-240's one problem
    format (samverk/error_shape.py): type, title,
    status, detail, error_id -- nothing else."""
    return problem_to_dict(problem_from_error(exc))


# ------------------------------------------------------------------
# Serialisers -- one event, one feed, as data
# ------------------------------------------------------------------

def event_to_dict(event: CanonicalEvent) -> dict:
    """One canonical event as JSON-safe data:
    S-221's payload shape carried unchanged on its
    shared keys (delivery id, verb, action, actor,
    target, repository, number, refs, detail,
    occurred_at), extended with the addressing
    facts of the resource itself -- the event id a
    script uses to fetch this event alone, who
    acted (id and kind), what kind of target was
    acted on, and the witnessed outcome. Data
    carries the raw values -- S-010 escaping is the
    page's law, not the wire's."""
    payload = event_payload(event)
    return {
        "id": event.id,
        "delivery_id": payload["delivery_id"],
        "event": payload["event"],
        "action": payload["action"],
        "actor": payload["actor"],
        "actor_id": event.actor_id,
        "actor_kind": event.actor_kind,
        "target": payload["target"],
        "target_kind": event.target_kind,
        "repository": payload["repository"],
        "number": payload["number"],
        "refs": payload["refs"],
        "detail": payload["detail"],
        "outcome": event.outcome,
        "occurred_at": payload["occurred_at"],
    }


def feed_to_dict(kind: str, subject: str, scope: str,
                 events: list[CanonicalEvent], *,
                 limit: int) -> dict:
    """One feed as data, from its FULL filtered
    event list (newest first, permission already
    judged): the kind, the subject, the honest
    scope sentence, the filtered total tallied
    before the cap, how many events the cap
    returned, whether the feed is complete under
    that cap, the limit honoured, and the events
    themselves. The total counts only what this
    reader may see -- filtered rows are counted
    nowhere."""
    page = events[:limit]
    return {
        "kind": kind,
        "subject": subject,
        "scope": scope,
        "total": len(events),
        "returned": len(page),
        "complete": len(events) <= len(page),
        "limit": limit,
        "events": [event_to_dict(event) for event in page],
    }


def feed_page_to_dict(kind: str, subject: str, scope: str,
                      page) -> dict:
    """One feed page as data, from S-239's Page
    over the feed's FULL filtered event list: the
    capped envelope's own facts (kind, subject,
    scope, the filtered total tallied before
    paging, whether the crawl is complete on this
    page) joined by the page's size, its walking
    facts and cursors, and its events. The total
    counts only what this reader may see --
    paging happens after filtering, never
    before."""
    return {
        "kind": kind,
        "subject": subject,
        "scope": scope,
        "total": page.total,
        "returned": page.returned,
        "complete": page.complete,
        "per_page": page.per_page,
        "has_next": page.has_next,
        "has_previous": page.has_previous,
        "next_cursor": page.next_cursor,
        "previous_cursor": page.previous_cursor,
        "events": [event_to_dict(event) for event in page.items],
    }


def feed_to_json(payload: dict) -> str:
    """One feed payload as a JSON text: keys sorted
    so the same feed renders byte-identically
    twice."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


# ------------------------------------------------------------------
# The API face
# ------------------------------------------------------------------

class EventsAPI:
    """The S-231 executor: S-229's feeds and
    S-221's single event, answered in data. It owns
    no store and no filter of its own -- the feed
    store and the event store are built once here
    and every call delegates to them, so permission
    filtering is identical by construction, not by
    copy."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        events: EventStore | None = None,
        feeds: ActivityFeedStore | None = None,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._events = events or EventStore(
            conn, repositories, accounts)
        self._feeds = feeds or ActivityFeedStore(
            conn, repositories, accounts, events=self._events)

    # -- the contract's own refusals -------------------
    @staticmethod
    def _check_limit(limit: object) -> int:
        if (isinstance(limit, bool) or not isinstance(limit, int)
                or limit < 1 or limit > MAX_LIMIT):
            raise EventsAPIError(
                "limit_invalid",
                f"limit must be an integer between 1 and {MAX_LIMIT}.")
        return limit

    @staticmethod
    def _check_verb_prefix(verb_prefix: object) -> str | None:
        if verb_prefix is None:
            return None
        if not isinstance(verb_prefix, str) or not verb_prefix:
            raise EventsAPIError(
                "filter_invalid",
                "verb_prefix must be a non-empty string.")
        return verb_prefix

    @staticmethod
    def _filtered(events: list[CanonicalEvent],
                  verb_prefix: str | None) -> list[CanonicalEvent]:
        """The verb filter, applied AFTER permission:
        a filter can only narrow what this reader may
        already see, never widen it."""
        if verb_prefix is None:
            return events
        return [e for e in events if e.verb.startswith(verb_prefix)]

    # -- the three feeds --------------------------------
    def user_events(self, viewer: User | None, actor: object,
                    *, limit: int = DEFAULT_LIMIT,
                    verb_prefix: str | None = None) -> dict:
        """One person's feed as data: their actions,
        newest first, filtered event by event to what
        *viewer* may see (S-229's own filter). The
        total counts only what is shown to this
        viewer. An unknown actor is `no_such_user`,
        the feed store's reason verbatim."""
        limit = self._check_limit(limit)
        verb_prefix = self._check_verb_prefix(verb_prefix)
        try:
            subject = self._feeds._resolve_actor(actor)
        except ActivityFeedError as exc:
            raise EventsAPIError(exc.reason, str(exc)) from None
        shown = [e for e in self._feeds._all_events()
                 if e.actor_id == subject.id
                 and self._feeds._visible(viewer, e)]
        return feed_to_dict(
            "user", subject.username,
            feed_scope("user", subject.username),
            self._filtered(shown, verb_prefix), limit=limit)

    def repo_events(self, viewer: User | None, owner: object,
                    repo: object, *, limit: int = DEFAULT_LIMIT,
                    verb_prefix: str | None = None) -> dict:
        """One repository's feed as data: its actions,
        newest first. Read access is the gate, judged
        by S-190's engine exactly as S-229 judges it:
        a reader who cannot read the repository --
        and anyone asking after a missing one -- gets
        the uniform `repo_not_found`, so the API never
        confirms an unreadable repository exists."""
        limit = self._check_limit(limit)
        verb_prefix = self._check_verb_prefix(verb_prefix)
        current = self._repos.get_repository(owner, repo)
        if current is None or not self._feeds._engine.can(
                viewer, current, "read"):
            raise EventsAPIError(
                "repo_not_found", "No such repository.")
        shown = [e for e in self._feeds._all_events()
                 if e.repository == current.full_name]
        return feed_to_dict(
            "repository", current.full_name,
            feed_scope("repository", current.full_name),
            self._filtered(shown, verb_prefix), limit=limit)

    def public_events(self, viewer: User | None = None,
                      *, limit: int = DEFAULT_LIMIT,
                      verb_prefix: str | None = None) -> dict:
        """The instance's public-activity feed as
        data: actions in public repositories only,
        newest first. *viewer* is accepted so callers
        pass their reader uniformly -- and is then
        deliberately not consulted: a site
        administrator, the actor themself, and an
        anonymous visitor all receive the same
        public-only payload (S-229's law)."""
        limit = self._check_limit(limit)
        verb_prefix = self._check_verb_prefix(verb_prefix)
        del viewer  # public means public, for everyone
        shown = [e for e in self._feeds._all_events()
                 if in_public_feed(self._feeds._repo_for(e))]
        return feed_to_dict(
            "public", "public", feed_scope("public", "public"),
            self._filtered(shown, verb_prefix), limit=limit)

    # -- the three feeds, paged (S-239) -----------------
    def _paginate_feed(self, kind, subject, scope, shown, *,
                       per_page, cursor, context) -> dict:
        """S-239's engine over one feed's FULL
        filtered list, keyed by event id in the
        feed's own newest-first order: filtering
        has already happened in the caller, so a
        page can no more leak than the capped feed
        could. The engine's refusals ride this
        face's own error, reasons verbatim."""
        try:
            page = paginate(
                shown, key=lambda event: event.id,
                per_page=per_page, cursor=cursor,
                context=context)
        except ApiPaginationError as exc:
            raise EventsAPIError(exc.reason, str(exc)) from None
        return feed_page_to_dict(kind, subject, scope, page)

    def user_events_page(self, viewer: User | None, actor: object,
                         *, per_page: int = DEFAULT_PAGE_SIZE,
                         cursor: str | None = None,
                         verb_prefix: str | None = None) -> dict:
        """One page of a person's feed (S-239):
        S-231's user feed crawled by cursor -- the
        same filtering, the same order, a bounded
        page."""
        verb_prefix = self._check_verb_prefix(verb_prefix)
        try:
            subject = self._feeds._resolve_actor(actor)
        except ActivityFeedError as exc:
            raise EventsAPIError(exc.reason, str(exc)) from None
        shown = [e for e in self._feeds._all_events()
                 if e.actor_id == subject.id
                 and self._feeds._visible(viewer, e)]
        return self._paginate_feed(
            "user", subject.username,
            feed_scope("user", subject.username),
            self._filtered(shown, verb_prefix),
            per_page=per_page, cursor=cursor,
            context=f"user:{subject.username}")

    def repo_events_page(self, viewer: User | None, owner: object,
                         repo: object, *,
                         per_page: int = DEFAULT_PAGE_SIZE,
                         cursor: str | None = None,
                         verb_prefix: str | None = None) -> dict:
        """One page of a repository's feed (S-239):
        the crawl of a large repository -- read
        access judged exactly as the capped feed
        judges it, the uniform `repo_not_found`
        included, before any page is cut."""
        verb_prefix = self._check_verb_prefix(verb_prefix)
        current = self._repos.get_repository(owner, repo)
        if current is None or not self._feeds._engine.can(
                viewer, current, "read"):
            raise EventsAPIError(
                "repo_not_found", "No such repository.")
        shown = [e for e in self._feeds._all_events()
                 if e.repository == current.full_name]
        return self._paginate_feed(
            "repository", current.full_name,
            feed_scope("repository", current.full_name),
            self._filtered(shown, verb_prefix),
            per_page=per_page, cursor=cursor,
            context=f"repository:{current.full_name}")

    def public_events_page(self, viewer: User | None = None, *,
                           per_page: int = DEFAULT_PAGE_SIZE,
                           cursor: str | None = None,
                           verb_prefix: str | None = None) -> dict:
        """One page of the instance's public feed
        (S-239): public repositories only, for
        every viewer alike -- *viewer* is accepted
        for the uniform call shape and, as on the
        capped face, deliberately not consulted."""
        verb_prefix = self._check_verb_prefix(verb_prefix)
        del viewer  # public means public, for everyone
        shown = [e for e in self._feeds._all_events()
                 if in_public_feed(self._feeds._repo_for(e))]
        return self._paginate_feed(
            "public", "public", feed_scope("public", "public"),
            self._filtered(shown, verb_prefix),
            per_page=per_page, cursor=cursor,
            context="public")

    # -- the single event --------------------------------
    def get_event(self, viewer: User | None,
                  event_id: object) -> dict:
        """One event by id, as data, under S-221's
        own visibility law: an event this viewer may
        not see is `event_not_found`, exactly like
        one that does not exist -- the store's reason
        verbatim."""
        try:
            event = self._events.get_event(viewer, event_id)
        except EventStoreError as exc:
            raise EventsAPIError(exc.reason, str(exc)) from None
        return event_to_dict(event)

    def get_event_conditional(self, viewer: User | None,
                              event_id: object, *,
                              if_none_match: object = None):
        """One event, conditionally (S-239): the
        event as data under S-221's visibility law,
        answered through S-239's conditional
        response -- 200 with the payload and its
        ETag, or 304 with no payload when the
        caller's `If-None-Match` already holds
        these exact bytes."""
        return conditional_response(
            self.get_event(viewer, event_id),
            if_none_match)

    # -- the wire forms -----------------------------------
    def user_events_json(self, viewer: User | None, actor: object,
                         **kwargs) -> str:
        """`user_events`, rendered as a JSON text
        with sorted keys -- the wire form."""
        return feed_to_json(self.user_events(viewer, actor, **kwargs))

    def repo_events_json(self, viewer: User | None, owner: object,
                         repo: object, **kwargs) -> str:
        """`repo_events`, rendered as a JSON text
        with sorted keys -- the wire form."""
        return feed_to_json(
            self.repo_events(viewer, owner, repo, **kwargs))

    def public_events_json(self, viewer: User | None = None,
                           **kwargs) -> str:
        """`public_events`, rendered as a JSON text
        with sorted keys -- the wire form."""
        return feed_to_json(self.public_events(viewer, **kwargs))

    def get_event_json(self, viewer: User | None,
                       event_id: object) -> str:
        """`get_event`, rendered as a JSON text with
        sorted keys -- the wire form."""
        return json.dumps(
            self.get_event(viewer, event_id),
            ensure_ascii=False, sort_keys=True)
