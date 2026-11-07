"""Enforce for admins (S-180).

Part VIII's admin-enforcement slice: the S-169 rule
field `enforce_admins`, wired to its judgment point.
Before this slice the field was stored policy with no
teeth — S-169 stored it (default ON: sovereignty means
the owner's rules bind the owner), folded it
most-restrictive-wins, and said it in words, and every
enforcement slice (S-170..S-179) bound an admin exactly
like anyone else whatever the toggle said, each noting
that S-180 was another slice's wiring. Now there is
one place that answers, for one branch and one actor,
whether the branch's protection binds that actor:

- **The one check.** `AdminEnforcementStore` — and,
  for a caller that already holds an S-169 evaluation,
  the pure `decide_admin_enforcement` it delegates
  to — resolves a branch's protection position once
  through S-169's
  `ProtectionRuleStore.evaluate_branch` (matching,
  the documented evaluation order, and the
  most-restrictive fold are never re-derived here)
  and judges the actor's standing through S-054's
  `role_for` — the one permission function every
  surface consults. An *admin* here is exactly who
  S-054 calls admin: the repository's owner, or a
  site admin. No second notion of admin is invented,
  and collaborator grants are S-054's business (a
  caller holding a collaborator role passes it to
  the pure half as `actor_role`; the store passes
  none, exactly as the sibling gates do).
- **The law.** An unprotected branch binds nobody —
  there is nothing to enforce and nothing to exempt
  from, for admins and everyone else alike. On a
  protected branch the default binds everyone: while
  the folded `enforce_admins` stands (any matching
  rule carries it, per S-169's fold), an admin is
  bound exactly like any other actor — the owner's
  rules bind the owner. Only when *every* matching
  rule leaves enforcement for admins off is an admin
  exempt, and the exemption reaches admins alone:
  writers, readers, and anonymous actors stay bound
  whatever the toggle says, and an anonymous actor
  is never exempt — exemption requires proven admin
  standing, never the absence of a name. Toggling
  the rule changes the next check's answer in both
  directions: the judgment is a pure read over the
  stored rules and stores no verdict of its own.
- **The first door it binds.** S-170's direct-push
  check consults this judgment in this slice:
  `PullRequestProtectionStore` resolves the pusher's
  role through S-054 and passes the standing into
  `decide_direct_push`, so a direct push by an admin
  to a pull-request-protected branch is refused
  while enforcement for admins stands, and allowed —
  said in words as an admin exemption — only when
  every matching rule leaves it off. Every existing
  caller of the pure half is unchanged: the standing
  keyword defaults to not-an-admin, which is bound,
  exactly the pre-S-180 answer. The remaining gates
  consult the same one check when they judge an
  actor; until a gate consults it, its plain check
  keeps binding admins exactly as before — the
  failure direction is always towards binding, never
  towards a silent exemption. Bypass is untouched:
  an exempt admin needs no bypass, and a bound
  actor's only road around a rule remains S-179's
  audited `use_bypass` — this slice opens no second
  door and names nobody.
- **No new policy storage is owned.** No migration
  (schema stays 66; the field already lives in
  migration 65's `protection_rules`), no new
  taxonomy event (120 events stand; rule changes
  already audit under the frozen
  `repo.protection.change`, and a judgment itself
  writes nothing and audits nothing, exactly as
  S-169's refused writes do).
- **Reads ride S-169's guards.** Every check reads
  the evaluation through S-169's store and the role
  through S-054, so a stranger to a private
  repository gets the uniform `repo_not_found`
  before any branch's enforcement position is named.
- **Said in words, never a colour alone.** A
  decision carries its position as `words` — who is
  bound or exempt, on which branch, and why — and
  the one renderer says exactly those words, escaped
  through S-010. No route is invented: the store and
  the judgment are the surfaces, as S-164's seam
  landed route-free. S-183's rule insights can quote
  these sentences when they answer "why was this
  push refused — or why was the admin let through?".
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .permissions import ROLE_RANK, role_for
from .protection_rules import (
    ProtectionEvaluation, ProtectionRuleStore)
from .repositories import RepositoryError, RepositoryStore

__all__ = [
    "ADMIN_ENFORCEMENT_INVALID", "AdminEnforcementDecision",
    "AdminEnforcementError", "AdminEnforcementStore",
    "decide_admin_enforcement",
    "render_admin_enforcement_decision",
]

ADMIN_ENFORCEMENT_INVALID = "admin_enforcement_invalid"

_ROLES = frozenset(ROLE_RANK)


class AdminEnforcementError(RepositoryError):
    """An admin-enforcement misuse: a RepositoryError
    carrying `.reason`, mirroring ProtectionRuleError
    and the sibling gates' errors. Raised only for an
    unlawful judgment input (an unknown actor role) —
    never as an enforcement refusal: this slice's
    judgment allows or binds, it does not refuse."""


@dataclass(frozen=True)
class AdminEnforcementDecision:
    """One branch, one actor: whether the branch's
    protection binds that actor, resolved once — the
    S-169 evaluation and the actor's S-054 role behind
    the answer, and the answer said in words."""
    full_name: str
    branch: str
    actor_role: str | None
    evaluation: ProtectionEvaluation

    @property
    def is_protected(self) -> bool:
        """Whether any enabled rule attaches to this
        branch at all."""
        return self.evaluation.effective is not None

    @property
    def enforce_admins(self) -> bool:
        """Whether the effective (folded) policy is
        enforced for admins. An unprotected branch
        enforces nothing, so this is False there."""
        effective = self.evaluation.effective
        return bool(
            effective is not None
            and effective.settings.enforce_admins)

    @property
    def is_admin(self) -> bool:
        """Whether the actor holds admin standing on
        this repository under S-054: the owner, or a
        site admin (role 'admin')."""
        return self.actor_role == "admin"

    @property
    def exempt(self) -> bool:
        """Whether this actor is exempt from this
        branch's protection: a protected branch, an
        admin actor, and enforcement for admins off in
        every matching rule. Nobody else is ever
        exempt, and an unprotected branch exempts
        nobody — there is nothing to exempt from."""
        return (self.is_protected and self.is_admin
                and not self.enforce_admins)

    @property
    def binds_actor(self) -> bool:
        """Whether this branch's protection binds this
        actor: the branch is protected and the actor
        is not exempt."""
        return self.is_protected and not self.exempt

    @property
    def words(self) -> str:
        if not self.is_protected:
            return (
                f"Branch '{self.branch}' in {self.full_name} "
                f"is not protected: no protection rule "
                f"matches it, so there is nothing for the "
                f"enforce-for-admins toggle to bind or to "
                f"exempt anyone from.")
        if not self.is_admin:
            return (
                f"Protection on branch '{self.branch}' in "
                f"{self.full_name} binds this actor: the "
                f"actor does not hold admin standing here, "
                f"and the enforce-for-admins toggle speaks "
                f"only to admins.")
        if self.enforce_admins:
            return (
                f"Protection on branch '{self.branch}' in "
                f"{self.full_name} binds this admin: the "
                f"effective rule is enforced for admins — "
                f"the Samverk default, under which the "
                f"owner's rules bind the owner.")
        return (
            f"Protection on branch '{self.branch}' in "
            f"{self.full_name} does not bind this admin: "
            f"no matching rule enforces for admins, so "
            f"this admin is exempt from this branch's "
            f"protection. Every other actor remains "
            f"bound.")


def decide_admin_enforcement(
        evaluation: ProtectionEvaluation, *,
        actor_role: str | None = None
        ) -> AdminEnforcementDecision:
    """The pure half of the check: one branch's
    admin-enforcement decision from its already-
    resolved S-169 evaluation and the actor's S-054
    role ('admin', 'write', 'read', or None for an
    actor with no standing — anonymous included).
    No database is touched here, so the judgment is
    provable in isolation; the store below only has
    to gather the evaluation and the role honestly."""
    if actor_role is not None and actor_role not in _ROLES:
        raise AdminEnforcementError(
            ADMIN_ENFORCEMENT_INVALID,
            "An actor's role is 'admin', 'write', 'read', "
            "or no role at all.")
    return AdminEnforcementDecision(
        full_name=evaluation.full_name,
        branch=evaluation.branch,
        actor_role=actor_role,
        evaluation=evaluation)


class AdminEnforcementStore:
    """The store half of the check: gather one
    branch's evaluation through S-169's store — the
    one evaluation Part VIII consults — and the
    actor's role through S-054's `role_for`, then
    delegate to `decide_admin_enforcement`.
    Enforcement gates hold this store (or call the
    pure half with a role they already hold) and
    never re-derive the toggle themselves."""

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

    def check_branch(self, viewer: User | None, owner: object,
                     repo: object, branch: object
                     ) -> AdminEnforcementDecision:
        """THE one check S-180's judgment point
        consults: this branch's admin-enforcement
        decision for `viewer`, resolved once. The
        evaluation is read through S-169, so a
        stranger to a private repository gets the
        uniform `repo_not_found` before any
        enforcement position is named."""
        evaluation = self._rules.evaluate_branch(
            viewer, owner, repo, branch)
        current = self._repos.get_repository(owner, repo)
        role = (role_for(viewer, current)
                if current is not None else None)
        return decide_admin_enforcement(
            evaluation, actor_role=role)

    def binds_actor(self, viewer: User | None, owner: object,
                    repo: object, branch: object) -> bool:
        """Whether this branch's protection binds this
        actor — the boolean a gate asks before it
        applies its refusal to the actor in front of
        it."""
        return self.check_branch(
            viewer, owner, repo, branch).binds_actor

    def exempt_actor(self, viewer: User | None, owner: object,
                     repo: object, branch: object) -> bool:
        """Whether this actor is exempt from this
        branch's protection — True only for an admin
        on a protected branch whose every matching
        rule leaves enforcement for admins off."""
        return self.check_branch(
            viewer, owner, repo, branch).exempt


def render_admin_enforcement_decision(
        decision: AdminEnforcementDecision) -> str:
    """One admin-enforcement decision in words —
    exactly the decision's own `words`, escaped
    through S-010, never a colour alone. The
    sentences S-183's rule insights will quote when
    they answer "why was the admin let through?"."""
    return (
        '<div class="admin-enforcement">'
        f"<p>{escape_html_text(decision.words)}</p></div>")
