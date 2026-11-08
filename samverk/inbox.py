"""Inbox (S-224).

Part XI's working surface over S-223's store: the
recipient's own unread list, with filters by reason
and by repository, mark done / mark saved, keyboard
triage, and an empty state that teaches the whole
model in one screen. S-223 stores the notification
and its reason; this module is how a person works
through what reached them, under five laws:

- **An inbox belongs to its recipient.** Every face
  takes the recipient themself and scopes by their
  account id -- in the query itself, as S-223's
  marking does -- so one account can never list,
  count, finish, or save another's notification,
  and an anonymous caller has no inbox at all
  (`authentication_required`). S-223's rows carry
  no repository scope of their own, so none is
  invented here: the repository a notification
  belongs to is derived from its stored target (see
  `repo_of`), never stored twice and never guessed
  from anywhere else.
- **Done and saved are distinct states, honestly
  modelled.** Done (`done_at`) is the only exit
  from the inbox: marking done also marks the
  notification read, because finished is read, and
  reopening restores it unread, as it was. Saved
  (`saved_at`) is an orthogonal flag -- a saved
  notification stays in the list until it is done,
  a done one keeps its saved flag, and neither
  state ever impersonates the other or S-223's
  `read_at`. Both live on one `inbox_triage` row
  per notification (migration 88); S-223's table
  is touched only to move `read_at` with done and
  reopen, through the same owner-scoped shape.
- **Filters are judged at the door.** The reason
  filter goes through S-223's `validate_reason`
  -- an unknown reason is refused `reason_invalid`,
  never silently empty -- and the repository
  filter must name one repository as
  `owner/name` (`repo_invalid` otherwise). The
  repository itself is derived purely:
  `detail["repo"]` when the delivery recorded one
  (S-223's own shape), else the first two segments
  of the target id (`volmarr/pub#1` belongs to
  `volmarr/pub`); a target that names no repository
  belongs to none and matches no repository filter.
- **Keyboard triage is data, not folklore.**
  `TRIAGE_KEYS` is a frozen registry in S-111's
  shape: every binding the inbox honours is named
  there with its action and plain words, none
  fires while typing, and no key repeats inside
  the inbox context. What a key *does* to an
  entry is the pure `apply_triage` over
  `TriageState`, and where the cursor lands is the
  pure `move_cursor` -- the client script and this
  store can never disagree about the model,
  because both read the same functions.
- **The empty state teaches the model in one
  screen.** `INBOX_LESSONS` names the four lessons
  -- what lands here and the seven reasons it can
  carry, the two filters, done versus saved, and
  the triage keys -- and the empty render is built
  from the lessons, the reason vocabulary, and
  the key registry themselves, so the teaching
  cannot drift from the law. A filtered list that
  matches nothing says so and names the way back;
  it never borrows the first-run teaching.

One migration: 88 creates `inbox_triage`. No new
taxonomy event: triage is a personal reading
state, like S-214's saved searches -- it mutates
no shared record, so it is not a witnessed act;
127 events stand.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .escaping import escape_html_text
from .notification_reasons import (
    NOTIFICATION_REASONS, Notification, NotificationError,
    validate_reason)

__all__ = [
    "INBOX_LESSONS", "TRIAGE_KEYS", "InboxCounts", "InboxEntry",
    "InboxError", "InboxStore", "TriageKey", "TriageState",
    "apply_triage", "decide_done", "decide_saved", "empty_state",
    "move_cursor", "render_inbox", "render_inbox_entry",
    "render_inbox_lessons", "repo_of", "triage_manifest",
    "validate_repo_filter",
]


class InboxError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


# -- the repository a notification belongs to ------------

def repo_of(target_kind: str = "", target_id: str = "",
            detail: dict | None = None) -> str:
    """Pure: the `owner/name` a notification belongs
    to, derived from what S-223 stored -- the
    delivery's recorded `detail["repo"]` when it is
    a repository name, else the first two segments
    of the target id with any `#number` tail cut.
    A target naming no repository yields ""."""
    if isinstance(detail, dict):
        recorded = detail.get("repo")
        if isinstance(recorded, str) and _repo_shape(recorded):
            return recorded
    parts = [p for p in str(target_id or "").split("/") if p]
    if len(parts) < 2:
        return ""
    name = parts[1].split("#", 1)[0].strip()
    owner = parts[0].strip()
    if not owner or not name:
        return ""
    return f"{owner}/{name}"


def _repo_shape(value: str) -> bool:
    parts = value.split("/")
    return (len(parts) == 2 and all(parts)
            and not any(c.isspace() for c in value))


def validate_repo_filter(repo: object) -> str:
    """Pure: the repository filter as stored shape,
    or a refusal -- a filter must name exactly one
    repository as `owner/name`."""
    if not isinstance(repo, str) or not _repo_shape(repo.strip()):
        raise InboxError(
            "repo_invalid",
            "Filter by one repository, named owner/name.")
    return repo.strip()


# -- triage state: the pure heart -------------------------

@dataclass(frozen=True)
class TriageState:
    """One entry's triage standing: S-223's read
    flag plus this slice's done and saved flags,
    kept distinct so no state impersonates another."""
    read: bool = False
    done: bool = False
    saved: bool = False


def decide_done(done: bool, want: bool) -> bool:
    """Pure: True when moving *done* to *want* is a
    real change worth storing."""
    return done != want


def decide_saved(saved: bool, want: bool) -> bool:
    """Pure: True when moving *saved* to *want* is a
    real change worth storing."""
    return saved != want


@dataclass(frozen=True)
class TriageKey:
    keys: str               # e.g. "j", "e", "Enter"
    action: str             # stable action name
    description: str        # plain words, taught verbatim
    context: str = "inbox"
    active_when_typing: bool = False


TRIAGE_KEYS: tuple[TriageKey, ...] = (
    TriageKey("j", "move_next",
              "Move to the next notification in the list."),
    TriageKey("k", "move_previous",
              "Move to the previous notification in the list."),
    TriageKey("Enter", "open_selected",
              "Open the selected notification; opening marks "
              "it read, and it stays in the inbox until done."),
    TriageKey("e", "mark_done",
              "Mark the selected notification done: it "
              "leaves the inbox, and done also means read."),
    TriageKey("s", "toggle_saved",
              "Save the selected notification, or unsave it "
              "if it is saved. Saved is a flag, not an exit: "
              "a saved notification stays until it is done."),
    TriageKey("u", "reopen",
              "Reopen the selected notification: it returns "
              "to the inbox unread, as it was before done."),
)

TRIAGE_ACTIONS = frozenset(k.action for k in TRIAGE_KEYS)


def _check_triage_registry() -> None:
    seen: set[str] = set()
    for k in TRIAGE_KEYS:
        if k.keys in seen:
            raise ValueError(f"duplicate triage key {k.keys!r}")
        seen.add(k.keys)
        if k.active_when_typing:
            raise ValueError(
                f"triage key {k.keys!r} would fire while "
                "typing -- S-111's baseline forbids it")


_check_triage_registry()


def triage_manifest() -> tuple[dict, ...]:
    """The bindings as plain data for the external
    client script -- the same registry, never a
    second list (S-111's manifest shape)."""
    return tuple(
        {"keys": k.keys, "action": k.action,
         "context": k.context,
         "active_when_typing": k.active_when_typing}
        for k in TRIAGE_KEYS)


def apply_triage(state: TriageState, action: object) -> TriageState:
    """Pure: the standing after *action*. Done sets
    done and read together; reopen clears both, so
    the entry returns exactly as it was; saving
    flips only the saved flag; opening sets only
    read. An unknown action is refused, never
    silently ignored."""
    if action == "mark_done":
        return TriageState(read=True, done=True, saved=state.saved)
    if action == "reopen":
        return TriageState(read=False, done=False, saved=state.saved)
    if action == "toggle_saved":
        return TriageState(read=state.read, done=state.done,
                           saved=not state.saved)
    if action == "open_selected":
        return TriageState(read=True, done=state.done,
                           saved=state.saved)
    if action in ("move_next", "move_previous"):
        return state
    raise InboxError(
        "triage_action_invalid",
        "Triage actions are: " + ", ".join(
            sorted(TRIAGE_ACTIONS)) + ".")


def move_cursor(index: int, total: int, action: object) -> int:
    """Pure: the selected position after a move
    action, clamped at both ends of a list of
    *total* entries; an empty list selects 0, and
    a non-move action leaves the cursor where it
    is."""
    if total <= 0:
        return 0
    current = max(0, min(int(index), total - 1))
    if action == "move_next":
        return min(current + 1, total - 1)
    if action == "move_previous":
        return max(current - 1, 0)
    return current


# -- the teaching empty state ------------------------------

INBOX_LESSONS: tuple[tuple[str, str], ...] = (
    ("What lands here",
     "Your inbox holds one row for every notification "
     "that reached you, each carrying the reason it "
     "reached you, said in plain words with the row."),
    ("Filter to what matters",
     "Filter the list by one reason, by one repository "
     "(named owner/name), or by both together, and ask "
     "for saved rows only when you want your kept set."),
    ("Done and saved are different",
     "Done is the exit: a done notification leaves the "
     "inbox, and done also means read. Saved is a flag "
     "for keeping: a saved notification stays in the "
     "inbox until it is done, and a done one can still "
     "be saved."),
    ("Triage from the keyboard",
     "Work the list without leaving the keys: move, "
     "open, mark done, save, and reopen, as the key "
     "table below says. No key fires while you type."),
)


@dataclass(frozen=True)
class InboxLesson:
    title: str
    body: str


def empty_state() -> tuple[InboxLesson, ...]:
    """The one-screen teaching, as data: the four
    lessons in order. The render is built from this,
    so the words a test reads are the words a person
    reads."""
    return tuple(InboxLesson(t, b) for t, b in INBOX_LESSONS)


# -- entries ------------------------------------------------

@dataclass(frozen=True)
class InboxEntry:
    notification: Notification
    repo: str            # owner/name, or "" when none
    done_at: int | None
    saved_at: int | None

    @property
    def id(self) -> int:
        return self.notification.id

    @property
    def reason(self) -> str:
        return self.notification.reason

    @property
    def unread(self) -> bool:
        return self.notification.unread and self.done_at is None

    @property
    def done(self) -> bool:
        return self.done_at is not None

    @property
    def saved(self) -> bool:
        return self.saved_at is not None

    @property
    def state(self) -> TriageState:
        return TriageState(read=not self.notification.unread,
                           done=self.done, saved=self.saved)

    @property
    def state_words(self) -> str:
        """The entry's standing in plain words --
        never a colour or an icon alone."""
        bits = []
        if self.done:
            bits.append("done")
        elif self.unread:
            bits.append("unread")
        else:
            bits.append("read")
        if self.saved:
            bits.append("saved")
        return ", ".join(bits)

    @property
    def words(self) -> str:
        """The entry said in plain words: S-223's
        words (actor, target, stored reason), its
        repository when it has one, and its triage
        standing."""
        text = self.notification.words
        if self.repo:
            text += f" Repository: {self.repo}."
        return text + f" ({self.state_words}.)"


@dataclass(frozen=True)
class InboxCounts:
    unread: int          # not read and not done
    saved: int           # saved and not done
    done: int            # done (kept, out of the list)


# -- the store ------------------------------------------------

class InboxStore:
    """The recipient's inbox over S-223's
    `notifications` (migration 87) plus this
    slice's `inbox_triage` (migration 88). Reads
    join the two; done and reopen move S-223's
    `read_at` with them; every write is
    owner-scoped and commits before the answer,
    like every house store."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        accounts: AccountStore,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._now = time_fn

    # -- guards -------------------------------------------
    def _require_user(self, user: User | None) -> User:
        if user is None:
            raise InboxError(
                "authentication_required",
                "Sign in to see your inbox.")
        return user

    def _judge_reason(self, reason: object) -> str:
        try:
            return validate_reason(reason)
        except NotificationError as exc:
            raise InboxError(exc.reason, str(exc)) from None

    # -- reads ----------------------------------------------
    def list_inbox(self, user: User | None, *,
                   reason: object = None,
                   repo: object = None,
                   saved_only: bool = False,
                   include_done: bool = False,
                   limit: int = 100) -> list[InboxEntry]:
        """*user*'s own inbox, newest first. The
        default list is the working list -- every
        notification that is not done, read ones
        included and flagged as read -- filtered by
        one reason and/or one repository when given,
        judged at the door. `saved_only` keeps the
        saved rows; `include_done` admits the done
        rows the default list has already let go."""
        owner = self._require_user(user)
        sql = ("SELECT n.*, t.done_at AS t_done_at,"
               " t.saved_at AS t_saved_at"
               " FROM notifications n"
               " LEFT JOIN inbox_triage t"
               " ON t.notification_id = n.id"
               " WHERE n.recipient_id = ?")
        params: list = [owner.id]
        if reason is not None:
            sql += " AND n.reason = ?"
            params.append(self._judge_reason(reason))
        if not include_done:
            sql += " AND t.done_at IS NULL"
        sql += " ORDER BY n.id DESC"
        entries = [self._to_entry(r) for r in
                   self._conn.execute(sql, params).fetchall()]
        if repo is not None:
            wanted = validate_repo_filter(repo)
            entries = [e for e in entries if e.repo == wanted]
        if saved_only:
            entries = [e for e in entries if e.saved]
        clamped = max(1, min(int(limit), 500))
        return entries[:clamped]

    def get_entry(self, user: User | None,
                  notification_id: int) -> InboxEntry | None:
        """One of *user*'s own entries, or None --
        another recipient's notification answers
        None here, never a leak that it exists."""
        owner = self._require_user(user)
        row = self._conn.execute(
            "SELECT n.*, t.done_at AS t_done_at,"
            " t.saved_at AS t_saved_at"
            " FROM notifications n"
            " LEFT JOIN inbox_triage t"
            " ON t.notification_id = n.id"
            " WHERE n.id = ? AND n.recipient_id = ?",
            (int(notification_id), owner.id)).fetchone()
        return self._to_entry(row) if row is not None else None

    def counts(self, user: User | None) -> InboxCounts:
        owner = self._require_user(user)
        row = self._conn.execute(
            "SELECT"
            " SUM(CASE WHEN n.read_at IS NULL"
            " AND t.done_at IS NULL THEN 1 ELSE 0 END)"
            " AS unread,"
            " SUM(CASE WHEN t.saved_at IS NOT NULL"
            " AND t.done_at IS NULL THEN 1 ELSE 0 END)"
            " AS saved,"
            " SUM(CASE WHEN t.done_at IS NOT NULL"
            " THEN 1 ELSE 0 END) AS done"
            " FROM notifications n"
            " LEFT JOIN inbox_triage t"
            " ON t.notification_id = n.id"
            " WHERE n.recipient_id = ?",
            (owner.id,)).fetchone()
        return InboxCounts(unread=int(row["unread"] or 0),
                           saved=int(row["saved"] or 0),
                           done=int(row["done"] or 0))

    def unread_count(self, user: User | None) -> int:
        return self.counts(user).unread

    def repos(self, user: User | None) -> tuple[str, ...]:
        """The repositories named by *user*'s working
        list, in name order -- the honest set the
        repository filter can be picked from."""
        owner = self._require_user(user)
        found = {e.repo for e in self.list_inbox(owner, limit=500)
                 if e.repo}
        return tuple(sorted(found))

    # -- triage writes ---------------------------------------
    def mark_done(self, user: User | None,
                  notification_id: int) -> bool:
        """Owner-only in the lookups themselves:
        True exactly when this call finished the
        recipient's own not-done notification. Done
        moves `read_at` with it (finished is read)
        and keeps any saved flag standing."""
        owner = self._require_user(user)
        entry = self.get_entry(owner, notification_id)
        if entry is None or not decide_done(entry.done, True):
            return False
        now = int(self._now())
        with self._conn:  # commits before the answer
            self._upsert_triage(entry.id, done_at=now,
                                saved_at=entry.saved_at)
            self._conn.execute(
                "UPDATE notifications SET read_at = ?"
                " WHERE id = ? AND recipient_id = ?"
                " AND read_at IS NULL",
                (now, entry.id, owner.id))
        return True

    def reopen(self, user: User | None,
               notification_id: int) -> bool:
        """Undo done: the entry returns to the inbox
        unread, as it was; its saved flag stands.
        True exactly when this call reopened one of
        the recipient's own done notifications."""
        owner = self._require_user(user)
        entry = self.get_entry(owner, notification_id)
        if entry is None or not decide_done(entry.done, False):
            return False
        with self._conn:
            self._upsert_triage(entry.id, done_at=None,
                                saved_at=entry.saved_at)
            self._conn.execute(
                "UPDATE notifications SET read_at = NULL"
                " WHERE id = ? AND recipient_id = ?",
                (entry.id, owner.id))
        return True

    def set_saved(self, user: User | None, notification_id: int,
                  want: bool) -> bool:
        """Set the saved flag to *want*: True exactly
        when the flag moved. Saving never touches
        read or done; it works on done rows too, so
        a finished notification can still be kept."""
        owner = self._require_user(user)
        entry = self.get_entry(owner, notification_id)
        if entry is None or not decide_saved(entry.saved, want):
            return False
        with self._conn:
            self._upsert_triage(
                entry.id, done_at=entry.done_at,
                saved_at=int(self._now()) if want else None)
        return True

    def toggle_saved(self, user: User | None,
                     notification_id: int) -> bool:
        """The `s` key as a store act: flip the saved
        flag. True exactly when one of the
        recipient's own notifications was flipped."""
        owner = self._require_user(user)
        entry = self.get_entry(owner, notification_id)
        if entry is None:
            return False
        return self.set_saved(owner, entry.id, not entry.saved)

    # -- internals --------------------------------------------
    def _upsert_triage(self, notification_id: int,
                       done_at: int | None,
                       saved_at: int | None) -> None:
        self._conn.execute(
            "INSERT INTO inbox_triage (notification_id,"
            " done_at, saved_at) VALUES (?, ?, ?)"
            " ON CONFLICT(notification_id) DO UPDATE SET"
            " done_at = excluded.done_at,"
            " saved_at = excluded.saved_at",
            (notification_id, done_at, saved_at))

    def _to_entry(self, row: sqlite3.Row) -> InboxEntry:
        try:
            detail = json.loads(row["detail_json"] or "{}")
        except ValueError:
            detail = {}
        if not isinstance(detail, dict):
            detail = {}
        recipient = self._accounts.get_by_id(int(row["recipient_id"]))
        actor = (self._accounts.get_by_id(int(row["actor_id"]))
                 if row["actor_id"] else None)
        notification = Notification(
            id=int(row["id"]), recipient_id=int(row["recipient_id"]),
            recipient=recipient.username if recipient else "",
            actor_id=row["actor_id"],
            actor=actor.username if actor else "",
            reason=row["reason"], verb=row["verb"],
            target_kind=row["target_kind"],
            target_id=row["target_id"], detail=detail,
            created_at=int(row["created_at"]),
            read_at=row["read_at"])
        return InboxEntry(
            notification=notification,
            repo=repo_of(row["target_kind"], row["target_id"],
                         detail),
            done_at=row["t_done_at"], saved_at=row["t_saved_at"])


# -- renders ---------------------------------------------------

def render_inbox_entry(entry: InboxEntry) -> str:
    """One inbox row, in plain words, its stored
    reason, repository, and standing said outright.
    Every value escapes through S-010."""
    return ('<li class="inbox-entry">'
            f"{escape_html_text(entry.words)}</li>")


def render_inbox_lessons() -> str:
    """The teaching empty state, rendered from the
    lessons, the seven reasons, and the triage
    registry themselves -- one screen that teaches
    the whole model."""
    parts = ['<div class="inbox-empty">',
             "<h2>Your inbox is empty</h2>",
             "<p>Nothing here needs you right now. "
             "When something does, it will be said "
             "here in plain words, with the reason it "
             "reached you:</p>",
             '<ul class="inbox-reasons">']
    for reason, words in NOTIFICATION_REASONS.items():
        parts.append(
            f"<li><strong>{escape_html_text(reason)}</strong>"
            f" -- {escape_html_text(words)}</li>")
    parts.append("</ul>")
    for lesson in empty_state():
        parts.append(
            f"<h3>{escape_html_text(lesson.title)}</h3>"
            f"<p>{escape_html_text(lesson.body)}</p>")
    parts.append('<table class="inbox-keys"><thead><tr>'
                 "<th>Keys</th><th>What it does</th></tr>"
                 "</thead><tbody>")
    for key in TRIAGE_KEYS:
        parts.append(
            f"<tr><td><kbd>{escape_html_text(key.keys)}</kbd>"
            f"</td><td>{escape_html_text(key.description)}"
            "</td></tr>")
    parts.append("</tbody></table></div>")
    return "".join(parts)


def render_inbox(entries, *, filtered: bool = False) -> str:
    """A recipient's inbox in plain words. An
    unfiltered empty inbox renders the one-screen
    teaching; a filtered list that matches nothing
    says so and names the way back, briefly."""
    rows = list(entries)
    if not rows:
        if filtered:
            return ('<p class="inbox">No notifications '
                    "match this filter. Clear the reason "
                    "or repository filter to see the "
                    "whole inbox.</p>")
        return render_inbox_lessons()
    items = "".join(render_inbox_entry(e) for e in rows)
    return f'<ul class="inbox">{items}</ul>'
