"""Issue timeline (S-131).

One ordered stream of everything that *happened* to an
issue — its creation, every state change, label,
assignment, milestone move, mention, and cross-reference
— in the order it happened, each event said in plain
words. Part XI's activity feeds read this stream; an
issue page interleaves it with the conversation.
(S-132's locks and pins joined the stream from the
same audit record the day they landed.)

- **Derived, not duplicated.** The timeline invents no
  second record. Each kind is read from the one record
  that already proves it: creation from the issue row
  itself (S-122), state changes through S-130's
  `state_events_for` seam over `issue_events`, label /
  assignment / milestone changes from the audit log
  (the append-only witness every one of those acts
  already writes, read the way S-047's login history
  reads it), and mentions / cross-references from
  S-127's `cross_references` record. Rebuilding the
  stream twice builds it identically, and an act the
  underlying slices refused or rolled back can never
  appear here.
- **Mentions and cross-references are two directions.**
  A *mention* is incoming: someone else's prose named
  this issue (`mentioned`). A *cross-reference* is
  outgoing: this issue's own prose named another
  numbered item or a commit (`referenced`), with a
  closing mark (`is_closing`) said in words, never
  discovered after a merge. A back-reference whose
  source lives in a repository the viewer cannot read
  is hidden, exactly as S-127 hides it — a private
  repo's conversations never leak through a public
  target's timeline.
- **Comments are the conversation, not events.** A
  comment is speech (S-123), not a happening; surfaces
  interleave comments and this stream by time. Title
  and body edits are likewise not events (the GitHub
  habit: an edit is shown on the comment/issue itself,
  not as a timeline entry), and reactions are counts
  (S-128), not happenings.
- **Order is time, then a named tie-break.** Events
  sort by `created_at`; events inside the same second
  sort by a fixed kind rank and then their source
  record's id, so the stream is deterministic and a
  rebuild never reshuffles it. The stream is words
  throughout — no event's meaning rides on a colour.
- **Permissions ride the repository's.** Reading a
  timeline requires reading the issue (S-054): a
  stranger to a private repository gets the uniform
  `issue_not_found`, exactly as for the issue itself.
- **No audit event of its own.** A timeline is derived
  data recomputed from already-audited acts, like
  S-127's record: reading it invents no act to witness.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from .accounts import AccountStore, User
from .escaping import escape_html_text
from .issue_locking import LOCK_REASON_WORDS
from .issues import REASON_WORDS, IssueStore
from .permissions import can_read
from .repositories import RepositoryStore

# Deterministic order inside one second: creation first,
# then the audited/recorded happenings in causal rank,
# then incoming mentions (recorded when prose was synced,
# never before the prose itself existed).
_KIND_RANK = {
    "created": 0,
    "labelled": 1, "unlabelled": 1,
    "assigned": 2, "unassigned": 2,
    "milestone": 3,
    "pinned": 3, "unpinned": 3,
    "closed": 4, "reopened": 4,
    "locked": 4, "unlocked": 4,
    "referenced": 5,
    "mentioned": 6,
}

_AUDIT_KINDS = {
    "repo.issue.label_add": "labelled",
    "repo.issue.label_remove": "unlabelled",
    "repo.issue.assign": "assigned",
    "repo.issue.unassign": "unassigned",
    "repo.issue.milestone": "milestone",
    # S-132's acts ride two target shapes: lock/pin rows are
    # addressed to the issue itself (full_name#number).
    "repo.issue.lock": "locked",
    "repo.issue.unlock": "unlocked",
    "repo.issue.pin": "pinned",
    "repo.issue.unpin": "unpinned",
}


@dataclass(frozen=True)
class TimelineEvent:
    kind: str            # see _KIND_RANK
    actor_id: int | None
    actor: str           # display case; '' when unknown
    created_at: int
    reason: str = ""     # closing reason for 'closed'
    label: str = ""      # for labelled / unlabelled
    assignee: str = ""   # for assigned / unassigned
    milestone: str = ""  # for milestone ('' = cleared)
    source_repo: str = ""    # mention: where the prose lives
    source_number: int = 0   # mention: the prose's #n (0 = commit)
    source_kind: str = ""    # mention: 'issue'|'comment'|'commit'
    source_sha: str = ""     # mention: the commit, for commit sources
    target_repo: str = ""    # referenced: the named repository
    target_number: int = 0   # referenced: the named #n (0 = commit)
    target_sha: str = ""     # referenced: the named commit (full oid)
    is_closing: bool = False  # referenced: marked to close on merge


def describe_event(event: TimelineEvent) -> str:
    """One timeline event in plain words."""
    actor = event.actor or "Someone"
    if event.kind == "created":
        return f"{actor} created this issue"
    if event.kind == "closed":
        words = REASON_WORDS.get(event.reason, "")
        suffix = f" as {words}" if words else ""
        return f"{actor} closed this issue{suffix}"
    if event.kind == "reopened":
        return f"{actor} reopened this issue"
    if event.kind == "labelled":
        return f"{actor} added the {event.label} label"
    if event.kind == "unlabelled":
        return f"{actor} removed the {event.label} label"
    if event.kind == "assigned":
        if event.assignee and event.assignee == event.actor:
            return f"{actor} self-assigned this issue"
        return f"{actor} assigned {event.assignee}"
    if event.kind == "unassigned":
        if event.assignee and event.assignee == event.actor:
            return f"{actor} removed their own assignment"
        return f"{actor} removed {event.assignee}'s assignment"
    if event.kind == "locked":
        words = LOCK_REASON_WORDS.get(event.reason, "")
        suffix = f" as {words}" if words else ""
        return f"{actor} locked this conversation{suffix}"
    if event.kind == "unlocked":
        return f"{actor} unlocked this conversation"
    if event.kind == "pinned":
        return f"{actor} pinned this issue"
    if event.kind == "unpinned":
        return f"{actor} unpinned this issue"
    if event.kind == "milestone":
        if event.milestone:
            return (f"{actor} added this issue to the "
                    f"{event.milestone} milestone")
        return f"{actor} removed this issue from its milestone"
    if event.kind == "mentioned":
        if event.source_kind == "commit":
            where = (f"commit {event.source_sha[:7]}"
                     if event.source_sha else "a commit")
            return f"{actor} mentioned this issue in {where}" \
                if event.actor else \
                f"This issue was mentioned in {where}"
        if event.source_kind == "comment":
            return (f"{actor} mentioned this issue in a comment on "
                    f"{event.source_repo}#{event.source_number}")
        return (f"{actor} mentioned this issue in "
                f"{event.source_repo}#{event.source_number}")
    if event.kind == "referenced":
        if event.target_sha:
            what = f"commit {event.target_sha[:7]}"
        else:
            what = f"{event.target_repo}#{event.target_number}"
        if event.is_closing:
            return f"{actor} referenced {what} and marked it to close on merge"
        return f"{actor} referenced {what}"
    return f"{actor} changed this issue"


def render_timeline(events: list[TimelineEvent]) -> str:
    """The stream as an HTML list of plain-word lines —
    every event's meaning is in its text, never a colour."""
    items = "".join(
        '<li class="timeline-event" data-kind="'
        + escape_html_text(e.kind) + '">'
        + escape_html_text(describe_event(e)) + "</li>"
        for e in events)
    return f'<ol class="timeline">{items}</ol>'


class TimelineStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        issues: IssueStore,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._issues = issues

    def timeline_for(self, viewer: User | None, owner: object,
                     repo: object, number: object
                     ) -> list[TimelineEvent]:
        """The issue's whole event stream, oldest first.
        Reading the issue (S-054, uniform `issue_not_found`)
        is the gate, enforced by `get_issue` itself."""
        issue = self._issues.get_issue(viewer, owner, repo, number)
        current = self._repos.get_repository(owner, repo)
        assert current is not None
        keyed: list[tuple[int, int, int, TimelineEvent]] = []

        def add(event: TimelineEvent, source_id: int) -> None:
            keyed.append((event.created_at,
                          _KIND_RANK.get(event.kind, 9),
                          source_id, event))

        # Creation — the issue row is its own record.
        author = self._accounts.get_by_id(issue.author_id)
        add(TimelineEvent(
            kind="created", actor_id=issue.author_id,
            actor=author.username if author else "",
            created_at=issue.created_at), 0)

        # State changes — S-130's designated seam.
        for state_event in self._issues.state_events_for(
                viewer, owner, repo, number):
            add(TimelineEvent(
                kind=state_event.kind, actor_id=state_event.actor_id,
                actor=state_event.actor, created_at=state_event.created_at,
                reason=state_event.reason), state_event.id)

        # Label / assignment / milestone changes — the
        # audit log is their event record (each act's own
        # slice writes exactly one row, in seq order).
        for row in self._conn.execute(
                "SELECT seq, ts, actor_id, action, detail FROM audit_log"
                " WHERE target_id IN (?, ?) AND action IN ("
                " 'repo.issue.label_add', 'repo.issue.label_remove',"
                " 'repo.issue.assign', 'repo.issue.unassign',"
                " 'repo.issue.milestone', 'repo.issue.lock',"
                " 'repo.issue.unlock', 'repo.issue.pin',"
                " 'repo.issue.unpin') ORDER BY seq",
                (current.full_name,
                 f"{current.full_name}#{issue.number}")).fetchall():
            try:
                detail = json.loads(row["detail"] or "{}")
            except ValueError:
                continue
            if detail.get("number") != issue.number:
                continue
            actor = self._accounts.get_by_id(row["actor_id"])
            kind = _AUDIT_KINDS[row["action"]]
            add(TimelineEvent(
                kind=kind, actor_id=row["actor_id"],
                actor=actor.username if actor else "",
                created_at=int(row["ts"]),
                reason=str(detail.get("reason") or ""),
                label=str(detail.get("label") or ""),
                assignee=str(detail.get("assignee") or ""),
                milestone=str(detail.get("milestone") or "")),
                int(row["seq"]))

        # Mentions (incoming) and cross-references
        # (outgoing) — S-127's record, both directions.
        for row in self._conn.execute(
                "SELECT * FROM cross_references"
                " WHERE target_repo_id = ? AND target_number = ?"
                " ORDER BY id", (current.id, issue.number)).fetchall():
            source_repo = self._repos.get_by_id(row["repo_id"])
            if source_repo is None or not can_read(viewer, source_repo):
                continue  # a private source never leaks (S-127)
            actor = (self._accounts.get_by_id(row["source_author_id"])
                     if row["source_author_id"] else None)
            add(TimelineEvent(
                kind="mentioned",
                actor_id=row["source_author_id"],
                actor=actor.username if actor else "",
                created_at=int(row["created_at"]),
                source_repo=source_repo.full_name,
                source_number=int(row["source_number"]),
                source_kind=row["source_kind"],
                source_sha=row["source_sha"]), int(row["id"]))
        for row in self._conn.execute(
                "SELECT * FROM cross_references"
                " WHERE repo_id = ? AND source_number = ?"
                " AND source_kind IN ('issue', 'comment') ORDER BY id",
                (current.id, issue.number)).fetchall():
            target_repo = self._repos.get_by_id(row["target_repo_id"])
            actor = (self._accounts.get_by_id(row["source_author_id"])
                     if row["source_author_id"] else None)
            add(TimelineEvent(
                kind="referenced",
                actor_id=row["source_author_id"],
                actor=actor.username if actor else "",
                created_at=int(row["created_at"]),
                target_repo=(target_repo.full_name
                             if target_repo is not None else ""),
                target_number=int(row["target_number"]),
                target_sha=row["target_sha"],
                is_closing=bool(row["is_closing"])), int(row["id"]))

        keyed.sort(key=lambda item: (item[0], item[1], item[2]))
        return [event for _, _, _, event in keyed]
