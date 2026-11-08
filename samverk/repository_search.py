"""Repository search (S-210).

By name, description, topics, owner — Part X's
repository face, beside S-206's issue/PR backend
and S-208's code search, written from research
file 18. The fourth thing a person hunts for on
an instance is the repository itself, and the
instance directory page is this search with an
empty query: every repository the viewer may
read, in directory order, with nothing hidden
counted and nothing unreadable named.

- **One query line, free text plus qualifiers.**
  Free-text terms are matched case-insensitively
  as substrings against four fields — the
  repository's name, its description, its topics
  (S-066's settings row), and its owner — and
  every term must hold in at least one field
  (AND across terms, the Part X composition law).
  A double-quoted phrase is one term, matched as
  a phrase. The qualifiers narrow by exact fact:
  `owner:NAME` (the owning account or
  organization, canonical case-insensitive),
  `topic:NAME` (the repository carries that
  topic; repeated `topic:` requires every named
  topic), `visibility:public` / `internal` /
  `private` (S-050's vocabulary, judged by name;
  `is:` is accepted as its alias), and
  `sort:` (`name-asc` — the default, owner then
  name — `name-desc`, `created-asc`,
  `created-desc`). A leading `-` negates one
  `owner:` / `topic:` / `visibility:` qualifier
  (S-206's negation shape). Explicit keyword
  arguments (`owner=`, `topic=`, `visibility=`)
  are additional qualifiers ANDed with the text;
  an explicit `sort=` overrides the text's.
- **Unknown qualifiers fail closed.** A token
  shaped like a qualifier whose name is outside
  this grammar is refused `query_invalid`, naming
  it — never silently dropped (a dropped
  qualifier widens the search, the S-118 law)
  and never folded into the free text. Empty
  values, unterminated quotes, control
  characters, an over-long query, a visibility
  or sort outside its vocabulary, and a bad
  limit are the same refusal. A qualifier naming
  something that does not exist (an owner with
  no repositories, a topic nobody uses) is not
  an error: it simply matches nothing.
- **Matching is pure, and says where it hit.**
  `repo_matches_query` judges a repository plus
  its topics against the parsed query with no
  storage read, so the deciding law is testable
  without a database; `matched_fields` names the
  fields (`name`, `description`, `topics`,
  `owner`) in which a free-text term was found,
  so a page can say *why* a repository matched
  and the battery can prove a hit came from the
  field it claims.
- **Permission is S-209's filtered law.**
  Visible repositories are resolved through
  S-209's one resolution (`visible_repositories`
  in samverk/search_permissions.py, over S-054's
  `can_read`) *before* any repository fact beyond
  the row itself is read — topics are loaded only
  for repositories that survive that resolution —
  so a hit can only ever name a repository its
  viewer may read, and the counted face
  (`search_counted`) tallies its total from the
  filtered hits only, before any result cap: an
  unreadable repository contributes no name, no
  description, no topic, and no count (the S-209
  leakage law, proven here by the same
  equivalence the S-209 battery proves: a
  stranger's hits and counts over a world
  containing a planted private repository equal
  the same search over a world where it was
  never created). The directory is the same law
  with an empty query — it lists exactly what
  the viewer may read, never a total of the
  instance. Under S-054's gate an `internal`
  repository is not public, so search shows it
  only to its owner, site admins, and
  collaborators — never wider than the gate
  allows (S-190's wider internal floor is the
  permission engine's surface, not this one's,
  exactly as S-206 and S-208 keep).
- **An empty search is the directory, honestly.**
  Unlike code search (S-208), which refuses an
  empty pattern, a repository search with no
  terms and no qualifiers is a listing, and
  listings are this slice's second named face:
  `directory` returns it, `render_directory_page`
  renders it. Results are capped by `limit`
  files (default 100, at most 500, the Part X
  cap shape); the counted faces keep the true
  total beside the capped hits, so shown and
  counted are never confused.
- **No audit event of its own, no migration.**
  Searching is a read over the repository rows
  and S-066's topics. 122 events stand: 31 auth
  / 79 repo / 12 admin. Schema stays 82.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from .accounts import User
from .escaping import escape_html_attr, escape_html_text
from .repositories import VISIBILITIES, Repository, RepositoryStore
from .search_permissions import visible_repositories

__all__ = [
    "DEFAULT_LIMIT", "MAX_LIMIT", "QUALIFIER_HELP", "QUALIFIER_NAMES",
    "QUERY_MAX", "SORT_VALUES", "RepositoryHit", "RepositorySearch",
    "RepositorySearchError", "RepositorySearchQuery",
    "RepositorySearchResults", "matched_fields", "parse_repository_query",
    "render_directory_page", "render_repository_search_page",
    "repo_matches_query", "visibility_word",
]

QUERY_MAX = 500
DEFAULT_LIMIT = 100
MAX_LIMIT = 500
QUALIFIER_NAMES = frozenset({"owner", "topic", "visibility", "is", "sort"})
SORT_VALUES = frozenset(
    {"name-asc", "name-desc", "created-asc", "created-desc"})
DEFAULT_SORT = "name-asc"

_VISIBILITY_WORDS = {"public": "Public",
                     "internal": "Internal", "private": "Private"}

QUALIFIER_HELP: tuple[tuple[str, str], ...] = (
    ("owner:NAME", "only repositories owned by that account "
                   "or organization"),
    ("topic:NAME", "only repositories carrying that topic; "
                   "repeat it to require several topics"),
    ("visibility:public", "only repositories with that "
                          "visibility (public, internal, or "
                          "private); is: works the same way"),
    ("sort:name-asc", "owner, then name, A to Z (the default)"),
    ("sort:name-desc", "owner, then name, Z to A"),
    ("sort:created-asc", "oldest repository first"),
    ("sort:created-desc", "newest repository first"),
    ("-topic:NAME", "a leading minus negates one owner:, "
                    "topic:, or visibility: qualifier"),
    ("free words", "words (or a \"quoted phrase\") matched "
                   "against name, description, topics, and "
                   "owner; every word must match somewhere"),
)


class RepositorySearchError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def _invalid(message: str) -> RepositorySearchError:
    return RepositorySearchError("query_invalid", message)


def visibility_word(visibility: str) -> str:
    """A visibility said in a word a person reads."""
    return _VISIBILITY_WORDS.get(visibility, visibility)


# ------------------------------------------------------------------
# The parsed query
# ------------------------------------------------------------------

@dataclass(frozen=True)
class RepositorySearchQuery:
    """One repository search, whole: the free-text
    terms (lowercased, in order), the exact owner,
    topic, and visibility qualifiers (canonical
    lowercase; the `not_*` tuples are the negated
    qualifiers), and the result ordering."""
    terms: tuple[str, ...] = ()
    owners: tuple[str, ...] = ()
    not_owners: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    not_topics: tuple[str, ...] = ()
    visibilities: tuple[str, ...] = ()
    not_visibilities: tuple[str, ...] = ()
    sort: str = DEFAULT_SORT

    @property
    def is_empty(self) -> bool:
        """True when the query carries no term and
        no qualifier — the directory query."""
        return not (self.terms or self.owners or self.not_owners
                    or self.topics or self.not_topics
                    or self.visibilities or self.not_visibilities)


def _tokenise(query: str) -> list[str]:
    """Split a query line into tokens: whitespace
    separates, a double-quoted span stays inside
    its token (so `"my project"` is one term and
    `topic:"two words"` would be one qualifier).
    An unterminated quote is `query_invalid`."""
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


def _check_visibility(value: str) -> str:
    lowered = value.strip().lower()
    if lowered not in VISIBILITIES:
        raise _invalid(
            "Visibility is 'public', 'internal', or 'private'.")
    return lowered


def parse_repository_query(query: object) -> RepositorySearchQuery:
    """Parse query text into a `RepositorySearchQuery`:
    `owner:`, `topic:`, `visibility:` (or `is:`),
    and `sort:` qualifiers are lifted out (a leading
    `-` negates an owner/topic/visibility qualifier),
    and the remaining tokens, in order, are the
    free-text terms. An unknown qualifier-shaped
    token, an empty value, a bad vocabulary value,
    an unterminated quote, a control character, or
    an over-long query is refused `query_invalid`,
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
    owners: list[str] = []
    not_owners: list[str] = []
    topics: list[str] = []
    not_topics: list[str] = []
    visibilities: list[str] = []
    not_visibilities: list[str] = []
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
            elif name in ("visibility", "is"):
                clean = _check_visibility(value)
                (not_visibilities if negated
                 else visibilities).append(clean)
            elif name == "owner":
                (not_owners if negated
                 else owners).append(value.strip().lower())
            else:  # topic
                (not_topics if negated
                 else topics).append(value.strip().lower())
            continue
        if colon and head and all(
                c.isalnum() or c in "_-" for c in head):
            raise _invalid(
                f"The qualifier {head!r} is not part of repository "
                "search. Known qualifiers: owner:, topic:, "
                "visibility:, sort:.")
        if negated:
            raise _invalid(
                "Only an owner:, topic:, or visibility: qualifier "
                "can be negated.")
        if token:
            terms.append(token.lower())
    return RepositorySearchQuery(
        terms=tuple(terms), owners=tuple(owners),
        not_owners=tuple(not_owners), topics=tuple(topics),
        not_topics=tuple(not_topics),
        visibilities=tuple(visibilities),
        not_visibilities=tuple(not_visibilities), sort=sort)


# ------------------------------------------------------------------
# The pure judgement
# ------------------------------------------------------------------

def _fields_of(repo: Repository,
               topics: tuple[str, ...]) -> dict[str, str]:
    """The four searched fields of one repository,
    lowercased for judging: its name, its
    description, its topics joined for substring
    judging (each topic is also judged exactly by
    the topic qualifiers), and its owner."""
    return {
        "name": repo.name_lower,
        "description": repo.description.lower(),
        "topics": " ".join(t.lower() for t in topics),
        "owner": repo.owner_lower,
    }


def matched_fields(repo: Repository, topics: tuple[str, ...],
                   parsed: RepositorySearchQuery) -> tuple[str, ...]:
    """The fields in which at least one free-text
    term of *parsed* was found, in the canonical
    order (name, description, topics, owner).
    Empty when the query carries no free-text
    term. Pure: no storage is read here."""
    if not parsed.terms:
        return ()
    fields = _fields_of(repo, topics)
    return tuple(
        name for name in ("name", "description", "topics", "owner")
        if any(term in fields[name] for term in parsed.terms))


def repo_matches_query(repo: Repository, topics: tuple[str, ...],
                       parsed: RepositorySearchQuery) -> bool:
    """Whether *repo* (with its S-066 *topics*)
    matches *parsed*: every owner, topic, and
    visibility qualifier holds (exact, canonical;
    repeated qualifiers of one kind all hold, so
    contradictory qualifiers match nothing), no
    negated qualifier holds, and every free-text
    term appears in at least one of the four
    fields. Pure: no storage is read here."""
    lowered_topics = tuple(t.lower() for t in topics)
    if any(repo.owner_lower != owner for owner in parsed.owners):
        return False
    if repo.owner_lower in parsed.not_owners:
        return False
    if any(topic not in lowered_topics for topic in parsed.topics):
        return False
    if any(topic in lowered_topics for topic in parsed.not_topics):
        return False
    if any(repo.visibility != wanted
           for wanted in parsed.visibilities):
        return False
    if repo.visibility in parsed.not_visibilities:
        return False
    if parsed.terms:
        fields = _fields_of(repo, topics)
        haystacks = tuple(fields.values())
        for term in parsed.terms:
            if not any(term in hay for hay in haystacks):
                return False
    return True


def _sort_hits(hits: list["RepositoryHit"],
               sort: str) -> list["RepositoryHit"]:
    """Order hits by the query's sort: name sorts
    judge owner, then name (canonical lowercase);
    created sorts judge the creation stamp, with
    the name order as the honest tie-break."""
    if sort == "name-desc":
        return sorted(
            hits, key=lambda h: (h.owner_lower, h.repo_lower),
            reverse=True)
    if sort == "created-asc":
        return sorted(
            hits, key=lambda h: (h.created_at, h.owner_lower,
                                 h.repo_lower))
    if sort == "created-desc":
        return sorted(
            hits, key=lambda h: (-h.created_at, h.owner_lower,
                                 h.repo_lower))
    return sorted(hits, key=lambda h: (h.owner_lower, h.repo_lower))


def _check_limit(limit: object) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool) \
            or limit < 1 or limit > MAX_LIMIT:
        raise _invalid(f"The limit is 1 to {MAX_LIMIT} repositories.")
    return limit


# ------------------------------------------------------------------
# Hits and the executor
# ------------------------------------------------------------------

@dataclass(frozen=True)
class RepositoryHit:
    """One repository that matched: where it lives,
    what it says about itself (description,
    visibility, S-066 topics), when it was created,
    and the fields its free-text terms matched in
    (empty for a qualifier-only or directory hit)."""
    repo_id: int
    owner: str
    repo: str
    description: str
    visibility: str
    topics: tuple[str, ...]
    created_at: int
    matched_fields: tuple[str, ...] = ()

    @property
    def owner_lower(self) -> str:
        return self.owner.lower()

    @property
    def repo_lower(self) -> str:
        return self.repo.lower()

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


@dataclass(frozen=True)
class RepositorySearchResults:
    """One permission-filtered repository search,
    counted (S-209): the hits a page shows (capped
    by the search's limit) and the total tallied
    over the full filtered result before the cap,
    counting only repositories the searcher may
    read."""
    hits: tuple[RepositoryHit, ...]
    total: int


class RepositorySearch:
    """The S-210 executor. It resolves the viewer's
    visible repositories through S-209's one
    resolution (over S-054's `can_read`) before any
    further repository fact is read, loads S-066
    topics only for those repositories, and judges
    each survivor with the pure `repo_matches_query`.
    It writes nothing."""

    def __init__(self, conn: sqlite3.Connection,
                 repositories: RepositoryStore):
        self._conn = conn
        self._repos = repositories

    def _topics_for(self, repo_ids: list[int]) -> dict[int, tuple[str, ...]]:
        """S-066 topics for exactly the repositories
        named — called only with visible ids, so an
        unreadable repository's topics are never
        read at all. A missing settings row means
        no topics; a malformed stored value reads
        as no topics (S-066's own read law)."""
        if not repo_ids:
            return {}
        placeholders = ", ".join("?" for _ in repo_ids)
        found: dict[int, tuple[str, ...]] = {}
        for row in self._conn.execute(
                "SELECT repo_id, topics FROM repo_settings"
                f" WHERE repo_id IN ({placeholders})",
                tuple(repo_ids)).fetchall():
            try:
                topics = tuple(json.loads(row["topics"]))
            except (ValueError, TypeError):
                topics = ()
            found[int(row["repo_id"])] = tuple(
                t for t in topics if isinstance(t, str))
        return found

    def _search_all(self, viewer: User | None, query: object = "", *,
                    owner: object = None, topic: object = None,
                    visibility: object = None, sort: object = None,
                    limit: int = DEFAULT_LIMIT,
                    ) -> list[RepositoryHit]:
        """Execute one repository search, whole (the
        public faces apply the *limit* cap). The
        query text's grammar is parsed first; the
        explicit keywords are additional qualifiers
        ANDed with it, except *sort*, which overrides
        the text's sort. An empty query is the
        directory: every visible repository."""
        parsed = parse_repository_query(query)
        owners = list(parsed.owners)
        topics_q = list(parsed.topics)
        visibilities = list(parsed.visibilities)
        final_sort = parsed.sort
        if owner is not None:
            if not isinstance(owner, str) or not owner.strip():
                raise _invalid("An owner filter is an account name.")
            owners.append(owner.strip().lower())
        if topic is not None:
            if not isinstance(topic, str) or not topic.strip():
                raise _invalid("A topic filter is a topic name.")
            topics_q.append(topic.strip().lower())
        if visibility is not None:
            if not isinstance(visibility, str):
                raise _invalid(
                    "Visibility is 'public', 'internal', or 'private'.")
            visibilities.append(_check_visibility(visibility))
        if sort is not None:
            final_sort = _check_sort(sort)
        _check_limit(limit)
        effective = RepositorySearchQuery(
            terms=parsed.terms, owners=tuple(owners),
            not_owners=parsed.not_owners, topics=tuple(topics_q),
            not_topics=parsed.not_topics,
            visibilities=tuple(visibilities),
            not_visibilities=parsed.not_visibilities,
            sort=final_sort)
        visible = visible_repositories(self._conn, self._repos, viewer)
        if not visible:
            return []
        topics_by_id = self._topics_for([r.id for r in visible])
        hits: list[RepositoryHit] = []
        for repo in visible:
            topics = topics_by_id.get(repo.id, ())
            if not repo_matches_query(repo, topics, effective):
                continue
            hits.append(RepositoryHit(
                repo_id=repo.id, owner=repo.owner, repo=repo.name,
                description=repo.description,
                visibility=repo.visibility, topics=topics,
                created_at=repo.created_at,
                matched_fields=matched_fields(repo, topics, effective)))
        return _sort_hits(hits, final_sort)

    def search(self, viewer: User | None, query: object = "", *,
               owner: object = None, topic: object = None,
               visibility: object = None, sort: object = None,
               limit: int = DEFAULT_LIMIT,
               ) -> list[RepositoryHit]:
        """Execute one repository search (see
        `_search_all` for the grammar and the law),
        capped at *limit* repositories."""
        hits = self._search_all(
            viewer, query, owner=owner, topic=topic,
            visibility=visibility, sort=sort, limit=limit)
        return hits[:limit]

    def search_counted(self, viewer: User | None,
                       query: object = "", **kwargs,
                       ) -> RepositorySearchResults:
        """One repository search with its S-209
        count: the capped hits plus a total tallied
        over the full filtered result before the
        cap — an unreadable repository contributes
        no name, no description, no topic, and no
        count."""
        limit = kwargs.get("limit", DEFAULT_LIMIT)
        hits = self._search_all(viewer, query, **kwargs)
        return RepositorySearchResults(
            hits=tuple(hits[:limit]), total=len(hits))

    def count(self, viewer: User | None, query: object = "",
              **kwargs) -> int:
        """Only the S-209 count of one repository
        search — the number on its own, computed
        from the filtered hits, never from the
        instance's rows."""
        return self.search_counted(viewer, query, **kwargs).total

    def directory(self, viewer: User | None, *,
                  visibility: object = None, sort: object = None,
                  limit: int = DEFAULT_LIMIT,
                  ) -> list[RepositoryHit]:
        """The instance directory for *viewer*: every
        repository they may read, in directory
        order — the empty search, named as the
        listing it is."""
        return self.search(
            viewer, "", visibility=visibility, sort=sort, limit=limit)

    def directory_counted(self, viewer: User | None, **kwargs,
                          ) -> RepositorySearchResults:
        """The directory with its S-209 count: the
        capped listing plus the total of visible
        repositories before the cap — a count of
        what the viewer may read, never a count of
        the instance."""
        return self.search_counted(viewer, "", **kwargs)


# ------------------------------------------------------------------
# Pages
# ------------------------------------------------------------------

def _hit_line(hit: RepositoryHit) -> str:
    """One result as a list item: full name,
    visibility said in words, description, topics,
    and the matched fields said in words when the
    search carried free text — every value escaped
    through S-010."""
    words = [f"{hit.full_name} — {visibility_word(hit.visibility)}"]
    if hit.description:
        words.append(hit.description)
    if hit.topics:
        words.append("Topics: " + ", ".join(hit.topics))
    if hit.matched_fields:
        words.append("Matched in: " + ", ".join(hit.matched_fields))
    return f"<li>{escape_html_text(' — '.join(words))}</li>"


def render_repository_search_page(query: object,
                                  hits: list[RepositoryHit], *,
                                  total: int | None = None) -> str:
    """The search results page: the search as typed
    (escaped through S-010), the qualifier help in
    plain words, the count of visible matches
    (the S-209 total when given, before any cap),
    and each hit with its repository, visibility
    said in words, description, and topics."""
    query_text = query if isinstance(query, str) else ""
    shown_total = len(hits) if total is None else total
    parts = [
        "<h1>Search repositories</h1>",
        '<form method="get" action="search" role="search">',
        '<label for="q">Search repositories</label>',
        f'<input id="q" name="q" type="search" '
        f'value="{escape_html_attr(query_text)}">',
        '<input type="hidden" name="type" value="repositories">',
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
        f"{'repository matches' if shown_total == 1 else 'repositories match'}"
        f" — only repositories you can read are counted.</p>")
    if not hits:
        parts.append(
            '<p class="empty">No repositories match. Try fewer '
            "words, or clear the search to see the whole "
            "directory of repositories you can read.</p>")
        return "\n".join(parts)
    parts.append('<ul class="search-results">')
    for hit in hits:
        parts.append(_hit_line(hit))
    parts.append("</ul>")
    return "\n".join(parts)


def render_directory_page(hits: list[RepositoryHit], *,
                          total: int | None = None) -> str:
    """The instance directory page: every repository
    the viewer may read, in directory order, with
    the visible count said plainly and the law
    stated in words — repositories the viewer
    cannot read are not listed and not counted,
    exactly as if they were not on the instance.
    Every value escaped through S-010."""
    shown_total = len(hits) if total is None else total
    parts = [
        "<h1>Repository directory</h1>",
        "<p>Every repository on this instance that you can "
        "read, in owner and name order. Repositories you "
        "cannot read are not listed and not counted.</p>",
        f"<p>{shown_total} "
        f"{'repository' if shown_total == 1 else 'repositories'}"
        f" shown.</p>",
    ]
    if not hits:
        parts.append(
            '<p class="empty">No repositories you can read '
            "yet. Public repositories will appear here as "
            "they are created.</p>")
        return "\n".join(parts)
    parts.append("<ul>")
    for hit in hits:
        parts.append(_hit_line(hit))
    parts.append("</ul>")
    return "\n".join(parts)
