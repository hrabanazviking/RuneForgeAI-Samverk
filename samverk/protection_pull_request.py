"""Require a pull request before merging (S-170).

Part VIII's first enforcement slice: the S-169 rule
field `require_pull_request`, wired to its refusal
point. Before this slice the field was stored policy
with no teeth — a rule could say a pull request was
required and a direct push to the branch still landed.
Now there is one place that answers, for a push, the
question the receive-pack gate asks:

- **The one check.** `PullRequestProtectionStore` —
  and, for a caller that already holds an S-169
  evaluation, the pure `decide_direct_push` it
  delegates to — resolves a branch's protection
  position once through S-169's
  `ProtectionRuleStore.evaluate_branch` (the one
  evaluation Part VIII consults; matching, ordering,
  and the most-restrictive fold are never re-derived
  here) and refuses a *direct* push when the effective
  policy requires a pull request. No new policy
  storage is owned: no migration (schema stays 65,
  the field already lives in migration 65's
  `protection_rules`), no new taxonomy event (119
  events stand; rule changes already audit under the
  frozen `repo.protection.change`, and a refusal
  itself writes nothing and audits nothing, exactly
  as S-169's refused writes do).
- **The refusal is said in words.** A refused push
  meets one human-readable reason naming the branch,
  the repository, the pattern(s) whose rule requires
  a pull request, and the remedy — open a pull
  request instead of pushing directly. The reason is
  the same sentence at every door: the store's error
  (`pull_request_required`, a `RepositoryError`
  carrying `.reason`, in the house shape), the gate
  plug-in's veto string, and the decision's own
  `words` all carry it, so S-183's rule insights can
  quote exactly what the pusher was told.
- **The receive-pack door is S-089's gate.**
  `receive_gate_plugin` adapts the check to the
  `protection` stage of the pre-receive gate point —
  the documented first stage, cheapest and most
  specific, before any content is inspected. The
  plug-in judges the ref updates the gate context
  carries: a branch ref (`refs/heads/<branch>`) whose
  effective rule requires a pull request vetoes the
  whole push, first refusal wins. Non-branch refs
  (tags and the rest) are not this slice's business.
  A gate context carrying no updates judges nothing —
  S-089's standing law: transports pass the updates
  they know (today the wire transports know none,
  pack contents being git's business), so the
  enforcement binds callers that have ref detail,
  and the battery proves it with real updates.
- **Pull request merges are not direct pushes.** The
  S-153 merge road (and its S-154/S-155 siblings)
  lands a merge by minting a commit and moving the
  base ref through `RefStore` compare-and-swap
  inside the forge — it never passes through
  receive-pack, so this refusal cannot block it by
  construction, and the battery proves a protected
  base still merges by pull request while a direct
  push to it is refused. A caller that *is* the
  merge road and ever meets this check says so with
  `via_pull_request=True` (the gate plug-in reads
  the same flag from the gate payload's
  `via_pull_request` key — a key the wire transports
  never set), and the check allows, said in words as
  a pull-request landing, never silently.
- **Everyone pushing directly is refused.** Bypass
  lists (S-179), push-actor restrictions (S-178),
  and the enforce-for-admins toggle (S-180) are
  later slices' wiring over the same effective
  policy; until they land, no stored list opens this
  door — a bypass name in a rule does not exempt a
  direct push from S-170's refusal, and an admin
  pushing directly is refused like anyone else.
  Branch creation and deletion by direct push are
  pushes to the branch and are refused on the same
  words (deletion carries S-177's own additional
  block, later); what is *not* refused is a push to
  a branch no enabled rule requiring a pull request
  matches — unprotected branches, rules with the
  requirement off, and disabled rules all push
  exactly as before.
- **Reads ride S-169's guards, and mutate nothing.**
  Every check reads the evaluation through S-169's
  store, so a stranger to a private repository gets
  the uniform `repo_not_found` before any branch's
  protection position is named. The check is a pure
  read: no row changes, no audit row, no stored
  verdict of its own to drift from the rules it
  reads — toggle the rule and the next check answers
  the new position, in both directions.
- **Said in words, never a colour alone.** A decision
  carries its position as `words` — allowed or
  refused, the branch, and why — and the one renderer
  says exactly those words, escaped through S-010.
  No route is invented: the gate plug-in and the
  store are the surfaces, as S-164's seam landed
  route-free.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .protection_rules import (
    ProtectionEvaluation, ProtectionRuleStore)
from .receive_gate import GateVeto
from .repositories import RepositoryError, RepositoryStore

__all__ = [
    "PULL_REQUEST_REQUIRED", "DirectPushDecision",
    "PullRequestProtectionStore", "PullRequestRequiredError",
    "branch_from_ref", "decide_direct_push",
    "render_direct_push_decision",
]

PULL_REQUEST_REQUIRED = "pull_request_required"

_BRANCH_PREFIX = "refs/heads/"


class PullRequestRequiredError(RepositoryError):
    """A direct-push refusal: a RepositoryError carrying
    `.reason` (`pull_request_required`), mirroring
    ProtectionRuleError and BranchHousekeepingError."""


def branch_from_ref(ref: object) -> str | None:
    """The branch name a full ref names, or None when
    the ref is not a branch ref at all (a tag, HEAD, a
    scratch ref): only `refs/heads/<branch>` is a
    branch a protection rule can attach to."""
    if not isinstance(ref, str):
        return None
    if not ref.startswith(_BRANCH_PREFIX):
        return None
    branch = ref[len(_BRANCH_PREFIX):]
    return branch or None


def _ref_of(update: object) -> object:
    """One ref update's ref, from whatever shape the
    caller carries it in: a RefUpdate (`.ref`), a
    mapping (`ref` key), or a tuple/list whose first
    item is the ref."""
    ref = getattr(update, "ref", None)
    if ref is not None:
        return ref
    if isinstance(update, dict):
        return update.get("ref")
    if isinstance(update, (tuple, list)) and update:
        return update[0]
    return None


def refusal_reason(evaluation: ProtectionEvaluation) -> str:
    """The one human-readable refusal sentence for a
    branch whose effective rule requires a pull
    request: the branch, the repository, the matching
    pattern(s) that carry the requirement, and the
    remedy. Every door quotes this sentence verbatim."""
    patterns = ", ".join(
        f"'{rule.pattern}'" for rule in evaluation.matching
        if rule.settings.require_pull_request)
    return (
        f"Direct push to branch '{evaluation.branch}' in "
        f"{evaluation.full_name} was refused: protection "
        f"rule {patterns} requires a pull request before "
        f"merging, so this branch cannot be pushed to "
        f"directly. Open a pull request to land changes "
        f"on '{evaluation.branch}' instead.")


@dataclass(frozen=True)
class DirectPushDecision:
    """One branch's direct-push position, resolved
    once: the S-169 evaluation behind the answer, and
    the answer said in words."""
    full_name: str
    branch: str
    via_pull_request: bool
    evaluation: ProtectionEvaluation

    @property
    def requires_pull_request(self) -> bool:
        """Whether the effective policy for this branch
        requires a pull request before merging."""
        effective = self.evaluation.effective
        return bool(
            effective is not None
            and effective.settings.require_pull_request)

    @property
    def allowed(self) -> bool:
        """Whether a push on this road may move this
        branch: a pull-request landing always may; a
        direct push may unless the effective rule
        requires a pull request."""
        return self.via_pull_request or not self.requires_pull_request

    @property
    def reason(self) -> str:
        """The refusal sentence when refused, else ''."""
        if self.allowed:
            return ""
        return refusal_reason(self.evaluation)

    @property
    def words(self) -> str:
        if self.via_pull_request:
            return (
                f"Push to branch '{self.branch}' in "
                f"{self.full_name} arrives by pull request: "
                f"the merge road is not a direct push, so "
                f"the pull-request requirement does not "
                f"refuse it.")
        if not self.requires_pull_request:
            return (
                f"Direct push to branch '{self.branch}' in "
                f"{self.full_name} is allowed: no protection "
                f"rule matching this branch requires a pull "
                f"request.")
        return self.reason


def decide_direct_push(
        evaluation: ProtectionEvaluation, *,
        via_pull_request: bool = False) -> DirectPushDecision:
    """The pure half of the check: one branch's
    direct-push decision from its already-resolved
    S-169 evaluation. No database is touched here, so
    the judgment is provable in isolation; the store
    below only has to gather the evaluation honestly."""
    if not isinstance(via_pull_request, bool):
        raise PullRequestRequiredError(
            "push_check_invalid",
            "Whether a push arrives by pull request is "
            "yes or no (a boolean).")
    return DirectPushDecision(
        full_name=evaluation.full_name,
        branch=evaluation.branch,
        via_pull_request=via_pull_request,
        evaluation=evaluation)


class PullRequestProtectionStore:
    """The store half of the check: gather one branch's
    evaluation through S-169's store — the one
    evaluation Part VIII consults — then delegate to
    `decide_direct_push`. Receive-pack callers hold
    this store (or its gate plug-in) and never
    re-derive matching or the fold themselves."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
        protection_rules: ProtectionRuleStore | None = None,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._audit = audit
        self._now = time_fn
        self._rules = protection_rules or ProtectionRuleStore(
            conn, repositories, accounts,
            audit=audit, time_fn=time_fn)

    # -- one branch ------------------------------------------------

    def check_branch(self, viewer: User | None, owner: object,
                     repo: object, branch: object, *,
                     via_pull_request: bool = False
                     ) -> DirectPushDecision:
        """THE one check S-170's refusal point consults:
        this branch's direct-push decision, resolved
        once. The evaluation is read through S-169, so
        a stranger to a private repository gets the
        uniform `repo_not_found` before any protection
        position is named."""
        evaluation = self._rules.evaluate_branch(
            viewer, owner, repo, branch)
        return decide_direct_push(
            evaluation, via_pull_request=via_pull_request)

    def enforce_branch(self, viewer: User | None, owner: object,
                       repo: object, branch: object, *,
                       via_pull_request: bool = False
                       ) -> DirectPushDecision:
        """The check, as a refusal: returns the allowed
        decision, or raises `pull_request_required`
        carrying the human-readable reason."""
        decision = self.check_branch(
            viewer, owner, repo, branch,
            via_pull_request=via_pull_request)
        if not decision.allowed:
            raise PullRequestRequiredError(
                PULL_REQUEST_REQUIRED, decision.reason)
        return decision

    # -- a whole push (the receive-pack shape) ----------------------

    def check_push(self, viewer: User | None, owner: object,
                   repo: object, updates, *,
                   via_pull_request: bool = False
                   ) -> tuple:
        """Every branch decision in one push, in the
        push's own update order. Non-branch refs are
        skipped — they are not this slice's business.
        The push as a whole is allowed iff every
        returned decision is allowed."""
        decisions = []
        for update in updates or ():
            branch = branch_from_ref(_ref_of(update))
            if branch is None:
                continue
            decisions.append(self.check_branch(
                viewer, owner, repo, branch,
                via_pull_request=via_pull_request))
        return tuple(decisions)

    def enforce_push(self, viewer: User | None, owner: object,
                     repo: object, updates, *,
                     via_pull_request: bool = False
                     ) -> tuple:
        """A whole push, as a refusal: the first refused
        branch in update order raises
        `pull_request_required` with its reason —
        first refusal wins, as at S-089's gate."""
        decisions = self.check_push(
            viewer, owner, repo, updates,
            via_pull_request=via_pull_request)
        for decision in decisions:
            if not decision.allowed:
                raise PullRequestRequiredError(
                    PULL_REQUEST_REQUIRED, decision.reason)
        return decisions

    # -- the S-089 gate plug-in --------------------------------------

    def receive_gate_plugin(self):
        """This check as an S-089 `protection`-stage
        plug-in: a callable over the gate context that
        allows (returns None) or vetoes with the
        refusal sentence (raises GateVeto). The actor
        is the gate context's username, resolved
        through the account store — an actor that
        resolves to nobody is judged as an anonymous
        viewer, so a private repository's position is
        never named to them (the gate then fails
        closed on S-169's `repo_not_found`, as every
        gate stage does on error). The merge road
        marks its landings with the payload key
        `via_pull_request`; the wire transports never
        set it, so a receive-pack push is always
        judged as the direct push it is."""
        def plugin(context):
            actor = context.actor
            viewer = None
            if isinstance(actor, str) and actor:
                viewer = self._accounts.get_by_username(actor)
            via = bool(context.payload.get("via_pull_request"))
            decisions = self.check_push(
                viewer, context.owner, context.repo_name,
                context.updates, via_pull_request=via)
            for decision in decisions:
                if not decision.allowed:
                    raise GateVeto(decision.reason)
            return None
        return plugin


def render_direct_push_decision(decision: DirectPushDecision) -> str:
    """One direct-push decision in words — exactly the
    decision's own `words`, escaped through S-010,
    never a colour alone. The sentences S-183's rule
    insights will quote when they answer "why was
    this push refused?"."""
    return (
        '<div class="pull-request-protection">'
        f"<p>{escape_html_text(decision.words)}</p></div>")
