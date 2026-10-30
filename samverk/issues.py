"""Issues — model and numbering (S-121); create/read/update (S-122);
close and reopen with reason (S-130).

Part VI opens with the number. In every GitHub-class forge
the habit users rely on is that ``#n`` names exactly one
thing in a repository: an issue *or* a pull request, never
both, never neither once claimed. That habit is a data law,
and this module is where it lives:

- **One shared sequence per repository.** `repo_counters`
  holds each repository's last-issued number. Claiming a
  number is a single atomic upsert (`INSERT ... ON CONFLICT
  ... RETURNING`), so two claims racing on separate
  connections can never receive the same number, and the
  counter only ever moves forward — a number is never
  reused, even if the row that claimed it is later removed
  (a deleted ``#3`` leaves a gap, never a second ``#3``
  meaning something else; links in prose must stay true).
- **A claim is a row.** `issues` is the numbered-items
  table: every claimed number has exactly one row
  (`UNIQUE (repo_id, number)`) carrying its `kind` —
  ``issue`` today, ``pull_request`` when Part VII claims
  its numbers through this same seam. S-127's
  cross-references and S-109's ``issue_exists`` seam read
  through `resolve_number` / `exists`, never around it.
- **Issues (S-122).** An issue is a claimed row filled in:
  title (plain text, required), Markdown body, author, and
  state (`open` at birth). Reads follow S-054: anyone who can read
  the repository can read its issues; a stranger to a
  private repository receives the uniform `issue_not_found`
  — the same answer as a number that was never claimed, so
  a private repo's issues cannot be enumerated by probing.
  Creating an issue requires read access to the repository
  (the GitHub habit: any reader may report). Editing is
  the author's, or a repository writer/admin's. Edits are
  commit-before-answer, and an edit may carry the
  `expected_version` it was based on: a stale expectation
  is refused as `edit_conflict` and changes nothing, so
  two editors racing the same issue cannot silently
  overwrite each other.
- **Close and reopen (S-130).** Closing carries a reason
  in plain words — `completed` or `not_planned`, nothing
  else (`reason_invalid`) — stored on the issue as
  `state_reason` and said in words wherever the state is
  shown, never as a colour alone. Every real transition
  writes an `issue_events` row in the same transaction
  (the state-change stream S-131's timeline reads) and
  an audit row (`repo.issue.close` / `repo.issue.reopen`).
  Closing a closed issue or reopening an open one is a
  quiet no-op — retries are safe and the record is not
  rewritten. The actor is the issue's author or a
  repository writer, the same hands that may edit it.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .permissions import can_read, can_write
from .repositories import Repository, RepositoryStore

KINDS = frozenset({"issue", "pull_request"})
ISSUE_STATES = frozenset({"open", "closed"})
CLOSE_REASONS = frozenset({"completed", "not_planned"})
REASON_WORDS = {"completed": "completed",
                "not_planned": "not planned"}
TITLE_MAX = 256
BODY_MAX = 65536


class IssueError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class NumberedItem:
    repo_id: int
    number: int
    kind: str          # 'issue' | 'pull_request'
    row_id: int


@dataclass(frozen=True)
class Issue:
    id: int
    repo_id: int
    number: int
    author_id: int
    title: str
    body: str
    state: str         # 'open' | 'closed'
    version: int       # optimistic-edit version (S-122)
    created_at: int
    updated_at: int
    state_reason: str = ""   # S-130: '' | 'completed' | 'not_planned'
    locked: bool = False     # S-132: conversation locked
    lock_reason: str = ""    # S-132: '' | the lock vocabulary

    @property
    def ref(self) -> str:
        return f"#{self.number}"

    @property
    def state_words(self) -> str:
        """The state as words: 'open', 'closed as completed',
        'closed as not planned' — never a colour alone."""
        if self.state == "open":
            return "open"
        words = REASON_WORDS.get(self.state_reason)
        return f"closed as {words}" if words else "closed"


@dataclass(frozen=True)
class IssueStateEvent:
    id: int
    issue_id: int
    actor_id: int
    actor: str         # the actor's username, display case
    kind: str          # 'closed' | 'reopened'
    reason: str        # closing reason, '' for a reopen
    created_at: int


def describe_state_event(event: IssueStateEvent) -> str:
    """One state event in plain words, for timelines."""
    if event.kind == "reopened":
        return f"{event.actor} reopened this issue"
    words = REASON_WORDS.get(event.reason, "")
    suffix = f" as {words}" if words else ""
    return f"{event.actor} closed this issue{suffix}"


def _row_to_issue(row: sqlite3.Row) -> Issue:
    keys = row.keys()
    return Issue(
        id=row["id"], repo_id=row["repo_id"], number=row["number"],
        author_id=row["author_id"], title=row["title"], body=row["body"],
        state=row["state"], version=row["version"],
        created_at=row["created_at"], updated_at=row["updated_at"],
        state_reason=row["state_reason"],
        locked=bool(row["locked"]) if "locked" in keys else False,
        lock_reason=row["lock_reason"] if "lock_reason" in keys else "")


class IssueStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._audit = audit
        self._now = time_fn

    # -- S-121: the shared sequence -------------------------------
    def _next_number_tx(self, repo_id: int) -> int:
        """Claim the next number inside the caller's
        transaction. The upsert is one statement, so the
        increment itself is atomic across connections."""
        row = self._conn.execute(
            "INSERT INTO repo_counters (repo_id, last_number)"
            " VALUES (?, 1)"
            " ON CONFLICT (repo_id) DO UPDATE"
            " SET last_number = last_number + 1"
            " RETURNING last_number",
            (repo_id,)).fetchone()
        return int(row["last_number"])

    def _require_repo(self, owner: object, repo: object) -> Repository:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise IssueError("repo_not_found", "No such repository.")
        return current

    def claim_number(self, owner: object, repo: object,
                     kind: object, author_id: int) -> NumberedItem:
        """Claim the next shared number for a new numbered
        item of *kind* in this repository. Commits before
        answering: a returned number is durably claimed."""
        if kind not in KINDS:
            raise IssueError(
                "kind_invalid",
                "A numbered item is an issue or a pull request.")
        author = self._accounts.get_by_id(author_id)
        if author is None:
            raise IssueError("no_such_user", "No such account.")
        current = self._require_repo(owner, repo)
        now = int(self._now())
        with self._conn:  # counter and claim row land together
            number = self._next_number_tx(current.id)
            cur = self._conn.execute(
                "INSERT INTO issues (repo_id, number, kind, author_id,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (current.id, number, kind, author.id, now, now))
        return NumberedItem(repo_id=current.id, number=number,
                            kind=str(kind), row_id=int(cur.lastrowid))

    def resolve_number(self, owner: object, repo: object,
                       number: object) -> NumberedItem | None:
        """What a `#n` means in this repository, or None —
        the seam cross-references (S-127) and prose (S-109)
        read through."""
        current = self._repos.get_repository(owner, repo)
        if current is None or not isinstance(number, int) \
                or isinstance(number, bool) or number <= 0:
            return None
        row = self._conn.execute(
            "SELECT * FROM issues WHERE repo_id = ? AND number = ?",
            (current.id, number)).fetchone()
        if row is None:
            return None
        return NumberedItem(repo_id=current.id, number=row["number"],
                            kind=row["kind"], row_id=row["id"])

    def exists(self, owner: object, repo: object, number: object) -> bool:
        return self.resolve_number(owner, repo, number) is not None

    def last_number(self, owner: object, repo: object) -> int:
        current = self._require_repo(owner, repo)
        row = self._conn.execute(
            "SELECT last_number FROM repo_counters WHERE repo_id = ?",
            (current.id,)).fetchone()
        return int(row["last_number"]) if row else 0

    # -- S-122: create / read / update ----------------------------
    def create_issue(self, actor: User, owner: object, repo: object,
                     title: object, body: object = "",
                     *, source_ip: str | None = None,
                     via_template: bool = False) -> Issue:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(actor, current):
            raise IssueError("repo_not_found", "No such repository.")
        if not via_template:
            # S-129: the owner's blank-issue toggle, enforced
            # here at the one creation seam so no surface can
            # walk around it. An absent row is the birth
            # default: blank issues allowed.
            row = self._conn.execute(
                "SELECT allow_blank_issues FROM repo_issue_options"
                " WHERE repo_id = ?", (current.id,)).fetchone()
            if row is not None and not row["allow_blank_issues"]:
                raise IssueError(
                    "blank_issue_not_allowed",
                    "This repository's owners ask reporters to use "
                    "an issue template; blank issues are turned off.")
        title = _validate_title(title)
        body = _validate_body(body)
        now = int(self._now())
        with self._conn:  # number, row and title land together
            number = self._next_number_tx(current.id)
            cur = self._conn.execute(
                "INSERT INTO issues (repo_id, number, kind, author_id,"
                " title, body, state, created_at, updated_at)"
                " VALUES (?, ?, 'issue', ?, ?, ?, 'open', ?, ?)",
                (current.id, number, actor.id, title, body, now, now))
        issue = self._issue_by_row_id(int(cur.lastrowid))
        assert issue is not None
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.issue.create", target_kind="repo",
                target_id=f"{current.full_name}#{number}",
                outcome="success", source_ip=source_ip,
                detail={"number": number})
        return issue

    def get_issue(self, viewer: User | None, owner: object,
                  repo: object, number: object) -> Issue:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise IssueError("issue_not_found", "No such issue.")
        item = self.resolve_number(owner, repo, number)
        if item is None or item.kind != "issue":
            raise IssueError("issue_not_found", "No such issue.")
        issue = self._issue_by_row_id(item.row_id)
        assert issue is not None
        return issue

    def list_issues(self, viewer: User | None, owner: object,
                    repo: object, *, state: str | None = None
                    ) -> list[Issue]:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise IssueError("issue_not_found", "No such issue.")
        if state is not None and state not in ISSUE_STATES:
            raise IssueError(
                "state_invalid", "Issue state is 'open' or 'closed'.")
        sql = ("SELECT * FROM issues WHERE repo_id = ?"
               " AND kind = 'issue'")
        params: list = [current.id]
        if state is not None:
            sql += " AND state = ?"
            params.append(state)
        sql += " ORDER BY number"
        return [_row_to_issue(r) for r in
                self._conn.execute(sql, params).fetchall()]

    def update_issue(self, actor: User, owner: object, repo: object,
                     number: object, *, title: object = None,
                     body: object = None,
                     expected_version: int | None = None,
                     source_ip: str | None = None) -> Issue:
        issue = self.get_issue(actor, owner, repo, number)
        current = self._require_repo(owner, repo)
        if actor.id != issue.author_id and not can_write(actor, current):
            raise IssueError(
                "permission_denied",
                "Only the author or a repository writer can edit "
                "this issue.")
        new_title = issue.title if title is None else _validate_title(title)
        new_body = issue.body if body is None else _validate_body(body)
        now = int(self._now())
        with self._conn:  # commits before the answer
            if expected_version is not None:
                cur = self._conn.execute(
                    "UPDATE issues SET title = ?, body = ?,"
                    " version = version + 1, updated_at = ?"
                    " WHERE id = ? AND version = ?",
                    (new_title, new_body, now, issue.id, expected_version))
                if cur.rowcount == 0:
                    raise IssueError(
                        "edit_conflict",
                        "This issue changed since you loaded it; "
                        "reload and try again.")
            else:
                self._conn.execute(
                    "UPDATE issues SET title = ?, body = ?,"
                    " version = version + 1, updated_at = ? WHERE id = ?",
                    (new_title, new_body, now, issue.id))
        updated = self._issue_by_row_id(issue.id)
        assert updated is not None
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.issue.update", target_kind="repo",
                target_id=f"{current.full_name}#{issue.number}",
                outcome="success", source_ip=source_ip,
                detail={"number": issue.number,
                        "version": updated.version})
        return updated

    # -- S-130: close / reopen ------------------------------------
    def close_issue(self, actor: User, owner: object, repo: object,
                    number: object, reason: object = "completed",
                    *, source_ip: str | None = None) -> Issue:
        if reason not in CLOSE_REASONS:
            raise IssueError(
                "reason_invalid",
                "An issue closes as 'completed' or 'not_planned'.")
        return self._transition(
            actor, owner, repo, number, to_state="closed",
            reason=str(reason), source_ip=source_ip)

    def reopen_issue(self, actor: User, owner: object, repo: object,
                     number: object,
                     *, source_ip: str | None = None) -> Issue:
        return self._transition(
            actor, owner, repo, number, to_state="open",
            reason="", source_ip=source_ip)

    def _transition(self, actor: User, owner: object, repo: object,
                    number: object, *, to_state: str, reason: str,
                    source_ip: str | None) -> Issue:
        issue = self.get_issue(actor, owner, repo, number)
        current = self._require_repo(owner, repo)
        if actor.id != issue.author_id and not can_write(actor, current):
            raise IssueError(
                "permission_denied",
                "Only the author or a repository writer can change "
                "this issue's state.")
        if issue.state == to_state:
            return issue  # a retry, not a second event
        now = int(self._now())
        kind = "closed" if to_state == "closed" else "reopened"
        with self._conn:  # state, reason, and event land together
            self._conn.execute(
                "UPDATE issues SET state = ?, state_reason = ?,"
                " version = version + 1, updated_at = ? WHERE id = ?",
                (to_state, reason, now, issue.id))
            self._conn.execute(
                "INSERT INTO issue_events (issue_id, actor_id, kind,"
                " reason, created_at) VALUES (?, ?, ?, ?, ?)",
                (issue.id, actor.id, kind, reason, now))
        updated = self._issue_by_row_id(issue.id)
        assert updated is not None
        if self._audit is not None:
            detail: dict = {"number": issue.number}
            if kind == "closed":
                detail["reason"] = reason
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action=f"repo.issue.{'close' if kind == 'closed' else 'reopen'}",
                target_kind="repo",
                target_id=f"{current.full_name}#{issue.number}",
                outcome="success", source_ip=source_ip, detail=detail)
        return updated

    def state_events_for(self, viewer: User | None, owner: object,
                         repo: object, number: object
                         ) -> list[IssueStateEvent]:
        """The issue's state-change stream in order — the
        seam S-131's timeline reads state changes through."""
        issue = self.get_issue(viewer, owner, repo, number)
        rows = self._conn.execute(
            "SELECT e.*, u.username AS actor_name FROM issue_events e"
            " JOIN users u ON u.id = e.actor_id"
            " WHERE e.issue_id = ? ORDER BY e.id",
            (issue.id,)).fetchall()
        return [IssueStateEvent(
            id=r["id"], issue_id=r["issue_id"], actor_id=r["actor_id"],
            actor=r["actor_name"], kind=r["kind"], reason=r["reason"],
            created_at=r["created_at"]) for r in rows]

    # -- internals --------------------------------------------------
    def _issue_by_row_id(self, row_id: int) -> Issue | None:
        row = self._conn.execute(
            "SELECT * FROM issues WHERE id = ?", (row_id,)).fetchone()
        return _row_to_issue(row) if row else None


def _validate_title(title: object) -> str:
    if not isinstance(title, str):
        raise IssueError("title_required", "An issue needs a title.")
    text = title.strip()
    if not text:
        raise IssueError("title_required", "An issue needs a title.")
    if len(text) > TITLE_MAX or any(
            ord(c) < 0x20 or ord(c) == 0x7F for c in text):
        raise IssueError(
            "title_invalid",
            f"Titles are at most {TITLE_MAX} characters of plain text.")
    return text


def _validate_body(body: object) -> str:
    if body is None:
        return ""
    if not isinstance(body, str):
        raise IssueError("body_invalid", "The body must be text.")
    if len(body) > BODY_MAX or any(
            (ord(c) < 0x20 and c not in "\n\t") or ord(c) == 0x7F
            for c in body):
        raise IssueError(
            "body_invalid",
            f"Bodies are at most {BODY_MAX} characters of Markdown text.")
    return body
