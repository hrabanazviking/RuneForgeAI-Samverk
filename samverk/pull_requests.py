"""Pull request creation, same repository (S-141).

Opening Part VII: a pull request born the ordinary way —
a writer picks a base branch and a head branch in the
same repository, sees what the change actually is, and
only then opens it.

- **Pickers are the repository's real branches.** The
  base/head pickers list the branches that exist in the
  bare store today (S-052's ref listing), never a typed
  guess; the creation page renders both pickers as
  labelled selects with the repository's default branch
  preselected as the base.
- **The preview is S-105's compare, unchanged.** Before
  opening, `preview_creation` runs the compare view over
  the chosen pair — ahead/behind counts, the commit
  list, and the diff totals are the same numbers the
  compare page shows, so what you preview is what you
  open. The preview also says, in words, whether opening
  is possible: a pair with no commits ahead, or a pair
  that already has an open pull request, is named as a
  blocker on the preview instead of being discovered by
  pressing the button.
- **Creation validates whole, before any number is
  claimed.** Same branch (`same_branch`), a missing
  base or head (`base_not_found` / `head_not_found`),
  no commits ahead (`no_commits`), and an open pull
  request for the same pair (`already_exists`, naming
  its number) are all refused before S-121's shared
  sequence moves, so a refused opening burns nothing.
- **The PR is an ordinary numbered item.** It claims
  the next shared number (its `issues` row carries
  `kind='pull_request'`, S-121), is born open and not
  draft (drafts are S-143's slice; the conversion-born
  PRs of S-137 start as drafts through their own seam),
  and its `pull_requests` row (migration 46) records
  the branch pair, both oids as compared at opening,
  and no source issue. The default title is the head
  commit's subject — the first commit the preview
  listed — when the author gives none.
- **Writers only.** A same-repository head branch is a
  write-side object, so opening is a writer act under
  S-054: a mere reader gets `permission_denied`, and a
  stranger to a private repository gets the uniform
  `repo_not_found`, exactly as issue creation answers.
- **Audited under the existing event.**
  `repo.pull_request.create` (named by S-137, taxonomy
  unchanged at 90 events) with the branch pair and
  `same_repo` said in the detail, so later slices read
  one creation story for every pull request.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .compare_view import CompareService, CompareView
from .escaping import escape_html_text
from .issue_conversion import PullRequest, _PR_SELECT, _row_to_pr
from .issues import IssueError, IssueStore, _validate_body, _validate_title
from .permissions import can_read, can_write
from .print_export import stylesheet_link_tag
from .refs import RefStore, branch_ref
from .repositories import RepositoryError, RepositoryStore, validate_branch_name

__all__ = [
    "PullRequest", "PullRequestError", "PullRequestStore",
    "CreationPreview", "render_creation_page", "render_pull_request",
]

from .issue_conversion import render_pull_request  # noqa: E402,F401


class PullRequestError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class CreationPreview:
    full_name: str
    branches: tuple          # of str, every branch in the repo
    base_branch: str
    head_branch: str
    compare: CompareView
    existing_open_number: int  # 0 when the pair has no open PR

    @property
    def blockers(self) -> tuple:
        """Why this pair cannot be opened, in words —
        empty when it can."""
        out = []
        if self.compare.ahead == 0:
            out.append(
                "There are no commits on the head branch that "
                "the base branch does not already have.")
        if self.existing_open_number:
            out.append(
                f"Pull request #{self.existing_open_number} is "
                "already open for this pair of branches.")
        return tuple(out)

    @property
    def can_open(self) -> bool:
        return not self.blockers

    @property
    def suggested_title(self) -> str:
        if self.compare.commits:
            return self.compare.commits[0].subject
        return self.head_branch


class PullRequestStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        issues: IssueStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._issues = issues
        self._audit = audit
        self._now = time_fn
        self._compare = CompareService(repositories)

    # -- internals ---------------------------------------------------
    def _require_readable(self, viewer, owner, repo):
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise PullRequestError("repo_not_found", "No such repository.")
        return current

    def _branch_names(self, current) -> tuple:
        path = self._repos.path_for(current.owner, current.name)
        return tuple(ref.short for ref in RefStore(path).list_branches())

    def _validate_pair(self, current, base_branch, head_branch):
        try:
            base = validate_branch_name(base_branch)
            head = validate_branch_name(head_branch)
        except RepositoryError:
            raise PullRequestError(
                "branch_invalid", "That branch name is not valid.") from None
        if base == head:
            raise PullRequestError(
                "same_branch",
                "The base and head branches are the same branch; "
                "a pull request needs two different branches.")
        path = self._repos.path_for(current.owner, current.name)
        refs = RefStore(path)
        if refs.resolve(branch_ref(base)) is None:
            raise PullRequestError(
                "base_not_found",
                f"The base branch {base!r} does not exist in "
                "this repository yet.")
        if refs.resolve(branch_ref(head)) is None:
            raise PullRequestError(
                "head_not_found",
                f"The head branch {head!r} does not exist in "
                "this repository yet.")
        return base, head

    def _existing_open_number(self, repo_id: int, base: str,
                              head: str) -> int:
        row = self._conn.execute(
            "SELECT i.number AS number FROM pull_requests p"
            " JOIN issues i ON i.id = p.issue_id"
            " WHERE p.repo_id = ? AND p.base_branch = ?"
            " AND p.head_branch = ? AND i.state = 'open'"
            " ORDER BY i.number LIMIT 1",
            (repo_id, base, head)).fetchone()
        return int(row["number"]) if row else 0

    # -- pickers + preview --------------------------------------------
    def branch_names(self, viewer: User | None, owner: object,
                     repo: object) -> tuple:
        """Every branch the pickers may offer, in the ref
        listing's order — read through S-054."""
        current = self._require_readable(viewer, owner, repo)
        return self._branch_names(current)

    def preview_creation(self, viewer: User | None, owner: object,
                         repo: object, base_branch: object,
                         head_branch: object) -> CreationPreview:
        """The compare preview for a candidate pair: the
        S-105 numbers plus whether opening is possible."""
        current = self._require_readable(viewer, owner, repo)
        base, head = self._validate_pair(current, base_branch, head_branch)
        view = self._compare.compare(viewer, owner, repo, base, head)
        return CreationPreview(
            full_name=current.full_name,
            branches=self._branch_names(current),
            base_branch=base, head_branch=head, compare=view,
            existing_open_number=self._existing_open_number(
                current.id, base, head))

    # -- creation -------------------------------------------------------
    def create_pull_request(self, actor: User, owner: object,
                            repo: object, *, base_branch: object,
                            head_branch: object, title: object = None,
                            body: object = "",
                            source_ip: str | None = None) -> PullRequest:
        """Open a same-repository pull request. Every
        refusal is raised before any number is claimed."""
        current = self._require_readable(actor, owner, repo)
        if not can_write(actor, current):
            raise PullRequestError(
                "permission_denied",
                "Only a repository writer can open a pull request "
                "from a branch in this repository.")
        base, head = self._validate_pair(current, base_branch, head_branch)
        view = self._compare.compare(actor, owner, repo, base, head)
        if view.ahead == 0:
            raise PullRequestError(
                "no_commits",
                "There are no commits on the head branch that the "
                "base branch does not already have; there is "
                "nothing to propose.")
        existing = self._existing_open_number(current.id, base, head)
        if existing:
            raise PullRequestError(
                "already_exists",
                f"Pull request #{existing} is already open for "
                f"{head} into {base}.")
        if title is None:
            title = view.commits[0].subject if view.commits else head
        try:
            title = _validate_title(title)
            body = _validate_body(body)
        except IssueError as exc:
            raise PullRequestError(exc.reason, str(exc)) from None
        now = int(self._now())
        with self._conn:  # number and both rows land together
            number = self._issues._next_number_tx(current.id)
            cur = self._conn.execute(
                "INSERT INTO issues (repo_id, number, kind, author_id,"
                " title, body, state, created_at, updated_at)"
                " VALUES (?, ?, 'pull_request', ?, ?, ?, 'open', ?, ?)",
                (current.id, number, actor.id, title, body, now, now))
            row_id = int(cur.lastrowid)
            self._conn.execute(
                "INSERT INTO pull_requests (issue_id, repo_id,"
                " source_issue_id, base_branch, head_branch,"
                " base_oid, head_oid, is_draft, created_at, updated_at)"
                " VALUES (?, ?, NULL, ?, ?, ?, ?, 0, ?, ?)",
                (row_id, current.id, base, head,
                 view.base_oid, view.head_oid, now, now))
        created = self.get_pull_request(actor, owner, repo, number)
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.pull_request.create", target_kind="repo",
                target_id=f"{current.full_name}#{number}",
                outcome="success", source_ip=source_ip,
                detail={"number": number, "base": base, "head": head,
                        "draft": False, "same_repo": True})
        return created

    # -- reads -----------------------------------------------------------
    def get_pull_request(self, viewer: User | None, owner: object,
                         repo: object, number: object) -> PullRequest:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise PullRequestError(
                "pull_request_not_found", "No such pull request.")
        if not isinstance(number, int) or isinstance(number, bool) \
                or number <= 0:
            raise PullRequestError(
                "pull_request_not_found", "No such pull request.")
        row = self._conn.execute(
            _PR_SELECT + " WHERE p.repo_id = ? AND i.number = ?",
            (current.id, number)).fetchone()
        if row is None:
            raise PullRequestError(
                "pull_request_not_found", "No such pull request.")
        return _row_to_pr(row)

    def list_pull_requests(self, viewer: User | None, owner: object,
                           repo: object, *, state: str | None = None
                           ) -> list:
        current = self._require_readable(viewer, owner, repo)
        if state is not None and state not in ("open", "closed"):
            raise PullRequestError(
                "state_invalid",
                "Pull request state is 'open' or 'closed'.")
        sql = _PR_SELECT + " WHERE p.repo_id = ?"
        params: list = [current.id]
        if state is not None:
            sql += " AND i.state = ?"
            params.append(state)
        sql += " ORDER BY i.number"
        return [_row_to_pr(r) for r in
                self._conn.execute(sql, params).fetchall()]


def _options(branches: tuple, chosen: str) -> str:
    out = []
    for name in branches:
        selected = " selected" if name == chosen else ""
        out.append(
            f'<option value="{escape_html_text(name)}"{selected}>'
            f"{escape_html_text(name)}</option>")
    return "".join(out)


def render_creation_page(preview: CreationPreview) -> str:
    """The opening page: labelled base/head pickers, the
    compare preview in numbers and words, the blockers
    said plainly when the pair cannot be opened, and the
    title field carrying the suggested title. Every user
    value escapes through S-010."""
    view = preview.compare
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{escape_html_text(preview.full_name)} — new pull "
        "request — Samverk</title>",
        stylesheet_link_tag(),
        "</head>",
        "<body>",
        f"<h1>New pull request — "
        f"{escape_html_text(preview.full_name)}</h1>",
        '<form method="post" class="pull-request-create">',
        '<label>Base branch <select name="base_branch">'
        + _options(preview.branches, preview.base_branch)
        + "</select></label>",
        '<label>Head branch <select name="head_branch">'
        + _options(preview.branches, preview.head_branch)
        + "</select></label>",
        f'<p class="meta">{escape_html_text(preview.head_branch)} '
        f"into {escape_html_text(preview.base_branch)} · "
        f"{view.ahead} ahead · {view.behind} behind · "
        f"{view.files_changed} files changed · "
        f"+{view.diff.additions} −{view.diff.deletions}</p>",
    ]
    if view.commits:
        parts.append('<ol class="commits">')
        for commit in view.commits:
            parts.append(
                f'<li class="commit"><span class="subject">'
                f"{escape_html_text(commit.subject)}</span></li>")
        parts.append("</ol>")
    for blocker in preview.blockers:
        parts.append(
            f'<p class="blocker">{escape_html_text(blocker)}</p>')
    if preview.can_open:
        parts.append(
            '<label>Title <input name="title" value="'
            f"{escape_html_text(preview.suggested_title)}"
            '"></label>')
        parts.append(
            '<button type="submit">Open pull request</button>')
    parts.append("</form>")
    parts.append("</body></html>")
    return "\n".join(parts)
