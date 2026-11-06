"""Required status checks gate (S-174).

Required status checks: the branch protection rule
(S-169) names checks that must be green before a pull
request may merge, and may also demand that the head
branch be up to date with its base. This slice is the
gate that judges both halves — the one check merge
gates consult, in the shape S-171 (approvals) and
S-173 (code owners) already established.

- **The requirement is the folded rule's word.** The
  pull request's base branch is resolved once through
  S-169's `ProtectionRuleStore.evaluate_branch`
  (matching, documented evaluation order, and the
  most-restrictive fold are never re-derived here):
  the gate speaks the folded
  `required_status_checks` — the union of every
  matching rule's named checks — and the folded
  `require_branch_up_to_date` toggle. A branch no
  rule matches carries no requirement, and the gate
  is satisfied by construction.
- **Green means passed, on the head commit.** The
  named checks are read from S-157's one record
  (`PullRequestChecksStore.checks_for`): the results
  recorded against the pull request's base repository
  for its head commit. A required check is green
  only when its latest recorded state there is
  `passed`. A check never reported is not green; a
  check still `pending` is not green; a check
  `failed` is not green. Results recorded against
  any other commit — an older head, a different
  branch — vouch for nothing here, and checks nobody
  required are listed by the panel but do not bind
  this gate either way.
- **Up to date means the base has not moved past
  the head.** When the folded rule carries the
  toggle, the head branch's position is counted the
  compare road's way (`rev-list --count
  head..base`): the pull request is up to date iff
  the count is zero — the base branch's current tip
  is contained in the head. A cross-fork head is
  read into the base repository through the merge
  road's scratch-ref fetch (S-153) and the scratch
  ref is always dropped afterwards. When the
  position cannot be counted at all (a branch ref
  that does not resolve, an unreadable comparison),
  an up-to-date requirement is unmet and the
  decision says so in words — an unprovable position
  never passes a gate that demands proof. With the
  toggle off, behindness is still counted and
  stated, but it binds nothing.
- **The refusal is one code, the reason a sentence.**
  `enforce_pull_request` raises
  `status_checks_required` (a `RepositoryError`
  carrying `.reason`) with the first blocker's
  sentence: which named check is missing, pending,
  or failed, or how far behind the base the head
  stands and what to do about it. The decision says
  its whole position in words, and the one renderer
  prints exactly those words escaped through S-010,
  never a colour alone.
- **A pure read.** The judgment writes nothing and
  audits nothing, so no taxonomy event is added
  (119 stand) and no migration is claimed (schema
  stays 66); rule changes already audit under the
  frozen `repo.protection.change`, and
  docs/AUDIT_TAXONOMY.md records the slice on that
  basis. Reads ride S-141's seam first, so a stranger
  to a private repository gets the uniform
  `pull_request_not_found` before any check position
  is named.
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
from .proc import run_git_fetch_ref, run_git_in
from .protection_rules import ProtectionEvaluation, ProtectionRuleStore
from .pull_request_checks import PullRequestCheck, PullRequestChecksStore
from .pull_request_forks import ForkPullRequestStore
from .pull_requests import PullRequestStore
from .refs import RefStore, branch_ref
from .repositories import RepositoryError, RepositoryStore

__all__ = [
    "STATUS_CHECKS_REQUIRED", "StatusCheckDecision",
    "StatusCheckProtectionStore", "StatusChecksRequiredError",
    "decide_status_checks", "render_status_check_decision",
]

STATUS_CHECKS_REQUIRED = "status_checks_required"

#: The scratch ref a cross-fork head is fetched under
#: while its position is counted — the merge road's
#: road (S-153), under this gate's own name so the two
#: never collide; always dropped after the count.
SCRATCH_REF = "refs/samverk-status-checks/head"


class StatusChecksRequiredError(RepositoryError):
    """A required-status-checks refusal: a
    RepositoryError carrying `.reason`
    (`status_checks_required`), mirroring
    ApprovalsRequiredError and
    CodeOwnerReviewRequiredError."""


@dataclass(frozen=True)
class StatusCheckDecision:
    """One pull request's required-status-checks
    position, resolved once: the S-169 evaluation for
    its base branch, the S-157 check rows recorded
    for its head commit, and its counted behindness,
    with the answer said in words."""
    full_name: str
    number: int
    base_branch: str
    head_branch: str
    evaluation: ProtectionEvaluation
    checks: tuple            # of PullRequestCheck, S-157 order
    head_oid: str            # the commit the checks were read for
    base_oid: str            # the base branch's current tip ('' if none)
    behind: int | None       # commits in base the head lacks (None = uncounted)

    # -- the requirement ---------------------------------------------

    @property
    def required_status_checks(self) -> tuple:
        effective = self.evaluation.effective
        if effective is None:
            return ()
        return tuple(effective.settings.required_status_checks)

    @property
    def require_branch_up_to_date(self) -> bool:
        effective = self.evaluation.effective
        return bool(
            effective is not None
            and effective.settings.require_branch_up_to_date)

    # -- the checks ----------------------------------------------------

    def _row_for(self, context: str) -> PullRequestCheck | None:
        for row in self.checks:
            if row.context == context:
                return row
        return None

    @property
    def missing_checks(self) -> tuple:
        """Required checks with no result recorded on
        the head commit at all."""
        return tuple(
            name for name in self.required_status_checks
            if self._row_for(name) is None)

    @property
    def pending_checks(self) -> tuple:
        """Required checks whose latest recorded state
        on the head commit is still pending."""
        return tuple(
            name for name in self.required_status_checks
            if (row := self._row_for(name)) is not None
            and row.is_pending)

    @property
    def failed_checks(self) -> tuple:
        """Required checks whose latest recorded state
        on the head commit is failed."""
        return tuple(
            name for name in self.required_status_checks
            if (row := self._row_for(name)) is not None
            and row.is_failed)

    @property
    def passed_checks(self) -> tuple:
        """Required checks whose latest recorded state
        on the head commit is passed — the green ones."""
        return tuple(
            name for name in self.required_status_checks
            if (row := self._row_for(name)) is not None
            and row.is_passed)

    @property
    def checks_satisfied(self) -> bool:
        """Every required check green on the head
        commit (vacuously true when none is required)."""
        return len(self.passed_checks) == len(self.required_status_checks)

    # -- the up-to-date half -------------------------------------------

    @property
    def up_to_date(self) -> bool:
        """The counted position: the base branch's
        current tip is contained in the head. An
        uncounted position is not up to date."""
        return self.behind == 0

    @property
    def up_to_date_satisfied(self) -> bool:
        """The toggle's word: with the toggle off the
        position binds nothing; with it on, only a
        counted zero satisfies."""
        return not self.require_branch_up_to_date or self.up_to_date

    # -- the answer ------------------------------------------------------

    @property
    def blockers(self) -> tuple:
        out: list[str] = []
        for name in self.missing_checks:
            out.append(
                f"Required check '{name}' has not been "
                f"reported on the head commit; it must "
                f"be green before this pull request can "
                f"merge.")
        for name in self.pending_checks:
            out.append(
                f"Required check '{name}' is still "
                f"pending on the head commit; it must "
                f"be green before this pull request can "
                f"merge.")
        for name in self.failed_checks:
            out.append(
                f"Required check '{name}' has failed on "
                f"the head commit; it must be green "
                f"before this pull request can merge.")
        if self.require_branch_up_to_date and not self.up_to_date:
            if self.behind is None:
                out.append(
                    f"The rule requires the head branch "
                    f"to be up to date with "
                    f"'{self.base_branch}', and its "
                    f"position could not be counted; "
                    f"update the head branch before "
                    f"this pull request can merge.")
            else:
                noun = "commit" if self.behind == 1 else "commits"
                out.append(
                    f"The head branch is {self.behind} "
                    f"{noun} behind '{self.base_branch}' "
                    f"and the rule requires it to be up "
                    f"to date; update the head branch "
                    f"before this pull request can merge.")
        return tuple(out)

    @property
    def satisfied(self) -> bool:
        return self.checks_satisfied and self.up_to_date_satisfied

    @property
    def reason(self) -> str:
        """The refusal sentence `enforce_pull_request`
        carries: the first blocker, or the satisfied
        position when there is none."""
        blockers = self.blockers
        if blockers:
            return blockers[0]
        return self.words

    @property
    def words(self) -> str:
        required = self.required_status_checks
        if required:
            names = ", ".join(f"'{name}'" for name in required)
            checks_part = (
                f"required status checks {names}: "
                f"{len(self.passed_checks)} of "
                f"{len(required)} green on the head commit")
        else:
            checks_part = "no status checks are required"
        if self.behind is None:
            position = "its position against the base branch was not counted"
        elif self.behind == 0:
            position = (
                f"the head branch is up to date with "
                f"'{self.base_branch}'")
        else:
            noun = "commit" if self.behind == 1 else "commits"
            position = (
                f"the head branch is {self.behind} {noun} "
                f"behind '{self.base_branch}'")
        toggle = (
            " and the rule requires the branch to be up to date"
            if self.require_branch_up_to_date else "")
        verdict = "satisfied" if self.satisfied else "not satisfied"
        return (
            f"Pull request #{self.number} in {self.full_name}: "
            f"{checks_part}{toggle}; {position}. "
            f"The required status checks gate is {verdict}.")


def decide_status_checks(
        evaluation: ProtectionEvaluation,
        checks, *,
        number: int = 0,
        head_branch: str = "",
        head_oid: str = "",
        base_oid: str = "",
        behind: int | None = None) -> StatusCheckDecision:
    """The pure half of the gate: one pull request's
    status-check decision from its already-resolved
    S-169 evaluation, the S-157 rows recorded for its
    head commit, and its counted behindness. No
    database and no git repository are touched here,
    so the judgment is provable in isolation; the
    store below only has to gather the records
    honestly."""
    return StatusCheckDecision(
        full_name=evaluation.full_name,
        number=number,
        base_branch=evaluation.branch,
        head_branch=head_branch,
        evaluation=evaluation,
        checks=tuple(checks),
        head_oid=head_oid,
        base_oid=base_oid,
        behind=behind)


class StatusCheckProtectionStore:
    """The store half of the gate: gather one pull
    request through S-141's seam, its base branch's
    evaluation through S-169's store, its check rows
    through S-157's store, and its behindness counted
    the compare road's way, then delegate to
    `decide_status_checks`. Merge gates hold this
    store and never re-derive protection, check
    state, or branch position themselves."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        issues: IssueStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
        protection_rules: ProtectionRuleStore | None = None,
        checks: PullRequestChecksStore | None = None,
        forks: ForkPullRequestStore | None = None,
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
        self._checks = checks or PullRequestChecksStore(
            conn, repositories, accounts, issues, time_fn=time_fn)
        self._forks = forks or ForkPullRequestStore(
            conn, repositories, accounts, issues, audit=audit,
            time_fn=time_fn)

    def _behind(self, viewer: User | None, owner: object,
                repo: object, pr) -> tuple[str, int | None]:
        """Count how far the pull request's head stands
        behind its base branch's current tip: the base
        oid and the behind count (None when the
        position cannot be counted). A cross-fork head
        is fetched into the base repository under this
        gate's scratch ref, counted, and the scratch
        ref dropped — the merge road's discipline."""
        base_repo = self._repos.get_repository(owner, repo)
        if base_repo is None:
            return "", None
        base_path = self._repos.path_for(base_repo.owner, base_repo.name)
        refs = RefStore(base_path)
        base_oid = refs.resolve(branch_ref(pr.base_branch)) or ""
        if not base_oid:
            return "", None
        record = self._forks.get_cross_fork(viewer, owner, repo, pr.number)
        scratch_live = False
        try:
            if record is not None:
                head_repo = self._repos.get_repository(
                    *record.head_full_name.split("/", 1))
                if head_repo is None:
                    return base_oid, None
                head_path = self._repos.path_for(
                    head_repo.owner, head_repo.name)
                result = run_git_fetch_ref(
                    base_path, head_path,
                    branch_ref(pr.head_branch), SCRATCH_REF)
                if result.returncode != 0:
                    return base_oid, None
                scratch_live = True
                head_oid = refs.resolve(SCRATCH_REF)
            else:
                head_oid = refs.resolve(branch_ref(pr.head_branch))
            if not head_oid:
                return base_oid, None
            result = run_git_in(
                base_path,
                ["rev-list", "--count", f"{head_oid}..{base_oid}"],
                timeout=15.0)
            if result.returncode != 0:
                return base_oid, None
            try:
                return base_oid, int(result.stdout.decode().strip())
            except ValueError:
                return base_oid, None
        finally:
            if scratch_live:
                run_git_in(base_path, ["update-ref", "-d", SCRATCH_REF],
                           timeout=15.0)

    def check_pull_request(self, viewer: User | None, owner: object,
                           repo: object, number: object
                           ) -> StatusCheckDecision:
        """THE one check S-174's gate consults: this
        pull request's required-status-checks decision,
        resolved once. The pull request is read through
        S-141's seam first, so a stranger to a private
        repository gets the uniform
        `pull_request_not_found` before any check
        position is named."""
        pr = self._prs.get_pull_request(viewer, owner, repo, number)
        evaluation = self._rules.evaluate_branch(
            viewer, owner, repo, pr.base_branch)
        rows = self._checks.checks_for(viewer, owner, repo, pr.number)
        base_oid, behind = self._behind(viewer, owner, repo, pr)
        return decide_status_checks(
            evaluation, rows, number=pr.number,
            head_branch=pr.head_branch, head_oid=pr.head_oid,
            base_oid=base_oid, behind=behind)

    def enforce_pull_request(self, viewer: User | None, owner: object,
                             repo: object, number: object
                             ) -> StatusCheckDecision:
        """The check, as a refusal: returns the satisfied
        decision, or raises `status_checks_required`
        carrying the human-readable reason."""
        decision = self.check_pull_request(
            viewer, owner, repo, number)
        if not decision.satisfied:
            raise StatusChecksRequiredError(
                STATUS_CHECKS_REQUIRED, decision.reason)
        return decision


def render_status_check_decision(decision: StatusCheckDecision) -> str:
    """One status-check decision in words — exactly
    the decision's own `words`, with its blockers
    listed when it has any, escaped through S-010,
    never a colour alone. The sentences S-183's rule
    insights will quote when they answer "why was
    this merge refused?"."""
    blockers = ""
    if decision.blockers:
        items = "".join(
            f"<li>{escape_html_text(blocker)}</li>"
            for blocker in decision.blockers)
        blockers = f"<ul>{items}</ul>"
    return (
        '<div class="protection-status-checks">'
        f"<p>{escape_html_text(decision.words)}</p>"
        f"{blockers}</div>")
