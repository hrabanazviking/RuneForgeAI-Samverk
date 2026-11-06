"""Pull request search (S-161).

The Part X qualifier language extended to pull requests:
S-135's per-repository issue grammar grows the three
qualifiers this slice names — `is:pr`, `review:`, and
`status:` — over one repository's pull requests.

- **`is:` gains `pr` and `draft`.** `is:pr` is the kind
  marker (research 19 reserves it for the full grammar);
  every result of this search is a pull request, so the
  marker is validated and holds by construction. `is:open`
  / `is:closed` filter the state column, drafts included
  in open; `is:draft` requires an open draft.
- **`review:` reads S-148's summary seam.** Its values
  are `approved`, `commented`, and `changes_requested`
  (the hyphenated spelling is accepted and normalised),
  each holding when some reviewer's *latest* submitted
  verdict is that verdict — the same latest-by-reviewer
  position S-164's gates will consult, so a superseded
  verdict does not match. `review:none` holds when no
  review has been submitted at all. `review:requested`
  holds when an active (not dismissed) review request
  from S-151/S-152 stands on the pull request.
- **`status:` says the pull request's whole position in
  one word:** `open` (open and ready, not a draft),
  `draft` (open and still a draft), or `closed`.
  `is:open` and `status:open` therefore differ honestly
  by exactly the drafts.
- **The inherited grammar keeps its laws.** Free text
  matches title and body case-insensitively, `author:`
  rides the account seam, and `label:` reads the label
  assignments on the shared numbered row directly
  (`issue_labels` keyed by the pull request's `issues`
  row): `IssueStore.get_issue` is issue-kind only by
  design, so the label store's issue seam cannot name
  a pull request. Tokens
  compose by AND, contradictory qualifiers match
  nothing, and unknown qualifiers, empty values, bad
  vocabulary values, unterminated quotes, and over-long
  or non-text queries all fail closed as `query_invalid`
  naming the problem — never a silently dropped
  qualifier (the S-118 law).
- **Permission is the pull request read gate.**
  Searching reads through `PullRequestStore`'s list
  seam: a stranger to a private repository gets that
  seam's uniform `repo_not_found`, and a search can
  never enumerate what its viewer cannot read.
- **No audit event of its own, and no migration.** A
  search mutates nothing; it is a read over tables that
  already exist.
- **The page teaches the language.** `render_search_page`
  renders the GET form with the query as typed (escaped
  through S-010), the qualifiers in plain words, and
  each result with its number, title, state said in
  words, and review position said in words — never a
  colour alone.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .accounts import AccountStore, User
from .escaping import escape_html_attr, escape_html_text
from .issue_search import SearchError, _tokenise
from .labels import LabelStore
from .pull_request_review_assignment import ReviewAssignmentStore
from .pull_request_reviews import PullRequestReviewStore
from .pull_requests import PullRequest, PullRequestStore
from .repositories import RepositoryStore

__all__ = [
    "ParsedPRQuery", "PullRequestSearch",
    "QUALIFIER_HELP", "parse_pr_query", "render_pr_search_page",
]

QUALIFIER_NAMES = frozenset({"is", "label", "author", "review", "status"})
IS_VALUES = frozenset({"pr", "open", "closed", "draft"})
REVIEW_VALUES = frozenset(
    {"approved", "commented", "changes_requested", "none", "requested"})
STATUS_VALUES = frozenset({"open", "draft", "closed"})
QUERY_MAX = 500

QUALIFIER_HELP: tuple[tuple[str, str], ...] = (
    ("is:pr", "only pull requests (this whole search)"),
    ("is:open / is:closed", "only pull requests in that state; "
                            "open includes drafts"),
    ("is:draft", "only open draft pull requests"),
    ("label:NAME", "only pull requests carrying that label; "
                   "quote names with spaces"),
    ("author:NAME", "only pull requests written by that account"),
    ("review:approved", "a reviewer's latest verdict is approval"),
    ("review:changes_requested", "a reviewer's latest verdict "
                                 "asks for changes"),
    ("review:commented", "a reviewer's latest verdict is a comment"),
    ("review:none", "no review has been submitted yet"),
    ("review:requested", "a review request is still active"),
    ("status:open", "open and ready — not a draft"),
    ("status:draft", "open and still a draft"),
    ("status:closed", "closed"),
)




@dataclass(frozen=True)
class ParsedPRQuery:
    text_terms: tuple[str, ...] = ()
    states: tuple[str, ...] = ()
    draft_only: bool = False
    labels: tuple[str, ...] = ()
    authors: tuple[str, ...] = ()
    reviews: tuple[str, ...] = ()
    statuses: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.text_terms or self.states or self.draft_only
                    or self.labels or self.authors or self.reviews
                    or self.statuses)


def parse_pr_query(query: object) -> ParsedPRQuery:
    """Parse *query* under the S-161 grammar. A non-string,
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
    draft_only = False
    labels: list[str] = []
    authors: list[str] = []
    reviews: list[str] = []
    statuses: list[str] = []
    for token in _tokenise(query):
        head, sep, value = token.partition(":")
        if sep and head.lower() in QUALIFIER_NAMES:
            name = head.lower()
            if not value.strip():
                raise SearchError(
                    "query_invalid",
                    f"The {name}: qualifier needs a value.")
            value = value.strip()
            low = value.lower()
            if name == "is":
                if low not in IS_VALUES:
                    raise SearchError(
                        "query_invalid",
                        "is: takes pr, open, closed, or draft.")
                if low in ("open", "closed") and low not in states:
                    states.append(low)
                elif low == "draft":
                    draft_only = True
            elif name == "review":
                normalised = low.replace("-", "_")
                if normalised not in REVIEW_VALUES:
                    raise SearchError(
                        "query_invalid",
                        "review: takes approved, commented, "
                        "changes_requested, none, or requested.")
                if normalised not in reviews:
                    reviews.append(normalised)
            elif name == "status":
                if low not in STATUS_VALUES:
                    raise SearchError(
                        "query_invalid",
                        "status: takes open, draft, or closed.")
                if low not in statuses:
                    statuses.append(low)
            elif name == "label":
                if low not in [v.lower() for v in labels]:
                    labels.append(value)
            else:  # author
                if low not in [v.lower() for v in authors]:
                    authors.append(value)
        elif sep and head and all(c.isalnum() or c in "_-" for c in head):
            raise SearchError(
                "query_invalid",
                f"There is no {head}: qualifier in pull request "
                "search; the qualifiers are is:, label:, author:, "
                "review:, and status:.")
        else:
            text_terms.append(token)
    return ParsedPRQuery(
        text_terms=tuple(text_terms), states=tuple(states),
        draft_only=draft_only, labels=tuple(labels),
        authors=tuple(authors), reviews=tuple(reviews),
        statuses=tuple(statuses))


def _status_holds(status: str, pr: PullRequest) -> bool:
    if status == "closed":
        return pr.state == "closed"
    if status == "draft":
        return pr.state == "open" and pr.is_draft
    return pr.state == "open" and not pr.is_draft  # open


class PullRequestSearch:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        pull_requests: PullRequestStore,
        labels: LabelStore,
        reviews: PullRequestReviewStore,
        assignments: ReviewAssignmentStore | None = None,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._prs = pull_requests
        self._labels = labels
        self._reviews = reviews
        self._assignments = assignments

    def search(self, viewer: User | None, owner: object, repo: object,
               query: object) -> list[PullRequest]:
        """The pull requests in this repository matching
        *query*, in number order. Permission rides the
        list seam of S-141's store."""
        parsed = parse_pr_query(query)
        if len(parsed.states) > 1:
            return []  # open AND closed at once matches nothing
        selected = self._prs.list_pull_requests(viewer, owner, repo)
        results: list[PullRequest] = []
        for pr in selected:
            if parsed.states and pr.state != parsed.states[0]:
                continue
            if parsed.draft_only and not (
                    pr.state == "open" and pr.is_draft):
                continue
            if any(not _status_holds(s, pr) for s in parsed.statuses):
                continue
            if parsed.text_terms:
                haystack = f"{pr.title}\n{pr.body}".lower()
                if any(t.lower() not in haystack
                       for t in parsed.text_terms):
                    continue
            if parsed.labels:
                # Label assignments live on the shared
                # numbered row: issue_labels.issue_id is
                # the pull request row in issues (pr.row_id).
                # IssueStore.get_issue is issue-kind only
                # by design, so the LabelStore issue seam
                # cannot name a pull request; read the
                # assignments from the row directly. The
                # list seam above already enforced read
                # permission for this repository.
                names = {r["name_lower"] for r in self._conn.execute(
                    "SELECT l.name_lower FROM labels l"
                    " JOIN issue_labels il ON il.label_id = l.id"
                    " WHERE il.issue_id = ?", (pr.row_id,))}
                if any(v.lower() not in names for v in parsed.labels):
                    continue
            if parsed.authors:
                writer = self._accounts.get_by_id(pr.author_id)
                if writer is None or writer.username_lower not in [
                        v.lower() for v in parsed.authors]:
                    continue
            if parsed.reviews:
                summary = self._reviews.review_summary(
                    viewer, owner, repo, pr.number)
                latest = set(summary.latest_by_reviewer.values())
                holds = True
                for wanted in parsed.reviews:
                    if wanted == "none":
                        if summary.total != 0:
                            holds = False
                    elif wanted == "requested":
                        if self._assignments is None or not any(
                                r.is_requested for r in
                                self._assignments.requests_for(
                                    viewer, owner, repo, pr.number)):
                            holds = False
                    elif wanted not in latest:
                        holds = False
                    if not holds:
                        break
                if not holds:
                    continue
            results.append(pr)
        return results


def render_pr_search_page(owner: object, repo: object, query: object,
                          results: list[PullRequest],
                          review_words: dict | None = None) -> str:
    """The pull request search page: the form as typed,
    the qualifier help in plain words, and the results
    with state (and, when *review_words* maps number to
    words, the review position) said in words. All user
    text through S-010."""
    query_text = query if isinstance(query, str) else ""
    parts = [
        "<h1>Pull requests</h1>",
        '<form method="get" action="pulls" role="search">',
        '<label for="q">Search pull requests</label>',
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
            '<p class="empty">No pull requests match. Try fewer '
            "qualifiers, or clear the search to see every "
            "pull request.</p>")
    else:
        parts.append('<ul class="pull-request-results">')
        for pr in results:
            line = (
                f'<li><a href="pulls/{pr.number}">'
                f"#{pr.number} {escape_html_text(pr.title)}</a>"
                f" — {escape_html_text(pr.state_words)}")
            if review_words and pr.number in review_words:
                line += f" — {escape_html_text(review_words[pr.number])}"
            parts.append(line + "</li>")
        parts.append("</ul>")
    return "\n".join(parts)
