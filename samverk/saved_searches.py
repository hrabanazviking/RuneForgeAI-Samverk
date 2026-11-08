"""Saved searches (S-214).

Per-user saved searches for the global box — beyond
S-136's saved filters: any global query saved and
re-runnable.

- **Beyond S-136.** S-136 saves per-repository issue
  and pull-request filters in S-135's grammar, keyed
  by (user, repository). This store saves any S-213
  global query — free words plus `type:` groups
  across repositories, people, commits, code, and
  issues — under a name, per user, with no repository
  in the key: a global search has no home repository,
  so its saved form cannot have one either.
- **A saved search is a name plus a query.** The
  query is validated through S-213's parser
  (`parse_global_query`) at save time — a search
  that cannot run is refused `query_invalid` at the
  door, never stored to fail later: unparseable text,
  an empty search, a words-less `type:`-only search,
  and a selection naming no group all refuse here,
  exactly as `GlobalSearch.search` refuses them at
  run time — and the query is parsed again at run
  time through that same executor, so the grammar
  can never drift between saving and running. Only
  the query text is stored, trimmed as typed.
- **Personal, signed-in only.** A saved search
  belongs to exactly one account: saving, listing,
  getting, renaming, updating, deleting, and running
  all scope by the owner's account id, so one user's
  searches are invisible to another — there is no
  seam that names anyone else's, and another user's
  name answers `saved_not_found`, never a leak that
  the name exists. A missing account is refused
  `auth_required` on every face (the
  RecentSearchStore pattern). Names are unique per
  user, case-insensitively (`name_taken`).
- **Re-running is live, never cached.** No result
  is ever stored: `run_search` executes the saved
  query through S-213's `GlobalSearch` at run time,
  whose groups each filter through S-209's one
  resolution before any private fact is read. A
  saved search therefore grants no access — what
  the runner may read can change between saving and
  running, and the rerun answers for today, with
  today's permissions, never yesterday's snapshot.
- **A deliberate list, capped honestly.** A user
  holds at most `SAVED_LIMIT` (50) saved searches;
  the next save is refused `saved_limit_reached`.
  The cap refuses, never prunes: recent searches
  (S-213) are automatic and prune to 10, but a saved
  search is deliberate user data — it leaves only
  when its owner deletes it, and deleting one frees
  its slot. (S-136's filters are per-repository and
  uncapped; this store is global per user, so one
  cap keeps the one list findable.)
- **Rename and update are first-class.** Renaming
  keeps the query and the creation time; updating
  replaces the query, validated exactly as at save
  (a refused update leaves the stored query whole);
  both move `updated_at` and commit before the
  answer, like every house store.
- **No audit event of its own.** A saved search is
  a personal reading preference, like a browser
  bookmark (the S-136 pattern, kept by S-213's
  recents): persisting it is the feature, but it
  mutates no shared record, so it is not a witnessed
  act. 122 events stand: 31 auth / 79 repo / 12
  admin. Schema 83 to 84 is this slice's one
  migration, claimed here for `saved_searches`.
- **The list teaches.** `render_saved_searches`
  renders the owner's searches in name order, each
  a rerun link to the search page carrying the
  query, with the query said in words beside it,
  every value escaped through S-010; an empty list
  renders an empty state that says how to make one.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote_plus

from .accounts import User
from .escaping import escape_html_attr, escape_html_text
from .global_search import (
    DEFAULT_GROUP_LIMIT, GlobalSearch, GlobalSearchError,
    GlobalSearchResults, parse_global_query)
from .repo_search import SEARCH_PATH

__all__ = [
    "NAME_MAX", "SAVED_LIMIT", "SavedSearch", "SavedSearchError",
    "SavedSearchStore", "render_saved_searches",
]

NAME_MAX = 50
SAVED_LIMIT = 50


class SavedSearchError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class SavedSearch:
    """One saved search: its owner's account id, the
    name as typed (with its lowercased uniqueness
    key), the global query as typed (trimmed), and
    when it was saved and last changed. No results
    ride here — a rerun executes the query live."""
    id: int
    user_id: int
    name: str            # display case
    name_lower: str
    query: str
    created_at: int
    updated_at: int


def _row_to_saved(row: sqlite3.Row) -> SavedSearch:
    return SavedSearch(
        id=int(row["id"]), user_id=int(row["user_id"]),
        name=row["name"], name_lower=row["name_lower"],
        query=row["query"], created_at=int(row["created_at"]),
        updated_at=int(row["updated_at"]))


def _require_user(user: object) -> User:
    if not isinstance(user, User):
        raise SavedSearchError(
            "auth_required",
            "Saved searches belong to a signed-in account.")
    return user


def _validate_name(name: object) -> str:
    if not isinstance(name, str) or not name.strip():
        raise SavedSearchError(
            "name_required", "A saved search needs a name.")
    text = name.strip()
    if len(text) > NAME_MAX or any(
            ord(c) < 0x20 or ord(c) == 0x7F for c in text):
        raise SavedSearchError(
            "name_invalid",
            f"Saved search names are at most {NAME_MAX} "
            "characters of plain text.")
    return text


def _validate_query(query: object) -> str:
    """One global query, judged as savable: S-213's
    parser is the seam, and the search must be one
    `GlobalSearch.search` would run — non-empty,
    carrying words, naming at least one group.
    Returns the query trimmed, as typed."""
    if not isinstance(query, str):
        raise SavedSearchError(
            "query_invalid", "A search is text.")
    try:
        parsed = parse_global_query(query)
    except GlobalSearchError as exc:
        raise SavedSearchError(
            "query_invalid", str(exc)) from None
    if parsed.is_empty:
        raise SavedSearchError(
            "query_invalid",
            "A saved search needs a search to save.")
    if not parsed.terms:
        raise SavedSearchError(
            "query_invalid",
            "A global search needs words to hunt for.")
    if not parsed.groups:
        raise SavedSearchError(
            "query_invalid",
            "That search names no result group.")
    return parsed.raw


class SavedSearchStore:
    """Per-user saved global searches over migration
    84. Every face scopes by the owner's account id;
    writes are commit-before-answer, like every house
    store. The executor is S-213's `GlobalSearch`,
    consulted only at run time."""

    def __init__(self, conn: sqlite3.Connection,
                 search: GlobalSearch,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._search = search
        self._now = time_fn

    def save_search(self, actor: object, name: object,
                    query: object) -> SavedSearch:
        """Save *query* for *actor* under *name*. The
        name must be free for this user (`name_taken`)
        and the user's list must hold a slot
        (`saved_limit_reached`); the query must be a
        runnable global search (`query_invalid`)."""
        owner = _require_user(actor)
        text = _validate_name(name)
        query_text = _validate_query(query)
        if self._count(owner.id) >= SAVED_LIMIT:
            raise SavedSearchError(
                "saved_limit_reached",
                f"You already hold {SAVED_LIMIT} saved "
                "searches. Delete one to save another.")
        now = int(self._now())
        try:
            with self._conn:  # commits before the answer
                cur = self._conn.execute(
                    "INSERT INTO saved_searches (user_id,"
                    " name, name_lower, query, created_at,"
                    " updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (owner.id, text, text.lower(), query_text,
                     now, now))
        except sqlite3.IntegrityError:
            raise SavedSearchError(
                "name_taken",
                "You already have a saved search with "
                "that name.") from None
        saved = self._by_id(int(cur.lastrowid))
        assert saved is not None
        return saved

    def list_searches(self, actor: object) -> list[SavedSearch]:
        """*actor*'s saved searches, in name order.
        Only the owner's rows can ever be named here:
        the account id is the query's first term."""
        owner = _require_user(actor)
        return [_row_to_saved(r) for r in self._conn.execute(
            "SELECT * FROM saved_searches WHERE user_id = ?"
            " ORDER BY name_lower", (owner.id,)).fetchall()]

    def get_search(self, actor: object,
                   name: object) -> SavedSearch:
        """One of *actor*'s saved searches, by name
        (case-insensitively). A name this user never
        saved — including one only another user holds
        — is `saved_not_found`."""
        owner = _require_user(actor)
        row = self._conn.execute(
            "SELECT * FROM saved_searches WHERE user_id = ?"
            " AND name_lower = ?",
            (owner.id,
             name.strip().lower() if isinstance(name, str)
             else "")).fetchone()
        if row is None:
            raise SavedSearchError(
                "saved_not_found", "No such saved search.")
        return _row_to_saved(row)

    def rename_search(self, actor: object, name: object,
                      new_name: object) -> SavedSearch:
        """Rename one of *actor*'s saved searches: the
        query and the creation time stand, the display
        name and `updated_at` move. A name another of
        the user's searches holds is `name_taken`."""
        owner = _require_user(actor)
        saved = self.get_search(owner, name)
        text = _validate_name(new_name)
        try:
            with self._conn:  # commits before the answer
                self._conn.execute(
                    "UPDATE saved_searches SET name = ?,"
                    " name_lower = ?, updated_at = ?"
                    " WHERE id = ?",
                    (text, text.lower(), int(self._now()),
                     saved.id))
        except sqlite3.IntegrityError:
            raise SavedSearchError(
                "name_taken",
                "You already have a saved search with "
                "that name.") from None
        renamed = self._by_id(saved.id)
        assert renamed is not None
        return renamed

    def update_search(self, actor: object, name: object,
                      query: object) -> SavedSearch:
        """Replace the query one of *actor*'s saved
        searches runs, validated exactly as at save:
        a refused update leaves the stored query
        whole. The name and creation time stand."""
        owner = _require_user(actor)
        saved = self.get_search(owner, name)
        query_text = _validate_query(query)
        with self._conn:  # commits before the answer
            self._conn.execute(
                "UPDATE saved_searches SET query = ?,"
                " updated_at = ? WHERE id = ?",
                (query_text, int(self._now()), saved.id))
        updated = self._by_id(saved.id)
        assert updated is not None
        return updated

    def delete_search(self, actor: object,
                      name: object) -> None:
        """Forget one of *actor*'s saved searches —
        and only theirs. Deleting frees its slot under
        the cap."""
        owner = _require_user(actor)
        saved = self.get_search(owner, name)
        with self._conn:
            self._conn.execute(
                "DELETE FROM saved_searches WHERE id = ?",
                (saved.id,))

    def run_search(self, actor: object, name: object, *,
                   per_group_limit: int = DEFAULT_GROUP_LIMIT,
                   ) -> GlobalSearchResults:
        """Re-run one of *actor*'s saved searches,
        live: the stored query text goes through
        S-213's `GlobalSearch` as *actor*, so every
        group filters through S-209 at run time and
        the answer is today's, never a stored one.
        The executor's refusals surface by name."""
        owner = _require_user(actor)
        saved = self.get_search(owner, name)
        try:
            return self._search.search(
                owner, saved.query,
                per_group_limit=per_group_limit)
        except GlobalSearchError as exc:
            raise SavedSearchError(
                exc.reason, str(exc)) from None

    def _count(self, user_id: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM saved_searches"
            " WHERE user_id = ?", (user_id,)).fetchone()
        return int(row["n"])

    def _by_id(self, saved_id: int) -> SavedSearch | None:
        row = self._conn.execute(
            "SELECT * FROM saved_searches WHERE id = ?",
            (saved_id,)).fetchone()
        return _row_to_saved(row) if row else None


def render_saved_searches(searches: list[SavedSearch]) -> str:
    """The saved-searches block: the owner's searches
    in the order given (the store lists in name
    order), each a rerun link to the search page
    carrying its query, the query said in words
    beside it, every value escaped through S-010.
    An empty list renders the honest empty state."""
    parts = ['<nav class="saved-searches">',
             "<h2>Saved searches</h2>"]
    if not searches:
        parts.append(
            "<p>No saved searches yet. Run a search, then "
            "save it to run it again from here.</p>")
        parts.append("</nav>")
        return "\n".join(parts)
    parts.append("<ul>")
    for saved in searches:
        href = (f"{SEARCH_PATH}?q="
                + quote_plus(saved.query))
        parts.append(
            f'<li><a href="{escape_html_attr(href)}">'
            f"{escape_html_text(saved.name)}</a> — "
            f"{escape_html_text(saved.query)}</li>")
    parts.append("</ul>")
    parts.append("</nav>")
    return "\n".join(parts)
