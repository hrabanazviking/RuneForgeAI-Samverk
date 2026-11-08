"""Notification reasons (S-223).

Part XI's reason vocabulary, made canonical: every
notification carries one of seven reasons -- `mention`,
`assign`, `review-requested`, `author`, `comment`,
`state-change`, `subscribed` -- stored on the row at
creation and shown, in plain words, with every
notification wherever it is rendered. Before this
slice the vocabulary lived only inside S-165's review
store (which stores `review-requested` and `author`
on its own rows, in this slice's words); there was no
one place that named the seven, judged a reason, or
held a notification that was not a review act. This
module is that place, under four laws:

- **The seven reasons are the whole vocabulary.**
  `NOTIFICATION_REASONS` names them in roadmap order,
  each with the plain words it is shown under.
  `validate_reason` is the only door: anything else
  -- an unknown word, an empty string, a non-string,
  even S-165's family-internal `review-dismissed`,
  which is not one of the seven -- is refused with
  `reason_invalid` naming the honest set, and a
  refusal stores nothing.
- **The reason is stored, never derived at read
  time.** A notification row carries the reason it
  was created under, so a later change to any
  caller's habits can never rewrite why an older
  notification reached its recipient. Reads return
  the stored value unchanged.
- **Shown with every notification.** The dataclass's
  `words` and both render functions say the reason's
  plain words outright -- meaning never rides on an
  icon or a colour alone -- and every value passes
  S-010's escaping seam.
- **An inbox belongs to its recipient.** Listing,
  counting and marking read all take the recipient
  themself; marking read is owner-scoped in the
  query itself, so one account can never mark
  another's notification read. Creating a
  notification needs a real recipient account
  (`no_such_user` otherwise); the actor may be
  absent (a system act) but is never invented.

One migration: 87 creates `notifications`. No new
taxonomy event: creating a notification is the
delivery of a mutation already witnessed under its
own verb (as S-165's store and S-221's store record
nothing of their own); 127 events stand.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .escaping import escape_html_text

__all__ = [
    "NOTIFICATION_REASONS", "Notification", "NotificationError",
    "NotificationStore", "reason_words", "render_notification",
    "render_notifications", "validate_reason",
]

# The seven reasons, in roadmap order: stored value ->
# the plain words it is shown under. Insertion order is
# the display order everywhere.
NOTIFICATION_REASONS: dict[str, str] = {
    "mention": "you were mentioned",
    "assign": "you were assigned",
    "review-requested": "your review was requested",
    "author": "you are the author",
    "comment": "there is a new comment",
    "state-change": "the state changed",
    "subscribed": "you are subscribed",
}


class NotificationError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def validate_reason(reason: object) -> str:
    """Pure: the stored reason for *reason*, or a
    refusal naming the honest set of seven."""
    if not isinstance(reason, str) or reason not in NOTIFICATION_REASONS:
        raise NotificationError(
            "reason_invalid",
            "Notification reasons are: "
            + ", ".join(NOTIFICATION_REASONS) + ".")
    return reason


def reason_words(reason: object) -> str:
    """Pure: the plain words a stored reason is shown
    under. Judged through the same door as creation,
    so an unknown reason is refused, never rendered."""
    return NOTIFICATION_REASONS[validate_reason(reason)]


@dataclass(frozen=True)
class Notification:
    id: int
    recipient_id: int
    recipient: str       # display case; '' when unknown
    actor_id: int | None
    actor: str           # display case; '' when none/unknown
    reason: str          # one of the seven, stored
    verb: str            # the witnessed act, carried as data
    target_kind: str
    target_id: str
    detail: dict
    created_at: int
    read_at: int | None

    @property
    def unread(self) -> bool:
        return self.read_at is None

    @property
    def reason_words(self) -> str:
        return NOTIFICATION_REASONS.get(self.reason, self.reason)

    @property
    def words(self) -> str:
        """The notification said in plain words -- who
        acted, on what, and the reason it reached this
        recipient, said outright."""
        who = self.actor or "Someone"
        where = self.target_id or self.target_kind
        return (f"{who} acted on {where} "
                f"(reason: {self.reason_words}).")


class NotificationStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        accounts: AccountStore,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._now = time_fn

    # -- creation -------------------------------------------
    def notify(self, recipient: User | None, actor: User | None,
               reason: object, verb: str = "",
               target_kind: str = "", target_id: str = "",
               detail: dict | None = None) -> Notification:
        """Store one notification for *recipient* under
        *reason* -- one of the seven, judged at the door.
        The reason lands on the row in the same commit
        as the notification itself."""
        stored_reason = validate_reason(reason)
        if recipient is None or \
                self._accounts.get_by_id(recipient.id) is None:
            raise NotificationError(
                "no_such_user", "No such account.")
        now = int(self._now())
        with self._conn:  # commits before the answer
            cur = self._conn.execute(
                "INSERT INTO notifications (recipient_id, actor_id,"
                " reason, verb, target_kind, target_id, detail_json,"
                " created_at, read_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                (recipient.id,
                 actor.id if actor is not None else None,
                 stored_reason, str(verb), str(target_kind),
                 str(target_id),
                 json.dumps(detail or {}, sort_keys=True), now))
        row = self._conn.execute(
            "SELECT * FROM notifications WHERE id = ?",
            (int(cur.lastrowid),)).fetchone()
        return self._to_notification(row)

    # -- reads ------------------------------------------------
    def list_for_recipient(self, user: User | None, *,
                           reason: object = None,
                           unread_only: bool = False,
                           limit: int = 100) -> list[Notification]:
        """The recipient's own notifications, oldest
        first, optionally filtered to one reason (judged
        through the same door -- an unknown filter is
        refused, never silently empty). An anonymous
        caller has no inbox at all."""
        if user is None:
            raise NotificationError(
                "authentication_required",
                "Sign in to see your notifications.")
        sql = "SELECT * FROM notifications WHERE recipient_id = ?"
        params: list = [user.id]
        if reason is not None:
            sql += " AND reason = ?"
            params.append(validate_reason(reason))
        if unread_only:
            sql += " AND read_at IS NULL"
        clamped = max(1, min(int(limit), 500))
        sql += " ORDER BY id LIMIT ?"
        params.append(clamped)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._to_notification(r) for r in rows]

    def unread_count(self, user: User | None) -> int:
        if user is None:
            raise NotificationError(
                "authentication_required",
                "Sign in to see your notifications.")
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM notifications"
            " WHERE recipient_id = ? AND read_at IS NULL",
            (user.id,)).fetchone()
        return int(row["n"])

    # -- marking read ------------------------------------------
    def mark_read(self, user: User | None, notification_id: int) -> bool:
        """Owner-only in the query itself: True exactly
        when this call marked the recipient's own unread
        notification read."""
        if user is None:
            raise NotificationError(
                "authentication_required",
                "Sign in to see your notifications.")
        with self._conn:
            cur = self._conn.execute(
                "UPDATE notifications SET read_at = ?"
                " WHERE id = ? AND recipient_id = ?"
                " AND read_at IS NULL",
                (int(self._now()), int(notification_id), user.id))
        return cur.rowcount > 0

    def mark_all_read(self, user: User | None) -> int:
        if user is None:
            raise NotificationError(
                "authentication_required",
                "Sign in to see your notifications.")
        with self._conn:
            cur = self._conn.execute(
                "UPDATE notifications SET read_at = ?"
                " WHERE recipient_id = ? AND read_at IS NULL",
                (int(self._now()), user.id))
        return int(cur.rowcount)

    # -- internals ----------------------------------------------
    def _to_notification(self, row: sqlite3.Row) -> Notification:
        try:
            detail = json.loads(row["detail_json"] or "{}")
        except ValueError:
            detail = {}
        recipient = self._accounts.get_by_id(int(row["recipient_id"]))
        actor = (self._accounts.get_by_id(int(row["actor_id"]))
                 if row["actor_id"] else None)
        return Notification(
            id=int(row["id"]), recipient_id=int(row["recipient_id"]),
            recipient=recipient.username if recipient else "",
            actor_id=row["actor_id"],
            actor=actor.username if actor else "",
            reason=row["reason"], verb=row["verb"],
            target_kind=row["target_kind"],
            target_id=row["target_id"],
            detail=detail if isinstance(detail, dict) else {},
            created_at=int(row["created_at"]), read_at=row["read_at"])


def render_notification(notification: Notification) -> str:
    """One notification, in plain words, its stored
    reason said outright."""
    return (
        '<li class="notification">'
        f"{escape_html_text(notification.words)}</li>")


def render_notifications(rows) -> str:
    """A recipient's notifications in plain words --
    each one's actor, target, and stored reason said
    outright. Never a colour alone; every value
    escapes through S-010."""
    rows = list(rows)
    if not rows:
        return ('<p class="notifications">No notifications yet. '
                "When you are mentioned, assigned, asked for a "
                "review, or activity lands on something you "
                "wrote, commented on, or subscribed to, it will "
                "be said here -- with the reason it reached "
                "you.</p>")
    items = "".join(render_notification(r) for r in rows)
    return f'<ul class="notifications">{items}</ul>'
