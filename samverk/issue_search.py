"""Issue search UI (S-135).

A small, honest qualifier language over one repository's
issues — the subset the roadmap names for this slice
(`is:open`, `label:`, `author:`, `assignee:`, `milestone:`),
with the full grammar documented in research file 19
(`research/19-issue-search-and-queries.md`). Part X's
S-206 executes the wider grammar over the global index;
this slice is the per-repository issue page.

- **Tokens are words, qualifiers, or quoted phrases.**
  A token containing `:` whose head is a known qualifier
  name is a qualifier; its value may be quoted
  (`label:"good first issue"`, `milestone:"Launch 1"`),
  because label and milestone names carry spaces. Every
  other token is free text, matched case-insensitively
  against the issue's title and body.
- **Unknown qualifiers fail closed.** A token shaped
  like a qualifier whose name is not in the subset is
  refused `query_invalid`, naming the qualifier — never
  silently dropped (a dropped qualifier would silently
  widen the search, the S-118 law) and never treated as
  free text. An empty qualifier value, an unterminated
  quote, and an `is:` value outside its vocabulary are
  the same refusal.
- **Qualifiers compose by AND.** Every qualifier and
  every free-text term must hold; repeated `label:`
  qualifiers require every named label. Matching reads
  through the owning seams — S-122's list, S-124's
  labels, S-126's assignees, S-125's milestone column —
  so permissions and shapes cannot drift from the
  stores that own them.
- **Permission is S-054's.** Searching follows the
  repository read gate through `IssueStore.list_issues`:
  a stranger to a private repository gets the uniform
  `issue_not_found`, and a search can never enumerate
  what its viewer cannot read.
- **No audit event of its own.** A search mutates
  nothing; it is a read, witnessed like other reads.
- **The page teaches the language.** `render_search_page`
  renders the GET form with the query as typed (escaped
  through S-010), a plain-words list of the qualifiers,
  each result with its number, title, and state said in
  words (never a colour alone), and an empty state that
  says what to try next.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from .accounts import AccountStore, User
from .assignees import AssigneeStore
from .escaping import escape_html_attr, escape_html_text
from .issues import Issue, IssueError, IssueStore
from .labels import LabelStore
from .repositories import RepositoryStore

QUALIFIER_NAMES = frozenset(
    {"is", "label", "author", "assignee", "milestone"})
IS_VALUES = frozenset({"open", "closed", "issue"})
QUERY_MAX = 500

QUALIFIER_HELP: tuple[tuple[str, str], ...] = (
    ("is:open / is:closed", "only issues in that state"),
    ("label:NAME", "only issues carrying that label; "
                    "quote names with spaces"),
    ("author:NAME", "only issues written by that account"),
    ("assignee:NAME", "only issues assigned to that account"),
    ("milestone:TITLE", "only issues in that milestone; "
                        "quote titles with spaces"),
)


class SearchError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class ParsedQuery:
    text_terms: tuple[str, ...] = ()
    states: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()
    authors: tuple[str, ...] = ()
    assignees: tuple[str, ...] = ()
    milestones: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.text_terms or self.states or self.labels
                    or self.authors or self.assignees or self.milestones)


def _tokenise(query: str) -> list[str]:
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
                    raise SearchError(
                        "query_invalid",
                        "A quoted value needs its closing quote.")
                buf.append(query[i + 1:end])
                i = end + 1
            else:
                buf.append(query[i])
                i += 1
        tokens.append("".join(buf))
    return tokens


def parse_query(query: object) -> ParsedQuery:
    """Parse *query* under the S-135 grammar. A non-string,
    over-long, or malformed query is refused `query_invalid`."""
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
        raise SearchError("query_invalid", "A search is one line of text.")
    text_terms: list[str] = []
    states: list[str] = []
    labels: list[str] = []
    authors: list[str] = []
    assignees: list[str] = []
    milestones: list[str] = []
    for token in _tokenise(query):
        head, sep, value = token.partition(":")
        if sep and head.lower() in QUALIFIER_NAMES:
            name = head.lower()
            if not value.strip():
                raise SearchError(
                    "query_invalid",
                    f"The {name}: qualifier needs a value.")
            value = value.strip()
            if name == "is":
                low = value.lower()
                if low not in IS_VALUES:
                    raise SearchError(
                        "query_invalid",
                        "is: takes open, closed, or issue.")
                if low in ("open", "closed") and low not in states:
                    states.append(low)
            elif name == "label":
                if value.lower() not in [v.lower() for v in labels]:
                    labels.append(value)
            elif name == "author":
                if value.lower() not in [v.lower() for v in authors]:
                    authors.append(value)
            elif name == "assignee":
                if value.lower() not in [v.lower() for v in assignees]:
                    assignees.append(value)
            else:  # milestone
                if value.lower() not in [v.lower() for v in milestones]:
                    milestones.append(value)
        elif sep and head and all(c.isalnum() or c in "_-" for c in head):
            raise SearchError(
                "query_invalid",
                f"There is no {head}: qualifier in issue search; "
                "the qualifiers are is:, label:, author:, "
                "assignee:, and milestone:.")
        else:
            text_terms.append(token)
    return ParsedQuery(
        text_terms=tuple(text_terms), states=tuple(states),
        labels=tuple(labels), authors=tuple(authors),
        assignees=tuple(assignees), milestones=tuple(milestones))


class IssueSearch:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        issues: IssueStore,
        labels: LabelStore,
        assignees: AssigneeStore,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._issues = issues
        self._labels = labels
        self._assignees = assignees

    def search(self, viewer: User | None, owner: object, repo: object,
               query: object) -> list[Issue]:
        """The issues in this repository matching *query*,
        in number order. Permission and the uniform
        private answer ride S-122's list seam."""
        parsed = parse_query(query)
        if len(parsed.states) > 1:
            return []  # open AND closed at once matches nothing
        state = parsed.states[0] if parsed.states else None
        selected = self._issues.list_issues(viewer, owner, repo, state=state)
        current = self._repos.get_repository(owner, repo)
        assert current is not None  # list_issues already gated
        milestone_titles: dict[int, str] = {}
        if parsed.milestones:
            milestone_titles = {
                int(r["id"]): r["title"] for r in self._conn.execute(
                    "SELECT id, title FROM milestones WHERE repo_id = ?",
                    (current.id,)).fetchall()}
        results: list[Issue] = []
        for issue in selected:
            if parsed.text_terms:
                haystack = f"{issue.title}\n{issue.body}".lower()
                if any(term.lower() not in haystack
                       for term in parsed.text_terms):
                    continue
            if parsed.labels:
                names = {l.name_lower for l in self._labels.labels_for_issue(
                    viewer, owner, repo, issue.number)}
                if any(v.lower() not in names for v in parsed.labels):
                    continue
            if parsed.assignees:
                names = {a.username.lower() for a in
                         self._assignees.assignees_for_issue(
                             viewer, owner, repo, issue.number)}
                if any(v.lower() not in names for v in parsed.assignees):
                    continue
            if parsed.authors:
                writer = self._accounts.get_by_id(issue.author_id)
                if writer is None or writer.username_lower not in [
                        v.lower() for v in parsed.authors]:
                    continue
            if parsed.milestones:
                row = self._conn.execute(
                    "SELECT milestone_id FROM issues WHERE id = ?",
                    (issue.id,)).fetchone()
                title = milestone_titles.get(row["milestone_id"]) \
                    if row is not None and row["milestone_id"] else None
                if title is None or title.lower() not in [
                        v.lower() for v in parsed.milestones]:
                    continue
            results.append(issue)
        return results


def render_search_page(owner: object, repo: object, query: object,
                       results: list[Issue]) -> str:
    """The issue search page: the form as typed, the
    qualifier help in plain words, and the results with
    state said in words. All user text through S-010."""
    query_text = query if isinstance(query, str) else ""
    parts = [
        "<h1>Issues</h1>",
        '<form method="get" action="issues" role="search">',
        '<label for="q">Search issues</label>',
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
    if not results:
        parts.append(
            '<p class="empty">No issues match. Try fewer '
            "qualifiers, or clear the search to see every "
            "issue.</p>")
    else:
        parts.append('<ul class="issue-results">')
        for issue in results:
            parts.append(
                f'<li><a href="issues/{issue.number}">'
                f"#{issue.number} {escape_html_text(issue.title)}</a>"
                f" — {escape_html_text(issue.state_words)}</li>")
        parts.append("</ul>")
    return "\n".join(parts)
