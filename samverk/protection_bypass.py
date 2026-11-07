"""Bypass list (S-179).

Part VIII's bypass gate: the S-169 rule field
`bypass_actors`, wired to its one audited road.
Before this slice the field was stored policy with
no teeth and no witness — every enforcement slice
(S-170, S-177, S-178) refused to let a bypass name
open its door, because a bypass that happens
silently is just a second, hidden rulebook. Now
there is exactly one place that answers, for one
branch and one actor, whether that actor may
bypass the branch's protection rules — and exactly
one road on which a bypass may actually be used,
and that road writes the audit row before it
answers yes.

- **The one check.** `BypassProtectionStore` — and,
  for a caller that already holds an S-169
  evaluation, the pure `decide_bypass` it delegates
  to — resolves a branch's protection position once
  through S-169's
  `ProtectionRuleStore.evaluate_branch` (matching,
  documented evaluation order, and the
  most-restrictive fold are never re-derived here)
  and speaks the folded `bypass_actors`: the
  intersection over *every* matching rule, so an
  actor bypasses only when every matching rule
  names them, and a matching rule whose bypass list
  is empty closes the door for the branch as a
  whole (S-169's fold, pinned there). No new policy
  storage is owned: no migration (schema stays 66;
  the field already lives in migration 65's
  `protection_rules`).
- **Named means named, as a user or through a
  team.** The naming semantics are S-178's, reused
  not re-derived (`matched_entry`): an entry with
  no `/` is a user name and names that user; an
  entry of the form `owner/team` names everyone the
  caller states belongs to it (`actor_teams`, full
  or bare form; another owner's same-named team
  names nothing; membership machinery itself is
  S-187's and is never guessed). Names compare
  case-insensitively, as usernames do. An anonymous
  actor bypasses nothing: the gate never passes on
  no proof of who is asking.
- **Every bypass is audit-logged — by
  construction.** The check itself is a pure read
  and audits nothing. The *use* of a bypass is
  `use_bypass`: it re-checks the decision, resolves
  the bypasser to a real account, and appends the
  audit event this slice claims —
  `repo.protection.bypass` (taxonomy 119 -> 120:
  29 auth, 79 repo, 12 admin) — with detail naming
  the branch, the matching patterns and rule ids,
  the bypass entry that named the actor, and the
  gate being bypassed, as stated by the caller.
  Only after the row lands does it return the
  decision, carrying the row's sequence number. A
  store built without an audit log cannot use a
  bypass at all — it fails closed with
  `bypass_audit_required`, because a bypass that
  cannot be logged must not happen. There is no
  other road: the enforcement gates' own checks
  keep refusing a bypass name exactly as before
  (their batteries still pin it), so no silent
  door exists anywhere — the only door is this
  one, and it keeps a witness.
- **Shown on the rule — no silent doors.** A
  decision carries its position as `words`: who may
  bypass this branch, through which entry, and the
  reminder that every bypass is audit-logged. Per
  rule, `rule_bypass_words` says the same for one
  rule alone: its bypass names, or that it names
  nobody and so closes the door. Both renderers say
  exactly those words, escaped through S-010,
  never a colour alone. S-169's rule and evaluation
  words already list the bypass names; this slice
  gives the list its own sentences for the surfaces
  that answer "who can bypass this?".
- **The refusal is said in words.** A refused use
  raises `bypass_not_allowed` (a `RepositoryError`
  carrying `.reason`) with one human-readable
  sentence naming the branch, the repository, the
  folded bypass list (or that nobody is named) and
  who was refused. An unresolvable bypasser — a
  name no account carries — is refused the same
  way: a bypass is a person's act, witnessed under
  their account, never an anonymous one's.
- **Reads ride S-169's guards.** Every check reads
  the evaluation through S-169's store, so a
  stranger to a private repository gets the uniform
  `repo_not_found` before any bypass position is
  named.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .protection_push_actors import matched_entry
from .protection_rules import (
    ProtectionEvaluation, ProtectionRule, ProtectionRuleStore)
from .repositories import RepositoryError, RepositoryStore

__all__ = [
    "BYPASS_AUDIT_REQUIRED", "BYPASS_EVENT", "BYPASS_NOT_ALLOWED",
    "BypassDecision", "BypassError", "BypassNotAllowedError",
    "BypassProtectionStore", "BypassUse", "actor_may_bypass",
    "decide_bypass", "render_bypass_decision", "render_bypass_use",
    "render_rule_bypass", "rule_bypass_words",
]

#: The audit event a used bypass writes (S-179's
#: taxonomy claim, append-only per the taxonomy rules).
BYPASS_EVENT = "repo.protection.bypass"

BYPASS_NOT_ALLOWED = "bypass_not_allowed"
BYPASS_AUDIT_REQUIRED = "bypass_audit_required"


class BypassError(RepositoryError):
    """A bypass-shape error: a RepositoryError carrying
    `.reason`, in the house shape."""


class BypassNotAllowedError(BypassError):
    """A refused bypass use: `bypass_not_allowed`,
    carrying the human-readable reason."""


def _norm(name: str) -> str:
    return name.strip().lower()


def _actor_phrase(actor: str | None) -> str:
    if actor:
        return f"'{actor}'"
    return "an anonymous actor"


def actor_may_bypass(bypass_actors, actor, actor_teams=()) -> bool:
    """Whether this actor is named by the folded
    `bypass_actors` list: directly, as a user, or
    through a stated team membership (S-178's
    `matched_entry` semantics). An empty list names
    nobody."""
    return matched_entry(bypass_actors, actor, actor_teams) is not None


def refusal_reason(evaluation: ProtectionEvaluation,
                   actor: str | None) -> str:
    """The one human-readable refusal sentence for an
    actor the folded bypass list does not name."""
    patterns = ", ".join(
        f"'{rule.pattern}'" for rule in evaluation.matching)
    bypass = evaluation.effective.settings.bypass_actors \
        if evaluation.effective is not None else ()
    if bypass:
        named = ("the folded bypass list (from rule "
                 f"{patterns}) names only: {', '.join(bypass)}")
    else:
        named = ("no matching rule names any bypasser — a "
                 "rule whose bypass list is empty closes "
                 "the door for the branch as a whole")
    return (
        f"Bypass of the protection rules matching branch "
        f"'{evaluation.branch}' in {evaluation.full_name} "
        f"was refused: {named}; and "
        f"{_actor_phrase(actor)} is not among the named "
        f"bypassers. Ask a repository admin to add the "
        f"actor, or a team the actor belongs to, to every "
        f"matching rule's bypass list, or land the change "
        f"under the rules instead.")


@dataclass(frozen=True)
class BypassDecision:
    """One branch's bypass position for one actor,
    resolved once: the S-169 evaluation behind the
    answer, who is asking and the teams they are
    stated to belong to, and the answer in words."""
    full_name: str
    branch: str
    actor: str | None
    actor_teams: tuple
    evaluation: ProtectionEvaluation

    @property
    def bypass_actors(self) -> tuple:
        """The folded list of actors named to bypass
        this branch: the intersection S-169 folds over
        every matching rule. Empty means nobody may
        bypass — including when no rule matches."""
        effective = self.evaluation.effective
        if effective is None:
            return ()
        return tuple(effective.settings.bypass_actors)

    @property
    def protected(self) -> bool:
        """Whether any rule matches this branch at all."""
        return self.evaluation.effective is not None

    @property
    def matched(self) -> str | None:
        """The bypass entry naming this actor — a user
        entry, or the team entry their stated membership
        answers — or None when no entry names them."""
        if not self.protected:
            return None
        return matched_entry(
            self.bypass_actors, self.actor, self.actor_teams)

    @property
    def may_bypass(self) -> bool:
        """Whether this actor may bypass this branch's
        protection rules: a matching rule stands and an
        entry names them."""
        return self.matched is not None

    @property
    def reason(self) -> str:
        """The refusal sentence when refused, else ''."""
        if self.may_bypass or not self.protected:
            return ""
        return refusal_reason(self.evaluation, self.actor)

    @property
    def words(self) -> str:
        if not self.protected:
            return (
                f"Branch '{self.branch}' in {self.full_name} "
                f"is not protected: no protection rule "
                f"matches it, so no bypass is needed and "
                f"none is possible.")
        patterns = ", ".join(
            f"'{rule.pattern}'" for rule in self.evaluation.matching)
        if self.may_bypass:
            entry = self.matched
            if entry is not None and "/" in entry:
                how = (f"the actor belongs to the named team "
                       f"'{entry}'")
            else:
                how = f"the actor is named as '{entry}'"
            return (
                f"{_actor_phrase(self.actor)} may bypass the "
                f"protection rules matching branch "
                f"'{self.branch}' in {self.full_name} (rule "
                f"{patterns}): the folded bypass list "
                f"({', '.join(self.bypass_actors)}) names "
                f"them — {how}. Every bypass is "
                f"audit-logged and shown on the rule; there "
                f"is no silent door.")
        if self.bypass_actors:
            return (
                f"{_actor_phrase(self.actor)} may not bypass "
                f"the protection rules matching branch "
                f"'{self.branch}' in {self.full_name}: the "
                f"folded bypass list names only "
                f"{', '.join(self.bypass_actors)}, shown on "
                f"the rule, and the actor is not among them.")
        return (
            f"{_actor_phrase(self.actor)} may not bypass "
            f"the protection rules matching branch "
            f"'{self.branch}' in {self.full_name}: no "
            f"matching rule names any bypasser, so nobody "
            f"may bypass this branch — there is no silent "
            f"door.")


def decide_bypass(
        evaluation: ProtectionEvaluation,
        actor: str | None, *,
        actor_teams=()) -> BypassDecision:
    """The pure half of the check: one branch's bypass
    decision for one actor, from its already-resolved
    S-169 evaluation. No database is touched here, so
    the judgment is provable in isolation; the store
    below only has to gather the evaluation honestly.
    `actor` is the actor's user name (None or blank
    judges an anonymous actor); `actor_teams` states
    the teams the actor belongs to, each in full
    (`owner/team`) or bare (`team`) form."""
    if actor is not None and not isinstance(actor, str):
        raise BypassError(
            "bypass_check_invalid",
            "An actor is named by their user name, or is "
            "anonymous.")
    if isinstance(actor_teams, (str, bytes)) \
            or not isinstance(actor_teams, (list, tuple)):
        raise BypassError(
            "bypass_check_invalid",
            "An actor's teams are a list of team names.")
    teams = []
    for team in actor_teams:
        if not isinstance(team, str) or not team.strip():
            raise BypassError(
                "bypass_check_invalid",
                "An actor's team is a team name.")
        teams.append(team.strip())
    name = actor.strip() if isinstance(actor, str) else None
    return BypassDecision(
        full_name=evaluation.full_name,
        branch=evaluation.branch,
        actor=name or None,
        actor_teams=tuple(teams),
        evaluation=evaluation)


@dataclass(frozen=True)
class BypassUse:
    """One used bypass: the decision that allowed it
    and the audit row that witnesses it — the pair a
    gate acts on, so the bypass and its witness can
    never be separated by a caller that holds this."""
    decision: BypassDecision
    audit_seq: int
    gate: str

    @property
    def words(self) -> str:
        return (
            f"{self.decision.words} This bypass was used "
            f"at the {self.gate} gate and audit-logged as "
            f"{BYPASS_EVENT} (audit entry {self.audit_seq}).")


class BypassProtectionStore:
    """The store half of the bypass gate: gather one
    branch's evaluation through S-169's store — the
    one evaluation Part VIII consults — then delegate
    to `decide_bypass`; and, for a use, write the
    audit row that makes the bypass a witnessed act
    before answering yes."""

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

    # -- the check (a pure read) ------------------------------------

    def check_branch(self, viewer: User | None, owner: object,
                     repo: object, branch: object, *,
                     actor: str | None = None,
                     actor_teams=()
                     ) -> BypassDecision:
        """THE one check S-179's road consults: this
        branch's bypass decision for one actor. The
        actor is `actor` when stated, else the viewer
        themselves; a viewer of None with no actor
        judges an anonymous actor. The evaluation is
        read through S-169, so a stranger to a private
        repository gets the uniform `repo_not_found`
        before any bypass position is named. A pure
        read: checking writes nothing and audits
        nothing — only a *used* bypass is witnessed."""
        evaluation = self._rules.evaluate_branch(
            viewer, owner, repo, branch)
        who = actor
        if who is None and viewer is not None:
            who = viewer.username
        return decide_bypass(
            evaluation, who, actor_teams=actor_teams)

    # -- the use (the audited road) -----------------------------------

    def use_bypass(self, viewer: User | None, owner: object,
                   repo: object, branch: object, *,
                   actor: str | None = None,
                   actor_teams=(),
                   gate: str = "protection"
                   ) -> BypassUse:
        """The one road on which a bypass happens:
        re-check the decision, resolve the bypasser to
        a real account, append the `repo.protection.
        bypass` audit row naming the branch, the
        matching patterns and rule ids, the bypass
        entry and the gate — and only then answer yes.
        A refused use raises `bypass_not_allowed` and
        writes nothing; a store without an audit log
        refuses every use with `bypass_audit_required`,
        because a bypass that cannot be logged must
        not happen."""
        if not isinstance(gate, str) or not gate.strip():
            raise BypassError(
                "bypass_check_invalid",
                "A bypass use names the gate it bypasses.")
        decision = self.check_branch(
            viewer, owner, repo, branch, actor=actor,
            actor_teams=actor_teams)
        if not decision.may_bypass:
            raise BypassNotAllowedError(
                BYPASS_NOT_ALLOWED,
                decision.reason or decision.words)
        if self._audit is None:
            raise BypassError(
                BYPASS_AUDIT_REQUIRED,
                "A bypass is never silent: this store has "
                "no audit log, so the bypass of branch "
                f"'{decision.branch}' in {decision.full_name} "
                "cannot be witnessed and is refused.")
        account = None
        if viewer is not None and decision.actor is not None \
                and _norm(viewer.username) == _norm(decision.actor):
            account = viewer
        elif decision.actor is not None:
            account = self._accounts.get_by_username(decision.actor)
        if account is None:
            raise BypassNotAllowedError(
                BYPASS_NOT_ALLOWED,
                f"Bypass of the protection rules matching "
                f"branch '{decision.branch}' in "
                f"{decision.full_name} was refused: "
                f"{_actor_phrase(decision.actor)} is named "
                f"on the rule but is not an account on this "
                f"instance, and a bypass is witnessed under "
                f"the bypasser's own account, never "
                f"anonymously.")
        effective = decision.evaluation.effective
        seq = self._audit.append(
            actor_kind="user", actor_id=account.id,
            action=BYPASS_EVENT, target_kind="repo",
            target_id=decision.full_name, outcome="success",
            detail={
                "branch": decision.branch,
                "patterns": list(effective.patterns),
                "rule_ids": list(effective.rule_ids),
                "bypass_entry": decision.matched,
                "gate": gate.strip(),
                "actor": decision.actor,
            })
        return BypassUse(
            decision=decision, audit_seq=seq, gate=gate.strip())


def rule_bypass_words(rule: ProtectionRule) -> str:
    """One rule's bypass position, said in words for
    the rule's own surface: who the rule names as
    bypassers — or that it names nobody, and so
    closes the branch's bypass door when it matches
    (S-169's fold intersects over every matching
    rule)."""
    if rule.settings.bypass_actors:
        return (
            f"Rule for pattern '{rule.pattern}' in "
            f"{rule.full_name}: these actors may bypass: "
            f"{', '.join(rule.settings.bypass_actors)}. "
            f"Every bypass is audit-logged; the list is "
            f"shown here, never hidden.")
    return (
        f"Rule for pattern '{rule.pattern}' in "
        f"{rule.full_name}: this rule names no "
        f"bypassers — when it matches a branch, nobody "
        f"may bypass that branch. There is no silent "
        f"door.")


def render_bypass_decision(decision: BypassDecision) -> str:
    """One bypass decision in words — exactly the
    decision's own `words`, escaped through S-010,
    never a colour alone."""
    return (
        '<div class="protection-bypass">'
        f"<p>{escape_html_text(decision.words)}</p></div>")


def render_bypass_use(use: BypassUse) -> str:
    """One used bypass in words — the decision's words
    plus its audit witness, escaped through S-010."""
    return (
        '<div class="protection-bypass-use">'
        f"<p>{escape_html_text(use.words)}</p></div>")


def render_rule_bypass(rule: ProtectionRule) -> str:
    """One rule's bypass position in words — exactly
    `rule_bypass_words`, escaped through S-010."""
    return (
        '<div class="protection-rule-bypass">'
        f"<p>{escape_html_text(rule_bypass_words(rule))}</p></div>")
