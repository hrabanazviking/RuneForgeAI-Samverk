"""Global search UI (S-213).

One box, typed result groups, keyboard-first, recent
searches per user — Part X's front door, over the
five faces the part already built: S-210's repository
search, S-211's user and org search, S-212's commit
search, S-208's code search, and S-206's issue/PR
backend. S-118's repository search box has pointed at
this page (`/search`) since it landed; this slice is
the page it points at.

- **One box, one small grammar.** A global query is
  free-text terms (a double-quoted phrase is one term)
  plus `type:` qualifiers naming the result groups to
  search — `repositories`, `people`, `commits`,
  `code`, `issues`, with the alias spellings each
  group's own page teaches (`repo`, `users`, `orgs`,
  `pr`, …). A leading `-` negates one `type:`
  qualifier; an explicit `types=` argument replaces
  the text's selection. That is the whole global
  grammar, on purpose: the qualifiers of the group
  grammars (`author:`, `label:`, `path:`, …) are not
  global qualifiers, and a token shaped like an
  unknown qualifier is refused `query_invalid`,
  naming it — never silently dropped, because a
  dropped qualifier widens the search (the S-118
  law), and never folded into the free text of a
  group whose grammar would read it differently.
- **Fan-out hands each group plain words only.**
  Each backend receives the free-text terms and
  nothing else — phrases re-quoted for the substring
  and FTS backends, the bare joined words as the
  code pattern — so no group's grammar can leak
  into another group's results. Each group is
  executed by its own banked executor, which
  resolves the viewer's visible repositories
  through S-209's one resolution (over S-054's
  `can_read`) before any private fact is read:
  this module reads no repository, profile, index,
  or history row itself, and adds no filtering of
  its own that could drift from the groups' law.
- **Counts are per group, never mixed.** Every
  group carries its own executor's S-209 total,
  tallied over that group's filtered hits before
  the per-group cap (default 10, at most 100, so a
  page shows a handful of each kind with its true
  count beside it). There is deliberately no
  combined total anywhere in this module: a number
  summed across groups would mix counts kept
  behind different permission boundaries, and the
  page states each group's law in that group's own
  words instead.
- **An empty search is the landing, honestly.**
  No terms and no qualifiers is not a search: it
  fans out nowhere, records nothing, and renders
  as the page with the box, the searcher's recent
  searches, and the keyboard help. A query carrying
  only `type:` qualifiers — groups but no words —
  is refused `query_invalid`, exactly as S-208 and
  S-212 refuse a search with nothing to hunt for.
- **Keyboard-first is rendered from the law.**
  The page's focus order is data here
  (`keyboard_focus_order`): the search box first
  (it carries `autofocus`, and S-111's `/` returns
  to it from anywhere), then the recent searches,
  then one skip link per group in the fixed group
  order, then each group's results in that same
  order. The Keyboard section of the page is
  rendered from S-111's registry itself, so it
  cannot promise a binding the registry does not
  hold, and the page ships no inline script
  (S-111's law). Group sections carry
  `tabindex="-1"` ids so the skip links land focus
  where they point.
- **Recent searches are personal, like S-136's
  filters.** Migration 83's `recent_searches`
  holds one row per (user, query): recording a
  search the user already made moves it to the
  front (the dedup key is the trimmed, lowercased
  text; the display keeps the latest typed case),
  the list is most-recent first, and each user's
  list is capped at `RECENT_LIMIT` rows, pruned
  on record. Every face scopes by the owner's
  account id — there is no seam that lists, removes,
  or clears another user's recents — and anonymous
  searching records nothing: the store refuses a
  missing account `auth_required`, and
  `GlobalSearch.search` records only for a
  signed-in viewer, only after a successful
  non-empty search. One recent can be removed and
  the whole list cleared, by its owner alone.
- **No audit event of its own.** Searching is a
  read, and a recent search is a personal reading
  preference, like a browser bookmark (the S-136
  pattern). 122 events stand: 31 auth / 79 repo /
  12 admin. Schema 82 to 83 is this slice's one
  migration, claimed here for `recent_searches`.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote_plus

from .accounts import User
from .code_search import CodeSearch, CodeSearchError
from .commit_search import CommitSearch, CommitSearchError
from .escaping import escape_html_attr, escape_html_text
from .issue_pr_search import IssuePRSearch, SearchBackendError
from .keyboard import shortcuts_for
from .organizations import OrganizationStore
from .repo_search import SEARCH_PATH
from .repositories import RepositoryStore
from .repository_search import RepositorySearch, RepositorySearchError
from .user_org_search import PeopleSearch, PeopleSearchError

__all__ = [
    "DEFAULT_GROUP_LIMIT", "GROUP_ORDER", "GROUP_WORDS", "MAX_GROUP_LIMIT",
    "QUERY_MAX", "RECENT_LIMIT", "TYPE_ALIASES", "GlobalSearch",
    "GlobalSearchError", "GlobalSearchQuery", "GlobalSearchResults",
    "GroupResults", "RecentSearch", "RecentSearchStore",
    "keyboard_focus_order", "parse_global_query",
    "render_global_search_box", "render_global_search_page",
    "render_recent_searches",
]

QUERY_MAX = 500
DEFAULT_GROUP_LIMIT = 10
MAX_GROUP_LIMIT = 100
RECENT_LIMIT = 10

GROUP_ORDER: tuple[str, ...] = (
    "repositories", "people", "commits", "code", "issues")
GROUP_WORDS = {
    "repositories": "Repositories",
    "people": "People and organizations",
    "commits": "Commits",
    "code": "Code",
    "issues": "Issues and pull requests",
}
TYPE_ALIASES = {
    "repositories": "repositories", "repository": "repositories",
    "repos": "repositories", "repo": "repositories",
    "people": "people", "person": "people", "users": "people",
    "user": "people", "orgs": "people", "org": "people",
    "organizations": "people", "organization": "people",
    "commits": "commits", "commit": "commits",
    "code": "code",
    "issues": "issues", "issue": "issues", "prs": "issues",
    "pr": "issues", "pulls": "issues",
}
QUALIFIER_NAMES = frozenset({"type"})

# What each group promises about its count, in its own
# words — the S-209 law said per group, never merged.
_GROUP_COUNT_LAW = {
    "repositories": "only repositories you can read are counted",
    "people": "only people and organizations you may see are counted",
    "commits": "only commits in repositories you can read are counted",
    "code": "only code in repositories you can read is counted",
    "issues": ("only issues and pull requests in repositories "
               "you can read are counted"),
}


class GlobalSearchError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def _invalid(message: str) -> GlobalSearchError:
    return GlobalSearchError("query_invalid", message)


# ------------------------------------------------------------------
# The parsed query
# ------------------------------------------------------------------

@dataclass(frozen=True)
class GlobalSearchQuery:
    """One global search, whole: the free-text terms
    (lowercased, in order; a quoted phrase is one term
    and keeps its spaces), the result groups the
    `type:` qualifiers named and negated (canonical
    names), and the search as typed (trimmed)."""
    terms: tuple[str, ...] = ()
    types: tuple[str, ...] = ()
    not_types: tuple[str, ...] = ()
    raw: str = ""

    @property
    def is_empty(self) -> bool:
        """True when the query carries no term and no
        qualifier — the landing state, not a search."""
        return not (self.terms or self.types or self.not_types)

    @property
    def groups(self) -> tuple[str, ...]:
        """The groups this search runs, in the fixed
        group order: the positively named groups, or
        every group when none is named, minus the
        negated ones."""
        base = self.types if self.types else GROUP_ORDER
        return tuple(g for g in GROUP_ORDER
                     if g in base and g not in self.not_types)


def _tokenise(query: str) -> list[str]:
    """Split a query line into tokens: whitespace
    separates, a double-quoted span stays inside its
    token (so `"my project"` is one term and
    `type:"two words"` would be one qualifier). An
    unterminated quote is `query_invalid`."""
    tokens: list[str] = []
    i, n = 0, len(query)
    while i < n:
        while i < n and query[i].isspace():
            i += 1
        if i >= n:
            break
        buf: list[str] = []
        while i < n and not query[i].isspace():
            if query[i] == '"':
                end = query.find('"', i + 1)
                if end == -1:
                    raise _invalid(
                        "A quoted value needs its closing quote.")
                buf.append(query[i + 1:end])
                i = end + 1
            else:
                buf.append(query[i])
                i += 1
        tokens.append("".join(buf))
    return tokens


def _check_type(value: object) -> str:
    if not isinstance(value, str) \
            or value.strip().lower() not in TYPE_ALIASES:
        raise _invalid(
            "The type: qualifier names a result group: "
            "repositories, people, commits, code, or issues.")
    return TYPE_ALIASES[value.strip().lower()]


def parse_global_query(query: object) -> GlobalSearchQuery:
    """Parse query text into a `GlobalSearchQuery`:
    `type:` qualifiers are lifted out (a leading `-`
    negates one), and the remaining tokens, in order,
    are the free-text terms. An unknown
    qualifier-shaped token, an empty or unknown type
    value, a negated free word, an unterminated quote,
    a control character, or an over-long query is
    refused `query_invalid`, naming the problem."""
    if query is None:
        query = ""
    if not isinstance(query, str):
        raise _invalid("A search is text.")
    if len(query) > QUERY_MAX:
        raise _invalid(
            f"A search is at most {QUERY_MAX} characters.")
    if any((ord(c) < 0x20 and c != "\t") or ord(c) == 0x7F
           for c in query):
        raise _invalid("A search carries no control characters.")
    terms: list[str] = []
    types: list[str] = []
    not_types: list[str] = []
    for token in _tokenise(query):
        negated = token.startswith("-") and len(token) > 1
        body = token[1:] if negated else token
        head, colon, value = body.partition(":")
        if colon and head.lower() in QUALIFIER_NAMES:
            if not value:
                raise _invalid("The type: qualifier needs a value.")
            (not_types if negated else types).append(
                _check_type(value))
            continue
        if colon and head and all(
                c.isalnum() or c in "_-" for c in head):
            raise _invalid(
                f"The qualifier {head!r} is not part of global "
                "search. The global grammar is free words plus "
                "type: (repositories, people, commits, code, "
                "issues); each group's own page keeps its full "
                "grammar.")
        if negated:
            raise _invalid(
                "Only a type: qualifier can be negated.")
        if token:
            terms.append(token.lower())
    return GlobalSearchQuery(
        terms=tuple(terms), types=tuple(types),
        not_types=tuple(not_types), raw=query.strip())


def _terms_text(parsed: GlobalSearchQuery) -> str:
    """The free-text terms as one query line for a
    substring or FTS backend: a term carrying spaces
    (a quoted phrase) is re-quoted, so the phrase
    stays one term in the group's own grammar."""
    return " ".join(
        f'"{term}"' if " " in term else term
        for term in parsed.terms)


def _pattern_text(parsed: GlobalSearchQuery) -> str:
    """The free-text terms as a code-search pattern:
    the bare words joined — quote characters are the
    global grammar's phrase marks, never pattern
    bytes."""
    return " ".join(parsed.terms)


def _check_group_limit(limit: object) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool) \
            or limit < 1 or limit > MAX_GROUP_LIMIT:
        raise _invalid(
            f"The per-group limit is 1 to {MAX_GROUP_LIMIT} results.")
    return limit


# ------------------------------------------------------------------
# Recent searches (migration 83)
# ------------------------------------------------------------------

@dataclass(frozen=True)
class RecentSearch:
    """One remembered search: the query as typed
    (display case), its dedup key, and when it was
    last searched."""
    user_id: int
    query: str
    query_lower: str
    searched_at: int


def _row_to_recent(row: sqlite3.Row) -> RecentSearch:
    return RecentSearch(
        user_id=int(row["user_id"]), query=row["query"],
        query_lower=row["query_lower"],
        searched_at=int(row["searched_at"]))


def _clean_recent_query(query: object) -> tuple[str, str]:
    """One recent-search query, judged: text, trimmed,
    non-empty, within the global query's own limits.
    Returns (display text, dedup key)."""
    if not isinstance(query, str):
        raise _invalid("A search is text.")
    text = query.strip()
    if not text:
        raise _invalid("A recent search needs the search text.")
    if len(text) > QUERY_MAX:
        raise _invalid(
            f"A search is at most {QUERY_MAX} characters.")
    if any((ord(c) < 0x20 and c != "\t") or ord(c) == 0x7F
           for c in text):
        raise _invalid("A search carries no control characters.")
    return text, text.lower()


def _require_user(user: object) -> User:
    if not isinstance(user, User):
        raise GlobalSearchError(
            "auth_required",
            "Recent searches belong to a signed-in account.")
    return user


class RecentSearchStore:
    """Per-user recent searches over migration 83.
    Every face scopes by the owner's account id;
    listing is most-recent first; recording is
    commit-before-answer, like every house store."""

    def __init__(self, conn: sqlite3.Connection,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._now = time_fn

    def record(self, user: object, query: object) -> RecentSearch:
        """Remember *query* for *user*: a query the
        user already made moves to the front with its
        latest typed case, and the list is pruned to
        `RECENT_LIMIT` rows in the same transaction."""
        owner = _require_user(user)
        text, key = _clean_recent_query(query)
        now = int(self._now())
        with self._conn:  # commits before the answer
            self._conn.execute(
                "DELETE FROM recent_searches"
                " WHERE user_id = ? AND query_lower = ?",
                (owner.id, key))
            self._conn.execute(
                "INSERT INTO recent_searches"
                " (user_id, query, query_lower, searched_at)"
                " VALUES (?, ?, ?, ?)",
                (owner.id, text, key, now))
            self._conn.execute(
                "DELETE FROM recent_searches WHERE user_id = ?"
                " AND id NOT IN (SELECT id FROM recent_searches"
                " WHERE user_id = ? ORDER BY searched_at DESC,"
                " id DESC LIMIT ?)",
                (owner.id, owner.id, RECENT_LIMIT))
        saved = self._by_key(owner.id, key)
        assert saved is not None
        return saved

    def list_recent(self, user: object, *,
                    limit: int = RECENT_LIMIT) -> list[RecentSearch]:
        """*user*'s recent searches, most-recent first.
        Only the owner's rows can ever be named here:
        the account id is the query's first term."""
        owner = _require_user(user)
        if not isinstance(limit, int) or isinstance(limit, bool) \
                or limit < 1 or limit > RECENT_LIMIT:
            raise _invalid(
                f"The recent list is 1 to {RECENT_LIMIT} searches.")
        return [_row_to_recent(r) for r in self._conn.execute(
            "SELECT * FROM recent_searches WHERE user_id = ?"
            " ORDER BY searched_at DESC, id DESC LIMIT ?",
            (owner.id, limit)).fetchall()]

    def remove(self, user: object, query: object) -> None:
        """Forget one of *user*'s recent searches, by
        its text (case-insensitively). A query the user
        never made is `recent_not_found`."""
        owner = _require_user(user)
        _, key = _clean_recent_query(query)
        if self._by_key(owner.id, key) is None:
            raise GlobalSearchError(
                "recent_not_found", "No such recent search.")
        with self._conn:
            self._conn.execute(
                "DELETE FROM recent_searches"
                " WHERE user_id = ? AND query_lower = ?",
                (owner.id, key))

    def clear(self, user: object) -> None:
        """Forget all of *user*'s recent searches —
        and only theirs."""
        owner = _require_user(user)
        with self._conn:
            self._conn.execute(
                "DELETE FROM recent_searches WHERE user_id = ?",
                (owner.id,))

    def _by_key(self, user_id: int, key: str) -> RecentSearch | None:
        row = self._conn.execute(
            "SELECT * FROM recent_searches"
            " WHERE user_id = ? AND query_lower = ?",
            (user_id, key)).fetchone()
        return _row_to_recent(row) if row else None


# ------------------------------------------------------------------
# Results and the executor
# ------------------------------------------------------------------

@dataclass(frozen=True)
class GroupResults:
    """One typed group's answer: its kind, the hits a
    page shows (capped per group), and the group's own
    filtered total tallied before the cap. The code
    group additionally carries its S-209 match totals.
    Totals are never summed across groups."""
    kind: str
    hits: tuple
    total: int
    total_matches: int = 0
    total_matched_lines: int = 0


@dataclass(frozen=True)
class GlobalSearchResults:
    """One global search: the query as typed, its
    parsed form, and one `GroupResults` per group
    searched, in the fixed group order. An empty
    query carries no groups — the landing state."""
    query: str
    parsed: GlobalSearchQuery
    groups: tuple[GroupResults, ...] = ()

    def group(self, kind: str) -> GroupResults | None:
        for current in self.groups:
            if current.kind == kind:
                return current
        return None

    @property
    def kinds(self) -> tuple[str, ...]:
        return tuple(g.kind for g in self.groups)


_BACKEND_ERRORS = (RepositorySearchError, PeopleSearchError,
                   CommitSearchError, CodeSearchError,
                   SearchBackendError)


class GlobalSearch:
    """The S-213 executor. It owns no index and reads
    no repository, profile, or history row: it parses
    the global grammar, hands each selected group its
    plain words through that group's own banked
    executor (each of which filters through S-209
    before reading anything private), and — for a
    signed-in viewer with a recent store configured —
    remembers the search after it succeeds."""

    def __init__(self, conn: sqlite3.Connection,
                 repositories: RepositoryStore,
                 organizations: OrganizationStore,
                 recents: RecentSearchStore | None = None):
        self._conn = conn
        self._recents = recents
        self._repositories = RepositorySearch(conn, repositories)
        self._people = PeopleSearch(conn, organizations)
        self._commits = CommitSearch(conn, repositories)
        self._code = CodeSearch(conn, repositories)
        self._issues = IssuePRSearch(conn, repositories)

    def search(self, viewer: User | None, query: object = "", *,
               types: object = None,
               per_group_limit: int = DEFAULT_GROUP_LIMIT,
               ) -> GlobalSearchResults:
        """Execute one global search. *types*, when
        given, is an iterable of group names or aliases
        replacing the text's `type:` selection. An
        empty query is the landing state: no group is
        searched and nothing is recorded. A words-less
        non-empty query, a selection naming no group,
        and a bad per-group limit are `query_invalid`."""
        parsed = parse_global_query(query)
        _check_group_limit(per_group_limit)
        selected = parsed.groups
        if types is not None:
            try:
                wanted = tuple(_check_type(t) for t in types)
            except TypeError:
                raise _invalid(
                    "The types are group names: repositories, "
                    "people, commits, code, or issues.") from None
            if not wanted:
                raise _invalid(
                    "That search names no result group.")
            selected = tuple(
                g for g in GROUP_ORDER if g in wanted)
        if parsed.is_empty and types is None:
            return GlobalSearchResults(
                query="", parsed=parsed, groups=())
        if not parsed.terms:
            raise _invalid(
                "A global search needs words to hunt for.")
        if not selected:
            raise _invalid("That search names no result group.")
        text = _terms_text(parsed)
        pattern = _pattern_text(parsed)
        groups: list[GroupResults] = []
        try:
            for kind in selected:
                groups.append(self._run_group(
                    kind, viewer, text, pattern, per_group_limit))
        except _BACKEND_ERRORS as exc:
            raise GlobalSearchError(
                getattr(exc, "reason", "query_invalid"),
                str(exc)) from None
        results = GlobalSearchResults(
            query=parsed.raw, parsed=parsed, groups=tuple(groups))
        if self._recents is not None and viewer is not None:
            self._recents.record(viewer, parsed.raw)
        return results

    def _run_group(self, kind: str, viewer: User | None,
                   text: str, pattern: str,
                   limit: int) -> GroupResults:
        if kind == "repositories":
            found = self._repositories.search_counted(
                viewer, text, limit=limit)
            return GroupResults(
                kind=kind, hits=found.hits, total=found.total)
        if kind == "people":
            found = self._people.search_counted(
                viewer, text, limit=limit)
            return GroupResults(
                kind=kind, hits=found.hits, total=found.total)
        if kind == "commits":
            found = self._commits.search_counted(
                viewer, text, limit=limit)
            return GroupResults(
                kind=kind, hits=found.hits, total=found.total)
        if kind == "code":
            found = self._code.search_counted(
                viewer, pattern, limit=limit)
            return GroupResults(
                kind=kind, hits=found.hits, total=found.total_files,
                total_matches=found.total_matches,
                total_matched_lines=found.total_matched_lines)
        found = self._issues.search_counted(viewer, text)
        return GroupResults(
            kind=kind, hits=tuple(found.hits[:limit]),
            total=found.total)


# ------------------------------------------------------------------
# Keyboard law and pages
# ------------------------------------------------------------------

def keyboard_focus_order(
        groups: tuple[str, ...] = GROUP_ORDER,
        *, has_recents: bool = False) -> tuple[str, ...]:
    """The page's documented focus order, as data: the
    search box first, then the recent searches when
    the page carries them, then the group skip links
    and group sections in the fixed group order. The
    rendered page follows this order exactly, and the
    battery proves the two agree."""
    order = ["search-box"]
    if has_recents:
        order.append("recent-searches")
    order.extend(f"group-{kind}" for kind in groups)
    return tuple(order)


def render_global_search_box(query: object = "") -> str:
    """The one box: a labelled GET form to the search
    page (S-118's contract), the input carrying
    `autofocus` so the keyboard starts where the
    search starts, and the way back to it said in
    words. Every value escaped through S-010."""
    query_text = query if isinstance(query, str) else ""
    return "\n".join([
        f'<form method="get" action="{escape_html_attr(SEARCH_PATH)}" '
        'role="search">',
        '<label for="q">Search everything</label>',
        f'<input id="q" name="q" type="search" autofocus '
        f'value="{escape_html_attr(query_text)}">',
        '<button type="submit">Search</button>',
        "<p>Type words to search repositories, people and "
        "organizations, commits, code, and issues and pull "
        "requests together — or add type:repositories, "
        "type:people, type:commits, type:code, or type:issues "
        "to search one kind. Press <kbd>/</kbd> from anywhere "
        "on the page to come back to this box.</p>",
        "</form>",
    ])


def render_recent_searches(recents: list[RecentSearch]) -> str:
    """The recent-searches block: the searcher's own
    latest searches, most-recent first, each a link
    that reruns it (S-136's sidebar shape). An empty
    list renders the honest empty state. Every query
    escaped through S-010, in text and in the link."""
    parts = ['<nav class="recent-searches" id="recent-searches">',
             "<h2>Recent searches</h2>"]
    if not recents:
        parts.append(
            "<p>No recent searches yet. Searches you run while "
            "signed in will appear here, newest first.</p>")
        parts.append("</nav>")
        return "\n".join(parts)
    parts.append("<ul>")
    for recent in recents:
        href = (f"{SEARCH_PATH}?q="
                + quote_plus(recent.query))
        parts.append(
            f'<li><a href="{escape_html_attr(href)}">'
            f"{escape_html_text(recent.query)}</a></li>")
    parts.append("</ul>")
    parts.append("</nav>")
    return "\n".join(parts)


def _keyboard_section(groups: tuple[str, ...]) -> str:
    """The Keyboard section: the page's focus order in
    words, then S-111's global bindings rendered from
    the registry itself — the section cannot promise
    a binding the registry does not hold."""
    words = {
        "search-box": "the search box",
        "recent-searches": "your recent searches",
    }
    steps = []
    for target in keyboard_focus_order(groups):
        label = words.get(
            target, f"the {GROUP_WORDS.get(target[6:], target)} "
                    "results")
        steps.append(label)
    parts = [
        '<section class="keyboard-help">',
        "<h2>Keyboard</h2>",
        "<p>This page is keyboard-first. Tab moves in this "
        "order: " + escape_html_text(", then ".join(steps))
        + ". The group links below jump straight to a "
        "group's results.</p>",
        '<ul class="shortcuts">',
    ]
    for shortcut in shortcuts_for("global"):
        keys_html = " then ".join(
            f"<kbd>{escape_html_text(k)}</kbd>"
            for k in shortcut.keys.split(" "))
        parts.append(
            f"<li>{keys_html} — "
            f"{escape_html_text(shortcut.description)}</li>")
    parts.append("</ul>")
    parts.append("</section>")
    return "\n".join(parts)


def _repo_line(hit) -> str:
    from .repository_search import visibility_word
    words = [f"{hit.full_name} — {visibility_word(hit.visibility)}"]
    if hit.description:
        words.append(hit.description)
    if hit.topics:
        words.append("Topics: " + ", ".join(hit.topics))
    if hit.matched_fields:
        words.append("Matched in: " + ", ".join(hit.matched_fields))
    return f"<li>{escape_html_text(' — '.join(words))}</li>"


def _commit_line(hit) -> str:
    when = time.strftime("%Y-%m-%d %H:%M UTC",
                         time.gmtime(hit.author_time))
    words = [f"{hit.full_name} — {hit.subject}",
             f"by {hit.author_name} <{hit.author_email}>", when]
    if hit.matched_fields:
        words.append("Matched in: " + ", ".join(hit.matched_fields))
    return f"<li>{escape_html_text(' — '.join(words))}</li>"


def _code_lines(hit) -> list[str]:
    words = (f"{hit.match_count} matches on "
             f"{hit.matched_lines} lines")
    if hit.is_pointer:
        words += " — LFS pointer (the pointer text itself)"
    lines = [
        f"<li><p>{escape_html_text(hit.full_name)} "
        f"{escape_html_text(hit.path)} — "
        f"{escape_html_text(hit.language)} — "
        f"{escape_html_text(words)}</p>"]
    for snippet in hit.snippets:
        lines.append('<pre class="snippet">')
        for line in snippet.lines:
            flag = "matched line" if line.is_match else "context"
            lines.append(
                f"{line.number}: [{flag}] "
                f"{escape_html_text(line.text)}")
        lines.append("</pre>")
    lines.append("</li>")
    return lines


def _issue_line(hit) -> str:
    return (
        f"<li>{escape_html_text(hit.full_name)} "
        f"#{hit.number} {escape_html_text(hit.title)} — "
        f"{escape_html_text(hit.state_words)}</li>")


def _group_section(group: GroupResults) -> str:
    """One typed group, whole: its heading, its own
    count with its own permission law in words, the
    shown-of-total note when the cap bit, and its
    hits — repositories, commits, code, and issues
    as lines in their own pages' wording, people as
    S-211's profile cards. Every value escaped
    through S-010."""
    kind = group.kind
    parts = [
        f'<section class="search-group" id="group-{kind}" '
        'tabindex="-1">',
        f"<h2>{escape_html_text(GROUP_WORDS[kind])}</h2>",
    ]
    if kind == "code":
        parts.append(
            f"<p>{group.total} "
            f"{'file matches' if group.total == 1 else 'files match'}"
            f" ({group.total_matches} matches on "
            f"{group.total_matched_lines} lines) — "
            f"{_GROUP_COUNT_LAW[kind]}.</p>")
    else:
        noun = {"repositories": ("repository matches",
                                 "repositories match"),
                "people": ("match", "matches"),
                "commits": ("commit matches", "commits match"),
                "issues": ("item matches", "items match")}[kind]
        parts.append(
            f"<p>{group.total} "
            f"{noun[0] if group.total == 1 else noun[1]}"
            f" — {_GROUP_COUNT_LAW[kind]}.</p>")
    if group.total > len(group.hits):
        parts.append(
            f"<p>Showing the first {len(group.hits)} of "
            f"{group.total}.</p>")
    if not group.hits:
        parts.append(
            '<p class="empty">Nothing in this group matches. '
            "Try fewer words.</p>")
        parts.append("</section>")
        return "\n".join(parts)
    if kind == "people":
        from .user_org_search import render_profile_card
        for hit in group.hits:
            parts.append(render_profile_card(hit))
    elif kind == "code":
        parts.append('<ul class="search-results">')
        for hit in group.hits:
            parts.extend(_code_lines(hit))
        parts.append("</ul>")
    else:
        line = {"repositories": _repo_line,
                "commits": _commit_line,
                "issues": _issue_line}[kind]
        parts.append('<ul class="search-results">')
        for hit in group.hits:
            parts.append(line(hit))
        parts.append("</ul>")
    parts.append("</section>")
    return "\n".join(parts)


def render_global_search_page(
        query: object,
        results: GlobalSearchResults | None = None,
        recents: list[RecentSearch] | None = None) -> str:
    """The global search page: the one box, the
    keyboard law, the searcher's recent searches
    (when the caller supplies them — signed-in
    viewers only; the store is the caller's to
    consult), skip links in group order, and one
    typed section per group searched, in the fixed
    group order. With no *results*, the page is the
    landing: box, keyboard, and recents, and no
    group claims anything. Every value escaped
    through S-010."""
    query_text = query if isinstance(query, str) else ""
    groups = results.kinds if results is not None else GROUP_ORDER
    parts = ["<h1>Search</h1>",
             render_global_search_box(query_text),
             _keyboard_section(groups)]
    if recents is not None:
        parts.append(render_recent_searches(recents))
    if results is None:
        parts.append(
            "<p>Type words above to search every kind of "
            "thing on this instance together.</p>")
        return "\n".join(parts)
    if results.groups:
        links = " · ".join(
            f'<a href="#group-{kind}">'
            f"{escape_html_text(GROUP_WORDS[kind])}</a>"
            for kind in results.kinds)
        parts.append(f'<nav class="group-links">{links}</nav>')
    for group in results.groups:
        parts.append(_group_section(group))
    return "\n".join(parts)
