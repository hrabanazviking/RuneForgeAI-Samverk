"""Profile activity (S-230).

The profile face of S-229's feed law. A profile is
a public surface: it shows the subject's *public*
actions, and nothing else. Before this slice a
person's actions were readable only through S-229's
user feed, whose law is the reader's: it shows a
viewer what that viewer may see, so the subject and
a site administrator saw private-repository actions
there. That is right for a feed and wrong for a
profile, which anyone may open. This module is the
profile's own gathering, under five laws:

- **Judged by the resource, never by the reader
  (S-209's rule applied to feeds).** An action
  appears on a profile exactly when it is genuinely
  public: it names a repository whose visibility is
  `public` (S-229's `in_public_feed` judgement,
  reused, never re-derived), or it is an
  organisation event, which S-221 and S-229 already
  name a public directory fact. Actions in private
  and internal repositories never appear -- not for
  an anonymous visitor, not for another member, not
  for the subject themself, and not for a site
  administrator. The reader's standing is accepted
  in the call shape and then deliberately not
  consulted, exactly as S-229's public feed refuses
  to consult it.
- **A read model over the witness, never a second
  log.** Every answer is read from S-221's canonical
  `events` table through S-229's own store (each
  read syncs first, so an answer is never stale).
  This slice writes nothing, audits nothing, and
  claims no migration and no taxonomy event: schema
  92 stands, and 127 events stand (31 auth, 83 repo,
  13 admin).
- **The limit is labelled, never silent.** The
  profile is a public surface and its page says so
  in plain words (the scope sentence below): only
  public actions appear here, and private and
  internal actions never do, not even for the
  subject or a site administrator.
- **One order, counted honestly.** Newest first,
  the order S-221's store reads. The count counts
  only what is shown; filtered rows contribute no
  row, no target, and no number anywhere on the
  page.
- **Honest empty state, escaped rendering.** A
  subject with no public actions gets a sentence
  that says the profile activity is empty and what
  would appear in it. All user-controlled text
  escapes through S-010's seam (rows reuse S-229's
  escaped entry renderer).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .accounts import AccountStore, User
from .activity_feeds import (
    ActivityFeedStore, in_public_feed, render_feed_entry)
from .escaping import escape_html_text
from .event_store import CanonicalEvent, EventStore
from .profiles import Profile, render_profile_page
from .repositories import Repository, RepositoryStore

__all__ = [
    "PROFILE_ACTIVITY_SCOPE", "ProfileActivity",
    "ProfileActivityError", "ProfileActivityStore",
    "is_profile_public", "profile_empty_words",
    "render_profile_activity_page",
    "render_profile_activity_section",
    "render_profile_page_with_activity",
]

# The profile activity scope, said once, in words,
# and printed on its page: the profile is a public
# surface, and the limit is a labelled law.
PROFILE_ACTIVITY_SCOPE = (
    "A profile is a public surface. This list carries "
    "the person's public actions only: actions in "
    "public repositories, and public organisation "
    "actions. Actions in private and internal "
    "repositories never appear here, not even for "
    "the person themself or for site administrators.")


class ProfileActivityError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def is_profile_public(event: CanonicalEvent,
                      repo: Repository | None) -> bool:
    """Pure: an event belongs on a profile exactly
    when it is genuinely public -- it names a public
    repository (S-229's judgement), or it is an
    organisation event, a public directory fact under
    S-221's standing law. Everything else -- private
    and internal repository actions, and every other
    non-repository event -- is refused, whoever asks.
    A repository event whose repository no longer
    resolves fails closed."""
    if event.repository is not None:
        return in_public_feed(repo)
    return event.target_kind == "organization"


def profile_empty_words(subject: str) -> str:
    """The honest empty state, in words: the list is
    empty, and what would appear in it."""
    return (
        f"No public activity by {subject} yet. When "
        "they act in a public repository, or act "
        "publicly for an organisation, those actions "
        "will appear here, newest first. Actions in "
        "private and internal repositories never "
        "appear on a profile.")


@dataclass(frozen=True)
class ProfileActivity:
    """One profile's activity as a single view: the
    subject's username, the honest scope sentence,
    and the public events, newest first. The count
    is the number of events shown -- there is
    deliberately no other count to carry."""
    subject: str
    scope: str
    events: tuple[CanonicalEvent, ...]

    @property
    def title(self) -> str:
        return f"Activity — {self.subject}"

    @property
    def count(self) -> int:
        return len(self.events)

    @property
    def words(self) -> str:
        noun = "event" if self.count == 1 else "events"
        return (f"{self.title}: {self.count} {noun}, "
                f"newest first. {self.scope}")


class ProfileActivityStore:
    """Profile activity over S-229's feed store: the
    gathering reuses S-229's sync and materialisation
    (its `_all_events` / `_repo_for` readers), then
    keeps only the subject's genuinely public events.
    The viewer is never consulted: the resource's
    visibility is the whole judgement."""

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
        self._feeds = feeds or ActivityFeedStore(
            conn, repositories, accounts, events=events)

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
            raise ProfileActivityError(
                "no_such_user", "No such account.")
        return found

    @staticmethod
    def _clamp(limit: int) -> int:
        return max(1, min(int(limit), 500))

    def profile_activity(
        self, viewer: User | None, subject: object,
        *, limit: int = 100,
    ) -> ProfileActivity:
        """One person's public actions, newest first.
        *viewer* is accepted so callers pass their
        reader uniformly -- and is then deliberately
        not consulted: an anonymous visitor, another
        member, the subject, and a site administrator
        all receive the same public-only list (see
        PROFILE_ACTIVITY_SCOPE). An unknown subject
        is `no_such_user`."""
        del viewer  # a profile is public, for everyone
        person = self._resolve_subject(subject)
        shown: list[CanonicalEvent] = []
        for event in self._feeds._all_events():
            if event.actor_id != person.id:
                continue
            if is_profile_public(
                    event, self._feeds._repo_for(event)):
                shown.append(event)
                if len(shown) >= self._clamp(limit):
                    break
        return ProfileActivity(
            subject=person.username,
            scope=PROFILE_ACTIVITY_SCOPE,
            events=tuple(shown))


# -- renders ---------------------------------------------------
def render_profile_activity_section(
        activity: ProfileActivity) -> str:
    """The activity section of a profile page: its
    title, its standing in one plain sentence (count,
    order, and the honest public-surface scope), then
    its rows -- or its honest empty state. Every
    user-controlled value escapes through S-010 (rows
    reuse S-229's escaped entry renderer)."""
    lines = [
        f"<h2>{escape_html_text(activity.title)}</h2>",
        f"<p>{escape_html_text(activity.words)}</p>",
    ]
    if not activity.events:
        lines.append(
            "<p>" + escape_html_text(
                profile_empty_words(activity.subject)) + "</p>")
        return "\n".join(lines)
    lines.append("<ul>")
    for event in activity.events:
        lines.append(render_feed_entry(event))
    lines.append("</ul>")
    return "\n".join(lines)


def render_profile_activity_page(
        activity: ProfileActivity) -> str:
    """The profile activity as a standalone page (see
    render_profile_activity_section)."""
    return render_profile_activity_section(activity)


def render_profile_page_with_activity(
        username: str, profile: Profile,
        activity: ProfileActivity) -> str:
    """S-029's profile page with the S-230 activity
    section set into it, before the closing body tag:
    the profile surface itself carries the person's
    public actions and the public-surface label."""
    page = render_profile_page(username, profile)
    section = render_profile_activity_section(activity)
    marker = "</body></html>"
    if marker in page:
        return page.replace(marker, section + "\n" + marker)
    return page + "\n" + section
