"""User and org search (S-211).

By name and username, with profile cards — Part X's
people face, beside S-210's repository search.
Where S-210 finds the repository, this slice finds
who owns it: a person by username and display name,
an organization by name and display name, each
returned as a profile card carrying exactly what
their public profile says about them.

- **One query line, free text plus qualifiers.**
  Free-text terms are matched case-insensitively
  as substrings against three fields of each
  subject — the handle (username for a person,
  name for an organization), the display name,
  and the bio — and every term must hold in at
  least one field (AND across terms, the Part X
  composition law). A double-quoted phrase is
  one term, matched as a phrase. The qualifiers
  narrow by exact fact: `type:user` / `type:org`
  (the subject kind; `users` / `orgs` spellings
  accepted), and `sort:` (`name-asc` — the
  default, handle order — `name-desc`,
  `created-asc`, `created-desc`). A leading `-`
  negates one `type:` qualifier (S-210's negation
  shape). An explicit `kind=` argument is an
  additional qualifier ANDed with the text; an
  explicit `sort=` overrides the text's.
- **Unknown qualifiers fail closed.** A token
  shaped like a qualifier whose name is outside
  this grammar is refused `query_invalid`, naming
  it — never silently dropped (a dropped
  qualifier widens the search, the S-118 law) and
  never folded into the free text. Empty values,
  unterminated quotes, control characters, an
  over-long query, a type or sort outside its
  vocabulary, and a bad limit are the same
  refusal. A qualifier naming a kind with no
  subjects is not an error: it matches nothing.
- **An email is not a search field, ever.**
  Account emails are private facts: no term is
  ever matched against an email, no card carries
  one, and no count moves because of one. The
  battery proves it by planting an address whose
  domain carries the world's unique bait word.
- **Matching is pure, and says where it hit.**
  `user_matches_query` / `org_matches_query`
  judge a subject's three fields against the
  parsed query with no storage read, so the
  deciding law is testable without a database;
  `matched_fields` names the fields (`handle`,
  `name`, `bio`) in which a free-text term was
  found, so a card can say *why* it matched.
- **Visibility is filtered before anything is
  read, the S-209 law applied to people.** An
  organization is a public directory fact: every
  organization is searchable by every viewer,
  including an anonymous one. A person is
  searchable only while their account is
  `active`; a pending or suspended account
  contributes no card, no field, and no count
  to anyone except the account holder themself
  and site admins — the same equivalence S-209
  proves for repositories: a stranger's hits and
  counts over a world containing a suspended
  account equal the same search over a world
  where it was never registered. Profiles are
  loaded only for people who survive that
  filter, and enrichment (a person's
  organizations, an organization's member
  count) is computed only for subjects that
  match. Team data is never read at all by this
  slice: a secret team's name, description, and
  existence cannot leak through a profile card
  or a people count, by construction.
- **Cards carry the profile, nothing behind
  it.** A person's card is their username,
  display name, bio, avatar (with its stored
  alt text), and the names of the public
  organizations they belong to. An
  organization's card is its name, display
  name, bio, website, avatar, and member
  count. Membership names are display facts,
  never a search field: searching an
  organization's name finds the organization,
  not its members. No card carries an email,
  a status word for an active account, a team,
  or a repository permission.
- **An empty search is the directory,
  honestly.** Like S-210, a search with no
  terms and no qualifiers is a listing:
  `directory` returns it, and
  `render_people_directory_page` renders it.
  Results are capped by `limit` (default 100,
  at most 500, the Part X cap shape); the
  counted faces keep the true total beside the
  capped hits, tallied from the filtered
  subjects only, before any cap.
- **No audit event of its own, no migration.**
  Searching is a read over the account,
  profile, and organization rows. 122 events
  stand: 31 auth / 79 repo / 12 admin. Schema
  stays 82.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .accounts import User
from .escaping import escape_html_attr, escape_html_text, safe_url
from .organizations import Organization, OrganizationStore

__all__ = [
    "DEFAULT_LIMIT", "KIND_VALUES", "MAX_LIMIT", "QUALIFIER_HELP",
    "QUALIFIER_NAMES", "QUERY_MAX", "SORT_VALUES", "PeopleHit",
    "PeopleSearch", "PeopleSearchError", "PeopleSearchQuery",
    "PeopleSearchResults", "kind_word", "matched_fields",
    "matched_org_fields", "matched_user_fields", "org_matches_query",
    "parse_people_query", "render_people_directory_page",
    "render_people_search_page", "render_profile_card",
    "user_matches_query", "user_visible_to",
]

QUERY_MAX = 500
DEFAULT_LIMIT = 100
MAX_LIMIT = 500
QUALIFIER_NAMES = frozenset({"type", "sort"})
KIND_VALUES = frozenset({"user", "org"})
_TYPE_WORDS = {
    "user": "user", "users": "user",
    "org": "org", "orgs": "org",
    "organization": "org", "organizations": "org",
}
SORT_VALUES = frozenset(
    {"name-asc", "name-desc", "created-asc", "created-desc"})
DEFAULT_SORT = "name-asc"

_KIND_WORDS = {"user": "User", "org": "Organization"}
_FIELD_ORDER = ("handle", "name", "bio")

_EXTENSION_FOR_TYPE = {
    "image/png": ".png", "image/jpeg": ".jpg",
    "image/gif": ".gif", "image/webp": ".webp",
}

QUALIFIER_HELP: tuple[tuple[str, str], ...] = (
    ("type:user", "only people (accounts)"),
    ("type:org", "only organizations"),
    ("sort:name-asc", "handle, A to Z (the default)"),
    ("sort:name-desc", "handle, Z to A"),
    ("sort:created-asc", "oldest account or organization first"),
    ("sort:created-desc", "newest account or organization first"),
    ("-type:org", "a leading minus negates one type: qualifier"),
    ("free words", "words (or a \"quoted phrase\") matched "
                   "against the handle, the display name, and "
                   "the bio; every word must match somewhere. "
                   "Email addresses are never searched."),
)


class PeopleSearchError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def _invalid(message: str) -> PeopleSearchError:
    return PeopleSearchError("query_invalid", message)


def kind_word(kind: str) -> str:
    """A subject kind said in a word a person reads."""
    return _KIND_WORDS.get(kind, kind)


def _avatar_filename(sha256: str | None,
                     content_type: str | None) -> str | None:
    if not sha256 or not content_type:
        return None
    ext = _EXTENSION_FOR_TYPE.get(content_type)
    return f"{sha256}{ext}" if ext else None


# ------------------------------------------------------------------
# The parsed query
# ------------------------------------------------------------------

@dataclass(frozen=True)
class PeopleSearchQuery:
    """One people search, whole: the free-text terms
    (lowercased, in order), the exact kind qualifiers
    (canonical `user` / `org`; the `not_kinds` tuple
    is the negated qualifiers), and the ordering."""
    terms: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()
    not_kinds: tuple[str, ...] = ()
    sort: str = DEFAULT_SORT

    @property
    def is_empty(self) -> bool:
        """True when the query carries no term and no
        qualifier — the directory query."""
        return not (self.terms or self.kinds or self.not_kinds)


def _tokenise(query: str) -> list[str]:
    """Split a query line into tokens: whitespace
    separates, a double-quoted span stays inside its
    token (so `"my name"` is one term and
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


def _check_sort(value: object) -> str:
    if not isinstance(value, str) \
            or value.strip().lower() not in SORT_VALUES:
        raise _invalid(
            "The sort is one of: name-asc, name-desc, "
            "created-asc, created-desc.")
    return value.strip().lower()


def _check_kind(value: object) -> str:
    if not isinstance(value, str) \
            or value.strip().lower() not in _TYPE_WORDS:
        raise _invalid("A type is 'user' or 'org'.")
    return _TYPE_WORDS[value.strip().lower()]


def parse_people_query(query: object) -> PeopleSearchQuery:
    """Parse query text into a `PeopleSearchQuery`:
    `type:` and `sort:` qualifiers are lifted out (a
    leading `-` negates a type qualifier), and the
    remaining tokens, in order, are the free-text
    terms. An unknown qualifier-shaped token, an
    empty value, a bad vocabulary value, an
    unterminated quote, a control character, or an
    over-long query is refused `query_invalid`,
    naming the problem."""
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
    kinds: list[str] = []
    not_kinds: list[str] = []
    sort = DEFAULT_SORT
    sort_seen = False
    for token in _tokenise(query):
        negated = token.startswith("-") and len(token) > 1
        body = token[1:] if negated else token
        head, colon, value = body.partition(":")
        if colon and head.lower() in QUALIFIER_NAMES:
            name = head.lower()
            if not value:
                raise _invalid(f"The {name}: qualifier needs a value.")
            if name == "sort":
                if negated:
                    raise _invalid("The sort: qualifier cannot be negated.")
                if sort_seen:
                    raise _invalid("A search carries one sort: qualifier.")
                sort_seen = True
                sort = _check_sort(value)
            else:  # type
                clean = _check_kind(value)
                (not_kinds if negated else kinds).append(clean)
            continue
        if colon and head and all(
                c.isalnum() or c in "_-" for c in head):
            raise _invalid(
                f"The qualifier {head!r} is not part of people "
                "search. Known qualifiers: type:, sort:.")
        if negated:
            raise _invalid(
                "Only a type: qualifier can be negated.")
        if token:
            terms.append(token.lower())
    return PeopleSearchQuery(
        terms=tuple(terms), kinds=tuple(kinds),
        not_kinds=tuple(not_kinds), sort=sort)


# ------------------------------------------------------------------
# The pure judgement
# ------------------------------------------------------------------

def _fields_of(handle_lower: str, display_name: str | None,
               bio: str | None) -> dict[str, str]:
    """The three searched fields of one subject,
    lowercased for judging. An email is never a
    field of this dict — that absence is the law,
    not an oversight."""
    return {
        "handle": handle_lower,
        "name": (display_name or "").lower(),
        "bio": (bio or "").lower(),
    }


def matched_fields(fields: dict[str, str],
                   parsed: PeopleSearchQuery) -> tuple[str, ...]:
    """The fields in which at least one free-text term
    of *parsed* was found, in the canonical order
    (handle, name, bio). Empty when the query carries
    no free-text term. Pure."""
    if not parsed.terms:
        return ()
    return tuple(
        name for name in _FIELD_ORDER
        if any(term in fields[name] for term in parsed.terms))


def _matches(fields: dict[str, str], kind: str,
             parsed: PeopleSearchQuery) -> bool:
    if any(wanted != kind for wanted in parsed.kinds):
        return False
    if kind in parsed.not_kinds:
        return False
    if parsed.terms:
        haystacks = tuple(fields.values())
        for term in parsed.terms:
            if not any(term in hay for hay in haystacks):
                return False
    return True


def matched_user_fields(user: object,
                        parsed: PeopleSearchQuery) -> tuple[str, ...]:
    """`matched_fields` for a person-shaped subject
    (anything carrying `username_lower`,
    `display_name`, and `bio`)."""
    return matched_fields(
        _fields_of(user.username_lower, user.display_name,
                   user.bio), parsed)


def matched_org_fields(org: object,
                       parsed: PeopleSearchQuery) -> tuple[str, ...]:
    """`matched_fields` for an organization-shaped
    subject (anything carrying `name_lower`,
    `display_name`, and `bio`)."""
    return matched_fields(
        _fields_of(org.name_lower, org.display_name, org.bio),
        parsed)


def user_matches_query(user: object, parsed: PeopleSearchQuery) -> bool:
    """Whether a person (carrying `username_lower`,
    `display_name`, `bio`) matches *parsed*: every
    kind qualifier holds and every free-text term
    appears in at least one of the three fields.
    Pure: no storage is read here, and no email is
    ever judged — a subject object may carry one;
    it is not consulted."""
    return _matches(
        _fields_of(user.username_lower, user.display_name,
                   user.bio), "user", parsed)


def org_matches_query(org: object, parsed: PeopleSearchQuery) -> bool:
    """Whether an organization (carrying `name_lower`,
    `display_name`, `bio`) matches *parsed*. Pure."""
    return _matches(
        _fields_of(org.name_lower, org.display_name, org.bio),
        "org", parsed)


def user_visible_to(viewer: User | None, subject_id: int,
                    subject_status: str) -> bool:
    """Whether *viewer* may see a person in search at
    all: an `active` account is a directory fact for
    everyone, including an anonymous viewer; any
    other status (pending, suspended) is visible
    only to the account holder themself and to site
    admins. Pure: the filter is judged before any
    profile fact is read."""
    if subject_status == "active":
        return True
    if viewer is None:
        return False
    return bool(viewer.is_admin or viewer.id == subject_id)


def _sort_hits(hits: list["PeopleHit"],
               sort: str) -> list["PeopleHit"]:
    """Order hits by the query's sort: name sorts
    judge the canonical handle (kind as the honest
    tie-break); created sorts judge the creation
    stamp, with the name order as tie-break."""
    if sort == "name-desc":
        return sorted(
            hits, key=lambda h: (h.handle_lower, h.kind),
            reverse=True)
    if sort == "created-asc":
        return sorted(
            hits, key=lambda h: (h.created_at, h.handle_lower,
                                 h.kind))
    if sort == "created-desc":
        return sorted(
            hits, key=lambda h: (-h.created_at, h.handle_lower,
                                 h.kind))
    return sorted(hits, key=lambda h: (h.handle_lower, h.kind))


def _check_limit(limit: object) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool) \
            or limit < 1 or limit > MAX_LIMIT:
        raise _invalid(f"The limit is 1 to {MAX_LIMIT} people.")
    return limit


# ------------------------------------------------------------------
# Hits and the executor
# ------------------------------------------------------------------

@dataclass(frozen=True)
class PeopleHit:
    """One person or organization that matched, as a
    profile card: the handle, the display name and
    bio the profile states, the avatar (filename
    built from the stored hash and sniffed type,
    with its mandatory alt text) when one is set,
    and the display enrichment — a person's public
    organizations, an organization's member count
    and website. `matched_fields` names where the
    free-text terms hit (empty for a qualifier-only
    or directory hit). No email, no team, no
    permission fact is ever on a card."""
    kind: str                # user | org
    subject_id: int
    handle: str              # display case
    display_name: str | None
    bio: str | None
    website: str | None      # organizations only
    avatar_filename: str | None
    avatar_alt: str | None
    created_at: int
    matched_fields: tuple[str, ...] = ()
    org_names: tuple[str, ...] = ()      # people only
    member_count: int | None = None      # orgs only

    @property
    def handle_lower(self) -> str:
        return self.handle.lower()

    @property
    def effective_name(self) -> str:
        return self.display_name or self.handle


@dataclass(frozen=True)
class PeopleSearchResults:
    """One permission-filtered people search, counted
    (the S-209 law for people): the hits a page shows
    (capped by the search's limit) and the total
    tallied over the full filtered result before the
    cap, counting only subjects the searcher may
    see."""
    hits: tuple[PeopleHit, ...]
    total: int


class PeopleSearch:
    """The S-211 executor. It resolves which people
    the viewer may see (active accounts, plus the
    viewer's own or an admin's view of non-active
    ones) before any profile fact is read, loads
    profiles only for those people, judges every
    survivor with the pure matchers, and enriches
    only the matches. Organizations are public
    directory facts. It never reads team rows and
    never reads an email column. It writes
    nothing."""

    def __init__(self, conn: sqlite3.Connection,
                 organizations: OrganizationStore):
        self._conn = conn
        self._orgs = organizations

    # -- enrichment, matches only -------------------
    def _org_names_for(self, user_id: int) -> tuple[str, ...]:
        rows = self._conn.execute(
            "SELECT o.name FROM organizations o"
            " JOIN organization_members m ON m.org_id = o.id"
            " WHERE m.user_id = ? ORDER BY o.name_lower",
            (user_id,)).fetchall()
        return tuple(str(r["name"]) for r in rows)

    def _member_count_for(self, org_id: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM organization_members"
            " WHERE org_id = ?", (org_id,)).fetchone()
        return int(row["n"])

    # -- the search, whole ---------------------------
    def _search_all(self, viewer: User | None, query: object = "",
                    *, kind: object = None, sort: object = None,
                    limit: int = DEFAULT_LIMIT,
                    ) -> list[PeopleHit]:
        """Execute one people search, whole (the public
        faces apply the *limit* cap). The query text's
        grammar is parsed first; the explicit *kind* is
        an additional qualifier ANDed with it, and an
        explicit *sort* overrides the text's sort. An
        empty query is the directory: every subject the
        viewer may see."""
        parsed = parse_people_query(query)
        kinds = list(parsed.kinds)
        final_sort = parsed.sort
        if kind is not None:
            kinds.append(_check_kind(kind))
        if sort is not None:
            final_sort = _check_sort(sort)
        _check_limit(limit)
        effective = PeopleSearchQuery(
            terms=parsed.terms, kinds=tuple(kinds),
            not_kinds=parsed.not_kinds, sort=final_sort)
        hits: list[PeopleHit] = []
        # People: filter on the account row alone,
        # then read profiles only for the survivors.
        for row in self._conn.execute(
                "SELECT id, status FROM users ORDER BY id"
                ).fetchall():
            if not user_visible_to(
                    viewer, int(row["id"]), str(row["status"])):
                continue
            profile = self._conn.execute(
                "SELECT u.username AS username,"
                " u.username_lower AS username_lower,"
                " u.created_at AS created_at,"
                " p.display_name AS display_name, p.bio AS bio,"
                " p.avatar_sha256 AS avatar_sha256,"
                " p.avatar_content_type AS avatar_content_type,"
                " p.avatar_alt AS avatar_alt"
                " FROM users u"
                " LEFT JOIN profiles p ON p.user_id = u.id"
                " WHERE u.id = ?", (int(row["id"]),)).fetchone()
            subject = _Subject(
                handle_lower=str(profile["username_lower"]),
                display_name=profile["display_name"],
                bio=profile["bio"])
            if not user_matches_query(subject, effective):
                continue
            hits.append(PeopleHit(
                kind="user", subject_id=int(row["id"]),
                handle=str(profile["username"]),
                display_name=profile["display_name"],
                bio=profile["bio"], website=None,
                avatar_filename=_avatar_filename(
                    profile["avatar_sha256"],
                    profile["avatar_content_type"]),
                avatar_alt=profile["avatar_alt"],
                created_at=int(profile["created_at"]),
                matched_fields=matched_fields(
                    _fields_of(subject.handle_lower,
                               subject.display_name, subject.bio),
                    effective),
                org_names=self._org_names_for(int(row["id"]))))
        # Organizations: public directory facts.
        for org in self._orgs.list_organizations():
            subject = _Subject(
                handle_lower=org.name_lower,
                display_name=org.display_name, bio=org.bio)
            org_subject = _OrgSubject(
                name_lower=org.name_lower,
                display_name=org.display_name, bio=org.bio)
            if not org_matches_query(org_subject, effective):
                continue
            hits.append(PeopleHit(
                kind="org", subject_id=org.id, handle=org.name,
                display_name=org.display_name, bio=org.bio,
                website=org.website,
                avatar_filename=org.avatar_filename,
                avatar_alt=org.avatar_alt,
                created_at=org.created_at,
                matched_fields=matched_fields(
                    _fields_of(subject.handle_lower,
                               subject.display_name, subject.bio),
                    effective),
                member_count=self._member_count_for(org.id)))
        return _sort_hits(hits, final_sort)

    def search(self, viewer: User | None, query: object = "", *,
               kind: object = None, sort: object = None,
               limit: int = DEFAULT_LIMIT,
               ) -> list[PeopleHit]:
        """Execute one people search (see `_search_all`
        for the grammar and the law), capped at *limit*
        subjects."""
        hits = self._search_all(
            viewer, query, kind=kind, sort=sort, limit=limit)
        return hits[:limit]

    def search_counted(self, viewer: User | None,
                       query: object = "", **kwargs,
                       ) -> PeopleSearchResults:
        """One people search with its filtered count:
        the capped hits plus a total tallied over the
        full filtered result before the cap — a person
        the searcher may not see contributes no card
        and no count."""
        limit = kwargs.get("limit", DEFAULT_LIMIT)
        hits = self._search_all(viewer, query, **kwargs)
        return PeopleSearchResults(
            hits=tuple(hits[:limit]), total=len(hits))

    def count(self, viewer: User | None, query: object = "",
              **kwargs) -> int:
        """Only the filtered count of one people
        search — the number on its own, computed from
        the filtered hits, never from the instance's
        rows."""
        return self.search_counted(viewer, query, **kwargs).total

    def directory(self, viewer: User | None, *,
                  kind: object = None, sort: object = None,
                  limit: int = DEFAULT_LIMIT,
                  ) -> list[PeopleHit]:
        """The people directory for *viewer*: every
        person they may see and every organization,
        in directory order — the empty search, named
        as the listing it is."""
        return self.search(
            viewer, "", kind=kind, sort=sort, limit=limit)

    def directory_counted(self, viewer: User | None, **kwargs,
                          ) -> PeopleSearchResults:
        """The directory with its filtered count: the
        capped listing plus the total of visible
        subjects before the cap — a count of what the
        viewer may see, never a count of the
        instance."""
        return self.search_counted(viewer, "", **kwargs)


@dataclass(frozen=True)
class _Subject:
    handle_lower: str
    display_name: str | None
    bio: str | None

    @property
    def username_lower(self) -> str:
        return self.handle_lower


@dataclass(frozen=True)
class _OrgSubject:
    name_lower: str
    display_name: str | None
    bio: str | None


# ------------------------------------------------------------------
# Pages
# ------------------------------------------------------------------

def render_profile_card(hit: PeopleHit) -> str:
    """One profile card: the kind said in a word,
    the effective name, the handle, the avatar
    (always with its stored alt text), the bio, and
    the display facts of the kind — a person's
    organizations, an organization's website and
    member count — plus the matched fields said in
    words when the search carried free text. Every
    value escaped through S-010; a website renders
    as a link only when S-010's `safe_url` keeps
    it, otherwise as plain text."""
    parts = ['<article class="profile-card">']
    parts.append(
        f"<h2>{escape_html_text(hit.effective_name)}</h2>")
    parts.append(
        f'<p class="handle">@{escape_html_text(hit.handle)}'
        f" — {escape_html_text(kind_word(hit.kind))}</p>")
    if hit.avatar_filename is not None and hit.avatar_alt:
        src = escape_html_attr(f"/avatars/{hit.avatar_filename}")
        alt = escape_html_attr(hit.avatar_alt)
        parts.append(f'<img class="avatar" src="{src}" alt="{alt}">')
    if hit.bio:
        bio_html = escape_html_text(hit.bio).replace("\n", "<br>\n")
        parts.append(f'<p class="bio">{bio_html}</p>')
    if hit.kind == "org":
        if hit.website:
            url = safe_url(hit.website)
            label = escape_html_text(hit.website)
            if url is not None:
                href = escape_html_attr(url)
                parts.append(
                    f'<p class="website"><a href="{href}">'
                    f"{label}</a></p>")
            else:
                parts.append(f'<p class="website">{label}</p>')
        if hit.member_count is not None:
            parts.append(
                f"<p>{hit.member_count} "
                f"{'member' if hit.member_count == 1 else 'members'}"
                "</p>")
    if hit.kind == "user" and hit.org_names:
        parts.append(
            "<p>Member of: "
            + escape_html_text(", ".join(hit.org_names)) + "</p>")
    if hit.matched_fields:
        parts.append(
            "<p>Matched in: "
            + escape_html_text(", ".join(hit.matched_fields))
            + "</p>")
    parts.append("</article>")
    return "\n".join(parts)


def render_people_search_page(query: object,
                              hits: list[PeopleHit], *,
                              total: int | None = None) -> str:
    """The people search results page: the search as
    typed (escaped through S-010), the qualifier
    help in plain words, the count of visible
    matches (the filtered total when given, before
    any cap), and each hit as its profile card."""
    query_text = query if isinstance(query, str) else ""
    shown_total = len(hits) if total is None else total
    parts = [
        "<h1>Search people and organizations</h1>",
        '<form method="get" action="search" role="search">',
        '<label for="q">Search people and organizations</label>',
        f'<input id="q" name="q" type="search" '
        f'value="{escape_html_attr(query_text)}">',
        '<input type="hidden" name="type" value="people">',
        '<button type="submit">Search</button>',
        "</form>",
        '<ul class="qualifier-help">',
    ]
    for name, words in QUALIFIER_HELP:
        parts.append(
            f"<li><code>{escape_html_text(name)}</code> — "
            f"{escape_html_text(words)}</li>")
    parts.append("</ul>")
    parts.append(
        f"<p>{shown_total} "
        f"{'match' if shown_total == 1 else 'matches'}"
        " — only people and organizations you may see "
        "are counted.</p>")
    if not hits:
        parts.append(
            '<p class="empty">No people or organizations '
            "match. Try fewer words, or clear the search "
            "to see the whole directory of people you may "
            "see and every organization.</p>")
        return "\n".join(parts)
    for hit in hits:
        parts.append(render_profile_card(hit))
    return "\n".join(parts)


def render_people_directory_page(hits: list[PeopleHit], *,
                                 total: int | None = None) -> str:
    """The people directory page: every person the
    viewer may see and every organization, in
    directory order, with the visible count said
    plainly and the law stated in words — people
    the viewer may not see are not listed and not
    counted, exactly as if they had no account.
    Every value escaped through S-010."""
    shown_total = len(hits) if total is None else total
    parts = [
        "<h1>People and organizations</h1>",
        "<p>Every organization on this instance, and "
        "every person with an active account, in "
        "handle order. People whose accounts are not "
        "active are not listed and not counted.</p>",
        f"<p>{shown_total} "
        f"{'entry' if shown_total == 1 else 'entries'}"
        " shown.</p>",
    ]
    if not hits:
        parts.append(
            '<p class="empty">Nobody to show yet. People '
            "and organizations will appear here as "
            "accounts are made active and organizations "
            "are created.</p>")
        return "\n".join(parts)
    for hit in hits:
        parts.append(render_profile_card(hit))
    return "\n".join(parts)
