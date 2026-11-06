"""Required approving reviews (S-171).

Part VIII's approval gate: the S-169 rule fields
`required_approvals` (the count, stored since the
model landed) and `require_last_pusher_approval`
(the toggle migration 66 adds), wired to their
judgment point. Before this slice those fields were
stored policy with no teeth — a rule could demand
two approvals and a pull request with none was in
exactly the position of one with five. Now there is
one place that answers, for a pull request, the
question a merge gate asks:

- **The one check.** `ApprovalProtectionStore` —
  and, for a caller that already holds the records,
  the pure `decide_approvals` it delegates to —
  resolves the pull request's base branch once
  through S-169's `ProtectionRuleStore.evaluate_branch`
  (the one evaluation Part VIII consults; matching,
  ordering, and the most-restrictive fold are never
  re-derived here) and the pull request's review
  position once through S-164's `review_state_for`
  (the one function Part VIII's rules consult;
  counting is S-149 freshness's word, never re-judged
  here), then compares the two. No new policy storage
  is owned beyond the S-169 toggle: no new taxonomy
  event (119 events stand; rule changes already audit
  under the frozen `repo.protection.change`, and a
  judgment itself writes nothing and audits nothing,
  exactly as S-170's check does).
- **The count is configurable, per rule.** The number
  a pull request must reach is the effective rule's
  `required_approvals` for its base branch — the
  maximum across matching rules, by S-169's fold — so
  different branches may demand different counts, and
  a branch no rule touches demands none. Changing the
  rule re-judges the next check in both directions:
  nothing is stored on the pull request to drift.
- **Self-approval never counts.** S-148 refuses a
  verdict on one's own pull request at submission and
  S-164's seam additionally never counts the author
  among approvers whatever record it is handed; this
  gate reads approvals only through that seam, so a
  verdict on your own work vouches for nothing here
  either — in particular the author cannot satisfy
  their own pull request's count by approving it
  through any road.
- **The last-pusher rule is available.** When the
  effective rule carries `require_last_pusher_approval`,
  an approval from the most recent pusher of the pull
  request's head branch does not count: the approval
  must come from someone other than the person who
  last moved the head — the public forges' "require
  approval of the most recent reviewable push" law,
  because the last pusher is the one person whose
  judgment of the newest code is not independent of
  having written its landing. The most recent pusher
  is read from S-090's push-event store: the newest
  recorded push, by a person, that moved the head
  branch to the head oid the reviews were judged
  against. When no such push stands recorded (a head
  moved by a road that records no event), the pusher
  is honestly unknown, nobody is excluded, and the
  decision says so in words rather than guessing. A
  caller that knows the pusher from its own transport
  may state it directly (`last_pusher_id=` on the
  check, or on the pure decision); a stated pusher
  overrides the recorded one. The exclusion is of
  the *approval*, never of the person: that reviewer's
  change request still blocks, and their approval
  counts again the moment someone else pushes.
- **A counting change request blocks.** Whatever the
  count — including a satisfied count — a reviewer
  whose latest counting verdict requests changes
  leaves the gate unsatisfied until that reviewer
  approves (S-164's law, quoted in the blockers).
  Code-owner review is not this gate's business:
  S-173 wires that field beside this one, through
  the same S-164 state.
- **The refusal is said in words.** An unmet gate
  meets one human-readable reason naming the pull
  request, the base branch, the repository, how many
  approvals count against how many are required, and
  each unmet part. The reason is the same sentence at
  every door: the store's error (`approvals_required`,
  a `RepositoryError` carrying `.reason`, in the house
  shape) and the decision's own `reason` carry it, so
  S-183's rule insights can quote exactly what the
  merger was told.
- **Reads ride the house guards, and mutate nothing.**
  The pull request is read through S-141's seam first
  (a stranger to a private repository gets the uniform
  `pull_request_not_found` before any position is
  named) and the branch's policy through S-169's
  store (the uniform `repo_not_found`). The check is
  a pure read: no row changes, no audit row, no stored
  verdict of its own.
- **Said in words, never a colour alone.** A decision
  carries its position as `words` and its unmet parts
  as `blockers`, and the one renderer says exactly
  those words, escaped through S-010. No route is
  invented: the store is the surface, as S-170's
  check landed route-free.
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
from .protection_rules import (
    ProtectionEvaluation, ProtectionRuleStore)
from .pull_request_required_review import (
    PullRequestRequiredReviewStore, RequiredReviewState,
    ReviewRequirement)
from .pull_requests import PullRequestStore
from .push_events import PushEventStore
from .repositories import RepositoryError, RepositoryStore

__all__ = [
    "APPROVALS_REQUIRED", "ApprovalDecision",
    "ApprovalProtectionStore", "ApprovalsRequiredError",
    "decide_approvals", "render_approval_decision",
]

APPROVALS_REQUIRED = "approvals_required"


class ApprovalsRequiredError(RepositoryError):
    """An approval-gate refusal: a RepositoryError
    carrying `.reason` (`approvals_required`), mirroring
    PullRequestRequiredError and ProtectionRuleError."""


@dataclass(frozen=True)
class ApprovalDecision:
    """One pull request's approval position, resolved
    once: the S-169 evaluation for its base branch, the
    S-164 review state it was judged against, who last
    pushed its head (when that is known), and the answer
    said in words."""
    full_name: str
    number: int
    base_branch: str
    head_branch: str
    evaluation: ProtectionEvaluation
    review_state: RequiredReviewState
    last_pusher_id: int | None

    # -- the requirement ---------------------------------------------
    @property
    def required_approvals(self) -> int:
        """How many counting approvals the effective
        rule for the base branch demands — zero when no
        matching rule demands any."""
        effective = self.evaluation.effective
        if effective is None:
            return 0
        return int(effective.settings.required_approvals)

    @property
    def require_last_pusher_approval(self) -> bool:
        """Whether the effective rule carries the
        last-pusher toggle: approval must come from
        someone other than the most recent pusher."""
        effective = self.evaluation.effective
        return bool(
            effective is not None
            and effective.settings.require_last_pusher_approval)

    # -- the count -----------------------------------------------------
    @property
    def counting_approver_ids(self) -> tuple:
        """Approvers whose verdict still counts, by
        S-164's word — the author never among them."""
        return self.review_state.counting_approver_ids

    @property
    def last_pusher_excluded(self) -> bool:
        """Whether the last-pusher rule removes an
        approval from the count: the toggle is on, the
        pusher is known, and the pusher is among the
        counting approvers."""
        return bool(
            self.require_last_pusher_approval
            and self.last_pusher_id is not None
            and self.last_pusher_id in self.counting_approver_ids)

    @property
    def effective_approver_ids(self) -> tuple:
        """The approvers this gate actually counts:
        S-164's counting approvers, minus the most
        recent pusher when the last-pusher rule
        excludes their approval."""
        if not self.last_pusher_excluded:
            return self.counting_approver_ids
        return tuple(
            rid for rid in self.counting_approver_ids
            if rid != self.last_pusher_id)

    @property
    def approval_count(self) -> int:
        """Counting approvals by other people, under
        every rule this gate carries — the number the
        required count is compared to."""
        return len(self.effective_approver_ids)

    # -- the judgment ----------------------------------------------------
    @property
    def blockers(self) -> tuple:
        """Why the gate is not met, one sentence per
        unmet part — empty when it is met. These are
        the reason sentences a refusal quotes."""
        out = []
        need = self.required_approvals
        if self.approval_count < need:
            out.append(
                f"Approvals are short: {self.approval_count} "
                f"of the {need} required approvals count.")
            if self.last_pusher_excluded:
                out.append(
                    "The most recent pusher of the head "
                    "branch has approved, but that approval "
                    "does not count under this branch's "
                    "last-pusher rule; an approval from "
                    "someone else is required.")
        if self.review_state.has_change_request:
            count = len(self.review_state.blocking_reviewer_ids)
            noun = "reviewer has" if count == 1 else "reviewers have"
            out.append(
                f"{count} {noun} requested changes, and that "
                f"request still counts; it blocks until the "
                f"reviewer approves.")
        return tuple(out)

    @property
    def satisfied(self) -> bool:
        """Whether this pull request may pass the
        approval gate for its base branch — the one
        answer merge gates act on."""
        return not self.blockers

    @property
    def reason(self) -> str:
        """The refusal sentence when refused, else ''."""
        if self.satisfied:
            return ""
        return (
            f"Pull request #{self.number} in {self.full_name} "
            f"does not meet the required approvals for "
            f"branch '{self.base_branch}': "
            + " ".join(self.blockers))

    @property
    def words(self) -> str:
        need = self.required_approvals
        if need:
            noun = "approval" if need == 1 else "approvals"
            demand = (f"{need} {noun} required for branch "
                      f"'{self.base_branch}'")
        else:
            demand = (f"no approvals required for branch "
                      f"'{self.base_branch}'")
        count = (f"{self.approval_count} "
                 f"{'approval counts' if self.approval_count == 1 else 'approvals count'}")
        position = (f"Pull request #{self.number} in "
                    f"{self.full_name}: {demand}; {count}.")
        if self.require_last_pusher_approval:
            if self.last_pusher_id is None:
                position += (
                    " The last-pusher rule applies, but no "
                    "push by a person stands recorded for "
                    "the current head, so nobody is "
                    "excluded by it.")
            elif self.last_pusher_excluded:
                position += (
                    " The last-pusher rule excludes the "
                    "most recent pusher's approval.")
            else:
                position += (
                    " The last-pusher rule applies and the "
                    "most recent pusher has not approved.")
        if self.satisfied:
            return position + " The approval requirement is met."
        return (position + " The approval requirement is "
                "not met: " + " ".join(self.blockers))


def decide_approvals(
        evaluation: ProtectionEvaluation,
        review_state: RequiredReviewState, *,
        last_pusher_id: int | None = None,
        head_branch: str = "") -> ApprovalDecision:
    """The pure half of the gate: one pull request's
    approval decision from its already-resolved S-169
    evaluation and S-164 review state, plus who last
    pushed its head when that is known. No database is
    touched here, so the judgment is provable in
    isolation; the store below only has to gather the
    records honestly."""
    if last_pusher_id is not None and (
            isinstance(last_pusher_id, bool)
            or not isinstance(last_pusher_id, int)):
        raise ApprovalsRequiredError(
            "approval_check_invalid",
            "The most recent pusher is an account id, "
            "or not known.")
    return ApprovalDecision(
        full_name=evaluation.full_name,
        number=review_state.number,
        base_branch=evaluation.branch,
        head_branch=head_branch,
        evaluation=evaluation,
        review_state=review_state,
        last_pusher_id=last_pusher_id)


class ApprovalProtectionStore:
    """The store half of the gate: gather one pull
    request through S-141's seam, its base branch's
    evaluation through S-169's store, and its review
    state through S-164's one function, then delegate
    to `decide_approvals`. Merge gates hold this store
    and never re-derive protection or review state
    themselves."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        issues: IssueStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
        protection_rules: ProtectionRuleStore | None = None,
        required_review: PullRequestRequiredReviewStore | None = None,
        push_events: PushEventStore | None = None,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._issues = issues
        self._audit = audit
        self._now = time_fn
        self._rules = protection_rules or ProtectionRuleStore(
            conn, repositories, accounts,
            audit=audit, time_fn=time_fn)
        self._prs = PullRequestStore(
            conn, repositories, accounts, issues, audit=audit,
            time_fn=time_fn)
        self._review = required_review or PullRequestRequiredReviewStore(
            conn, repositories, accounts, issues, audit=audit,
            time_fn=time_fn)
        self._pushes = push_events or PushEventStore(
            conn, repositories, time_fn=time_fn)

    # -- the last pusher -------------------------------------------------
    def _recorded_last_pusher(self, owner: object, repo: object,
                              head_branch: str,
                              head_oid: str) -> int | None:
        """Who last pushed the head branch to the head
        the reviews were judged against, from S-090's
        push-event store (newest first): the first
        recorded push, by a person, whose updates move
        `refs/heads/<head_branch>` to `head_oid`. None
        when no such push stands recorded — the pusher
        is unknown, never guessed. Fork-head pull
        requests record their pushes in the fork, not
        here, so their pusher is unknown to this store
        and nobody is excluded for them."""
        ref = f"refs/heads/{head_branch}"
        for event in self._pushes.list_for_repo(owner, repo, limit=500):
            if event.actor_kind != "user" or event.actor_id is None:
                continue
            for update in event.updates:
                if update.ref == ref and update.new_oid == head_oid:
                    return int(event.actor_id)
        return None

    # -- the one check -----------------------------------------------------
    def check_pull_request(self, viewer: User | None, owner: object,
                           repo: object, number: object, *,
                           last_pusher_id: int | None = None
                           ) -> ApprovalDecision:
        """THE one check S-171's gate consults: this
        pull request's approval decision, resolved once.
        The pull request is read through S-141's seam
        first, so a stranger to a private repository
        gets the uniform `pull_request_not_found` before
        any approval position is named. A caller that
        knows the most recent pusher from its own
        transport states it with `last_pusher_id=`; left
        unstated, the pusher is read from the recorded
        push events."""
        pr = self._prs.get_pull_request(viewer, owner, repo, number)
        evaluation = self._rules.evaluate_branch(
            viewer, owner, repo, pr.base_branch)
        effective = evaluation.effective
        requirement = ReviewRequirement(
            required_approvals=(
                int(effective.settings.required_approvals)
                if effective is not None else 0))
        state = self._review.review_state_for(
            viewer, owner, repo, pr.number, requirement=requirement)
        pusher = last_pusher_id
        if pusher is None:
            pusher = self._recorded_last_pusher(
                owner, repo, pr.head_branch, state.current_head_oid)
        return decide_approvals(
            evaluation, state, last_pusher_id=pusher,
            head_branch=pr.head_branch)

    def enforce_pull_request(self, viewer: User | None, owner: object,
                             repo: object, number: object, *,
                             last_pusher_id: int | None = None
                             ) -> ApprovalDecision:
        """The check, as a refusal: returns the satisfied
        decision, or raises `approvals_required`
        carrying the human-readable reason."""
        decision = self.check_pull_request(
            viewer, owner, repo, number,
            last_pusher_id=last_pusher_id)
        if not decision.satisfied:
            raise ApprovalsRequiredError(
                APPROVALS_REQUIRED, decision.reason)
        return decision


def render_approval_decision(decision: ApprovalDecision) -> str:
    """One approval decision in words — exactly the
    decision's own `words`, with its blockers listed
    when it has any, escaped through S-010, never a
    colour alone. The sentences S-183's rule insights
    will quote when they answer "why was this merge
    refused?"."""
    blockers = ""
    if decision.blockers:
        items = "".join(
            f"<li>{escape_html_text(blocker)}</li>"
            for blocker in decision.blockers)
        blockers = f"<ul>{items}</ul>"
    return (
        '<div class="protection-approvals">'
        f"<p>{escape_html_text(decision.words)}</p>"
        f"{blockers}</div>")
