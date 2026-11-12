"""Search API -- the public contract (S-245).

Search API -- S-216 lands as a public contract
here. S-216 built the search face in Part X
(samverk/search_api.py) and S-237's contract
ratified its shape under `/api/v1/search`,
naming this slice to land it as the public
contract; S-238..S-241 then landed the door,
the paging law, the one problem format, and
the rate limiting every public face stands
behind. This module is that landing: the same
search, answered through the API door, with
each group's hits carrying their paging keys.

- **No API-only back doors, by construction.**
  The whole-search call delegates to S-216's
  `SearchAPI`, which constructs S-213's
  `GlobalSearch` without a recent-search store
  and delegates every search to it -- so an API
  search records no recents and audits nothing,
  exactly as S-216 landed. The paged group call
  delegates to the very executors S-213 fans
  out to (S-210's `RepositorySearch`, S-211's
  `PeopleSearch`, S-212's `CommitSearch`,
  S-208's `CodeSearch`, S-206's
  `IssuePRSearch`), handing each the plain
  words of the parsed global query exactly as
  S-213's fan-out hands them (phrases re-quoted
  for the substring and FTS backends, the bare
  joined words as the code pattern), at those
  executors' own limit (500 -- their documented
  maximum, where the global face's per-group
  cap is 100). This module owns no index, no
  parser of its own beyond S-213's
  `parse_global_query`, and no filter: every
  executor resolves the viewer's visible
  repositories through S-209's one resolution
  (over S-054's `can_read`) before any private
  fact is read, so permission filtering is
  identical by construction -- an unreadable
  repository contributes no hit, no title, no
  snippet, and no count on either call. The
  battery proves the agreement: a paged
  group's crawl is exactly the whole-search
  group's hits, extended past the global cap
  by the same executor, and a stranger's
  answers over a world containing a private
  repository equal, group by group and page
  by page, the answers over a world where it
  was never created.
- **Every call resolves through S-238.**
  The header is resolved by S-238's door
  (`ApiAuthenticator.resolve_caller`) and
  nothing else: a missing header is the
  anonymous caller (public facts only, through
  the same gate), and a present-but-wrong
  header is refused with the door's own
  reasons verbatim -- it never silently
  downgrades to anonymous. Search is a public
  read of already permission-filtered facts,
  so no token-scope family judges it: S-238's
  scope law names families for repository-
  scoped resources, and a search names no
  repository -- what a caller may see is
  decided per hit by S-209, not by a scope
  ceiling over one repo. Rate limiting is
  likewise the door's own brake (S-241,
  judged over the resolved caller at the
  door), not a second limit inside this face.
- **Each group's hits carry paging keys
  (S-239).** `search_group_page` answers one
  group as one page through S-239's cursor
  engine: the group's full filtered hits (to
  the executors' own 500 bound) are re-run
  and re-filtered on every page call, then
  paged -- filtering first, paging second, so
  a page can no more leak than the capped
  group could. A search cursor names a
  position in this query's filtered order for
  this viewer: the cursor's context binds it
  to the group, the query as typed, and the
  viewer's name (or `anonymous`), so a cursor
  carried to another group, another query, or
  another viewer is refused `cursor_invalid`,
  and a cursor grants nothing -- replayed by
  a stranger, it pages the stranger's own
  filtered order. The five groups share no
  single id space and their orders are their
  executors' own (relevance and name orders,
  not id orders), so the paging key is the
  position itself, said plainly: if the
  corpus changes between two page calls,
  later pages are positions in the new order.
  The page payload carries the query, the
  group, its own filtered `total` tallied
  before paging, `returned`, a `complete`
  flag that is true only when this page
  reaches the group's true total (never
  merely the crawl bound), the honoured
  `per_page`, the walking facts and cursors,
  and the hits -- serialised by S-216's own
  `hit_to_dict`, so a hit is the same shape
  on both calls. The code group additionally
  carries its match totals. There is
  deliberately no combined total across
  groups, here as everywhere (the S-213 law).
- **Shapes are the contract's.** The whole
  search is S-237's (`query`, `groups`) with
  S-216's group shape; one paged group is the
  contract's `SEARCH_PAGE_FIELDS`. Refusals
  are S-240's shape: every refusal is a
  `PublicSearchAPIError` with a
  machine-branchable reason -- the door's
  reasons verbatim for authentication,
  S-213's and the executors' reasons verbatim
  for the search itself (`query_invalid`
  above all), S-239's reasons verbatim for
  paging (`cursor_invalid`,
  `page_size_invalid`, `ordering_invalid`) --
  rendered by `error_to_dict` in the one
  problem format through
  samverk/error_shape.py.
- **What a read witnesses.** Both calls are
  reads: they write no row and audit nothing
  (the S-216 law, unchanged). No migration
  (schema stays 94), no taxonomy event (129
  stand: 33 auth / 83 repo / 13 admin).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Callable

from .accounts import AccountStore, User
from .api_auth import ApiAuthError, ApiAuthenticator, ApiIdentity
from .api_pagination import (
    DEFAULT_PAGE_SIZE, ApiPaginationError, paginate)
from .code_search import CodeSearch, CodeSearchError
from .commit_search import CommitSearch, CommitSearchError
from .error_shape import problem_from_error, problem_to_dict
from .global_search import (
    DEFAULT_GROUP_LIMIT, GROUP_ORDER, TYPE_ALIASES,
    GlobalSearchError, parse_global_query)
from .issue_pr_search import IssuePRSearch, SearchBackendError
from .organizations import OrganizationStore
from .repositories import RepositoryStore
from .repository_search import (
    RepositorySearch, RepositorySearchError)
from .search_api import SearchAPI, SearchAPIError, hit_to_dict
from .user_org_search import PeopleSearch, PeopleSearchError
from .wiki_gist_search import WikiGistSearch, WikiGistSearchError

__all__ = [
    "GROUP_LIMIT", "SEARCH_API_PATH", "PublicSearchAPI",
    "PublicSearchAPIError", "error_to_dict",
    "group_page_to_dict", "render_search_api_page", "to_json",
]

SEARCH_API_PATH = "/api/search"

# The group executors' own bound (S-206/S-208/
# S-210/S-211/S-212 each cap a counted search at
# 500): a paged crawl reaches this many hits of
# one group, and the payload's `complete` flag
# says plainly when the group's true total
# stands beyond it.
GROUP_LIMIT = 500

_BACKEND_ERRORS = (RepositorySearchError, PeopleSearchError,
                   WikiGistSearchError,
                   CommitSearchError, CodeSearchError,
                   SearchBackendError)

_GROUP_INVALID = (
    "The group is one of: repositories, people, "
    "commits, code, issues, wiki, or gists.")


class PublicSearchAPIError(ValueError):
    """One refused public search-API call: a
    machine-branchable reason with its human
    detail."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def error_to_dict(exc: PublicSearchAPIError) -> dict:
    """One refusal as data, in S-240's one problem
    format (samverk/error_shape.py): type, title,
    status, detail, error_id -- nothing else."""
    return problem_to_dict(problem_from_error(exc))


def to_json(payload: dict) -> str:
    """One payload as a JSON text: keys sorted so
    the same answer renders byte-identically
    twice."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _terms_text(terms: tuple) -> str:
    """The free-text terms as one query line for a
    substring or FTS backend -- S-213's fan-out
    law: a term carrying spaces (a quoted phrase)
    is re-quoted, so the phrase stays one term in
    the group's own grammar."""
    return " ".join(
        f'"{term}"' if " " in term else term for term in terms)


def _pattern_text(terms: tuple) -> str:
    """The free-text terms as a code-search
    pattern -- S-213's fan-out law: the bare
    words joined; quote characters are the
    global grammar's phrase marks, never pattern
    bytes."""
    return " ".join(terms)


def group_page_to_dict(query: str, kind: str, page, total: int,
                       results: list, *,
                       total_matches: int | None = None,
                       total_matched_lines: int | None = None,
                       ) -> dict:
    """One paged group as data, in the contract's
    SEARCH_PAGE_FIELDS order: the query as typed,
    the group, its own filtered total tallied
    before paging, how many hits this page
    returned, whether the crawl is complete on
    this page -- true only when the page reaches
    the group's true total, not merely the crawl
    bound -- the honoured page size, the walking
    facts, the neighbouring cursors, and the
    hits (serialised by their own face). The
    code group additionally carries its match
    totals, after the contracted fields, exactly
    as S-216's group shape carries them."""
    payload = {
        "query": query,
        "type": kind,
        "total": total,
        "returned": page.returned,
        "complete": page.complete and page.total >= total,
        "per_page": page.per_page,
        "has_next": page.has_next,
        "has_previous": page.has_previous,
        "next_cursor": page.next_cursor,
        "previous_cursor": page.previous_cursor,
        "results": list(results),
    }
    if kind == "code":
        payload["total_matches"] = total_matches
        payload["total_matched_lines"] = total_matched_lines
    return payload


# ------------------------------------------------------------------
# The API face
# ------------------------------------------------------------------

class PublicSearchAPI:
    """The S-245 executor: S-216's search face
    ratified as the public `/api/v1/search`
    contract -- the whole search through S-238's
    door over S-216's own face, and one group at
    a time paged by S-239's cursor engine over
    the banked group executors (seven since S-287
    added the wiki and gists groups). It owns no
    index, no grammar, and no permission law of
    its own, so the public contract cannot drift
    from the web search it stands behind."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        accounts: AccountStore,
        repositories: RepositoryStore,
        organizations: OrganizationStore,
        audit=None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._auth = ApiAuthenticator(
            conn, accounts, repositories, audit=audit,
            time_fn=time_fn)
        self._face = SearchAPI(conn, repositories, organizations)
        self._repositories = RepositorySearch(conn, repositories)
        self._people = PeopleSearch(conn, organizations)
        self._commits = CommitSearch(conn, repositories)
        self._code = CodeSearch(conn, repositories)
        self._issues = IssuePRSearch(conn, repositories)
        self._wiki_gists = WikiGistSearch(conn, repositories)

    # -- shared judgements --------------------------------
    def _caller(self, header: object) -> ApiIdentity:
        """The caller of one call, through S-238's
        door alone: a missing header is the
        anonymous caller; its refusals ride this
        face's error verbatim (reason and
        detail)."""
        try:
            return self._auth.resolve_caller(header, required=False)
        except ApiAuthError as exc:
            raise PublicSearchAPIError(
                exc.reason, str(exc)) from None

    # -- the whole search ----------------------------------
    def search(self, header: object, query: object = "", *,
               types: object = None,
               per_group_limit: int = DEFAULT_GROUP_LIMIT,
               ) -> dict:
        """One whole search as the public contract
        answers it: S-216's payload (`query`,
        `groups`) unchanged, for the caller the
        door resolved -- the anonymous caller when
        no header rides along. Every refusal of
        the door and of the engine rides this
        face's error with its reason verbatim."""
        identity = self._caller(header)
        try:
            return self._face.search(
                identity.user, query, types=types,
                per_group_limit=per_group_limit)
        except SearchAPIError as exc:
            raise PublicSearchAPIError(
                exc.reason, str(exc)) from None

    def search_json(self, header: object, query: object = "", *,
                    types: object = None,
                    per_group_limit: int = DEFAULT_GROUP_LIMIT,
                    ) -> str:
        """`search`, rendered as a JSON text with
        sorted keys -- the wire form of the
        payload."""
        return to_json(self.search(
            header, query, types=types,
            per_group_limit=per_group_limit))

    # -- one group, paged ----------------------------------
    def _run_group(self, kind: str, viewer: User | None,
                   text: str, pattern: str):
        """One group's full filtered answer through
        its own banked executor, at the executor's
        own bound: (hits, total) -- and, for code,
        its match totals. The executors judge
        permission through S-209 before reading
        anything private, exactly as they do for
        S-213's fan-out."""
        if kind == "repositories":
            found = self._repositories.search_counted(
                viewer, text, limit=GROUP_LIMIT)
            return found.hits, found.total, None, None
        if kind == "people":
            found = self._people.search_counted(
                viewer, text, limit=GROUP_LIMIT)
            return found.hits, found.total, None, None
        if kind == "commits":
            found = self._commits.search_counted(
                viewer, text, limit=GROUP_LIMIT)
            return found.hits, found.total, None, None
        if kind == "code":
            found = self._code.search_counted(
                viewer, pattern, limit=GROUP_LIMIT)
            return (found.hits, found.total_files,
                    found.total_matches, found.total_matched_lines)
        if kind == "wiki":
            found_w = self._wiki_gists.search_wiki_counted(
                viewer, text, limit=GROUP_LIMIT)
            return found_w.hits, found_w.total, None, None
        if kind == "gists":
            found_g = self._wiki_gists.search_gists_counted(
                viewer, text, limit=GROUP_LIMIT)
            return found_g.hits, found_g.total, None, None
        found = self._issues.search_counted(viewer, text)
        return found.hits, found.total, None, None

    def search_group_page(self, header: object,
                          query: object = "", group: object = None,
                          *, per_page: int = DEFAULT_PAGE_SIZE,
                          cursor: str | None = None) -> dict:
        """One page of one group of one search,
        crawled by cursor (S-239): the group is
        re-run through its own executor and
        re-filtered for this caller on every call,
        then paged by position in its filtered
        order. *group* names the group (its
        canonical name or any alias its own page
        teaches). An empty query is the landing
        state and pages an empty group; a
        words-less non-empty query is refused
        `query_invalid`, exactly as the engine
        refuses it. The payload is
        `group_page_to_dict`'s shape."""
        identity = self._caller(header)
        viewer = identity.user
        if not isinstance(group, str) or (
                group.strip().lower() not in TYPE_ALIASES):
            raise PublicSearchAPIError(
                "query_invalid", _GROUP_INVALID)
        kind = TYPE_ALIASES[group.strip().lower()]
        try:
            parsed = parse_global_query(query)
        except GlobalSearchError as exc:
            raise PublicSearchAPIError(
                exc.reason, str(exc)) from None
        total = 0
        total_matches = None
        total_matched_lines = None
        hits: tuple = ()
        if not parsed.is_empty:
            if not parsed.terms:
                raise PublicSearchAPIError(
                    "query_invalid",
                    "A global search needs words to hunt for.")
            try:
                hits, total, total_matches, total_matched_lines = (
                    self._run_group(
                        kind, viewer, _terms_text(parsed.terms),
                        _pattern_text(parsed.terms)))
            except _BACKEND_ERRORS as exc:
                raise PublicSearchAPIError(
                    getattr(exc, "reason", "query_invalid"),
                    str(exc)) from None
        viewer_key = (
            viewer.username_lower if viewer is not None
            else "anonymous")
        digest = hashlib.sha256(
            parsed.raw.encode("utf-8")).hexdigest()
        context = f"search:{kind}:{viewer_key}:{digest}"
        try:
            page = paginate(
                list(enumerate(hits)), key=lambda pair: pair[0],
                per_page=per_page, cursor=cursor,
                context=context, descending=False)
        except ApiPaginationError as exc:
            raise PublicSearchAPIError(
                exc.reason, str(exc)) from None
        results = [hit_to_dict(kind, hit) for _, hit in page.items]
        return group_page_to_dict(
            parsed.raw, kind, page, total, results,
            total_matches=total_matches,
            total_matched_lines=total_matched_lines)


def render_search_api_page() -> str:
    """The search API, in plain words, where a
    script's author finds it: the whole search as
    data, one group at a time crawled by cursor,
    the same permission filtering as the web's
    own search, and refusals in the one problem
    format. Every value escaped through S-010."""
    parts = [
        "<h1>Search API</h1>",
        "<p>Scripts search under /api/v1: GET the "
        "search resource to run one global search "
        "and read its typed groups as data -- the "
        "query as typed, then one group per kind "
        "searched (repositories, people, commits, "
        "code, issues), each with its own filtered "
        "total, returned count and complete flag; "
        "and page one group at a time by cursor "
        "when a script needs more than the "
        "per-group cap, following the page's own "
        "next cursor until the group is complete. "
        "Totals are never summed across groups.</p>",
        "<p>Every call is judged exactly as the "
        "web judges the same search: the caller "
        "resolves through the API door (S-238) -- "
        "no credential reads as the web's "
        "anonymous -- and every group is executed "
        "by the same engine the search page uses, "
        "with the same permission filtering "
        "(S-209): a repository the caller cannot "
        "read contributes no hit, no title, no "
        "snippet and no count. A cursor names a "
        "position in one query's filtered order "
        "for one caller; it grants nothing, and "
        "carrying it to another group, another "
        "query or another caller is refused. "
        "Searching is a read: it records no "
        "recent searches and audits nothing.</p>",
        "<p>Refusals speak the one problem format "
        "(S-240): type, title, status, detail and "
        "error id, with the engine's own reasons "
        "-- query_invalid for a search that "
        "cannot be understood, cursor_invalid for "
        "a cursor that does not name a page of "
        "the group it is carried to.</p>",
    ]
    return "\n".join(parts)
