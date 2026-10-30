"""Issue comments (S-123).

A comment is Markdown conversation on an issue, under
three laws:

- **The record is honest.** Editing a comment never
  rewrites history silently: the previous body is kept in
  `issue_comment_edits` (editor + time) before the new
  body lands, in the same transaction, and `edits_for`
  shows that history to any repository reader. A comment
  carries `edited_at` so a surface can say *edited*
  without opening the history.
- **Deletion is a tombstone plus an audit trail.**
  Deleting clears the body and stamps `deleted_at` /
  `deleted_by`; the row remains so counts, ordering and
  the audit reference stay true, list views skip
  tombstones, and the act is audited
  `repo.issue.comment_delete`. Only the author or a
  repository admin (the moderator road) may delete.
- **Permissions ride the repository's.** Reading and
  commenting require S-054 read access; a stranger to a
  private repository gets S-122's uniform
  `issue_not_found` for every comment operation, exactly
  as for the issue itself. Editing is the author's alone
  (moderators delete, they do not put words in another
  person's mouth).
- **A locked conversation refuses new comments**
  (S-132): `add_comment` is the one comment seam, so the
  lock is enforced here — everyone except repository
  writers/admins is refused `conversation_locked`, with
  the lock's reason named in words.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .issue_locking import LOCK_REASON_WORDS
from .issues import BODY_MAX, IssueError, IssueStore
from .permissions import can_admin, can_write
from .repositories import RepositoryStore


@dataclass(frozen=True)
class Comment:
    id: int
    issue_id: int
    number: int        # the issue's #n in its repository
    author_id: int
    body: str          # '' once deleted (tombstone)
    created_at: int
    updated_at: int
    edited_at: int | None
    deleted_at: int | None
    deleted_by: int | None

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def was_edited(self) -> bool:
        return self.edited_at is not None


@dataclass(frozen=True)
class CommentEdit:
    comment_id: int
    editor_id: int
    previous_body: str
    edited_at: int


def _row_to_comment(row: sqlite3.Row, number: int) -> Comment:
    return Comment(
        id=row["id"], issue_id=row["issue_id"], number=number,
        author_id=row["author_id"], body=row["body"],
        created_at=row["created_at"], updated_at=row["updated_at"],
        edited_at=row["edited_at"], deleted_at=row["deleted_at"],
        deleted_by=row["deleted_by"])


class IssueCommentStore:
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

    # -- create -----------------------------------------------------
    def add_comment(self, actor: User, owner: object, repo: object,
                    number: object, body: object,
                    *, source_ip: str | None = None) -> Comment:
        issue = self._issues.get_issue(actor, owner, repo, number)
        if issue.locked:
            # S-132: a locked conversation refuses new comments
            # from everyone except repository writers/admins,
            # with the lock's reason said in words.
            current = self._repos.get_repository(owner, repo)
            if current is None or not can_write(actor, current):
                words = LOCK_REASON_WORDS.get(issue.lock_reason, "")
                suffix = f" as {words}" if words else ""
                raise IssueError(
                    "conversation_locked",
                    f"This conversation is locked{suffix}; only "
                    "repository writers can still comment.")
        text = _validate_comment_body(body)
        now = int(self._now())
        with self._conn:  # commits before the answer
            cur = self._conn.execute(
                "INSERT INTO issue_comments (issue_id, author_id, body,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (issue.id, actor.id, text, now, now))
        comment = self._comment_by_id(int(cur.lastrowid), issue.number)
        assert comment is not None
        self._emit(actor, "repo.issue.comment", owner, repo, issue.number,
                   {"number": issue.number, "comment_id": comment.id},
                   source_ip)
        return comment

    # -- read ---------------------------------------------------------
    def list_comments(self, viewer: User | None, owner: object,
                      repo: object, number: object) -> list[Comment]:
        issue = self._issues.get_issue(viewer, owner, repo, number)
        rows = self._conn.execute(
            "SELECT * FROM issue_comments WHERE issue_id = ?"
            " AND deleted_at IS NULL ORDER BY id",
            (issue.id,)).fetchall()
        return [_row_to_comment(r, issue.number) for r in rows]

    def get_comment(self, viewer: User | None, owner: object,
                    repo: object, number: object,
                    comment_id: int) -> Comment:
        """One comment, tombstones included (a reader who
        follows a link to a deleted comment is told it was
        deleted, not that it never existed — unless they
        cannot read the repository at all)."""
        issue = self._issues.get_issue(viewer, owner, repo, number)
        comment = self._comment_by_id(comment_id, issue.number)
        if comment is None or comment.issue_id != issue.id:
            raise IssueError("comment_not_found", "No such comment.")
        return comment

    def edits_for(self, viewer: User | None, owner: object,
                  repo: object, number: object,
                  comment_id: int) -> list[CommentEdit]:
        comment = self.get_comment(viewer, owner, repo, number, comment_id)
        rows = self._conn.execute(
            "SELECT * FROM issue_comment_edits WHERE comment_id = ?"
            " ORDER BY id", (comment.id,)).fetchall()
        return [CommentEdit(comment_id=r["comment_id"],
                            editor_id=r["editor_id"],
                            previous_body=r["previous_body"],
                            edited_at=r["edited_at"]) for r in rows]

    # -- edit ---------------------------------------------------------
    def edit_comment(self, actor: User, owner: object, repo: object,
                     number: object, comment_id: int, body: object,
                     *, source_ip: str | None = None) -> Comment:
        comment = self.get_comment(actor, owner, repo, number, comment_id)
        if comment.is_deleted:
            raise IssueError("comment_not_found", "No such comment.")
        if actor.id != comment.author_id:
            raise IssueError(
                "permission_denied",
                "Only the author can edit this comment.")
        text = _validate_comment_body(body)
        now = int(self._now())
        with self._conn:  # history and new body land together
            self._conn.execute(
                "INSERT INTO issue_comment_edits (comment_id, editor_id,"
                " previous_body, edited_at) VALUES (?, ?, ?, ?)",
                (comment.id, actor.id, comment.body, now))
            self._conn.execute(
                "UPDATE issue_comments SET body = ?, updated_at = ?,"
                " edited_at = ? WHERE id = ?",
                (text, now, now, comment.id))
        updated = self._comment_by_id(comment.id, comment.number)
        assert updated is not None
        self._emit(actor, "repo.issue.comment_edit", owner, repo,
                   comment.number,
                   {"number": comment.number, "comment_id": comment.id},
                   source_ip)
        return updated

    # -- delete ---------------------------------------------------------
    def delete_comment(self, actor: User, owner: object, repo: object,
                       number: object, comment_id: int,
                       *, source_ip: str | None = None) -> Comment:
        comment = self.get_comment(actor, owner, repo, number, comment_id)
        if comment.is_deleted:
            raise IssueError("comment_not_found", "No such comment.")
        current = self._repos.get_repository(owner, repo)
        if actor.id != comment.author_id and (
                current is None or not can_admin(actor, current)):
            raise IssueError(
                "permission_denied",
                "Only the author or a repository admin can delete "
                "this comment.")
        now = int(self._now())
        with self._conn:  # tombstone commits before the answer
            self._conn.execute(
                "UPDATE issue_comments SET body = '', updated_at = ?,"
                " deleted_at = ?, deleted_by = ? WHERE id = ?",
                (now, now, actor.id, comment.id))
        deleted = self._comment_by_id(comment.id, comment.number)
        assert deleted is not None
        self._emit(actor, "repo.issue.comment_delete", owner, repo,
                   comment.number,
                   {"number": comment.number, "comment_id": comment.id},
                   source_ip)
        return deleted

    # -- internals ------------------------------------------------------
    def _comment_by_id(self, comment_id: int,
                       number: int) -> Comment | None:
        row = self._conn.execute(
            "SELECT * FROM issue_comments WHERE id = ?",
            (comment_id,)).fetchone()
        return _row_to_comment(row, number) if row else None

    def _emit(self, actor: User, action: str, owner: object,
              repo: object, number: int, detail: dict,
              source_ip: str | None) -> None:
        if self._audit is not None:
            current = self._repos.get_repository(owner, repo)
            target = (f"{current.full_name}#{number}"
                      if current is not None else f"#{number}")
            self._audit.append(
                actor_kind="user", actor_id=actor.id, action=action,
                target_kind="repo", target_id=target,
                outcome="success", source_ip=source_ip, detail=detail)


def _validate_comment_body(body: object) -> str:
    if not isinstance(body, str) or not body.strip():
        raise IssueError(
            "comment_required", "A comment needs some text.")
    if len(body) > BODY_MAX or any(
            (ord(c) < 0x20 and c not in "\n\t") or ord(c) == 0x7F
            for c in body):
        raise IssueError(
            "comment_invalid",
            f"Comments are at most {BODY_MAX} characters of "
            "Markdown text.")
    return body
