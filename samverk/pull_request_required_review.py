"""Required-review seam (S-164).

Part VIII's rules consult review state through one
function; this slice builds the function. Before this
slice, review state lived in three records that each
spoke well alone — S-148's submitted reviews and their
latest-by-reviewer summary, S-149's freshness judgment
(which reviews still count after a push, under the
repository's policy), and S-151/S-152's review requests
(who was asked, by CODEOWNERS or by hand, and who was
dismissed) — and every protection rule that needed the
position would have had to re-derive it, in its own
words, with its own idea of what counts. That is how
gates quietly disagree. Now there is one place:

- **The one function.** `review_state_for` on
  `PullRequestRequiredReviewStore` — and, for a caller
  that already holds the records, the pure
  `resolve_review_state` it delegates to — resolves a
  pull request's whole review position once: which
  reviews still count, each reviewer's latest counting
  verdict, who has approved, who is blocking with a
  change request, which code owners were asked and
  whether one of them has approved, and which
  requested reviewers have not yet given a counting
  verdict. Part VIII's rules (S-171's approval count,
  S-172's stale dismissal, S-173's code-owner gate)
  read this answer and nothing else; a rule states
  what it requires as a `ReviewRequirement` and reads
  `satisfied` and `blockers` off the state.
- **Counting is S-149's word, never re-judged here.**
  A review counts iff the freshness report counts it,
  so a stale approval vouches for nothing at this gate
  either, and changing the freshness policy re-judges
  this state in both directions with no stored flags
  to disagree. Only a reviewer's *latest* counting
  verdict speaks for them: an approval superseded by
  a change request no longer approves, and a change
  request superseded by an approval no longer blocks.
- **Self-approval never counts** (the S-171 law,
  enforced here so a rule cannot get it wrong). S-148
  already refuses a verdict on one's own pull request
  at submission; this seam additionally never counts
  the pull request's author among approvers or
  blockers, whatever record it is handed: a verdict
  on your own work vouches for nothing, in either
  direction.
- **Code owners are the recorded requests.** The code
  owners of a pull request are the resolved accounts
  on its active (not dismissed) `codeowners` review
  requests — S-151's record, read through S-152's
  dismissal-aware seam — never a fresh parse of the
  CODEOWNERS file at gate time, so the gate answers
  about the requests that actually stand. When a rule
  requires code-owner review and no code owner stands
  recorded, that part of the requirement is met by
  construction (there is nobody whose review could be
  required, the S-158 checks shape); when code owners
  stand recorded, one of them must be among the
  counting approvers.
- **A counting change request blocks.** Whatever the
  numeric requirement — including none — a reviewer
  whose latest counting verdict requests changes
  leaves the state unsatisfied, with the block said in
  words, until that reviewer approves (or their
  verdict goes stale under the policy). Comment
  reviews neither approve nor block; they are counted
  and named, and a requested reviewer who has
  commented is no longer outstanding.
- **Reads ride the S-141 seam, and mutate nothing.**
  Every resolution reads the pull request through
  `PullRequestStore` first, so a stranger to a private
  repository gets the uniform `pull_request_not_found`
  before any review position is named. The seam is a
  pure read: no migration (schema stays 63), no new
  taxonomy event (119 events stand), no audit row, and
  no stored verdict of its own to drift from the
  records it reads. Thread resolution is not review
  state: unresolved threads remain S-147's
  `ThreadSummary.blocks_merge`, a separate seam the
  merge gates consult beside this one, not through it.
- **Said in words, never a colour alone.** The state
  carries its position as `words`, each unmet part of
  a requirement as a `blockers` sentence, and the one
  renderer says exactly those words — the sentences
  S-183's rule insights will quote when they answer
  "why was this merge refused?".
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
from .pull_request_review_assignment import (
    ReviewAssignment, ReviewAssignmentStore)
from .pull_request_review_freshness import (
    FreshnessReport, PullRequestReviewFreshnessStore,
    ReviewFreshness)
from .pull_requests import PullRequestError, PullRequestStore
from .repositories import RepositoryStore

__all__ = [
    "REQUIREMENT_INVALID", "PullRequestRequiredReviewStore",
    "RequiredReviewState", "ReviewRequirement",
    "render_required_review_state", "resolve_review_state",
]

REQUIREMENT_INVALID = "requirement_invalid"


@dataclass(frozen=True)
class ReviewRequirement:
    """What one Part VIII rule asks of review state:
    how many counting approvals it needs, and whether
    one of them must be a code owner's. Rules build
    this value from their own stored policy (S-169's
    rule model, S-171's count, S-173's gate); the seam
    owns no policy of its own. An unlawful requirement
    is refused whole, in the house error shape, before
    any state is resolved."""
    required_approvals: int = 0
    require_code_owner_review: bool = False

    def __post_init__(self):
        if isinstance(self.required_approvals, bool) \
                or not isinstance(self.required_approvals, int) \
                or self.required_approvals < 0:
            raise PullRequestError(
                REQUIREMENT_INVALID,
                "A review requirement names a whole number "
                "of required approvals, zero or more.")
        if not isinstance(self.require_code_owner_review, bool):
            raise PullRequestError(
                REQUIREMENT_INVALID,
                "A review requirement says, yes or no, "
                "whether code-owner review is required.")

    @property
    def words(self) -> str:
        if not self.required_approvals \
                and not self.require_code_owner_review:
            return ("No review requirement: no approving "
                    "reviews are required, and code-owner "
                    "review is not required.")
        parts = []
        if self.required_approvals:
            noun = ("approval" if self.required_approvals == 1
                    else "approvals")
            parts.append(
                f"{self.required_approvals} required "
                f"{noun} from reviewers")
        if self.require_code_owner_review:
            parts.append("code-owner review required")
        return "; ".join(parts) + "."


@dataclass(frozen=True)
class RequiredReviewState:
    """One pull request's review position, resolved
    once for the rules: the requirement it was judged
    against, the counting verdicts behind the answer,
    and the answer said in words."""
    full_name: str
    number: int
    author_id: int
    requirement: ReviewRequirement
    policy_mode: str           # the S-149 policy in force
    current_head_oid: str
    entries: tuple             # of ReviewFreshness, oldest first
    latest_counting_by_reviewer: dict  # reviewer_id -> verdict
    counting_approver_ids: tuple   # author never among them
    blocking_reviewer_ids: tuple   # latest counting: changes_requested
    commented_reviewer_ids: tuple  # latest counting: commented
    code_owner_user_ids: tuple     # active codeowners requests, resolved
    code_owner_approver_ids: tuple  # approvers who are code owners
    requested_user_ids: tuple      # active requests, resolved, any source
    outstanding_user_ids: tuple    # requested, no counting verdict yet

    # -- tallies -------------------------------------------------------
    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def counting_entries(self) -> tuple:
        return tuple(e for e in self.entries if e.counts)

    @property
    def counting_count(self) -> int:
        return len(self.counting_entries)

    @property
    def stale_count(self) -> int:
        return self.total - self.counting_count

    @property
    def approval_count(self) -> int:
        """Counting approvals by other people — the
        number S-171's rule compares its count to."""
        return len(self.counting_approver_ids)

    @property
    def has_approval(self) -> bool:
        return self.approval_count > 0

    @property
    def has_change_request(self) -> bool:
        return bool(self.blocking_reviewer_ids)

    @property
    def has_code_owners(self) -> bool:
        return bool(self.code_owner_user_ids)

    def verdict_for(self, reviewer_id: int) -> str | None:
        """One reviewer's latest counting verdict, or
        None when nothing of theirs counts."""
        return self.latest_counting_by_reviewer.get(reviewer_id)

    def has_approved(self, reviewer_id: int) -> bool:
        return reviewer_id in self.counting_approver_ids

    # -- the judgment ----------------------------------------------------
    @property
    def code_owner_satisfied(self) -> bool:
        """The code-owner part of the requirement:
        not required, or no code owner stands recorded
        (met by construction), or a code owner is among
        the counting approvers."""
        if not self.requirement.require_code_owner_review:
            return True
        if not self.has_code_owners:
            return True
        return bool(self.code_owner_approver_ids)

    @property
    def blockers(self) -> tuple:
        """Why the requirement is not met, one sentence
        per unmet part — empty when it is met. These are
        the reason sentences a refusal quotes."""
        out = []
        need = self.requirement.required_approvals
        if self.approval_count < need:
            out.append(
                f"Approvals are short: {self.approval_count} "
                f"of the {need} required approvals count.")
        if self.has_change_request:
            count = len(self.blocking_reviewer_ids)
            noun = "reviewer has" if count == 1 else "reviewers have"
            out.append(
                f"{count} {noun} requested changes, and that "
                f"request still counts; it blocks until the "
                f"reviewer approves.")
        if not self.code_owner_satisfied:
            out.append(
                "Code-owner review is required and code "
                "owners were requested, but no code owner "
                "has approved yet.")
        return tuple(out)

    @property
    def satisfied(self) -> bool:
        """Whether this position meets the requirement
        it was resolved against — the one answer Part
        VIII's rules act on."""
        return not self.blockers

    @property
    def words(self) -> str:
        if self.total == 0:
            position = "No reviews have been submitted yet."
        else:
            tallies = []
            if self.approval_count:
                tallies.append(
                    f"{self.approval_count} approved")
            if self.blocking_reviewer_ids:
                tallies.append(
                    f"{len(self.blocking_reviewer_ids)} "
                    f"requested changes")
            if self.commented_reviewer_ids:
                tallies.append(
                    f"{len(self.commented_reviewer_ids)} commented")
            position = (
                f"{self.counting_count} of {self.total} "
                f"reviews still count"
                + (f": {', '.join(tallies)}" if tallies else "")
                + ".")
            if self.stale_count:
                noun = ("review is" if self.stale_count == 1
                        else "reviews are")
                position += (
                    f" {self.stale_count} {noun} stale and "
                    f"no longer count.")
        if self.satisfied:
            verdict = "The review requirement is met."
        else:
            verdict = ("The review requirement is not met: "
                       + " ".join(self.blockers))
        return f"{position} {verdict}"


def resolve_review_state(
        *, full_name: str, number: int, author_id: int,
        freshness: FreshnessReport,
        assignments: tuple = (),
        requirement: ReviewRequirement | None = None
        ) -> RequiredReviewState:
    """The pure half of the seam: a pull request's
    review position from the records that speak for it
    — S-149's freshness report (which reviews count,
    and each reviewer's latest counting verdict) and
    S-151/S-152's recorded review requests (who was
    asked, and whether the ask still stands). No
    database is touched here, so the judgment is
    provable in isolation; the store below only has to
    gather the records honestly."""
    requirement = requirement if requirement is not None \
        else ReviewRequirement()
    if not isinstance(requirement, ReviewRequirement):
        raise PullRequestError(
            REQUIREMENT_INVALID,
            "A review requirement is a ReviewRequirement: "
            "how many approvals, and whether code-owner "
            "review is required.")
    latest = dict(freshness.latest_counting_by_reviewer)
    approvers = tuple(
        rid for rid, verdict in latest.items()
        if verdict == "approved" and rid != author_id)
    blocking = tuple(
        rid for rid, verdict in latest.items()
        if verdict == "changes_requested" and rid != author_id)
    commented = tuple(
        rid for rid, verdict in latest.items()
        if verdict == "commented" and rid != author_id)
    active = [a for a in assignments if a.is_requested]
    code_owners: list = []
    requested: list = []
    for assignment in active:
        if assignment.user_id is None:
            continue
        if assignment.user_id not in requested:
            requested.append(assignment.user_id)
        if assignment.source == "codeowners" \
                and assignment.user_id not in code_owners:
            code_owners.append(assignment.user_id)
    code_approvers = tuple(
        rid for rid in approvers if rid in code_owners)
    outstanding = tuple(
        uid for uid in requested if uid not in latest)
    return RequiredReviewState(
        full_name=full_name, number=number,
        author_id=author_id, requirement=requirement,
        policy_mode=freshness.policy.mode,
        current_head_oid=freshness.current_head_oid,
        entries=tuple(freshness.entries),
        latest_counting_by_reviewer=latest,
        counting_approver_ids=approvers,
        blocking_reviewer_ids=blocking,
        commented_reviewer_ids=commented,
        code_owner_user_ids=tuple(code_owners),
        code_owner_approver_ids=code_approvers,
        requested_user_ids=tuple(requested),
        outstanding_user_ids=outstanding)


class PullRequestRequiredReviewStore:
    """The store half of the seam: gather the records
    through the seams that own them, then delegate to
    `resolve_review_state`. Rules hold this store (or
    call `review_state_for` on a composition root's)
    and never re-derive review state themselves."""

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
        self._freshness = PullRequestReviewFreshnessStore(
            conn, repositories, accounts, issues, audit=audit,
            time_fn=time_fn)
        self._assignments = ReviewAssignmentStore(
            conn, repositories, accounts, issues, audit=audit,
            time_fn=time_fn)

    def review_state_for(self, viewer: User | None, owner: object,
                         repo: object, number: object, *,
                         requirement: ReviewRequirement | None = None
                         ) -> RequiredReviewState:
        """THE one function Part VIII's rules consult:
        this pull request's review state, resolved once
        against *requirement* (the empty requirement
        when a rule states none). The pull request is
        read through S-141's seam first, so a stranger
        to a private repository gets the uniform
        `pull_request_not_found` before any review
        position is named; freshness is S-149's judgment
        as it stands now, and the requests are S-152's
        dismissal-aware record as it stands now."""
        if requirement is not None \
                and not isinstance(requirement, ReviewRequirement):
            raise PullRequestError(
                REQUIREMENT_INVALID,
                "A review requirement is a ReviewRequirement: "
                "how many approvals, and whether code-owner "
                "review is required.")
        pr = self._prs.get_pull_request(viewer, owner, repo, number)
        current = self._repos.get_repository(owner, repo)
        assert current is not None
        freshness = self._freshness.freshness_for(
            viewer, owner, repo, number)
        assignments = tuple(self._assignments.requests_for(
            viewer, owner, repo, number))
        return resolve_review_state(
            full_name=current.full_name, number=pr.number,
            author_id=pr.author_id, freshness=freshness,
            assignments=assignments, requirement=requirement)


def render_required_review_state(state: RequiredReviewState) -> str:
    """The review position and, when it falls short,
    the blockers — exactly the state's own words,
    escaped through S-010, never a colour alone. This
    is a renderer for the seam's answer, not a page:
    no route consumes review state yet, so none is
    invented."""
    blockers = ""
    if state.blockers:
        items = "".join(
            f"<li>{escape_html_text(blocker)}</li>"
            for blocker in state.blockers)
        blockers = f"<ul>{items}</ul>"
    return (
        '<div class="required-review-state">'
        f"<p>{escape_html_text(state.words)}</p>"
        f"{blockers}</div>")
