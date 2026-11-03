"""Pull request review assignment (S-152).

Review assignment: individuals and teams requested;
re-request and dismissal recorded. This slice is the
manual half of the review-request record S-151 began:
where S-151 auto-requests the owners a CODEOWNERS file
names, a person with a stake in the pull request can
here request reviewers directly, dismiss a request
that should no longer stand, and re-request one that
was dismissed — with every one of those acts on the
record, never a silent deletion.

- **One table, two sources** (migration 56's
  `pull_request_review_requests`, extended by
  migration 57). Manual requests ride the same table
  with `source='manual'`: the owner token verbatim
  (`owner_ref`), the Samverk account it resolves to
  when it is a plain `@username` that exists
  (`user_id`, NULL for unknown names and for team
  tokens, exactly as S-151 resolves), and the head
  oid the request was made against.
- **Tokens are reviewers, in words.** A manual token
  must be `@name` or `@org/team`; an email address is
  not a reviewer here (it names a code owner in a
  CODEOWNERS file, S-151, but it is not an account or
  a team a person can ask). A batch validates whole
  before anything is stored: any token that is not
  of that shape refuses the whole batch with
  `owner_ref_invalid` and stores nothing. The pull
  request's own author is never requested on their
  own pull request: an author token in a batch is
  excluded silently, the other tokens still land —
  the same author honesty as S-151's sync.
- **Dismissal is a recorded act, never a deletion**
  (migration 57). A request row carries its state
  (`requested` / `dismissed`), who dismissed it and
  when, and how many times it has been re-requested;
  the `pull_request_review_request_events` table
  keeps one row per act (request, dismissal,
  re-request) so the history stays provable even
  after a re-request clears the dismissal stamp from
  the request row itself. A dismissed request stays
  visible through `requests_for`, said as dismissed.
- **The dismissal-source rule.** Dismissal targets
  the active request row for that `owner_ref`,
  whatever its source, preferring the `manual` row
  when both a manual and a codeowners row for the
  same token are active, and the `codeowners` row
  otherwise. One dismissal dismisses one row. Because
  dismissal is state on the row and never a deletion,
  S-151's codeowners sync — which inserts only
  owner_refs not already on record for its source —
  can never resurrect a dismissed codeowners row: the
  row is still there, so the sync sees it as already
  requested and adds nothing.
- **Re-request reactivates.** Requesting a token
  whose manual request was dismissed reactivates
  that same row (state back to `requested`, the
  dismissal stamp cleared, `rerequest_count` one
  higher, a re-request event row written) instead of
  inserting a second row. Requesting a token already
  actively requested from the same source is a quiet
  no-op for that token.
- **Who may assign.** The pull request's author, or
  a writer or admin on the base repository, for both
  requesting and dismissing. Anyone else who can see
  the pull request is refused `permission_denied`,
  said in the message; a stranger to a private
  repository gets the uniform `pull_request_not_found`
  from S-141's read seam, before any permission
  question is asked. A closed pull request takes no
  new requests (`pull_request_closed`, nothing
  stored).
- **Audited only on real change** (taxonomy
  append-only +3, 110 events:
  `repo.pull_request.review_request`,
  `repo.pull_request.review_rerequest`,
  `repo.pull_request.review_dismiss`). A no-op
  request emits nothing; a re-request emits
  `review_rerequest`, never a second
  `review_request`. Every detail names the pull
  request number and the owner_refs — never bodies.
"""

from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .issues import IssueStore
from .permissions import can_write
from .pull_request_forks import ForkPullRequestStore
from .pull_requests import PullRequestError, PullRequestStore
from .repositories import RepositoryStore

__all__ = [
    "AssignmentReport", "ReviewAssignment",
    "ReviewAssignmentStore", "render_review_assignment",
    "render_review_assignments",
]

_OWNER_RE = re.compile(
    r"^@[A-Za-z0-9][A-Za-z0-9._-]*"
    r"(?:/[A-Za-z0-9][A-Za-z0-9._-]*)?$")


@dataclass(frozen=True)
class ReviewAssignment:
    id: int
    pull_request_id: int     # pull_requests row id
    number: int              # the pull request's #n
    owner_ref: str           # the owner token, verbatim
    user_id: int | None      # resolved account, plain @username only
    source: str              # 'manual' | 'codeowners'
    head_oid: str            # the head this request was made against
    created_at: int
    state: str = "requested"  # 'requested' | 'dismissed'
    dismissed_by: int | None = None
    dismissed_by_username: str = ""
    dismissed_at: int | None = None
    rerequest_count: int = 0

    @property
    def is_dismissed(self) -> bool:
        return self.state == "dismissed"

    @property
    def is_requested(self) -> bool:
        return self.state == "requested"

    @property
    def state_words(self) -> str:
        """The state in words — never a colour alone."""
        if self.is_dismissed:
            return "dismissed"
        return "requested"

    @property
    def resolution_words(self) -> str:
        if self.user_id is not None:
            return f"Samverk account #{self.user_id}"
        return "No Samverk account by that name"

    @property
    def dismissal_words(self) -> str:
        if not self.is_dismissed:
            return ""
        who = (self.dismissed_by_username
               or (f"account #{self.dismissed_by}"
                   if self.dismissed_by is not None else "unknown"))
        when = self.dismissed_at if self.dismissed_at is not None else 0
        return f"dismissed by {who} at {when}"

    @property
    def words(self) -> str:
        parts = [f"{self.owner_ref} — {self.state_words}",
                 f"source {self.source}",
                 self.resolution_words]
        if self.is_dismissed and self.dismissal_words:
            parts.append(self.dismissal_words)
        if self.rerequest_count:
            parts.append(
                f"re-requested {self.rerequest_count} time(s)")
        if self.head_oid:
            parts.append(f"against head {self.head_oid}")
        return "; ".join(parts) + "."


@dataclass(frozen=True)
class AssignmentReport:
    number: int
    requested_now: tuple = ()     # of str, newly inserted
    rerequested: tuple = ()       # of str, reactivated
    already_requested: tuple = ()  # of str, active no-ops
    skipped_author: tuple = ()    # of str, author tokens excluded

    @property
    def requested(self) -> tuple:
        return self.requested_now

    @property
    def words(self) -> str:
        parts = []
        if self.requested_now:
            parts.append("requested now: "
                         + ", ".join(self.requested_now))
        if self.rerequested:
            parts.append("re-requested: "
                         + ", ".join(self.rerequested))
        if self.already_requested:
            parts.append("already requested: "
                         + ", ".join(self.already_requested))
        if self.skipped_author:
            parts.append("author token(s) not requested: "
                         + ", ".join(self.skipped_author))
        if not parts:
            return "No reviewers were requested."
        return "; ".join(parts) + "."


def _row_value(row: sqlite3.Row, key: str, default=None):
    return row[key] if key in row.keys() else default


class ReviewAssignmentStore:
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
        self._forks = ForkPullRequestStore(
            conn, repositories, accounts, issues, audit=audit,
            time_fn=time_fn)

    # -- internals ---------------------------------------------------
    def _resolve_user_id(self, owner_ref: str) -> int | None:
        """An account id only for a plain @username token
        naming an account that exists — team tokens
        record NULL, by the S-151 design."""
        if not owner_ref.startswith("@") or "/" in owner_ref:
            return None
        user = self._accounts.get_by_username(owner_ref[1:])
        return user.id if user is not None else None

    def _is_author(self, pr, owner_ref: str) -> bool:
        author = self._accounts.get_by_id(pr.author_id)
        if author is None:
            return False
        if owner_ref.startswith("@") and "/" not in owner_ref:
            return owner_ref[1:].lower() == author.username_lower
        return False

    def _require_permission(self, actor: User, owner, repo, number):
        """The PR through S-141's uniform seam, plus the
        assignment permission: author, or a writer/admin
        on the base repository."""
        pr = self._prs.get_pull_request(actor, owner, repo, number)
        current = self._repos.get_repository(owner, repo)
        assert current is not None
        if actor.id != pr.author_id and not can_write(actor, current):
            raise PullRequestError(
                "permission_denied",
                "permission_denied — only the pull request's "
                "author or a writer or admin on the base "
                "repository can request or dismiss reviewers.")
        return pr, current

    def _row_to_assignment(self, row: sqlite3.Row,
                           number: int) -> ReviewAssignment:
        dismissed_by = _row_value(row, "dismissed_by")
        dismissed_by = int(dismissed_by) if dismissed_by is not None else None
        username = ""
        if dismissed_by is not None:
            user = self._accounts.get_by_id(dismissed_by)
            if user is not None:
                username = user.username
        dismissed_at = _row_value(row, "dismissed_at")
        return ReviewAssignment(
            id=row["id"], pull_request_id=row["pull_request_id"],
            number=number, owner_ref=row["owner_ref"],
            user_id=row["user_id"], source=row["source"],
            head_oid=row["head_oid"], created_at=row["created_at"],
            state=str(_row_value(row, "state", "requested")
                      or "requested"),
            dismissed_by=dismissed_by,
            dismissed_by_username=username,
            dismissed_at=(int(dismissed_at)
                          if dismissed_at is not None else None),
            rerequest_count=int(
                _row_value(row, "rerequest_count", 0) or 0))

    def _assignment_by_id(self, row_id: int,
                          number: int) -> ReviewAssignment | None:
        row = self._conn.execute(
            "SELECT * FROM pull_request_review_requests"
            " WHERE id = ?", (row_id,)).fetchone()
        return self._row_to_assignment(row, number) if row else None

    def _record_event(self, row_id: int, pr, owner_ref: str,
                      source: str, kind: str, actor_id: int,
                      now: int) -> None:
        self._conn.execute(
            "INSERT INTO pull_request_review_request_events"
            " (review_request_id, pull_request_id, owner_ref,"
            " source, kind, actor_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (row_id, pr.id, owner_ref, source, kind, actor_id, now))

    def _emit(self, actor: User, action: str, owner, repo,
              number: int, refs: list[str],
              source_ip: str | None) -> None:
        if self._audit is not None and refs:
            current = self._repos.get_repository(owner, repo)
            target = (f"{current.full_name}#{number}"
                      if current is not None else f"#{number}")
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action=action, target_kind="repo", target_id=target,
                outcome="success", source_ip=source_ip,
                detail={"number": number, "owner_refs": list(refs)})

    def _validate_batch(self, owner_refs) -> list[str]:
        if isinstance(owner_refs, (str, bytes)) \
                or not isinstance(owner_refs, (list, tuple)):
            raise PullRequestError(
                "owner_ref_invalid",
                "owner_ref_invalid — name the reviewers to "
                "request as a list of @name or @org/team tokens.")
        refs: list[str] = []
        for token in owner_refs:
            if not isinstance(token, str) \
                    or not _OWNER_RE.match(token):
                raise PullRequestError(
                    "owner_ref_invalid",
                    f"owner_ref_invalid — {token!r} is not a "
                    "reviewer: a reviewer is @name or @org/team "
                    "(an email address is not a reviewer). "
                    "Nothing was requested.")
            if token not in refs:
                refs.append(token)
        return refs

    # -- requesting ----------------------------------------------------
    def request_reviewers(self, actor: User, owner: object,
                          repo: object, number: object,
                          owner_refs: object, *,
                          source_ip: str | None = None
                          ) -> AssignmentReport:
        """Manually request reviewers (source='manual').
        The whole batch validates first; the author's own
        token is excluded and the rest still land."""
        pr, _current = self._require_permission(
            actor, owner, repo, number)
        if pr.state == "closed":
            raise PullRequestError(
                "pull_request_closed",
                "pull_request_closed — a closed pull request "
                "takes no review requests; reopen it first. "
                "Nothing was requested.")
        refs = self._validate_batch(owner_refs)
        skipped = [r for r in refs if self._is_author(pr, r)]
        refs = [r for r in refs if r not in skipped]
        requested_now: list[str] = []
        rerequested: list[str] = []
        already: list[str] = []
        now = int(self._now())
        with self._conn:  # commits before the answer
            for owner_ref in refs:
                row = self._conn.execute(
                    "SELECT * FROM pull_request_review_requests"
                    " WHERE pull_request_id = ? AND owner_ref = ?"
                    " AND source = 'manual'",
                    (pr.id, owner_ref)).fetchone()
                if row is None:
                    cur = self._conn.execute(
                        "INSERT INTO pull_request_review_requests"
                        " (pull_request_id, owner_ref, user_id,"
                        " source, head_oid, created_at, state,"
                        " dismissed_by, dismissed_at,"
                        " rerequest_count)"
                        " VALUES (?, ?, ?, 'manual', ?, ?,"
                        " 'requested', NULL, NULL, 0)",
                        (pr.id, owner_ref,
                         self._resolve_user_id(owner_ref),
                         pr.head_oid, now))
                    self._record_event(
                        int(cur.lastrowid), pr, owner_ref,
                        "manual", "request", actor.id, now)
                    requested_now.append(owner_ref)
                elif str(_row_value(row, "state", "requested")
                         or "requested") == "dismissed":
                    self._conn.execute(
                        "UPDATE pull_request_review_requests"
                        " SET state = 'requested',"
                        " dismissed_by = NULL, dismissed_at = NULL,"
                        " rerequest_count = rerequest_count + 1,"
                        " head_oid = ? WHERE id = ?",
                        (pr.head_oid, row["id"]))
                    self._record_event(
                        int(row["id"]), pr, owner_ref, "manual",
                        "rerequest", actor.id, now)
                    rerequested.append(owner_ref)
                else:
                    already.append(owner_ref)
        if requested_now:
            self._emit(actor, "repo.pull_request.review_request",
                       owner, repo, pr.number, requested_now,
                       source_ip)
        if rerequested:
            self._emit(actor, "repo.pull_request.review_rerequest",
                       owner, repo, pr.number, rerequested,
                       source_ip)
        return AssignmentReport(
            number=pr.number,
            requested_now=tuple(requested_now),
            rerequested=tuple(rerequested),
            already_requested=tuple(already),
            skipped_author=tuple(skipped))

    # -- dismissal -------------------------------------------------------
    def dismiss_request(self, actor: User, owner: object,
                        repo: object, number: object,
                        owner_ref: object, *,
                        source_ip: str | None = None
                        ) -> ReviewAssignment:
        """Dismiss the active request for one owner_ref.
        Per the module's dismissal-source rule, the manual
        row is preferred when both sources are active for
        the token, otherwise the codeowners row. The row
        stays on record, stamped with who dismissed it
        and when; nothing is deleted."""
        pr, _current = self._require_permission(
            actor, owner, repo, number)
        row = None
        if isinstance(owner_ref, str):
            row = self._conn.execute(
                "SELECT * FROM pull_request_review_requests"
                " WHERE pull_request_id = ? AND owner_ref = ?"
                " AND state = 'requested'"
                " ORDER BY CASE source WHEN 'manual' THEN 0"
                " ELSE 1 END, id LIMIT 1",
                (pr.id, owner_ref)).fetchone()
        if row is None:
            raise PullRequestError(
                "request_not_found",
                "request_not_found — there is no active review "
                f"request for {owner_ref!r} on this pull request. "
                "Nothing was dismissed.")
        now = int(self._now())
        with self._conn:  # commits before the answer
            self._conn.execute(
                "UPDATE pull_request_review_requests"
                " SET state = 'dismissed', dismissed_by = ?,"
                " dismissed_at = ? WHERE id = ?",
                (actor.id, now, row["id"]))
            self._record_event(
                int(row["id"]), pr, str(row["owner_ref"]),
                str(row["source"]), "dismiss", actor.id, now)
        dismissed = self._assignment_by_id(int(row["id"]), pr.number)
        assert dismissed is not None
        self._emit(actor, "repo.pull_request.review_dismiss",
                   owner, repo, pr.number, [dismissed.owner_ref],
                   source_ip)
        return dismissed

    # -- reads ------------------------------------------------------------
    def requests_for(self, viewer: User | None, owner: object,
                     repo: object, number: object
                     ) -> list[ReviewAssignment]:
        """Every recorded review request on this pull
        request, in insertion order, dismissed rows
        included and said as dismissed."""
        pr = self._prs.get_pull_request(viewer, owner, repo, number)
        rows = self._conn.execute(
            "SELECT * FROM pull_request_review_requests"
            " WHERE pull_request_id = ? ORDER BY id",
            (pr.id,)).fetchall()
        return [self._row_to_assignment(r, pr.number) for r in rows]


def render_review_assignment(row: ReviewAssignment) -> str:
    """One review request, in plain words."""
    return (
        '<li class="review-assignment">'
        f"{escape_html_text(row.words)}</li>")


def render_review_assignments(report_or_rows) -> str:
    """The review-assignment position in plain words —
    a request report's summary, or the recorded
    requests listed with each one's state, source,
    dismissal and re-request count said in words.
    Never a colour alone; every value escapes
    through S-010."""
    if isinstance(report_or_rows, AssignmentReport):
        report = report_or_rows
        return (
            '<div class="review-assignments">'
            f"<p>{escape_html_text(report.words)}</p></div>")
    rows = list(report_or_rows)
    if not rows:
        return ('<p class="review-assignments">No reviewers have '
                "been requested for this pull request.</p>")
    items = "".join(render_review_assignment(r) for r in rows)
    return f'<ul class="review-assignments">{items}</ul>'
