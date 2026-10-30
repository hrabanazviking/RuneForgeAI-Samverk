"""Issue -> pull request conversion (S-137).

The branch-from-issue shortcut: from an open issue, one
act creates a linked branch and a draft pull request
whose work is that issue.

- **A linked branch, in git.** The head branch is a real
  branch in the repository's bare store, created through
  S-053's ref seam at the base branch's current commit
  (compare-and-swap against the zero oid, so a name that
  already exists is refused `branch_taken`, never
  overwritten). The default name is derived from the
  issue — ``<number>-<title slug>`` — so the branch says
  which issue it serves; an explicit name is honoured
  when it passes the branch-name law.
- **A draft PR, on the shared number.** The pull request
  claims the repository's next shared number through
  S-121's sequence (its row in `issues` carries
  `kind='pull_request'`, so the issue's `#n` and the
  PR's `#m` can never collide), is born **draft** (Part
  VII's S-143 owns the ready-for-review transition), and
  carries the issue's title with a body that links back
  to the issue. The `pull_requests` row records the
  branch pair, both oids at birth, and the source issue
  — the link both ways: `pull_request_for_issue` reads
  it forward, the PR row names its source.
- **One conversion per issue.** A second conversion of
  the same issue is refused `already_converted`, naming
  the existing PR's number — the shortcut mints one
  branch and one PR, not a pile of duplicates.
- **Writers only, open issues only.** Creating a branch
  is a write act: the actor must be able to write the
  repository (`permission_denied` for a mere reader,
  even the issue's author); a stranger to a private
  repository gets S-122's uniform `issue_not_found`.
  A closed issue is refused `issue_closed` — reopen it
  first. A base branch that does not exist (including
  an empty repository) is refused `base_not_found`, and
  every refusal happens *before* any number is claimed
  or any branch is created, so a refused conversion
  burns nothing.
- **All-or-nothing across git and the database.** The
  branch is created first; if the database claim then
  fails, the just-created branch is deleted again, so
  no half-conversion is ever left behind.
- **Audited on both sides.** `repo.issue.convert` on
  the issue (branch + PR number) and
  `repo.pull_request.create` on the PR (branch pair,
  draft, source issue) — taxonomy append-only +2, 87
  events — so S-131's timeline can say, in words, that
  this issue gained a branch and a draft PR.
"""

from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .issues import IssueError, IssueStore
from .permissions import can_read, can_write
from .refs import RefError, RefStore, branch_ref
from .repositories import RepositoryStore, validate_branch_name, RepositoryError


class ConversionError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class PullRequest:
    id: int              # pull_requests row id
    row_id: int          # the shared numbered row (issues.id)
    repo_id: int
    number: int
    author_id: int
    title: str
    body: str
    state: str           # 'open' | 'closed'
    is_draft: bool
    base_branch: str
    head_branch: str
    base_oid: str
    head_oid: str
    source_issue_number: int   # 0 when not born from an issue
    created_at: int
    updated_at: int

    @property
    def ref(self) -> str:
        return f"#{self.number}"

    @property
    def state_words(self) -> str:
        """The state in words — 'draft pull request' /
        'open pull request' / 'closed pull request' —
        never a colour alone."""
        if self.state == "closed":
            return "closed pull request"
        return "draft pull request" if self.is_draft \
            else "open pull request"


def _slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:40].strip("-") or "work"


def default_branch_name(number: int, title: str) -> str:
    return f"{number}-{_slug(title)}"


def _row_to_pr(row: sqlite3.Row) -> PullRequest:
    return PullRequest(
        id=row["pr_id"], row_id=row["id"], repo_id=row["repo_id"],
        number=row["number"], author_id=row["author_id"],
        title=row["title"], body=row["body"], state=row["state"],
        is_draft=bool(row["is_draft"]), base_branch=row["base_branch"],
        head_branch=row["head_branch"], base_oid=row["base_oid"],
        head_oid=row["head_oid"],
        source_issue_number=int(row["source_number"] or 0),
        created_at=row["created_at"], updated_at=row["updated_at"])


_PR_SELECT = (
    "SELECT i.*, p.id AS pr_id, p.source_issue_id,"
    " p.base_branch, p.head_branch, p.base_oid, p.head_oid,"
    " p.is_draft,"
    " (SELECT number FROM issues s WHERE s.id = p.source_issue_id)"
    " AS source_number"
    " FROM pull_requests p JOIN issues i ON i.id = p.issue_id")


class IssueConversionStore:
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

    # -- the shortcut ----------------------------------------------
    def convert_issue(self, actor: User, owner: object, repo: object,
                      number: object, *, branch_name: object = None,
                      base_branch: object = None,
                      source_ip: str | None = None) -> PullRequest:
        """Create the linked branch + draft PR for an issue.
        Every refusal is raised before anything is created."""
        issue = self._issues.get_issue(actor, owner, repo, number)
        current = self._repos.get_repository(owner, repo)
        assert current is not None
        if not can_write(actor, current):
            raise ConversionError(
                "permission_denied",
                "Only a repository writer can create a branch "
                "and a pull request from an issue.")
        if issue.state != "open":
            raise ConversionError(
                "issue_closed",
                "A closed issue cannot be converted; reopen it first.")
        existing = self._conn.execute(
            "SELECT issue_id FROM pull_requests WHERE source_issue_id = ?",
            (issue.id,)).fetchone()
        if existing is not None:
            pr_number = self._conn.execute(
                "SELECT number FROM issues WHERE id = ?",
                (existing["issue_id"],)).fetchone()
            raise ConversionError(
                "already_converted",
                f"This issue already has a draft pull request: "
                f"#{int(pr_number['number']) if pr_number else '?'}.")

        base = current.default_branch if base_branch is None else base_branch
        try:
            base = validate_branch_name(base)
            head = validate_branch_name(
                default_branch_name(issue.number, issue.title)
                if branch_name is None else branch_name)
        except RepositoryError:
            raise ConversionError(
                "branch_invalid",
                f"That branch name is not valid: "
                f"{branch_name if branch_name is not None else base!r}") from None

        path: Path = self._repos.path_for(current.owner, current.name)
        refs = RefStore(path)
        base_oid = refs.resolve(branch_ref(base))
        if base_oid is None:
            raise ConversionError(
                "base_not_found",
                f"The base branch {base!r} does not exist in "
                "this repository yet.")
        if refs.resolve(branch_ref(head)) is not None:
            raise ConversionError(
                "branch_taken",
                f"A branch named {head!r} already exists.")
        try:
            refs.create_branch(head, base_oid)
        except RefError:
            raise ConversionError(
                "branch_taken",
                f"A branch named {head!r} already exists.") from None

        now = int(self._now())
        title = issue.title
        body = f"Draft pull request for #{issue.number}."
        try:
            with self._conn:  # number, PR row and link land together
                pr_number = self._issues._next_number_tx(current.id)
                cur = self._conn.execute(
                    "INSERT INTO issues (repo_id, number, kind, author_id,"
                    " title, body, state, created_at, updated_at)"
                    " VALUES (?, ?, 'pull_request', ?, ?, ?, 'open', ?, ?)",
                    (current.id, pr_number, actor.id, title, body, now, now))
                row_id = int(cur.lastrowid)
                self._conn.execute(
                    "INSERT INTO pull_requests (issue_id, repo_id,"
                    " source_issue_id, base_branch, head_branch,"
                    " base_oid, head_oid, is_draft, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                    (row_id, current.id, issue.id, base, head,
                     base_oid, base_oid, now, now))
        except Exception:
            # The database refused: the branch must not outlive
            # the failed claim (all-or-nothing, module docstring).
            try:
                refs.delete_branch(head, expected_old=base_oid)
            except RefError:
                pass
            raise
        created = self.get_pull_request(actor, owner, repo, pr_number)
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.issue.convert", target_kind="repo",
                target_id=f"{current.full_name}#{issue.number}",
                outcome="success", source_ip=source_ip,
                detail={"number": issue.number, "to_number": pr_number,
                        "branch": head})
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.pull_request.create", target_kind="repo",
                target_id=f"{current.full_name}#{pr_number}",
                outcome="success", source_ip=source_ip,
                detail={"number": pr_number, "base": base, "head": head,
                        "draft": True, "from_issue": issue.number})
        return created

    # -- reads -------------------------------------------------------
    def get_pull_request(self, viewer: User | None, owner: object,
                         repo: object, number: object) -> PullRequest:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise ConversionError(
                "pull_request_not_found", "No such pull request.")
        if not isinstance(number, int) or isinstance(number, bool) \
                or number <= 0:
            raise ConversionError(
                "pull_request_not_found", "No such pull request.")
        row = self._conn.execute(
            _PR_SELECT + " WHERE p.repo_id = ? AND i.number = ?",
            (current.id, number)).fetchone()
        if row is None:
            raise ConversionError(
                "pull_request_not_found", "No such pull request.")
        return _row_to_pr(row)

    def pull_request_for_issue(self, viewer: User | None, owner: object,
                               repo: object, number: object
                               ) -> PullRequest | None:
        """The PR this issue was converted into, or None —
        read through the issue itself, so a stranger to a
        private repository gets the uniform issue answer."""
        issue = self._issues.get_issue(viewer, owner, repo, number)
        row = self._conn.execute(
            _PR_SELECT + " WHERE p.source_issue_id = ?",
            (issue.id,)).fetchone()
        return _row_to_pr(row) if row else None


def render_pull_request(pr: PullRequest) -> str:
    """The PR as one plain-words line: number, title,
    state in words, and the branch pair — every value
    escaped through S-010, meaning never in colour."""
    return (
        f'<p class="pull-request">#{pr.number} '
        f"{escape_html_text(pr.title)} — "
        f"{escape_html_text(pr.state_words)}: "
        f"{escape_html_text(pr.head_branch)} into "
        f"{escape_html_text(pr.base_branch)}</p>")
