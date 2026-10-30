"""Server-side hooks seam (S-067).

Every push passes two gates Samverk itself controls, and later
parts hang their work on these gates — branch protection and
checks at S-089, secret scanning in Part XV:

- **pre-receive** runs *before* any ref moves. A hook may veto
  the push, and the veto is final: the runner stops at the
  first refusal and the caller (the receive path) must not
  move anything. Pre-receive fails **closed**: a hook that
  raises, misbehaves, or overruns its time budget refuses the
  push, because a protection gate that fails open is not a
  gate.
- **post-receive** runs *after* the refs have moved. It can
  observe and react (notifications, cache invalidation at
  S-072) but it can never veto — the runner records every
  outcome, including failures and timeouts, and moves on.

**Timeout and kill discipline.** A hook is arbitrary operator
/ subsystem code, so no hook ever runs in the server's own
process: each invocation runs in a forked child, the parent
waits only up to the runner's timeout, and an overrunning
child is terminated, then killed if it ignores termination,
then reaped. A hung hook therefore costs one refused push
(pre) or one recorded failure (post) — never a hung server.

The hook contract is a plain callable over a `HookContext`:

- return `None` or `True` — allow / done;
- return `False` or a string — veto, the string is the reason
  shown to the pusher (pre-receive only);
- raise `HookVeto(reason)` — veto with a reason;
- raise anything else — an error (fails closed pre-receive).

Handlers register by name, in order, per phase; names are
unique per phase so an outcome always names its hook.
"""

from __future__ import annotations

import multiprocessing
import time
from collections.abc import Callable
from dataclasses import dataclass, field

PRE_RECEIVE = "pre-receive"
POST_RECEIVE = "post-receive"
_PHASES = (PRE_RECEIVE, POST_RECEIVE)

DEFAULT_TIMEOUT_SECONDS = 10.0
_TERMINATE_GRACE_SECONDS = 0.5


class HookError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


class HookVeto(Exception):
    """A hook raises this to veto a push with a reason."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class RefUpdate:
    ref: str
    old_oid: str
    new_oid: str


@dataclass(frozen=True)
class HookContext:
    phase: str                      # PRE_RECEIVE | POST_RECEIVE
    repo: str                       # canonical owner/name
    actor: str | None = None        # who is pushing, if known
    updates: tuple[RefUpdate, ...] = ()
    payload: dict = field(default_factory=dict)


@dataclass(frozen=True)
class HookOutcome:
    name: str
    status: str          # allowed | vetoed | error | timeout | completed
    detail: str = ""
    duration_seconds: float = 0.0


@dataclass(frozen=True)
class PreReceiveResult:
    allowed: bool
    outcomes: tuple[HookOutcome, ...]
    vetoed_by: str | None = None
    reason: str = ""


def _child_entry(send_conn, handler: Callable, context: HookContext) -> None:
    """Run one hook in the child and report (status, detail)."""
    try:
        result = handler(context)
    except HookVeto as veto:
        send_conn.send(("vetoed", veto.reason))
    except Exception as exc:  # a hook's failure is data, not a crash
        send_conn.send(("error", f"{type(exc).__name__}: {exc}"))
    else:
        if result is None or result is True:
            send_conn.send(("allowed", ""))
        elif result is False:
            send_conn.send(("vetoed", "vetoed without a stated reason"))
        elif isinstance(result, str):
            send_conn.send(("vetoed", result))
        else:
            send_conn.send(("error",
                            f"hook returned an unrecognised value: {result!r}"))
    finally:
        send_conn.close()


class HookRunner:
    def __init__(self, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS):
        if not (isinstance(timeout_seconds, (int, float))
                and timeout_seconds > 0):
            raise HookError("timeout_invalid",
                            "The hook timeout must be a positive number.")
        self._timeout = float(timeout_seconds)
        self._handlers: dict[str, list[tuple[str, Callable]]] = {
            phase: [] for phase in _PHASES}

    # -- registration --------------------------------------------
    def register(self, phase: str, name: str, handler: Callable) -> None:
        if phase not in _PHASES:
            raise HookError("phase_invalid", f"Unknown hook phase: {phase!r}")
        if not isinstance(name, str) or not name.strip():
            raise HookError("hook_name_invalid", "A hook needs a name.")
        if not callable(handler):
            raise HookError("hook_not_callable",
                            f"Hook {name!r} is not callable.")
        if any(existing == name for existing, _ in self._handlers[phase]):
            raise HookError("hook_name_taken",
                            f"A {phase} hook named {name!r} already exists.")
        self._handlers[phase].append((name, handler))

    def register_pre_receive(self, name: str, handler: Callable) -> None:
        self.register(PRE_RECEIVE, name, handler)

    def register_post_receive(self, name: str, handler: Callable) -> None:
        self.register(POST_RECEIVE, name, handler)

    def names(self, phase: str) -> tuple[str, ...]:
        if phase not in _PHASES:
            raise HookError("phase_invalid", f"Unknown hook phase: {phase!r}")
        return tuple(name for name, _ in self._handlers[phase])

    # -- execution -------------------------------------------------
    def _run_one(self, name: str, handler: Callable,
                 context: HookContext) -> HookOutcome:
        """Run one hook in a forked child under the time budget.

        The child is terminated, then killed, then reaped when
        it overruns — this method never waits longer than the
        timeout plus the terminate grace.
        """
        mp = multiprocessing.get_context("fork")
        recv_conn, send_conn = mp.Pipe(duplex=False)
        proc = mp.Process(target=_child_entry,
                          args=(send_conn, handler, context))
        started = time.monotonic()
        proc.start()
        send_conn.close()
        try:
            if recv_conn.poll(self._timeout):
                status, detail = recv_conn.recv()
            else:
                status, detail = "timeout", (
                    f"hook did not finish within {self._timeout:g} seconds "
                    "and was killed")
            proc.join(timeout=_TERMINATE_GRACE_SECONDS)
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=_TERMINATE_GRACE_SECONDS)
            if proc.is_alive():
                proc.kill()
                proc.join()
        finally:
            recv_conn.close()
            if proc.is_alive():  # last resort: never leave a child behind
                proc.kill()
                proc.join()
        return HookOutcome(name=name, status=status, detail=str(detail),
                           duration_seconds=time.monotonic() - started)

    def run_pre_receive(self, repo: str, updates=(), actor: str | None = None,
                        payload: dict | None = None) -> PreReceiveResult:
        """Run the pre-receive chain; stop at the first refusal.

        Fail-closed by construction: veto, error, and timeout
        all refuse the push.
        """
        context = HookContext(
            phase=PRE_RECEIVE, repo=repo, actor=actor,
            updates=tuple(updates), payload=dict(payload or {}))
        outcomes: list[HookOutcome] = []
        for name, handler in self._handlers[PRE_RECEIVE]:
            outcome = self._run_one(name, handler, context)
            outcomes.append(outcome)
            if outcome.status != "allowed":
                reason = outcome.detail or f"refused by hook {name!r}"
                if outcome.status == "timeout":
                    reason = f"hook {name!r} timed out; push refused"
                elif outcome.status == "error":
                    reason = f"hook {name!r} failed ({outcome.detail}); push refused"
                return PreReceiveResult(
                    allowed=False, outcomes=tuple(outcomes),
                    vetoed_by=name, reason=reason)
        return PreReceiveResult(allowed=True, outcomes=tuple(outcomes))

    def run_post_receive(self, repo: str, updates=(), actor: str | None = None,
                         payload: dict | None = None) -> tuple[HookOutcome, ...]:
        """Run every post-receive hook; record, never veto.

        An "allowed" child outcome is reported as "completed":
        after the fact there is nothing left to allow.
        """
        context = HookContext(
            phase=POST_RECEIVE, repo=repo, actor=actor,
            updates=tuple(updates), payload=dict(payload or {}))
        outcomes: list[HookOutcome] = []
        for name, handler in self._handlers[POST_RECEIVE]:
            outcome = self._run_one(name, handler, context)
            if outcome.status == "allowed":
                outcome = HookOutcome(
                    name=outcome.name, status="completed",
                    detail=outcome.detail,
                    duration_seconds=outcome.duration_seconds)
            outcomes.append(outcome)
        return tuple(outcomes)
