"""Pull request line comments (S-146).

A line comment is a comment anchored to one line of
the pull request's diff — the place a reviewer was
actually looking when they wrote it.

- **The anchor is exact.** A line comment records
  the file path, the side (`old` / `new`), the line
  number on that side, the line's text, and the
  head oid it was written against (migration 51).
  Anchoring validates whole against the current
  diff (S-145's diff, so same-repo and cross-fork
  pull requests anchor the same way): a file not in
  the diff is refused `file_not_found`, a side that
  is not `old`/`new` is refused `side_invalid`, and
  a line that does not exist on that side of that
  file — including an added line addressed on the
  old side, or a removed line on the new side — is
  refused `line_not_found`. A refused anchoring
  stores nothing.
- **Outdated is judged on every read, never
  stored.** A comment reads as outdated when the
  current diff no longer carries that exact line
  (same file, same side, same number, same text).
  That is the honest rule for "the lines moved":
  a push that rewrites the line, inserts lines
  above it so it shifts, or removes the file from
  the diff altogether marks the comment outdated;
  a push that leaves the anchored line exactly
  where it was leaves the comment current. The
  record itself is never moved to a new line
  silently — the reader is told, in words
  (`state_words`), that the line has moved or
  changed, and the comment stays at its original
  anchor so what the reviewer saw remains provable.
- **The comment record is S-123's honest record.**
  Editing is the author's alone and keeps the
  previous body in the visible edit history;
  deletion is a tombstone (author or repository
  admin). Threaded replies and resolution are
  S-147's slice, built on this record.
- **Permissions ride the pull request's.** Every
  read and write goes through S-141's seam: a
  stranger to a private repository gets the
  uniform `pull_request_not_found` on every
  surface. Any repository reader may comment, as
  in S-144's conversation.
- **Audited under its own events** (taxonomy
  append-only +3: `repo.pull_request.line_comment`
  / `.line_comment_edit` / `.line_comment_delete`,
  98 events; carried by S-139's outbox under its
  `repo.pull_request.*` verb rule). Audit detail
  names the anchor, never the body.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, replace

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .issue_comments import _validate_comment_body
from .issues import IssueError, IssueStore
from .permissions import can_admin
from .pull_request_files import PullRequestFilesStore
from .pull_requests import PullRequestError, PullRequestStore
from .repositories import RepositoryStore

__all__ = [
    "LineComment", "LineCommentEdit", "PullRequestLineCommentStore",
    "render_line_comments",
]

SIDES = ("old", "new")

_SIDE_WORDS = {"old": "the old side", "new": "the new side"}


@dataclass(frozen=True)
class LineComment:
    id: int
    pull_request_id: int     # pull_requests row id
    number: int              # the pull request's #n
    author_id: int
    file_path: str
    side: str                # 'old' | 'new'
    line_number: int
    line_text: str
    head_oid: str            # head as it stood when written
    body: str                # '' once deleted (tombstone)
    created_at: int
    updated_at: int
    edited_at: int | None
    deleted_at: int | None
    deleted_by: int | None
    is_outdated: bool = False

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def was_edited(self) -> bool:
        return self.edited_at is not None

    @property
    def anchor_words(self) -> str:
        """Where this comment sits, in words."""
        return (f"{self.file_path}, line {self.line_number} "
                f"on {_SIDE_WORDS.get(self.side, self.side)}")

    @property
    def state_words(self) -> str:
        """Current or outdated, in words — never a
        colour or an icon alone."""
        if self.is_outdated:
            return ("Outdated — the line this comment was on "
                    "has moved or changed since it was written")
        return "Current"


@dataclass(frozen=True)
class LineCommentEdit:
    comment_id: int
    editor_id: int
    previous_body: str
    edited_at: int


def _row_to_line_comment(row: sqlite3.Row, number: int) -> LineComment:
    return LineComment(
        id=row["id"], pull_request_id=row["pull_request_id"],
        number=number, author_id=row["author_id"],
        file_path=row["file_path"], side=row["side"],
        line_number=int(row["line_number"]),
        line_text=row["line_text"], head_oid=row["head_oid"],
        body=row["body"], created_at=row["created_at"],
        updated_at=row["updated_at"], edited_at=row["edited_at"],
        deleted_at=row["deleted_at"], deleted_by=row["deleted_by"])


class PullRequestLineCommentStore:
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
        self._prs = PullRequestStore(
            conn, repositories, accounts, issues, audit=audit,
            time_fn=time_fn)
        self._files = PullRequestFilesStore(
            conn, repositories, accounts, issues, audit=audit,
            time_fn=time_fn)

    # -- internals ---------------------------------------------------
    def _validate_body(self, body: object) -> str:
        try:
            return _validate_comment_body(body)
        except IssueError as exc:
            raise PullRequestError(exc.reason, str(exc)) from None

    def _current_diff(self, viewer, owner, repo, pr):
        diff, _base_oid, head_oid = self._files._diff_for(
            viewer, owner, repo, pr)
        return diff, head_oid

    @staticmethod
    def _anchor_line(diff, file_path: object, side: object,
                     line_number: object):
        """The diff line the anchor names, or the named
        refusal. Returns (file, line)."""
        if side not in SIDES:
            raise PullRequestError(
                "side_invalid",
                "A line comment sits on the 'old' side or the "
                "'new' side of the diff.")
        if not isinstance(file_path, str) or not file_path:
            raise PullRequestError(
                "file_not_found", "No such file in this pull request.")
        file = None
        for entry in diff.files:
            if entry.path == file_path:
                file = entry
                break
        if file is None:
            raise PullRequestError(
                "file_not_found",
                f"{file_path!r} is not one of the files this pull "
                "request changes.")
        if not isinstance(line_number, int) \
                or isinstance(line_number, bool) or line_number <= 0:
            raise PullRequestError(
                "line_not_found", "No such line in this diff.")
        for line in file.lines:
            number = (line.old_number if side == "old"
                      else line.new_number)
            if number == line_number:
                return file, line
        raise PullRequestError(
            "line_not_found",
            f"There is no line {line_number} on the {side} side "
            f"of {file_path} in this diff.")

    @staticmethod
    def _is_outdated(comment: LineComment, diff) -> bool:
        """The outdated judgement: the current diff no
        longer carries the comment's exact line — same
        file, same side, same number, same text."""
        for entry in diff.files:
            if entry.path != comment.file_path:
                continue
            for line in entry.lines:
                number = (line.old_number if comment.side == "old"
                          else line.new_number)
                if number == comment.line_number \
                        and line.text == comment.line_text:
                    return False
            return True   # the file is there; the line is not
        return True       # the file itself left the diff

    def _with_freshness(self, comments, diff):
        return [replace(c, is_outdated=self._is_outdated(c, diff))
                for c in comments]

    def _comment_by_id(self, comment_id: int,
                       number: int) -> LineComment | None:
        row = self._conn.execute(
            "SELECT * FROM pull_request_line_comments WHERE id = ?",
            (comment_id,)).fetchone()
        return _row_to_line_comment(row, number) if row else None

    def _emit(self, actor: User, action: str, owner, repo,
              number: int, comment: LineComment,
              source_ip: str | None) -> None:
        if self._audit is not None:
            current = self._repos.get_repository(owner, repo)
            target = (f"{current.full_name}#{number}"
                      if current is not None else f"#{number}")
            self._audit.append(
                actor_kind="user", actor_id=actor.id, action=action,
                target_kind="repo", target_id=target,
                outcome="success", source_ip=source_ip,
                detail={"number": number, "comment_id": comment.id,
                        "file": comment.file_path,
                        "side": comment.side,
                        "line": comment.line_number})

    # -- create ---------------------------------------------------------
    def add_line_comment(self, actor: User, owner: object, repo: object,
                         number: object, file_path: object,
                         side: object, line_number: object,
                         body: object,
                         *, source_ip: str | None = None) -> LineComment:
        """Comment on one line of the pull request's
        current diff. The anchor validates whole
        before anything is stored."""
        pr = self._prs.get_pull_request(actor, owner, repo, number)
        diff, head_oid = self._current_diff(actor, owner, repo, pr)
        _file, line = self._anchor_line(diff, file_path, side, line_number)
        text = self._validate_body(body)
        now = int(self._now())
        with self._conn:  # commits before the answer
            cur = self._conn.execute(
                "INSERT INTO pull_request_line_comments"
                " (pull_request_id, author_id, file_path, side,"
                " line_number, line_text, head_oid, body,"
                " created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (pr.id, actor.id, file_path, side, int(line_number),
                 line.text, head_oid, text, now, now))
        comment = self._comment_by_id(int(cur.lastrowid), pr.number)
        assert comment is not None
        self._emit(actor, "repo.pull_request.line_comment", owner, repo,
                   pr.number, comment, source_ip)
        return comment

    # -- reads ------------------------------------------------------------
    def list_line_comments(self, viewer: User | None, owner: object,
                           repo: object, number: object,
                           *, file_path: object = None
                           ) -> list[LineComment]:
        """Every live line comment on this pull
        request, oldest first, each judged against
        the current diff. Tombstones are skipped;
        one file's comments can be read alone."""
        pr = self._prs.get_pull_request(viewer, owner, repo, number)
        diff, _head_oid = self._current_diff(viewer, owner, repo, pr)
        sql = ("SELECT * FROM pull_request_line_comments"
               " WHERE pull_request_id = ? AND deleted_at IS NULL")
        params: list = [pr.id]
        if file_path is not None:
            sql += " AND file_path = ?"
            params.append(file_path)
        sql += " ORDER BY id"
        rows = self._conn.execute(sql, params).fetchall()
        comments = [_row_to_line_comment(r, pr.number) for r in rows]
        return self._with_freshness(comments, diff)

    def get_line_comment(self, viewer: User | None, owner: object,
                         repo: object, number: object,
                         comment_id: int) -> LineComment:
        """One line comment, tombstones included, with
        its freshness judged against the current diff."""
        pr = self._prs.get_pull_request(viewer, owner, repo, number)
        comment = self._comment_by_id(comment_id, pr.number)
        if comment is None or comment.pull_request_id != pr.id:
            raise PullRequestError(
                "comment_not_found", "No such line comment.")
        diff, _head_oid = self._current_diff(viewer, owner, repo, pr)
        return replace(
            comment, is_outdated=self._is_outdated(comment, diff))

    def edits_for(self, viewer: User | None, owner: object,
                  repo: object, number: object,
                  comment_id: int) -> list[LineCommentEdit]:
        """The visible edit history of one line
        comment — the previous bodies, in order."""
        comment = self.get_line_comment(
            viewer, owner, repo, number, comment_id)
        rows = self._conn.execute(
            "SELECT * FROM pull_request_line_comment_edits"
            " WHERE comment_id = ? ORDER BY id",
            (comment.id,)).fetchall()
        return [LineCommentEdit(
            comment_id=r["comment_id"], editor_id=r["editor_id"],
            previous_body=r["previous_body"],
            edited_at=r["edited_at"]) for r in rows]

    # -- edit / delete -------------------------------------------------------
    def edit_line_comment(self, actor: User, owner: object, repo: object,
                          number: object, comment_id: int, body: object,
                          *, source_ip: str | None = None) -> LineComment:
        """Edit one's own line comment; the previous
        body is kept in the edit history in the same
        transaction. Editing never moves the anchor."""
        pr = self._prs.get_pull_request(actor, owner, repo, number)
        comment = self.get_line_comment(actor, owner, repo, number,
                                        comment_id)
        if comment.is_deleted:
            raise PullRequestError(
                "comment_not_found", "No such line comment.")
        if actor.id != comment.author_id:
            raise PullRequestError(
                "permission_denied",
                "Only the author can edit this comment.")
        text = self._validate_body(body)
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "INSERT INTO pull_request_line_comment_edits"
                " (comment_id, editor_id, previous_body, edited_at)"
                " VALUES (?, ?, ?, ?)",
                (comment.id, actor.id, comment.body, now))
            self._conn.execute(
                "UPDATE pull_request_line_comments SET body = ?,"
                " updated_at = ?, edited_at = ? WHERE id = ?",
                (text, now, now, comment.id))
        updated = self.get_line_comment(actor, owner, repo, number,
                                        comment.id)
        self._emit(actor, "repo.pull_request.line_comment_edit",
                   owner, repo, pr.number, updated, source_ip)
        return updated

    def delete_line_comment(self, actor: User, owner: object,
                            repo: object, number: object,
                            comment_id: int,
                            *, source_ip: str | None = None
                            ) -> LineComment:
        """Delete a line comment: a tombstone plus an
        audit row. The author, or a repository admin."""
        pr = self._prs.get_pull_request(actor, owner, repo, number)
        comment = self.get_line_comment(actor, owner, repo, number,
                                        comment_id)
        if comment.is_deleted:
            raise PullRequestError(
                "comment_not_found", "No such line comment.")
        current = self._repos.get_repository(owner, repo)
        if actor.id != comment.author_id and (
                current is None or not can_admin(actor, current)):
            raise PullRequestError(
                "permission_denied",
                "Only the author or a repository admin can delete "
                "this comment.")
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "UPDATE pull_request_line_comments SET body = '',"
                " updated_at = ?, deleted_at = ?, deleted_by = ?"
                " WHERE id = ?",
                (now, now, actor.id, comment.id))
        deleted = self._comment_by_id(comment.id, pr.number)
        assert deleted is not None
        self._emit(actor, "repo.pull_request.line_comment_delete",
                   owner, repo, pr.number, deleted, source_ip)
        return deleted


def render_line_comments(comments: list[LineComment]) -> str:
    """The line comments as HTML: each comment's
    anchor and its current/outdated state said in
    words, its body through S-010, an *edited*
    marker when it was edited. An empty list says
    so plainly."""
    if not comments:
        return ('<p class="empty">No line comments on this pull '
                "request yet.</p>")
    parts = ['<ol class="line-comments">']
    for comment in comments:
        edited = (' <span class="edited">edited</span>'
                  if comment.was_edited else "")
        parts.append(
            '<li class="line-comment">'
            f'<p class="anchor">{escape_html_text(comment.anchor_words)}'
            f" · {escape_html_text(comment.state_words)}</p>"
            f'<p class="comment-body">'
            f"{escape_html_text(comment.body)}</p>"
            f"{edited}</li>")
    parts.append("</ol>")
    return "\n".join(parts)
