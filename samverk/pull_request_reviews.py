"""Pull request review submission (S-148).

A review is one act with one verdict: a reviewer looks
at the whole pull request and submits a single review
carrying a verdict — approve, comment, or request
changes — and a summary that says why.

- **One pending review per reviewer, autosaved.** While
  a review is being composed it lives as a pending
  draft (`pull_request_pending_reviews`, migration 53):
  one row per (pull request, reviewer), replaced whole
  on every `save_pending_review` — that replacement IS
  the autosave, so what the composer last saved is what
  a later visit finds, on any device, with no explicit
  save step to forget. A pending draft may hold a
  verdict not yet chosen and a summary still being
  written; it is unpublished, so it is not audited (the
  S-136/S-145 personal-state pattern) and nobody else
  can read it — every pending read scopes by the
  reviewer's own account id. `discard_pending_review`
  removes it and reports whether anything was there.
- **Submission is the audited act.** `submit_review`
  takes an explicit verdict + summary, or falls back to
  the pending draft's when they are not given; the
  submitted review and the pending draft's removal land
  in one transaction, so a submitted review is never
  also still pending. The review records the head oid
  as it stood at submission (through S-145's diff road,
  so same-repo and cross-fork heads are both honest) —
  S-149's freshness judgment reads that record. One
  event: `repo.pull_request.review_submit` (taxonomy
  append-only +1, 104 events), its detail naming the
  verdict, never the summary.
- **The verdict law.** The closed set is `approve`,
  `comment`, `request_changes`; anything else is
  refused `verdict_invalid`. A request for changes
  must carry a summary (`summary_required`) — asking
  for work while saying nothing is not a review. The
  pull request's own author may submit a comment
  review, but approving or requesting changes on one's
  own pull request is refused `self_review`: a verdict
  on your own work vouches for nothing, and later gates
  (S-164) read approvals as other people's word.
- **Closed pull requests take no reviews**
  (`pull_request_closed`, the S-143 reason); drafts
  may be reviewed, as they may be commented on. Every
  surface reads through S-141's seam, so a stranger to
  a private repository gets the uniform
  `pull_request_not_found`.
- **The summary seam.** `reviews_for` lists submitted
  reviews oldest first; `review_summary` counts them,
  counts each verdict, and names the latest submitted
  verdict per reviewer (`latest_by_reviewer`) with the
  whole position said in words — the record S-149
  marks stale and S-164's gates consult.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .issues import IssueError, IssueStore, _validate_body
from .pull_request_files import PullRequestFilesStore
from .pull_requests import PullRequestError, PullRequestStore
from .repositories import RepositoryStore

__all__ = [
    "PendingReview", "PullRequestReviewStore", "Review",
    "ReviewSummary", "VERDICTS", "render_pending_review",
    "render_review", "render_review_summary",
]

# The closed verdict set: what a reviewer may submit,
# mapped to the verdict word stored on the review.
VERDICTS = {
    "approve": "approved",
    "comment": "commented",
    "request_changes": "changes_requested",
}

_VERDICT_WORDS = {
    "approved": "Approved",
    "commented": "Commented",
    "changes_requested": "Requested changes",
}


@dataclass(frozen=True)
class PendingReview:
    pull_request_id: int
    number: int
    reviewer_id: int
    verdict: str             # '' while not yet chosen
    summary: str
    created_at: int
    updated_at: int

    @property
    def verdict_words(self) -> str:
        if not self.verdict:
            return "No verdict chosen yet"
        return _VERDICT_WORDS[VERDICTS[self.verdict]]


@dataclass(frozen=True)
class Review:
    id: int
    pull_request_id: int
    number: int
    reviewer_id: int
    verdict: str             # approved|commented|changes_requested
    summary: str
    head_oid: str            # the head as it stood at submission
    submitted_at: int

    @property
    def verdict_words(self) -> str:
        return _VERDICT_WORDS[self.verdict]


@dataclass(frozen=True)
class ReviewSummary:
    total: int
    approved: int
    commented: int
    changes_requested: int
    latest_by_reviewer: dict  # reviewer_id -> verdict word stored

    @property
    def has_approval(self) -> bool:
        return "approved" in self.latest_by_reviewer.values()

    @property
    def has_change_request(self) -> bool:
        return "changes_requested" in self.latest_by_reviewer.values()

    @property
    def words(self) -> str:
        if self.total == 0:
            return "No reviews have been submitted yet."
        parts = []
        if self.approved:
            parts.append(
                f"{self.approved} approved")
        if self.changes_requested:
            parts.append(
                f"{self.changes_requested} requested changes")
        if self.commented:
            parts.append(f"{self.commented} commented")
        noun = "review" if self.total == 1 else "reviews"
        return f"{self.total} {noun} submitted: " + ", ".join(parts) + "."


def _row_to_pending(row: sqlite3.Row, number: int) -> PendingReview:
    return PendingReview(
        pull_request_id=row["pull_request_id"], number=number,
        reviewer_id=row["reviewer_id"], verdict=row["verdict"],
        summary=row["summary"], created_at=row["created_at"],
        updated_at=row["updated_at"])


def _row_to_review(row: sqlite3.Row, number: int) -> Review:
    return Review(
        id=row["id"], pull_request_id=row["pull_request_id"],
        number=number, reviewer_id=row["reviewer_id"],
        verdict=row["verdict"], summary=row["summary"],
        head_oid=row["head_oid"], submitted_at=row["submitted_at"])


class PullRequestReviewStore:
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
        self._files = PullRequestFilesStore(
            conn, repositories, accounts, issues, audit=audit,
            time_fn=time_fn)

    # -- internals ---------------------------------------------------
    def _validate_verdict(self, verdict: object,
                          *, allow_empty: bool) -> str:
        if verdict is None or verdict == "":
            if allow_empty:
                return ""
            raise PullRequestError(
                "verdict_invalid",
                "A review needs a verdict: approve, comment, "
                "or request changes.")
        if verdict not in VERDICTS:
            raise PullRequestError(
                "verdict_invalid",
                "A review's verdict is approve, comment, or "
                "request changes.")
        return str(verdict)

    def _validate_summary(self, summary: object) -> str:
        if summary is None:
            return ""
        if not isinstance(summary, str):
            raise PullRequestError(
                "summary_invalid", "A review summary is text.")
        if summary == "":
            return ""
        try:
            return _validate_body(summary)
        except IssueError as exc:
            raise PullRequestError(exc.reason, str(exc)) from None

    def _require_open(self, pr) -> None:
        if pr.state == "closed":
            raise PullRequestError(
                "pull_request_closed",
                "A closed pull request cannot be reviewed; "
                "reopen it first.")

    def _check_verdict_law(self, actor: User, pr, verdict: str,
                           summary: str) -> None:
        if verdict == "request_changes" and not summary.strip():
            raise PullRequestError(
                "summary_required",
                "Requesting changes needs a summary saying "
                "what should change.")
        if actor.id == pr.author_id and verdict != "comment":
            raise PullRequestError(
                "self_review",
                "The pull request's author can comment on "
                "their own pull request, but cannot approve "
                "it or request changes on it — a verdict on "
                "your own work vouches for nothing.")

    def _pending_row(self, pull_request_id: int, reviewer_id: int):
        return self._conn.execute(
            "SELECT * FROM pull_request_pending_reviews"
            " WHERE pull_request_id = ? AND reviewer_id = ?",
            (pull_request_id, reviewer_id)).fetchone()

    def _emit(self, actor: User, owner, repo, number: int,
              detail: dict, source_ip: str | None) -> None:
        if self._audit is not None:
            current = self._repos.get_repository(owner, repo)
            target = (f"{current.full_name}#{number}"
                      if current is not None else f"#{number}")
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.pull_request.review_submit",
                target_kind="repo", target_id=target,
                outcome="success", source_ip=source_ip, detail=detail)

    # -- pending review (the autosaved draft) -------------------------
    def save_pending_review(self, actor: User, owner: object,
                            repo: object, number: object, *,
                            verdict: object = None,
                            summary: object = None,
                            source_ip: str | None = None
                            ) -> PendingReview:
        """Autosave the reviewer's pending review: one
        row per (pull request, reviewer), replaced whole
        on every save. Not audited — nothing is
        published yet."""
        pr = self._prs.get_pull_request(actor, owner, repo, number)
        self._require_open(pr)
        chosen = self._validate_verdict(verdict, allow_empty=True)
        text = self._validate_summary(summary)
        now = int(self._now())
        with self._conn:  # commits before the answer
            self._conn.execute(
                "INSERT INTO pull_request_pending_reviews"
                " (pull_request_id, reviewer_id, verdict, summary,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (pull_request_id, reviewer_id)"
                " DO UPDATE SET verdict = excluded.verdict,"
                " summary = excluded.summary,"
                " updated_at = excluded.updated_at",
                (pr.id, actor.id, chosen, text, now, now))
        row = self._pending_row(pr.id, actor.id)
        assert row is not None
        return _row_to_pending(row, pr.number)

    def pending_review_for(self, viewer: User, owner: object,
                           repo: object, number: object
                           ) -> PendingReview | None:
        """The viewer's own pending review, or None.
        Pending drafts are personal: no seam reads
        another reviewer's draft."""
        pr = self._prs.get_pull_request(viewer, owner, repo, number)
        if viewer is None:
            return None
        row = self._pending_row(pr.id, viewer.id)
        return _row_to_pending(row, pr.number) if row else None

    def discard_pending_review(self, actor: User, owner: object,
                               repo: object, number: object) -> bool:
        """Throw the pending draft away. True when one
        was there to discard."""
        pr = self._prs.get_pull_request(actor, owner, repo, number)
        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM pull_request_pending_reviews"
                " WHERE pull_request_id = ? AND reviewer_id = ?",
                (pr.id, actor.id))
        return int(cur.rowcount) > 0

    # -- submission -----------------------------------------------------
    def submit_review(self, actor: User, owner: object, repo: object,
                      number: object, *, verdict: object = None,
                      summary: object = None,
                      source_ip: str | None = None) -> Review:
        """Submit one review. An explicit verdict and
        summary win; what is not given falls back to the
        pending draft's, and the draft is consumed in the
        same transaction that lands the review."""
        pr = self._prs.get_pull_request(actor, owner, repo, number)
        self._require_open(pr)
        pending = self._pending_row(pr.id, actor.id)
        if verdict is None and pending is not None:
            verdict = pending["verdict"]
        if summary is None and pending is not None:
            summary = pending["summary"]
        chosen = self._validate_verdict(verdict, allow_empty=False)
        text = self._validate_summary(summary)
        self._check_verdict_law(actor, pr, chosen, text)
        _diff, _base_oid, head_oid = self._files._diff_for(
            actor, owner, repo, pr)
        now = int(self._now())
        with self._conn:  # review lands, draft consumed, together
            cur = self._conn.execute(
                "INSERT INTO pull_request_reviews"
                " (pull_request_id, reviewer_id, verdict, summary,"
                " head_oid, submitted_at) VALUES (?, ?, ?, ?, ?, ?)",
                (pr.id, actor.id, VERDICTS[chosen], text,
                 head_oid, now))
            self._conn.execute(
                "DELETE FROM pull_request_pending_reviews"
                " WHERE pull_request_id = ? AND reviewer_id = ?",
                (pr.id, actor.id))
        review = Review(
            id=int(cur.lastrowid), pull_request_id=pr.id,
            number=pr.number, reviewer_id=actor.id,
            verdict=VERDICTS[chosen], summary=text,
            head_oid=head_oid, submitted_at=now)
        self._emit(actor, owner, repo, pr.number,
                   {"number": pr.number, "review_id": review.id,
                    "verdict": review.verdict}, source_ip)
        return review

    # -- reads ------------------------------------------------------------
    def reviews_for(self, viewer: User | None, owner: object,
                    repo: object, number: object) -> list[Review]:
        """Every submitted review on this pull request,
        oldest first."""
        pr = self._prs.get_pull_request(viewer, owner, repo, number)
        rows = self._conn.execute(
            "SELECT * FROM pull_request_reviews"
            " WHERE pull_request_id = ? ORDER BY id",
            (pr.id,)).fetchall()
        return [_row_to_review(r, pr.number) for r in rows]

    def review_summary(self, viewer: User | None, owner: object,
                       repo: object, number: object) -> ReviewSummary:
        """The submitted-review position in counts and
        words, with each reviewer's latest verdict."""
        reviews = self.reviews_for(viewer, owner, repo, number)
        latest: dict = {}
        for review in reviews:
            latest[review.reviewer_id] = review.verdict
        return ReviewSummary(
            total=len(reviews),
            approved=sum(1 for r in reviews
                         if r.verdict == "approved"),
            commented=sum(1 for r in reviews
                          if r.verdict == "commented"),
            changes_requested=sum(
                1 for r in reviews
                if r.verdict == "changes_requested"),
            latest_by_reviewer=latest)


def render_pending_review(pending: PendingReview | None) -> str:
    """The composer's autosaved state, said in words —
    so a returning reviewer sees what will be resumed."""
    if pending is None:
        return ('<p class="pending-review">No review is being '
                "composed for this pull request.</p>")
    return (
        '<div class="pending-review">'
        f"<p>Composing a review · "
        f"{escape_html_text(pending.verdict_words)}</p>"
        f'<p class="summary">{escape_html_text(pending.summary)}</p>'
        "</div>")


def render_review(review: Review) -> str:
    """One submitted review: its verdict in words, its
    summary through S-010, never a colour alone."""
    return (
        '<div class="review">'
        f'<p class="verdict">{escape_html_text(review.verdict_words)}</p>'
        f'<p class="summary">{escape_html_text(review.summary)}</p>'
        "</div>")


def render_review_summary(summary: ReviewSummary) -> str:
    """The review position of a pull request, in words."""
    return (f'<p class="review-summary">'
            f"{escape_html_text(summary.words)}</p>")
