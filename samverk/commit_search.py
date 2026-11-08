"""Commit search (S-212).

By message and author across permitted repos —
Part X's history face, beside S-208's code search,
S-210's repository search, and S-211's user and
org search, written from research file 18. Where
S-102 lists one repository's history, this slice
hunts a message or an author across every
repository the searcher may read, and returns the
commits themselves: where each lives, who wrote
it, and when.

- **One query line, free text plus qualifiers.**
  Free-text terms are matched case-insensitively
  as substrings against two fields of each commit
  — its message (subject and body together) and
  its author (name and email together) — and
  every term must hold in at least one field (AND
  across terms, the Part X composition law). A
  double-quoted phrase is one term, matched as a
  phrase. The qualifiers narrow by exact fact:
  `author:TEXT` (the commit's author name or
  email contains the text, case-insensitively;
  repeated `author:` requires every one),
  `repo:OWNER/NAME` (the search is that one
  repository's — S-118's scope shape), and
  `sort:` (`newest` — the default, author time
  descending — or `oldest`). A leading `-`
  negates one `author:` qualifier (S-210's
  negation shape). Explicit keyword arguments
  (`author=`, `owner=`/`repo=`) are additional
  qualifiers ANDed with the text; an explicit
  `sort=` overrides the text's.
- **Unknown qualifiers fail closed.** A token
  shaped like a qualifier whose name is outside
  this grammar is refused `query_invalid`, naming
  it — never silently dropped (a dropped
  qualifier widens the search, the S-118 law) and
  never folded into the free text. Empty values,
  a malformed `repo:` scope, a duplicated scope
  or sort, an unterminated quote, control
  characters, an over-long query, and a bad limit
  are the same refusal. An empty search (no term,
  no author, no scope) is refused too, as S-208
  refuses an empty pattern: a commit search with
  nothing to hunt is a listing, and listings are
  S-102's face, not this one's.
- **History is read through the house seams.**
  Each permitted repository's commits are read
  with `git log --all` (every ref, so a commit on
  a side branch is findable; git itself dedupes
  commits several refs reach) through S-014's
  `run_git_in`, and parsed by S-102's own
  `parse_log_output`, so the author, time, and
  message facts are exactly the facts the commit
  list shows. The scan is capped at
  `MAX_SCAN_PER_REPO` commits per repository,
  newest first — the stated cost cap S-219's
  honest-limits document will carry. An empty
  repository contributes nothing (its `log --all`
  answers empty, in success). A repository whose
  history cannot be read at all fails a search
  scoped to it alone (`object_unreadable`, as
  S-102 answers) and contributes nothing to a
  global search, so one broken repository cannot
  blind the whole instance's history hunt.
- **Matching is pure, and says where it hit.**
  `commit_matches_query` judges one parsed commit
  (S-102's `CommitSummary`) against the parsed
  query with no storage read, so the deciding law
  is testable without a database or a repository;
  `matched_fields` names the fields (`message`,
  `author`) in which a free-text term was found,
  so a page can say *why* a commit matched.
- **Permission is S-209's filtered law.**
  Visible repositories are resolved through
  S-209's one resolution (`visible_repositories`
  in samverk/search_permissions.py, over S-054's
  `can_read`) *before* any repository's history
  is read — git is spawned only for repositories
  that survive that resolution — so a hit can
  only ever name a commit in a repository its
  viewer may read, and the counted face
  (`search_counted`) tallies its total from the
  filtered hits only, before any result cap: an
  unreadable repository contributes no commit, no
  message, no author, and no count (the S-209
  leakage law, proven here by the same equivalence
  the S-209 battery proves: a stranger's hits and
  counts over a world containing a planted private
  repository equal the same search over a world
  where it was never created). A search scoped to
  an unreadable (or missing) repository answers
  the uniform `repo_not_found`, worded identically
  to a repository that does not exist.
- **No audit event of its own, no migration.**
  Searching is a read over git histories. 122
  events stand: 31 auth / 79 repo / 12 admin.
  Schema stays 82.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

from .accounts import User
from .commit_list import CommitSummary, parse_log_output
from .escaping import escape_html_attr, escape_html_text
from .permissions import can_read
from .proc import run_git_in
from .repositories import Repository, RepositoryStore
from .search_permissions import visible_repositories

__all__ = [
    "DEFAULT_LIMIT", "MAX_LIMIT", "MAX_SCAN_PER_REPO",
    "QUALIFIER_HELP", "QUALIFIER_NAMES", "QUERY_MAX", "SORT_VALUES",
    "CommitHit", "CommitSearch", "CommitSearchError",
    "CommitSearchQuery", "CommitSearchResults", "commit_matches_query",
    "matched_fields", "parse_commit_query", "render_commit_search_page",
]

QUERY_MAX = 500
DEFAULT_LIMIT = 100
MAX_LIMIT = 500
MAX_SCAN_PER_REPO = 5000
QUALIFIER_NAMES = frozenset({"author", "repo", "sort"})
SORT_VALUES = frozenset({"newest", "oldest"})
DEFAULT_SORT = "newest"

_SEP = "\x1f"
_REC = "\x1e"
_FORMAT = _SEP.join(["%H", "%P", "%an", "%ae", "%at", "%s", "%b"]) + _REC

QUALIFIER_HELP: tuple[tuple[str, str], ...] = (
    ("author:NAME", "only commits whose author name or email "
                    "contains that text"),
    ("repo:OWNER/NAME", "only commits in that one repository"),
    ("sort:newest", "newest commit first (the default)"),
    ("sort:oldest", "oldest commit first"),
    ("-author:NAME", "a leading minus negates one author: "
                      "qualifier"),
    ("free words", "words (or a \"quoted phrase\") matched "
                   "against the commit message and its author; "
                   "every word must match somewhere"),
)


class CommitSearchError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def _invalid(message: str) -> CommitSearchError:
    return CommitSearchError("query_invalid", message)


# ------------------------------------------------------------------
# The parsed query
# ------------------------------------------------------------------

@dataclass(frozen=True)
class CommitSearchQuery:
    """One commit search, whole: the free-text terms
    (lowercased, in order), the author qualifiers
    (canonical lowercase substrings; the `not_*`
    tuple is the negated qualifiers), the one
    repository scope (lowercased owner/name, ''
    when global), and the result ordering."""
    terms: tuple[str, ...] = ()
    authors: tuple[str, ...] = ()
    not_authors: tuple[str, ...] = ()
    repo_owner: str = ""
    repo_name: str = ""
    sort: str = DEFAULT_SORT

    @property
    def repo_scope(self) -> tuple[str, str] | None:
        if self.repo_owner and self.repo_name:
            return (self.repo_owner, self.repo_name)
        return None

    @property
    def is_empty(self) -> bool:
        """True when the query carries no term, no
        author qualifier, and no repository scope —
        nothing to hunt for."""
        return not (self.terms or self.authors or self.not_authors
                    or self.repo_scope)


def _tokenise(query: str) -> list[str]:
    """Split a query line into tokens: whitespace
    separates, a double-quoted span stays inside
    its token (so `"my phrase"` is one term and
    `author:"two words"` would be one qualifier).
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
        raise _invalid("The sort is one of: newest, oldest.")
    return value.strip().lower()


def _check_scope(value: str) -> tuple[str, str]:
    owner, slash, name = value.strip().partition("/")
    if not slash or not owner or not name or "/" in name:
        raise _invalid(
            "The repo: qualifier names exactly one repository "
            "(owner/name).")
    return owner.lower(), name.lower()


def parse_commit_query(query: object) -> CommitSearchQuery:
    """Parse query text into a `CommitSearchQuery`:
    `author:`, `repo:`, and `sort:` qualifiers are
    lifted out (a leading `-` negates an author
    qualifier), and the remaining tokens, in order,
    are the free-text terms. An unknown
    qualifier-shaped token, an empty value, a
    malformed or duplicated scope, a duplicated
    sort, an unterminated quote, a control
    character, or an over-long query is refused
    `query_invalid`, naming the problem."""
    if query is None:
        query = ""
    if not isinstance(query, str):
        raise _invalid("A search is text.")
    if len(query) > QUERY_MAX:
        raise _invalid(f"A search is at most {QUERY_MAX} characters.")
    if any((ord(c) < 0x20 and c != "\t") or ord(c) == 0x7F
           for c in query):
        raise _invalid("A search carries no control characters.")
    terms: list[str] = []
    authors: list[str] = []
    not_authors: list[str] = []
    repo_owner = repo_name = ""
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
            elif name == "repo":
                if negated:
                    raise _invalid("The repo: qualifier cannot be negated.")
                if repo_owner:
                    raise _invalid("A search carries one repo: qualifier.")
                repo_owner, repo_name = _check_scope(value)
            else:  # author
                (not_authors if negated
                 else authors).append(value.strip().lower())
            continue
        if colon and head and all(
                c.isalnum() or c in "_-" for c in head):
            raise _invalid(
                f"The qualifier {head!r} is not part of commit "
                "search. Known qualifiers: author:, repo:, sort:.")
        if negated:
            raise _invalid(
                "Only an author: qualifier can be negated.")
        if token:
            terms.append(token.lower())
    return CommitSearchQuery(
        terms=tuple(terms), authors=tuple(authors),
        not_authors=tuple(not_authors), repo_owner=repo_owner,
        repo_name=repo_name, sort=sort)


# ------------------------------------------------------------------
# The pure judgement
# ------------------------------------------------------------------

def _fields_of(summary: CommitSummary) -> dict[str, str]:
    """The two searched fields of one commit,
    lowercased for judging: its message (subject
    and body together) and its author (name and
    email together)."""
    message = summary.subject
    if summary.body:
        message = message + "\n" + summary.body
    return {
        "message": message.lower(),
        "author": (summary.author_name + " "
                   + summary.author_email).lower(),
    }


def matched_fields(summary: CommitSummary,
                   parsed: CommitSearchQuery) -> tuple[str, ...]:
    """The fields in which at least one free-text
    term of *parsed* was found, in the canonical
    order (message, author). Empty when the query
    carries no free-text term. Pure: no storage is
    read here."""
    if not parsed.terms:
        return ()
    fields = _fields_of(summary)
    return tuple(
        name for name in ("message", "author")
        if any(term in fields[name] for term in parsed.terms))


def commit_matches_query(summary: CommitSummary,
                         parsed: CommitSearchQuery) -> bool:
    """Whether *summary* matches *parsed*: every
    author qualifier appears in the author field,
    no negated author qualifier does, and every
    free-text term appears in the message or the
    author field. Pure: no storage is read here."""
    fields = _fields_of(summary)
    author = fields["author"]
    if any(wanted not in author for wanted in parsed.authors):
        return False
    if any(unwanted in author for unwanted in parsed.not_authors):
        return False
    if parsed.terms:
        haystacks = (fields["message"], author)
        for term in parsed.terms:
            if not any(term in hay for hay in haystacks):
                return False
    return True


def _check_limit(limit: object) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool) \
            or limit < 1 or limit > MAX_LIMIT:
        raise _invalid(f"The limit is 1 to {MAX_LIMIT} commits.")
    return limit


# ------------------------------------------------------------------
# Hits and the executor
# ------------------------------------------------------------------

@dataclass(frozen=True)
class CommitHit:
    """One commit that matched: where it lives, its
    identity and parentage, who wrote it and when,
    its subject and body, and the fields its
    free-text terms matched in (empty for an
    author-only or scope-only hit)."""
    repo_id: int
    owner: str
    repo: str
    oid: str
    parents: tuple[str, ...]
    author_name: str
    author_email: str
    author_time: int
    subject: str
    body: str
    matched_fields: tuple[str, ...] = ()

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def message(self) -> str:
        if self.body:
            return self.subject + "\n\n" + self.body
        return self.subject


@dataclass(frozen=True)
class CommitSearchResults:
    """One permission-filtered commit search,
    counted (S-209): the hits a page shows (capped
    by the search's limit) and the total tallied
    over the full filtered result before the cap,
    counting only commits in repositories the
    searcher may read."""
    hits: tuple[CommitHit, ...]
    total: int


def _sort_hits(hits: list[CommitHit], sort: str) -> list[CommitHit]:
    """Order hits by author time — newest first by
    default, oldest first under `sort:oldest` —
    with repository and oid as the honest
    tie-break, so equal-time commits order the
    same way on every run."""
    if sort == "oldest":
        return sorted(
            hits, key=lambda h: (h.author_time, h.full_name.lower(),
                                 h.oid))
    return sorted(
        hits, key=lambda h: (-h.author_time, h.full_name.lower(), h.oid))


class CommitSearch:
    """The S-212 executor. It resolves the viewer's
    visible repositories through S-209's one
    resolution (over S-054's `can_read`) before any
    history is read, reads each survivor's commits
    through S-014's git seam and S-102's parser,
    and judges each with the pure
    `commit_matches_query`. It writes nothing."""

    def __init__(self, conn: sqlite3.Connection,
                 repositories: RepositoryStore):
        self._conn = conn
        self._repos = repositories

    def _commits_for(self, repo: Repository, *,
                     strict: bool) -> list[CommitSummary]:
        """One repository's commits, newest first,
        from every ref (`git log --all`, capped at
        `MAX_SCAN_PER_REPO`), parsed by S-102's own
        parser. An empty repository contributes
        nothing. An unreadable history fails a
        *strict* (scoped) read with
        `object_unreadable` and contributes nothing
        to a global one."""
        repo_path = self._repos.path_for(repo.owner, repo.name)
        result = run_git_in(
            repo_path,
            ["log", "--all", f"--max-count={MAX_SCAN_PER_REPO}",
             f"--format={_FORMAT}"],
            timeout=60.0)
        if result.returncode != 0:
            if strict:
                raise CommitSearchError(
                    "object_unreadable",
                    "That repository's history could not be read.")
            return []
        try:
            return parse_log_output(
                result.stdout.decode("utf-8", "replace"))
        except Exception:
            if strict:
                raise CommitSearchError(
                    "object_unreadable",
                    "That repository's history could not be read.")
            return []

    def _search_all(self, viewer: User | None, query: object = "", *,
                    author: object = None, owner: object = None,
                    repo: object = None, sort: object = None,
                    limit: int = DEFAULT_LIMIT,
                    ) -> list[CommitHit]:
        """Execute one commit search, whole (the
        public faces apply the *limit* cap). The
        query text's grammar is parsed first; the
        explicit keywords are additional qualifiers
        ANDed with it, except *sort*, which overrides
        the text's sort, and an explicit *owner* /
        *repo* pair, which overrides the text's
        `repo:` scope. A search with nothing to hunt
        is refused `query_invalid`."""
        parsed = parse_commit_query(query)
        authors = list(parsed.authors)
        final_sort = parsed.sort
        scope = parsed.repo_scope
        if author is not None:
            if not isinstance(author, str) or not author.strip():
                raise _invalid("An author filter is a name or email.")
            authors.append(author.strip().lower())
        if owner is not None or repo is not None:
            scoped = self._repos.get_repository(owner, repo)
            if scoped is None:
                raise CommitSearchError(
                    "repo_not_found", "No such repository.")
            scope = (scoped.owner_lower, scoped.name_lower)
        elif scope is not None:
            scoped = self._repos.get_repository(scope[0], scope[1])
            if scoped is None:
                raise CommitSearchError(
                    "repo_not_found", "No such repository.")
        else:
            scoped = None
        if sort is not None:
            final_sort = _check_sort(sort)
        _check_limit(limit)
        effective = CommitSearchQuery(
            terms=parsed.terms, authors=tuple(authors),
            not_authors=parsed.not_authors,
            repo_owner=scope[0] if scope else "",
            repo_name=scope[1] if scope else "", sort=final_sort)
        if effective.is_empty:
            raise _invalid(
                "A commit search needs words or an author to "
                "hunt for.")
        if scoped is not None:
            if not can_read(viewer, scoped):
                raise CommitSearchError(
                    "repo_not_found", "No such repository.")
            visible = [scoped]
            strict = True
        else:
            visible = visible_repositories(
                self._conn, self._repos, viewer)
            strict = False
        if not visible:
            return []
        hits: list[CommitHit] = []
        for current in visible:
            for summary in self._commits_for(current, strict=strict):
                if not commit_matches_query(summary, effective):
                    continue
                hits.append(CommitHit(
                    repo_id=current.id, owner=current.owner,
                    repo=current.name, oid=summary.oid,
                    parents=summary.parents,
                    author_name=summary.author_name,
                    author_email=summary.author_email,
                    author_time=summary.author_time,
                    subject=summary.subject, body=summary.body,
                    matched_fields=matched_fields(summary, effective)))
        return _sort_hits(hits, final_sort)

    def search(self, viewer: User | None, query: object = "", *,
               author: object = None, owner: object = None,
               repo: object = None, sort: object = None,
               limit: int = DEFAULT_LIMIT,
               ) -> list[CommitHit]:
        """Execute one commit search (see `_search_all`
        for the grammar and the law), capped at
        *limit* commits."""
        hits = self._search_all(
            viewer, query, author=author, owner=owner, repo=repo,
            sort=sort, limit=limit)
        return hits[:limit]

    def search_counted(self, viewer: User | None,
                       query: object = "", **kwargs,
                       ) -> CommitSearchResults:
        """One commit search with its S-209 count: the
        capped hits plus a total tallied over the full
        filtered result before the cap — an unreadable
        repository contributes no commit, no message,
        no author, and no count."""
        limit = kwargs.get("limit", DEFAULT_LIMIT)
        hits = self._search_all(viewer, query, **kwargs)
        return CommitSearchResults(
            hits=tuple(hits[:limit]), total=len(hits))

    def count(self, viewer: User | None, query: object = "",
              **kwargs) -> int:
        """Only the S-209 count of one commit search —
        the number on its own, computed from the
        filtered hits, never from the instance's
        histories."""
        return self.search_counted(viewer, query, **kwargs).total

    def search_repository(self, viewer: User | None,
                          owner: object, repo: object,
                          query: object = "", **kwargs,
                          ) -> list[CommitHit]:
        """One repository's commit search — the
        per-repository face of `search`, answering
        the uniform `repo_not_found` when the viewer
        may not read that repository."""
        return self.search(viewer, query, owner=owner, repo=repo,
                           **kwargs)


# ------------------------------------------------------------------
# Pages
# ------------------------------------------------------------------

def _format_time(author_time: int) -> str:
    """One commit's author time said in words: the
    UTC date and minute it was written."""
    return time.strftime("%Y-%m-%d %H:%M UTC",
                         time.gmtime(author_time))


def _hit_line(hit: CommitHit) -> str:
    """One result as a list item: where the commit
    lives, its subject, who wrote it and when, and
    the matched fields said in words when the search
    carried free text — every value escaped through
    S-010."""
    words = [f"{hit.full_name} — {hit.subject}"]
    words.append(
        f"by {hit.author_name} <{hit.author_email}>")
    words.append(_format_time(hit.author_time))
    if hit.matched_fields:
        words.append(
            "Matched in: " + ", ".join(hit.matched_fields))
    return f"<li>{escape_html_text(' — '.join(words))}</li>"


def render_commit_search_page(query: object,
                              hits: list[CommitHit], *,
                              total: int | None = None) -> str:
    """The search results page: the search as typed
    (escaped through S-010), the qualifier help in
    plain words, the count of visible matches
    (the S-209 total when given, before any cap),
    and each hit with its repository, subject,
    author, and time."""
    query_text = query if isinstance(query, str) else ""
    shown_total = len(hits) if total is None else total
    parts = [
        "<h1>Search commits</h1>",
        '<form method="get" action="search" role="search">',
        '<label for="q">Search commits</label>',
        f'<input id="q" name="q" type="search" '
        f'value="{escape_html_attr(query_text)}">',
        '<input type="hidden" name="type" value="commits">',
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
        f"{'commit matches' if shown_total == 1 else 'commits match'}"
        " — only commits in repositories you can read "
        "are counted.</p>")
    if not hits:
        parts.append(
            '<p class="empty">No commits match. Try fewer '
            "words, or a different author.</p>")
        return "\n".join(parts)
    parts.append('<ul class="search-results">')
    for hit in hits:
        parts.append(_hit_line(hit))
    parts.append("</ul>")
    return "\n".join(parts)
