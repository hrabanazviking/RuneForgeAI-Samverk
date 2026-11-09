"""Star lists (S-233).

A user's stars browsable as a reading list; stars
are public signals and are labelled as such.
S-222 made the star itself -- one stored row per
(repository, account) in migration 86's
`repo_stars`, counted live, witnessed by
`repo.star` / `repo.unstar` only when a real
change happened -- and its store already answers
the plain question "what has this person
starred?" as bare names. This slice is the
browsable form of that answer: the reading list
a profile carries, one entry per star, each
entry saying what the repository is, when it
was starred, and how many stars it holds now.

- **A read model, not a second record.** The
  list is gathered at read time from S-222's
  rows and S-050's repository record; it stores
  nothing of its own. No migration -- schema 93
  stands. No new audit event -- 129 stand:
  browsing a list witnesses nothing, because
  the star itself was witnessed when it was
  made. Un-starring removes the entry, because
  the row is gone; re-starring is a new star
  with its own time and stands at the front.
- **Stars are public signals, labelled as
  such.** Every page and every entry says so
  in plain words (`STAR_SIGNAL_WORDS`): anyone
  who can read a repository can see who
  starred it. A star is a bookmark and a
  public signal in one act (S-222's law); the
  list never dresses it as a private note.
- **Privacy is S-209's rule, as everywhere.**
  An entry is shown exactly when the viewer
  may read the repository (S-054's `can_read`,
  reused through the same judgement S-222's
  own star list applies). A star on a private
  repository is as invisible as the repository
  itself: filtered rows contribute no entry,
  no name, and no count -- the list's total
  is the visible total, never the stored one.
- **Order is stated, never silent.** Most
  recently starred first -- the order a
  reading list grows in -- said in the list's
  own words (`STAR_LIST_SCOPE`) beside the
  count. Entry star counts are S-222's live
  `COUNT(*)` seam at read time, never cached.
- **A public profile fact.** Like S-232's
  follower lists, a star list is readable by
  anyone, anonymous visitors included, for
  exactly the entries they may read. An
  unknown subject is refused `no_such_user`
  on every face, and a refusal reads nothing.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

from .accounts import AccountStore, User
from .escaping import escape_html_text
from .permissions import can_read
from .repositories import RepositoryStore
from .watch_star import WatchStarStore

__all__ = [
    "STAR_LIST_SCOPE", "STAR_SIGNAL_LABEL",
    "STAR_SIGNAL_WORDS", "StarList", "StarListEntry",
    "StarListError", "StarListStore",
    "render_profile_stars_section",
    "render_star_list_entry", "render_star_list_page",
    "star_list_empty_words",
]

# The public-signal law, said once, in words, and
# printed on the page and in the empty state: the
# label is a standing fact of the model, not a
# warning invented per page.
STAR_SIGNAL_WORDS = (
    "Stars are public signals: anyone who can "
    "read a repository can see that a person "
    "starred it. A star is a bookmark and a "
    "public signal, never a private note.")

# The list's order, said once, in words, beside
# the public-signal law: the order is a labelled
# law, not a silent sort.
STAR_LIST_SCOPE = (
    "Most recently starred first. "
    + STAR_SIGNAL_WORDS)

# The label every entry carries.
STAR_SIGNAL_LABEL = "public signal"


class StarListError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class StarListEntry:
    """One star on the reading list: the
    repository as S-050 records it, the moment
    the star was made, and the repository's
    live star count at read time."""
    full_name: str
    owner: str
    name: str
    description: str
    visibility: str
    star_count: int          # live, counted rows
    starred_at: int          # the star row's own time

    @property
    def signal_label(self) -> str:
        return STAR_SIGNAL_LABEL

    @property
    def starred_words(self) -> str:
        return time.strftime(
            "%Y-%m-%d %H:%M UTC",
            time.gmtime(self.starred_at))

    @property
    def words(self) -> str:
        noun = "star" if self.star_count == 1 else "stars"
        desc = (f" — {self.description}"
                if self.description else "")
        return (f"{self.full_name}{desc} "
                f"({self.visibility} repository, "
                f"{self.star_count} {noun}, starred "
                f"{self.starred_words}, "
                f"{STAR_SIGNAL_LABEL})")


@dataclass(frozen=True)
class StarList:
    """One person's star reading list as one
    viewer sees it: the visible entries, most
    recently starred first, and the visible
    total -- filtered rows contribute no entry
    and no number, so the total is the visible
    total, never the stored one."""
    subject: str
    scope: str
    entries: tuple[StarListEntry, ...]
    total: int               # visible, before the cap

    @property
    def title(self) -> str:
        return f"Stars — {self.subject}"

    @property
    def count(self) -> int:
        return len(self.entries)

    @property
    def words(self) -> str:
        noun = ("repository" if self.total == 1
                else "repositories")
        shown = ("" if self.count == self.total else
                 f" Showing the {self.count} most recent.")
        return (f"{self.subject} has starred "
                f"{self.total} {noun}.{shown} "
                f"{self.scope}")


def star_list_empty_words(subject: str) -> str:
    """The honest empty state, in words: the
    list is empty for this viewer, and what a
    star is and does -- including that it is a
    public signal -- in one teaching sentence
    set."""
    return (
        f"{subject} has not starred any "
        "repository you can read yet. Starring a "
        "repository adds it to this reading list "
        "as a bookmark. " + STAR_SIGNAL_WORDS)


class StarListStore:
    """Star lists over S-222's `repo_stars` rows:
    a read model that stores nothing, gathers
    each entry from the repository record, and
    judges every row through S-054's `can_read`
    before any fact about it is read."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        watch_stars: WatchStarStore | None = None,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._stars = watch_stars or WatchStarStore(
            conn, repositories, accounts)

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
            raise StarListError(
                "no_such_user", "No such account.")
        return found

    # -- the list ------------------------------------
    @staticmethod
    def _clamp(limit: int) -> int:
        return max(1, min(int(limit), 500))

    def _visible_entries(
            self, viewer: User | None,
            person: User) -> list[StarListEntry]:
        """Every visible entry, most recently
        starred first: a row becomes an entry
        exactly when this viewer may read the
        repository it names."""
        rows = self._conn.execute(
            "SELECT repo_id, created_at FROM repo_stars"
            " WHERE user_id = ?"
            " ORDER BY created_at DESC, id DESC",
            (person.id,)).fetchall()
        entries: list[StarListEntry] = []
        for row in rows:
            repo = self._repos.get_by_id(int(row["repo_id"]))
            if repo is None or not can_read(viewer, repo):
                continue
            entries.append(StarListEntry(
                full_name=repo.full_name,
                owner=repo.owner, name=repo.name,
                description=repo.description,
                visibility=repo.visibility,
                star_count=self._stars.star_count(repo),
                starred_at=int(row["created_at"])))
        return entries

    def star_list(self, viewer: User | None,
                  subject: object, *, limit: int = 100
                  ) -> StarList:
        """The subject's star reading list as
        *viewer* sees it: a public profile fact,
        readable by anyone, anonymous included,
        for exactly the entries the viewer may
        read."""
        person = self._resolve_subject(subject)
        visible = self._visible_entries(viewer, person)
        return StarList(
            subject=person.username,
            scope=STAR_LIST_SCOPE,
            entries=tuple(
                visible[:self._clamp(limit)]),
            total=len(visible))

    def starred_count(self, viewer: User | None,
                      subject: object) -> int:
        """The visible total: how many of the
        subject's stars this viewer may read --
        filtered stars contribute no number."""
        person = self._resolve_subject(subject)
        return len(self._visible_entries(viewer, person))


# -- renders ---------------------------------------------------
def render_star_list_entry(entry: StarListEntry) -> str:
    """One reading-list entry: the repository,
    its description when it has one, and its
    standing in words -- visibility, live star
    count, when the star was made, and the
    public-signal label. Meaning never rides on
    an icon or a colour alone. Every value
    passes S-010's seam."""
    lines = ["<li>", f"<p>{escape_html_text(entry.words)}</p>", "</li>"]
    return "\n".join(lines)


def _render_star_list_body(star_list: StarList) -> list[str]:
    lines = [f"<p>{escape_html_text(star_list.words)}</p>"]
    if not star_list.entries:
        lines.append(
            "<p>" + escape_html_text(
                star_list_empty_words(star_list.subject))
            + "</p>")
        return lines
    lines.append("<ul>")
    for entry in star_list.entries:
        lines.append(render_star_list_entry(entry))
    lines.append("</ul>")
    return lines


def render_star_list_page(star_list: StarList) -> str:
    """The star list as a page: its title, its
    standing in one plain sentence set (visible
    count, order, and the public-signal law),
    then its entries -- or its honest empty
    state, which teaches the model."""
    lines = [f"<h1>{escape_html_text(star_list.title)}</h1>"]
    lines.extend(_render_star_list_body(star_list))
    return "\n".join(lines)


def render_profile_stars_section(star_list: StarList) -> str:
    """The star list as a profile page section:
    the same body under the profile's own
    heading, so a profile and the list page
    never tell two different stories."""
    lines = [
        '<section class="profile-stars">',
        f"<h2>{escape_html_text(star_list.title)}</h2>",
    ]
    lines.extend(_render_star_list_body(star_list))
    lines.append("</section>")
    return "\n".join(lines)
