"""Wiki/gist search (S-287).

Wiki pages and gists join Part X's index under the
same permission filtering — Part XIV's closing
search slice, beside S-212's commit search (the
live-read face whose shape this one follows) and
under S-209's leakage law, which this slice extends
to the two kinds Part X did not yet hunt.

- **What joins, said plainly.** A *wiki page* is
  searched by its page name and its standing body,
  inside its parent repository. A *gist* is
  searched by its one description, its file names,
  and its files' standing bodies, as one hit per
  gist (never one hit per file: a gist is one
  thing, S-277's mini-repository). Both kinds are
  gathered live from their owning stores at query
  time — the wiki through S-273's `WikiStore`, the
  gists through S-277's `GistStore` — exactly as
  S-212 reads histories live through git; there is
  no second index table to drift from the stores,
  and no migration: schema stands at 114.
- **One small grammar.** Free-text terms (a
  double-quoted phrase is one term) plus `type:`
  qualifiers naming the kinds to search — `wiki`
  (aliases `wikis`) and `gists` (alias `gist`) —
  with a leading `-` negating one `type:`. Every
  term must hold somewhere in the hit (AND across
  terms, the Part X composition law), matched as a
  case-insensitive substring. A token shaped like
  an unknown qualifier is refused `query_invalid`,
  naming it — never silently dropped, because a
  dropped qualifier widens the search (the S-118
  law). An empty search, a words-less search, an
  unterminated quote, a control character, an
  over-long query, and a bad limit are the same
  refusal.
- **Matching is pure, and says where it hit.**
  `wiki_page_matches` and `gist_matches` judge one
  candidate's already-read facts against the
  parsed query with no storage read; `matched_fields`
  names the fields a hit matched in (`title` /
  `content` for a page; `description` / `filename`
  / `content` for a gist), so a page can say *why*
  a hit matched. Snippets are S-208's own
  `Snippet` blocks, built here over the matched
  body text with matched-line context.
- **Permission is S-209's filtered law, per kind.**
  Wiki: the viewer's visible repositories are
  resolved through S-209's one resolution
  (`visible_repositories`, over S-054's `can_read`)
  *before* any wiki is read — git is spawned only
  for repositories that survive it — so a private
  repository's wiki contributes no page, no title,
  no snippet, and no count. Gists: S-278's listing
  law is the search law — a *public* gist is
  findable by anyone, signed in or not; a *secret*
  gist is findable only by its owner (or a site
  admin). The visibility filter runs over the gist
  rows *before* any description is matched or any
  file is read, because a secret gist's read-by-link
  reach (S-278) is not a listing reach: search must
  never reveal a secret gist's description, file
  names, content, or count to anyone but its owner.
  Both counted faces tally totals over the filtered
  hits only, before any result cap — the S-209
  equivalence holds per kind: a stranger's hits and
  counts over a world containing a planted private
  wiki or secret gist are identical to the same
  search over a world where it was never created.
- **Broken neighbours contribute nothing.** A wiki
  that cannot be read, a wiki page that is not
  readable text (its name still searches), and a
  gist file that is not readable text (its name
  and its gist's description still search) never
  blind the whole hunt; the scoped wiki face
  (`search_repository`) answers the uniform
  `repo_not_found` for an unreadable or missing
  repository, worded identically either way.
- **The global fan-out rides this executor.**
  S-213's one box gains the `wiki` and `gists`
  groups through this module's counted faces, and
  S-216's / S-245's search APIs serialise them the
  same way — one executor, one filtering law, no
  per-surface copy that could drift.
- **No audit event of its own, no migration.**
  Searching is a read over reads. 133 events
  stand: 33 auth / 87 repo / 13 admin. Schema
  stands at 114.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore, User
from .code_search import Snippet, SnippetLine
from .escaping import escape_html_text
from .gists import GistError, GistStore
from .repositories import RepositoryStore
from .search_permissions import visible_repositories
from .wiki_storage import WikiError, WikiStore

__all__ = [
    "DEFAULT_LIMIT", "KIND_ALIASES", "KINDS", "MAX_LIMIT",
    "QUERY_MAX", "GistSearchHit", "GistSearchResults",
    "WikiGistQuery", "WikiGistResults", "WikiGistSearch",
    "WikiGistSearchError", "WikiSearchHit", "WikiSearchResults",
    "build_term_snippets", "gist_matches", "parse_wiki_gist_query",
    "render_wiki_gist_search_page", "wiki_page_matches",
]

QUERY_MAX = 500
DEFAULT_LIMIT = 100
MAX_LIMIT = 500
MAX_SNIPPETS = 3
CONTEXT_LINES = 1

KINDS: tuple[str, ...] = ("wiki", "gists")
KIND_ALIASES = {
    "wiki": "wiki", "wikis": "wiki",
    "gist": "gists", "gists": "gists",
}
QUALIFIER_NAMES = frozenset({"type"})
WIKI_FIELDS = ("title", "content")
GIST_FIELDS = ("description", "filename", "content")


class WikiGistSearchError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def _invalid(message: str) -> WikiGistSearchError:
    return WikiGistSearchError("query_invalid", message)


# ------------------------------------------------------------------
# The parsed query
# ------------------------------------------------------------------

@dataclass(frozen=True)
class WikiGistQuery:
    """One wiki/gist search, whole: the free-text
    terms (lowercased, in order; a quoted phrase is
    one term), the kinds the `type:` qualifiers
    named and negated (canonical names), and the
    search as typed (trimmed)."""
    terms: tuple[str, ...] = ()
    types: tuple[str, ...] = ()
    not_types: tuple[str, ...] = ()
    raw: str = ""

    @property
    def is_empty(self) -> bool:
        return not (self.terms or self.types or self.not_types)

    @property
    def kinds(self) -> tuple[str, ...]:
        """The kinds this search runs, in the fixed
        kind order: the positively named kinds, or
        every kind when none is named, minus the
        negated ones."""
        base = self.types if self.types else KINDS
        return tuple(k for k in KINDS
                     if k in base and k not in self.not_types)


def _tokenise(query: str) -> list[str]:
    """Split a query line into tokens: whitespace
    separates, a double-quoted span stays inside its
    token (so `"my phrase"` is one term and
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


def _check_kind(value: object) -> str:
    if not isinstance(value, str) \
            or value.strip().lower() not in KIND_ALIASES:
        raise _invalid(
            "The type: qualifier names a kind: wiki or gists.")
    return KIND_ALIASES[value.strip().lower()]


def parse_wiki_gist_query(query: object) -> WikiGistQuery:
    """Parse query text into a `WikiGistQuery`:
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
                _check_kind(value))
            continue
        if colon and head and all(
                c.isalnum() or c in "_-" for c in head):
            raise _invalid(
                f"The qualifier {head!r} is not part of wiki/gist "
                "search. The grammar is free words plus type: "
                "(wiki, gists).")
        if negated:
            raise _invalid(
                "Only a type: qualifier can be negated.")
        if token:
            terms.append(token.lower())
    return WikiGistQuery(
        terms=tuple(terms), types=tuple(types),
        not_types=tuple(not_types), raw=query.strip())


def _check_limit(limit: object) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool) \
            or limit < 1 or limit > MAX_LIMIT:
        raise _invalid(
            f"The limit is 1 to {MAX_LIMIT} results per kind.")
    return limit


# ------------------------------------------------------------------
# Pure matching and snippets
# ------------------------------------------------------------------

def _term_fields(terms: tuple[str, ...],
                 fields: tuple[tuple[str, str], ...],
                 ) -> tuple[str, ...] | None:
    """Judge *terms* against named text *fields*:
    every term must appear (case-insensitive
    substring) in at least one field. Returns the
    matched field names, in the fields' own order,
    or None when any term holds nowhere."""
    lowered = tuple((name, text.lower()) for name, text in fields)
    matched: set[str] = set()
    for term in terms:
        holders = [name for name, text in lowered if term in text]
        if not holders:
            return None
        matched.update(holders)
    ordered: list[str] = []
    for name, _ in fields:
        if name in matched and name not in ordered:
            ordered.append(name)
    return tuple(ordered)


def wiki_page_matches(name: object, content: object,
                      parsed: WikiGistQuery,
                      ) -> tuple[str, ...] | None:
    """Judge one wiki page — its canonical *name*
    and standing *content* — against *parsed*.
    Returns its matched fields (`title`, `content`)
    or None. Pure: no storage is read here."""
    title = name if isinstance(name, str) else ""
    body = content if isinstance(content, str) else ""
    return _term_fields(
        parsed.terms, (("title", title), ("content", body)))


def gist_matches(description: object,
                 files: tuple[tuple[str, str], ...],
                 parsed: WikiGistQuery,
                 ) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    """Judge one gist — its *description* and its
    *files* as (name, content) pairs — against
    *parsed*. Returns (matched fields, matched file
    names) or None. A file matches when its name or
    its content holds a term. Pure."""
    desc = description if isinstance(description, str) else ""
    fields: list[tuple[str, str]] = [("description", desc)]
    for fname, _ in files:
        fields.append(("filename", fname))
    for _, content in files:
        fields.append(("content", content))
    matched = _term_fields(parsed.terms, tuple(fields))
    if matched is None:
        return None
    matched_files: list[str] = []
    for fname, content in files:
        low_name, low_body = fname.lower(), content.lower()
        if any(t in low_name or t in low_body for t in parsed.terms):
            matched_files.append(fname)
    return matched, tuple(matched_files)


def _line_spans(line: str, terms: tuple[str, ...],
                ) -> tuple[tuple[int, int], ...]:
    """Every occurrence of any term in *line*, as
    (start, end) character spans, in order."""
    low = line.lower()
    spans: list[tuple[int, int]] = []
    for term in terms:
        if not term:
            continue
        start = 0
        while True:
            found = low.find(term, start)
            if found < 0:
                break
            spans.append((found, found + len(term)))
            start = found + max(1, len(term))
    spans.sort()
    return tuple(spans)


def build_term_snippets(text: str, terms: tuple[str, ...], *,
                        context: int = CONTEXT_LINES,
                        max_snippets: int = MAX_SNIPPETS,
                        ) -> tuple[tuple[Snippet, ...], int]:
    """Build S-208 `Snippet` blocks over *text* for
    the lines holding any of *terms* (case-insensitive
    substring), with *context* lines around each
    matched line; overlapping windows merge. Returns
    (snippets, matched_line_count): the count is the
    text's whole truth even when `max_snippets` trims
    the blocks returned."""
    lines = text.splitlines()
    matched: dict[int, tuple[tuple[int, int], ...]] = {}
    for index, line in enumerate(lines):
        spans = _line_spans(line, terms)
        if spans:
            matched[index] = spans
    if not matched:
        return (), 0
    windows: list[tuple[int, int]] = []
    for index in sorted(matched):
        lo = max(0, index - context)
        hi = min(len(lines) - 1, index + context)
        if windows and lo <= windows[-1][1] + 1:
            windows[-1] = (windows[-1][0], max(windows[-1][1], hi))
        else:
            windows.append((lo, hi))
    snippets: list[Snippet] = []
    for lo, hi in windows[:max_snippets]:
        block = tuple(
            SnippetLine(
                number=i + 1, text=lines[i],
                is_match=i in matched,
                spans=matched.get(i, ()))
            for i in range(lo, hi + 1))
        snippets.append(Snippet(start_line=lo + 1, lines=block))
    return tuple(snippets), len(matched)


# ------------------------------------------------------------------
# Hits and results
# ------------------------------------------------------------------

@dataclass(frozen=True)
class WikiSearchHit:
    """One wiki page that matched: where it lives,
    the fields it matched in, its matched-line count
    in the body, and its snippets with context."""
    repo_id: int
    owner: str
    repo: str
    page_name: str
    filename: str
    matched_fields: tuple[str, ...]
    matched_lines: int
    snippets: tuple[Snippet, ...]

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


@dataclass(frozen=True)
class GistSearchHit:
    """One gist that matched: its identity and
    honest visibility, the fields it matched in, the
    files that matched, and snippets from the first
    content-matched file (named by `snippet_file`)."""
    gist_id: int
    owner: str
    description: str
    visibility: str
    matched_fields: tuple[str, ...]
    matched_files: tuple[str, ...]
    matched_lines: int
    snippet_file: str = ""
    snippets: tuple[Snippet, ...] = ()


@dataclass(frozen=True)
class WikiSearchResults:
    """One permission-filtered wiki search, counted
    (S-209): the hits a page shows (capped) and the
    total tallied over the full filtered result
    before the cap."""
    hits: tuple[WikiSearchHit, ...]
    total: int


@dataclass(frozen=True)
class GistSearchResults:
    """One permission-filtered gist search, counted
    (S-209) exactly as `WikiSearchResults`."""
    hits: tuple[GistSearchHit, ...]
    total: int


@dataclass(frozen=True)
class WikiGistResults:
    """One whole wiki/gist search: the query as
    typed, its parsed form, and one counted result
    per kind searched — None for a kind the query
    did not run. Totals are per kind, never summed
    (the kinds stand behind different permission
    boundaries: S-213's law)."""
    query: str
    parsed: WikiGistQuery
    wiki: WikiSearchResults | None = None
    gists: GistSearchResults | None = None


# ------------------------------------------------------------------
# The executor
# ------------------------------------------------------------------

class WikiGistSearch:
    """The S-287 executor. It owns no index and
    stores nothing: it resolves permission first
    (S-209's visible repositories for wiki pages;
    S-278's listing law for gists, judged over the
    gist rows before any gist fact is matched or
    read), then gathers candidates live from the
    owning stores and matches them purely."""

    def __init__(self, conn: sqlite3.Connection,
                 repositories: RepositoryStore,
                 *, wiki: WikiStore | None = None,
                 gists: GistStore | None = None,
                 data_root: Path | None = None):
        self._conn = conn
        self._repositories = repositories
        self._wiki = wiki or WikiStore(conn, repositories)
        if gists is not None:
            self._gists = gists
        else:
            root = data_root or repositories._data_root  # type: ignore[attr-defined]
            self._gists = GistStore(
                conn, Path(root), AccountStore(conn))

    # -- wiki ------------------------------------------------

    def _wiki_hits(self, viewer: User | None,
                   parsed: WikiGistQuery,
                   repos: list) -> list[WikiSearchHit]:
        hits: list[WikiSearchHit] = []
        for repo in repos:
            try:
                pages = self._wiki.list_pages(
                    viewer, repo.owner, repo.name)
            except WikiError:
                continue  # a broken wiki contributes nothing
            for page in pages:
                try:
                    full = self._wiki.read_page(
                        viewer, repo.owner, repo.name, page.name)
                    content = full.content
                except WikiError:
                    content = ""  # unreadable: the name still searches
                matched = wiki_page_matches(
                    page.name, content, parsed)
                if matched is None:
                    continue
                snippets, lines = build_term_snippets(
                    content, parsed.terms)
                hits.append(WikiSearchHit(
                    repo_id=repo.id, owner=repo.owner,
                    repo=repo.name, page_name=page.name,
                    filename=page.filename,
                    matched_fields=matched,
                    matched_lines=lines, snippets=snippets))
        hits.sort(key=lambda h: (h.full_name.lower(),
                                 h.page_name.lower()))
        return hits

    def search_wiki_counted(self, viewer: User | None,
                            query: object = "", *,
                            limit: int = DEFAULT_LIMIT,
                            ) -> WikiSearchResults:
        """One wiki search with its S-209 count: the
        capped hits plus a total tallied over the
        full filtered result before the cap."""
        parsed = parse_wiki_gist_query(query)
        _check_limit(limit)
        if not parsed.terms:
            raise _invalid("A search needs words to hunt for.")
        repos = visible_repositories(
            self._conn, self._repositories, viewer)
        hits = self._wiki_hits(viewer, parsed, repos)
        return WikiSearchResults(
            hits=tuple(hits[:limit]), total=len(hits))

    def search_repository(self, viewer: User | None,
                          owner: object, repo: object,
                          query: object = "", *,
                          limit: int = DEFAULT_LIMIT,
                          ) -> WikiSearchResults:
        """One repository's wiki pages, searched: the
        per-repository face. A repository the viewer
        cannot read (or that does not exist) answers
        the uniform `repo_not_found`, exactly as the
        wiki's own doors answer it."""
        parsed = parse_wiki_gist_query(query)
        _check_limit(limit)
        if not parsed.terms:
            raise _invalid("A search needs words to hunt for.")
        current = self._repositories.get_repository(owner, repo)
        visible = visible_repositories(
            self._conn, self._repositories, viewer)
        if current is None or all(
                r.id != current.id for r in visible):
            raise WikiGistSearchError(
                "repo_not_found", "No such repository.")
        hits = self._wiki_hits(viewer, parsed, [current])
        return WikiSearchResults(
            hits=tuple(hits[:limit]), total=len(hits))

    # -- gists -----------------------------------------------

    def _gist_candidates(self, viewer: User | None) -> list:
        """The gist rows *viewer* may find, judged
        before any gist fact is read: public gists
        for everyone; secret gists only for their
        owner or a site admin (S-278's listing law)."""
        rows = self._conn.execute(
            "SELECT g.id AS id, g.owner_id AS owner_id,"
            " g.visibility AS visibility,"
            " u.username AS owner FROM gists g"
            " JOIN users u ON u.id = g.owner_id"
            " ORDER BY g.id").fetchall()
        out = []
        for row in rows:
            if row["visibility"] == "public":
                out.append(row)
            elif viewer is not None and (
                    viewer.id == row["owner_id"]
                    or viewer.is_admin):
                out.append(row)
        return out

    def _gist_hits(self, viewer: User | None,
                   parsed: WikiGistQuery) -> list[GistSearchHit]:
        hits: list[GistSearchHit] = []
        for row in self._gist_candidates(viewer):
            gist_id = int(row["id"])
            try:
                gist = self._gists.get_gist(viewer, gist_id)
                files: list[tuple[str, str]] = []
                for entry in self._gists.list_files(viewer, gist_id):
                    try:
                        body = self._gists.read_file(
                            viewer, gist_id, entry.name)
                        files.append((entry.name, body.content))
                    except GistError:
                        files.append((entry.name, ""))
            except GistError:
                continue  # a broken gist contributes nothing
            judged = gist_matches(
                gist.description, tuple(files), parsed)
            if judged is None:
                continue
            matched, matched_files = judged
            snippets: tuple[Snippet, ...] = ()
            snippet_file = ""
            matched_lines = 0
            for fname, content in files:
                if fname not in matched_files:
                    continue
                built, lines = build_term_snippets(
                    content, parsed.terms)
                if built:
                    snippets, snippet_file = built, fname
                    matched_lines = lines
                    break
            hits.append(GistSearchHit(
                gist_id=gist.id, owner=gist.owner,
                description=gist.description,
                visibility=gist.visibility,
                matched_fields=matched,
                matched_files=matched_files,
                matched_lines=matched_lines,
                snippet_file=snippet_file, snippets=snippets))
        hits.sort(key=lambda h: (h.owner.lower(), h.gist_id))
        return hits

    def search_gists_counted(self, viewer: User | None,
                             query: object = "", *,
                             limit: int = DEFAULT_LIMIT,
                             ) -> GistSearchResults:
        """One gist search with its S-209 count,
        exactly as `search_wiki_counted`."""
        parsed = parse_wiki_gist_query(query)
        _check_limit(limit)
        if not parsed.terms:
            raise _invalid("A search needs words to hunt for.")
        hits = self._gist_hits(viewer, parsed)
        return GistSearchResults(
            hits=tuple(hits[:limit]), total=len(hits))

    # -- both kinds ------------------------------------------

    def search(self, viewer: User | None, query: object = "", *,
               limit: int = DEFAULT_LIMIT) -> WikiGistResults:
        """Execute one wiki/gist search over the kinds
        the query names (both by default). An empty
        query is refused `query_invalid` here — this
        face has no landing state; S-213's page owns
        that. A words-less query and a selection
        naming no kind are the same refusal."""
        parsed = parse_wiki_gist_query(query)
        _check_limit(limit)
        if parsed.is_empty or not parsed.terms:
            raise _invalid("A search needs words to hunt for.")
        kinds = parsed.kinds
        if not kinds:
            raise _invalid("That search names no kind.")
        text = " ".join(
            f'"{t}"' if " " in t else t for t in parsed.terms)
        wiki = (self.search_wiki_counted(viewer, text, limit=limit)
                if "wiki" in kinds else None)
        gists = (self.search_gists_counted(viewer, text, limit=limit)
                 if "gists" in kinds else None)
        return WikiGistResults(
            query=parsed.raw, parsed=parsed, wiki=wiki, gists=gists)


# ------------------------------------------------------------------
# Rendering
# ------------------------------------------------------------------

_WIKI_COUNT_LAW = (
    "only wiki pages in repositories you can read are counted")
_GIST_COUNT_LAW = (
    "only gists you may find are counted — public gists for "
    "everyone, and secret gists for their owner")


def _snippet_block(snippets: tuple[Snippet, ...]) -> list[str]:
    parts: list[str] = []
    for snippet in snippets:
        parts.append('<pre class="snippet">')
        for line in snippet.lines:
            flag = "matched line" if line.is_match else "context"
            parts.append(
                f"{line.number}: [{flag}] "
                f"{escape_html_text(line.text)}")
        parts.append("</pre>")
    return parts


def _wiki_section(found: WikiSearchResults) -> str:
    parts = [
        '<section class="search-group" id="group-wiki" tabindex="-1">',
        "<h2>Wiki pages</h2>",
        f"<p>{found.total} "
        f"{'wiki page matches' if found.total == 1 else 'wiki pages match'}"
        f" — {_WIKI_COUNT_LAW}.</p>",
    ]
    if found.total > len(found.hits):
        parts.append(
            f"<p>Showing the first {len(found.hits)} of "
            f"{found.total}.</p>")
    if not found.hits:
        parts.append(
            '<p class="empty">No wiki page matches. '
            "Try fewer words.</p></section>")
        return "\n".join(parts)
    parts.append('<ul class="search-results">')
    for hit in found.hits:
        words = [f"{hit.full_name} — {hit.page_name}"]
        words.append("Matched in: " + ", ".join(hit.matched_fields))
        parts.append(
            f"<li><p>{escape_html_text(' — '.join(words))}</p>")
        parts.extend(_snippet_block(hit.snippets))
        parts.append("</li>")
    parts.append("</ul></section>")
    return "\n".join(parts)


def _gist_section(found: GistSearchResults) -> str:
    parts = [
        '<section class="search-group" id="group-gists" tabindex="-1">',
        "<h2>Gists</h2>",
        f"<p>{found.total} "
        f"{'gist matches' if found.total == 1 else 'gists match'}"
        f" — {_GIST_COUNT_LAW}.</p>",
    ]
    if found.total > len(found.hits):
        parts.append(
            f"<p>Showing the first {len(found.hits)} of "
            f"{found.total}.</p>")
    if not found.hits:
        parts.append(
            '<p class="empty">No gist matches. '
            "Try fewer words.</p></section>")
        return "\n".join(parts)
    parts.append('<ul class="search-results">')
    for hit in found.hits:
        words = [f"{hit.owner} — gist #{hit.gist_id}"]
        if hit.description:
            words.append(hit.description)
        words.append(f"Visibility: {hit.visibility}")
        words.append("Matched in: " + ", ".join(hit.matched_fields))
        if hit.matched_files:
            words.append("Files: " + ", ".join(hit.matched_files))
        parts.append(
            f"<li><p>{escape_html_text(' — '.join(words))}</p>")
        if hit.snippets:
            parts.append(
                f"<p>{escape_html_text(hit.snippet_file)}</p>")
            parts.extend(_snippet_block(hit.snippets))
        parts.append("</li>")
    parts.append("</ul></section>")
    return "\n".join(parts)


def render_wiki_gist_search_page(
        query: object,
        results: WikiGistResults | None = None) -> str:
    """The wiki/gist search page: the query in
    words, then one section per kind searched, each
    with its own count and its own permission law
    stated beside it. With no *results*, the page
    is the honest invitation state and claims
    nothing. Every value escaped through S-010."""
    query_text = query if isinstance(query, str) else ""
    parts = ["<h1>Wiki and gist search</h1>"]
    if query_text:
        parts.append(
            f"<p>Search for {escape_html_text(query_text)} in "
            "wiki pages and gists.</p>")
    if results is None:
        parts.append(
            "<p>Wiki pages are searched by page name and body, "
            "inside the repositories you can read. Gists are "
            "searched by description, file names, and file "
            "bodies — public gists for everyone, secret gists "
            "only for their owner.</p>")
        return "\n".join(parts)
    if results.wiki is not None:
        parts.append(_wiki_section(results.wiki))
    if results.gists is not None:
        parts.append(_gist_section(results.gists))
    return "\n".join(parts)
