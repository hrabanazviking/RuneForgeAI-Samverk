"""Assignees (S-126).

An issue may carry several assignees — the people who
have taken the work — under three laws:

- **Multiple, bounded, and recorded.** Up to
  `MAX_ASSIGNEES` (10) accounts per issue; every assign
  and unassign is audited (`repo.issue.assign` /
  `repo.issue.unassign`, carrying the assignee's
  username), so the assignment history is an event
  record, not a silent field. Assigning someone already
  assigned, or unassigning someone who is not, is a
  quiet no-op that reports the unchanged set — retries
  are safe.
- **An assignee must be able to see the work.** The
  assignee must be a real account that can read the
  repository under S-054 (on a private repository that
  means the owner, a site admin, or a collaborator when
  Part IX's grants land; on a public one, any account).
  Assigning a stranger to a private issue would leak
  the issue and strand the work, so it is refused
  `assignee_cannot_read`.
- **Who may assign.** A repository writer may assign
  anyone eligible; any reader may assign *themselves*
  (taking work is not a management act) and the issue's
  author may unassign themselves. Unassigning someone
  else is a writer act. Reading assignments follows
  S-054, with the uniform private answer.

`issues_assigned_to` is the "assigned to me" seam:
the caller's own list, per repository, optionally
filtered by state — the filter S-135's `assignee:`
qualifier will execute over the same rows.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .issues import ISSUE_STATES, Issue, IssueStore
from .permissions import can_read, can_write
from .repositories import Repository, RepositoryStore

MAX_ASSIGNEES = 10


class AssigneeError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class Assignment:
    issue_id: int
    number: int
    user_id: int
    username: str        # display case
    assigned_by: int
    assigned_at: int


class AssigneeStore:
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

    # -- assignment -----------------------------------------------------
    def assign(self, actor: User, owner: object, repo: object,
               number: object, username: object,
               *, source_ip: str | None = None) -> list[Assignment]:
        issue, current, assignee = self._resolve(
            actor, owner, repo, number, username)
        if actor.id != assignee.id and not can_write(actor, current):
            raise AssigneeError(
                "permission_denied",
                "Only a repository writer can assign someone else; "
                "any reader can assign themselves.")
        if not can_read(assignee, current):
            raise AssigneeError(
                "assignee_cannot_read",
                "That account cannot see this repository, so it "
                "cannot be assigned its issues.")
        existing = self.assignees_for_issue(actor, owner, repo, number)
        if any(a.user_id == assignee.id for a in existing):
            return existing
        if len(existing) >= MAX_ASSIGNEES:
            raise AssigneeError(
                "assignee_limit",
                f"An issue carries at most {MAX_ASSIGNEES} assignees.")
        now = int(self._now())
        with self._conn:  # commits before the answer
            self._conn.execute(
                "INSERT INTO issue_assignees (issue_id, user_id,"
                " assigned_by, created_at) VALUES (?, ?, ?, ?)",
                (issue.id, assignee.id, actor.id, now))
        self._emit(actor, "repo.issue.assign", current,
                   {"number": issue.number,
                    "assignee": assignee.username}, source_ip)
        return self.assignees_for_issue(actor, owner, repo, number)

    def unassign(self, actor: User, owner: object, repo: object,
                 number: object, username: object,
                 *, source_ip: str | None = None) -> list[Assignment]:
        issue, current, assignee = self._resolve(
            actor, owner, repo, number, username)
        if actor.id != assignee.id and not can_write(actor, current):
            raise AssigneeError(
                "permission_denied",
                "Only a repository writer can unassign someone "
                "else; anyone can unassign themselves.")
        existing = self.assignees_for_issue(actor, owner, repo, number)
        if not any(a.user_id == assignee.id for a in existing):
            return existing
        with self._conn:
            self._conn.execute(
                "DELETE FROM issue_assignees WHERE issue_id = ?"
                " AND user_id = ?", (issue.id, assignee.id))
        self._emit(actor, "repo.issue.unassign", current,
                   {"number": issue.number,
                    "assignee": assignee.username}, source_ip)
        return self.assignees_for_issue(actor, owner, repo, number)

    # -- reads ------------------------------------------------------------
    def assignees_for_issue(self, viewer: User | None, owner: object,
                            repo: object, number: object
                            ) -> list[Assignment]:
        issue = self._issues.get_issue(viewer, owner, repo, number)
        # Assignment order is insertion order (rowid): two
        # assignments in the same second must not reorder by
        # account id — who was assigned first is the record.
        rows = self._conn.execute(
            "SELECT a.*, u.username AS username FROM issue_assignees a"
            " JOIN users u ON u.id = a.user_id WHERE a.issue_id = ?"
            " ORDER BY a.rowid", (issue.id,)).fetchall()
        return [Assignment(
            issue_id=r["issue_id"], number=issue.number,
            user_id=r["user_id"], username=r["username"],
            assigned_by=r["assigned_by"], assigned_at=r["created_at"])
            for r in rows]

    def is_assigned(self, viewer: User | None, owner: object,
                    repo: object, number: object, username: object
                    ) -> bool:
        return any(a.username.lower() == str(username).lower()
                   for a in self.assignees_for_issue(
                       viewer, owner, repo, number))

    def issues_assigned_to(self, viewer: User, owner: object,
                           repo: object, *,
                           state: str | None = None) -> list[Issue]:
        """The 'assigned to me' list: issues in this
        repository assigned to the viewer, newest number
        last, optionally filtered by state."""
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise AssigneeError(
                "repo_not_found", "No such repository.")
        if state is not None and state not in ISSUE_STATES:
            raise AssigneeError(
                "state_invalid", "Issue state is 'open' or 'closed'.")
        from .issues import _row_to_issue
        sql = ("SELECT i.* FROM issues i JOIN issue_assignees a"
               " ON a.issue_id = i.id WHERE i.repo_id = ?"
               " AND a.user_id = ? AND i.kind = 'issue'")
        params: list = [current.id, viewer.id]
        if state is not None:
            sql += " AND i.state = ?"
            params.append(state)
        sql += " ORDER BY i.number"
        return [_row_to_issue(r) for r in
                self._conn.execute(sql, params).fetchall()]

    # -- internals ----------------------------------------------------------
    def _resolve(self, actor: User, owner: object, repo: object,
                 number: object, username: object):
        # get_issue enforces read access + the uniform private
        # answer for the actor before any name is resolved.
        issue = self._issues.get_issue(actor, owner, repo, number)
        current = self._repos.get_repository(owner, repo)
        assert current is not None
        assignee = (self._accounts.get_by_username(username)
                    if isinstance(username, str) else None)
        if assignee is None:
            raise AssigneeError("no_such_user", "No such account.")
        return issue, current, assignee

    def _emit(self, actor: User, action: str, current: Repository,
              detail: dict, source_ip: str | None) -> None:
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id, action=action,
                target_kind="repo", target_id=current.full_name,
                outcome="success", source_ip=source_ip, detail=detail)
