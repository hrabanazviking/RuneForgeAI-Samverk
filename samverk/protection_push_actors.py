"""Restrict who can push (S-178).

Part VIII's push-actor gate: the S-169 rule field
`allowed_push_actors`, wired to its refusal point.
Before this slice the field was stored policy with no
teeth — a rule could name the only actors allowed to
push a branch directly and anyone else's direct push
still landed. Now there is one place that answers,
for a direct push, the question the receive-pack
gate asks:

- **The one check.** `PushActorProtectionStore` —
  and, for a caller that already holds an S-169
  evaluation, the pure `decide_push_actor` it
  delegates to — resolves a branch's protection
  position once through S-169's
  `ProtectionRuleStore.evaluate_branch` (the one
  evaluation Part VIII consults; matching, ordering,
  and the most-restrictive fold are never re-derived
  here) and refuses a *direct* push by an actor the
  folded rule does not name. No new policy storage
  is owned: no migration (schema stays 66, the field
  already lives in migration 65's `protection_rules`
  as the actor-name list S-169 stores), no new
  taxonomy event (119 events stand; rule changes
  already audit under the frozen
  `repo.protection.change`, and a refusal itself
  writes nothing and audits nothing, exactly as
  S-170's refused pushes do).
- **Named means named, as a user or through a team.**
  The folded `allowed_push_actors` is the
  intersection S-169 folds: a pusher must be allowed
  by every matching rule that restricts pushing, so
  the folded list is the whole position. An entry
  with no `/` is a user name and names that user; an
  entry of the form `owner/team` is a team and names
  everyone the caller states belongs to it (team
  membership itself is Part IX's machinery, S-187;
  until it lands, membership arrives stated by the
  caller — the store's `actor_teams`, the gate
  plug-in's `actor_teams` payload key — never
  guessed). A stated membership matches a team entry
  when it is the entry itself (`owner/team`) or the
  bare team name (`team`); a membership in another
  owner's team of the same name names nothing here.
  Names compare case-insensitively, as usernames do
  (the account store's canonical key is the lowered
  name); the words keep the spelling the rule and
  the pusher carry. An empty folded list restricts
  nobody: any actor may push, exactly as before.
- **An unnamed pusher is refused.** A push whose
  actor cannot be shown to be named — an actor the
  list does not name, a member of no named team, or
  an anonymous pusher with no name at all — is
  refused while the restriction binds. The gate
  never passes on no proof of who is pushing.
- **The refusal is said in words.** A refused push
  meets one human-readable reason naming the branch,
  the repository, the pattern(s) whose rule restricts
  pushing, the folded list of who may push, who was
  refused, and the remedies — be added to the rule
  (as a user or through a team) or open a pull
  request instead. The reason is the same sentence
  at every door: the store's error
  (`push_actor_required`, a `RepositoryError`
  carrying `.reason`, in the house shape), the gate
  plug-in's veto string, and the decision's own
  `words` all carry it, so S-183's rule insights can
  quote exactly what the pusher was told.
- **The receive-pack door is S-089's gate.**
  `receive_gate_plugin` adapts the check to the
  `protection` stage of the pre-receive gate point.
  The plug-in judges the ref updates the gate
  context carries: a branch ref whose folded rule
  restricts pushing vetoes the whole push when the
  context's actor is not named, first refusal wins.
  Non-branch refs (tags and the rest) are not this
  slice's business. A gate context carrying no
  updates judges nothing — S-089's standing law.
- **Where direct push is allowed at all.** The
  roadmap's own qualifier: this gate judges only
  who may push *directly*. A branch S-170's rule
  closes to direct pushes entirely is refused there
  whoever pushes; this gate does not re-derive that
  position, and the two gates compose at the gate
  point in stage order. Pull request merges are not
  direct pushes: the S-153 merge road lands inside
  the forge and never passes through receive-pack,
  and a caller that *is* the merge road says so with
  `via_pull_request=True` (the gate plug-in reads
  the same flag from the payload's `via_pull_request`
  key — a key the wire transports never set), and
  the check allows, said in words as a pull-request
  landing, never silently.
- **Nobody is exempt by role, and no list opens a
  side door yet.** The repo owner and admins are
  refused like anyone else when they are not named —
  the restriction names *who*, not *what rank*; the
  enforce-for-admins toggle (S-180) speaks to rules
  whose binding on admins is optional, and this
  slice's restriction is not one of them. A rule's
  bypass list (S-179) does not exempt a pusher from
  this restriction at this gate: S-179 wires bypass
  with its audit on its own road (samverk/
  protection_bypass.py), and a bypass name in a
  rule never opens this door silently.
- **Reads ride S-169's guards, and mutate nothing.**
  Every check reads the evaluation through S-169's
  store, so a stranger to a private repository gets
  the uniform `repo_not_found` before any branch's
  push position is named. The check is a pure read:
  no row changes, no audit row, no stored verdict of
  its own to drift from the rules it reads — change
  the list and the next check answers the new
  position, in both directions.
- **Said in words, never a colour alone.** A decision
  carries its position as `words` — allowed or
  refused, the branch, who pushed, and why — and the
  one renderer says exactly those words, escaped
  through S-010. No route is invented: the gate
  plug-in and the store are the surfaces, as S-170's
  seam landed route-free.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .protection_pull_request import branch_from_ref
from .protection_rules import (
    ProtectionEvaluation, ProtectionRuleStore)
from .receive_gate import GateVeto
from .repositories import RepositoryError, RepositoryStore

__all__ = [
    "PUSH_ACTOR_REQUIRED", "PushActorDecision",
    "PushActorProtectionStore", "PushActorRequiredError",
    "actor_is_named", "decide_push_actor",
    "render_push_actor_decision",
]

PUSH_ACTOR_REQUIRED = "push_actor_required"


class PushActorRequiredError(RepositoryError):
    """A push-actor refusal: a RepositoryError carrying
    `.reason` (`push_actor_required`), mirroring
    PullRequestRequiredError and ProtectionRuleError."""


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


def _norm(name: str) -> str:
    """One actor name in its comparison form: stripped
    and lowered, as the account store's canonical
    username key is lowered."""
    return name.strip().lower()


def matched_entry(allowed, actor, actor_teams=()) -> str | None:
    """The `allowed_push_actors` entry that names this
    pusher, or None when none does: a user entry (no
    `/`) names the actor of that name; a team entry
    (`owner/team`) names a pusher stated to belong to
    that team, the membership stated either in full
    (`owner/team`) or as the bare team name. Pure: the
    same lists and names always answer the same way."""
    if not actor:
        return None
    who = _norm(actor)
    teams = {_norm(team) for team in actor_teams or ()}
    bare_teams = {team for team in teams if "/" not in team}
    for entry in allowed or ():
        if "/" in entry:
            team_part = _norm(entry.partition("/")[2])
            if _norm(entry) in teams or team_part in bare_teams:
                return entry
        elif _norm(entry) == who:
            return entry
    return None


def actor_is_named(allowed, actor, actor_teams=()) -> bool:
    """Whether this pusher is named by the folded
    `allowed_push_actors` list: directly, as a user,
    or through a stated team membership. An empty
    list names nobody — callers that treat an empty
    list as *no restriction* say so themselves, as
    `decide_push_actor` does."""
    return matched_entry(allowed, actor, actor_teams) is not None


def _actor_phrase(actor: str | None) -> str:
    """The pusher, said in words: their name, or the
    anonymous position when no name stands."""
    if actor:
        return f"'{actor}'"
    return "an anonymous pusher"


def refusal_reason(evaluation: ProtectionEvaluation,
                   actor: str | None) -> str:
    """The one human-readable refusal sentence for a
    branch whose folded rule restricts direct pushes
    to named actors and this pusher is not among
    them: the branch, the repository, the pattern(s)
    carrying the restriction, who may push, who was
    refused, and the remedies. Every door quotes this
    sentence verbatim."""
    patterns = ", ".join(
        f"'{rule.pattern}'" for rule in evaluation.matching
        if rule.settings.allowed_push_actors)
    allowed = evaluation.effective.settings.allowed_push_actors \
        if evaluation.effective is not None else ()
    names = ", ".join(allowed)
    return (
        f"Direct push to branch '{evaluation.branch}' in "
        f"{evaluation.full_name} was refused: protection "
        f"rule {patterns} restricts direct pushes to "
        f"these named actors only: {names}; and "
        f"{_actor_phrase(actor)} is not among them. "
        f"Ask a repository admin to add the pusher, or "
        f"a team the pusher belongs to, to the rule, or "
        f"open a pull request to land changes on "
        f"'{evaluation.branch}' instead.")


@dataclass(frozen=True)
class PushActorDecision:
    """One branch's push-actor position for one
    pusher, resolved once: the S-169 evaluation behind
    the answer, who is pushing and the teams they are
    stated to belong to, and the answer said in
    words."""
    full_name: str
    branch: str
    actor: str | None
    actor_teams: tuple
    via_pull_request: bool
    evaluation: ProtectionEvaluation

    @property
    def allowed_actors(self) -> tuple:
        """The folded list of actors named to push this
        branch directly: the intersection S-169 folds
        over every matching rule that restricts
        pushing. Empty means no matching rule restricts
        pushing at all."""
        effective = self.evaluation.effective
        if effective is None:
            return ()
        return tuple(effective.settings.allowed_push_actors)

    @property
    def restricted(self) -> bool:
        """Whether any matching rule restricts who may
        push this branch directly."""
        return bool(self.allowed_actors)

    @property
    def matched(self) -> str | None:
        """The allowed entry naming this pusher — a
        user entry, or the team entry their stated
        membership answers — or None when no entry
        names them (always None when unrestricted)."""
        if not self.restricted:
            return None
        return matched_entry(
            self.allowed_actors, self.actor, self.actor_teams)

    @property
    def is_named(self) -> bool:
        """Whether this pusher may push under the
        restriction: by construction when no rule
        restricts pushing, else by being named."""
        return not self.restricted or self.matched is not None

    @property
    def allowed(self) -> bool:
        """Whether this push on this road may move this
        branch: a pull-request landing always may (it
        is not a direct push); a direct push may iff
        the pusher is named, or nobody is restricted."""
        return self.via_pull_request or self.is_named

    @property
    def reason(self) -> str:
        """The refusal sentence when refused, else ''."""
        if self.allowed:
            return ""
        return refusal_reason(self.evaluation, self.actor)

    @property
    def words(self) -> str:
        if self.via_pull_request:
            return (
                f"Push to branch '{self.branch}' in "
                f"{self.full_name} arrives by pull request: "
                f"the merge road is not a direct push, so "
                f"the push-actor restriction does not "
                f"refuse it.")
        if not self.restricted:
            return (
                f"Direct push to branch '{self.branch}' in "
                f"{self.full_name} is allowed: no protection "
                f"rule matching this branch restricts who "
                f"may push.")
        if self.is_named:
            entry = self.matched
            if entry is not None and "/" in entry:
                return (
                    f"Direct push to branch '{self.branch}' in "
                    f"{self.full_name} by {_actor_phrase(self.actor)} "
                    f"is allowed: protection rules restrict "
                    f"direct pushes to named actors "
                    f"({', '.join(self.allowed_actors)}), and "
                    f"the pusher belongs to the named team "
                    f"'{entry}'.")
            return (
                f"Direct push to branch '{self.branch}' in "
                f"{self.full_name} by {_actor_phrase(self.actor)} "
                f"is allowed: protection rules restrict "
                f"direct pushes to named actors "
                f"({', '.join(self.allowed_actors)}), and "
                f"{_actor_phrase(self.actor)} is named.")
        return self.reason


def decide_push_actor(
        evaluation: ProtectionEvaluation,
        actor: str | None, *,
        actor_teams=(),
        via_pull_request: bool = False) -> PushActorDecision:
    """The pure half of the check: one branch's
    push-actor decision for one pusher, from its
    already-resolved S-169 evaluation. No database is
    touched here, so the judgment is provable in
    isolation; the store below only has to gather the
    evaluation honestly. `actor` is the pusher's user
    name (None or blank judges an anonymous pusher);
    `actor_teams` states the teams the pusher belongs
    to, each in full (`owner/team`) or bare (`team`)
    form."""
    if not isinstance(via_pull_request, bool):
        raise PushActorRequiredError(
            "push_check_invalid",
            "Whether a push arrives by pull request is "
            "yes or no (a boolean).")
    if actor is not None and not isinstance(actor, str):
        raise PushActorRequiredError(
            "push_check_invalid",
            "A pusher is named by their user name, or "
            "is anonymous.")
    if isinstance(actor_teams, (str, bytes)) \
            or not isinstance(actor_teams, (list, tuple)):
        raise PushActorRequiredError(
            "push_check_invalid",
            "A pusher's teams are a list of team names.")
    teams = []
    for team in actor_teams:
        if not isinstance(team, str) or not team.strip():
            raise PushActorRequiredError(
                "push_check_invalid",
                "A pusher's team is a team name.")
        teams.append(team.strip())
    name = actor.strip() if isinstance(actor, str) else None
    return PushActorDecision(
        full_name=evaluation.full_name,
        branch=evaluation.branch,
        actor=name or None,
        actor_teams=tuple(teams),
        via_pull_request=via_pull_request,
        evaluation=evaluation)


class PushActorProtectionStore:
    """The store half of the check: gather one branch's
    evaluation through S-169's store — the one
    evaluation Part VIII consults — then delegate to
    `decide_push_actor`. Receive-pack callers hold
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
                     actor: str | None = None,
                     actor_teams=(),
                     via_pull_request: bool = False
                     ) -> PushActorDecision:
        """THE one check S-178's refusal point consults:
        this branch's push-actor decision for one
        pusher. The pusher is `actor` when stated, else
        the viewer themselves (the ordinary case: the
        person pushing is the person asking); a viewer
        of None with no actor judges an anonymous push.
        The evaluation is read through S-169, so a
        stranger to a private repository gets the
        uniform `repo_not_found` before any push
        position is named."""
        evaluation = self._rules.evaluate_branch(
            viewer, owner, repo, branch)
        pusher = actor
        if pusher is None and viewer is not None:
            pusher = viewer.username
        return decide_push_actor(
            evaluation, pusher, actor_teams=actor_teams,
            via_pull_request=via_pull_request)

    def enforce_branch(self, viewer: User | None, owner: object,
                       repo: object, branch: object, *,
                       actor: str | None = None,
                       actor_teams=(),
                       via_pull_request: bool = False
                       ) -> PushActorDecision:
        """The check, as a refusal: returns the allowed
        decision, or raises `push_actor_required`
        carrying the human-readable reason."""
        decision = self.check_branch(
            viewer, owner, repo, branch, actor=actor,
            actor_teams=actor_teams,
            via_pull_request=via_pull_request)
        if not decision.allowed:
            raise PushActorRequiredError(
                PUSH_ACTOR_REQUIRED, decision.reason)
        return decision

    # -- a whole push (the receive-pack shape) ----------------------

    def check_push(self, viewer: User | None, owner: object,
                   repo: object, updates, *,
                   actor: str | None = None,
                   actor_teams=(),
                   via_pull_request: bool = False
                   ) -> tuple:
        """Every branch decision in one push, in the
        push's own update order, all judged for the one
        pusher. Non-branch refs are skipped — they are
        not this slice's business. The push as a whole
        is allowed iff every returned decision is
        allowed."""
        decisions = []
        for update in updates or ():
            branch = branch_from_ref(_ref_of(update))
            if branch is None:
                continue
            decisions.append(self.check_branch(
                viewer, owner, repo, branch, actor=actor,
                actor_teams=actor_teams,
                via_pull_request=via_pull_request))
        return tuple(decisions)

    def enforce_push(self, viewer: User | None, owner: object,
                     repo: object, updates, *,
                     actor: str | None = None,
                     actor_teams=(),
                     via_pull_request: bool = False
                     ) -> tuple:
        """A whole push, as a refusal: the first refused
        branch in update order raises
        `push_actor_required` with its reason — first
        refusal wins, as at S-089's gate."""
        decisions = self.check_push(
            viewer, owner, repo, updates, actor=actor,
            actor_teams=actor_teams,
            via_pull_request=via_pull_request)
        for decision in decisions:
            if not decision.allowed:
                raise PushActorRequiredError(
                    PUSH_ACTOR_REQUIRED, decision.reason)
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
        viewer and pusher, so a private repository's
        position is never named to them (the gate then
        fails closed on S-169's `repo_not_found`, as
        every gate stage does on error). The pusher's
        stated teams ride the payload's `actor_teams`
        key and the merge road marks its landings with
        the payload key `via_pull_request`; the wire
        transports set neither, so a receive-pack push
        is always judged as the direct push by the
        transport's own actor that it is."""
        def plugin(context):
            actor = context.actor
            viewer = None
            if isinstance(actor, str) and actor:
                viewer = self._accounts.get_by_username(actor)
            teams = context.payload.get("actor_teams") or ()
            if isinstance(teams, str):
                teams = (teams,)
            via = bool(context.payload.get("via_pull_request"))
            decisions = self.check_push(
                viewer, context.owner, context.repo_name,
                context.updates, actor=actor,
                actor_teams=tuple(teams), via_pull_request=via)
            for decision in decisions:
                if not decision.allowed:
                    raise GateVeto(decision.reason)
            return None
        return plugin


def render_push_actor_decision(decision: PushActorDecision) -> str:
    """One push-actor decision in words — exactly the
    decision's own `words`, escaped through S-010,
    never a colour alone. The sentences S-183's rule
    insights will quote when they answer "why was
    this push refused?"."""
    return (
        '<div class="protection-push-actors">'
        f"<p>{escape_html_text(decision.words)}</p></div>")
