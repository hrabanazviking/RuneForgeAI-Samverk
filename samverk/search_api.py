"""Search API (S-216).

The same engine behind Part XII endpoints with
identical permission filtering — Part X's programmatic
face over S-213's global search. S-245 will ratify
this shape as the public `/api/v1` search contract in
Part XII; this slice lands the contract itself: one
call, the global grammar, typed groups, and counts a
script can trust, with no second engine anywhere.

- **The same engine, literally.** `SearchAPI` owns
  no index, no parser, and no filter: it constructs
  S-213's `GlobalSearch` and delegates every search
  to it. The query grammar (free words plus `type:`
  groups), the per-group executors, and the group
  order are S-213's own, so the API cannot drift
  from the web page it stands behind — a query means
  the same thing in both mouths, and a refusal here
  carries the engine's own reason, verbatim.
- **Identical permission filtering.** Each group is
  executed by its own banked executor, which
  resolves the viewer's visible repositories
  through S-209's one resolution (over S-054's
  `can_read`) before any private fact is read. This
  module reads no repository, profile, index, or
  history row itself and adds no filtering of its
  own — and removes none: an unreadable repository
  contributes no hit, no title, no snippet, and no
  count, exactly as on the page (absence, never
  redaction). The battery proves the S-209
  equivalence over the payload itself: a stranger's
  answer over a world containing a private
  repository equals, group by group, the answer
  over a world where it was never created.
- **A machine shape, honestly bounded.** The
  payload is plain JSON-safe data (dicts, lists,
  strings, numbers, booleans, nulls — it round-trips
  through `json` unchanged): the query as typed,
  then one group per kind searched, in S-213's
  fixed order, each carrying its own filtered
  `total` tallied before the per-group cap, the
  `returned` count the cap allowed, and a
  `complete` flag that says plainly whether the cap
  truncated the group. Totals are never summed
  across groups — a combined number would mix
  counts kept behind different permission
  boundaries (the S-213 law). The code group
  additionally carries its match totals. There is
  still no paging cursor here: S-239's engine
  (samverk/api_pagination.py) has landed and
  the events face crawls by cursor through it,
  but this face's groups keep their cap and
  `complete` flag until S-245 ratifies search
  as the public contract and gives each
  group's hits their paging keys — a caller
  who needs more than the cap (default 10, at
  most 100, the engine's own limits) is told
  so by `complete`, never silently
  short-changed.
- **Stateless, like an API should be.** The engine
  is built without a recent-search store, so an API
  search records nothing — a script's queries never
  land in the searcher's web recents (S-213's
  recents are the page's memory, not the API's).
  Searching is a read, so it audits nothing either
  (the S-209/S-213 pattern). No migration, no audit
  event of its own: schema stays 84 and 123 events
  stand — 31 auth / 79 repo / 13 admin.
- **Refusals a script can branch on.** A refused
  search raises `SearchAPIError` carrying the
  engine's reason verbatim (`query_invalid` for a
  malformed query, an unknown qualifier, a
  words-less or group-less selection, or a bad
  per-group limit), and `error_to_dict` renders any
  refusal as `{"error": reason, "detail": message}`.
  S-240's one problem format (type, title,
  status, detail, error id), rendered through
  samverk/error_shape.py, is the shape this
  face now emits -- the same shape every
  endpoint and the web UI's refusals use.
- **Anonymous callers search as the web's
  anonymous.** A missing viewer is the engine's own
  anonymous: public facts only, through the same
  `can_read` gate — never a back door around it.
"""

from __future__ import annotations

import json
import sqlite3

from .accounts import User
from .global_search import (
    DEFAULT_GROUP_LIMIT, GlobalSearch, GlobalSearchError,
    GlobalSearchResults, GroupResults)
from .error_shape import problem_from_error, problem_to_dict
from .organizations import OrganizationStore
from .repositories import RepositoryStore

__all__ = [
    "SearchAPI", "SearchAPIError", "error_to_dict",
    "group_to_dict", "hit_to_dict", "results_to_dict",
    "results_to_json",
]


class SearchAPIError(ValueError):
    """One refused API search: the engine's own
    reason, carried verbatim, with its message."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def error_to_dict(exc: SearchAPIError) -> dict:
    """One refusal as data, in S-240's one problem
    format (samverk/error_shape.py): type, title,
    status, detail, error_id -- nothing else."""
    return problem_to_dict(problem_from_error(exc))


# ------------------------------------------------------------------
# Serialisers — one hit, one group, one search, as data
# ------------------------------------------------------------------

def _repository_hit(hit) -> dict:
    return {
        "repository": hit.full_name,
        "owner": hit.owner,
        "name": hit.repo,
        "description": hit.description,
        "visibility": hit.visibility,
        "topics": list(hit.topics),
        "created_at": hit.created_at,
        "matched_fields": list(hit.matched_fields),
    }


def _people_hit(hit) -> dict:
    avatar = None
    if hit.avatar_filename is not None:
        avatar = {"filename": hit.avatar_filename,
                  "alt": hit.avatar_alt}
    return {
        "kind": hit.kind,
        "handle": hit.handle,
        "display_name": hit.display_name,
        "bio": hit.bio,
        "website": hit.website,
        "avatar": avatar,
        "created_at": hit.created_at,
        "matched_fields": list(hit.matched_fields),
        "organizations": list(hit.org_names),
        "member_count": hit.member_count,
    }


def _commit_hit(hit) -> dict:
    return {
        "repository": hit.full_name,
        "oid": hit.oid,
        "parents": list(hit.parents),
        "author_name": hit.author_name,
        "author_email": hit.author_email,
        "author_time": hit.author_time,
        "subject": hit.subject,
        "body": hit.body,
        "matched_fields": list(hit.matched_fields),
    }


def _code_hit(hit) -> dict:
    return {
        "repository": hit.full_name,
        "path": hit.path,
        "language": hit.language,
        "is_pointer": bool(hit.is_pointer),
        "commit_oid": hit.commit_oid,
        "match_count": hit.match_count,
        "matched_lines": hit.matched_lines,
        "snippets": [
            {"start_line": snippet.start_line,
             "lines": [
                 {"number": line.number, "text": line.text,
                  "is_match": line.is_match,
                  "spans": [list(span) for span in line.spans]}
                 for line in snippet.lines]}
            for snippet in hit.snippets],
    }


def _issue_hit(hit) -> dict:
    return {
        "repository": hit.full_name,
        "number": hit.number,
        "kind": hit.kind,
        "title": hit.title,
        "state": hit.state,
        "state_words": hit.state_words,
        "is_draft": hit.is_draft,
        "author": hit.author_lower,
        "created_at": hit.created_at,
        "updated_at": hit.updated_at,
        "comment_count": hit.comment_count,
    }


_HIT_SERIALISERS = {
    "repositories": _repository_hit,
    "people": _people_hit,
    "commits": _commit_hit,
    "code": _code_hit,
    "issues": _issue_hit,
}


def hit_to_dict(kind: str, hit) -> dict:
    """One hit of group *kind* as JSON-safe data:
    exactly the facts that group's own page shows,
    in data — no HTML, no escaping (S-010 is the
    page's law; data carries the raw values)."""
    return _HIT_SERIALISERS[kind](hit)


def group_to_dict(group: GroupResults) -> dict:
    """One typed group as data: its kind, its own
    filtered total tallied before the cap, how many
    hits the cap returned, whether the group is
    complete under that cap, and the hits. The code
    group additionally carries its match totals."""
    payload = {
        "type": group.kind,
        "total": group.total,
        "returned": len(group.hits),
        "complete": group.total <= len(group.hits),
        "results": [hit_to_dict(group.kind, hit)
                    for hit in group.hits],
    }
    if group.kind == "code":
        payload["total_matches"] = group.total_matches
        payload["total_matched_lines"] = \
            group.total_matched_lines
    return payload


def results_to_dict(results: GlobalSearchResults) -> dict:
    """One whole search as data: the query as typed
    and one group per kind searched, in the fixed
    group order. Deliberately no combined total —
    totals are per group, never mixed (S-213). An
    empty query carries no groups: the landing
    state, said as data."""
    return {
        "query": results.query,
        "groups": [group_to_dict(group)
                   for group in results.groups],
    }


def results_to_json(results: GlobalSearchResults) -> str:
    """One whole search as a JSON text: the payload
    of `results_to_dict`, keys sorted so the same
    search renders byte-identically twice."""
    return json.dumps(
        results_to_dict(results),
        ensure_ascii=False, sort_keys=True)


# ------------------------------------------------------------------
# The API face
# ------------------------------------------------------------------

class SearchAPI:
    """The S-216 executor: S-213's `GlobalSearch`,
    built without a recent-search store (API calls
    record nothing), answering in data. It owns no
    index and reads no row itself — every search is
    the engine's own call, so permission filtering
    is identical by construction, not by copy."""

    def __init__(self, conn: sqlite3.Connection,
                 repositories: RepositoryStore,
                 organizations: OrganizationStore):
        self._engine = GlobalSearch(
            conn, repositories, organizations)

    def search(self, viewer: User | None, query: object = "",
               *, types: object = None,
               per_group_limit: int = DEFAULT_GROUP_LIMIT,
               ) -> dict:
        """Execute one search and answer its payload:
        `results_to_dict` of the engine's results.
        *types*, when given, replaces the text's
        `type:` selection, exactly as the engine's
        own call allows. Every engine refusal is
        re-raised as `SearchAPIError` with the
        engine's reason verbatim."""
        try:
            results = self._engine.search(
                viewer, query, types=types,
                per_group_limit=per_group_limit)
        except GlobalSearchError as exc:
            raise SearchAPIError(
                exc.reason, str(exc)) from None
        return results_to_dict(results)

    def search_json(self, viewer: User | None,
                    query: object = "", *,
                    types: object = None,
                    per_group_limit: int = DEFAULT_GROUP_LIMIT,
                    ) -> str:
        """`search`, rendered as a JSON text with
        sorted keys — the wire form of the payload."""
        return json.dumps(
            self.search(viewer, query, types=types,
                        per_group_limit=per_group_limit),
            ensure_ascii=False, sort_keys=True)
