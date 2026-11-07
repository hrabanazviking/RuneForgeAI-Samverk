"""Block force pushes and branch deletion (S-177).

On protected patterns, for everyone, admins included:
the branch protection rule (S-169) blocks force
pushes and branch deletion by default, and this slice
is the gate that judges the shape of a push's branch
updates against those two blocks, in the shape S-170
(direct-push refusal), S-175 (signed commits) and
S-176 (linear history) established — plus the second
enforcement point for deletion, the merge path's own
housekeeping guard.

- **The blocks are the folded rule's word.** The
  branch is resolved once through S-169's
  `ProtectionRuleStore.evaluate_branch` (matching,
  documented evaluation order, and the
  most-restrictive fold are never re-derived here):
  the gate speaks the folded `block_force_pushes` and
  `block_branch_deletion`. Both default ON in the
  S-169 shape, so a branch a rule matches is
  force-proof and deletion-proof unless every
  matching rule turns the block off. A branch no rule
  matches carries no block, and the gate is satisfied
  by construction.
- **A push update has one shape.** Judged from its
  old and new oids and, for a move, the ancestry
  between them: a creation (no old tip), a
  fast-forward (the old tip is an ancestor of the new
  tip), a force push (it is not), a deletion (no new
  tip), a no-op (old equals new), or unproven (a move
  whose fast-forwardness could not be proven).
  Ancestry is git's own answer (`merge-base
  --is-ancestor`), never a guess from oid shapes.
- **Everyone is bound.** The judgment never consults
  the pusher's role: owner, admin, writer — a blocked
  shape is refused for all of them alike. The two
  named softenings land later and are not smuggled in
  here: S-179's bypass list (named bypassers, every
  bypass audit-logged) and S-180's enforce-for-admins
  toggle. Until they land, there is no silent door.
- **An unproven move never passes a force block.**
  When ancestry cannot be read at all (an oid that
  does not resolve, an unreadable object), a move on a
  branch whose rule blocks force pushes is refused
  with the position said in words — a gate that
  blocks force pushes never passes on no proof that
  the move is not one. With no block folded, an
  unproven move binds nothing and the decision still
  says it was not proven.
- **Creations, fast-forwards and no-ops pass.**
  Creating a branch moves nothing that exists, a
  fast-forward loses no commit, and a no-op changes
  nothing: neither block speaks to them, and the gate
  is satisfied whatever the folded rule says.
- **Deletion is judged at two points.** Here, a push
  carrying a branch deletion is refused while
  `block_branch_deletion` binds. On the merge path,
  S-159's delete-head-branch-on-merge hook routes
  through the one deletability predicate, whose
  protection guard S-177 wires to S-169's
  `ProtectionRuleStore.is_protected` — so a protected
  head branch is kept after its merge lands, in words,
  by the same rule that blocks its pushed deletion.
- **The refusal is one code, the reason a sentence.**
  `enforce_*` raises `protected_push_refused` (a
  `RepositoryError` carrying `.reason`) with the
  first blocker's sentence: what shape the update is,
  which block speaks, and the remedy (fast-forward
  the work, or remove or retarget the rule first).
  The decision says its whole position in words, and
  the one renderer prints exactly those words escaped
  through S-010, never a colour alone.
- **A pure read.** The judgment writes nothing and
  audits nothing, so no taxonomy event is added
  (119 stand) and no migration is claimed (schema
  stays 66); rule changes already audit under the
  frozen `repo.protection.change`, and
  docs/AUDIT_TAXONOMY.md records the slice on that
  basis. Reads ride the house guards first — S-169's
  evaluation — so a stranger to a private repository
  gets the uniform `repo_not_found` before any push
  position is named.
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
from .proc import run_git_in
from .protection_pull_request import branch_from_ref
from .protection_rules import ProtectionEvaluation, ProtectionRuleStore
from .receive_gate import GateVeto
from .repositories import RepositoryError, RepositoryStore

__all__ = [
    "PROTECTED_PUSH_REFUSED", "CREATION", "DELETION",
    "FAST_FORWARD", "FORCE", "NO_OP", "UNPROVEN",
    "PushShapeDecision", "PushShapeProtectionStore",
    "PushShapeRefusedError", "decide_push_shape",
    "render_push_shape_decision", "update_shape",
]

PROTECTED_PUSH_REFUSED = "protected_push_refused"

#: The null oid a ref update carries for a ref that
#: does not exist on that side (creation / deletion).
ZERO_OID = "0" * 40

#: The shapes one branch update can take.
CREATION = "creation"
FAST_FORWARD = "fast-forward"
FORCE = "force"
DELETION = "deletion"
NO_OP = "no-op"
UNPROVEN = "unproven"

_SHAPE_WORDS = {
    CREATION: "the update creates the branch",
    FAST_FORWARD: "the update fast-forwards the branch",
    FORCE: "the update is a force push",
    DELETION: "the update deletes the branch",
    NO_OP: "the update changes nothing",
    UNPROVEN: ("the update moves the branch, and its "
                "fast-forwardness was not proven"),
}


class PushShapeRefusedError(RepositoryError):
    """A protected-push refusal: a RepositoryError
    carrying `.reason` (`protected_push_refused`),
    mirroring LinearHistoryRequiredError and
    SignedCommitsRequiredError."""


def update_shape(old_oid: str, new_oid: str,
                 ancestor: bool | None) -> str:
    """One branch update's shape, from its oids and —
    for a move — the ancestry between them. An update
    whose new oid is unknown is unproven; old equal to
    new is a no-op; no new tip is a deletion; no old
    tip is a creation; a move is a fast-forward when
    the old tip is an ancestor of the new tip, a force
    push when it is not, and unproven when ancestry
    was not read."""
    old = str(old_oid or "")
    new = str(new_oid or "")
    if not new:
        return UNPROVEN
    if old == new:
        return NO_OP
    if new == ZERO_OID:
        return DELETION
    if not old or old == ZERO_OID:
        return CREATION
    if ancestor is True:
        return FAST_FORWARD
    if ancestor is False:
        return FORCE
    return UNPROVEN


@dataclass(frozen=True)
class PushShapeDecision:
    """One branch update's push-shape position,
    resolved once: the S-169 evaluation for the branch
    being pushed to, the update's old and new oids,
    and the shape they make. The answer is said in
    words; no role is consulted anywhere in it."""
    full_name: str
    branch: str
    evaluation: ProtectionEvaluation
    old_oid: str
    new_oid: str
    shape: str

    @property
    def _settings(self):
        effective = self.evaluation.effective
        return effective.settings if effective is not None else None

    @property
    def blocks_force_pushes(self) -> bool:
        settings = self._settings
        return bool(settings is not None
                    and settings.block_force_pushes)

    @property
    def blocks_branch_deletion(self) -> bool:
        settings = self._settings
        return bool(settings is not None
                    and settings.block_branch_deletion)

    @property
    def blockers(self) -> tuple:
        out: list[str] = []
        if self.shape == FORCE and self.blocks_force_pushes:
            out.append(
                f"This update is a force push to branch "
                f"'{self.branch}' (the old tip "
                f"{self.old_oid[:12]} is not an ancestor "
                f"of the new tip {self.new_oid[:12]}), "
                f"and the rule blocks force pushes on "
                f"branch '{self.branch}'; rebase the "
                f"work onto the current tip so the push "
                f"fast-forwards, and push again. The "
                f"block binds everyone, admins included.")
        elif self.shape == DELETION \
                and self.blocks_branch_deletion:
            out.append(
                f"This update deletes branch "
                f"'{self.branch}', and the rule blocks "
                f"branch deletion on branch "
                f"'{self.branch}'; a protected branch "
                f"cannot be deleted — remove or retarget "
                f"the protection rule first if the branch "
                f"must go. The block binds everyone, "
                f"admins included.")
        elif self.shape == UNPROVEN \
                and self.blocks_force_pushes \
                and self.old_oid and self.old_oid != ZERO_OID \
                and self.new_oid and self.new_oid != ZERO_OID:
            out.append(
                f"This update moves branch "
                f"'{self.branch}', its fast-forwardness "
                f"could not be proven, and the rule "
                f"blocks force pushes on branch "
                f"'{self.branch}'; a gate that blocks "
                f"force pushes never passes a move it "
                f"cannot prove is a fast-forward — push "
                f"again so the update can be judged.")
        return tuple(out)

    @property
    def satisfied(self) -> bool:
        return not self.blockers

    @property
    def reason(self) -> str:
        blockers = self.blockers
        if blockers:
            return blockers[0]
        return self.words

    @property
    def words(self) -> str:
        shape_words = _SHAPE_WORDS[self.shape]
        settings = self._settings
        if settings is None:
            rule_words = "no protection rule matches"
        elif self.shape == FORCE:
            rule_words = ("force pushes are blocked"
                          if self.blocks_force_pushes
                          else "force pushes are not blocked")
        elif self.shape == DELETION:
            rule_words = ("branch deletion is blocked"
                          if self.blocks_branch_deletion
                          else "branch deletion is not blocked")
        elif self.shape == UNPROVEN:
            rule_words = ("force pushes are blocked"
                          if self.blocks_force_pushes
                          else "force pushes are not blocked")
        else:
            rule_words = ("the folded rule does not block "
                          "this shape")
        verdict = "satisfied" if self.satisfied else "not satisfied"
        return (
            f"Push-shape gate for a push to branch "
            f"'{self.branch}' in {self.full_name}: "
            f"{shape_words}; {rule_words}. The "
            f"push-shape gate is {verdict}.")


def decide_push_shape(
        evaluation: ProtectionEvaluation,
        old_oid: str, new_oid: str, *,
        ancestor: bool | None = None) -> PushShapeDecision:
    """The pure half of the gate: one branch update's
    push-shape decision from its already-resolved
    S-169 evaluation, its old and new oids, and — for
    a move — whether the old tip is an ancestor of the
    new tip (None when ancestry was not read). No
    database and no git repository are touched here,
    so the judgment is provable in isolation; the
    store below only has to gather the ancestry
    honestly."""
    return PushShapeDecision(
        full_name=evaluation.full_name,
        branch=evaluation.branch,
        evaluation=evaluation,
        old_oid=str(old_oid or ""),
        new_oid=str(new_oid or ""),
        shape=update_shape(old_oid, new_oid, ancestor))


def _ref_of(update: object) -> object:
    """One ref update's ref, from whatever shape the
    caller carries it in: a RefUpdate (`.ref`), a
    mapping (`ref` key), or a tuple/list whose first
    item is the ref — the S-170 shape, so callers that
    carry pushes in any of these shapes work here."""
    ref = getattr(update, "ref", None)
    if ref is not None:
        return ref
    if isinstance(update, dict):
        return update.get("ref")
    if isinstance(update, (tuple, list)) and update:
        return update[0]
    return None


def _oid_of(update: object, *names: str, index: int) -> str:
    """One ref update's old or new oid, from the same
    shapes: a RefUpdate's `.old_oid` / `.new_oid`, a
    mapping's `old` / `new` / `old_oid` / `new_oid`
    keys, or a tuple/list position. '' when unknown —
    the caller then judges nothing, per S-089's law
    that transports pass the updates they know."""
    for name in names:
        value = getattr(update, name, None)
        if value:
            return str(value)
    if isinstance(update, dict):
        for name in names:
            if update.get(name):
                return str(update[name])
    if isinstance(update, (tuple, list)) and len(update) > index:
        return str(update[index]) if update[index] else ""
    return ""


class PushShapeProtectionStore:
    """The store half of the gate: gather one branch's
    evaluation through S-169's store, read the ancestry
    a move needs through git, and delegate to
    `decide_push_shape`. Push callers hold this store
    and never re-derive protection or ancestry
    themselves."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        issues: IssueStore | None = None,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
        protection_rules: ProtectionRuleStore | None = None,
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

    # -- git reading -------------------------------------------------

    def _is_ancestor(self, repo_path, old_oid: str,
                     new_oid: str) -> bool | None:
        """Git's own ancestry answer: True when the old
        tip is an ancestor of the new tip, False when it
        is not, None when git cannot answer at all (an
        oid that does not resolve, an unreadable
        object) — the caller then judges the move
        unproven, never guessed."""
        result = run_git_in(
            repo_path,
            ["merge-base", "--is-ancestor", old_oid, new_oid],
            timeout=15.0)
        if result.returncode == 0:
            return True
        if result.returncode == 1:
            return False
        return None

    # -- the push door -------------------------------------------------

    def check_push_update(self, viewer: User | None, owner: object,
                          repo: object, branch: object,
                          old_oid: str, new_oid: str
                          ) -> PushShapeDecision:
        """THE one check the push door consults: this
        branch update's push-shape decision. The
        evaluation is read through S-169, so a stranger
        to a private repository gets the uniform
        `repo_not_found` before any push position is
        named. The pusher's role is never consulted:
        the block binds everyone, admins included."""
        evaluation = self._rules.evaluate_branch(
            viewer, owner, repo, branch)
        old = str(old_oid or "")
        new = str(new_oid or "")
        ancestor: bool | None = None
        if old and old != ZERO_OID and new and new != ZERO_OID \
                and old != new:
            base_repo = self._repos.get_repository(owner, repo)
            if base_repo is not None:
                repo_path = self._repos.path_for(
                    base_repo.owner, base_repo.name)
                ancestor = self._is_ancestor(repo_path, old, new)
        return decide_push_shape(evaluation, old, new,
                                 ancestor=ancestor)

    def enforce_push_update(self, viewer: User | None, owner: object,
                            repo: object, branch: object,
                            old_oid: str, new_oid: str
                            ) -> PushShapeDecision:
        """The push check, as a refusal: returns the
        satisfied decision, or raises
        `protected_push_refused` carrying the
        human-readable reason."""
        decision = self.check_push_update(
            viewer, owner, repo, branch, old_oid, new_oid)
        if not decision.satisfied:
            raise PushShapeRefusedError(
                PROTECTED_PUSH_REFUSED, decision.reason)
        return decision

    def check_push(self, viewer: User | None, owner: object,
                   repo: object, updates) -> tuple:
        """Every branch decision in one push, in the
        push's own update order. Non-branch refs are
        skipped (tag protection is S-182's own block).
        Updates whose new oid is unknown carry no shape
        this gate can judge and are skipped — S-089's
        law that transports pass the updates they
        know."""
        decisions = []
        for update in updates or ():
            branch = branch_from_ref(_ref_of(update))
            if branch is None:
                continue
            old_oid = _oid_of(update, "old_oid", "old", index=1)
            new_oid = _oid_of(update, "new_oid", "new", index=2)
            if not new_oid:
                continue
            decisions.append(self.check_push_update(
                viewer, owner, repo, branch, old_oid, new_oid))
        return tuple(decisions)

    def enforce_push(self, viewer: User | None, owner: object,
                     repo: object, updates) -> tuple:
        """A whole push, as a refusal: the first refused
        branch in update order raises
        `protected_push_refused` with its reason — first
        refusal wins, as at S-089's gate."""
        decisions = self.check_push(viewer, owner, repo, updates)
        for decision in decisions:
            if not decision.satisfied:
                raise PushShapeRefusedError(
                    PROTECTED_PUSH_REFUSED, decision.reason)
        return decisions

    # -- the S-089 gate plug-in -----------------------------------------

    def receive_gate_plugin(self):
        """This check as an S-089 `protection`-stage
        plug-in: a callable over the gate context that
        allows (returns None) or vetoes with the refusal
        sentence (raises GateVeto). The actor is the
        gate context's username, resolved through the
        account store — an actor that resolves to nobody
        is judged as an anonymous viewer, so a private
        repository's position is never named to them
        (the gate then fails closed on S-169's
        `repo_not_found`, as every gate stage does on
        error). Unlike the commit-content gates, this
        gate takes no `via_pull_request` exemption: its
        judgment is the push's shape, which binds at
        every door — and a pull-request landing is a
        fast-forward by construction, so a true landing
        passes as what it is."""
        def plugin(context):
            actor = context.actor
            viewer = None
            if isinstance(actor, str) and actor:
                viewer = self._accounts.get_by_username(actor)
            decisions = self.check_push(
                viewer, context.owner, context.repo_name,
                context.updates)
            for decision in decisions:
                if not decision.satisfied:
                    raise GateVeto(decision.reason)
            return None
        return plugin


def render_push_shape_decision(decision: PushShapeDecision) -> str:
    """One push-shape decision in words — exactly the
    decision's own `words`, with its blockers listed
    when it has any, escaped through S-010, never a
    colour alone. The sentences S-183's rule insights
    will quote when they answer "why was this push
    refused?"."""
    blockers = ""
    if decision.blockers:
        items = "".join(
            f"<li>{escape_html_text(blocker)}</li>"
            for blocker in decision.blockers)
        blockers = f"<ul>{items}</ul>"
    return (
        '<div class="protection-push-shape">'
        f"<p>{escape_html_text(decision.words)}</p>"
        f"{blockers}</div>")
