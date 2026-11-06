"""Require code-owner review (S-173).

Part VIII's code-owner gate: the S-169 rule field
`require_code_owner_review`, wired to the record it
governs. Before this slice that field was stored
policy with no teeth — a rule could say code-owner
review is required and a pull request approved only
by people who own none of its files was in exactly
the position of one its owners had approved. Now
there is one place that answers, for a pull request,
the question a merge gate asks about ownership:

- **The one check.** `CodeOwnerProtectionStore` —
  and, for a caller that already holds the records,
  the pure `decide_codeowners` it delegates to —
  resolves the pull request's base branch once
  through S-169's `ProtectionRuleStore.evaluate_branch`
  (the one evaluation Part VIII consults; matching,
  ordering, and the most-restrictive fold are never
  re-derived here, so the gate speaks when ANY
  matching rule carries the toggle) and the pull
  request's review position once through S-164's
  `review_state_for` (the one function Part VIII's
  rules consult; who the recorded code owners are
  and which of them has a counting approval are
  S-164's words, never re-judged here), then applies
  the rule between them. No new policy storage is
  owned: no migration (schema stays 66), no new
  taxonomy event (119 events stand; rule changes
  already audit under the frozen
  `repo.protection.change`, and a judgment itself
  writes nothing and audits nothing, exactly as
  S-170's, S-171's, and S-172's judgments do).
- **A gate distinct from any-approval** (the
  roadmap's own words for this slice). This gate is
  satisfied by an approval from a code owner, and
  by nothing else: an approval from any other
  reviewer counts toward S-171's count and leaves
  this gate unmet, and a code owner's approval
  counts toward both gates at once. The two gates
  consult the same S-164 state and answer different
  questions about it — S-171 asks *how many*, this
  gate asks *whose*.
- **Who the code owners are.** The owners of record
  are S-151's CODEOWNERS matches for the pull
  request's changed files, as recorded by S-151's
  sync and read back through S-152's dismissal-aware
  assignment record: an owner token that resolves
  to a Samverk account (`@username` naming an
  account that exists). A dismissed request no
  longer stands, so its owner is not an owner of
  record until re-requested. Team tokens, email
  addresses, and names with no account resolve to
  no account (S-151's design); they request a
  review no Samverk approval can answer, so they
  are not owners of record here — a pull request
  whose only matched owners are unresolvable has
  no code owner of record, exactly as S-164's seam
  already judges it.
- **Met by construction when no owner stands
  recorded** (S-164's law, kept here). When the
  rule requires code-owner review but no code
  owner stands recorded for the pull request —
  no CODEOWNERS file on the base branch, no rule
  matching its files, or every match unresolvable
  — there is nobody whose approval the gate could
  demand, so the gate is met and the decision says
  so in words rather than refusing every merge on
  a branch whose owners were never named.
- **Counting is S-149's word, through S-164.** A
  code owner's approval counts only while S-164
  counts it: an approval stale-dated by the
  repository's freshness policy, or superseded by
  that owner's own later verdict, vouches for
  nothing here — and if a code owner's latest
  counting verdict requests changes, the gate is
  unmet until that owner approves, which the
  blockers say by name. Self-approval never
  counts: S-151 never auto-requests the author,
  S-148 refuses a verdict on one's own pull
  request at submission, and S-164 never counts
  the author among approvers, so an author who is
  also a matched owner cannot satisfy their own
  pull request's gate through any road.
- **The refusal is said in words.** An unmet gate
  meets one human-readable reason naming the pull
  request, the base branch, and the repository:
  the store's error (`code_owner_review_required`,
  a `RepositoryError` carrying `.reason`, in the
  house shape) and the decision's own `reason`
  carry the same sentence, so S-183's rule
  insights can quote exactly what the merger
  was told.
- **Reads ride the house guards, and mutate
  nothing.** The pull request is read through
  S-141's seam first (a stranger to a private
  repository gets the uniform
  `pull_request_not_found` before any position is
  named) and the branch's policy through S-169's
  store (the uniform `repo_not_found`). The check
  is a pure read: no row changes, no audit row,
  no stored verdict of its own.
- **Said in words, never a colour alone.** A
  decision carries its position as `words` and
  its unmet parts as `blockers`, and the one
  renderer says exactly those words, escaped
  through S-010. No route is invented: the store
  is the surface, as S-170's, S-171's, and
  S-172's gates landed route-free.
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
from .repositories import RepositoryError, RepositoryStore

__all__ = [
    "CODE_OWNER_REVIEW_REQUIRED", "CodeOwnerDecision",
    "CodeOwnerProtectionStore", "CodeOwnerReviewRequiredError",
    "decide_codeowners", "render_codeowner_decision",
]

CODE_OWNER_REVIEW_REQUIRED = "code_owner_review_required"


class CodeOwnerReviewRequiredError(RepositoryError):
    """A code-owner-gate refusal: a RepositoryError
    carrying `.reason` (`code_owner_review_required`),
    mirroring ApprovalsRequiredError and
    ProtectionRuleError."""


@dataclass(frozen=True)
class CodeOwnerDecision:
    """One pull request's code-owner position,
    resolved once: the S-169 evaluation for its base
    branch and the S-164 review state it was judged
    against, and the answer said in words."""
    full_name: str
    number: int
    base_branch: str
    head_branch: str
    evaluation: ProtectionEvaluation
    review_state: RequiredReviewState

    # -- the requirement ---------------------------------------------
    @property
    def require_code_owner_review(self) -> bool:
        """Whether the effective rule for the base
        branch requires code-owner review — the fold
        of every matching rule, per S-169."""
        effective = self.evaluation.effective
        return bool(
            effective is not None
            and effective.settings.require_code_owner_review)

    # -- who the owners are, and who has approved ----------------------
    @property
    def code_owner_user_ids(self) -> tuple:
        """The pull request's code owners of record,
        by S-164's word: recorded CODEOWNERS requests
        that resolve to a Samverk account and still
        stand (not dismissed)."""
        return self.review_state.code_owner_user_ids

    @property
    def has_code_owners(self) -> bool:
        return bool(self.code_owner_user_ids)

    @property
    def code_owner_approver_ids(self) -> tuple:
        """Code owners whose approval counts now —
        S-164's counting approvers who are code
        owners. The author is never among them."""
        return self.review_state.code_owner_approver_ids

    @property
    def has_code_owner_approval(self) -> bool:
        return bool(self.code_owner_approver_ids)

    @property
    def counting_approver_ids(self) -> tuple:
        """Every counting approver, owner or not —
        the number S-171's gate consults, carried
        here so the distinctness of the two gates
        is visible in one decision."""
        return self.review_state.counting_approver_ids

    @property
    def code_owner_blocking_ids(self) -> tuple:
        """Code owners whose latest counting verdict
        requests changes — their approval is owed
        before this gate can be met."""
        return tuple(
            rid for rid in self.review_state.blocking_reviewer_ids
            if rid in self.code_owner_user_ids)

    # -- the judgment ----------------------------------------------------
    @property
    def blockers(self) -> tuple:
        """Why the gate is not met, one sentence per
        unmet part — empty when it is met. These are
        the reason sentences a refusal quotes."""
        out = []
        if self.require_code_owner_review and self.has_code_owners \
                and not self.has_code_owner_approval:
            out.append(
                "Code-owner review is required: code "
                "owners stand recorded for this pull "
                "request, but no code owner has a "
                "counting approval on it — an approval "
                "from any other reviewer does not "
                "satisfy this gate.")
            if self.code_owner_blocking_ids:
                count = len(self.code_owner_blocking_ids)
                noun = "owner has" if count == 1 else "owners have"
                out.append(
                    f"{count} code {noun} requested "
                    f"changes, and that request still "
                    f"counts; it stands until the code "
                    f"owner approves.")
        return tuple(out)

    @property
    def satisfied(self) -> bool:
        """Whether this pull request may pass the
        code-owner gate for its base branch — the one
        answer merge gates act on. Met when the rule
        does not require code-owner review, when no
        code owner stands recorded (met by
        construction), or when a code owner has a
        counting approval."""
        return not self.blockers

    @property
    def reason(self) -> str:
        """The refusal sentence when refused, else ''."""
        if self.satisfied:
            return ""
        return (
            f"Pull request #{self.number} in {self.full_name} "
            f"does not meet the code-owner review required "
            f"for branch '{self.base_branch}': "
            + " ".join(self.blockers))

    @property
    def words(self) -> str:
        if self.require_code_owner_review:
            demand = (f"code-owner review is required for "
                      f"branch '{self.base_branch}'")
        else:
            demand = (f"code-owner review is not required "
                      f"for branch '{self.base_branch}'")
        position = (f"Pull request #{self.number} in "
                    f"{self.full_name}: {demand}; ")
        if not self.has_code_owners:
            position += ("no code owner stands recorded "
                         "for this pull request")
            if self.require_code_owner_review:
                position += (", so the gate is met by "
                             "construction")
            position += "."
        else:
            owners = len(self.code_owner_user_ids)
            noun = "owner stands" if owners == 1 else "owners stand"
            position += f"{owners} code {noun} recorded"
            if self.has_code_owner_approval:
                count = len(self.code_owner_approver_ids)
                verb = "has" if count == 1 else "have"
                position += f"; {count} {verb} approved."
            else:
                position += "; none has a counting approval."
        if self.satisfied:
            return position + " The code-owner requirement is met."
        return (position + " The code-owner requirement is "
                "not met: " + " ".join(self.blockers))


def decide_codeowners(
        evaluation: ProtectionEvaluation,
        review_state: RequiredReviewState, *,
        head_branch: str = "") -> CodeOwnerDecision:
    """The pure half of the gate: one pull request's
    code-owner decision from its already-resolved
    S-169 evaluation and S-164 review state. The
    gate's answer is computed from the evaluation's
    toggle and the state's owner facts, so the state
    need not have been resolved against any
    particular requirement for the answer to hold.
    No database is touched here, so the judgment is
    provable in isolation; the store below only has
    to gather the records honestly."""
    return CodeOwnerDecision(
        full_name=evaluation.full_name,
        number=review_state.number,
        base_branch=evaluation.branch,
        head_branch=head_branch,
        evaluation=evaluation,
        review_state=review_state)


class CodeOwnerProtectionStore:
    """The store half of the gate: gather one pull
    request through S-141's seam, its base branch's
    evaluation through S-169's store, and its review
    state through S-164's one function (resolved
    against this gate's own requirement, so the
    state's code-owner words agree with the
    decision's), then delegate to `decide_codeowners`.
    Merge gates hold this store and never re-derive
    protection, ownership, or review state
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

    def check_pull_request(self, viewer: User | None, owner: object,
                           repo: object, number: object
                           ) -> CodeOwnerDecision:
        """THE one check S-173's gate consults: this
        pull request's code-owner decision, resolved
        once. The pull request is read through
        S-141's seam first, so a stranger to a private
        repository gets the uniform
        `pull_request_not_found` before any code-owner
        position is named."""
        pr = self._prs.get_pull_request(viewer, owner, repo, number)
        evaluation = self._rules.evaluate_branch(
            viewer, owner, repo, pr.base_branch)
        effective = evaluation.effective
        requirement = ReviewRequirement(
            require_code_owner_review=bool(
                effective is not None
                and effective.settings.require_code_owner_review))
        state = self._review.review_state_for(
            viewer, owner, repo, pr.number, requirement=requirement)
        return decide_codeowners(
            evaluation, state, head_branch=pr.head_branch)

    def enforce_pull_request(self, viewer: User | None, owner: object,
                             repo: object, number: object
                             ) -> CodeOwnerDecision:
        """The check, as a refusal: returns the satisfied
        decision, or raises `code_owner_review_required`
        carrying the human-readable reason."""
        decision = self.check_pull_request(
            viewer, owner, repo, number)
        if not decision.satisfied:
            raise CodeOwnerReviewRequiredError(
                CODE_OWNER_REVIEW_REQUIRED, decision.reason)
        return decision


def render_codeowner_decision(decision: CodeOwnerDecision) -> str:
    """One code-owner decision in words — exactly the
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
        '<div class="protection-codeowners">'
        f"<p>{escape_html_text(decision.words)}</p>"
        f"{blockers}</div>")
