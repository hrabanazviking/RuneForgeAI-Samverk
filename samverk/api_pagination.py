"""API pagination and conditional requests (S-239).

Cursor pagination, `Link` headers, ETag /
`If-None-Match`; acceptance: a full crawl of a
large repo uses bounded requests. S-237's contract
named this slice as the builder of the API's
paging law, and the landed faces stated the gap
honestly until it landed (S-231: "there is
deliberately no paging cursor here"). This module
is that law, in one place, for every face.

- **Keyset cursors over a stable ordering.** A
  cursor names the last key a page returned, in
  the collection's one stable order (the events
  face: event id, newest first). The next page is
  the rows strictly beyond that key -- never an
  offset -- so a row inserted at the head of the
  collection while a crawl is running neither
  repeats nor skips a row of the crawl already
  under way: the crawl test in the battery proves
  exactly that, page by page. Page size is
  bounded (default 30, at most 100): every
  response carries at most that many rows, so a
  full crawl of a large repository is a known
  number of bounded requests -- the total is
  stated on the first page and the request count
  is its ceiling division, never an open-ended
  stream and never one giant answer.
- **A cursor is a position, never a credential.**
  It is an opaque, versioned encoding of one key
  and the context that minted it (which feed, of
  which subject). It grants nothing: permission
  filtering (S-190 through the faces' own stores)
  runs in full before paging on every request, so
  a cursor replayed by a stranger is judged
  against the stranger's own filtered list, and a
  cursor carried to a different feed is refused
  `cursor_invalid` -- contexts never cross. A
  cursor that does not decode, is not the current
  version, or names a key of the wrong type is
  the same one refusal; a caller learns their
  cursor failed, never which part.
- **Link headers walk the crawl.** Every page
  answers with the RFC 8288 links a script
  follows instead of doing arithmetic: `first`
  always, `prev` when a page stands before this
  one, `next` when one stands after, and `last`
  until the crawl arrives there. The links carry
  the page size and, where a page is not the
  first, its cursor; the first page's link
  carries no cursor, because no cursor is what
  the first page means.
- **Conditional requests end unchanged crawls
  early.** A payload's strong ETag is the SHA-256
  of its canonical JSON (S-237's json-utf8 rule:
  sorted keys, UTF-8), quoted as HTTP requires.
  `If-None-Match` is judged with the standard's
  weak comparison over the header's tag list --
  a held tag, a list containing it, a weak
  `W/`-prefixed form of it, or `*` all match --
  and a match answers 304 with no body: a crawler
  re-checking a feed it already holds pays one
  small refusal-shaped answer instead of the
  page again. A changed payload hashes
  differently and answers 200 in full; the
  battery proves both directions.
- **The faces as they stand.** S-231's events
  face crawls by cursor through this engine
  (`user_events_page`, `repo_events_page`,
  `public_events_page`, and `get_event_conditional`
  for the single event), filtering first and
  paging second, so a page can no more leak than
  the capped feed could. S-216's search groups
  keep their cap and `complete` flag until S-245
  ratifies search as the public contract and
  gives each group's hits their paging keys --
  this module does not pretend a search cursor
  exists before then.
- **Refusals are S-237's shape.** Every refusal
  is an `ApiPaginationError` with a
  machine-branchable reason, rendered by
  `error_to_dict` as exactly `error` and
  `detail` -- the contract's current refusal
  fields, pinned against `CURRENT_ERROR_FIELDS`;
  S-240's problem format is future work and is
  not claimed.
- **A read that witnesses nothing.** Paging and
  conditioning write no row and audit nothing:
  they are arithmetic over answers the faces
  already judged. No migration (schema stays
  94), no taxonomy event (129 stand: 33 auth /
  83 repo / 13 admin).
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from .api_contract import CURRENT_ERROR_FIELDS
from .escaping import escape_html_text

__all__ = [
    "CURSOR_VERSION", "DEFAULT_PAGE_SIZE", "MAX_PAGE_SIZE",
    "PAGINATION_PATH", "ApiPaginationError", "ConditionalResponse",
    "Page", "check_page_size", "conditional_response",
    "decode_cursor", "encode_cursor", "error_to_dict", "etag_for",
    "etag_for_text", "if_none_match_matches", "link_header",
    "page_to_dict", "page_url", "paginate", "parse_if_none_match",
    "render_api_pagination_page",
]

PAGINATION_PATH = "/api/pagination"
CURSOR_VERSION = 1
DEFAULT_PAGE_SIZE = 30
MAX_PAGE_SIZE = 100

_CURSOR_INVALID = "That cursor does not name a page of this collection."
_TOKEN_SHAPE = re.compile(r"^[A-Za-z0-9_\-=]+$")
_TAG_SHAPE = re.compile(r'^(?:W/)?"[^"]*"$')


class ApiPaginationError(ValueError):
    """One refused paging or conditional call: a
    machine-branchable reason with its human detail."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def error_to_dict(exc: ApiPaginationError) -> dict:
    """One refusal as data, in S-237's current
    shape: the reason and the detail, nothing else."""
    return {"error": exc.reason, "detail": str(exc)}


# ------------------------------------------------------------------
# Cursors -- a versioned position in one context
# ------------------------------------------------------------------

def _check_key(key: object) -> int | str:
    if isinstance(key, bool) or not isinstance(key, (int, str)):
        raise ApiPaginationError("cursor_invalid", _CURSOR_INVALID)
    if isinstance(key, str) and not key:
        raise ApiPaginationError("cursor_invalid", _CURSOR_INVALID)
    return key


def encode_cursor(key: object, context: str = "") -> str:
    """Mint the cursor naming *key* as the last key
    seen in *context*: an opaque, URL-safe encoding
    of the version, the context, and the key, and
    of nothing else -- no identity, no permission,
    no timestamp rides in a cursor."""
    key = _check_key(key)
    if not isinstance(context, str):
        raise ApiPaginationError("cursor_invalid", _CURSOR_INVALID)
    raw = json.dumps(
        {"v": CURSOR_VERSION, "ctx": context, "k": key},
        sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(token: object, context: str = "",
                  *, key_type: type | None = None) -> int | str:
    """The key a cursor names, judged strictly: the
    token must decode to exactly the current
    version's shape, minted for exactly *context*,
    holding a key of the expected kind. Every
    failure -- garbage, an old version, another
    feed's cursor, a key of the wrong type -- is
    the one refusal `cursor_invalid`."""
    if (not isinstance(token, str) or not token
            or not _TOKEN_SHAPE.match(token)):
        raise ApiPaginationError("cursor_invalid", _CURSOR_INVALID)
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, binascii.Error, UnicodeDecodeError):
        raise ApiPaginationError(
            "cursor_invalid", _CURSOR_INVALID) from None
    if not isinstance(data, dict) or set(data) != {"v", "ctx", "k"}:
        raise ApiPaginationError("cursor_invalid", _CURSOR_INVALID)
    if data["v"] != CURSOR_VERSION or data["ctx"] != context:
        raise ApiPaginationError("cursor_invalid", _CURSOR_INVALID)
    key = _check_key(data["k"])
    if key_type is not None and type(key) is not key_type:
        raise ApiPaginationError("cursor_invalid", _CURSOR_INVALID)
    return key


# ------------------------------------------------------------------
# The paging engine
# ------------------------------------------------------------------

def check_page_size(value: object) -> int:
    """One page size, judged as the faces judge a
    limit: an integer inside S-239's bounds or the
    refusal `page_size_invalid` -- a contract never
    silently clamps a caller's stated bound."""
    if (isinstance(value, bool) or not isinstance(value, int)
            or value < 1 or value > MAX_PAGE_SIZE):
        raise ApiPaginationError(
            "page_size_invalid",
            f"per_page must be an integer between 1 and "
            f"{MAX_PAGE_SIZE}.")
    return value


@dataclass(frozen=True)
class Page:
    """One page of a paged collection: the rows,
    the filtered total tallied before paging, the
    honoured page size, whether pages stand before
    or after this one, and the cursors that name
    the neighbouring pages. `previous_cursor` and
    `last_cursor` are None when the page they name
    is the first page -- no cursor is what the
    first page means, and `has_previous` says
    whether a previous page exists at all."""
    items: tuple
    total: int
    per_page: int
    start: int
    has_next: bool
    has_previous: bool
    next_cursor: str | None
    previous_cursor: str | None
    last_cursor: str | None
    is_last: bool

    @property
    def returned(self) -> int:
        return len(self.items)

    @property
    def complete(self) -> bool:
        """True when this page reaches the end of
        the collection -- the envelope's word,
        kept: nothing stands beyond this page."""
        return not self.has_next


def paginate(items, *, key, per_page: int = DEFAULT_PAGE_SIZE,
             cursor: str | None = None, context: str = "",
             descending: bool = True) -> Page:
    """One bounded page of *items*, which the
    caller has already permission-filtered and
    holds in the collection's one stable order.
    *key* reads each row's paging key; the keys
    must be unique and strictly monotonic in that
    order, or the collection is refused
    `ordering_invalid` -- a cursor over an unstable
    order would repeat and skip rows silently, so
    the engine proves the order instead of trusting
    it. With *cursor*, the page is the rows
    strictly beyond the cursor's key: rows inserted
    ahead of that key since the cursor was minted
    do not move this page."""
    per_page = check_page_size(per_page)
    seq = list(items)
    keys = [_check_key(key(row)) for row in seq]
    for before, after in zip(keys, keys[1:]):
        if descending and not before > after:
            raise ApiPaginationError(
                "ordering_invalid",
                "The collection is not in its stable "
                "descending order, so no cursor can "
                "name a page of it.")
        if not descending and not before < after:
            raise ApiPaginationError(
                "ordering_invalid",
                "The collection is not in its stable "
                "ascending order, so no cursor can "
                "name a page of it.")
    start = 0
    if cursor is not None:
        mark = decode_cursor(
            cursor, context,
            key_type=type(keys[0]) if keys else None)
        start = len(seq)
        for index, held in enumerate(keys):
            if (descending and held < mark) or (
                    not descending and held > mark):
                start = index
                break
    page_items = tuple(seq[start:start + per_page])
    end = start + len(page_items)
    has_next = end < len(seq)
    has_previous = start > 0
    next_cursor = (
        encode_cursor(keys[end - 1], context) if has_next else None)
    previous_cursor = None
    if has_previous:
        prev_start = max(0, start - per_page)
        if prev_start > 0:
            previous_cursor = encode_cursor(
                keys[prev_start - 1], context)
    last_start = (
        ((len(seq) - 1) // per_page) * per_page if seq else 0)
    last_cursor = None
    if last_start > 0:
        last_cursor = encode_cursor(keys[last_start - 1], context)
    return Page(
        items=page_items, total=len(seq), per_page=per_page,
        start=start, has_next=has_next, has_previous=has_previous,
        next_cursor=next_cursor, previous_cursor=previous_cursor,
        last_cursor=last_cursor, is_last=start == last_start)


def page_to_dict(page: Page, serialised_items) -> dict:
    """One page as JSON-safe data: the filtered
    total, how many rows this page returned,
    whether the crawl is complete on this page,
    the honoured page size, the walking facts, the
    neighbouring cursors, and the rows themselves
    (already serialised by their own face)."""
    return {
        "total": page.total,
        "returned": page.returned,
        "complete": page.complete,
        "per_page": page.per_page,
        "has_next": page.has_next,
        "has_previous": page.has_previous,
        "next_cursor": page.next_cursor,
        "previous_cursor": page.previous_cursor,
        "items": list(serialised_items),
    }


# ------------------------------------------------------------------
# Link headers -- the crawl a script follows
# ------------------------------------------------------------------

def page_url(base_url: str, *, cursor: str | None = None,
             per_page: int | None = None) -> str:
    """One page's address: *base_url* with any
    query it already carries kept, its old `cursor`
    and `per_page` parameters replaced by this
    page's, and no cursor parameter at all when
    *cursor* is None -- the first page's address."""
    parts = urlsplit(base_url)
    pairs = [
        (name, value)
        for name, value in parse_qsl(
            parts.query, keep_blank_values=True)
        if name not in ("cursor", "per_page")]
    if per_page is not None:
        pairs.append(("per_page", str(per_page)))
    if cursor is not None:
        pairs.append(("cursor", cursor))
    return urlunsplit((
        parts.scheme, parts.netloc, parts.path,
        urlencode(pairs, quote_via=quote), parts.fragment))


def link_header(base_url: str, page: Page) -> str:
    """The `Link` header value for one page
    (RFC 8288): `first` always, `prev` when a page
    stands before this one, `next` when one stands
    after, and `last` until the crawl arrives at
    the last page. A script follows these links
    and never constructs a cursor itself."""
    links = []

    def add(url: str, rel: str) -> None:
        links.append(f'<{url}>; rel="{rel}"')

    add(page_url(base_url, per_page=page.per_page), "first")
    if page.has_previous:
        add(page_url(base_url, cursor=page.previous_cursor,
                     per_page=page.per_page), "prev")
    if page.has_next:
        add(page_url(base_url, cursor=page.next_cursor,
                     per_page=page.per_page), "next")
    if page.total > 0 and not page.is_last:
        add(page_url(base_url, cursor=page.last_cursor,
                     per_page=page.per_page), "last")
    return ", ".join(links)


# ------------------------------------------------------------------
# ETags and conditional requests
# ------------------------------------------------------------------

def _canonical_bytes(payload: object) -> bytes:
    try:
        text = json.dumps(
            payload, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"))
    except (TypeError, ValueError):
        raise ApiPaginationError(
            "payload_not_json",
            "An ETag can only be taken over JSON-safe "
            "data.") from None
    return text.encode("utf-8")


def etag_for(payload: object) -> str:
    """The strong ETag of one JSON-safe payload:
    the quoted SHA-256 of its canonical JSON, so
    the same payload hashes identically whoever
    serialises it, and any change -- one field,
    one row -- hashes differently."""
    digest = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    return f'"{digest}"'


def etag_for_text(text: str) -> str:
    """The strong ETag of one wire text (a face's
    JSON rendering, byte for byte): the quoted
    SHA-256 of its UTF-8 bytes."""
    if not isinstance(text, str):
        raise ApiPaginationError(
            "payload_not_json",
            "An ETag can only be taken over text.")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f'"{digest}"'


def _normalise_tag(tag: str) -> str:
    """One entity tag in comparison form: the weak
    prefix removed, because `If-None-Match` is
    judged by weak comparison (RFC 9110)."""
    tag = tag.strip()
    if tag.startswith("W/"):
        tag = tag[len("W/"):]
    return tag


def parse_if_none_match(header: object) -> tuple[bool, tuple[str, ...]]:
    """One `If-None-Match` header read as (star,
    tags): whether it carries `*`, and its
    well-formed entity tags in comparison form.
    A malformed entry is skipped, never guessed
    at; a header of the wrong type is refused
    `header_invalid`."""
    if header is None:
        return (False, ())
    if not isinstance(header, str):
        raise ApiPaginationError(
            "header_invalid",
            "If-None-Match must be a header string.")
    star = False
    tags: list[str] = []
    for entry in header.split(","):
        entry = entry.strip()
        if entry == "*":
            star = True
        elif _TAG_SHAPE.match(entry):
            tags.append(_normalise_tag(entry))
    return (star, tuple(tags))


def if_none_match_matches(header: object, etag: str) -> bool:
    """Whether an `If-None-Match` header matches
    the current representation's *etag*: `*`
    matches any current representation, and any
    listed tag matching under weak comparison --
    including a `W/`-prefixed form of the current
    strong tag -- ends the request as unchanged.
    No header, or no matching tag, is no match."""
    if header is None:
        return False
    star, tags = parse_if_none_match(header)
    if star:
        return True
    return _normalise_tag(etag) in tags


@dataclass(frozen=True)
class ConditionalResponse:
    """The answer to one conditional request: the
    status (200 with the payload, 304 without
    one), the representation's ETag either way,
    and the payload itself when it is owed."""
    status: int
    etag: str
    payload: object = None

    @property
    def not_modified(self) -> bool:
        return self.status == 304


def conditional_response(payload: object,
                         if_none_match: object = None,
                         *, etag: str | None = None) -> ConditionalResponse:
    """Answer one conditional GET: the payload's
    ETag (taken here, or *etag* when the caller
    already holds it), judged against the caller's
    `If-None-Match`. A match is 304 and carries no
    payload -- the caller already holds these
    exact bytes; anything else is 200 with the
    payload in full."""
    tag = etag if etag is not None else etag_for(payload)
    if if_none_match_matches(if_none_match, tag):
        return ConditionalResponse(status=304, etag=tag, payload=None)
    return ConditionalResponse(status=200, etag=tag, payload=payload)


# ------------------------------------------------------------------
# The help page
# ------------------------------------------------------------------

def render_api_pagination_page(link: str | None = None,
                               etag: str | None = None) -> str:
    """How a script crawls, in plain words: the
    bounded page, the cursor that names a position
    and nothing more, the links that walk a crawl,
    and the conditional request that ends an
    unchanged re-check early -- with a live
    example's header values when they ride along.
    Every value escaped through S-010."""
    parts = [
        "<h1>API pagination and conditional requests</h1>",
        "<p>Lists in /api/v1 are crawled, never "
        "dumped: ask for a page (at most "
        f"{MAX_PAGE_SIZE} rows, {DEFAULT_PAGE_SIZE} "
        "by default) and the answer carries that "
        "page, the filtered total, and a cursor "
        "naming the last row it returned. Send the "
        "cursor back for the next page. A cursor "
        "names a position in one list only -- it is "
        "not a credential, it is refused by any "
        "other list, and permission is judged in "
        "full before every page.</p>",
        "<p>Each page also answers with a Link "
        "header -- first, prev, next, last -- so a "
        "script follows links instead of building "
        "cursors. Rows added while a crawl runs do "
        "not move the pages still to come: nothing "
        "already passed repeats, and nothing ahead "
        "is skipped.</p>",
        "<p>Every payload carries a strong ETag. "
        "Send it back as If-None-Match when "
        "re-checking: if the answer is unchanged "
        "the reply is 304 with no body, and a "
        "changed answer returns in full with its "
        "new ETag.</p>",
    ]
    if link is not None:
        parts.append(
            "<p>One page's Link header: "
            f"{escape_html_text(link)}</p>")
    if etag is not None:
        parts.append(
            "<p>One payload's ETag: "
            f"{escape_html_text(etag)}</p>")
    return "\n".join(parts)
