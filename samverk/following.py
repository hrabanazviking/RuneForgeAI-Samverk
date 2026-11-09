"""Following (S-232).

Follow users to see their public activity; follower
lists on profiles; no algorithmic ranking,
chronological truth only. Part XI closes its social
circle here: S-222 gave repositories watchers and
stars, S-229/S-230 gathered a person's actions into
feeds and onto their profile, and this slice is the
subscription-free, ranking-free way to keep up with
a person -- follow them, and their *public* activity
arrives in witness order.

- **A follow is a stored row, counted live.** One
  row per (follower, followed) pair in migration
  93's `user_follows`; unfollowing deletes the row.
  Follower and following counts are `COUNT(*)`
  over those rows at read time -- never a cached
  counter that could drift, never a dressed-up
  zero (S-222's law, carried to people).
- **Only genuinely public activity is followed.**
  The following feed shows a followed person's
  actions exactly when S-230's `is_profile_public`
  judgement -- reused, never re-derived -- calls
  them genuinely public: an action in a public
  repository, or a public organisation action.
  Actions in private and internal repositories,
  and every other non-public action, never appear
  -- not for the follower, not for the subject,
  not for a site administrator. The reader's
  standing is never the judgement; the resource's
  visibility is.
- **Chronological truth only.** The feed is the
  canonical event store's own order -- newest
  first, witness order, event by event. There is
  no score, no relevance, no ranking field
  anywhere in this module: what happened later
  stands above what happened earlier, and nothing
  reorders it. The page says so in plain words.
- **Only real changes are witnessed.** Following
  someone you already follow and unfollowing
  someone you never followed are quiet no-ops --
  retries are safe, and the audit log
  (`auth.follow` / `auth.unfollow`, two append-only
  taxonomy additions; 129 events stand) records a
  change only when one happened, so S-221's event
  store sees exactly the real mutations.
- **Refusals are uniform and store nothing.**
  Following yourself is refused (`self_follow`);
  an unknown person is `no_such_user` on every
  face; mutations and the personal following feed
  need a signed-in account (`login_required`).
  Follower and following lists are public profile
  facts, readable by anyone, in the order the
  follows began.

One migration: 93 creates `user_follows`
(schema 92 to 93).
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .activity_feeds import ActivityFeedStore, render_feed_entry
from .audit import AuditLog
from .escaping import escape_html_text
from .event_store import CanonicalEvent, EventStore
from .profile_activity import is_profile_public
from .repositories import RepositoryStore

__all__ = [
    "FOLLOWING_FEED_SCOPE", "FOLLOWING_SCOPE",
    "FollowLists", "FollowState", "FollowingError",
    "FollowingFeed", "FollowingStore", "decide_follow",
    "following_empty_words", "render_follow_lists",
    "render_follow_state", "render_following_feed_page",
    "render_profile_follows_section",
]

# The following law, said once, in words, and
# printed on its pages: the limit is a labelled
# law, not a silent filter.
FOLLOWING_SCOPE = (
    "Following shows a person's public activity "
    "only. Actions in private and internal "
    "repositories never appear in a following "
    "feed, for anyone.")

# The feed's order, said once, in words: there is
# no ranking to describe, and the page says that
# too, so the absence is labelled, never silent.
FOLLOWING_FEED_SCOPE = (
    "Newest first, in the order things happened. "
    "There is no algorithmic ranking: nothing is "
    "scored, promoted, or reordered. "
    + FOLLOWING_SCOPE)


class FollowingError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def decide_follow(following_now: bool, want: bool) -> bool:
    """Pure: True when moving to *want* changes the
    stored follow state -- a real change worth
    storing and witnessing; False for a retry of
    the state already held."""
    return following_now != want


@dataclass(frozen=True)
class FollowState:
    """One person's standing with one viewer: who
    the subject is, whether the viewer follows
    them, and the live counts on their profile."""
    subject: str
    following: bool          # the viewer's own follow
    follower_count: int      # live, counted rows
    following_count: int     # live, counted rows

    @property
    def words(self) -> str:
        mine = ("followed by you" if self.following
                else "not followed by you")
        return (f"{self.subject}: {self.follower_count} "
                f"followers, following "
                f"{self.following_count} — {mine}.")


@dataclass(frozen=True)
class FollowLists:
    """A profile's two lists: who follows the
    subject and who the subject follows, each in
    the order those follows began. The counts are
    the lists' own lengths -- there is deliberately
    no other count to carry."""
    subject: str
    followers: tuple[str, ...]
    following: tuple[str, ...]

    @property
    def follower_count(self) -> int:
        return len(self.followers)

    @property
    def following_count(self) -> int:
        return len(self.following)


@dataclass(frozen=True)
class FollowingFeed:
    """The viewer's following feed: the public
    activity of the people they follow, newest
    first, in witness order. The count is the
    number of events shown -- filtered rows
    contribute no row and no number."""
    viewer: str
    scope: str
    events: tuple[CanonicalEvent, ...]

    @property
    def title(self) -> str:
        return "Following"

    @property
    def count(self) -> int:
        return len(self.events)

    @property
    def words(self) -> str:
        noun = "event" if self.count == 1 else "events"
        return (f"{self.title}: {self.count} {noun}, "
                f"{self.scope}")


def following_empty_words(viewer: str) -> str:
    """The honest empty state, in words: the feed
    is empty, and what would appear in it."""
    return (
        "No followed activity yet. When someone "
        "you follow acts in a public repository, "
        "or acts publicly for an organisation, "
        "those actions will appear here, newest "
        "first. Actions in private and internal "
        "repositories never appear in a following "
        "feed.")


class FollowingStore:
    """Follows over migration 93's rows, and the
    following feed over S-229's feed store (each
    read syncs S-221's canonical events first, so
    an answer is never stale), judged event by
    event through S-230's `is_profile_public`."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        audit: AuditLog | None = None,
        events: EventStore | None = None,
        feeds: ActivityFeedStore | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._audit = audit
        self._now = time_fn
        self._feeds = feeds or ActivityFeedStore(
            conn, repositories, accounts, events=events)

    # -- resolution --------------------------------
    def _resolve_subject(self, subject: object) -> User:
        found: User | None = None
        if isinstance(subject, bool):
            found = None
        elif isinstance(subject, int):
            found = self._accounts.get_by_id(subject)
        elif isinstance(subject, User):
            found = self._accounts.get_by_id(subject.id)
        elif isinstance(subject, str):
            found = self._accounts.get_by_username(subject)
        if found is None:
            raise FollowingError(
                "no_such_user", "No such account.")
        return found

    @staticmethod
    def _require_actor(actor: User | None) -> User:
        if actor is None:
            raise FollowingError(
                "login_required",
                "Following needs a signed-in account.")
        return actor

    def _follow_row(self, follower_id: int,
                    followed_id: int) -> bool:
        row = self._conn.execute(
            "SELECT 1 AS x FROM user_follows"
            " WHERE follower_id = ? AND followed_id = ?",
            (follower_id, followed_id)).fetchone()
        return row is not None

    # -- follow / unfollow ---------------------------
    def follow(self, actor: User | None, subject: object,
               *, source_ip: str | None = None
               ) -> FollowState:
        """Follow *subject*: one stored row. A retry
        of a held follow is a quiet no-op. Following
        yourself is refused `self_follow`."""
        actor = self._require_actor(actor)
        person = self._resolve_subject(subject)
        if person.id == actor.id:
            raise FollowingError(
                "self_follow",
                "You cannot follow yourself.")
        if decide_follow(
                self._follow_row(actor.id, person.id), True):
            with self._conn:  # commits before the answer
                self._conn.execute(
                    "INSERT OR IGNORE INTO user_follows"
                    " (follower_id, followed_id, created_at)"
                    " VALUES (?, ?, ?)",
                    (actor.id, person.id, int(self._now())))
            self._emit(actor, "auth.follow", person, source_ip)
        return self.follow_state(actor, person)

    def unfollow(self, actor: User | None, subject: object,
                 *, source_ip: str | None = None
                 ) -> FollowState:
        """Take the actor's own follow back.
        Unfollowing someone never followed is a
        quiet no-op; there is no seam that removes
        another account's follow."""
        actor = self._require_actor(actor)
        person = self._resolve_subject(subject)
        if decide_follow(
                self._follow_row(actor.id, person.id), False):
            with self._conn:
                self._conn.execute(
                    "DELETE FROM user_follows"
                    " WHERE follower_id = ? AND followed_id = ?",
                    (actor.id, person.id))
            self._emit(actor, "auth.unfollow", person, source_ip)
        return self.follow_state(actor, person)

    def _emit(self, actor: User, action: str, person: User,
              source_ip: str | None) -> None:
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action=action, target_kind="user",
                target_id=str(person.id), outcome="success",
                source_ip=source_ip,
                detail={"followed": person.username})

    # -- state and lists -----------------------------
    def is_following(self, viewer: User | None,
                     subject: object) -> bool:
        person = self._resolve_subject(subject)
        if viewer is None:
            return False
        return self._follow_row(viewer.id, person.id)

    def follower_count(self, subject: object) -> int:
        """Live count of the subject's follower rows."""
        person = self._resolve_subject(subject)
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM user_follows"
            " WHERE followed_id = ?", (person.id,)).fetchone()
        return int(row["c"])

    def following_count(self, subject: object) -> int:
        """Live count of the rows where the subject
        is the follower."""
        person = self._resolve_subject(subject)
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM user_follows"
            " WHERE follower_id = ?", (person.id,)).fetchone()
        return int(row["c"])

    def follow_state(self, viewer: User | None,
                     subject: object) -> FollowState:
        person = self._resolve_subject(subject)
        mine = (viewer is not None
                and self._follow_row(viewer.id, person.id))
        return FollowState(
            subject=person.username, following=mine,
            follower_count=self.follower_count(person),
            following_count=self.following_count(person))

    def followers(self, subject: object) -> tuple[str, ...]:
        """Who follows the subject, in the order
        they began: a public profile fact, readable
        by anyone."""
        person = self._resolve_subject(subject)
        rows = self._conn.execute(
            "SELECT u.username AS username FROM user_follows f"
            " JOIN users u ON u.id = f.follower_id"
            " WHERE f.followed_id = ?"
            " ORDER BY f.created_at, f.id",
            (person.id,)).fetchall()
        return tuple(r["username"] for r in rows)

    def following_of(self, subject: object) -> tuple[str, ...]:
        """Who the subject follows, in the order
        they began: a public profile fact, readable
        by anyone."""
        person = self._resolve_subject(subject)
        rows = self._conn.execute(
            "SELECT u.username AS username FROM user_follows f"
            " JOIN users u ON u.id = f.followed_id"
            " WHERE f.follower_id = ?"
            " ORDER BY f.created_at, f.id",
            (person.id,)).fetchall()
        return tuple(r["username"] for r in rows)

    def follow_lists(self, subject: object) -> FollowLists:
        """The profile's two lists as one view."""
        person = self._resolve_subject(subject)
        return FollowLists(
            subject=person.username,
            followers=self.followers(person),
            following=self.following_of(person))

    # -- the following feed ----------------------------
    @staticmethod
    def _clamp(limit: int) -> int:
        return max(1, min(int(limit), 500))

    def following_feed(self, viewer: User | None,
                       *, limit: int = 100) -> FollowingFeed:
        """The public activity of everyone *viewer*
        follows, newest first in witness order --
        chronological truth only, no ranking. An
        event is shown exactly when its actor is
        followed by the viewer and S-230's judgement
        calls it genuinely public. Anonymous is
        refused `login_required`: the feed is
        personal, because the follow list is the
        viewer's own."""
        viewer = self._require_actor(viewer)
        rows = self._conn.execute(
            "SELECT followed_id FROM user_follows"
            " WHERE follower_id = ?", (viewer.id,)).fetchall()
        followed = {int(r["followed_id"]) for r in rows}
        shown: list[CanonicalEvent] = []
        if followed:
            for event in self._feeds._all_events():
                if event.actor_id not in followed:
                    continue
                if is_profile_public(
                        event, self._feeds._repo_for(event)):
                    shown.append(event)
                    if len(shown) >= self._clamp(limit):
                        break
        return FollowingFeed(
            viewer=viewer.username,
            scope=FOLLOWING_FEED_SCOPE,
            events=tuple(shown))


# -- renders ---------------------------------------------------
def render_follow_state(state: FollowState) -> str:
    """The follow panel in words: the live counts,
    and the viewer's own standing named plainly --
    meaning never rides on an icon or a colour
    alone. Every value passes S-010's seam."""
    return "\n".join([
        '<section class="profile-follow">',
        f"<p>{escape_html_text(state.words)}</p>",
        "</section>",
    ])


def render_follow_lists(lists: FollowLists) -> str:
    """A profile's follower and following lists:
    each list's count said in words, then its
    names in the order the follows began -- or
    its honest empty sentence. Every name passes
    S-010's seam."""
    lines = [
        f"<h2>Followers — {escape_html_text(lists.subject)}</h2>",
        f"<p>{lists.follower_count} followers, in the "
        "order they began following.</p>",
    ]
    if lists.followers:
        lines.append("<ul>")
        for name in lists.followers:
            lines.append(
                f"<li>{escape_html_text(name)}</li>")
        lines.append("</ul>")
    else:
        lines.append(
            "<p>No followers yet. When someone "
            "follows this person, their name will "
            "appear here.</p>")
    lines.append(
        f"<h2>Following — {escape_html_text(lists.subject)}</h2>")
    lines.append(
        f"<p>Following {lists.following_count}, in the "
        "order the follows began.</p>")
    if lists.following:
        lines.append("<ul>")
        for name in lists.following:
            lines.append(
                f"<li>{escape_html_text(name)}</li>")
        lines.append("</ul>")
    else:
        lines.append(
            "<p>Not following anyone yet. When this "
            "person follows someone, their name will "
            "appear here.</p>")
    return "\n".join(lines)


def render_profile_follows_section(lists: FollowLists) -> str:
    """The follow lists as a profile page section
    (see render_follow_lists)."""
    return render_follow_lists(lists)


def render_following_feed_page(feed: FollowingFeed) -> str:
    """The following feed as a page: its title, its
    standing in one plain sentence (count, witness
    order, the no-ranking scope, and the
    public-only law), then its rows -- or its
    honest empty state. Rows reuse S-229's escaped
    entry renderer."""
    lines = [
        f"<h1>{escape_html_text(feed.title)}</h1>",
        f"<p>{escape_html_text(feed.words)}</p>",
    ]
    if not feed.events:
        lines.append(
            "<p>" + escape_html_text(
                following_empty_words(feed.viewer)) + "</p>")
        return "\n".join(lines)
    lines.append("<ul>")
    for event in feed.events:
        lines.append(render_feed_entry(event))
    lines.append("</ul>")
    return "\n".join(lines)
