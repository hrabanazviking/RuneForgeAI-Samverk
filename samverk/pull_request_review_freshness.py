"""Pull request review freshness (S-149).

A review is submitted against the head as it stood at
that moment (S-148 stores that oid on the review). When
the head branch is pushed to, the code a review passed
judgment on is no longer the code on offer — whether
that push stale-dates the review is the repository's
own policy, and this slice is that policy plus the
judgment it drives.

- **The policy is per repository** (migration 54,
  `repo_review_freshness_policies`; no row is the
  default). Three modes, said in plain words:
  `never` — a push never stale-dates a review (the
  default: S-148's position stands unchanged until an
  owner chooses otherwise); `approvals` — an approval
  submitted against an older head goes stale when the
  head moves, while comments and change requests keep
  counting (the shape S-172's rules engine dismisses
  under); `verdicts` — approvals *and* change requests
  go stale on a push, while plain comment reviews,
  which gate nothing, keep counting under every mode.
  Setting the policy is a repository admin's act,
  audited under the frozen `repo.settings.change` with
  the key named (the S-129 settings pattern): a real
  change writes one row, a same-mode retry is a quiet
  no-op, an unknown mode is refused `policy_invalid`
  and stores nothing.
- **Freshness is judged on read, never stored** (the
  S-145/S-146 law). `freshness_for` re-reads the
  current head through S-145's diff road — so
  same-repo and cross-fork heads are both honest —
  and marks each submitted review fresh or stale by
  comparing its stored head oid against the head as
  it stands now, under the policy as it stands now.
  Changing the policy therefore re-judges reviews
  already submitted, in both directions: a review a
  push stale-dated under `approvals` counts again if
  the policy returns to `never`. No push hook writes
  stale flags that could disagree with the record.
- **Exactly which reviews still count, in words.**
  A review counts iff it is fresh. `FreshnessReport`
  carries every review with its state said in words
  and its reason, counts of fresh and stale, the
  counting tallies per verdict, and
  `latest_counting_by_reviewer` — each reviewer's
  latest *counting* verdict — the record S-164's
  required-review seam and S-172's dismissal rule
  consult, so a stale approval vouches for nothing
  wherever gates read review state.
- Every surface reads through S-141's seam, so a
  stranger to a private repository gets the uniform
  `pull_request_not_found`; the policy surfaces read
  through the repository seam with the uniform
  `repo_not_found`. State is always said in words,
  never a colour alone.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .issues import IssueStore
from .permissions import can_admin, can_read
from .pull_request_files import PullRequestFilesStore
from .pull_request_reviews import PullRequestReviewStore, Review
from .pull_requests import PullRequestError, PullRequestStore
from .repositories import RepositoryStore

__all__ = [
    "POLICY_MODES", "FreshnessReport", "ReviewFreshness",
    "ReviewFreshnessPolicy", "PullRequestReviewFreshnessStore",
    "render_freshness_policy", "render_freshness_report",
]

# The closed policy set, in the order a settings page
# would offer them.
POLICY_MODES = ("never", "approvals", "verdicts")

_POLICY_WORDS = {
    "never": (
        "Reviews never go stale: a review counts however "
        "the head branch moves after it was submitted."),
    "approvals": (
        "Approvals go stale on a push: an approval submitted "
        "against an older head no longer counts once the "
        "head moves; comments and change requests still count."),
    "verdicts": (
        "Verdict reviews go stale on a push: approvals and "
        "change requests submitted against an older head no "
        "longer count once the head moves; comments still count."),
}

# Which stored verdicts a mode can stale-date. Comment
# reviews gate nothing, so no mode stale-dates them.
_AFFECTED = {
    "never": frozenset(),
    "approvals": frozenset({"approved"}),
    "verdicts": frozenset({"approved", "changes_requested"}),
}


@dataclass(frozen=True)
class ReviewFreshnessPolicy:
    full_name: str
    mode: str                # never|approvals|verdicts

    @property
    def words(self) -> str:
        return _POLICY_WORDS[self.mode]


@dataclass(frozen=True)
class ReviewFreshness:
    review: Review
    is_stale: bool

    @property
    def counts(self) -> bool:
        """Whether this review still counts."""
        return not self.is_stale

    @property
    def state_words(self) -> str:
        if self.is_stale:
            return "Stale — no longer counts"
        return "Counts"

    @property
    def reason_words(self) -> str:
        if not self.is_stale:
            return ("Submitted against the head as it now "
                    "stands, or protected by this repository's "
                    "freshness policy.")
        return ("Submitted against an earlier head; the head "
                "has moved since, and this repository's policy "
                "stale-dates this kind of review on a push.")


@dataclass(frozen=True)
class FreshnessReport:
    full_name: str
    number: int
    policy: ReviewFreshnessPolicy
    current_head_oid: str
    entries: tuple             # of ReviewFreshness, oldest first

    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def fresh_count(self) -> int:
        return sum(1 for e in self.entries if e.counts)

    @property
    def stale_count(self) -> int:
        return self.total - self.fresh_count

    @property
    def counting(self) -> tuple:
        return tuple(e for e in self.entries if e.counts)

    @property
    def latest_counting_by_reviewer(self) -> dict:
        """Each reviewer's latest verdict that still
        counts — the record merge gates consult."""
        latest: dict = {}
        for entry in self.entries:
            if entry.counts:
                latest[entry.review.reviewer_id] = entry.review.verdict
        return latest

    @property
    def has_counting_approval(self) -> bool:
        return "approved" in self.latest_counting_by_reviewer.values()

    @property
    def has_counting_change_request(self) -> bool:
        return ("changes_requested"
                in self.latest_counting_by_reviewer.values())

    @property
    def words(self) -> str:
        if self.total == 0:
            return "No reviews have been submitted yet."
        parts = []
        if self.fresh_count:
            approved = sum(1 for e in self.counting
                           if e.review.verdict == "approved")
            requested = sum(1 for e in self.counting
                            if e.review.verdict == "changes_requested")
            commented = sum(1 for e in self.counting
                            if e.review.verdict == "commented")
            tallies = []
            if approved:
                tallies.append(f"{approved} approved")
            if requested:
                tallies.append(f"{requested} requested changes")
            if commented:
                tallies.append(f"{commented} commented")
            noun = "review" if self.fresh_count == 1 else "reviews"
            parts.append(
                f"{self.fresh_count} {noun} still count"
                + (f": {', '.join(tallies)}" if tallies else "")
                + ".")
        if self.stale_count:
            noun = "review is" if self.stale_count == 1 else "reviews are"
            parts.append(
                f"{self.stale_count} {noun} stale and no longer count.")
        return " ".join(parts)


class PullRequestReviewFreshnessStore:
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
        self._reviews = PullRequestReviewStore(
            conn, repositories, accounts, issues, audit=audit,
            time_fn=time_fn)
        self._files = PullRequestFilesStore(
            conn, repositories, accounts, issues, audit=audit,
            time_fn=time_fn)

    # -- internals ---------------------------------------------------
    def _repo_for_read(self, viewer, owner, repo):
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise PullRequestError(
                "repo_not_found", "No such repository.")
        return current

    def _mode_for(self, repo_id: int) -> str:
        row = self._conn.execute(
            "SELECT mode FROM repo_review_freshness_policies"
            " WHERE repo_id = ?", (repo_id,)).fetchone()
        return str(row["mode"]) if row is not None else "never"

    # -- the policy ----------------------------------------------------
    def policy_for(self, viewer: User | None, owner: object,
                   repo: object) -> ReviewFreshnessPolicy:
        """This repository's review freshness policy.
        No stored row is the default, `never`."""
        current = self._repo_for_read(viewer, owner, repo)
        return ReviewFreshnessPolicy(
            full_name=current.full_name,
            mode=self._mode_for(current.id))

    def set_policy(self, actor: User, owner: object, repo: object,
                   mode: object, *,
                   source_ip: str | None = None
                   ) -> ReviewFreshnessPolicy:
        """Set the policy. Repository admins only; a
        real change is audited under
        `repo.settings.change` with the key named, a
        same-mode retry is a quiet no-op, and an
        unknown mode is refused whole."""
        current = self._repo_for_read(actor, owner, repo)
        if not can_admin(actor, current):
            raise PullRequestError(
                "permission_denied",
                "Only a repository admin can set the review "
                "freshness policy.")
        if mode not in POLICY_MODES:
            raise PullRequestError(
                "policy_invalid",
                "The review freshness policy is one of: "
                "never, approvals, verdicts.")
        before = self._mode_for(current.id)
        if before != mode:
            now = int(self._now())
            with self._conn:  # commits before the answer
                self._conn.execute(
                    "INSERT INTO repo_review_freshness_policies"
                    " (repo_id, mode, updated_at, updated_by)"
                    " VALUES (?, ?, ?, ?)"
                    " ON CONFLICT (repo_id) DO UPDATE"
                    " SET mode = excluded.mode,"
                    " updated_at = excluded.updated_at,"
                    " updated_by = excluded.updated_by",
                    (current.id, str(mode), now, actor.id))
            if self._audit is not None:
                self._audit.append(
                    actor_kind="user", actor_id=actor.id,
                    action="repo.settings.change",
                    target_kind="repo", target_id=current.full_name,
                    outcome="success", source_ip=source_ip,
                    detail={"key": "review_freshness_policy",
                            "from": before, "to": str(mode)})
        return ReviewFreshnessPolicy(
            full_name=current.full_name, mode=str(mode))

    # -- the judgment ----------------------------------------------------
    def freshness_for(self, viewer: User | None, owner: object,
                      repo: object, number: object) -> FreshnessReport:
        """Every submitted review on this pull request
        judged fresh or stale, on read, under the
        policy as it stands now: a review is stale iff
        the policy can stale-date its verdict and the
        head it was submitted against is no longer the
        current head."""
        pr = self._prs.get_pull_request(viewer, owner, repo, number)
        current = self._repos.get_repository(owner, repo)
        assert current is not None
        policy = ReviewFreshnessPolicy(
            full_name=current.full_name,
            mode=self._mode_for(current.id))
        reviews = self._reviews.reviews_for(viewer, owner, repo, number)
        _diff, _base_oid, head_oid = self._files._diff_for(
            viewer, owner, repo, pr)
        affected = _AFFECTED[policy.mode]
        entries = tuple(
            ReviewFreshness(
                review=review,
                is_stale=(review.verdict in affected
                          and review.head_oid != head_oid))
            for review in reviews)
        return FreshnessReport(
            full_name=current.full_name, number=pr.number,
            policy=policy, current_head_oid=head_oid,
            entries=entries)


def render_freshness_policy(policy: ReviewFreshnessPolicy) -> str:
    """The repository's policy, said in words."""
    return (
        '<p class="review-freshness-policy">'
        f"{escape_html_text(policy.words)}</p>")


def render_freshness_report(report: FreshnessReport) -> str:
    """The pull request's review position under its
    freshness policy: the summary in words, then every
    review with its state and reason in words — never
    a colour alone."""
    items = "".join(
        '<li class="review-freshness">'
        f"{escape_html_text(entry.review.verdict_words)} — "
        f"{escape_html_text(entry.state_words)} "
        f"({escape_html_text(entry.reason_words)})"
        "</li>"
        for entry in report.entries)
    listing = f"<ul>{items}</ul>" if items else ""
    return (
        '<div class="review-freshness-report">'
        f"<p>{escape_html_text(report.words)}</p>"
        f"{listing}</div>")
