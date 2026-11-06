"""Pull request review notifications (S-165).

Review requests and submissions emit Part XI events
with reasons. The review acts themselves already stand
audited — S-151's `repo.pull_request.codeowners_request`,
S-152's `repo.pull_request.review_request` /
`review_rerequest` / `review_dismiss`, and S-148's
`repo.pull_request.review_submit` — and S-139's outbox
already carries those verbs as repo-wide outbound
events. What no record did until this slice is turn
them into *addressed* notifications: one row per
recipient, naming who needs to hear it and why. This
store is that turning, on the pattern S-139 set:

- **Derived from the witness, exactly once.** Every
  review act already writes exactly one audit row (the
  slices' standing law: real changes only, retries
  quiet). This store materialises those rows — one
  notification per (audit row, recipient) under a
  UNIQUE constraint on that pair, inserted with
  OR IGNORE — so syncing twice notifies nobody twice,
  a refused or no-op act (which never reached the audit
  log) notifies nobody at all, and a second submission
  is a second audit row and rightly a second
  notification. S-221 completes Part XI's canonical
  event store over this shape; S-224's inbox and
  S-223's reason display read from here.
- **The verb set is the review family.** Exactly the
  five audited review acts above, computed from the
  frozen taxonomy, so nothing outside the family (PR
  creation, merges, comments, suggestions) can leak in,
  and no new taxonomy event is claimed: the taxonomy
  stands at 119 events and this store, like S-131's
  timeline and S-139's outbox, is derived data.
- **Every notification carries its reason** (the
  S-223 vocabulary, stored and shown): a request,
  re-request, or CODEOWNERS request reaches the
  requested reviewer with reason `review-requested`;
  a dismissal reaches the dismissed reviewer with
  reason `review-dismissed`; a submission reaches the
  pull request's author with reason `author`. The
  audit row's own detail rides along unchanged
  (numbers, owner_refs, the submission's verdict —
  never summaries, titles, or bodies).
- **Addressed means resolvable, readable, and not
  oneself.** A requested token notifies only when it
  is a plain `@username` naming an account that exists
  — the S-151/S-152 resolution rule — so team tokens
  notify nobody until team expansion lands (S-195),
  and unknown names notify nobody. A recipient is
  notified only when they can read the repository
  (S-209's rule applied at emission: a notification
  never reveals a pull request its recipient cannot
  read), and nobody is ever notified of their own act.
- **Reads are honest about whose they are.** `inbox`
  takes the recipient themselves — there is no
  cross-user read of an inbox — and syncs first, so
  the answer is never stale. The per-pull-request
  listing reads through S-141's seam, so a stranger
  to a private repository gets the uniform
  `pull_request_not_found` before any notification
  is named. Migration 64 claims the one table;
  the store writes no audit row of its own.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .issues import IssueStore
from .permissions import can_read
from .pull_requests import PullRequestStore
from .repositories import Repository, RepositoryStore
from .taxonomy import REPO_EVENTS

__all__ = [
    "REASONS", "REASON_BY_VERB", "REVIEW_NOTIFICATION_VERBS",
    "ReviewNotification", "ReviewNotificationError",
    "ReviewNotificationStore", "render_review_notification",
    "render_review_notifications",
]

REVIEW_NOTIFICATION_VERBS = frozenset(
    verb for verb in REPO_EVENTS if verb in {
        "repo.pull_request.codeowners_request",
        "repo.pull_request.review_request",
        "repo.pull_request.review_rerequest",
        "repo.pull_request.review_dismiss",
        "repo.pull_request.review_submit",
    })

# The S-223 reason each verb notifies under, stored on
# every row and said in its words.
REASON_BY_VERB = {
    "repo.pull_request.codeowners_request": "review-requested",
    "repo.pull_request.review_request": "review-requested",
    "repo.pull_request.review_rerequest": "review-requested",
    "repo.pull_request.review_dismiss": "review-dismissed",
    "repo.pull_request.review_submit": "author",
}

REASONS = frozenset(REASON_BY_VERB.values())

_REASON_WORDS = {
    "review-requested": "review requested",
    "review-dismissed": "review request dismissed",
    "author": "you are the author",
}

_VERDICT_WORDS = {
    "approved": "approved",
    "commented": "commented on",
    "changes_requested": "requested changes on",
}


class ReviewNotificationError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class ReviewNotification:
    id: int
    audit_seq: int
    repo_id: int
    repository: str      # full name
    pull_request_id: int | None
    number: int | None
    recipient_id: int
    recipient: str       # display case
    actor_id: int | None
    actor: str           # display case; '' when unknown
    verb: str
    reason: str          # the S-223 reason, stored
    detail: dict
    created_at: int

    @property
    def action(self) -> str:
        return self.verb.rsplit(".", 1)[-1]

    @property
    def reason_words(self) -> str:
        return _REASON_WORDS.get(self.reason, self.reason)

    @property
    def words(self) -> str:
        """The notification said in plain words — the
        actor, what they did, where, and the reason it
        reached this recipient. Never a colour alone."""
        who = self.actor or "Someone"
        where = (f"{self.repository}#{self.number}"
                 if self.number is not None else self.repository)
        if self.verb == "repo.pull_request.review_submit":
            verdict = _VERDICT_WORDS.get(
                str(self.detail.get("verdict")), "reviewed")
            return (f"{who} {verdict} {where} "
                    f"(reason: {self.reason_words}).")
        if self.verb == "repo.pull_request.review_dismiss":
            return (f"{who} dismissed your review request on "
                    f"{where} (reason: {self.reason_words}).")
        return (f"{who} requested your review on {where} "
                f"(reason: {self.reason_words}).")


class ReviewNotificationStore:
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

    # -- materialisation -------------------------------------------
    def sync_repo(self, owner: object, repo: object) -> int:
        """Materialise this repository's audited review
        acts into addressed notifications; returns how
        many notifications were newly emitted (0 on a
        re-sync — exactly-once is the UNIQUE pair doing
        its work)."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise ReviewNotificationError(
                "repo_not_found", "No such repository.")
        return self._sync(current)

    def sync_all(self) -> int:
        """Materialise every repository's new review
        notifications; returns the total newly emitted."""
        total = 0
        rows = self._conn.execute(
            "SELECT id FROM repositories ORDER BY id").fetchall()
        for row in rows:
            current = self._repos.get_by_id(int(row["id"]))
            if current is not None:
                total += self._sync(current)
        return total

    def _sync(self, current: Repository) -> int:
        verbs = sorted(REVIEW_NOTIFICATION_VERBS)
        placeholders = ", ".join("?" for _ in verbs)
        rows = self._conn.execute(
            f"SELECT seq, ts, actor_id, action, target_id, detail"
            f" FROM audit_log WHERE action IN ({placeholders})"
            " AND (target_id = ? OR substr(target_id, 1, ?) = ?)"
            " ORDER BY seq",
            (*verbs, current.full_name, len(current.full_name) + 1,
             current.full_name + "#")).fetchall()
        emitted = 0
        pr_cache: dict = {}
        with self._conn:  # the batch lands whole, or not at all
            for row in rows:
                try:
                    detail = json.loads(row["detail"] or "{}")
                except ValueError:
                    detail = {}
                if not isinstance(detail, dict):
                    detail = {}
                number = detail.get("number")
                if not isinstance(number, int):
                    number = self._number_from_target(row["target_id"])
                pr_id, author_id = self._pr_facts(
                    current, number, pr_cache)
                recipients = self._recipients(
                    current, row, detail, author_id)
                for recipient_id, reason in recipients:
                    cur = self._conn.execute(
                        "INSERT OR IGNORE INTO"
                        " pull_request_review_notifications"
                        " (audit_seq, recipient_id, repo_id,"
                        " pull_request_id, number, actor_id, verb,"
                        " reason, detail_json, created_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (int(row["seq"]), recipient_id, current.id,
                         pr_id, number, row["actor_id"],
                         row["action"], reason,
                         row["detail"] or "{}", int(row["ts"])))
                    emitted += int(cur.rowcount)
        return emitted

    @staticmethod
    def _number_from_target(target_id: object) -> int | None:
        if not isinstance(target_id, str) or "#" not in target_id:
            return None
        tail = target_id.rsplit("#", 1)[-1]
        return int(tail) if tail.isdigit() else None

    def _pr_facts(self, current: Repository, number: int | None,
                  cache: dict):
        """(pull_request row id, author account id) for
        this repository's numbered pull request, resolved
        once per sync — the submission road addresses the
        author from the record, never from the detail."""
        if number is None:
            return None, None
        if number not in cache:
            row = self._conn.execute(
                "SELECT pr.id AS pr_id, i.author_id AS author_id"
                " FROM pull_requests pr"
                " JOIN issues i ON i.id = pr.issue_id"
                " WHERE pr.repo_id = ? AND i.number = ?",
                (current.id, number)).fetchone()
            cache[number] = (
                (int(row["pr_id"]), int(row["author_id"]))
                if row is not None else (None, None))
        return cache[number]

    def _recipients(self, current: Repository, row: sqlite3.Row,
                    detail: dict,
                    author_id: int | None) -> list:
        """Who one audited review act notifies, and under
        what reason — the module's addressing law in one
        place: resolvable, readable, never oneself."""
        verb = row["action"]
        reason = REASON_BY_VERB[verb]
        actor_id = row["actor_id"]
        candidates: list = []
        if verb == "repo.pull_request.review_submit":
            if author_id is not None:
                candidates.append(author_id)
        else:  # the request family addresses its tokens
            refs = detail.get("owner_refs")
            if isinstance(refs, list):
                for ref in refs:
                    resolved = self._resolve_ref(ref)
                    if resolved is not None:
                        candidates.append(resolved)
        out: list = []
        for recipient_id in candidates:
            if recipient_id == actor_id:
                continue  # nobody is notified of their own act
            if recipient_id in [r for r, _ in out]:
                continue
            recipient = self._accounts.get_by_id(recipient_id)
            if recipient is None or not can_read(recipient, current):
                continue  # never reveal what they cannot read
            out.append((recipient_id, reason))
        return out

    def _resolve_ref(self, ref: object) -> int | None:
        """An account id only for a plain @username token
        naming an account that exists — team tokens and
        unknown names resolve to nobody, exactly as
        S-151/S-152 resolve them."""
        if not isinstance(ref, str) or not ref.startswith("@") \
                or "/" in ref:
            return None
        user = self._accounts.get_by_username(ref[1:])
        return user.id if user is not None else None

    # -- reads -------------------------------------------------------
    def inbox(self, user: User | None, *, limit: int = 100
              ) -> list[ReviewNotification]:
        """The recipient's own review notifications,
        oldest first. Syncs every repository first, so
        the answer is never stale; an inbox belongs to
        its recipient, so there is no cross-user read
        and an anonymous caller has no inbox at all."""
        if user is None:
            raise ReviewNotificationError(
                "authentication_required",
                "Sign in to see your review notifications.")
        self.sync_all()
        clamped = max(1, min(int(limit), 500))
        rows = self._conn.execute(
            "SELECT * FROM pull_request_review_notifications"
            " WHERE recipient_id = ? ORDER BY id LIMIT ?",
            (user.id, clamped)).fetchall()
        return [self._to_notification(r) for r in rows]

    def count_for_recipient(self, user: User | None) -> int:
        return len(self.inbox(user, limit=500))

    def notifications_for_pull_request(
            self, viewer: User | None, owner: object, repo: object,
            number: object, *, limit: int = 100
            ) -> list[ReviewNotification]:
        """Every review notification addressed for this
        pull request, oldest first. The pull request is
        read through S-141's seam first, so a stranger
        to a private repository gets the uniform
        `pull_request_not_found`; the repository syncs
        before the listing, so it is never stale."""
        pr = self._prs.get_pull_request(viewer, owner, repo, number)
        current = self._repos.get_repository(owner, repo)
        assert current is not None
        self._sync(current)
        clamped = max(1, min(int(limit), 500))
        rows = self._conn.execute(
            "SELECT * FROM pull_request_review_notifications"
            " WHERE pull_request_id = ? ORDER BY id LIMIT ?",
            (pr.id, clamped)).fetchall()
        return [self._to_notification(r, current) for r in rows]

    def _to_notification(self, row: sqlite3.Row,
                         current: Repository | None = None
                         ) -> ReviewNotification:
        try:
            detail = json.loads(row["detail_json"] or "{}")
        except ValueError:
            detail = {}
        if current is None:
            current = self._repos.get_by_id(int(row["repo_id"]))
        recipient = self._accounts.get_by_id(int(row["recipient_id"]))
        actor = (self._accounts.get_by_id(int(row["actor_id"]))
                 if row["actor_id"] else None)
        return ReviewNotification(
            id=int(row["id"]), audit_seq=int(row["audit_seq"]),
            repo_id=int(row["repo_id"]),
            repository=current.full_name if current is not None else "",
            pull_request_id=row["pull_request_id"],
            number=row["number"],
            recipient_id=int(row["recipient_id"]),
            recipient=recipient.username if recipient else "",
            actor_id=row["actor_id"],
            actor=actor.username if actor else "",
            verb=row["verb"], reason=row["reason"],
            detail=detail if isinstance(detail, dict) else {},
            created_at=int(row["created_at"]))


def render_review_notification(notification: ReviewNotification) -> str:
    """One review notification, in plain words."""
    return (
        '<li class="review-notification">'
        f"{escape_html_text(notification.words)}</li>")


def render_review_notifications(rows) -> str:
    """A recipient's review notifications in plain
    words — each one's actor, act, pull request, and
    stored reason said outright. Never a colour alone;
    every value escapes through S-010."""
    rows = list(rows)
    if not rows:
        return ('<p class="review-notifications">No review '
                "notifications yet. When someone requests your "
                "review, dismisses a request, or reviews a pull "
                "request you wrote, it will be said here.</p>")
    items = "".join(render_review_notification(r) for r in rows)
    return f'<ul class="review-notifications">{items}</ul>'
