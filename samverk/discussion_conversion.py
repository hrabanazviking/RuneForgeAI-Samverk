"""Issue <-> discussion conversion (S-285).

Roadmap S-285: Issue <-> discussion conversion (if
in) -- converts with a forwarding note both ways,
never silently. S-282 verdicted conversion IN
(docs/DISCUSSIONS_VERDICT.md), S-283 built the
discussion board (samverk/discussions.py) and
S-284 added answer marking, recording there that
conversion is this slice's road. This module is
the conversion store: it converts through the two
standing stores' own doors, under the verdict's
conversion invariant -- *conversion-is-exactly-
once-and-never-silent*:

- **Both ways, through the standing doors.** An
  issue becomes a discussion in a caller-named
  category of the same repository, and a discussion
  becomes an issue in the same repository. The
  source is read through its own store's door
  first (``IssueStore.get_issue`` /
  ``DiscussionStore.get_thread``), so a missing
  object, a pull-request number named as an issue,
  and an object in a repository the caller cannot
  read all answer exactly as they do at those
  doors -- ``issue_not_found`` /
  ``discussion_not_found``, private
  indistinguishable from missing. Every refusal
  this face raises is a ``ConversionError``; the
  doors' reasons are carried over verbatim.
- **Judged by S-190 on the owning repository.**
  The hands that may convert are the source's
  author or a holder of the ``write`` rung or
  above on the owning repository, judged pure by
  ``can_convert`` through the S-190 permission
  engine -- the same hands S-122/S-130 trust with
  an issue's edits and state, and S-283 trusts
  with a thread's close. A fellow reader, a
  stranger and the anonymous are refused
  ``permission_denied``. The new discussion is
  opened under its category's declared create
  rung (``decide_power``), judged on the
  converter: a reader-author may convert their
  own issue into a question or open-discussion
  category, never into an announcement.
- **The origin is preserved, never copied away.**
  Conversion creates the counterpart and links
  it; it never deletes, closes, edits or moves
  the source. The counterpart carries the
  source's title and body verbatim and keeps the
  source's author as its own author -- the
  converter is recorded on the link, not
  substituted as the voice. A converted question
  keeps its thread, its accepted-answer mark
  (S-284) and its whole timeline as the linked
  origin the new issue points back to, exactly
  as S-284 recorded; replies are never copied
  into the issue, and issue comments are never
  copied into the thread.
- **A forwarding note both ways, never silent.**
  Each conversion leaves a note on BOTH sides,
  written in the same transaction as the link
  itself: on a discussion the note is an event
  on the thread's one timeline
  (``converted_to_issue`` on the origin thread /
  ``converted_from_issue`` as the new thread's
  first event, said in words by S-283's timeline
  describer); on an issue the note is a comment
  by the converter in the issue's conversation,
  naming the counterpart it forwards to or from.
  The durable link itself is migration 114's
  ``discussion_conversions`` row, read back
  through ``conversion_for_issue`` /
  ``conversion_for_discussion`` and stated as a
  ``ForwardingNote`` through
  ``forwarding_note_for_issue`` /
  ``forwarding_note_for_discussion`` -- the
  S-133 forwarding seam's shape.
- **Exactly once.** One conversion per object,
  in either seat: a source that already stands
  on either side of a conversion row is refused
  ``already_converted``, naming the linked
  counterpart the first conversion made -- as
  S-137's conversion refuses its second. The
  refusal is judged before anything is created,
  and migration 114's ``UNIQUE (issue_id)`` /
  ``UNIQUE (discussion_id)`` are the backstop
  that holds the law under concurrency
  (research 30's own acceptance check): a racing
  second claim rolls back whole and is answered
  with the same refusal, read from the row that
  won.
- **Open sources only.** A closed issue is
  refused ``issue_closed`` and a closed thread
  ``discussion_closed`` -- reopen it first, as
  S-137's road states for issues. A locked
  thread may still convert: conversion is
  curation, not a reply, as S-284's marking is.
- **Numbers from the standing sequences.** The
  new issue claims the repository's next shared
  number through S-121's seam inside the
  conversion transaction; the new thread claims
  the next discussion number from
  ``discussion_counters`` by S-283's atomic
  upsert. A refused conversion claims nothing.
- **States said in words.** A conversion and its
  forwarding notes state themselves in plain
  words (``Conversion.words``,
  ``ForwardingNote.words`` and the renderers,
  S-010-escaped) -- never by colour alone.

What this slice does NOT build: no cross-
repository conversion (a conversion never leaves
its repository; moving an issue between
repositories is S-133's transfer), no conversion
of pull requests, and no un-conversion -- the
link is the record, and the two objects live
their own lives from it.

Storage is migration 114's
``discussion_conversions`` table (schema 113 ->
114), added to S-282's sanctioned discussion
tables in samverk/discussions_verdict.py, as
S-283's tables were. Conversion acts carry no
verb of their own in the frozen taxonomy
vocabulary -- the thread timeline, the issue
conversation and the link row are their
attributable record, as S-283/S-284 held for
discussion acts -- so no new taxonomy event:
133 stand (33 auth / 87 repo / 13 admin), proven
in the battery by an audit-count snapshot taken
across both conversion directions.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .discussions import (
    KIND_SPECS, Discussion, DiscussionError, DiscussionStore,
    decide_power)
from .escaping import escape_html_text
from .issue_comments import _validate_comment_body
from .issues import Issue, IssueError, IssueStore
from .permission_engine import PermissionEngine
from .repositories import Repository, RepositoryStore
from .team_permissions import role_covers

__all__ = [
    "DIRECTION_DISCUSSION_TO_ISSUE", "DIRECTION_ISSUE_TO_DISCUSSION",
    "Conversion", "ConversionError", "DiscussionConversionStore",
    "ForwardingNote", "can_convert", "conversion_to_dict",
    "render_conversion_banner", "render_forwarding_note",
]

DIRECTION_ISSUE_TO_DISCUSSION = "issue_to_discussion"
DIRECTION_DISCUSSION_TO_ISSUE = "discussion_to_issue"


class ConversionError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def can_convert(*, is_author: bool, role: str | None) -> bool:
    """Pure conversion judgement (S-285): the hands
    that may convert an issue or a discussion are
    its author's own, or a holder of the ``write``
    rung or above on the owning repository, judged
    through S-190. A reader, a stranger (no rung)
    and the anonymous hold no conversion."""
    return bool(is_author) or role_covers(role, "write")


@dataclass(frozen=True)
class Conversion:
    """One durable conversion link, both ways: the
    issue and the discussion it joins, the direction
    the conversion ran, who converted, and when."""
    id: int
    repo_id: int
    issue_id: int
    issue_number: int
    discussion_id: int
    discussion_number: int
    direction: str       # DIRECTION_*
    converted_by: int
    created_at: int

    @property
    def source_kind(self) -> str:
        return ("issue" if self.direction
                == DIRECTION_ISSUE_TO_DISCUSSION else "discussion")

    @property
    def target_kind(self) -> str:
        return ("discussion" if self.direction
                == DIRECTION_ISSUE_TO_DISCUSSION else "issue")

    @property
    def source_number(self) -> int:
        return (self.issue_number if self.direction
                == DIRECTION_ISSUE_TO_DISCUSSION
                else self.discussion_number)

    @property
    def target_number(self) -> int:
        return (self.discussion_number if self.direction
                == DIRECTION_ISSUE_TO_DISCUSSION
                else self.issue_number)

    @property
    def words(self) -> str:
        """The conversion in plain words -- never a
        colour alone."""
        return (f"This {self.source_kind} was converted to "
                f"{self.target_kind} #{self.target_number}")


@dataclass(frozen=True)
class ForwardingNote:
    """The note standing on one side of a conversion
    (S-133's shape): which object it stands on, which
    object it forwards to or from, who converted, and
    when. ``relation`` is 'to' on the converted-from
    side and 'from' on the converted-to side."""
    side_kind: str       # 'issue' | 'discussion'
    side_number: int
    other_kind: str      # 'issue' | 'discussion'
    other_number: int
    relation: str        # 'to' | 'from'
    converted_by: int
    created_at: int

    @property
    def words(self) -> str:
        """The note in plain words."""
        return (f"This {self.side_kind} was converted "
                f"{self.relation} {self.other_kind} "
                f"#{self.other_number}")


def conversion_to_dict(conversion: Conversion) -> dict:
    return {
        "id": conversion.id, "repo_id": conversion.repo_id,
        "issue_id": conversion.issue_id,
        "issue_number": conversion.issue_number,
        "discussion_id": conversion.discussion_id,
        "discussion_number": conversion.discussion_number,
        "direction": conversion.direction,
        "source_kind": conversion.source_kind,
        "source_number": conversion.source_number,
        "target_kind": conversion.target_kind,
        "target_number": conversion.target_number,
        "converted_by": conversion.converted_by,
        "created_at": conversion.created_at,
        "words": conversion.words,
    }


def render_forwarding_note(note: ForwardingNote) -> str:
    """One side's forwarding note as an HTML
    paragraph; every value passes S-010's escaping
    seam, and the meaning is in the words."""
    return ('<p class="forwarding-note">'
            + escape_html_text(note.words) + "</p>")


def render_conversion_banner(conversion: Conversion,
                             repo_full_name: str) -> str:
    """The conversion stated for a page banner: the
    repository, both addresses and the direction,
    in words, S-010-escaped."""
    text = (f"{repo_full_name}: issue "
            f"#{conversion.issue_number} and discussion "
            f"#{conversion.discussion_number} are linked -- "
            f"{conversion.words}.")
    return ('<p class="conversion-banner">'
            + escape_html_text(text) + "</p>")


def _row_to_conversion(row: sqlite3.Row) -> Conversion:
    return Conversion(
        id=row["id"], repo_id=row["repo_id"],
        issue_id=row["issue_id"], issue_number=row["issue_number"],
        discussion_id=row["discussion_id"],
        discussion_number=row["discussion_number"],
        direction=row["direction"],
        converted_by=row["converted_by"],
        created_at=row["created_at"])


class DiscussionConversionStore:
    """Issue <-> discussion conversion (S-285):
    both directions through the standing stores'
    doors, judged by S-190, exactly once, with a
    forwarding note on both sides and a durable
    link read back both ways."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        issues: IssueStore,
        board: DiscussionStore,
        audit: AuditLog | None = None,
        engine: PermissionEngine | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._issues = issues
        self._board = board
        self._audit = audit
        self._engine = engine or PermissionEngine(
            conn, accounts, audit=None, time_fn=time_fn)
        self._now = time_fn

    # -- the doors, translated to this face's one error --------

    def _get_issue(self, viewer: User | None, owner: object,
                   repo: object, number: object) -> Issue:
        try:
            return self._issues.get_issue(viewer, owner, repo, number)
        except IssueError as exc:
            raise ConversionError(exc.reason, str(exc)) from None

    def _get_thread(self, viewer: User | None, owner: object,
                    repo: object, number: object) -> Discussion:
        try:
            return self._board.get_thread(viewer, owner, repo, number)
        except DiscussionError as exc:
            raise ConversionError(exc.reason, str(exc)) from None

    def _repo(self, owner: object, repo: object) -> Repository:
        current = self._repos.get_repository(owner, repo)
        assert current is not None  # a door above proved it
        return current

    def _judge_hands(self, actor: User | None,
                     current: Repository,
                     author_id: int) -> None:
        """Signed-in + can_convert, or the refusal."""
        if actor is None:
            raise ConversionError(
                "permission_denied",
                "Only a signed-in user can convert.")
        role = self._engine.role_for(actor, current)
        if not can_convert(
                is_author=actor.id == author_id, role=role):
            raise ConversionError(
                "permission_denied",
                "Only the author or a repository writer can "
                "convert this.")

    # -- the link record ----------------------------------------

    def _by_issue_id(self, issue_id: int) -> Conversion | None:
        row = self._conn.execute(
            "SELECT * FROM discussion_conversions"
            " WHERE issue_id = ?", (issue_id,)).fetchone()
        return _row_to_conversion(row) if row else None

    def _by_discussion_id(
            self, discussion_id: int) -> Conversion | None:
        row = self._conn.execute(
            "SELECT * FROM discussion_conversions"
            " WHERE discussion_id = ?",
            (discussion_id,)).fetchone()
        return _row_to_conversion(row) if row else None

    def _by_id(self, row_id: int) -> Conversion | None:
        row = self._conn.execute(
            "SELECT * FROM discussion_conversions WHERE id = ?",
            (row_id,)).fetchone()
        return _row_to_conversion(row) if row else None

    @staticmethod
    def _already(existing: Conversion, source_kind: str) -> ConversionError:
        """The exactly-once refusal, naming the linked
        counterpart the first conversion made."""
        if source_kind == "issue":
            other = f"discussion #{existing.discussion_number}"
        else:
            other = f"issue #{existing.issue_number}"
        return ConversionError(
            "already_converted",
            f"This {source_kind} is already linked to {other} "
            "by a conversion; a conversion happens exactly once.")

    # -- standing-sequence claims (inside the caller's tx) ------

    def _next_discussion_number_tx(self, repo_id: int) -> int:
        row = self._conn.execute(
            "INSERT INTO discussion_counters (repo_id, last_number)"
            " VALUES (?, 1)"
            " ON CONFLICT (repo_id) DO UPDATE"
            " SET last_number = last_number + 1"
            " RETURNING last_number",
            (repo_id,)).fetchone()
        return int(row["last_number"])

    def _note_comment_tx(self, issue_id: int, author_id: int,
                         body: str, now: int) -> None:
        """The issue-side forwarding note: a comment in
        the issue's conversation, written inside the
        conversion transaction. The text is judged by
        S-123's own validator before it is stored."""
        text = _validate_comment_body(body)
        self._conn.execute(
            "INSERT INTO issue_comments (issue_id, author_id, body,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (issue_id, author_id, text, now, now))

    def _thread_event_tx(self, thread_id: int, actor_id: int,
                         kind: str, detail: str, now: int) -> None:
        """The discussion-side forwarding note: an event
        on the thread's one timeline, written inside
        the conversion transaction."""
        self._conn.execute(
            "INSERT INTO discussion_events"
            " (thread_id, actor_id, kind, detail, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (thread_id, actor_id, kind, detail, now))

    # -- issue -> discussion --------------------------------------

    def convert_issue_to_discussion(
            self, actor: User | None, owner: object, repo: object,
            number: object, category_id: object) -> Conversion:
        """Convert an open issue into a discussion in
        the named category of the same repository. The
        issue keeps its state, its conversation and its
        number; the new thread carries its title, body
        and author, and both sides gain a forwarding
        note and the durable link, in one transaction."""
        issue = self._get_issue(actor, owner, repo, number)
        current = self._repo(owner, repo)
        self._judge_hands(actor, current, issue.author_id)
        assert actor is not None
        if issue.state != "open":
            raise ConversionError(
                "issue_closed",
                "A closed issue cannot be converted; "
                "reopen it first.")
        existing = self._by_issue_id(issue.id)
        if existing is not None:
            raise self._already(existing, "issue")
        try:
            category = self._board.get_category(
                actor, owner, repo, category_id)
        except DiscussionError as exc:
            raise ConversionError(exc.reason, str(exc)) from None
        role = self._engine.role_for(actor, current)
        if not decide_power(category.kind, "create", role):
            raise ConversionError(
                "permission_denied",
                f"Opening a {KIND_SPECS[category.kind].title.lower()} "
                "thread needs a stronger repository role.")
        now = int(self._now())
        try:
            with self._conn:  # number, thread, event, link, note
                disc_number = self._next_discussion_number_tx(
                    current.id)
                cur = self._conn.execute(
                    "INSERT INTO discussion_threads"
                    " (repo_id, category_id, number, author_id,"
                    " title, body, state, pinned, locked,"
                    " created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, 'open', 0, 0, ?, ?)",
                    (current.id, category.id, disc_number,
                     issue.author_id, issue.title, issue.body,
                     now, now))
                thread_id = int(cur.lastrowid)
                self._thread_event_tx(
                    thread_id, actor.id, "converted_from_issue",
                    f"issue #{issue.number}", now)
                link = self._conn.execute(
                    "INSERT INTO discussion_conversions"
                    " (repo_id, issue_id, issue_number,"
                    " discussion_id, discussion_number, direction,"
                    " converted_by, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (current.id, issue.id, issue.number,
                     thread_id, disc_number,
                     DIRECTION_ISSUE_TO_DISCUSSION,
                     actor.id, now))
                self._note_comment_tx(
                    issue.id, actor.id,
                    f"This issue was converted to discussion "
                    f"#{disc_number}. The conversation continues "
                    "there; this issue stays as the linked origin.",
                    now)
        except sqlite3.IntegrityError:
            # The UNIQUE backstop: a racing conversion won.
            won = self._by_issue_id(issue.id)
            if won is not None:
                raise self._already(won, "issue") from None
            raise
        found = self._by_id(int(link.lastrowid))
        assert found is not None
        return found

    # -- discussion -> issue --------------------------------------

    def convert_discussion_to_issue(
            self, actor: User | None, owner: object, repo: object,
            number: object) -> Conversion:
        """Convert an open discussion into an issue in
        the same repository. The thread keeps its
        replies, its accepted-answer mark and its whole
        timeline as the linked origin; the new issue
        carries its title, body and author, claims the
        next shared number, and both sides gain a
        forwarding note and the durable link, in one
        transaction."""
        thread = self._get_thread(actor, owner, repo, number)
        current = self._repo(owner, repo)
        self._judge_hands(actor, current, thread.author_id)
        assert actor is not None
        if thread.state != "open":
            raise ConversionError(
                "discussion_closed",
                "A closed discussion cannot be converted; "
                "reopen it first.")
        existing = self._by_discussion_id(thread.id)
        if existing is not None:
            raise self._already(existing, "discussion")
        now = int(self._now())
        try:
            with self._conn:  # number, issue, link, event, note
                issue_number = self._issues._next_number_tx(
                    current.id)
                cur = self._conn.execute(
                    "INSERT INTO issues (repo_id, number, kind,"
                    " author_id, title, body, state,"
                    " created_at, updated_at)"
                    " VALUES (?, ?, 'issue', ?, ?, ?, 'open', ?, ?)",
                    (current.id, issue_number, thread.author_id,
                     thread.title, thread.body, now, now))
                issue_id = int(cur.lastrowid)
                link = self._conn.execute(
                    "INSERT INTO discussion_conversions"
                    " (repo_id, issue_id, issue_number,"
                    " discussion_id, discussion_number, direction,"
                    " converted_by, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (current.id, issue_id, issue_number,
                     thread.id, thread.number,
                     DIRECTION_DISCUSSION_TO_ISSUE,
                     actor.id, now))
                self._thread_event_tx(
                    thread.id, actor.id, "converted_to_issue",
                    f"issue #{issue_number}", now)
                self._note_comment_tx(
                    issue_id, actor.id,
                    f"This issue was converted from discussion "
                    f"#{thread.number}. The original discussion "
                    "-- its thread, timeline and any accepted "
                    "answer -- stays there as the linked origin.",
                    now)
        except sqlite3.IntegrityError:
            # The UNIQUE backstop: a racing conversion won.
            won = self._by_discussion_id(thread.id)
            if won is not None:
                raise self._already(won, "discussion") from None
            raise
        found = self._by_id(int(link.lastrowid))
        assert found is not None
        return found

    # -- reads: the link and the notes, both ways -----------------

    def conversion_for_issue(
            self, viewer: User | None, owner: object,
            repo: object, number: object) -> Conversion | None:
        """The conversion an issue stands on either side
        of, or None -- read through the issue itself, so
        a stranger to a private repository gets the
        uniform issue answer before any link is shown."""
        issue = self._get_issue(viewer, owner, repo, number)
        return self._by_issue_id(issue.id)

    def conversion_for_discussion(
            self, viewer: User | None, owner: object,
            repo: object, number: object) -> Conversion | None:
        """The conversion a discussion stands on either
        side of, or None -- read through the thread
        itself, so a private board answers
        discussion_not_found before any link is shown."""
        thread = self._get_thread(viewer, owner, repo, number)
        return self._by_discussion_id(thread.id)

    def forwarding_note_for_issue(
            self, viewer: User | None, owner: object,
            repo: object, number: object) -> ForwardingNote | None:
        """The forwarding note standing on an issue, or
        None when the issue was never converted."""
        conversion = self.conversion_for_issue(
            viewer, owner, repo, number)
        if conversion is None:
            return None
        if conversion.direction == DIRECTION_ISSUE_TO_DISCUSSION:
            return ForwardingNote(
                side_kind="issue",
                side_number=conversion.issue_number,
                other_kind="discussion",
                other_number=conversion.discussion_number,
                relation="to",
                converted_by=conversion.converted_by,
                created_at=conversion.created_at)
        return ForwardingNote(
            side_kind="issue",
            side_number=conversion.issue_number,
            other_kind="discussion",
            other_number=conversion.discussion_number,
            relation="from",
            converted_by=conversion.converted_by,
            created_at=conversion.created_at)

    def forwarding_note_for_discussion(
            self, viewer: User | None, owner: object,
            repo: object, number: object) -> ForwardingNote | None:
        """The forwarding note standing on a discussion,
        or None when the thread was never converted."""
        conversion = self.conversion_for_discussion(
            viewer, owner, repo, number)
        if conversion is None:
            return None
        if conversion.direction == DIRECTION_DISCUSSION_TO_ISSUE:
            return ForwardingNote(
                side_kind="discussion",
                side_number=conversion.discussion_number,
                other_kind="issue",
                other_number=conversion.issue_number,
                relation="to",
                converted_by=conversion.converted_by,
                created_at=conversion.created_at)
        return ForwardingNote(
            side_kind="discussion",
            side_number=conversion.discussion_number,
            other_kind="issue",
            other_number=conversion.issue_number,
            relation="from",
            converted_by=conversion.converted_by,
            created_at=conversion.created_at)
