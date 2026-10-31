"""Pull request review threads (S-147).

A review thread is one S-146 line comment and the
replies under it, with one explicit state: resolved
or unresolved.

- **Replies live under the root comment.** A reply
  is written against a live line comment of this
  pull request (migration 52); a reply to a comment
  that does not exist, belongs to another pull
  request, or has been deleted is refused
  `comment_not_found` and stores nothing. Replies
  carry S-123's honest record, like the root does:
  author-only edits with the previous bodies kept,
  tombstone deletion by the author or a repository
  admin. Any repository reader may reply, as any
  reader may comment (S-144/S-146). Replying never
  changes the resolution state by itself —
  resolution is always someone's explicit act.
- **Resolution is an act with named actors.** The
  thread's author (the root comment's author), the
  pull request's author, or a repository writer may
  resolve or unresolve; anyone else is refused
  `permission_denied`, with the rule said in the
  message. Resolving an already-resolved thread —
  and unresolving one that is not resolved — is a
  quiet no-op: no state rewrite, no second audit
  event (the S-132/S-143 retry law). The audit log
  keeps the history of both acts; the resolution
  record itself exists only while resolved.
- **Resolution feeds the merge gates through one
  summary.** `resolution_summary` counts a pull
  request's live threads — total, resolved, and
  unresolved — and says the result in words
  (`words`), with `blocks_merge` naming whether
  unresolved threads remain for the merge slices
  (S-153…S-155) and Part VIII's rules to enforce.
  This slice builds the count honestly; pressing
  the merge button is not this slice's work. A
  thread on an outdated line (S-146) still counts:
  outdated is about the anchor, resolution is
  about the conversation, and neither erases the
  other.
- **Permissions ride the pull request's.** Every
  read and write goes through S-141's seam (via
  S-146's store): a stranger to a private
  repository gets the uniform
  `pull_request_not_found` on every surface.
- **Audited under its own events** (taxonomy
  append-only +5: `repo.pull_request.line_reply` /
  `.line_reply_edit` / `.line_reply_delete` /
  `.thread_resolve` / `.thread_unresolve`, 103
  events; carried by S-139's outbox under its
  `repo.pull_request.*` verb rule). Audit detail
  names ids, never bodies.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .issue_comments import _validate_comment_body
from .issues import IssueError, IssueStore
from .permissions import can_admin, can_write
from .pull_request_line_comments import (
    LineComment, PullRequestLineCommentStore)
from .pull_requests import PullRequestError, PullRequestStore
from .repositories import RepositoryStore

__all__ = [
    "LineReply", "LineReplyEdit", "PullRequestReviewThreadStore",
    "ReviewThread", "ThreadSummary", "render_thread",
]


@dataclass(frozen=True)
class LineReply:
    id: int
    comment_id: int          # the thread's root line comment
    number: int              # the pull request's #n
    author_id: int
    body: str                # '' once deleted (tombstone)
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
class LineReplyEdit:
    reply_id: int
    editor_id: int
    previous_body: str
    edited_at: int


@dataclass(frozen=True)
class ReviewThread:
    root: LineComment
    replies: tuple           # of LineReply, live only, oldest first
    is_resolved: bool
    resolved_by: int | None
    resolved_at: int | None

    @property
    def reply_count(self) -> int:
        return len(self.replies)

    @property
    def resolution_words(self) -> str:
        """The resolution state in words — never a
        colour or an icon alone."""
        return "Resolved" if self.is_resolved else "Unresolved"


@dataclass(frozen=True)
class ThreadSummary:
    total: int
    resolved: int
    unresolved: int

    @property
    def blocks_merge(self) -> bool:
        """Whether unresolved threads remain for the
        merge gates to refuse on."""
        return self.unresolved > 0

    @property
    def words(self) -> str:
        if self.total == 0:
            return "No review threads on this pull request."
        if self.unresolved == 0:
            return "All review threads are resolved."
        verb = "is" if self.unresolved == 1 else "are"
        return (f"{self.unresolved} of {self.total} review "
                f"threads {verb} unresolved.")


def _row_to_reply(row: sqlite3.Row, number: int) -> LineReply:
    return LineReply(
        id=row["id"], comment_id=row["comment_id"], number=number,
        author_id=row["author_id"], body=row["body"],
        created_at=row["created_at"], updated_at=row["updated_at"],
        edited_at=row["edited_at"], deleted_at=row["deleted_at"],
        deleted_by=row["deleted_by"])


class PullRequestReviewThreadStore:
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
        self._lines = PullRequestLineCommentStore(
            conn, repositories, accounts, issues, audit=audit,
            time_fn=time_fn)

    # -- internals ---------------------------------------------------
    def _validate_body(self, body: object) -> str:
        try:
            return _validate_comment_body(body)
        except IssueError as exc:
            raise PullRequestError(exc.reason, str(exc)) from None

    def _root(self, viewer, owner, repo, number,
              comment_id: int) -> LineComment:
        root = self._lines.get_line_comment(
            viewer, owner, repo, number, comment_id)
        if root.is_deleted:
            raise PullRequestError(
                "comment_not_found", "No such line comment.")
        return root

    def _resolution(self, comment_id: int):
        return self._conn.execute(
            "SELECT * FROM pull_request_review_threads"
            " WHERE comment_id = ?", (comment_id,)).fetchone()

    def _reply_by_id(self, reply_id: int,
                     number: int) -> LineReply | None:
        row = self._conn.execute(
            "SELECT * FROM pull_request_line_replies WHERE id = ?",
            (reply_id,)).fetchone()
        return _row_to_reply(row, number) if row else None

    def _emit(self, actor: User, action: str, owner, repo,
              number: int, detail: dict,
              source_ip: str | None) -> None:
        if self._audit is not None:
            current = self._repos.get_repository(owner, repo)
            target = (f"{current.full_name}#{number}"
                      if current is not None else f"#{number}")
            self._audit.append(
                actor_kind="user", actor_id=actor.id, action=action,
                target_kind="repo", target_id=target,
                outcome="success", source_ip=source_ip, detail=detail)

    def _require_resolver(self, actor: User, owner, repo,
                          pr, root: LineComment) -> None:
        current = self._repos.get_repository(owner, repo)
        if actor.id in (root.author_id, pr.author_id) or (
                current is not None and can_write(actor, current)):
            return
        raise PullRequestError(
            "permission_denied",
            "Only the comment's author, the pull request's "
            "author, or a repository writer can change this "
            "thread's resolution.")

    # -- replies ---------------------------------------------------------
    def add_reply(self, actor: User, owner: object, repo: object,
                  number: object, comment_id: int, body: object,
                  *, source_ip: str | None = None) -> LineReply:
        """Reply in a line comment's thread. Replying
        never resolves or unresolves the thread."""
        pr = self._prs.get_pull_request(actor, owner, repo, number)
        root = self._root(actor, owner, repo, number, comment_id)
        text = self._validate_body(body)
        now = int(self._now())
        with self._conn:  # commits before the answer
            cur = self._conn.execute(
                "INSERT INTO pull_request_line_replies"
                " (comment_id, author_id, body, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (root.id, actor.id, text, now, now))
        reply = self._reply_by_id(int(cur.lastrowid), pr.number)
        assert reply is not None
        self._emit(actor, "repo.pull_request.line_reply", owner, repo,
                   pr.number,
                   {"number": pr.number, "comment_id": root.id,
                    "reply_id": reply.id}, source_ip)
        return reply

    def get_reply(self, viewer: User | None, owner: object,
                  repo: object, number: object,
                  comment_id: int, reply_id: int) -> LineReply:
        """One reply, tombstones included."""
        pr = self._prs.get_pull_request(viewer, owner, repo, number)
        root = self._root(viewer, owner, repo, number, comment_id)
        reply = self._reply_by_id(reply_id, pr.number)
        if reply is None or reply.comment_id != root.id:
            raise PullRequestError(
                "comment_not_found", "No such reply.")
        return reply

    def edit_reply(self, actor: User, owner: object, repo: object,
                   number: object, comment_id: int, reply_id: int,
                   body: object,
                   *, source_ip: str | None = None) -> LineReply:
        """Edit one's own reply; the previous body is
        kept in the edit history in the same
        transaction."""
        pr = self._prs.get_pull_request(actor, owner, repo, number)
        reply = self.get_reply(actor, owner, repo, number,
                               comment_id, reply_id)
        if reply.is_deleted:
            raise PullRequestError(
                "comment_not_found", "No such reply.")
        if actor.id != reply.author_id:
            raise PullRequestError(
                "permission_denied",
                "Only the author can edit this reply.")
        text = self._validate_body(body)
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "INSERT INTO pull_request_line_reply_edits"
                " (reply_id, editor_id, previous_body, edited_at)"
                " VALUES (?, ?, ?, ?)",
                (reply.id, actor.id, reply.body, now))
            self._conn.execute(
                "UPDATE pull_request_line_replies SET body = ?,"
                " updated_at = ?, edited_at = ? WHERE id = ?",
                (text, now, now, reply.id))
        updated = self._reply_by_id(reply.id, pr.number)
        assert updated is not None
        self._emit(actor, "repo.pull_request.line_reply_edit",
                   owner, repo, pr.number,
                   {"number": pr.number, "comment_id": comment_id,
                    "reply_id": reply.id}, source_ip)
        return updated

    def delete_reply(self, actor: User, owner: object, repo: object,
                     number: object, comment_id: int, reply_id: int,
                     *, source_ip: str | None = None) -> LineReply:
        """Delete a reply: a tombstone plus an audit
        row. The author, or a repository admin."""
        pr = self._prs.get_pull_request(actor, owner, repo, number)
        reply = self.get_reply(actor, owner, repo, number,
                               comment_id, reply_id)
        if reply.is_deleted:
            raise PullRequestError(
                "comment_not_found", "No such reply.")
        current = self._repos.get_repository(owner, repo)
        if actor.id != reply.author_id and (
                current is None or not can_admin(actor, current)):
            raise PullRequestError(
                "permission_denied",
                "Only the author or a repository admin can delete "
                "this reply.")
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "UPDATE pull_request_line_replies SET body = '',"
                " updated_at = ?, deleted_at = ?, deleted_by = ?"
                " WHERE id = ?",
                (now, now, actor.id, reply.id))
        deleted = self._reply_by_id(reply.id, pr.number)
        assert deleted is not None
        self._emit(actor, "repo.pull_request.line_reply_delete",
                   owner, repo, pr.number,
                   {"number": pr.number, "comment_id": comment_id,
                    "reply_id": reply.id}, source_ip)
        return deleted

    def reply_edits_for(self, viewer: User | None, owner: object,
                        repo: object, number: object,
                        comment_id: int,
                        reply_id: int) -> list[LineReplyEdit]:
        reply = self.get_reply(viewer, owner, repo, number,
                               comment_id, reply_id)
        rows = self._conn.execute(
            "SELECT * FROM pull_request_line_reply_edits"
            " WHERE reply_id = ? ORDER BY id",
            (reply.id,)).fetchall()
        return [LineReplyEdit(
            reply_id=r["reply_id"], editor_id=r["editor_id"],
            previous_body=r["previous_body"],
            edited_at=r["edited_at"]) for r in rows]

    # -- threads ------------------------------------------------------------
    def _thread(self, root: LineComment) -> ReviewThread:
        rows = self._conn.execute(
            "SELECT * FROM pull_request_line_replies"
            " WHERE comment_id = ? AND deleted_at IS NULL"
            " ORDER BY id", (root.id,)).fetchall()
        resolution = self._resolution(root.id)
        return ReviewThread(
            root=root,
            replies=tuple(_row_to_reply(r, root.number) for r in rows),
            is_resolved=resolution is not None,
            resolved_by=(int(resolution["resolved_by"])
                         if resolution is not None else None),
            resolved_at=(int(resolution["resolved_at"])
                         if resolution is not None else None))

    def thread_for(self, viewer: User | None, owner: object,
                   repo: object, number: object,
                   comment_id: int) -> ReviewThread:
        """One thread: its root (with S-146's freshness
        judged), its live replies, and its resolution."""
        root = self._root(viewer, owner, repo, number, comment_id)
        return self._thread(root)

    def threads_for(self, viewer: User | None, owner: object,
                    repo: object, number: object) -> list[ReviewThread]:
        """Every live thread on this pull request, in
        the roots' own order."""
        roots = self._lines.list_line_comments(
            viewer, owner, repo, number)
        return [self._thread(root) for root in roots]

    def resolution_summary(self, viewer: User | None, owner: object,
                           repo: object, number: object
                           ) -> ThreadSummary:
        """The one count the merge gates consult:
        how many of this pull request's threads are
        still unresolved."""
        threads = self.threads_for(viewer, owner, repo, number)
        resolved = sum(1 for t in threads if t.is_resolved)
        return ThreadSummary(
            total=len(threads), resolved=resolved,
            unresolved=len(threads) - resolved)

    # -- resolution ------------------------------------------------------------
    def resolve_thread(self, actor: User, owner: object, repo: object,
                       number: object, comment_id: int,
                       *, source_ip: str | None = None) -> ReviewThread:
        """Mark a thread resolved. Already resolved is
        a quiet no-op — no rewrite, no second event."""
        pr = self._prs.get_pull_request(actor, owner, repo, number)
        root = self._root(actor, owner, repo, number, comment_id)
        self._require_resolver(actor, owner, repo, pr, root)
        if self._resolution(root.id) is None:
            now = int(self._now())
            with self._conn:
                self._conn.execute(
                    "INSERT INTO pull_request_review_threads"
                    " (comment_id, resolved_by, resolved_at)"
                    " VALUES (?, ?, ?)", (root.id, actor.id, now))
            self._emit(actor, "repo.pull_request.thread_resolve",
                       owner, repo, pr.number,
                       {"number": pr.number, "comment_id": root.id},
                       source_ip)
        return self._thread(root)

    def unresolve_thread(self, actor: User, owner: object, repo: object,
                         number: object, comment_id: int,
                         *, source_ip: str | None = None) -> ReviewThread:
        """Mark a thread unresolved again. Not
        resolved is a quiet no-op."""
        pr = self._prs.get_pull_request(actor, owner, repo, number)
        root = self._root(actor, owner, repo, number, comment_id)
        self._require_resolver(actor, owner, repo, pr, root)
        if self._resolution(root.id) is not None:
            with self._conn:
                self._conn.execute(
                    "DELETE FROM pull_request_review_threads"
                    " WHERE comment_id = ?", (root.id,))
            self._emit(actor, "repo.pull_request.thread_unresolve",
                       owner, repo, pr.number,
                       {"number": pr.number, "comment_id": root.id},
                       source_ip)
        return self._thread(root)


def render_thread(thread: ReviewThread) -> str:
    """One thread as HTML: the root's anchor and
    freshness in words, its resolution in words,
    then root and replies as speech, every body
    through S-010."""
    root = thread.root
    parts = ['<div class="review-thread">']
    parts.append(
        f'<p class="anchor">{escape_html_text(root.anchor_words)}'
        f" · {escape_html_text(root.state_words)}"
        f" · {escape_html_text(thread.resolution_words)}</p>")
    parts.append(
        f'<p class="comment-body">{escape_html_text(root.body)}</p>')
    for reply in thread.replies:
        edited = (' <span class="edited">edited</span>'
                  if reply.was_edited else "")
        parts.append(
            '<p class="reply-body">'
            f"{escape_html_text(reply.body)}</p>{edited}")
    parts.append("</div>")
    return "\n".join(parts)
