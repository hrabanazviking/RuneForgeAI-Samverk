"""Milestones (S-125).

A milestone is a named target in one repository — a title
(mandatory plain text), an optional description, an
optional due date, and an open/closed state — that issues
are grouped under, under three laws:

- **Progress is counted, never dressed up.** Progress is
  derived live from the issues table: open count, closed
  count, total, and the closed share as a whole-number
  percent. An empty milestone reports `0 of 0` and says
  so in words; there is no bar whose colour carries the
  meaning — `render_progress` prints the counts and the
  percent as text.
- **Due dates are real dates.** A due date must be a
  calendar `YYYY-MM-DD` date that exists (30 February is
  refused, a datetime string is refused). A past due
  date is not an error: an open milestone past its date
  is *overdue*, and that word is part of its progress
  answer, computed against the store's clock.
- **Permissions ride the repository's (S-054).**
  Managing milestones and setting an issue's milestone
  are writer acts (or the issue author's own act for
  assignment); reading follows read access, and a
  stranger to a private repository gets the uniform
  `repo_not_found`. Deleting a milestone unassigns its
  issues in the same transaction — issues are never
  deleted with their milestone.

The assignment seam is `set_issue_milestone` (a milestone
title, or None to clear), read back through
`milestone_for_issue` and `list_issues_in_milestone`;
S-135's `milestone:` search qualifier will read the
same columns.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .issues import IssueStore
from .permissions import can_read, can_write
from .repositories import Repository, RepositoryStore

TITLE_MAX = 100
DESCRIPTION_MAX = 1000
MILESTONE_STATES = frozenset({"open", "closed"})


class MilestoneError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class Milestone:
    id: int
    repo_id: int
    title: str
    title_lower: str
    description: str
    due_on: str | None      # 'YYYY-MM-DD', a real calendar date
    state: str               # 'open' | 'closed'
    created_at: int
    updated_at: int


@dataclass(frozen=True)
class MilestoneProgress:
    milestone_id: int
    open_count: int
    closed_count: int
    total: int
    percent_closed: int      # whole percent; 0 when total is 0
    is_overdue: bool

    @property
    def summary(self) -> str:
        """The progress as one plain sentence (text, never
        colour alone)."""
        if self.total == 0:
            return "No issues in this milestone yet."
        return (f"{self.closed_count} of {self.total} issues "
                f"closed ({self.percent_closed}%).")


def _row_to_milestone(row: sqlite3.Row) -> Milestone:
    return Milestone(
        id=row["id"], repo_id=row["repo_id"], title=row["title"],
        title_lower=row["title_lower"], description=row["description"],
        due_on=row["due_on"], state=row["state"],
        created_at=row["created_at"], updated_at=row["updated_at"])


def validate_due_on(due_on: object) -> str | None:
    if due_on is None or due_on == "":
        return None
    if not isinstance(due_on, str):
        raise MilestoneError(
            "due_date_invalid", "A due date is YYYY-MM-DD.")
    text = due_on.strip()
    parts = text.split("-")
    if len(parts) != 3 or len(parts[0]) != 4 or len(parts[1]) != 2 \
            or len(parts[2]) != 2 or not all(p.isdigit() for p in parts):
        raise MilestoneError(
            "due_date_invalid", "A due date is YYYY-MM-DD.")
    try:
        date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        raise MilestoneError(
            "due_date_invalid",
            f"{text} is not a date that exists.") from None
    return text


def _validate_title(title: object) -> str:
    if not isinstance(title, str) or not title.strip():
        raise MilestoneError(
            "milestone_title_required", "A milestone needs a title.")
    text = title.strip()
    if len(text) > TITLE_MAX or any(
            ord(c) < 0x20 or ord(c) == 0x7F for c in text):
        raise MilestoneError(
            "milestone_title_invalid",
            f"Milestone titles are at most {TITLE_MAX} characters "
            "of plain text.")
    return text


def _validate_description(description: object) -> str:
    if description is None:
        return ""
    if not isinstance(description, str):
        raise MilestoneError(
            "description_invalid", "A description must be text.")
    if len(description) > DESCRIPTION_MAX or any(
            (ord(c) < 0x20 and c not in "\n\t") or ord(c) == 0x7F
            for c in description):
        raise MilestoneError(
            "description_invalid",
            f"Descriptions are at most {DESCRIPTION_MAX} characters.")
    return description


def render_progress(milestone: Milestone,
                    progress: MilestoneProgress) -> str:
    """Milestone + progress as HTML text: title, due date in
    words, counts and percent as text, Overdue named."""
    due = (f"Due {milestone.due_on}" if milestone.due_on
           else "No due date")
    overdue = " — Overdue" if progress.is_overdue else ""
    return (
        '<section class="milestone"><h3>'
        + escape_html_text(milestone.title) + "</h3><p>"
        + escape_html_text(due) + escape_html_text(overdue)
        + "</p><p>" + escape_html_text(progress.summary)
        + "</p></section>")


class MilestoneStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        issues: IssueStore | None = None,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._issues = issues
        self._audit = audit
        self._now = time_fn

    # -- guards -----------------------------------------------------
    def _repo_for_read(self, viewer: User | None, owner: object,
                       repo: object) -> Repository:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise MilestoneError(
                "repo_not_found", "No such repository.")
        return current

    def _repo_for_write(self, actor: User, owner: object,
                        repo: object) -> Repository:
        current = self._repo_for_read(actor, owner, repo)
        if not can_write(actor, current):
            raise MilestoneError(
                "permission_denied",
                "Only a repository writer can manage milestones.")
        return current

    # -- CRUD ---------------------------------------------------------
    def create_milestone(self, actor: User, owner: object,
                         repo: object, title: object,
                         description: object = "",
                         due_on: object = None,
                         *, source_ip: str | None = None) -> Milestone:
        current = self._repo_for_write(actor, owner, repo)
        text = _validate_title(title)
        desc = _validate_description(description)
        due = validate_due_on(due_on)
        now = int(self._now())
        with self._conn:
            try:
                cur = self._conn.execute(
                    "INSERT INTO milestones (repo_id, title,"
                    " title_lower, description, due_on, state,"
                    " created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, 'open', ?, ?)",
                    (current.id, text, text.lower(), desc, due, now, now))
            except sqlite3.IntegrityError:
                raise MilestoneError(
                    "milestone_taken",
                    f"A milestone titled {text!r} already exists "
                    "in this repository.") from None
        milestone = self._by_id(int(cur.lastrowid))
        assert milestone is not None
        self._emit(actor, "repo.milestone.create", current,
                   {"milestone": milestone.title}, source_ip)
        return milestone

    def get_milestone(self, viewer: User | None, owner: object,
                      repo: object, title: object) -> Milestone:
        current = self._repo_for_read(viewer, owner, repo)
        milestone = self._by_title(current.id, title)
        if milestone is None:
            raise MilestoneError(
                "milestone_not_found", "No such milestone.")
        return milestone

    def list_milestones(self, viewer: User | None, owner: object,
                        repo: object, *, state: str | None = None
                        ) -> list[Milestone]:
        current = self._repo_for_read(viewer, owner, repo)
        if state is not None and state not in MILESTONE_STATES:
            raise MilestoneError(
                "state_invalid",
                "Milestone state is 'open' or 'closed'.")
        sql = "SELECT * FROM milestones WHERE repo_id = ?"
        params: list = [current.id]
        if state is not None:
            sql += " AND state = ?"
            params.append(state)
        sql += " ORDER BY (due_on IS NULL), due_on, title_lower"
        return [_row_to_milestone(r) for r in
                self._conn.execute(sql, params).fetchall()]

    def update_milestone(self, actor: User, owner: object,
                         repo: object, title: object, *,
                         new_title: object = None,
                         description: object = None,
                         due_on: object = ...,  # ... = leave; None = clear
                         state: object = None,
                         source_ip: str | None = None) -> Milestone:
        current = self._repo_for_write(actor, owner, repo)
        milestone = self._by_title(current.id, title)
        if milestone is None:
            raise MilestoneError(
                "milestone_not_found", "No such milestone.")
        text = (milestone.title if new_title is None
                else _validate_title(new_title))
        desc = (milestone.description if description is None
                else _validate_description(description))
        due = (milestone.due_on if due_on is ...
               else validate_due_on(due_on))
        new_state = milestone.state if state is None else state
        if new_state not in MILESTONE_STATES:
            raise MilestoneError(
                "state_invalid",
                "Milestone state is 'open' or 'closed'.")
        now = int(self._now())
        with self._conn:
            try:
                self._conn.execute(
                    "UPDATE milestones SET title = ?, title_lower = ?,"
                    " description = ?, due_on = ?, state = ?,"
                    " updated_at = ? WHERE id = ?",
                    (text, text.lower(), desc, due, new_state, now,
                     milestone.id))
            except sqlite3.IntegrityError:
                raise MilestoneError(
                    "milestone_taken",
                    f"A milestone titled {text!r} already exists "
                    "in this repository.") from None
        updated = self._by_id(milestone.id)
        assert updated is not None
        self._emit(actor, "repo.milestone.update", current,
                   {"milestone": updated.title}, source_ip)
        return updated

    def close_milestone(self, actor: User, owner: object,
                        repo: object, title: object,
                        *, source_ip: str | None = None) -> Milestone:
        return self.update_milestone(
            actor, owner, repo, title, state="closed",
            source_ip=source_ip)

    def reopen_milestone(self, actor: User, owner: object,
                         repo: object, title: object,
                         *, source_ip: str | None = None) -> Milestone:
        return self.update_milestone(
            actor, owner, repo, title, state="open",
            source_ip=source_ip)

    def delete_milestone(self, actor: User, owner: object,
                         repo: object, title: object,
                         *, source_ip: str | None = None) -> Milestone:
        current = self._repo_for_write(actor, owner, repo)
        milestone = self._by_title(current.id, title)
        if milestone is None:
            raise MilestoneError(
                "milestone_not_found", "No such milestone.")
        with self._conn:  # unassign + delete land together
            self._conn.execute(
                "UPDATE issues SET milestone_id = NULL"
                " WHERE milestone_id = ?", (milestone.id,))
            self._conn.execute(
                "DELETE FROM milestones WHERE id = ?", (milestone.id,))
        self._emit(actor, "repo.milestone.delete", current,
                   {"milestone": milestone.title}, source_ip)
        return milestone

    # -- progress -----------------------------------------------------
    def progress_for(self, viewer: User | None, owner: object,
                     repo: object, title: object) -> MilestoneProgress:
        current = self._repo_for_read(viewer, owner, repo)
        milestone = self._by_title(current.id, title)
        if milestone is None:
            raise MilestoneError(
                "milestone_not_found", "No such milestone.")
        return self._progress(milestone)

    def _progress(self, milestone: Milestone) -> MilestoneProgress:
        row = self._conn.execute(
            "SELECT COUNT(*) AS total,"
            " COALESCE(SUM(state = 'closed'), 0) AS closed"
            " FROM issues WHERE milestone_id = ? AND kind = 'issue'",
            (milestone.id,)).fetchone()
        total = int(row["total"])
        closed = int(row["closed"])
        percent = (closed * 100 // total) if total else 0
        today = time.strftime("%Y-%m-%d", time.gmtime(self._now()))
        overdue = bool(milestone.state == "open" and milestone.due_on
                       and milestone.due_on < today)
        return MilestoneProgress(
            milestone_id=milestone.id, open_count=total - closed,
            closed_count=closed, total=total, percent_closed=percent,
            is_overdue=overdue)

    # -- assignment to issues -----------------------------------------
    def set_issue_milestone(self, actor: User, owner: object,
                            repo: object, number: object,
                            milestone_title: object,
                            *, source_ip: str | None = None):
        if self._issues is None:
            raise MilestoneError(
                "issues_unavailable", "No issue store is wired.")
        issue = self._issues.get_issue(actor, owner, repo, number)
        current = self._repos.get_repository(owner, repo)
        assert current is not None
        if actor.id != issue.author_id and not can_write(actor, current):
            raise MilestoneError(
                "permission_denied",
                "Only a repository writer or the issue's author "
                "can set its milestone.")
        milestone = None
        if milestone_title is not None:
            milestone = self._by_title(current.id, milestone_title)
            if milestone is None:
                raise MilestoneError(
                    "milestone_not_found", "No such milestone.")
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "UPDATE issues SET milestone_id = ?, updated_at = ?"
                " WHERE id = ?",
                (milestone.id if milestone else None, now, issue.id))
        self._emit(actor, "repo.issue.milestone", current,
                   {"number": issue.number,
                    "milestone": milestone.title if milestone else None},
                   source_ip)
        return milestone

    def milestone_for_issue(self, viewer: User | None, owner: object,
                            repo: object, number: object
                            ) -> Milestone | None:
        if self._issues is None:
            raise MilestoneError(
                "issues_unavailable", "No issue store is wired.")
        issue = self._issues.get_issue(viewer, owner, repo, number)
        row = self._conn.execute(
            "SELECT milestone_id FROM issues WHERE id = ?",
            (issue.id,)).fetchone()
        if row is None or row["milestone_id"] is None:
            return None
        return self._by_id(int(row["milestone_id"]))

    def list_issue_numbers(self, viewer: User | None, owner: object,
                           repo: object, title: object) -> list[int]:
        current = self._repo_for_read(viewer, owner, repo)
        milestone = self._by_title(current.id, title)
        if milestone is None:
            raise MilestoneError(
                "milestone_not_found", "No such milestone.")
        rows = self._conn.execute(
            "SELECT number FROM issues WHERE milestone_id = ?"
            " AND kind = 'issue' ORDER BY number",
            (milestone.id,)).fetchall()
        return [int(r["number"]) for r in rows]

    # -- internals ------------------------------------------------------
    def _by_id(self, milestone_id: int) -> Milestone | None:
        row = self._conn.execute(
            "SELECT * FROM milestones WHERE id = ?",
            (milestone_id,)).fetchone()
        return _row_to_milestone(row) if row else None

    def _by_title(self, repo_id: int, title: object) -> Milestone | None:
        if not isinstance(title, str) or not title.strip():
            return None
        row = self._conn.execute(
            "SELECT * FROM milestones WHERE repo_id = ?"
            " AND title_lower = ?",
            (repo_id, title.strip().lower())).fetchone()
        return _row_to_milestone(row) if row else None

    def _emit(self, actor: User, action: str, current: Repository,
              detail: dict, source_ip: str | None) -> None:
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id, action=action,
                target_kind="repo", target_id=current.full_name,
                outcome="success", source_ip=source_ip, detail=detail)
