"""Code search basic (S-208).

Substring and regex modes, path and language
filters, result snippets with matched-line context
— Part X's query face over the code index S-207
fills (migration 82's `code_fts`), written from
research file 18. S-205 fixed the index law, S-206
built the issue/PR backend beside this one, and
S-207's extractor fills the rows this slice reads.
Querying is all this slice does: it writes nothing,
audits nothing, and grants no permission of its own.

- **Two modes, said plainly.** `substring` is a
  literal, case-insensitive hunt: the pattern is
  text, never a pattern language, and every
  non-overlapping occurrence on a line is a match.
  `regex` is a Python regular expression, matched
  case-sensitively (inline flags such as `(?i)`
  are the author's to write); a pattern that does
  not compile is refused `query_invalid`, naming
  the compiler's reason — never silently retried
  as a substring. The mode is chosen per search
  (`mode=` or a `mode:substring` / `mode:regex`
  qualifier in the query text), never guessed from
  the pattern's shape.
- **The query text is pattern plus qualifiers.**
  Tokens shaped `path:`, `language:` (or `lang:`),
  `repo:`, and `mode:` are qualifiers; everything
  else, joined in order, is the pattern — so a
  substring pattern may contain spaces. A token
  shaped like a qualifier with any other name is
  refused `query_invalid`, naming it: never dropped
  (a dropped qualifier widens the search, the
  S-118 law) and never folded into the pattern.
  `repo:owner/name` is S-118's scope contract,
  consumed through its own `extract_repo_scope`
  seam. Explicit keyword arguments override the
  same qualifier written in the text.
- **Filters judge the index's own facts.** The
  path filter judges the repository-relative path:
  a filter ending in `/` (or naming a directory)
  matches everything under that directory prefix,
  a filter naming a file matches that file, and a
  filter containing `*` or `?` is a glob matched
  against the whole path and against any suffix
  beginning at a path-segment boundary. The
  language filter is an exact, case-insensitive
  match on the language S-207 recorded (S-099's
  shared table via the extractor) — `python`
  finds Python files, never files that merely
  mention the word. Absolute paths and `..`
  filters are refused `query_invalid`.
- **Snippets carry matched-line context.** Each
  hit carries up to `MAX_SNIPPETS_PER_FILE`
  snippet blocks: the matched line plus
  `context` lines either side (0 to 3, default 1),
  with windows that overlap or touch merged into
  one block. Every line says its 1-based number
  and whether it matched; every match says its
  character span on its line, so a page can mark
  exactly the matched text. The hit also says the
  file's true total match count, even when the
  snippet cap trims what is shown — shown and
  counted are never confused.
- **Matching is a per-line scan, honestly.** FTS5
  answers whole tokens; substring and regex hunts
  cannot be its MATCH, so the executor reads the
  candidate rows (already narrowed by repository,
  path, and language) and scans line by line.
  The cost caps are stated, not hidden: patterns
  are at most `PATTERN_MAX` characters, results
  are capped by `limit` files (default 100, at
  most 500), and snippets per file are capped as
  above. S-217 measures the latency budget and
  S-219 writes the honest limits where users find
  them; this slice states its own caps here.
- **Permission today is S-054's gate; S-209 owns
  the hardening.** Visible repositories are
  resolved through `can_read` before any index
  row is read — the S-206 seam — so a hit can
  only ever name a repository its viewer may
  read, and a scoped search for an unreadable
  (or missing) repository answers the uniform
  `repo_not_found`. S-209 owns the leakage
  battery and the count/snippet guarantees and
  can tighten the resolution in this one place.
- **No audit event of its own.** Searching is a
  read. 122 events stand: 31 auth / 79 repo /
  12 admin. No migration: schema stays 82.
"""

from __future__ import annotations

import fnmatch
import re
import sqlite3
from dataclasses import dataclass

from .accounts import User
from .escaping import escape_html_attr, escape_html_text
from .permissions import can_read
from .repo_search import SearchBoxError, extract_repo_scope
from .repositories import Repository, RepositoryStore

__all__ = [
    "MODES", "PATTERN_MAX", "CodeSearch", "CodeSearchError",
    "CodeSearchHit", "CodeSearchQuery", "Snippet", "SnippetLine",
    "find_line_matches", "matches_language", "matches_path",
    "parse_code_query", "render_code_search_page",
]

PATTERN_MAX = 500
DEFAULT_LIMIT = 100
MAX_LIMIT = 500
MAX_CONTEXT = 3
MAX_SNIPPETS_PER_FILE = 20
MODES = frozenset({"substring", "regex"})
_QUALIFIERS = frozenset({"path", "language", "lang", "mode", "repo"})


class CodeSearchError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def _invalid(message: str) -> CodeSearchError:
    return CodeSearchError("query_invalid", message)


# ------------------------------------------------------------------
# The parsed query
# ------------------------------------------------------------------

@dataclass(frozen=True)
class CodeSearchQuery:
    """One code search, whole: the pattern and the
    mode that interprets it, the path and language
    filters ('' when unset), and the repository
    scope (lowercased owner/name, '' when global)."""
    pattern: str = ""
    mode: str = "substring"
    path: str = ""
    language: str = ""
    repo_owner: str = ""
    repo_name: str = ""

    @property
    def repo_scope(self) -> tuple[str, str] | None:
        if self.repo_owner and self.repo_name:
            return (self.repo_owner, self.repo_name)
        return None


def _check_pattern(pattern: object) -> str:
    if pattern is None:
        return ""
    if not isinstance(pattern, str):
        raise _invalid("A search pattern is text.")
    if len(pattern) > PATTERN_MAX:
        raise _invalid(
            f"A search pattern is at most {PATTERN_MAX} characters.")
    if any((ord(c) < 0x20 and c != "\t") or ord(c) == 0x7F
           for c in pattern):
        raise _invalid("A search pattern carries no control characters.")
    return pattern


def _check_mode(mode: object) -> str:
    if not isinstance(mode, str) or mode.lower() not in MODES:
        raise _invalid(
            "The mode is 'substring' or 'regex'.")
    return mode.lower()


def _check_path_filter(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise _invalid("A path filter is text.")
    text = value.strip()
    if text.startswith("/") or text == ".." \
            or text.startswith("../") or "/../" in text \
            or text.endswith("/.."):
        raise _invalid(
            "A path filter is a repository-relative path, "
            "never absolute and never with '..'.")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in text):
        raise _invalid("A path filter carries no control characters.")
    return text


def _check_language(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise _invalid("A language filter is text.")
    return value.strip().lower()


def parse_code_query(query: object) -> CodeSearchQuery:
    """Parse query text into a `CodeSearchQuery`:
    `path:`, `language:`/`lang:`, and `mode:`
    qualifiers are lifted out, `repo:owner/name` is
    consumed through S-118's `extract_repo_scope`
    seam, and the remaining tokens joined in order
    are the pattern. An unknown qualifier-shaped
    token, a bad mode, or a malformed scope is
    refused `query_invalid`, naming the problem."""
    if query is None:
        query = ""
    if not isinstance(query, str):
        raise _invalid("A search is text.")
    try:
        scoped = extract_repo_scope(query)
    except SearchBoxError as exc:
        raise _invalid(str(exc)) from None
    owner = name = ""
    text = query
    if scoped is not None:
        owner, name, text = scoped
        owner, name = owner.lower(), name.lower()
    pattern_tokens: list[str] = []
    path = language = ""
    mode = "substring"
    for token in text.split():
        qual, colon, value = token.partition(":")
        if colon and qual.lower() in _QUALIFIERS and qual.lower() != "repo":
            if not value:
                raise _invalid(f"The {qual}: qualifier needs a value.")
            if qual.lower() == "path":
                path = _check_path_filter(value)
            elif qual.lower() == "mode":
                mode = _check_mode(value)
            else:
                language = _check_language(value)
            continue
        if colon and re.match(r"^[A-Za-z][A-Za-z0-9_-]*:", token):
            raise _invalid(
                f"The qualifier {qual!r} is not part of code search. "
                "Known qualifiers: path:, language:, repo:, mode:.")
        pattern_tokens.append(token)
    pattern = _check_pattern(" ".join(pattern_tokens))
    return CodeSearchQuery(
        pattern=pattern, mode=mode, path=path,
        language=language, repo_owner=owner, repo_name=name)


# ------------------------------------------------------------------
# Pure law: filters and per-line matching
# ------------------------------------------------------------------

def matches_path(path: str, path_filter: str) -> bool:
    """Whether *path* passes *path_filter*, under the
    documented shapes: an empty filter passes all; a
    glob (carrying `*` or `?`) is matched against the
    whole path and against any suffix beginning at a
    segment boundary; any other filter matches the
    file it names exactly, or everything under it
    when it names a directory prefix."""
    if not path_filter:
        return True
    filt = path_filter.rstrip("/")
    if not filt:
        return True
    if "*" in filt or "?" in filt:
        if fnmatch.fnmatchcase(path, filt):
            return True
        parts = path.split("/")
        return any(fnmatch.fnmatchcase("/".join(parts[i:]), filt)
                   for i in range(1, len(parts)))
    return path == filt or path.startswith(filt + "/")


def matches_language(language: str, language_filter: str) -> bool:
    """Whether an indexed *language* passes the
    filter: an exact match, case-insensitively; an
    empty filter passes all."""
    if not language_filter:
        return True
    return language.lower() == language_filter.lower()


def _compile(pattern: str, mode: str):
    """The matcher for one (pattern, mode): a compiled
    regex for regex mode (a bad pattern refused
    `query_invalid` with the compiler's reason), or
    None for substring mode, which needs no compile."""
    if mode != "regex":
        return None
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise _invalid(
            f"The regex {pattern!r} does not compile: {exc}.") from None


def find_line_matches(line: str, pattern: str, mode: str,
                      compiled=None) -> tuple[tuple[int, int], ...]:
    """Every match span (start, end) of *pattern* on
    one *line*, in order. Substring mode is literal
    and case-insensitive (non-overlapping spans);
    regex mode yields the compiled pattern's spans,
    zero-width matches included. An empty pattern
    matches nothing."""
    if not pattern:
        return ()
    if mode == "regex":
        rx = compiled if compiled is not None else _compile(pattern, mode)
        return tuple((m.start(), m.end()) for m in rx.finditer(line))
    spans: list[tuple[int, int]] = []
    haystack = line.casefold()
    needle = pattern.casefold()
    start = 0
    while True:
        found = haystack.find(needle, start)
        if found < 0:
            return tuple(spans)
        spans.append((found, found + len(needle)))
        start = found + max(1, len(needle))


@dataclass(frozen=True)
class SnippetLine:
    """One line inside a snippet: its 1-based number,
    its text, whether it matched, and — for a matched
    line — its match spans in character offsets."""
    number: int
    text: str
    is_match: bool
    spans: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class Snippet:
    """One block of matched-line context: consecutive
    lines from `start_line`, matched lines flagged
    in place among their context."""
    start_line: int
    lines: tuple[SnippetLine, ...]

    @property
    def match_numbers(self) -> tuple[int, ...]:
        return tuple(l.number for l in self.lines if l.is_match)


def build_snippets(text: str, pattern: str, mode: str, *,
                   context: int = 1, compiled=None,
                   max_snippets: int = MAX_SNIPPETS_PER_FILE,
                   ) -> tuple[tuple[Snippet, ...], int, int]:
    """Scan *text* line by line and build its
    snippets. Returns (snippets, total_matches,
    matched_lines): the counts are the file's whole
    truth even when `max_snippets` trims the blocks
    returned. Context windows that overlap or touch
    merge into one block."""
    if context < 0 or context > MAX_CONTEXT:
        raise _invalid(f"Context is 0 to {MAX_CONTEXT} lines.")
    lines = text.splitlines()
    matched: dict[int, tuple[tuple[int, int], ...]] = {}
    total = 0
    for index, line in enumerate(lines):
        spans = find_line_matches(line, pattern, mode, compiled)
        if spans:
            matched[index] = spans
            total += len(spans)
    if not matched:
        return (), 0, 0
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
    return tuple(snippets), total, len(matched)


# ------------------------------------------------------------------
# Hits and the executor over migration 82
# ------------------------------------------------------------------

@dataclass(frozen=True)
class CodeSearchHit:
    """One file that matched: where it lives, the
    facts S-207 recorded for it, its true match
    counts, and its snippets with matched-line
    context. A pointer hit is labelled a pointer —
    its text is the pointer's own, said honestly."""
    repo_id: int
    owner: str
    repo: str
    path: str
    language: str
    disposition: str          # 'index' | 'index_pointer'
    commit_oid: str
    digest: str
    match_count: int
    matched_lines: int
    snippets: tuple[Snippet, ...]

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def is_pointer(self) -> bool:
        return self.disposition == "index_pointer"


class CodeSearch:
    """The S-208 executor. It resolves the viewer's
    visible repositories through S-054's `can_read`
    before any index row is read (the S-206/S-209
    seam), narrows migration 82's rows by scope,
    path, and language, then scans each candidate
    file's text line by line under the chosen mode.
    It writes nothing."""

    def __init__(self, conn: sqlite3.Connection,
                 repositories: RepositoryStore):
        self._conn = conn
        self._repos = repositories

    def _visible_repos(self, viewer: User | None,
                       scoped: Repository | None,
                       ) -> list[Repository]:
        """The repositories a search may read, resolved
        before any index row is touched. A named
        repository the viewer cannot read — or that
        does not exist — answers the uniform
        `repo_not_found`."""
        if scoped is not None:
            if not can_read(viewer, scoped):
                raise CodeSearchError(
                    "repo_not_found", "No such repository.")
            return [scoped]
        visible: list[Repository] = []
        for found in self._conn.execute(
                "SELECT id FROM repositories ORDER BY id").fetchall():
            current = self._repos.get_by_id(int(found["id"]))
            if current is not None and can_read(viewer, current):
                visible.append(current)
        return visible

    def search(self, viewer: User | None, query: object = "", *,
               pattern: object = None, mode: object = None,
               path: object = None, language: object = None,
               owner: object = None, repo: object = None,
               context: int = 1,
               limit: int = DEFAULT_LIMIT,
               ) -> list[CodeSearchHit]:
        """Execute one code search. The pattern and
        filters come from the query text's grammar,
        overridden by any explicit keyword given;
        *pattern* given explicitly is taken literally
        and never qualifier-parsed. With *owner* and
        *repo* (or a `repo:` qualifier) the search is
        that repository's; otherwise it is global over
        every repository the viewer may read. An empty
        pattern is refused `query_invalid` — a code
        search with nothing to hunt is a listing, and
        listings are not this slice. Results are
        ordered by repository, then path, capped at
        *limit* files."""
        parsed = parse_code_query(query)
        final_pattern = parsed.pattern if pattern is None \
            else _check_pattern(pattern)
        if isinstance(pattern, str) and pattern == "":
            final_pattern = ""
        final_mode = parsed.mode if mode is None else _check_mode(mode)
        final_path = parsed.path if path is None \
            else _check_path_filter(path)
        final_language = parsed.language if language is None \
            else _check_language(language)
        if not final_pattern:
            raise _invalid("A code search needs a pattern to hunt for.")
        if context < 0 or context > MAX_CONTEXT:
            raise _invalid(f"Context is 0 to {MAX_CONTEXT} lines.")
        if not isinstance(limit, int) or isinstance(limit, bool) \
                or limit < 1 or limit > MAX_LIMIT:
            raise _invalid(f"The limit is 1 to {MAX_LIMIT} files.")
        compiled = _compile(final_pattern, final_mode)
        scoped = None
        scope = parsed.repo_scope
        if owner is not None or repo is not None:
            scoped = self._repos.get_repository(owner, repo)
            if scoped is None:
                raise CodeSearchError(
                    "repo_not_found", "No such repository.")
        elif scope is not None:
            scoped = self._repos.get_repository(scope[0], scope[1])
            if scoped is None:
                raise CodeSearchError(
                    "repo_not_found", "No such repository.")
        visible = self._visible_repos(viewer, scoped)
        if not visible:
            return []
        by_id = {r.id: r for r in visible}
        placeholders = ", ".join("?" for _ in visible)
        rows = self._conn.execute(
            "SELECT path, text, repo_id, commit_oid, digest,"
            " language, disposition FROM code_fts"
            f" WHERE repo_id IN ({placeholders}) ORDER BY path",
            tuple(by_id.keys())).fetchall()
        hits: list[CodeSearchHit] = []
        for row in rows:
            if not matches_path(row["path"], final_path):
                continue
            if not matches_language(row["language"], final_language):
                continue
            snippets, total, matched_lines = build_snippets(
                row["text"], final_pattern, final_mode,
                context=context, compiled=compiled)
            if total == 0:
                continue
            current = by_id[int(row["repo_id"])]
            hits.append(CodeSearchHit(
                repo_id=int(row["repo_id"]), owner=current.owner,
                repo=current.name, path=row["path"],
                language=row["language"],
                disposition=row["disposition"],
                commit_oid=row["commit_oid"], digest=row["digest"],
                match_count=total, matched_lines=matched_lines,
                snippets=snippets))
        hits.sort(key=lambda h: (h.full_name.lower(), h.path))
        return hits[:limit]

    def search_repository(self, viewer: User | None,
                          owner: object, repo: object,
                          query: object = "", **kwargs,
                          ) -> list[CodeSearchHit]:
        """One repository's code search — the
        per-repository face of `search`."""
        return self.search(viewer, query, owner=owner, repo=repo,
                           **kwargs)


def _render_line(line: SnippetLine) -> str:
    """One snippet line as escaped HTML: matched spans
    wrapped in <mark>, every byte through S-010's
    escaping segment by segment, so stored markup in
    code renders as visible text, never as tags."""
    if not line.spans:
        return escape_html_text(line.text)
    parts: list[str] = []
    cursor = 0
    for start, end in line.spans:
        if start > cursor:
            parts.append(escape_html_text(line.text[cursor:start]))
        if end > start:
            parts.append(
                f"<mark>{escape_html_text(line.text[start:end])}</mark>")
        cursor = max(cursor, end)
    if cursor < len(line.text):
        parts.append(escape_html_text(line.text[cursor:]))
    return "".join(parts)


def render_code_search_page(query: object,
                            hits: list[CodeSearchHit], *,
                            mode: object = "substring") -> str:
    """The results page: the search as typed (escaped
    through S-010), the mode and the filter law said
    in plain words, and each hit with its repository,
    path, language, and true match count, followed by
    its snippets — line numbers in the gutter, matched
    lines flagged in words as well as by <mark>, and
    LFS pointers labelled as pointers."""
    query_text = query if isinstance(query, str) else ""
    mode_text = mode if isinstance(mode, str) else "substring"
    parts = [
        "<h1>Search code</h1>",
        '<form method="get" action="search" role="search">',
        '<label for="q">Search code</label>',
        f'<input id="q" name="q" type="search" '
        f'value="{escape_html_attr(query_text)}">',
        '<input type="hidden" name="type" value="code">',
        '<button type="submit">Search</button>',
        "</form>",
        f"<p>Mode: {escape_html_text(mode_text)}. Filters: "
        "path:PATH narrows to a path or directory, "
        "language:NAME narrows to one language, "
        "repo:OWNER/NAME narrows to one repository, "
        "mode:regex switches to regular expressions.</p>",
    ]
    if not hits:
        parts.append(
            '<p class="empty">No indexed code matches. '
            "Try a different pattern, or check the path "
            "and language filters.</p>")
        return "\n".join(parts)
    parts.append('<ul class="search-results">')
    for hit in hits:
        words = (f"{hit.match_count} matches on "
                 f"{hit.matched_lines} lines")
        if hit.is_pointer:
            words += " — LFS pointer (the pointer text itself)"
        parts.append("<li>")
        parts.append(
            f"<p>{escape_html_text(hit.full_name)} "
            f"{escape_html_text(hit.path)} — "
            f"{escape_html_text(hit.language)} — "
            f"{escape_html_text(words)}</p>")
        for snippet in hit.snippets:
            parts.append('<pre class="snippet">')
            for line in snippet.lines:
                flag = "matched line" if line.is_match else "context"
                parts.append(
                    f"{line.number}: [{flag}] {_render_line(line)}")
            parts.append("</pre>")
        parts.append("</li>")
    parts.append("</ul>")
    return "\n".join(parts)
