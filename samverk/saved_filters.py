"""Saved filters (S-136).

Per-user saved searches for a repository's issues and
pull requests, shown in the sidebar.

- **A filter is a name plus an S-135 query.** The query
  is validated through S-135's parser at save time — a
  filter that cannot run is refused `query_invalid` at
  the door, never stored to fail later — and parsed
  again at run time through the same seam, so the
  grammar can never drift between saving and running.
- **Filters are personal.** A filter belongs to exactly
  one account: listing, running, renaming, and deleting
  all scope by the owner's account id, so one user's
  filters are invisible to another (there is no seam
  that lists anyone else's). Names are unique per user
  per repository, case-insensitively (`name_taken`).
- **Targets are issues or pull requests.** The `target`
  word (`issues` / `pull_requests`) is what the sidebar
  groups by; the query itself is S-135's language either
  way (Part VII's PR surfaces consume the pull-request
  filters; S-135's `is:issue` keeps an issues filter
  honest today).
- **Running follows S-054** through S-135's search: a
  saved filter grants no access — if its owner loses
  read access to the repository, running it gets the
  uniform not-found answer like any other read.
- **No audit event of its own.** A saved filter is a
  personal reading preference, like a browser bookmark;
  it mutates no shared record. (The S-127/S-131/S-135
  pattern for work that is not a witnessed act.)
- **The sidebar teaches.** `render_sidebar` groups the
  filters by target in plain words, each a link carrying
  the query URL-encoded, every name escaped through
  S-010; an account with no filters gets an empty state
  that says how to make one.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote

from .accounts import AccountStore, User
from .escaping import escape_html_attr, escape_html_text
from .issue_search import IssueSearch, SearchError, parse_query
from .issues import Issue
from .permissions import can_read
from .repositories import RepositoryStore

TARGETS = frozenset({"issues", "pull_requests"})
TARGET_WORDS = {"issues": "Issues", "pull_requests": "Pull requests"}
NAME_MAX = 50


class SavedFilterError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class SavedFilter:
    id: int
    user_id: int
    repo_id: int
    target: str          # 'issues' | 'pull_requests'
    name: str            # display case
    name_lower: str
    query: str
    created_at: int
    updated_at: int


def _row_to_filter(row: sqlite3.Row) -> SavedFilter:
    return SavedFilter(
        id=row["id"], user_id=row["user_id"], repo_id=row["repo_id"],
        target=row["target"], name=row["name"],
        name_lower=row["name_lower"], query=row["query"],
        created_at=row["created_at"], updated_at=row["updated_at"])


def _validate_name(name: object) -> str:
    if not isinstance(name, str) or not name.strip():
        raise SavedFilterError(
            "name_required", "A saved filter needs a name.")
    text = name.strip()
    if len(text) > NAME_MAX or any(
            ord(c) < 0x20 or ord(c) == 0x7F for c in text):
        raise SavedFilterError(
            "name_invalid",
            f"Filter names are at most {NAME_MAX} characters "
            "of plain text.")
    return text


def _validate_query(query: object) -> str:
    if not isinstance(query, str):
        raise SavedFilterError("query_invalid", "A search is text.")
    try:
        parse_query(query)
    except SearchError as exc:
        raise SavedFilterError("query_invalid", str(exc)) from None
    return query.strip()


class SavedFilterStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        search: IssueSearch,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._search = search
        self._now = time_fn

    def _repo_for_read(self, viewer: User | None, owner: object,
                       repo: object):
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise SavedFilterError(
                "repo_not_found", "No such repository.")
        return current

    def save_filter(self, actor: User, owner: object, repo: object,
                    name: object, query: object,
                    target: object = "issues") -> SavedFilter:
        current = self._repo_for_read(actor, owner, repo)
        if target not in TARGETS:
            raise SavedFilterError(
                "target_invalid",
                "A filter targets issues or pull_requests.")
        text = _validate_name(name)
        query_text = _validate_query(query)
        now = int(self._now())
        try:
            with self._conn:  # commits before the answer
                cur = self._conn.execute(
                    "INSERT INTO saved_filters (user_id, repo_id,"
                    " target, name, name_lower, query, created_at,"
                    " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (actor.id, current.id, target, text, text.lower(),
                     query_text, now, now))
        except sqlite3.IntegrityError:
            raise SavedFilterError(
                "name_taken",
                "You already have a filter with that name here.") from None
        saved = self._by_id(int(cur.lastrowid))
        assert saved is not None
        return saved

    def list_filters(self, actor: User, owner: object, repo: object,
                     target: object = None) -> list[SavedFilter]:
        current = self._repo_for_read(actor, owner, repo)
        sql = ("SELECT * FROM saved_filters WHERE user_id = ?"
               " AND repo_id = ?")
        params: list = [actor.id, current.id]
        if target is not None:
            if target not in TARGETS:
                raise SavedFilterError(
                    "target_invalid",
                    "A filter targets issues or pull_requests.")
            sql += " AND target = ?"
            params.append(target)
        sql += " ORDER BY name_lower"
        return [_row_to_filter(r) for r in
                self._conn.execute(sql, params).fetchall()]

    def get_filter(self, actor: User, owner: object, repo: object,
                   name: object) -> SavedFilter:
        current = self._repo_for_read(actor, owner, repo)
        row = self._conn.execute(
            "SELECT * FROM saved_filters WHERE user_id = ?"
            " AND repo_id = ? AND name_lower = ?",
            (actor.id, current.id,
             name.lower() if isinstance(name, str) else "")).fetchone()
        if row is None:
            raise SavedFilterError(
                "filter_not_found", "No such saved filter.")
        return _row_to_filter(row)

    def delete_filter(self, actor: User, owner: object, repo: object,
                      name: object) -> None:
        saved = self.get_filter(actor, owner, repo, name)
        with self._conn:
            self._conn.execute(
                "DELETE FROM saved_filters WHERE id = ?", (saved.id,))

    def run_filter(self, actor: User, owner: object, repo: object,
                   name: object) -> list[Issue]:
        saved = self.get_filter(actor, owner, repo, name)
        return self._search.search(actor, owner, repo, saved.query)

    def _by_id(self, filter_id: int) -> SavedFilter | None:
        row = self._conn.execute(
            "SELECT * FROM saved_filters WHERE id = ?",
            (filter_id,)).fetchone()
        return _row_to_filter(row) if row else None


def render_sidebar(owner: object, repo: object,
                   filters: list[SavedFilter]) -> str:
    """The sidebar block: filters grouped by target in
    plain words, each a link to its search, names escaped
    through S-010, and a teaching empty state."""
    parts = ['<nav class="saved-filters">', "<h2>Saved filters</h2>"]
    if not filters:
        parts.append(
            "<p>No saved filters yet. Run a search, then save "
            "it to see it here.</p>")
    for target in ("issues", "pull_requests"):
        group = [f for f in filters if f.target == target]
        if not group:
            continue
        parts.append(f"<h3>{TARGET_WORDS[target]}</h3>")
        parts.append("<ul>")
        for saved in group:
            href = (f"{target}?q="
                    + quote(saved.query, safe=""))
            parts.append(
                f'<li><a href="{escape_html_attr(href)}">'
                f"{escape_html_text(saved.name)}</a></li>")
        parts.append("</ul>")
    parts.append("</nav>")
    return "\n".join(parts)
