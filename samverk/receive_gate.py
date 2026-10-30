"""Pre-receive gate point (S-089).

This is the one door every accepted-or-refused push passes
through, and the place later parts plug into:

- **Part VIII** protection rules plug in at the `protection`
  stage;
- **Part XV** secret scanning plugs in at the `secret_scan`
  stage;
- **S-068** quotas are the `quota` stage;
- **S-067** generic pre-receive hooks are the `hooks` stage.

**Gate order (documented here, binding on plug-ins):**

0. *Transport permission* — authentication and S-054
   read/write permission happen in the transport (S-077/S-086)
   before this gate is consulted at all; this gate never
   re-decides identity.
1. `protection` — ref policy (which refs may move, by whom).
   Cheapest and most specific: a protected ref refuses without
   any content ever being inspected.
2. `secret_scan` — content policy over the incoming commits.
3. `quota` — the measured resource decision (S-068's
   `check_receive`), consulted only when the caller knows the
   incoming size; a transport that cannot know it yet leaves
   this stage to the caller that can.
4. `hooks` — S-067's operator/subsystem pre-receive chain,
   last because it is arbitrary code under a fork+timeout
   discipline and the most expensive stage.

**Fail-closed, first refusal wins.** Every stage runs in the
order above and the chain stops at the first refusal; a
plug-in that raises (other than `GateVeto`, the explicit veto)
is an error and also refuses — a protection gate that fails
open is not a gate (S-067's law, applied to every stage).
With no plug-ins registered the gate allows: this slice builds
the gate *point*; the rules themselves land in their own parts.

**Transport wiring.** Both receive paths accept an optional
gate: SSH (`SshServeService`) consults it after its permission
gate and before any pack byte moves; smart HTTP
(`SmartHttpService.receive_pack`) consults it after `_resolve`
and before the pack program spawns. A transport passes the
ref updates it knows (today: none — pack contents are git's
business, S-078's law), so plug-ins that need ref detail
belong to callers that have it; the gate API carries the full
`RefUpdate` tuple for those callers and its own battery proves
the stages with real updates.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .hooks import HookRunner, RefUpdate

GATE_ORDER = ("protection", "secret_scan", "quota", "hooks")
STAGE_PROTECTION, STAGE_SECRET_SCAN, STAGE_QUOTA, STAGE_HOOKS = GATE_ORDER


class GateVeto(Exception):
    """A plug-in raises this to refuse a push with a reason."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class GateContext:
    repo: str                        # canonical owner/name
    owner: str
    repo_name: str
    actor: str | None = None
    transport: str | None = None     # http | ssh | local
    updates: tuple[RefUpdate, ...] = ()
    incoming_bytes: int | None = None
    payload: dict = field(default_factory=dict)


@dataclass(frozen=True)
class StageOutcome:
    stage: str
    status: str          # allowed | vetoed | error | skipped
    detail: str = ""
    by: str | None = None


@dataclass(frozen=True)
class GateResult:
    allowed: bool
    outcomes: tuple[StageOutcome, ...]
    refused_stage: str | None = None
    refused_by: str | None = None
    reason: str = ""


def _run_plugin(stage: str, name: str, plugin: Callable,
                context: GateContext) -> StageOutcome:
    """One plug-in under fail-closed discipline (no fork here —
    plug-ins are in-process policy callables; arbitrary operator
    code belongs in the S-067 hooks stage, which forks)."""
    try:
        result = plugin(context)
    except GateVeto as veto:
        return StageOutcome(stage, "vetoed", veto.reason, name)
    except Exception as exc:  # a plug-in's failure refuses the push
        return StageOutcome(
            stage, "error", f"{type(exc).__name__}: {exc}", name)
    if result is None or result is True:
        return StageOutcome(stage, "allowed", "", name)
    if result is False:
        return StageOutcome(stage, "vetoed", "refused without a stated reason", name)
    if isinstance(result, str):
        return StageOutcome(stage, "vetoed", result, name)
    return StageOutcome(
        stage, "error",
        f"plug-in returned an unrecognised value: {result!r}", name)


class ReceiveGate:
    """The pre-receive gate point: ordered plug-in stages over
    one push decision."""

    def __init__(self, *, quota_service=None,
                 hook_runner: HookRunner | None = None):
        self._plugins: dict[str, list[tuple[str, Callable]]] = {
            STAGE_PROTECTION: [], STAGE_SECRET_SCAN: []}
        self._quota = quota_service
        self._hooks = hook_runner

    # -- registration --------------------------------------------
    def _register(self, stage: str, name: str, plugin: Callable) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("a gate plug-in needs a name")
        if not callable(plugin):
            raise ValueError(f"gate plug-in {name!r} is not callable")
        if any(existing == name for existing, _ in self._plugins[stage]):
            raise ValueError(f"a {stage} plug-in named {name!r} already exists")
        self._plugins[stage].append((name, plugin))

    def register_protection(self, name: str, plugin: Callable) -> None:
        self._register(STAGE_PROTECTION, name, plugin)

    def register_secret_scanner(self, name: str, plugin: Callable) -> None:
        self._register(STAGE_SECRET_SCAN, name, plugin)

    def names(self, stage: str) -> tuple[str, ...]:
        if stage in self._plugins:
            return tuple(n for n, _ in self._plugins[stage])
        if stage == STAGE_HOOKS and self._hooks is not None:
            from .hooks import PRE_RECEIVE
            return self._hooks.names(PRE_RECEIVE)
        return ()

    # -- the decision ----------------------------------------------
    def check(self, *, owner: str, repo: str, actor: str | None = None,
              transport: str | None = None, updates=(),
              incoming_bytes: int | None = None,
              payload: dict | None = None) -> GateResult:
        context = GateContext(
            repo=f"{owner}/{repo}", owner=owner, repo_name=repo,
            actor=actor, transport=transport,
            updates=tuple(updates), incoming_bytes=incoming_bytes,
            payload=dict(payload or {}))
        outcomes: list[StageOutcome] = []

        def refused(outcome: StageOutcome) -> GateResult:
            reason = outcome.detail or f"refused at the {outcome.stage} stage"
            if outcome.status == "error":
                reason = (f"the {outcome.stage} check "
                          f"{outcome.by or ''} failed ({outcome.detail}); "
                          "push refused").strip()
            return GateResult(
                allowed=False, outcomes=tuple(outcomes),
                refused_stage=outcome.stage, refused_by=outcome.by,
                reason=reason)

        # 1+2: plug-in stages, in gate order.
        for stage in (STAGE_PROTECTION, STAGE_SECRET_SCAN):
            for name, plugin in self._plugins[stage]:
                outcome = _run_plugin(stage, name, plugin, context)
                outcomes.append(outcome)
                if outcome.status != "allowed":
                    return refused(outcome)
            if not self._plugins[stage]:
                outcomes.append(StageOutcome(stage, "skipped", "no plug-ins registered"))

        # 3: quota — only when a size is known (see docstring).
        if self._quota is None or incoming_bytes is None:
            outcomes.append(StageOutcome(
                STAGE_QUOTA, "skipped",
                "no quota service" if self._quota is None
                else "incoming size not known at this door"))
        else:
            decision = self._quota.check_receive(owner, repo, incoming_bytes)
            outcome = StageOutcome(
                STAGE_QUOTA, "allowed" if decision.allowed else "vetoed",
                decision.message, "quota")
            outcomes.append(outcome)
            if not decision.allowed:
                return refused(outcome)

        # 4: S-067 hooks.
        if self._hooks is None:
            outcomes.append(StageOutcome(STAGE_HOOKS, "skipped", "no hook runner"))
        else:
            result = self._hooks.run_pre_receive(
                context.repo, updates=context.updates, actor=actor,
                payload={"transport": transport, **context.payload})
            for hook_outcome in result.outcomes:
                outcomes.append(StageOutcome(
                    STAGE_HOOKS,
                    "allowed" if hook_outcome.status == "allowed"
                    else hook_outcome.status,
                    hook_outcome.detail, hook_outcome.name))
            if not result.allowed:
                return GateResult(
                    allowed=False, outcomes=tuple(outcomes),
                    refused_stage=STAGE_HOOKS,
                    refused_by=result.vetoed_by, reason=result.reason)
        return GateResult(allowed=True, outcomes=tuple(outcomes))
