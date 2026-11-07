"""Issue/PR search backend (S-206).

The qualifier language of S-135/S-161 executed over
FTS + structured fields — Part X's backend over the
S-205 index architecture, written from research
files 18 and 19. S-135 searched one repository's
issues by scanning live rows; S-161 did the same for
pull requests. This slice builds the index those
searches grow into: a SQLite FTS5 table (migration
81, the founding engine Part X names) holding each
numbered item's title and body for text, plus its
structured fields denormalised at index time, and a
single parser/executor for the whole grammar over
issues and pull requests together.

- **One grammar, the union of its parts.** The
  S-135 qualifiers (`is:open` / `is:closed`,
  `label:`, `author:`, `assignee:`, `milestone:`),
  the S-161 qualifiers (`is:pr`, `is:draft`,
  `review:`, `status:`), the kind markers
  (`is:issue`, `is:pr`), and the full-grammar
  qualifiers research 19 reserved for this slice:
  `repo:owner/name` scoping, `no:label` /
  `no:assignee` / `no:milestone` emptiness,
  `created:` / `updated:` date filters (`on` a day,
  `>`, `>=`, `<`, `<=`, and `A..B` ranges over real
  calendar dates, judged in UTC), `sort:` ordering
  (`created-asc`, `created-desc`, `comments-desc`;
  the default is repository, then number), and
  `-qualifier:value` negation of one qualifier.
  Tokens compose by AND, exactly as before;
  contradictory qualifiers match nothing.
- **Kind honesty for kind vocabulary.** `review:`
  and `status:` are pull-request positions (S-161):
  they hold only for pull requests, never for
  issues — an issue is found by `is:`, not by
  pretending it has a review position. `status:`
  keeps S-161's whole-position meaning (open and
  ready / draft / closed), so `is:open` and
  `status:open` differ by exactly the drafts.
  `review:none` holds when no review has been
  submitted; `review:requested` when an active
  (not dismissed) review request stands — both
  read at index time from S-148/S-151's tables,
  taking each reviewer's *latest* verdict, the
  S-161 position.
- **FTS is the text engine, with its ceiling said
  plainly.** Free text and quoted phrases run as
  an FTS5 MATCH over title and body: whole tokens
  and phrases, case-insensitively — not substring
  hunts (research 18's honest limit; S-135's
  per-page substring scan is not this backend's
  promise). Structured qualifiers are judged by
  the pure `matches_query` over the index row, so
  the deciding law is testable without a database.
- **The index is filled from the owning tables,
  on the S-205 triggers.** `index_item`,
  `index_repository`, and `index_all` read the
  shared numbered row plus its label, assignee,
  and milestone relations (and, for pull requests,
  the branch pair, draft flag, and review
  position) and write the FTS row keyed by the
  shared row id; each write also registers the
  document in S-205's registry (`put_document`,
  key `<kind>:<number>`), so the architecture's
  document counts tell the truth about this
  backend. Indexing is the mutation trigger's
  work (S-205): callers re-index an item when it
  mutates; a search reads only the index, so an
  item never indexed is honestly absent, and
  `rebuild_repository` replaces a repository's
  rows whole in one transaction.
- **Unknown qualifiers fail closed.** A token
  shaped like a qualifier whose name is outside
  the union grammar — negated or not — is refused
  `query_invalid`, naming it: never silently
  dropped (a dropped qualifier widens the search,
  the S-118 law) and never treated as free text.
  Empty values, bad vocabulary values, malformed
  `repo:` scopes, unreal or malformed dates, a
  second differing `sort:`, unterminated quotes,
  and over-long or non-text queries are the same
  refusal.
- **Permission today is S-054's gate; S-209 owns
  the hardening.** A per-repository search answers
  a stranger to a private repository with the
  uniform `repo_not_found`, and a global search
  resolves its visible repositories through
  `can_read` *before* any FTS row is read, so a
  hit can only ever name a repository its viewer
  may read. That is the seam S-209 builds on: it
  owns the leakage battery and the count/snippet
  guarantees (this backend returns no snippets at
  all), and it can tighten the visible-repository
  resolution in this one place without touching
  the grammar or the index. Nothing here designs
  S-209 away.
- **No audit event of its own, and the registry
  is the only write.** Searching mutates nothing.
  Indexing writes the FTS table and S-205's
  document registry — derived data, rebuildable
  from the owning tables at any time. 122 events
  stand: 31 auth / 79 repo / 12 admin. Storage is
  migration 81 (schema 80 to 81).
"""

from __future__ import annotations

import calendar
import re
import sqlite3
from dataclasses import dataclass
from datetime import date

from .accounts import User
from .escaping import escape_html_attr, escape_html_text
from .index_architecture import SearchIndexStore
from .issue_search import SearchError, _tokenise
from .permissions import can_read
from .repositories import Repository, RepositoryStore

__all__ = [
    "QUALIFIER_HELP", "QUALIFIER_NAMES", "IndexRow",
    "ParsedSearchQuery", "SearchBackendError", "SearchHit",
    "IssuePRSearch", "date_bounds", "decide_status",
    "fts_match_query", "matches_query", "parse_search_query",
    "render_backend_search_page", "review_holds",
]

QUERY_MAX = 500
_SEP = "\x1f"  # structured multi-value separator in index rows

QUALIFIER_NAMES = frozenset({
    "is", "label", "author", "assignee", "milestone",
    "review", "status", "repo", "no", "created",
    "updated", "sort"})
IS_VALUES = frozenset({"open", "closed", "issue", "pr", "draft"})
REVIEW_VALUES = frozenset(
    {"approved", "commented", "changes_requested", "none", "requested"})
STATUS_VALUES = frozenset({"open", "draft", "closed"})
NO_VALUES = frozenset({"label", "assignee", "milestone"})
SORT_VALUES = frozenset(
    {"created-asc", "created-desc", "comments-desc"})
_KIND_FOR_IS = {"issue": "issue", "pr": "pull_request"}

QUALIFIER_HELP: tuple[tuple[str, str], ...] = (
    ("is:open / is:closed", "only items in that state"),
    ("is:issue / is:pr", "only issues, or only pull requests"),
    ("is:draft", "only open draft pull requests"),
    ("label:NAME", "only items carrying that label; "
                   "quote names with spaces"),
    ("author:NAME", "only items written by that account"),
    ("assignee:NAME", "only items assigned to that account"),
    ("milestone:TITLE", "only items in that milestone; "
                        "quote titles with spaces"),
    ("review:approved", "pull requests where a reviewer's "
                        "latest verdict is approval"),
    ("review:changes_requested", "a reviewer's latest verdict "
                                 "asks for changes"),
    ("review:commented", "a reviewer's latest verdict is a comment"),
    ("review:none", "pull requests with no review submitted yet"),
    ("review:requested", "pull requests with a review request "
                         "still active"),
    ("status:open", "pull requests open and ready — not a draft"),
    ("status:draft", "pull requests open and still a draft"),
    ("status:closed", "pull requests that are closed"),
    ("repo:OWNER/NAME", "only items in that repository"),
    ("no:label / no:assignee / no:milestone",
     "only items with that field empty"),
    ("created:DATE", "items created on that day; >, <, >=, <="
                     " and A..B ranges also work"),
    ("updated:DATE", "items last updated on that day; "
                     "the same range shapes work"),
    ("sort:created-asc", "oldest first"),
    ("sort:created-desc", "newest first"),
    ("sort:comments-desc", "most comments first"),
    ("-label:NAME", "a leading minus negates one qualifier"),
)


class SearchBackendError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


# ------------------------------------------------------------------
# The parsed query
# ------------------------------------------------------------------

@dataclass(frozen=True)
class ParsedSearchQuery:
    text_terms: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()
    states: tuple[str, ...] = ()
    draft_only: bool = False
    labels: tuple[str, ...] = ()
    authors: tuple[str, ...] = ()
    assignees: tuple[str, ...] = ()
    milestones: tuple[str, ...] = ()
    reviews: tuple[str, ...] = ()
    statuses: tuple[str, ...] = ()
    repo_scopes: tuple[tuple[str, str], ...] = ()
    no_fields: tuple[str, ...] = ()
    created_bounds: tuple[tuple[int | None, int | None], ...] = ()
    updated_bounds: tuple[tuple[int | None, int | None], ...] = ()
    sort: str = ""
    not_kinds: tuple[str, ...] = ()
    not_states: tuple[str, ...] = ()
    not_draft: bool = False
    not_labels: tuple[str, ...] = ()
    not_authors: tuple[str, ...] = ()
    not_assignees: tuple[str, ...] = ()
    not_milestones: tuple[str, ...] = ()
    not_reviews: tuple[str, ...] = ()
    not_statuses: tuple[str, ...] = ()
    not_repo_scopes: tuple[tuple[str, str], ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.text_terms or self.kinds or self.states
                    or self.draft_only or self.labels or self.authors
                    or self.assignees or self.milestones or self.reviews
                    or self.statuses or self.repo_scopes or self.no_fields
                    or self.created_bounds or self.updated_bounds)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_day(value: str, name: str) -> date:
    if not _DATE_RE.match(value):
        raise SearchError(
            "query_invalid",
            f"The {name}: date {value!r} is not a YYYY-MM-DD date.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise SearchError(
            "query_invalid",
            f"The {name}: date {value!r} is not a real calendar "
            "date.") from None


def _day_start(day: date) -> int:
    return calendar.timegm(
        (day.year, day.month, day.day, 0, 0, 0, 0, 0, 0))


def date_bounds(value: str, name: str) -> tuple[int | None, int | None]:
    """One `created:` / `updated:` value as a half-open
    epoch interval [lo, hi) in UTC. A bare date is that
    day; `>D` is after that day, `>=D` from its start,
    `<D` before its start, `<=D` through its end, and
    `A..B` the inclusive range. Malformed shapes and
    unreal dates are refused `query_invalid`."""
    text = value.strip()
    if ".." in text:
        first, _, rest = text.partition("..")
        if ".." in rest or not first or not rest:
            raise SearchError(
                "query_invalid",
                f"The {name}: range {value!r} needs two dates.")
        start_day = _parse_day(first, name)
        end_day = _parse_day(rest, name)
        if end_day < start_day:
            raise SearchError(
                "query_invalid",
                f"The {name}: range {value!r} ends before it "
                "begins.")
        return (_day_start(start_day), _day_start(end_day) + 86400)
    for prefix, op in ((">=", "ge"), ("<=", "le"),
                       (">", "gt"), ("<", "lt")):
        if text.startswith(prefix):
            day = _parse_day(text[len(prefix):], name)
            start = _day_start(day)
            if op == "ge":
                return (start, None)
            if op == "gt":
                return (start + 86400, None)
            if op == "lt":
                return (None, start)
            return (None, start + 86400)
    day = _parse_day(text, name)
    start = _day_start(day)
    return (start, start + 86400)


def _add_unique(target: list, value: str) -> None:
    if value.lower() not in [v.lower() for v in target]:
        target.append(value)


def _parse_repo_scope(value: str) -> tuple[str, str]:
    owner, slash, name = value.partition("/")
    if not slash or "/" in name or not owner.strip() \
            or not name.strip():
        raise SearchError(
            "query_invalid",
            f"The repo: qualifier {value!r} does not name exactly "
            "one repository (owner/name).")
    return (owner.strip().lower(), name.strip().lower())


def parse_search_query(query: object) -> ParsedSearchQuery:
    """Parse *query* under the unified S-206 grammar:
    the S-135 subset, the S-161 extension, and the
    research-19 full-grammar qualifiers. A non-string,
    over-long, or malformed query — and any qualifier
    outside the grammar, negated or not — is refused
    `query_invalid`, naming the problem."""
    if query is None:
        query = ""
    if not isinstance(query, str):
        raise SearchError("query_invalid", "A search is text.")
    if len(query) > QUERY_MAX:
        raise SearchError(
            "query_invalid",
            f"A search is at most {QUERY_MAX} characters.")
    if any((ord(c) < 0x20 and c not in "\t") or ord(c) == 0x7F
           for c in query):
        raise SearchError(
            "query_invalid", "A search is one line of text.")
    text_terms: list[str] = []
    kinds: list[str] = []
    states: list[str] = []
    draft_only = False
    labels: list[str] = []
    authors: list[str] = []
    assignees: list[str] = []
    milestones: list[str] = []
    reviews: list[str] = []
    statuses: list[str] = []
    repo_scopes: list[tuple[str, str]] = []
    no_fields: list[str] = []
    created_bounds: list[tuple[int | None, int | None]] = []
    updated_bounds: list[tuple[int | None, int | None]] = []
    sort = ""
    not_kinds: list[str] = []
    not_states: list[str] = []
    not_draft = False
    not_labels: list[str] = []
    not_authors: list[str] = []
    not_assignees: list[str] = []
    not_milestones: list[str] = []
    not_reviews: list[str] = []
    not_statuses: list[str] = []
    not_repo_scopes: list[tuple[str, str]] = []
    for token in _tokenise(query):
        negated = token.startswith("-") and len(token) > 1
        probe = token[1:] if negated else token
        head, sep, value = probe.partition(":")
        if not (sep and head):
            text_terms.append(token)
            continue
        if head.lower() not in QUALIFIER_NAMES:
            if all(c.isalnum() or c in "_-" for c in head):
                raise SearchError(
                    "query_invalid",
                    f"There is no {head}: qualifier in issue and "
                    "pull request search; the qualifiers are is:, "
                    "label:, author:, assignee:, milestone:, "
                    "review:, status:, repo:, no:, created:, "
                    "updated:, and sort:.")
            text_terms.append(token)
            continue
        name = head.lower()
        if not value.strip():
            raise SearchError(
                "query_invalid",
                f"The {name}: qualifier needs a value.")
        value = value.strip()
        low = value.lower()
        if name in ("created", "updated", "sort", "no") and negated:
            raise SearchError(
                "query_invalid",
                f"The {name}: qualifier cannot be negated.")
        if name == "is":
            if low not in IS_VALUES:
                raise SearchError(
                    "query_invalid",
                    "is: takes open, closed, issue, pr, or draft.")
            if low in ("open", "closed"):
                _add_unique(not_states if negated else states, low)
            elif low == "draft":
                if negated:
                    not_draft = True
                else:
                    draft_only = True
            else:
                _add_unique(not_kinds if negated else kinds,
                            _KIND_FOR_IS[low])
        elif name == "label":
            _add_unique(not_labels if negated else labels, value)
        elif name == "author":
            _add_unique(not_authors if negated else authors, value)
        elif name == "assignee":
            _add_unique(not_assignees if negated else assignees, value)
        elif name == "milestone":
            _add_unique(not_milestones if negated else milestones,
                        value)
        elif name == "review":
            normalised = low.replace("-", "_")
            if normalised not in REVIEW_VALUES:
                raise SearchError(
                    "query_invalid",
                    "review: takes approved, commented, "
                    "changes_requested, none, or requested.")
            _add_unique(not_reviews if negated else reviews,
                        normalised)
        elif name == "status":
            if low not in STATUS_VALUES:
                raise SearchError(
                    "query_invalid",
                    "status: takes open, draft, or closed.")
            _add_unique(not_statuses if negated else statuses, low)
        elif name == "repo":
            scope = _parse_repo_scope(value)
            target = not_repo_scopes if negated else repo_scopes
            if scope not in target:
                target.append(scope)
        elif name == "no":
            if low not in NO_VALUES:
                raise SearchError(
                    "query_invalid",
                    "no: takes label, assignee, or milestone.")
            if low not in no_fields:
                no_fields.append(low)
        elif name == "created":
            created_bounds.append(date_bounds(value, "created"))
        elif name == "updated":
            updated_bounds.append(date_bounds(value, "updated"))
        else:  # sort
            if low not in SORT_VALUES:
                raise SearchError(
                    "query_invalid",
                    "sort: takes created-asc, created-desc, or "
                    "comments-desc.")
            if sort and sort != low:
                raise SearchError(
                    "query_invalid",
                    "A search names one sort: qualifier.")
            sort = low
    return ParsedSearchQuery(
        text_terms=tuple(text_terms), kinds=tuple(kinds),
        states=tuple(states), draft_only=draft_only,
        labels=tuple(labels), authors=tuple(authors),
        assignees=tuple(assignees), milestones=tuple(milestones),
        reviews=tuple(reviews), statuses=tuple(statuses),
        repo_scopes=tuple(repo_scopes), no_fields=tuple(no_fields),
        created_bounds=tuple(created_bounds),
        updated_bounds=tuple(updated_bounds), sort=sort,
        not_kinds=tuple(not_kinds), not_states=tuple(not_states),
        not_draft=not_draft, not_labels=tuple(not_labels),
        not_authors=tuple(not_authors),
        not_assignees=tuple(not_assignees),
        not_milestones=tuple(not_milestones),
        not_reviews=tuple(not_reviews),
        not_statuses=tuple(not_statuses),
        not_repo_scopes=tuple(not_repo_scopes))


def fts_match_query(text_terms: tuple[str, ...]) -> str:
    """The FTS5 MATCH string for the free-text terms:
    each term a quoted phrase (quotes doubled, the
    FTS5 escape), joined by AND. Pure and testable;
    an empty term set yields an empty string, whose
    caller must not issue a MATCH at all."""
    return " AND ".join(
        '"' + term.replace('"', '""') + '"' for term in text_terms)


# ------------------------------------------------------------------
# Index rows and the pure deciding law
# ------------------------------------------------------------------

@dataclass(frozen=True)
class IndexRow:
    """One indexed numbered item: the FTS row's
    structured fields, as the deciding law reads
    them. Multi-value fields are lowercase tuples."""
    row_id: int
    repo_id: int
    number: int
    kind: str            # 'issue' | 'pull_request'
    title: str
    body: str
    state: str           # 'open' | 'closed'
    author_lower: str
    labels: tuple[str, ...] = ()
    assignees: tuple[str, ...] = ()
    milestone_lower: str = ""
    is_draft: bool = False
    base_branch: str = ""
    head_branch: str = ""
    reviews_latest: tuple[str, ...] = ()
    reviews_total: int = 0
    review_requested: bool = False
    created_at: int = 0
    updated_at: int = 0
    comment_count: int = 0


def decide_status(status: str, row: IndexRow) -> bool:
    """S-161's whole-position law over an index row:
    `status:` holds only for pull requests."""
    if row.kind != "pull_request":
        return False
    if status == "closed":
        return row.state == "closed"
    if status == "draft":
        return row.state == "open" and row.is_draft
    return row.state == "open" and not row.is_draft  # open


def review_holds(wanted: str, row: IndexRow) -> bool:
    """One `review:` value over an index row: pull
    requests only; `none` is no submitted review,
    `requested` an active review request, and the
    verdict words read the latest-by-reviewer set
    captured at index time."""
    if row.kind != "pull_request":
        return False
    if wanted == "none":
        return row.reviews_total == 0
    if wanted == "requested":
        return row.review_requested
    return wanted in row.reviews_latest


def _in_bounds(stamp: int,
               bounds: tuple[tuple[int | None, int | None], ...]
               ) -> bool:
    for lo, hi in bounds:
        if lo is not None and stamp < lo:
            return False
        if hi is not None and stamp >= hi:
            return False
    return True


def matches_query(row: IndexRow, parsed: ParsedSearchQuery) -> bool:
    """The pure structured law: does this index row
    satisfy every structured qualifier in *parsed*?
    (Free text is the FTS engine's half of the AND;
    the executor narrows by MATCH before this law
    runs, so a row reaching here with text terms in
    the query has already matched them.) Every
    qualifier must hold; every negated qualifier
    must not."""
    for kind in parsed.kinds:
        if row.kind != kind:
            return False
    if row.kind in parsed.not_kinds:
        return False
    for state in parsed.states:
        if row.state != state:
            return False
    if row.state in parsed.not_states:
        return False
    if parsed.draft_only and not (
            row.kind == "pull_request" and row.state == "open"
            and row.is_draft):
        return False
    if parsed.not_draft and row.kind == "pull_request" \
            and row.state == "open" and row.is_draft:
        return False
    for value in parsed.labels:
        if value.lower() not in row.labels:
            return False
    for value in parsed.not_labels:
        if value.lower() in row.labels:
            return False
    if parsed.authors and row.author_lower not in [
            v.lower() for v in parsed.authors]:
        return False
    if row.author_lower in [v.lower() for v in parsed.not_authors]:
        return False
    for value in parsed.assignees:
        if value.lower() not in row.assignees:
            return False
    for value in parsed.not_assignees:
        if value.lower() in row.assignees:
            return False
    for value in parsed.milestones:
        if row.milestone_lower != value.lower():
            return False
    for value in parsed.not_milestones:
        if row.milestone_lower == value.lower():
            return False
    for field_name in parsed.no_fields:
        if field_name == "label" and row.labels:
            return False
        if field_name == "assignee" and row.assignees:
            return False
        if field_name == "milestone" and row.milestone_lower:
            return False
    for wanted in parsed.reviews:
        if not review_holds(wanted, row):
            return False
    for wanted in parsed.not_reviews:
        if review_holds(wanted, row):
            return False
    for status in parsed.statuses:
        if not decide_status(status, row):
            return False
    for status in parsed.not_statuses:
        if decide_status(status, row):
            return False
    if not _in_bounds(row.created_at, parsed.created_bounds):
        return False
    if not _in_bounds(row.updated_at, parsed.updated_bounds):
        return False
    return True


@dataclass(frozen=True)
class SearchHit:
    """One result: the indexed item's public face —
    where it lives, what it is called, and its
    position said in data the page renders in
    words. Deliberately no snippet: S-209 owns
    what result text may be shown, and when."""
    repo_id: int
    owner: str
    repo: str
    number: int
    kind: str            # 'issue' | 'pull_request'
    row_id: int
    title: str
    state: str
    is_draft: bool
    author_lower: str
    created_at: int
    updated_at: int
    comment_count: int

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def kind_words(self) -> str:
        return "pull request" if self.kind == "pull_request" \
            else "issue"

    @property
    def state_words(self) -> str:
        if self.kind == "pull_request":
            if self.state == "closed":
                return "closed pull request"
            return "draft pull request" if self.is_draft \
                else "open pull request"
        return self.state


def _sort_key(sort: str):
    if sort == "created-asc":
        return lambda h: (h.created_at, h.full_name.lower(),
                          h.number)
    if sort == "created-desc":
        return lambda h: (-h.created_at, h.full_name.lower(),
                          h.number)
    if sort == "comments-desc":
        return lambda h: (-h.comment_count, h.full_name.lower(),
                          h.number)
    return lambda h: (h.full_name.lower(), h.number)


# ------------------------------------------------------------------
# The backend: indexer + executor over migration 81
# ------------------------------------------------------------------

class IssuePRSearch:
    """The S-206 backend. The indexer reads the
    owning tables and writes migration 81's FTS
    table plus S-205's document registry; the
    executor parses the unified grammar, narrows
    by FTS MATCH when the query carries text, and
    judges the structured law with `matches_query`.
    Visible repositories are resolved through
    S-054's `can_read` before any index row is
    read (the S-209 seam — see the docstring)."""

    def __init__(self, conn: sqlite3.Connection,
                 repositories: RepositoryStore,
                 index_store: SearchIndexStore | None = None):
        self._conn = conn
        self._repos = repositories
        self._index = index_store or SearchIndexStore(
            conn, repositories)

    # -- indexing ------------------------------------

    def _build_row(self, repo_id: int, number: int) -> IndexRow:
        source = self._conn.execute(
            "SELECT * FROM issues WHERE repo_id = ? AND number = ?",
            (repo_id, number)).fetchone()
        if source is None:
            raise SearchBackendError(
                "item_not_found",
                f"No numbered item #{number} in this repository.")
        row_id = int(source["id"])
        kind = source["kind"]
        author = self._conn.execute(
            "SELECT username_lower FROM users WHERE id = ?",
            (int(source["author_id"]),)).fetchone()
        labels = tuple(r["name_lower"] for r in self._conn.execute(
            "SELECT l.name_lower FROM labels l"
            " JOIN issue_labels il ON il.label_id = l.id"
            " WHERE il.issue_id = ? ORDER BY l.name_lower",
            (row_id,)))
        assignees = tuple(
            r["username_lower"] for r in self._conn.execute(
                "SELECT u.username_lower FROM issue_assignees a"
                " JOIN users u ON u.id = a.user_id"
                " WHERE a.issue_id = ? ORDER BY u.username_lower",
                (row_id,)))
        milestone_lower = ""
        if source["milestone_id"]:
            found = self._conn.execute(
                "SELECT title_lower FROM milestones WHERE id = ?",
                (int(source["milestone_id"]),)).fetchone()
            milestone_lower = found["title_lower"] if found else ""
        comments = self._conn.execute(
            "SELECT COUNT(*) AS c FROM issue_comments"
            " WHERE issue_id = ? AND deleted_at IS NULL",
            (row_id,)).fetchone()
        is_draft = False
        base_branch = head_branch = ""
        reviews_latest: tuple[str, ...] = ()
        reviews_total = 0
        review_requested = False
        if kind == "pull_request":
            pr = self._conn.execute(
                "SELECT * FROM pull_requests WHERE issue_id = ?",
                (row_id,)).fetchone()
            if pr is not None:
                is_draft = bool(pr["is_draft"])
                base_branch = pr["base_branch"]
                head_branch = pr["head_branch"]
                latest: dict[int, str] = {}
                for review in self._conn.execute(
                        "SELECT reviewer_id, verdict"
                        " FROM pull_request_reviews"
                        " WHERE pull_request_id = ? ORDER BY id",
                        (int(pr["id"]),)):
                    latest[int(review["reviewer_id"])] = \
                        review["verdict"]
                    reviews_total += 1
                reviews_latest = tuple(sorted(set(latest.values())))
                asked = self._conn.execute(
                    "SELECT COUNT(*) AS c"
                    " FROM pull_request_review_requests"
                    " WHERE pull_request_id = ?"
                    " AND state = 'requested'",
                    (int(pr["id"]),)).fetchone()
                review_requested = int(asked["c"]) > 0
        return IndexRow(
            row_id=row_id, repo_id=repo_id, number=number,
            kind=kind, title=source["title"], body=source["body"],
            state=source["state"],
            author_lower=author["username_lower"] if author else "",
            labels=labels, assignees=assignees,
            milestone_lower=milestone_lower, is_draft=is_draft,
            base_branch=base_branch, head_branch=head_branch,
            reviews_latest=reviews_latest,
            reviews_total=reviews_total,
            review_requested=review_requested,
            created_at=int(source["created_at"]),
            updated_at=int(source["updated_at"]),
            comment_count=int(comments["c"]))

    def _write_row(self, row: IndexRow) -> None:
        with self._conn:
            self._conn.execute(
                "DELETE FROM issue_pr_fts WHERE rowid = ?",
                (row.row_id,))
            self._conn.execute(
                "INSERT INTO issue_pr_fts (rowid, title, body,"
                " repo_id, number, kind, state, author_lower,"
                " labels_lower, assignees_lower, milestone_lower,"
                " is_draft, base_branch, head_branch,"
                " reviews_latest, reviews_total, review_requested,"
                " created_at, updated_at, comment_count)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
                " ?, ?, ?, ?, ?, ?)",
                (row.row_id, row.title, row.body, row.repo_id,
                 row.number, row.kind, row.state, row.author_lower,
                 _SEP.join(row.labels), _SEP.join(row.assignees),
                 row.milestone_lower, 1 if row.is_draft else 0,
                 row.base_branch, row.head_branch,
                 _SEP.join(row.reviews_latest), row.reviews_total,
                 1 if row.review_requested else 0, row.created_at,
                 row.updated_at, row.comment_count))

    def _register(self, repo: Repository, row: IndexRow) -> None:
        self._index.put_document(
            repo.owner, repo.name, kind=row.kind,
            doc_key=f"{row.kind}:{row.number}")

    def index_item(self, owner: object, repo: object,
                   number: object) -> IndexRow:
        """(Re)index one numbered item from its owning
        tables: the FTS row is replaced whole and the
        S-205 document registered. A repository or
        item that does not exist is refused by name."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise SearchBackendError(
                "repo_not_found", "No such repository.")
        if not isinstance(number, int) or isinstance(number, bool):
            raise SearchBackendError(
                "item_not_found",
                "A numbered item is named by its integer number.")
        row = self._build_row(current.id, number)
        self._write_row(row)
        self._register(current, row)
        return row

    def index_repository(self, owner: object,
                         repo: object) -> int:
        """Index every numbered item in one repository.
        Returns how many items were indexed."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise SearchBackendError(
                "repo_not_found", "No such repository.")
        numbers = [int(r["number"]) for r in self._conn.execute(
            "SELECT number FROM issues WHERE repo_id = ?"
            " ORDER BY number", (current.id,))]
        for number in numbers:
            row = self._build_row(current.id, number)
            self._write_row(row)
            self._register(current, row)
        return len(numbers)

    def index_all(self) -> int:
        """Index every numbered item in every
        repository. Returns the total indexed."""
        total = 0
        for found in self._conn.execute(
                "SELECT id FROM repositories ORDER BY id").fetchall():
            current = self._repos.get_by_id(int(found["id"]))
            if current is not None:
                total += self.index_repository(
                    current.owner, current.name)
        return total

    def remove_item(self, owner: object, repo: object,
                    number: object) -> bool:
        """Drop one item's index row and registry
        document (its source was deleted). True when
        an index row was removed."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise SearchBackendError(
                "repo_not_found", "No such repository.")
        source = self._conn.execute(
            "SELECT id, kind FROM issues"
            " WHERE repo_id = ? AND number = ?",
            (current.id, number)).fetchone()
        removed = False
        if source is not None:
            with self._conn:
                cur = self._conn.execute(
                    "DELETE FROM issue_pr_fts WHERE rowid = ?",
                    (int(source["id"]),))
                removed = cur.rowcount > 0
            self._index.remove_document(
                current.owner, current.name, kind=source["kind"],
                doc_key=f"{source['kind']}:{number}")
        return removed

    def rebuild_repository(self, owner: object,
                           repo: object) -> int:
        """Replace one repository's issue/PR index
        whole: every FTS row for the repository is
        deleted and rebuilt from the owning tables in
        one transaction, so a rebuild never serves a
        half-rebuilt repository. Returns the count."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise SearchBackendError(
                "repo_not_found", "No such repository.")
        rows = [self._build_row(current.id, int(r["number"]))
                for r in self._conn.execute(
                    "SELECT number FROM issues WHERE repo_id = ?"
                    " ORDER BY number", (current.id,))]
        with self._conn:
            self._conn.execute(
                "DELETE FROM issue_pr_fts WHERE repo_id = ?",
                (current.id,))
        for row in rows:
            self._write_row(row)
            self._register(current, row)
        return len(rows)

    # -- searching -------------------------------------

    def _visible_repos(self, viewer: User | None,
                       scoped: Repository | None) -> list[Repository]:
        """The repositories a search may read, resolved
        before any index row is touched (the S-209
        seam). A named repository the viewer cannot
        read — or that does not exist — answers the
        uniform `repo_not_found`."""
        if scoped is not None:
            if not can_read(viewer, scoped):
                raise SearchBackendError(
                    "repo_not_found", "No such repository.")
            return [scoped]
        visible: list[Repository] = []
        for found in self._conn.execute(
                "SELECT id FROM repositories ORDER BY id").fetchall():
            current = self._repos.get_by_id(int(found["id"]))
            if current is not None and can_read(viewer, current):
                visible.append(current)
        return visible

    def _row_from(self, found: sqlite3.Row) -> IndexRow:
        labels = found["labels_lower"]
        assignees = found["assignees_lower"]
        latest = found["reviews_latest"]
        return IndexRow(
            row_id=int(found["rowid"]), repo_id=int(found["repo_id"]),
            number=int(found["number"]), kind=found["kind"],
            title=found["title"], body=found["body"],
            state=found["state"],
            author_lower=found["author_lower"],
            labels=tuple(labels.split(_SEP)) if labels else (),
            assignees=tuple(assignees.split(_SEP)) if assignees
            else (),
            milestone_lower=found["milestone_lower"],
            is_draft=bool(found["is_draft"]),
            base_branch=found["base_branch"],
            head_branch=found["head_branch"],
            reviews_latest=tuple(latest.split(_SEP)) if latest
            else (),
            reviews_total=int(found["reviews_total"]),
            review_requested=bool(found["review_requested"]),
            created_at=int(found["created_at"]),
            updated_at=int(found["updated_at"]),
            comment_count=int(found["comment_count"]))

    _COLUMNS = (
        "rowid, title, body, repo_id, number, kind, state,"
        " author_lower, labels_lower, assignees_lower,"
        " milestone_lower, is_draft, base_branch, head_branch,"
        " reviews_latest, reviews_total, review_requested,"
        " created_at, updated_at, comment_count")

    def search(self, viewer: User | None, query: object,
               owner: object = None, repo: object = None
               ) -> list[SearchHit]:
        """Execute one unified query. With *owner* and
        *repo* the search is that repository's (the
        uniform `repo_not_found` for a repository the
        viewer cannot read); without them it is
        global over every repository the viewer may
        read. `repo:` qualifiers narrow either mode.
        Results are ordered by the query's `sort:`,
        else by repository, then number."""
        parsed = parse_search_query(query)
        scoped = None
        if owner is not None or repo is not None:
            scoped = self._repos.get_repository(owner, repo)
            if scoped is None:
                raise SearchBackendError(
                    "repo_not_found", "No such repository.")
        visible = self._visible_repos(viewer, scoped)
        if parsed.repo_scopes:
            visible = [r for r in visible if all(
                (r.owner_lower, r.name_lower) == scope
                for scope in parsed.repo_scopes)]
        if parsed.not_repo_scopes:
            visible = [r for r in visible if (
                r.owner_lower, r.name_lower)
                not in parsed.not_repo_scopes]
        if not visible:
            return []
        by_id = {r.id: r for r in visible}
        placeholders = ", ".join("?" for _ in visible)
        if parsed.text_terms:
            found_rows = self._conn.execute(
                f"SELECT {self._COLUMNS} FROM issue_pr_fts"
                " WHERE issue_pr_fts MATCH ?"
                f" AND repo_id IN ({placeholders})",
                (fts_match_query(parsed.text_terms),
                 *by_id.keys())).fetchall()
        else:
            found_rows = self._conn.execute(
                f"SELECT {self._COLUMNS} FROM issue_pr_fts"
                f" WHERE repo_id IN ({placeholders})",
                tuple(by_id.keys())).fetchall()
        hits: list[SearchHit] = []
        for found in found_rows:
            row = self._row_from(found)
            if not matches_query(row, parsed):
                continue
            current = by_id[row.repo_id]
            hits.append(SearchHit(
                repo_id=row.repo_id, owner=current.owner,
                repo=current.name, number=row.number,
                kind=row.kind, row_id=row.row_id, title=row.title,
                state=row.state, is_draft=row.is_draft,
                author_lower=row.author_lower,
                created_at=row.created_at,
                updated_at=row.updated_at,
                comment_count=row.comment_count))
        hits.sort(key=_sort_key(parsed.sort))
        return hits

    def search_repository(self, viewer: User | None,
                          owner: object, repo: object,
                          query: object) -> list[SearchHit]:
        """One repository's unified search — the
        per-repository face of `search`."""
        return self.search(viewer, query, owner=owner, repo=repo)


def render_backend_search_page(query: object,
                               hits: list[SearchHit]) -> str:
    """The backend's results page: the form as typed
    (escaped through S-010), the qualifier help in
    plain words, and each result with its repository,
    number, title, and kind and state said in words —
    never a colour alone."""
    query_text = query if isinstance(query, str) else ""
    parts = [
        "<h1>Search issues and pull requests</h1>",
        '<form method="get" action="search" role="search">',
        '<label for="q">Search issues and pull requests</label>',
        f'<input id="q" name="q" type="search" '
        f'value="{escape_html_attr(query_text)}">',
        '<button type="submit">Search</button>',
        "</form>",
        '<ul class="qualifier-help">',
    ]
    for name, words in QUALIFIER_HELP:
        parts.append(
            f"<li><code>{escape_html_text(name)}</code> — "
            f"{escape_html_text(words)}</li>")
    parts.append("</ul>")
    if not hits:
        parts.append(
            '<p class="empty">No issues or pull requests match. '
            "Try fewer qualifiers, or clear the search to see "
            "every indexed item.</p>")
    else:
        parts.append('<ul class="search-results">')
        for hit in hits:
            parts.append(
                f"<li>{escape_html_text(hit.full_name)} "
                f"#{hit.number} "
                f"{escape_html_text(hit.title)} — "
                f"{escape_html_text(hit.state_words)}</li>")
        parts.append("</ul>")
    return "\n".join(parts)
