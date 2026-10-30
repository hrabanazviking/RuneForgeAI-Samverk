"""Comment moderation (S-138).

Hiding and removing abusive comments on issues — the
moderator's hand, exercised in the open.

- **Moderators are repository admins** (S-054's
  `can_admin`: the owner, or a site admin). No one else
  moderates: not the comment's author (their roads are
  S-123's edit and delete), not a mere writer.
- **Hide, don't erase.** Hiding stamps the comment
  (`hidden_at` / `hidden_by` / a reason in the plain
  vocabulary below) and S-123's list seam then keeps it
  out of the conversation for everyone except its
  author and the moderators. The body is untouched —
  hiding governs who sees a comment, never what was
  said — and `unhide_comment` restores it whole.
- **Removal is the tombstone, struck as moderation.**
  `remove_comment` deletes through S-123's tombstone
  law (body cleared, row kept) but is a distinct act
  from an author's own delete: it requires a reason
  and is audited under its own event, so the record
  never confuses a moderator's removal with an author
  changing their mind.
- **A reason is required, in words.** `spam`, `abuse`,
  `off_topic`, `outdated` — anything else is refused
  `reason_invalid`, and the reason is said in words
  wherever the act is shown (the hidden notice, the
  timeline), never as a colour or an icon alone.
- **No silent edits of the record.** Every real act is
  audited (`repo.issue.comment_hide` / `.unhide` /
  `.remove` — taxonomy append-only +3, 90 events) and
  S-131's timeline learned all three from that same
  audit record, so an issue's stream says who hid or
  removed a comment and why. Retries are quiet no-ops:
  hiding a hidden comment or unhiding a visible one
  changes nothing and writes no second event. A
  deleted comment can be neither hidden nor removed
  again (`comment_not_found`).
- **Permissions ride the repository's.** A stranger to
  a private repository gets the uniform
  `issue_not_found` through S-123's read seam, exactly
  as for the issue itself.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .issue_comments import Comment, IssueCommentStore
from .issues import IssueError
from .permissions import can_admin
from .repositories import RepositoryStore

MODERATION_REASONS = frozenset(
    {"spam", "abuse", "off_topic", "outdated"})
REASON_WORDS = {
    "spam": "spam",
    "abuse": "abusive",
    "off_topic": "off-topic",
    "outdated": "outdated",
}


def reason_words(reason: str) -> str:
    return REASON_WORDS.get(reason, reason)


def render_comment(comment: Comment) -> str:
    """A comment as its surface line: a deleted comment
    says it was deleted, a hidden one says a moderator
    hid it and why, a live one shows its body — every
    value through S-010, meaning always in words."""
    if comment.is_deleted:
        return ('<p class="comment comment-deleted">'
                "This comment was deleted.</p>")
    if comment.is_hidden:
        return ('<p class="comment comment-hidden">'
                "This comment was hidden by a moderator as "
                + escape_html_text(reason_words(comment.hide_reason))
                + ".</p>")
    return ('<p class="comment">'
            + escape_html_text(comment.body) + "</p>")


class ModerationStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        comments: IssueCommentStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._comments = comments
        self._audit = audit
        self._now = time_fn

    # -- the acts -----------------------------------------------------
    def hide_comment(self, actor: User, owner: object, repo: object,
                     number: object, comment_id: int, reason: object,
                     *, source_ip: str | None = None) -> Comment:
        comment = self._moderated_comment(actor, owner, repo, number,
                                          comment_id)
        checked = self._validate_reason(reason)
        if comment.is_hidden:
            return comment  # a retry, not a second event
        now = int(self._now())
        with self._conn:  # commits before the answer
            self._conn.execute(
                "UPDATE issue_comments SET hidden_at = ?, hidden_by = ?,"
                " hide_reason = ?, updated_at = ? WHERE id = ?",
                (now, actor.id, checked, now, comment.id))
        updated = self._comments.get_comment(
            actor, owner, repo, number, comment_id)
        self._emit(actor, "repo.issue.comment_hide", owner, repo,
                   comment.number,
                   {"number": comment.number, "comment_id": comment.id,
                    "reason": checked}, source_ip)
        return updated

    def unhide_comment(self, actor: User, owner: object, repo: object,
                       number: object, comment_id: int,
                       *, source_ip: str | None = None) -> Comment:
        comment = self._moderated_comment(actor, owner, repo, number,
                                          comment_id)
        if not comment.is_hidden:
            return comment  # a retry, not a second event
        now = int(self._now())
        with self._conn:  # commits before the answer
            self._conn.execute(
                "UPDATE issue_comments SET hidden_at = NULL,"
                " hidden_by = NULL, hide_reason = '', updated_at = ?"
                " WHERE id = ?", (now, comment.id))
        updated = self._comments.get_comment(
            actor, owner, repo, number, comment_id)
        self._emit(actor, "repo.issue.comment_unhide", owner, repo,
                   comment.number,
                   {"number": comment.number, "comment_id": comment.id},
                   source_ip)
        return updated

    def remove_comment(self, actor: User, owner: object, repo: object,
                       number: object, comment_id: int, reason: object,
                       *, source_ip: str | None = None) -> Comment:
        comment = self._moderated_comment(actor, owner, repo, number,
                                          comment_id)
        checked = self._validate_reason(reason)
        now = int(self._now())
        with self._conn:  # S-123's tombstone, struck as moderation
            self._conn.execute(
                "UPDATE issue_comments SET body = '', updated_at = ?,"
                " deleted_at = ?, deleted_by = ? WHERE id = ?",
                (now, now, actor.id, comment.id))
        removed = self._comments.get_comment(
            actor, owner, repo, number, comment_id)
        self._emit(actor, "repo.issue.comment_remove", owner, repo,
                   comment.number,
                   {"number": comment.number, "comment_id": comment.id,
                    "reason": checked}, source_ip)
        return removed

    # -- internals ------------------------------------------------------
    def _moderated_comment(self, actor: User, owner: object,
                           repo: object, number: object,
                           comment_id: int) -> Comment:
        """The comment under the moderator gate: readable
        (S-123's seam, uniform answers), not deleted, and
        the actor a repository admin."""
        comment = self._comments.get_comment(
            actor, owner, repo, number, comment_id)
        if comment.is_deleted:
            raise IssueError("comment_not_found", "No such comment.")
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_admin(actor, current):
            raise IssueError(
                "permission_denied",
                "Only a repository moderator can do that.")
        return comment

    @staticmethod
    def _validate_reason(reason: object) -> str:
        if reason not in MODERATION_REASONS:
            raise IssueError(
                "reason_invalid",
                "A moderation reason is 'spam', 'abuse', "
                "'off_topic', or 'outdated'.")
        return str(reason)

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
