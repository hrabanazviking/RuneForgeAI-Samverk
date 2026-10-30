"""Pull request conversation (S-144).

The conversation is where a pull request is actually
reviewed in prose: comments from anyone who can read
the repository, one timeline that merges everything
that *happened* to the pull request, and — shown
before anyone merges — the closing keywords its prose
carries, read through S-127's law.

- **Comments are S-123's record, on the pull request.**
  A pull request is a numbered item (S-121), and its
  comments live in the same `issue_comments` table,
  with the same honest record: edits keep their
  previous bodies in `issue_comment_edits`, deletion
  is a tombstone, a moderator-hidden comment leaves
  the conversation for everyone except its author and
  the repository's moderators (S-138's visibility law,
  read from the same stamps). What S-123's store
  cannot do is *address* a pull request — its seam
  reads through `IssueStore.get_issue`, which refuses
  pull-request rows by kind — so this store is the
  comment seam for pull requests, writing the same
  rows under its own audit events (taxonomy
  append-only +3: `repo.pull_request.comment` /
  `.comment_edit` / `.comment_delete`, carried by
  S-139's outbox under its `repo.pull_request.*`
  verb rule). Editing is the author's alone; deletion
  is the author's or a repository admin's. A locked
  conversation refuses new comments exactly as
  S-132's law refuses them on issues — everyone
  except repository writers, with the reason in words.
- **The timeline is derived, never duplicated.** Each
  kind is read from the one record that proves it:
  opening from the pull request row itself, state
  changes from `issue_events` (S-130's stream, read
  directly because its seam is issue-addressed),
  readiness changes and the audited issue-family acts
  from the audit log, and mentions / cross-references
  from S-127's record. Review submissions (S-148) are
  audited acts when they land; like S-132…S-138 taught
  S-131's timeline their events in their own slices,
  that slice teaches this stream its review events —
  until then there are no review records to merge,
  and this stream invents none.
- **The conversation merges comments and timeline by
  time.** `conversation_for` interleaves the two in
  one ordered stream — time first, then a fixed kind
  rank, then the source record's id — so a reader
  sees what was said and what happened in the order
  they actually alternated.
- **Closing keywords are displayed before merge.**
  `closing_references` parses the pull request's
  current body and its live comments through S-127's
  parser and keeps only the references its closing
  keywords govern, proven to exist through
  `IssueStore.resolve_number` — the display follows
  the text, so editing the keyword away removes the
  promise, and `closing_notice` says each closing in
  plain words ("Will close owner/repo#3 on merge.").
  Acting on the mark is the merge slices' work
  (S-153…S-155); surprising no one is this slice's.
  `sync_references` records the same prose into
  S-127's cross-reference record (the pull request's
  prose under the shared source kind for numbered
  items), so the things it mentions gain their
  back-references and this timeline gains its
  `referenced` events, both ways like S-127 promises.
- **Permissions ride the repository's.** Every read
  and write goes through S-141's pull-request seam:
  a stranger to a private repository gets the uniform
  `pull_request_not_found` for comments, timeline,
  conversation, and closing display alike.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .cross_references import (
    CrossReference, CrossReferenceStore, _row_to_ref,
    parse_closing_references, parse_references)
from .escaping import escape_html_text
from .issue_comments import Comment, CommentEdit, _row_to_comment, \
    _validate_comment_body
from .issue_conversion import PullRequest
from .issue_locking import LOCK_REASON_WORDS
from .issues import IssueError, IssueStore
from .permissions import can_admin, can_read, can_write
from .pull_requests import PullRequestError, PullRequestStore
from .repositories import RepositoryStore

__all__ = [
    "ConversationItem", "PrClosingReference", "PrTimelineEvent",
    "PullRequestConversationStore", "describe_pr_event",
    "render_closing_notice", "render_conversation", "render_pr_timeline",
]

# Deterministic order inside one second, mirroring
# S-131's ranks: opening first, then the audited
# happenings in causal rank, comments interleaved as
# happenings of the conversation, then references out
# and mentions in.
_KIND_RANK = {
    "created": 0,
    "labelled": 1, "unlabelled": 1,
    "assigned": 2, "unassigned": 2,
    "milestone": 3,
    "comment": 4,
    "closed": 4, "reopened": 4,
    "marked_ready": 4, "converted_to_draft": 4,
    "comment_hidden": 4, "comment_unhidden": 4,
    "comment_removed": 4,
    "referenced": 5,
    "mentioned": 6,
}

_TIMELINE_AUDIT_KINDS = {
    "repo.pull_request.mark_ready": "marked_ready",
    "repo.pull_request.convert_to_draft": "converted_to_draft",
    "repo.issue.label_add": "labelled",
    "repo.issue.label_remove": "unlabelled",
    "repo.issue.assign": "assigned",
    "repo.issue.unassign": "unassigned",
    "repo.issue.milestone": "milestone",
    "repo.issue.comment_hide": "comment_hidden",
    "repo.issue.comment_unhide": "comment_unhidden",
    "repo.issue.comment_remove": "comment_removed",
}


@dataclass(frozen=True)
class PrTimelineEvent:
    kind: str            # see _KIND_RANK
    actor_id: int | None
    actor: str           # display case; '' when unknown
    created_at: int
    reason: str = ""     # closing reason for 'closed'
    label: str = ""
    assignee: str = ""
    milestone: str = ""
    source_repo: str = ""    # mention: where the prose lives
    source_number: int = 0
    source_kind: str = ""    # mention: 'issue'|'comment'|'commit'
    source_sha: str = ""
    target_repo: str = ""    # referenced: the named repository
    target_number: int = 0
    target_sha: str = ""
    is_closing: bool = False  # referenced: marked to close on merge


def describe_pr_event(event: PrTimelineEvent) -> str:
    """One pull-request timeline event in plain words."""
    actor = event.actor or "Someone"
    if event.kind == "created":
        return f"{actor} opened this pull request"
    if event.kind == "marked_ready":
        return f"{actor} marked this pull request ready for review"
    if event.kind == "converted_to_draft":
        return f"{actor} converted this pull request back to a draft"
    if event.kind == "closed":
        return f"{actor} closed this pull request"
    if event.kind == "reopened":
        return f"{actor} reopened this pull request"
    if event.kind == "labelled":
        return f"{actor} added the {event.label} label"
    if event.kind == "unlabelled":
        return f"{actor} removed the {event.label} label"
    if event.kind == "assigned":
        if event.assignee and event.assignee == event.actor:
            return f"{actor} self-assigned this pull request"
        return f"{actor} assigned {event.assignee}"
    if event.kind == "unassigned":
        if event.assignee and event.assignee == event.actor:
            return f"{actor} removed their own assignment"
        return f"{actor} removed {event.assignee}'s assignment"
    if event.kind == "milestone":
        if event.milestone:
            return (f"{actor} added this pull request to the "
                    f"{event.milestone} milestone")
        return f"{actor} removed this pull request from its milestone"
    if event.kind == "comment_hidden":
        return f"{actor} hid a comment"
    if event.kind == "comment_unhidden":
        return f"{actor} unhid a comment"
    if event.kind == "comment_removed":
        return f"{actor} removed a comment"
    if event.kind == "mentioned":
        if event.source_kind == "commit":
            where = (f"commit {event.source_sha[:7]}"
                     if event.source_sha else "a commit")
            return f"{actor} mentioned this pull request in {where}" \
                if event.actor else \
                f"This pull request was mentioned in {where}"
        if event.source_kind == "comment":
            return (f"{actor} mentioned this pull request in a comment "
                    f"on {event.source_repo}#{event.source_number}")
        return (f"{actor} mentioned this pull request in "
                f"{event.source_repo}#{event.source_number}")
    if event.kind == "referenced":
        if event.target_sha:
            what = f"commit {event.target_sha[:7]}"
        else:
            what = f"{event.target_repo}#{event.target_number}"
        if event.is_closing:
            return (f"{actor} referenced {what} and marked it to "
                    "close on merge")
        return f"{actor} referenced {what}"
    return f"{actor} changed this pull request"


@dataclass(frozen=True)
class ConversationItem:
    kind: str            # 'comment', or a PrTimelineEvent kind
    created_at: int
    author: str = ""     # comment author, display case
    comment: Comment | None = None
    event: PrTimelineEvent | None = None

    @property
    def is_comment(self) -> bool:
        return self.comment is not None


@dataclass(frozen=True)
class PrClosingReference:
    target_repo: str     # full name of the target repository
    target_number: int
    target_kind: str     # 'issue' | 'pull_request'
    raw: str             # as written in the prose

    @property
    def notice(self) -> str:
        return f"Will close {self.target_repo}#{self.target_number} on merge."


class PullRequestConversationStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        issues: IssueStore,
        audit: AuditLog | None = None,
        commit_resolver: Callable[[str, str, str], str | None] | None = None,
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
        self._refs = CrossReferenceStore(
            conn, repositories, accounts, issues,
            commit_resolver=commit_resolver, time_fn=time_fn)

    # -- internals ---------------------------------------------------
    def _require_pr(self, viewer, owner, repo, number) -> PullRequest:
        return self._prs.get_pull_request(viewer, owner, repo, number)

    def _validate_body(self, body: object) -> str:
        try:
            return _validate_comment_body(body)
        except IssueError as exc:
            raise PullRequestError(exc.reason, str(exc)) from None

    def _comment_by_id(self, comment_id: int,
                       number: int) -> Comment | None:
        row = self._conn.execute(
            "SELECT * FROM issue_comments WHERE id = ?",
            (comment_id,)).fetchone()
        return _row_to_comment(row, number) if row else None

    def _emit(self, actor: User, action: str, owner, repo,
              pr: PullRequest, comment_id: int,
              source_ip: str | None) -> None:
        if self._audit is not None:
            current = self._repos.get_repository(owner, repo)
            target = (f"{current.full_name}#{pr.number}"
                      if current is not None else f"#{pr.number}")
            self._audit.append(
                actor_kind="user", actor_id=actor.id, action=action,
                target_kind="repo", target_id=target,
                outcome="success", source_ip=source_ip,
                detail={"number": pr.number, "comment_id": comment_id})

    # -- comments ------------------------------------------------------
    def add_comment(self, actor: User, owner: object, repo: object,
                    number: object, body: object,
                    *, source_ip: str | None = None) -> Comment:
        """Comment on a pull request. Any repository
        reader may speak (the S-122 habit); a locked
        conversation refuses everyone except writers,
        with the lock's reason in words (S-132)."""
        pr = self._require_pr(actor, owner, repo, number)
        row = self._conn.execute(
            "SELECT locked, lock_reason FROM issues WHERE id = ?",
            (pr.row_id,)).fetchone()
        if row is not None and bool(row["locked"]):
            current = self._repos.get_repository(owner, repo)
            if current is None or not can_write(actor, current):
                words = LOCK_REASON_WORDS.get(row["lock_reason"], "")
                suffix = f" as {words}" if words else ""
                raise PullRequestError(
                    "conversation_locked",
                    f"This conversation is locked{suffix}; only "
                    "repository writers can still comment.")
        text = self._validate_body(body)
        now = int(self._now())
        with self._conn:  # commits before the answer
            cur = self._conn.execute(
                "INSERT INTO issue_comments (issue_id, author_id, body,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (pr.row_id, actor.id, text, now, now))
        comment = self._comment_by_id(int(cur.lastrowid), pr.number)
        assert comment is not None
        self._emit(actor, "repo.pull_request.comment", owner, repo,
                   pr, comment.id, source_ip)
        return comment

    def list_comments(self, viewer: User | None, owner: object,
                      repo: object, number: object) -> list[Comment]:
        """The conversation's comments, oldest first,
        tombstones skipped, hidden comments visible
        only to their author and the repository's
        moderators (S-138's law, on the same stamps)."""
        pr = self._require_pr(viewer, owner, repo, number)
        rows = self._conn.execute(
            "SELECT * FROM issue_comments WHERE issue_id = ?"
            " AND deleted_at IS NULL ORDER BY id",
            (pr.row_id,)).fetchall()
        comments = [_row_to_comment(r, pr.number) for r in rows]
        current = self._repos.get_repository(owner, repo)
        viewer_is_moderator = (
            viewer is not None and current is not None
            and can_admin(viewer, current))
        return [c for c in comments if not c.is_hidden
                or viewer_is_moderator
                or (viewer is not None and viewer.id == c.author_id)]

    def get_comment(self, viewer: User | None, owner: object,
                    repo: object, number: object,
                    comment_id: int) -> Comment:
        """One comment, tombstones included — a reader
        following a link to a deleted comment is told
        it was deleted, not that it never existed."""
        pr = self._require_pr(viewer, owner, repo, number)
        comment = self._comment_by_id(comment_id, pr.number)
        if comment is None or comment.issue_id != pr.row_id:
            raise PullRequestError(
                "comment_not_found", "No such comment.")
        return comment

    def edits_for(self, viewer: User | None, owner: object,
                  repo: object, number: object,
                  comment_id: int) -> list[CommentEdit]:
        """The visible edit history of one comment —
        the previous bodies, in the order they were
        replaced (S-123's honest record)."""
        comment = self.get_comment(viewer, owner, repo, number, comment_id)
        rows = self._conn.execute(
            "SELECT * FROM issue_comment_edits WHERE comment_id = ?"
            " ORDER BY id", (comment.id,)).fetchall()
        return [CommentEdit(comment_id=r["comment_id"],
                            editor_id=r["editor_id"],
                            previous_body=r["previous_body"],
                            edited_at=r["edited_at"]) for r in rows]

    def edit_comment(self, actor: User, owner: object, repo: object,
                     number: object, comment_id: int, body: object,
                     *, source_ip: str | None = None) -> Comment:
        """Edit one's own comment; the previous body is
        kept in the edit history in the same transaction."""
        pr = self._require_pr(actor, owner, repo, number)
        comment = self.get_comment(actor, owner, repo, number, comment_id)
        if comment.is_deleted:
            raise PullRequestError(
                "comment_not_found", "No such comment.")
        if actor.id != comment.author_id:
            raise PullRequestError(
                "permission_denied",
                "Only the author can edit this comment.")
        text = self._validate_body(body)
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "INSERT INTO issue_comment_edits (comment_id, editor_id,"
                " previous_body, edited_at) VALUES (?, ?, ?, ?)",
                (comment.id, actor.id, comment.body, now))
            self._conn.execute(
                "UPDATE issue_comments SET body = ?, updated_at = ?,"
                " edited_at = ? WHERE id = ?",
                (text, now, now, comment.id))
        updated = self._comment_by_id(comment.id, pr.number)
        assert updated is not None
        self._emit(actor, "repo.pull_request.comment_edit", owner, repo,
                   pr, comment.id, source_ip)
        return updated

    def delete_comment(self, actor: User, owner: object, repo: object,
                       number: object, comment_id: int,
                       *, source_ip: str | None = None) -> Comment:
        """Delete a comment: a tombstone plus an audit
        row. The author, or a repository admin."""
        pr = self._require_pr(actor, owner, repo, number)
        comment = self.get_comment(actor, owner, repo, number, comment_id)
        if comment.is_deleted:
            raise PullRequestError(
                "comment_not_found", "No such comment.")
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
                "UPDATE issue_comments SET body = '', updated_at = ?,"
                " deleted_at = ?, deleted_by = ? WHERE id = ?",
                (now, now, actor.id, comment.id))
        deleted = self._comment_by_id(comment.id, pr.number)
        assert deleted is not None
        self._emit(actor, "repo.pull_request.comment_delete", owner, repo,
                   pr, comment.id, source_ip)
        return deleted

    # -- timeline --------------------------------------------------------
    def timeline_for(self, viewer: User | None, owner: object,
                     repo: object, number: object
                     ) -> list[PrTimelineEvent]:
        """Everything that happened to this pull
        request, oldest first, derived from the records
        that prove each act — never a second record."""
        pr = self._require_pr(viewer, owner, repo, number)
        current = self._repos.get_repository(owner, repo)
        assert current is not None
        keyed: list[tuple[int, int, int, PrTimelineEvent]] = []

        def add(event: PrTimelineEvent, source_id: int) -> None:
            keyed.append((event.created_at,
                          _KIND_RANK.get(event.kind, 9),
                          source_id, event))

        author = self._accounts.get_by_id(pr.author_id)
        add(PrTimelineEvent(
            kind="created", actor_id=pr.author_id,
            actor=author.username if author else "",
            created_at=pr.created_at), 0)

        # State changes — issue_events is S-130's stream;
        # read it directly for this numbered row.
        for row in self._conn.execute(
                "SELECT * FROM issue_events WHERE issue_id = ?"
                " ORDER BY id", (pr.row_id,)).fetchall():
            actor = self._accounts.get_by_id(row["actor_id"])
            add(PrTimelineEvent(
                kind=row["kind"], actor_id=row["actor_id"],
                actor=actor.username if actor else "",
                created_at=int(row["created_at"]),
                reason=row["reason"] or ""), int(row["id"]))

        # Readiness + audited acts — the audit log is
        # their record, as it is for S-131's stream.
        actions = sorted(_TIMELINE_AUDIT_KINDS)
        placeholders = ", ".join("?" for _ in actions)
        for row in self._conn.execute(
                f"SELECT seq, ts, actor_id, action, detail FROM audit_log"
                f" WHERE target_id IN (?, ?)"
                f" AND action IN ({placeholders}) ORDER BY seq",
                (current.full_name, f"{current.full_name}#{pr.number}",
                 *actions)).fetchall():
            try:
                detail = json.loads(row["detail"] or "{}")
            except ValueError:
                continue
            if detail.get("number") != pr.number:
                continue
            actor = self._accounts.get_by_id(row["actor_id"])
            add(PrTimelineEvent(
                kind=_TIMELINE_AUDIT_KINDS[row["action"]],
                actor_id=row["actor_id"],
                actor=actor.username if actor else "",
                created_at=int(row["ts"]),
                reason=str(detail.get("reason") or ""),
                label=str(detail.get("label") or ""),
                assignee=str(detail.get("assignee") or ""),
                milestone=str(detail.get("milestone") or "")),
                int(row["seq"]))

        # Mentions in, references out — S-127's record.
        for row in self._conn.execute(
                "SELECT * FROM cross_references"
                " WHERE target_repo_id = ? AND target_number = ?"
                " ORDER BY id", (current.id, pr.number)).fetchall():
            source_repo = self._repos.get_by_id(row["repo_id"])
            if source_repo is None or not can_read(viewer, source_repo):
                continue  # a private source never leaks (S-127)
            actor = (self._accounts.get_by_id(row["source_author_id"])
                     if row["source_author_id"] else None)
            add(PrTimelineEvent(
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
                (current.id, pr.number)).fetchall():
            target_repo = self._repos.get_by_id(row["target_repo_id"])
            actor = (self._accounts.get_by_id(row["source_author_id"])
                     if row["source_author_id"] else None)
            add(PrTimelineEvent(
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

    # -- the merged conversation -------------------------------------------
    def conversation_for(self, viewer: User | None, owner: object,
                         repo: object, number: object
                         ) -> list[ConversationItem]:
        """Comments and timeline in one stream, in the
        order they happened — what was said and what
        was done, alternating as they actually did."""
        pr = self._require_pr(viewer, owner, repo, number)
        keyed: list[tuple[int, int, int, ConversationItem]] = []
        for event in self.timeline_for(viewer, owner, repo, number):
            keyed.append((event.created_at,
                          _KIND_RANK.get(event.kind, 9), 0,
                          ConversationItem(
                              kind=event.kind,
                              created_at=event.created_at,
                              event=event)))
        for comment in self.list_comments(viewer, owner, repo, number):
            author = self._accounts.get_by_id(comment.author_id)
            keyed.append((comment.created_at,
                          _KIND_RANK["comment"], comment.id,
                          ConversationItem(
                              kind="comment",
                              created_at=comment.created_at,
                              author=author.username if author else "",
                              comment=comment)))
        # Timeline entries carry no per-source id in the
        # merged key (their own stream already ordered
        # them); a stable sort keeps that order inside
        # one timestamp.
        keyed.sort(key=lambda item: (item[0], item[1], item[2]))
        return [item for _, _, _, item in keyed]

    # -- references: sync + closing display ---------------------------------
    def sync_references(self, actor: User, owner: object,
                        repo: object, number: object
                        ) -> list[CrossReference]:
        """(Re)record what this pull request's body and
        live comments currently reference, through
        S-127's sync seam — the record follows the
        text, and a tombstoned comment's references die
        with its body."""
        pr = self._require_pr(actor, owner, repo, number)
        current = self._repos.get_repository(owner, repo)
        assert current is not None
        self._refs._sync(
            current, "issue", pr.number, 0, "", pr.author_id,
            parse_references(f"{pr.title}\n{pr.body}"))
        for comment in self.list_comments(actor, owner, repo, number):
            self._refs._sync(
                current, "comment", pr.number, comment.id, "",
                comment.author_id, parse_references(comment.body))
        rows = self._conn.execute(
            "SELECT * FROM cross_references WHERE repo_id = ?"
            " AND source_number = ?"
            " AND source_kind IN ('issue', 'comment') ORDER BY id",
            (current.id, pr.number)).fetchall()
        return [_row_to_ref(r) for r in rows]

    def closing_references(self, viewer: User | None, owner: object,
                           repo: object, number: object
                           ) -> list[PrClosingReference]:
        """What merging this pull request would close,
        from the closing keywords in its current body
        and live comments — shown before merge, never
        discovered after it (S-127's law)."""
        pr = self._require_pr(viewer, owner, repo, number)
        current = self._repos.get_repository(owner, repo)
        assert current is not None
        texts = [pr.body]
        texts.extend(
            c.body for c in
            self.list_comments(viewer, owner, repo, number))
        found: list[PrClosingReference] = []
        seen: set[tuple[int, int]] = set()
        for text in texts:
            for ref in parse_closing_references(text):
                if ref.target_number is None:
                    continue
                if ref.target_owner is None:
                    target_repo = current
                else:
                    target_repo = self._repos.get_repository(
                        ref.target_owner, ref.target_repo)
                    if target_repo is None:
                        continue
                item = self._issues.resolve_number(
                    target_repo.owner, target_repo.name,
                    ref.target_number)
                if item is None:
                    continue  # a reference to nothing closes nothing
                if target_repo.id == current.id \
                        and ref.target_number == pr.number:
                    continue  # a pull request does not close itself
                key = (target_repo.id, int(ref.target_number))
                if key in seen:
                    continue
                seen.add(key)
                found.append(PrClosingReference(
                    target_repo=target_repo.full_name,
                    target_number=int(ref.target_number),
                    target_kind=item.kind, raw=ref.raw))
        return found

    def closing_notice(self, viewer: User | None, owner: object,
                       repo: object, number: object) -> list[str]:
        """The closing list in plain words, one line
        per item that would close on merge."""
        return [ref.notice for ref in
                self.closing_references(viewer, owner, repo, number)]


def render_pr_timeline(events: list[PrTimelineEvent]) -> str:
    """The timeline as an HTML list of plain-word
    lines — meaning in the text, never a colour."""
    items = "".join(
        '<li class="timeline-event" data-kind="'
        + escape_html_text(e.kind) + '">'
        + escape_html_text(describe_pr_event(e)) + "</li>"
        for e in events)
    return f'<ol class="timeline">{items}</ol>'


def render_conversation(items: list[ConversationItem]) -> str:
    """The merged conversation as HTML: comments as
    speech (author named, body through S-010, an
    *edited* marker when the comment was edited) and
    timeline events as plain-word happenings, in the
    stream's own order."""
    parts = ['<ol class="conversation">']
    for item in items:
        if item.is_comment:
            comment = item.comment
            assert comment is not None
            edited = (' <span class="edited">edited</span>'
                      if comment.was_edited else "")
            parts.append(
                '<li class="conversation-comment">'
                f'<p class="comment-author">'
                f"{escape_html_text(item.author)} commented</p>"
                f'<p class="comment-body">'
                f"{escape_html_text(comment.body)}</p>"
                f"{edited}</li>")
        else:
            assert item.event is not None
            parts.append(
                '<li class="timeline-event" data-kind="'
                + escape_html_text(item.event.kind) + '">'
                + escape_html_text(describe_pr_event(item.event))
                + "</li>")
    parts.append("</ol>")
    return "\n".join(parts)


def render_closing_notice(lines: list[str]) -> str:
    """The closing display: each closing said in
    words, or — when the prose carries no closing
    keyword — the honest sentence that merging
    closes nothing."""
    if not lines:
        return ('<p class="closing-notice">Merging this pull request '
                "will not close any issue.</p>")
    items = "".join(
        f"<li>{escape_html_text(line)}</li>" for line in lines)
    return f'<ul class="closing-notice">{items}</ul>'
