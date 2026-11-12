"""Discussion polls -- the published refusal (S-286).

Roadmap S-286: Polls (if in) -- discussion polls
with honest counts and close dates; otherwise
recorded as refused with reasons. S-282 verdicted
polls DEFERRED (docs/DISCUSSIONS_VERDICT.md,
samverk/discussions_verdict.py): no village need
for thread polls has been measured, and polls
carry research 30's honesty warning -- fraud-
resistant rules that do not pretend to establish
voter identity beyond account scope. So this
slice takes the verdicted-out road, in the house
shape of S-265's registry refusal: the published
refusal with the seam documented. This module IS
the polls face's standing shape, with every act
refused:

- **A poll belongs to a discussion thread.** A
  poll is named whole -- the owner/name of the
  repository the thread stands in, the thread's
  per-repository number, a question, its options
  and a close date (``PollRef``) -- and it lives
  or dies with that thread, exactly as S-282's
  first must-not-break invariant
  (``permissions-follow-the-repository``) states
  for every discussion surface. There is no
  poll-only ownership and no poll apart from the
  thread it would stand in.
- **Permissions are judged for real, first.**
  ``OPERATIONS`` names the four acts a poll
  would carry -- create, vote, results, close --
  each with the rung of S-190's permission law it
  would require on the owning repository
  (create, vote and results: read, the rungs
  S-283 declares for opening and answering a
  question or open-discussion thread; close:
  the thread's author or a holder of the
  ``maintain`` rung, the hands S-284 trusts with
  a thread's curation). ``DiscussionPolls``
  resolves the thread through S-283's own door
  (``DiscussionStore.get_thread``) before any
  verdict is spoken: a missing thread, and a
  thread in a repository the caller cannot read,
  answer exactly the same
  ``discussion_not_found`` -- private
  indistinguishable from missing, applied to the
  refusal itself, so the refusal never leaks
  what the caller may not read. A signed-in act
  by the anonymous is refused
  ``authentication_required``; a close by hands
  that hold neither the authorship nor the
  maintain rung is refused ``permission_denied``.
- **Only then is the verdict spoken.** A caller
  who passes the permission door meets S-282's
  deferral for the polls feature, delegated to
  the verdict's own ``decide_discussion_request``
  so the two slices can never drift:
  ``discussions_deferred``, with the recorded
  reasons (the polls ``FeatureAssessment`` in
  samverk/discussions_verdict.py). Shapeless
  requests are refused at the door storing
  nothing: ``poll_question_invalid``,
  ``poll_options_invalid``, ``poll_close_invalid``,
  ``poll_choice_invalid`` and
  ``poll_action_invalid`` -- and a shapeless
  thread reference answers at the board's own
  door, as the board answers it.
- **The seam is S-282's, imported not forked.**
  ``SEAM_INVARIANTS`` is the verdict's own
  ``MUST_NOT_BREAK`` tuple -- the same objects --
  so the law a future poll builds under is
  stated once, in samverk/discussions_verdict.py,
  and this face already stands inside it: the
  battery pins the identity. What a reopened
  verdict would have to satisfy is the verdict's
  ``BUILD_CONDITIONS`` for polls, named here and
  in docs/DISCUSSION_POLLS.md: a measured village
  need, and a fraud-honest design -- one honest
  count per account, a close date stated in
  words, no identity claimed beyond account
  scope.
- **A refusal that writes nothing.** This
  module holds no store of its own, creates no
  table and audits nothing: no act here can
  succeed, so there is nothing to witness.
  ``audit_discussion_polls`` proves the refusal
  against the live instance: the verdict still
  defers polls, and no table, column or audit
  event carries a poll -- S-282's verdict audit
  still refuses any discussion-shaped name
  beyond its sanctioned build, and a poll
  surface arriving ahead of a reopened verdict
  is caught here by name. No migration (schema
  stays 114), no taxonomy event (133 stand:
  33 auth / 87 repo / 13 admin). The published
  refusal also lives in docs/DISCUSSION_POLLS.md,
  where a person who never opens this module
  can read it.
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from . import taxonomy
from .accounts import AccountStore, User
from .audit import AuditLog
from .discussions import Discussion, DiscussionError, DiscussionStore
from .discussions_verdict import (
    BUILD_CONDITIONS, MUST_NOT_BREAK,
    audit_discussions_verdict, decide_discussion_request,
    get_feature)
from .escaping import escape_html_text
from .permission_engine import PermissionEngine
from .repositories import Repository, RepositoryStore
from .team_permissions import role_covers

__all__ = [
    "DEFERRAL_REASONS", "OPERATIONS", "OPTIONS_MAX",
    "OPTIONS_MIN", "OPTION_MAX", "QUESTION_MAX",
    "SEAM_INVARIANTS", "DiscussionPolls",
    "DiscussionPollsAudit", "OperationSpec", "PollError",
    "PollRef", "audit_discussion_polls", "decide_close",
    "decide_create", "decide_results", "decide_vote",
    "get_operation", "render_discussion_polls_page",
    "validate_choice", "validate_close_date",
    "validate_options", "validate_question",
]

# The seam, stated once in S-282 and imported
# whole: this face stands inside the verdict's
# invariants, it does not restate them.
SEAM_INVARIANTS = MUST_NOT_BREAK

QUESTION_MAX = 200
OPTION_MAX = 80
OPTIONS_MIN = 2
OPTIONS_MAX = 6

# Why polls defer, in the verdict's own words:
# the polls assessment S-282 recorded (its
# village-need finding and its honesty warning).
DEFERRAL_REASONS = get_feature("polls")


class PollError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class PollRef:
    """One poll, named whole: the repository its
    thread stands in (owner and name, display
    case), the thread's per-repository number,
    the question, the options in order, and the
    close date as an epoch second. A ref names
    where a poll WOULD stand; naming one creates
    nothing."""
    owner: str
    repo: str
    thread_number: int
    question: str
    options: tuple[str, ...]
    closes_at: int

    @property
    def thread_ref(self) -> str:
        return f"{self.owner}/{self.repo}#{self.thread_number}"

    @property
    def coordinate(self) -> str:
        return (f"poll:{self.thread_ref}:"
                f"{len(self.options)} options")


@dataclass(frozen=True)
class OperationSpec:
    """One act a discussion poll would carry: a
    stable id, the plain title a reader sees, the
    rung of S-190's permission law the act
    requires on the owning repository, and what
    the act would do if polls stood."""
    id: str
    title: str
    minimum_role: str
    would_do: str


OPERATIONS: tuple[OperationSpec, ...] = (
    OperationSpec(
        id="create",
        title="Open a poll in a discussion thread",
        minimum_role="read",
        would_do=(
            "Fix a question, its options and a close "
            "date onto one discussion thread, one "
            "poll standing in a thread at a time, "
            "its state said in words on the thread.")),
    OperationSpec(
        id="vote",
        title="Vote in a discussion poll",
        minimum_role="read",
        would_do=(
            "Record one honest count per account "
            "for one option, changeable until the "
            "close date and never after, claiming "
            "no identity beyond account scope.")),
    OperationSpec(
        id="results",
        title="Read a discussion poll's results",
        minimum_role="read",
        would_do=(
            "State the count per option in words "
            "and numbers together, the close date "
            "and whether the poll stands open or "
            "closed, to any reader of the thread.")),
    OperationSpec(
        id="close",
        title="Close a discussion poll",
        minimum_role="maintain",
        would_do=(
            "End voting at the author's word or a "
            "maintainer's, before the close date if "
            "need be, leaving the final counts "
            "standing on the thread in words.")),
)


def get_operation(operation_id: object) -> OperationSpec:
    """One poll operation by its id. An unknown id
    is refused ``poll_action_invalid`` -- the face
    does not invent an act to answer with."""
    for operation in OPERATIONS:
        if operation.id == operation_id:
            return operation
    raise PollError(
        "poll_action_invalid",
        "No such poll action exists.")


def validate_question(question: object) -> str:
    """One poll question, judged at the door: text
    of 1..200 plain characters, stripped. Refused
    ``poll_question_invalid`` storing nothing."""
    if not isinstance(question, str) or not question.strip():
        raise PollError(
            "poll_question_invalid",
            "A poll needs a question.")
    text = question.strip()
    if len(text) > QUESTION_MAX or any(
            ord(c) < 0x20 or ord(c) == 0x7F for c in text):
        raise PollError(
            "poll_question_invalid",
            f"Poll questions are at most {QUESTION_MAX} "
            "characters of plain text.")
    return text


def validate_options(options: object) -> tuple[str, ...]:
    """A poll's options, judged at the door: a list
    or tuple of 2..6 distinct texts of 1..80 plain
    characters each, stripped, distinct ignoring
    case -- a poll whose options cannot be told
    apart cannot be counted honestly. Refused
    ``poll_options_invalid`` storing nothing."""
    if not isinstance(options, (list, tuple)):
        raise PollError(
            "poll_options_invalid",
            "A poll's options are a list of texts.")
    if not OPTIONS_MIN <= len(options) <= OPTIONS_MAX:
        raise PollError(
            "poll_options_invalid",
            f"A poll carries {OPTIONS_MIN} to "
            f"{OPTIONS_MAX} options.")
    cleaned: list[str] = []
    seen: set[str] = set()
    for option in options:
        if not isinstance(option, str) or not option.strip():
            raise PollError(
                "poll_options_invalid",
                "Every poll option is text.")
        text = option.strip()
        if len(text) > OPTION_MAX or any(
                ord(c) < 0x20 or ord(c) == 0x7F for c in text):
            raise PollError(
                "poll_options_invalid",
                f"Poll options are at most {OPTION_MAX} "
                "characters of plain text.")
        if text.lower() in seen:
            raise PollError(
                "poll_options_invalid",
                "A poll's options are distinct: two "
                "options may not say the same thing.")
        seen.add(text.lower())
        cleaned.append(text)
    return tuple(cleaned)


def validate_close_date(closes_at: object, now: int) -> int:
    """A poll's close date, judged at the door: an
    epoch second (never a bool) lying ahead of
    *now* -- a poll that closes in the past was
    never open, and its counts could never be
    honest. Refused ``poll_close_invalid``."""
    if not isinstance(closes_at, int) \
            or isinstance(closes_at, bool) or closes_at <= now:
        raise PollError(
            "poll_close_invalid",
            "A poll's close date is a time still "
            "ahead, stated as an epoch second.")
    return closes_at


def validate_choice(choice: object) -> int:
    """One vote's choice, judged at the door: the
    index of an option, a non-negative integer
    (never a bool). Whether the index names an
    option of a standing poll can only be judged
    against a poll, and no poll stands. Refused
    ``poll_choice_invalid``."""
    if not isinstance(choice, int) \
            or isinstance(choice, bool) or choice < 0:
        raise PollError(
            "poll_choice_invalid",
            "A vote names one of the poll's options, "
            "by its number.")
    return choice


def _verdict_reason() -> str:
    """S-282's answer for the polls feature,
    delegated so the verdict is spoken in one
    place only: ``discussions_deferred``."""
    return decide_discussion_request("polls")


def decide_create(thread_found: bool,
                  caller_role: str | None) -> str:
    """Pure create judgement: a thread the caller
    cannot read -- missing, or in a repository
    that answers as missing -- is the uniform
    ``discussion_not_found``; a reader of the
    thread meets the verdict's deferral."""
    if not thread_found or caller_role is None:
        return "discussion_not_found"
    return _verdict_reason()


def decide_vote(thread_found: bool,
                caller_role: str | None) -> str:
    """Pure vote judgement, judged exactly as
    create is judged: voting is a reader's act in
    the thread, so the missing and the unreadable
    are one ``discussion_not_found`` and a reader
    meets the deferral."""
    return decide_create(thread_found, caller_role)


def decide_results(thread_found: bool,
                   caller_role: str | None) -> str:
    """Pure results judgement, judged exactly as
    create is judged: results are read with the
    thread, so the missing and the unreadable are
    one ``discussion_not_found`` and a reader
    meets the deferral."""
    return decide_create(thread_found, caller_role)


def decide_close(thread_found: bool, caller_role: str | None,
                 *, is_author: bool) -> str:
    """Pure close judgement, in order: the missing
    and the unreadable are the uniform
    ``discussion_not_found``; hands that are
    neither the thread author's nor a holder of
    the ``maintain`` rung are
    ``permission_denied`` (closing is curation,
    the hands S-284 trusts); the author or a
    maintainer meets the deferral."""
    if not thread_found or caller_role is None:
        return "discussion_not_found"
    if not is_author and not role_covers(caller_role, "maintain"):
        return "permission_denied"
    return _verdict_reason()


_DEFERRED_MESSAGE = (
    "Samverk has no discussion polls: S-282 "
    "deferred them, with reasons, because no "
    "village-scale need for thread polls has been "
    "measured, and a poll's counts are honest only "
    "under fraud-resistant rules that claim no "
    "identity beyond account scope. The record is "
    "docs/DISCUSSIONS_VERDICT.md; this refusal is "
    "docs/DISCUSSION_POLLS.md.")


class DiscussionPolls:
    """The polls face's standing doors. Every
    method judges its request whole -- shape,
    then the thread through S-283's own door and
    S-190's rungs on the owning repository, then
    S-282's verdict -- and refuses; nothing here
    can succeed, write a row, or audit an event,
    because no poll stands to succeed against."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        board: DiscussionStore,
        audit: AuditLog | None = None,
        engine: PermissionEngine | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._board = board
        self._audit = audit
        self._now = time_fn
        self._engine = engine or PermissionEngine(
            conn, accounts, audit=None, time_fn=time_fn)

    # -- judging -------------------------------------------------

    def _thread(self, viewer: User | None, owner: object,
                repo: object, number: object) -> Discussion:
        """The thread, through S-283's own door:
        its reasons are carried over verbatim, so
        a missing thread and an unreadable one
        answer exactly as the board answers them."""
        try:
            return self._board.get_thread(viewer, owner, repo, number)
        except DiscussionError as exc:
            raise PollError(exc.reason, str(exc)) from None

    def _repo(self, owner: object, repo: object) -> Repository:
        current = self._repos.get_repository(owner, repo)
        assert current is not None  # the door above proved it
        return current

    def _judge(self, operation: str, actor: User | None,
               owner: object, repo: object, number: object) -> None:
        """Judge one act in the face's one order
        and raise its refusal -- every path raises,
        because no act here can succeed; shape
        refusals raise in the doors, before any
        thread is read."""
        spec = get_operation(operation)
        if operation in ("create", "vote", "close") \
                and actor is None:
            raise PollError(
                "authentication_required",
                "That poll act needs a signed-in account.")
        thread = self._thread(actor, owner, repo, number)
        current = self._repo(owner, repo)
        role = self._engine.role_for(actor, current)
        if operation == "close":
            reason = decide_close(
                True, role, is_author=(
                    actor is not None
                    and actor.id == thread.author_id))
        elif operation == "vote":
            reason = decide_vote(True, role)
        elif operation == "results":
            reason = decide_results(True, role)
        else:
            reason = decide_create(True, role)
        if reason == "discussion_not_found":
            raise PollError(reason, "No such discussion.")
        if reason == "permission_denied":
            raise PollError(
                reason,
                f"Only the thread's author or a repository "
                f"{spec.minimum_role} may do that with "
                "this thread's poll.")
        raise PollError(reason, _DEFERRED_MESSAGE)

    # -- the four doors -------------------------------------------

    def create_poll(self, actor: User | None, owner: object,
                    repo: object, number: object,
                    question: object, options: object,
                    closes_at: object) -> None:
        """Refuse a poll's opening: shape first
        (question, options, close date -- storing
        nothing), then the thread through the
        board's door at the read rung, then
        S-282's deferral."""
        validate_question(question)
        validate_options(options)
        validate_close_date(closes_at, int(self._now()))
        self._judge("create", actor, owner, repo, number)

    def vote(self, actor: User | None, owner: object,
             repo: object, number: object,
             choice: object) -> None:
        """Refuse a vote: shape first, then the
        thread through the board's door at the
        read rung -- the missing and the unreadable
        answering as one ``discussion_not_found``
        -- then S-282's deferral."""
        validate_choice(choice)
        self._judge("vote", actor, owner, repo, number)

    def results(self, viewer: User | None, owner: object,
                repo: object, number: object) -> None:
        """Refuse a results read: the thread
        through the board's door at the read rung,
        then S-282's deferral. An anonymous reader
        of a public thread meets the same deferral
        as any reader."""
        self._judge("results", viewer, owner, repo, number)

    def close_poll(self, actor: User | None, owner: object,
                   repo: object, number: object) -> None:
        """Refuse a poll's closing: the thread
        through the board's door, then the
        curation hands -- the thread's author or
        the ``maintain`` rung -- then S-282's
        deferral."""
        self._judge("close", actor, owner, repo, number)


@dataclass(frozen=True)
class DiscussionPollsAudit:
    """The refusal checked against one live
    instance: S-282's verdict audit carried whole
    (its counts and offender lists), the polls
    feature's standing judgement, and every poll-
    shaped name found in the instance. The refusal
    is clean only when polls still defer, the
    verdict audit finds no offender beyond its
    sanctioned build, and no table, column or
    audit event carries a poll."""
    verdict_feature: str
    feature_judgement: str
    verdict_audit_clean: bool
    tables_scanned: int
    columns_scanned: int
    events_scanned: int
    verdict_offending_tables: tuple[str, ...]
    verdict_offending_columns: tuple[str, ...]
    verdict_offending_events: tuple[str, ...]
    offending_tables: tuple[str, ...]
    offending_columns: tuple[str, ...]
    offending_events: tuple[str, ...]
    operations_defined: int
    seam_invariants: int

    @property
    def refused_cleanly(self) -> bool:
        return (self.feature_judgement == "deferred"
                and self.verdict_audit_clean
                and not self.offending_tables
                and not self.offending_columns
                and not self.offending_events)


def audit_discussion_polls(
        conn: sqlite3.Connection) -> DiscussionPollsAudit:
    """Check the published refusal against the
    live instance: S-282 must still defer the
    polls feature and its audit must still find
    the sanctioned build clean, and no table,
    column or audit event may carry a poll -- a
    poll surface arriving ahead of a reopened
    verdict, by any door, would be the refusal
    broken. Pure read."""
    verdict_audit = audit_discussions_verdict(conn)
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master"
        " WHERE type = 'table' ORDER BY name").fetchall()]
    offending_tables: list[str] = []
    offending_columns: list[str] = []
    for table in tables:
        if "poll" in table.lower():
            offending_tables.append(table)
        safe = table.replace('"', '""')
        for row in conn.execute(
                f'PRAGMA table_info("{safe}")').fetchall():
            if "poll" in str(row[1]).lower():
                offending_columns.append(f"{table}.{row[1]}")
    offending_events = tuple(
        e for e in sorted(taxonomy.AUDIT_EVENTS)
        if "poll" in e.lower())
    return DiscussionPollsAudit(
        verdict_feature="polls",
        feature_judgement=get_feature("polls").judgement,
        verdict_audit_clean=verdict_audit.build_queued_cleanly,
        tables_scanned=verdict_audit.tables_scanned,
        columns_scanned=verdict_audit.columns_scanned,
        events_scanned=verdict_audit.events_scanned,
        verdict_offending_tables=verdict_audit.offending_tables,
        verdict_offending_columns=verdict_audit.offending_columns,
        verdict_offending_events=verdict_audit.offending_events,
        offending_tables=tuple(offending_tables),
        offending_columns=tuple(offending_columns),
        offending_events=offending_events,
        operations_defined=len(OPERATIONS),
        seam_invariants=len(SEAM_INVARIANTS))


def render_discussion_polls_page(
        audit: DiscussionPollsAudit | None = None) -> str:
    """The published refusal, rendered: no polls
    said plainly, the thread law, the four
    operations with the permission rung each is
    judged at, how a request is answered, the
    seam invariants with the ground each hangs
    from, what to use instead, the reopen pointer,
    and the checked proof when an audit rides
    along -- every value escaped through S-010,
    the state said in words, never colour-only."""
    parts = [
        "<h1>Discussion polls -- no polls (S-286)</h1>",
        "<p>Samverk has <strong>no discussion "
        "polls</strong>. S-282 deferred them, with "
        "reasons (docs/DISCUSSIONS_VERDICT.md), and "
        "this slice is the published refusal the "
        "roadmap names for the verdicted-out road: "
        "the polls face's doors stand defined -- a "
        "poll named whole on its discussion thread, "
        "judged by the owning repository's "
        "permissions -- and every one of them "
        "refuses. There is no poll table, no vote "
        "and no count; a village decision today is "
        "made in the open discussion itself, in "
        "words, by named people.</p>",
        "<h2>A poll belongs to its thread</h2>",
        "<p>A poll is named by the owner and name "
        "of the repository its thread stands in, "
        "the thread's number, a question, its "
        "options and a close date. The poll belongs "
        "to that thread and its repository: every "
        "act is judged by the repository's own "
        "permissions (S-190's engine, through "
        "S-283's board), never by a poll-only "
        "ownership.</p>",
        "<h2>The four doors, and the rung each is judged at</h2>",
        "<ul>",
    ]
    for operation in OPERATIONS:
        parts.append(
            f"<li><strong>{escape_html_text(operation.title)}"
            f"</strong> ({escape_html_text(operation.id)}; "
            f"requires {escape_html_text(operation.minimum_role)} "
            f"on the owning repository): "
            f"{escape_html_text(operation.would_do)} "
            "Today it refuses.</li>")
    parts.append("</ul>")
    parts.append("<h2>How a request is answered</h2>")
    parts.append(
        "<p>Shape first, storing nothing; then the "
        "thread through S-283's own door -- a "
        "missing thread, and a thread in a "
        "repository the caller may not read, answer "
        "as one discussion_not_found, so the refusal "
        "itself leaks nothing; a signed-in act by "
        "the anonymous is authentication_required, "
        "and closing asks the thread's author or "
        "the maintain rung. Only a caller who "
        "passes that door meets the verdict's "
        "answer for polls: "
        f"{escape_html_text(_verdict_reason())} -- "
        f"{escape_html_text(DEFERRAL_REASONS.village_need)}</p>")
    parts.append(
        "<h2>The seam a future poll builds under</h2>")
    parts.append("<ul>")
    for invariant in SEAM_INVARIANTS:
        parts.append(
            f"<li><strong>{escape_html_text(invariant.title)}"
            f"</strong> (grounded in: "
            f"{escape_html_text(invariant.ground)}): "
            f"{escape_html_text(invariant.statement)}</li>")
    parts.append("</ul>")
    parts.append("<h2>When this reopens</h2>")
    parts.append("<ul>")
    for condition in BUILD_CONDITIONS:
        if "poll" in condition.lower():
            parts.append(
                f"<li>{escape_html_text(condition)}</li>")
    parts.append("</ul>")
    if audit is not None:
        if audit.refused_cleanly:
            parts.append(
                "<p>Checked, not just claimed: this "
                "instance was inspected for a poll "
                f"surface -- {audit.tables_scanned} "
                f"tables, {audit.columns_scanned} "
                f"columns and {audit.events_scanned} "
                "audit events -- and none carries a "
                "poll: no poll exists here before a "
                "reopened verdict builds one, exactly "
                "as the deferral states.</p>")
        else:
            found = ", ".join(
                audit.offending_tables
                + audit.offending_columns
                + audit.offending_events
                + audit.verdict_offending_tables
                + audit.verdict_offending_columns
                + audit.verdict_offending_events
                + (("S-282 no longer defers polls",)
                   if audit.feature_judgement != "deferred"
                   else ()))
            parts.append(
                "<p>Checked, and not clean: the "
                "refusal no longer holds as stated -- "
                f"{escape_html_text(found)} -- and "
                "that is a defect against S-286, to "
                "be fixed where it lies.</p>")
    parts.append(
        "<p>The full verdict lives in "
        "docs/DISCUSSIONS_VERDICT.md (S-282); this "
        "refusal's own record is "
        "docs/DISCUSSION_POLLS.md.</p>")
    return "\n".join(parts)
