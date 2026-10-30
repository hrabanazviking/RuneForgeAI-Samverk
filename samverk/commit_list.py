"""Commit list (S-102).

Paginated history for any ref: author, message, time, and
a verification badge slot.

- **Pagination is honest.** The total commit count comes
  from `rev-list --count`; a page is fetched with
  `--skip`/`--max-count`, and the view reports the true
  total and page count. A page past the end answers with
  no rows and the true totals — never a silent repeat of
  the last page.
- **The verification badge is a slot, not a claim.**
  Signature verification is Part XV's work. Until it
  lands, every row carries `verification_badge=None` and
  the page renders the slot in words — "Not checked" —
  so no reader mistakes an unchecked commit for a
  verified one, and Part XV fills exactly this field.
- Messages render only through S-010's escaping seam;
  the subject is the first line, the body stays available
  on the row for detail views.
- Permission and ref law are S-097's shared helpers.
"""

from __future__ import annotations

from dataclasses import dataclass

from .accounts import User
from .escaping import escape_html_text
from .permissions import can_read
from .proc import run_git_in
from .repo_home import RepoHomeError, resolve_commit
from .repositories import RepositoryStore

DEFAULT_PER_PAGE = 30
MAX_PER_PAGE = 100

_SEP = "\x1f"
_REC = "\x1e"
_FORMAT = _SEP.join(["%H", "%P", "%an", "%ae", "%at", "%s", "%b"]) + _REC


class CommitListError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class CommitSummary:
    oid: str
    parents: tuple[str, ...]
    author_name: str
    author_email: str
    author_time: int
    subject: str
    body: str
    # Part XV fills this slot; None means "not checked",
    # never "verified".
    verification_badge: str | None = None


@dataclass(frozen=True)
class CommitList:
    full_name: str
    current_ref: str
    commit_oid: str
    total_commits: int
    page: int
    per_page: int
    total_pages: int
    commits: tuple[CommitSummary, ...]

    @property
    def has_previous(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages


def parse_log_output(output: str) -> list[CommitSummary]:
    rows: list[CommitSummary] = []
    for record in output.split(_REC):
        record = record.strip("\n")
        if not record:
            continue
        fields = record.split(_SEP)
        if len(fields) != 7:
            raise CommitListError("object_unreadable",
                                  "History output could not be read.")
        oid, parents, name, email, when, subject, body = fields
        rows.append(CommitSummary(
            oid=oid, parents=tuple(parents.split()) if parents else (),
            author_name=name, author_email=email,
            author_time=int(when or 0), subject=subject,
            body=body.strip("\n")))
    return rows


class CommitLister:
    def __init__(self, repositories: RepositoryStore):
        self._repos = repositories

    def list(self, viewer: User | None, owner: object, repo: object,
             ref: object = None, page: object = 1,
             per_page: object = DEFAULT_PER_PAGE) -> CommitList:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise CommitListError("repo_not_found", "No such repository.")
        try:
            page_no = max(1, int(page))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            page_no = 1
        try:
            page_size = int(per_page)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            page_size = DEFAULT_PER_PAGE
        page_size = min(MAX_PER_PAGE, max(1, page_size))
        repo_path = self._repos.path_for(current.owner, current.name)
        requested = current.default_branch if ref is None else ref
        try:
            ref_name, commit_oid = resolve_commit(repo_path, requested)
        except RepoHomeError as exc:
            raise CommitListError(exc.reason, str(exc)) from None
        count = run_git_in(repo_path, ["rev-list", "--count", commit_oid],
                           timeout=15.0)
        try:
            total = int(count.stdout.decode().strip())
        except ValueError:
            raise CommitListError("object_unreadable",
                                  "History could not be counted.") from None
        total_pages = (total + page_size - 1) // page_size if total else 0
        skip = (page_no - 1) * page_size
        result = run_git_in(
            repo_path,
            ["log", f"--skip={skip}", f"--max-count={page_size}",
             f"--format={_FORMAT}", commit_oid],
            timeout=30.0)
        if result.returncode != 0:
            raise CommitListError("object_unreadable",
                                  "History could not be read.")
        commits = tuple(parse_log_output(
            result.stdout.decode("utf-8", "replace")))
        return CommitList(
            full_name=current.full_name, current_ref=ref_name,
            commit_oid=commit_oid, total_commits=total, page=page_no,
            per_page=page_size, total_pages=total_pages, commits=commits)


def render_commit_list_page(listing: CommitList) -> str:
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{escape_html_text(listing.full_name)} — commits — "
        "Samverk</title></head>",
        "<body>",
        f"<h1>Commits — {escape_html_text(listing.full_name)}</h1>",
        f'<p class="meta">{listing.total_commits} commits · '
        f"ref {escape_html_text(listing.current_ref)}</p>",
    ]
    if not listing.commits:
        parts.append(
            '<p class="empty">No commits on this page. '
            "This repository's history starts at its first commit.</p>")
    else:
        parts.append('<ol class="commits">')
        for commit in listing.commits:
            badge = commit.verification_badge
            badge_html = (
                f'<span class="verification-badge">'
                f"{escape_html_text(badge)}</span>" if badge else
                '<span class="verification-badge" '
                'data-state="not-checked">Not checked</span>')
            parts.append(
                f'<li class="commit"><a class="oid" '
                f'href="/{escape_html_text(listing.full_name)}/commit/'
                f'{escape_html_text(commit.oid)}">'
                f"{escape_html_text(commit.oid[:12])}</a> "
                f'<span class="subject">'
                f"{escape_html_text(commit.subject)}</span> "
                f'<span class="author">'
                f"{escape_html_text(commit.author_name)}</span> "
                f"{badge_html}</li>")
        parts.append("</ol>")
    if listing.total_pages > 1:
        nav = ['<nav class="pagination">']
        if listing.has_previous:
            nav.append(f'<a href="?page={listing.page - 1}">Previous</a> ')
        nav.append(f"Page {listing.page} of {listing.total_pages}")
        if listing.has_next:
            nav.append(f' <a href="?page={listing.page + 1}">Next</a>')
        nav.append("</nav>")
        parts.append("".join(nav))
    parts.append("</body></html>")
    return "\n".join(parts)
