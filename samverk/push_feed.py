"""Push feed for owners (S-234).

Pushes to your repos surface in your feed with
commit summaries (from S-090 events). S-090 made
the canonical push record -- who pushed, by which
transport, and exactly which refs moved with their
commit ranges -- and S-229 gave Part XI its feed
faces, but a repository owner had no surface that
answers the owner's own question: *what landed on
the repositories I own?* This module is that
surface, under five laws:

- **A read model over S-090's store, never a
  second record.** The feed is gathered at read
  time from S-090's `push_events` rows for
  repositories whose owner
  is the reader. It stores nothing of its own. No
  migration -- schema 93 stands. No new audit
  event -- 129 stand (33 auth, 83 repo, 13 admin):
  reading a feed witnesses nothing, because the
  push itself was witnessed by `repo.push` when
  it landed.
- **Yours means owned by you.** A push surfaces
  exactly when the repository it landed on is
  owned by the feed's reader (its owner name is
  the reader's username) -- whoever pushed it: the
  owner themself, another account, a deploy key,
  or the system. Pushes to other people's
  repositories never appear, in rows or in counts;
  the feed's total is the total of what it shows.
  Organisation-owned repositories are not folded
  in silently: this feed is the personal owner's
  feed, and its scope sentence says so.
- **The feed is personal, so it is signed-in
  only.** Anonymous readers are refused
  `authentication_required` (S-232's law for a
  personal feed): the feed carries pushes to
  private repositories too, and only their owner
  may see them gathered. There is no other-person
  face at all -- a push feed is read by its owner
  or not at all.
- **Commit summaries are read live, and degrade
  honestly.** Each moved ref is summarised from
  the repository itself at read time: the ref's
  short name, its kind (S-090's `update_kind`:
  created / updated / deleted), the true commit
  count of its range (`rev-list --count`), and up
  to `SUBJECT_LIMIT` commit subjects, with the
  remainder counted, never hidden. A deleted ref
  carries no commits and says so. A range whose
  commits cannot be read -- a force-moved history,
  a pruned object -- still surfaces as a push, with
  its summary marked unavailable in words: the
  feed never invents a count or a subject it did
  not read.
- **One order, said in words.** Newest push first
  -- the S-090 store's own order -- stated beside
  the count on the page, never by colour or
  position alone. All user-controlled text (actor
  names, repository names, commit subjects) escapes
  through S-010's seam.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

from .accounts import AccountStore, User
from .escaping import escape_html_text
from .hooks import RefUpdate
from .proc import run_git_in
from .push_events import PushEventStore, update_kind
from .repositories import RepositoryStore

__all__ = [
    "PUSH_FEED_SCOPE", "SUBJECT_LIMIT", "PushFeed",
    "PushFeedEntry", "PushFeedError", "PushFeedStore",
    "RefSummary", "push_feed_empty_words",
    "range_revspec", "render_push_feed_entry",
    "render_push_feed_page", "short_ref",
    "summarise_update",
]

# How many commit subjects one ref summary carries;
# the rest are counted in `more_count`, never hidden.
SUBJECT_LIMIT = 5

# The feed's scope, said once, in words, and printed
# on its page: whose pushes these are, and whose
# never appear.
PUSH_FEED_SCOPE = (
    "Pushes to repositories you own, newest first, "
    "each with the commits that landed. Pushes to "
    "other people's repositories never appear here.")


class PushFeedError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def short_ref(ref: str) -> str:
    """A ref's short name: `refs/heads/main` is
    `main`, `refs/tags/v1` is `v1`; anything else is
    carried whole."""
    for prefix in ("refs/heads/", "refs/tags/"):
        if ref.startswith(prefix):
            return ref[len(prefix):]
    return ref


def range_revspec(update: RefUpdate) -> str | None:
    """The revspec naming a ref update's commits:
    `old..new` for an update, the new oid alone for
    a creation (its commits are the ones that
    became reachable), and None for a deletion,
    which lands no commits."""
    kind = update_kind(update)
    if kind == "deleted":
        return None
    if kind == "created":
        return update.new_oid
    return f"{update.old_oid}..{update.new_oid}"


@dataclass(frozen=True)
class RefSummary:
    """One moved ref, summarised: its short name,
    its kind, and the commits that landed with it.
    `commit_count` is None exactly when the range
    could not be read; `available` says which."""
    ref: str
    name: str
    kind: str                # created | updated | deleted
    commit_count: int | None
    subjects: tuple[str, ...]
    more_count: int          # commits beyond the subjects
    available: bool

    @property
    def words(self) -> str:
        if self.kind == "deleted":
            return f"{self.name} deleted (no commits landed)"
        if not self.available or self.commit_count is None:
            return (f"{self.name} {self.kind}; the commit "
                    "summary could not be read")
        noun = "commit" if self.commit_count == 1 else "commits"
        verb = "created with" if self.kind == "created" else "updated with"
        words = f"{self.name} {verb} {self.commit_count} {noun}"
        if self.subjects:
            words += ": " + "; ".join(self.subjects)
            if self.more_count:
                words += f"; and {self.more_count} more"
        return words


def summarise_update(repo_path, update: RefUpdate,
                     *, subject_limit: int = SUBJECT_LIMIT) -> RefSummary:
    """One ref update's summary, read live from the
    repository: the true range count and up to
    `subject_limit` subjects. Any read failure --
    an unreadable range, a missing object -- yields
    the honest unavailable summary, never a guess."""
    name = short_ref(update.ref)
    kind = update_kind(update)
    spec = range_revspec(update)
    if spec is None:
        return RefSummary(
            ref=update.ref, name=name, kind=kind, commit_count=0,
            subjects=(), more_count=0, available=True)
    try:
        counted = run_git_in(
            repo_path, ["rev-list", "--count", spec], timeout=15.0)
        if counted.returncode != 0:
            raise ValueError("range unreadable")
        total = int(counted.stdout.decode().strip())
        logged = run_git_in(
            repo_path,
            ["log", f"--max-count={int(subject_limit)}",
             "--format=%s", spec],
            timeout=15.0)
        if logged.returncode != 0:
            raise ValueError("range unreadable")
        subjects = tuple(
            line for line in
            logged.stdout.decode("utf-8", "replace").splitlines()
            if line)
    except Exception:
        return RefSummary(
            ref=update.ref, name=name, kind=kind, commit_count=None,
            subjects=(), more_count=0, available=False)
    return RefSummary(
        ref=update.ref, name=name, kind=kind, commit_count=total,
        subjects=subjects,
        more_count=max(0, total - len(subjects)), available=True)


@dataclass(frozen=True)
class PushFeedEntry:
    """One push in the owner's feed: the S-090 event
    said in feed terms -- which repository, who
    pushed (an account name, or the actor kind in
    words for deploy keys and the system), by which
    transport, when, and one summary per moved ref."""
    event_id: int
    full_name: str
    actor_label: str
    actor_kind: str
    transport: str
    pushed_at: int
    summaries: tuple[RefSummary, ...]

    @property
    def pushed_words(self) -> str:
        return time.strftime(
            "%Y-%m-%d %H:%M UTC", time.gmtime(self.pushed_at))

    @property
    def words(self) -> str:
        moved = "; ".join(s.words for s in self.summaries)
        return (f"{self.actor_label} pushed to "
                f"{self.full_name} via {self.transport} "
                f"({self.pushed_words}): {moved}")


@dataclass(frozen=True)
class PushFeed:
    """The owner's push feed as one view: the
    visible pushes, newest first, and the total --
    which counts only pushes to the owner's own
    repositories, because no other push is gathered
    at all."""
    owner: str
    scope: str
    entries: tuple[PushFeedEntry, ...]
    total: int               # gathered pushes, before the cap

    @property
    def title(self) -> str:
        return f"Pushes to your repositories — {self.owner}"

    @property
    def count(self) -> int:
        return len(self.entries)

    @property
    def words(self) -> str:
        noun = "push" if self.total == 1 else "pushes"
        shown = ("" if self.count == self.total else
                 f" Showing the {self.count} most recent.")
        return f"{self.total} {noun}.{shown} {self.scope}"


def push_feed_empty_words(owner: str) -> str:
    """The honest empty state, in words: nothing has
    been pushed to the owner's repositories yet, and
    what will appear here when it is."""
    return (
        f"No pushes to {owner}'s repositories yet. "
        "When anyone pushes to a repository you own "
        "-- you, another account, or a deploy key -- "
        "the push will appear here with the commits "
        "that landed, newest first.")


class PushFeedStore:
    """The owner push feed over S-090's `push_events`
    rows: gathered by repository ownership at read
    time, summarised live from each repository's own
    history, and stored nowhere."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        pushes: PushEventStore | None = None,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._pushes = pushes or PushEventStore(conn, repositories)

    # -- the reader ----------------------------------
    def _require_viewer(self, viewer: object) -> User:
        found: User | None = None
        if isinstance(viewer, bool):
            found = None
        elif isinstance(viewer, int):
            found = self._accounts.get_by_id(viewer)
        elif isinstance(viewer, User):
            found = self._accounts.get_by_id(viewer.id)
        if found is None:
            raise PushFeedError(
                "authentication_required",
                "The push feed is personal: sign in to "
                "read the pushes to your repositories.")
        return found

    def _actor_label(self, actor_kind: str,
                     actor_id: int | None) -> str:
        if actor_kind == "user" and actor_id is not None:
            actor = self._accounts.get_by_id(int(actor_id))
            if actor is not None:
                return actor.username
            return "an unknown account"
        if actor_kind == "deploy_key":
            return "a deploy key"
        if actor_kind == "system":
            return "the system"
        return actor_kind

    @staticmethod
    def _clamp(limit: int) -> int:
        return max(1, min(int(limit), 500))

    def _gather(self, person: User) -> list[PushFeedEntry]:
        """Every push to the reader's own
        repositories, newest first: the gather is
        judged by repository ownership in the query
        itself, so no other owner's push is ever
        read, counted, or summarised."""
        rows = self._conn.execute(
            "SELECT pe.id AS pid FROM push_events pe"
            " JOIN repositories r ON r.id = pe.repo_id"
            " WHERE r.owner_lower = ? ORDER BY pe.id DESC",
            (person.username.lower(),)).fetchall()
        entries: list[PushFeedEntry] = []
        by_repo: dict[int, object] = {}
        for row in rows:
            event = self._event_for(int(row["pid"]))
            if event is None:
                continue
            repo = by_repo.get(event.repo_id)
            if repo is None:
                repo = self._repos.get_by_id(event.repo_id)
                by_repo[event.repo_id] = repo
            if repo is None:
                continue
            path = self._repos.path_for(repo.owner, repo.name)
            entries.append(PushFeedEntry(
                event_id=event.id, full_name=event.full_name,
                actor_label=self._actor_label(
                    event.actor_kind, event.actor_id),
                actor_kind=event.actor_kind,
                transport=event.transport,
                pushed_at=event.created_at,
                summaries=tuple(
                    summarise_update(path, update)
                    for update in event.updates)))
        return entries

    def _event_for(self, event_id: int):
        """One S-090 event by id, read through the
        push store's own row seam."""
        row = self._conn.execute(
            "SELECT * FROM push_events WHERE id = ?",
            (event_id,)).fetchone()
        if row is None:
            return None
        repo = self._repos.get_by_id(int(row["repo_id"]))
        if repo is None:
            return None
        return self._pushes._to_event(row, repo.full_name)

    # -- the feed --------------------------------------
    def push_feed(self, viewer: object, *, limit: int = 100) -> PushFeed:
        """The reader's own push feed: pushes to
        repositories they own, newest first, each
        with live commit summaries. Signed-in only;
        there is no other-person face."""
        person = self._require_viewer(viewer)
        gathered = self._gather(person)
        return PushFeed(
            owner=person.username, scope=PUSH_FEED_SCOPE,
            entries=tuple(gathered[:self._clamp(limit)]),
            total=len(gathered))

    def push_count(self, viewer: object) -> int:
        """How many pushes to the reader's own
        repositories the feed gathers -- the same
        total the feed itself reports."""
        person = self._require_viewer(viewer)
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM push_events pe"
            " JOIN repositories r ON r.id = pe.repo_id"
            " WHERE r.owner_lower = ?",
            (person.username.lower(),)).fetchone()
        return int(row["n"])


# -- renders ---------------------------------------------------
def render_push_feed_entry(entry: PushFeedEntry) -> str:
    """One push in words -- who pushed to what, by
    which transport, when, and what landed ref by
    ref -- with every user-controlled value escaped
    through S-010. Meaning never rides on an icon or
    a colour alone."""
    lines = ["<li>", f"<p>{escape_html_text(entry.words)}</p>", "</li>"]
    return "\n".join(lines)


def render_push_feed_page(feed: PushFeed) -> str:
    """The push feed as a page: its title, its
    standing in one plain sentence set (total,
    order, and honest scope), then its pushes -- or
    its honest empty state, which teaches what the
    feed will carry."""
    lines = [
        f"<h1>{escape_html_text(feed.title)}</h1>",
        f"<p>{escape_html_text(feed.words)}</p>",
    ]
    if not feed.entries:
        lines.append(
            "<p>" + escape_html_text(
                push_feed_empty_words(feed.owner)) + "</p>")
        return "\n".join(lines)
    lines.append("<ul>")
    for entry in feed.entries:
        lines.append(render_push_feed_entry(entry))
    lines.append("</ul>")
    return "\n".join(lines)
