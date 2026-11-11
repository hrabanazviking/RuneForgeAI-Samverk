"""Gist comments (S-280).

Roadmap S-280: Gist comments -- the issue-comment
machinery (S-123) reused, not duplicated.

A comment on a gist is the S-123 conversation carried
to a gist, standing on S-277's model, S-278's
visibility law and S-279's fork/star face in
``samverk/gists.py`` / ``samverk/gist_web.py``. The
machinery is S-123's, reused piece by piece, never
re-invented:

- **The body law is S-123's own.** A gist comment body
  is judged by ``samverk/issue_comments.py``'s
  ``_validate_comment_body`` -- the one validator the
  pull-request line comments and review threads also
  ride -- translated here from ``IssueError`` to
  ``GistError`` with the reason and the words intact:
  ``comment_required`` for no text, ``comment_invalid``
  past S-122's ``BODY_MAX`` or with control characters.
  A comment is Markdown text, at most that one cap,
  everywhere it is taken.
- **The record is honest (S-123).** Editing never
  rewrites history silently: the previous body is kept
  in migration 111's ``gist_comment_edits`` (editor +
  time) before the new body lands, in the same
  transaction, and ``edits_for`` shows that history to
  any gist reader. A comment carries ``edited_at`` so
  a surface can say *edited* without opening the
  history. The tables are migration 35's
  ``issue_comments`` / ``issue_comment_edits`` shape
  carried whole, one column renamed: ``gist_id`` for
  ``issue_id``.
- **Deletion is a tombstone (S-123).** Deleting clears
  the body and stamps ``deleted_at`` / ``deleted_by``;
  the row remains so counts, ordering and references
  stay true, list views skip tombstones, and a reader
  who follows a link to a deleted comment is told it
  was deleted, not that it never existed. Only the
  author, the gist's owner, or a site admin may
  delete: the gist's owner is the moderator here, as
  the repository admin is for an issue -- moderators
  delete, they do not edit another person's words.
  Editing is the author's alone.
- **Permissions ride the gist's, not a repository's.**
  A gist has no repository and no S-054 gate: reading
  is S-278's law -- public and secret alike are
  readable by anyone who reaches the gist by its id,
  signed in or not (a secret gist is unlisted, not
  private), so listing and reading comments follow
  the gist's own read door in ``GistStore`` and an
  unknown gist id is the uniform ``gist_not_found``
  for every comment operation. Commenting is a
  signed-in act (``permission_denied`` for an
  anonymous visitor, as creating and forking are);
  any signed-in reader who can reach the gist by its
  link may comment on it, a secret gist included.
- **Comments belong to the gist, not a revision.**
  A gist's files move by revision; its conversation
  does not. Editing the gist's files or description
  moves no comment, forking copies the history and
  the files but not the conversation (a fork starts
  with no comments, as a forked repository starts
  with no issues), and deleting the gist deletes its
  comments and their edit history with it (wired in
  ``GistStore.delete_gist``).
- **Unwitnessed, as every gist act is.** Gist acts
  carry no verb of their own in the frozen taxonomy
  vocabulary (S-277's law, unchanged): the store
  accepts an audit handle for house symmetry and
  appends nothing -- no new taxonomy event, 133 stand
  (33 auth / 87 repo / 13 admin).

Storage is migration 111's ``gist_comments`` and
``gist_comment_edits`` tables (schema 110 -> 111).
The web face lives in ``samverk/gist_web.py``.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .gists import GistError, GistStore
from .issue_comments import _validate_comment_body
from .issues import IssueError

__all__ = [
    "GistComment", "GistCommentEdit", "GistCommentStore",
    "gist_comment_to_dict", "render_gist_comments",
]


@dataclass(frozen=True)
class GistComment:
    id: int
    gist_id: int
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
class GistCommentEdit:
    comment_id: int
    editor_id: int
    previous_body: str
    edited_at: int


def _row_to_comment(row: sqlite3.Row) -> GistComment:
    return GistComment(
        id=row["id"], gist_id=row["gist_id"],
        author_id=row["author_id"], body=row["body"],
        created_at=row["created_at"], updated_at=row["updated_at"],
        edited_at=row["edited_at"], deleted_at=row["deleted_at"],
        deleted_by=row["deleted_by"])


def gist_comment_to_dict(comment: GistComment) -> dict:
    return {
        "id": comment.id,
        "gist_id": comment.gist_id,
        "author_id": comment.author_id,
        "body": comment.body,
        "created_at": comment.created_at,
        "updated_at": comment.updated_at,
        "edited_at": comment.edited_at,
        "deleted_at": comment.deleted_at,
        "deleted_by": comment.deleted_by,
        "is_deleted": comment.is_deleted,
        "was_edited": comment.was_edited,
    }


def render_gist_comments(
        comments: list[GistComment],
        authors: dict[int, str] | None = None) -> str:
    """The conversation in words (S-010-escaped): each
    live comment's author and body as plain escaped
    text, an *edited* marker in words when it was
    edited. Tombstones never reach a list, so none is
    rendered here. An empty conversation says so
    plainly."""
    if not comments:
        return ('<p class="empty">No comments on this gist yet.</p>')
    parts = ['<ol class="gist-comments">']
    for comment in comments:
        name = (authors or {}).get(
            comment.author_id, f"user {comment.author_id}")
        edited = (' <span class="edited">edited</span>'
                  if comment.was_edited else "")
        parts.append(
            '<li class="gist-comment">'
            f'<p class="comment-author">'
            f'{escape_html_text(name)}</p>'
            f'<p class="comment-body">'
            f'{escape_html_text(comment.body)}</p>'
            f'{edited}</li>')
    parts.append("</ol>")
    return "\n".join(parts)


class GistCommentStore:
    """The S-123 comment machinery over one GistStore."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        data_root: Path,
        accounts: AccountStore,
        gists: GistStore | None = None,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._gists = gists or GistStore(
            conn, data_root, accounts, audit=audit,
            time_fn=time_fn)
        self._audit = audit
        self._now = time_fn

    # -- the one body law, reused ---------------------------

    def _validate_body(self, body: object) -> str:
        try:
            return _validate_comment_body(body)
        except IssueError as exc:
            raise GistError(exc.reason, str(exc)) from None

    # -- internals -------------------------------------------

    def _comment_by_id(self, comment_id: object) -> GistComment | None:
        if not isinstance(comment_id, int) or isinstance(comment_id, bool):
            return None
        row = self._conn.execute(
            "SELECT * FROM gist_comments WHERE id = ?",
            (comment_id,)).fetchone()
        return _row_to_comment(row) if row else None

    def _get_on_gist(self, viewer: User | None, gist_id: object,
                     comment_id: object) -> GistComment:
        gist = self._gists.get_gist(viewer, gist_id)
        comment = self._comment_by_id(comment_id)
        if comment is None or comment.gist_id != gist.id:
            raise GistError("comment_not_found", "No such comment.")
        return comment

    # -- create ------------------------------------------------

    def add_comment(self, actor: User | None, gist_id: object,
                    body: object) -> GistComment:
        """Comment on a gist: a signed-in act on a gist
        the actor can reach by its link (S-278's read
        law, public and secret alike)."""
        if actor is None:
            raise GistError(
                "permission_denied",
                "Only a signed-in user can comment on a gist.")
        gist = self._gists.get_gist(actor, gist_id)
        text = self._validate_body(body)
        now = int(self._now())
        with self._conn:  # commits before the answer
            cur = self._conn.execute(
                "INSERT INTO gist_comments (gist_id, author_id, body,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (gist.id, actor.id, text, now, now))
        comment = self._comment_by_id(int(cur.lastrowid))
        assert comment is not None
        return comment

    # -- read ----------------------------------------------------

    def list_comments(self, viewer: User | None,
                      gist_id: object) -> list[GistComment]:
        """The live conversation in order, tombstones
        skipped (S-123): any viewer the gist's own read
        door admits, signed in or not."""
        gist = self._gists.get_gist(viewer, gist_id)
        rows = self._conn.execute(
            "SELECT * FROM gist_comments WHERE gist_id = ?"
            " AND deleted_at IS NULL ORDER BY id",
            (gist.id,)).fetchall()
        return [_row_to_comment(r) for r in rows]

    def get_comment(self, viewer: User | None, gist_id: object,
                    comment_id: object) -> GistComment:
        """One comment, tombstones included (a reader who
        follows a link to a deleted comment is told it was
        deleted, not that it never existed -- unless the
        gist itself does not stand for them)."""
        return self._get_on_gist(viewer, gist_id, comment_id)

    def edits_for(self, viewer: User | None, gist_id: object,
                  comment_id: object) -> list[GistCommentEdit]:
        """The visible edit history (S-123): every previous
        body, in the order the edits landed."""
        comment = self._get_on_gist(viewer, gist_id, comment_id)
        rows = self._conn.execute(
            "SELECT * FROM gist_comment_edits WHERE comment_id = ?"
            " ORDER BY id", (comment.id,)).fetchall()
        return [GistCommentEdit(comment_id=r["comment_id"],
                                editor_id=r["editor_id"],
                                previous_body=r["previous_body"],
                                edited_at=r["edited_at"]) for r in rows]

    def comment_count(self, viewer: User | None,
                      gist_id: object) -> int:
        """Live comments on a gist, counted at read time
        over the standing rows, tombstones excluded."""
        gist = self._gists.get_gist(viewer, gist_id)
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM gist_comments"
            " WHERE gist_id = ? AND deleted_at IS NULL",
            (gist.id,)).fetchone()
        return int(row["n"])

    # -- edit ------------------------------------------------------

    def edit_comment(self, actor: User | None, gist_id: object,
                     comment_id: object, body: object) -> GistComment:
        """Edit a comment: the author's alone (moderators
        delete, they do not put words in another person's
        mouth); the previous body is recorded first, in
        the same transaction."""
        if actor is None:
            raise GistError(
                "permission_denied",
                "Only a signed-in user can edit a comment.")
        comment = self._get_on_gist(actor, gist_id, comment_id)
        if comment.is_deleted:
            raise GistError("comment_not_found", "No such comment.")
        if actor.id != comment.author_id:
            raise GistError(
                "permission_denied",
                "Only the author can edit this comment.")
        text = self._validate_body(body)
        now = int(self._now())
        with self._conn:  # history and new body land together
            self._conn.execute(
                "INSERT INTO gist_comment_edits (comment_id, editor_id,"
                " previous_body, edited_at) VALUES (?, ?, ?, ?)",
                (comment.id, actor.id, comment.body, now))
            self._conn.execute(
                "UPDATE gist_comments SET body = ?, updated_at = ?,"
                " edited_at = ? WHERE id = ?",
                (text, now, now, comment.id))
        updated = self._comment_by_id(comment.id)
        assert updated is not None
        return updated

    # -- delete ------------------------------------------------------

    def delete_comment(self, actor: User | None, gist_id: object,
                       comment_id: object) -> GistComment:
        """Delete a comment: a tombstone, by its author or
        by a moderator -- the gist's owner or a site admin,
        the hands that may change the gist itself."""
        if actor is None:
            raise GistError(
                "permission_denied",
                "Only a signed-in user can delete a comment.")
        comment = self._get_on_gist(actor, gist_id, comment_id)
        if comment.is_deleted:
            raise GistError("comment_not_found", "No such comment.")
        gist = self._gists.get_gist(actor, gist_id)
        if actor.id != comment.author_id and not (
                actor.id == gist.owner_id or actor.is_admin):
            raise GistError(
                "permission_denied",
                "Only the author, the gist's owner, or a site "
                "admin can delete this comment.")
        now = int(self._now())
        with self._conn:  # tombstone commits before the answer
            self._conn.execute(
                "UPDATE gist_comments SET body = '', updated_at = ?,"
                " deleted_at = ?, deleted_by = ? WHERE id = ?",
                (now, now, actor.id, comment.id))
        deleted = self._comment_by_id(comment.id)
        assert deleted is not None
        return deleted
