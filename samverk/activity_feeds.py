"""Activity feeds (S-229).

Part XI's three feed faces over S-221's canonical
event store: a person's feed (their own actions), a
repository's feed (that repository's actions), and
the instance's public-activity feed. Before this
slice the events existed -- S-221 materialised one
canonical record (actor, verb, target, refs,
timestamp) for every mutation in Parts III-X -- but
no surface gathered them as feeds a person reads.
This module is that gathering, under five laws:

- **A read model over the witness, never a second
  log.** Every feed is read from migration 85's
  `events` table, materialised through S-221's own
  `EventStore` (each read syncs first, so an answer
  is never stale). This slice writes nothing, audits
  nothing, and claims no migration and no taxonomy
  event: schema 92 stands, and 127 events stand
  (31 auth, 83 repo, 13 admin).
- **Permission-filtered by construction (S-209's
  law, judged by S-190's one function).** A feed
  never reveals an action on a repository the reader
  cannot read -- not the row, not its target, not
  its count. Repository visibility is resolved
  through `PermissionEngine` (S-190), the one
  function that also speaks S-197's internal
  visibility, team grants, and collaborator grants,
  so a feed's answer can never drift from the
  repository's own door. A repository event whose
  repository no longer resolves fails closed.
  Non-repository events follow S-221's standing law:
  organisation events name public directory facts
  and are visible to everyone; every other
  non-repository event is visible only to its actor
  and to site administrators.
- **The public feed is public repositories only --
  for everyone.** `public_feed` carries an event
  exactly when its repository's visibility is
  `public`. Private and internal repositories
  contribute no row, no target, and no count, and
  the reader's standing changes nothing: a site
  administrator reading the public feed sees the
  same public-only feed as an anonymous visitor.
  The page says so in plain words (the scope
  sentence below), so the limit is labelled, never
  silent. Non-repository events never appear here.
- **One order, said in words.** Every feed is
  newest first -- reverse chronological, the order
  S-221's store reads -- and each page states the
  order and its count in text, never by colour or
  position alone. A feed's count counts only what
  the feed shows this reader; there is no second,
  larger number anywhere on the page to leak what
  was filtered away.
- **Honest empty states.** An empty feed renders a
  sentence that says the feed is empty and what
  would appear in it -- for the public feed, that
  only public-repository actions ever appear. All
  user-controlled text escapes through S-010's
  seam.
"""

from __future__ import annotations

import json
import sqlite3

from dataclasses import dataclass

from .accounts import AccountStore, User
from .escaping import escape_html_text
from .event_store import CanonicalEvent, EventStore
from .permission_engine import PermissionEngine
from .repositories import Repository, RepositoryStore

__all__ = [
    "FEED_KINDS", "PUBLIC_FEED_SCOPE", "ActivityFeed",
    "ActivityFeedError", "ActivityFeedStore",
    "empty_words", "feed_scope", "in_public_feed",
    "render_feed_entry", "render_feed_page",
    "render_public_feed_page", "render_repo_feed_page",
    "render_user_feed_page",
]

# The three feeds, in the order the roadmap names
# them: user, repository, instance public activity.
FEED_KINDS = ("user", "repository", "public")

# The public feed's scope, said once, in words, and
# printed on its page: the limit is a labelled law,
# not a silent filter.
PUBLIC_FEED_SCOPE = (
    "This feed carries actions in public repositories "
    "only. Actions in private and internal repositories "
    "never appear here, not even for site administrators "
    "reading this feed.")


class ActivityFeedError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def in_public_feed(repo: Repository | None) -> bool:
    """Pure: an event belongs to the instance's
    public-activity feed exactly when it names a
    repository whose visibility is `public`. A
    missing repository, a private one, and an
    internal one are all refused -- the public feed
    is judged by the repository's visibility alone,
    never by who is asking."""
    return repo is not None and repo.visibility == "public"


def feed_scope(kind: str, subject: str) -> str:
    """The one honest scope sentence a feed's page
    carries, judged by its kind: what this feed
    shows, and what it never shows."""
    if kind == "public":
        return PUBLIC_FEED_SCOPE
    if kind == "repository":
        return (
            f"Actions in {subject}, newest first. This "
            "feed is shown only to people who can read "
            "the repository.")
    return (
        f"Actions by {subject} that you may see, newest "
        "first. Actions in repositories you cannot read "
        "are never shown here, and the count counts only "
        "what is shown.")


def empty_words(kind: str, subject: str) -> str:
    """The honest empty state for one feed, in
    words: the feed is empty, and what would appear
    in it."""
    if kind == "public":
        return (
            "No public activity yet. Only actions in "
            "public repositories appear here; actions in "
            "private and internal repositories never do.")
    if kind == "repository":
        return (
            f"No activity in {subject} yet. Actions in "
            "this repository will appear here, newest "
            "first.")
    return (
        f"No activity by {subject} that you may see "
        "yet. When they act -- open an issue, push, "
        "create a repository -- the actions you may "
        "see will appear here, newest first.")


@dataclass(frozen=True)
class ActivityFeed:
    """One feed as a single view: its kind, its
    subject (a username, a repository full name, or
    `public`), its honest scope sentence, and the
    visible events, newest first. The count is the
    number of events shown to this reader -- there
    is deliberately no other count to carry."""
    kind: str
    subject: str
    scope: str
    events: tuple[CanonicalEvent, ...]

    @property
    def title(self) -> str:
        if self.kind == "public":
            return "Public activity"
        return f"Activity — {self.subject}"

    @property
    def count(self) -> int:
        """How many events this feed shows this
        reader. Filtered rows are not counted
        anywhere."""
        return len(self.events)

    @property
    def words(self) -> str:
        """The feed said in one plain sentence: what
        it is, how many it shows, and its scope."""
        noun = "event" if self.count == 1 else "events"
        return (f"{self.title}: {self.count} {noun}, "
                f"newest first. {self.scope}")


class ActivityFeedStore:
    """The three feeds over S-221's store: every
    read syncs the canonical events first, then
    filters event by event through S-190's engine,
    so no caller can forget the permission law."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        events: EventStore | None = None,
        engine: PermissionEngine | None = None,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._events = events or EventStore(
            conn, repositories, accounts)
        self._engine = engine or PermissionEngine(
            conn, accounts)

    # -- reading the witness -------------------------
    def _all_events(self) -> list[CanonicalEvent]:
        """Every canonical event, newest first,
        materialised fresh through S-221 (a read is
        never stale)."""
        self._events.sync_all()
        rows = self._conn.execute(
            "SELECT * FROM events ORDER BY id DESC"
        ).fetchall()
        return [self._to_event(r) for r in rows]

    def _to_event(self, row: sqlite3.Row) -> CanonicalEvent:
        try:
            refs = tuple(json.loads(row["refs_json"] or "[]"))
        except ValueError:
            refs = ()
        actor = (self._accounts.get_by_id(int(row["actor_id"]))
                 if row["actor_id"] else None)
        return CanonicalEvent(
            id=int(row["id"]), audit_seq=int(row["audit_seq"]),
            actor_kind=row["actor_kind"], actor_id=row["actor_id"],
            actor=actor.username if actor else "",
            verb=row["verb"], target_kind=row["target_kind"],
            target_id=row["target_id"],
            refs=tuple(str(r) for r in refs),
            detail=_parse_detail(row["detail_json"]),
            outcome=row["outcome"],
            created_at=int(row["created_at"]))

    def _repo_for(self, event: CanonicalEvent) -> Repository | None:
        full = event.repository
        if full is None:
            return None
        owner, _, name = full.partition("/")
        return self._repos.get_repository(owner, name)

    # -- the permission law --------------------------
    def _visible(self, viewer: User | None,
                 event: CanonicalEvent) -> bool:
        """One event under S-209's law, judged by
        S-190's engine: a repository event is visible
        exactly when this reader can read that
        repository (an unresolvable repository fails
        closed for everyone but its actor and site
        administrators, whose own history and
        oversight S-221 already names); an
        organisation event is a public directory
        fact; every other non-repository event is
        its actor's and the site administrators'."""
        if event.repository is not None:
            repo = self._repo_for(event)
            if repo is None:
                return viewer is not None and (
                    bool(viewer.is_admin)
                    or (event.actor_id is not None
                        and viewer.id == event.actor_id))
            return self._engine.can(viewer, repo, "read")
        if event.target_kind == "organization":
            return True
        if viewer is None:
            return False
        if viewer.is_admin:
            return True
        return (event.actor_id is not None
                and viewer.id == event.actor_id)

    @staticmethod
    def _clamp(limit: int) -> int:
        return max(1, min(int(limit), 500))

    def _resolve_actor(self, actor: object) -> User:
        subject: User | None = None
        if isinstance(actor, bool):
            subject = None
        elif isinstance(actor, int):
            subject = self._accounts.get_by_id(actor)
        elif isinstance(actor, User):
            subject = self._accounts.get_by_id(actor.id)
        elif isinstance(actor, str):
            subject = self._accounts.get_by_username(actor)
        if subject is None:
            raise ActivityFeedError(
                "no_such_user", "No such account.")
        return subject

    # -- the three feeds ------------------------------
    def user_feed(self, viewer: User | None, actor: object,
                  *, limit: int = 100) -> ActivityFeed:
        """One person's feed: their own actions,
        newest first, filtered event by event to
        what *viewer* may see. An unknown actor is
        `no_such_user`."""
        subject = self._resolve_actor(actor)
        shown = [e for e in self._all_events()
                 if e.actor_id == subject.id
                 and self._visible(viewer, e)]
        return ActivityFeed(
            kind="user", subject=subject.username,
            scope=feed_scope("user", subject.username),
            events=tuple(shown[:self._clamp(limit)]))

    def repo_feed(self, viewer: User | None, owner: object,
                  repo: object, *, limit: int = 100
                  ) -> ActivityFeed:
        """One repository's feed: its actions, newest
        first. Read access is the gate, judged by
        S-190's engine: a reader who cannot read the
        repository -- and anyone asking after a
        missing one -- gets the uniform
        `repo_not_found`, so the feed never confirms
        an unreadable repository exists."""
        current = self._repos.get_repository(owner, repo)
        if current is None or not self._engine.can(
                viewer, current, "read"):
            raise ActivityFeedError(
                "repo_not_found", "No such repository.")
        shown = [e for e in self._all_events()
                 if e.repository == current.full_name]
        return ActivityFeed(
            kind="repository", subject=current.full_name,
            scope=feed_scope("repository", current.full_name),
            events=tuple(shown[:self._clamp(limit)]))

    def public_feed(self, viewer: User | None = None,
                    *, limit: int = 100) -> ActivityFeed:
        """The instance's public-activity feed:
        actions in public repositories only, newest
        first. *viewer* is accepted so callers pass
        their reader uniformly -- and is then
        deliberately not consulted: a site
        administrator, the actor themself, and an
        anonymous visitor all receive the same
        public-only feed (see PUBLIC_FEED_SCOPE)."""
        del viewer  # public means public, for everyone
        shown: list[CanonicalEvent] = []
        for event in self._all_events():
            if in_public_feed(self._repo_for(event)):
                shown.append(event)
                if len(shown) >= self._clamp(limit):
                    break
        return ActivityFeed(
            kind="public", subject="public",
            scope=feed_scope("public", "public"),
            events=tuple(shown))


def _parse_detail(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


# -- renders ---------------------------------------------------
def render_feed_entry(event: CanonicalEvent) -> str:
    """One feed row in words -- who did what to
    what, and when -- with every user-controlled
    value escaped through S-010."""
    actor = escape_html_text(event.actor or event.actor_kind)
    verb = escape_html_text(event.verb)
    target = escape_html_text(event.target_id or event.target_kind)
    refs = escape_html_text(", ".join(event.refs))
    ref_part = f" ({refs})" if refs else ""
    return (f'<li class="feed-entry">{actor} — {verb} — '
            f"{target}{ref_part} — {event.created_at}</li>")


def render_feed_page(feed: ActivityFeed) -> str:
    """One feed as a page: its title, its standing
    in one plain sentence (count, order, and honest
    scope), then its rows -- or its honest empty
    state, which says what would appear. Meaning
    never rides on an icon or a colour alone."""
    lines = [
        f"<h1>{escape_html_text(feed.title)}</h1>",
        f"<p>{escape_html_text(feed.words)}</p>",
    ]
    if not feed.events:
        lines.append(
            "<p>" + escape_html_text(
                empty_words(feed.kind, feed.subject)) + "</p>")
        return "\n".join(lines)
    lines.append("<ul>")
    for event in feed.events:
        lines.append(render_feed_entry(event))
    lines.append("</ul>")
    return "\n".join(lines)


def render_user_feed_page(feed: ActivityFeed) -> str:
    """A person's feed page (see render_feed_page)."""
    return render_feed_page(feed)


def render_repo_feed_page(feed: ActivityFeed) -> str:
    """A repository's feed page (see render_feed_page)."""
    return render_feed_page(feed)


def render_public_feed_page(feed: ActivityFeed) -> str:
    """The instance public-activity page: its scope
    sentence -- public repositories only, private
    and internal actions never shown, not even to
    site administrators -- is part of the feed's own
    words, so the label is on the page itself."""
    return render_feed_page(feed)
