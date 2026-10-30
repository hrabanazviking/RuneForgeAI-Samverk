"""Transfer limits (S-091).

Every git transfer is bounded, per transport, and every bound
**explains itself** when it refuses:

- **Pack size** — the largest pack (bytes) a transfer may
  carry. Enforced on the request body the HTTP door can
  measure before git spawns, and available as a decision
  (`check_pack_size`) to any caller that knows a size.
- **Wall clock** — the longest a whole transfer may run.
  On the HTTP door this becomes the pack program's timeout
  (S-014's mandatory timeout, valued from here); `WallClock`
  gives any other caller the same budget as a checkable clock.
- **Idle timeout** — the longest a transfer may go without
  moving a byte. `IdleWatch` is the checkable form: `touch()`
  on progress, `check()` raises when the silence is too long.

Limits are **per transport** (`http` / `ssh`): an operator
tightens one door without touching the other, by constructing
the policy with overrides. A limit that was never set is
unlimited in size only — wall-clock and idle budgets always
exist, because an unbounded transfer is a hung server waiting
to happen (defaults: 600 s wall, 60 s idle, both named here).

A refusal is a decision object first (`LimitDecision`, so a
surface can show the state) and an exception second
(`TransferLimitError`, carrying the same plain message naming
the transport, the measured size/time, the limit, and the
remedy) — the S-068 quota shape, applied to transfers.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, replace

TRANSPORTS = ("http", "ssh")
DEFAULT_WALL_CLOCK_SECONDS = 600.0
DEFAULT_IDLE_TIMEOUT_SECONDS = 60.0


class TransferLimitError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class TransportLimits:
    max_pack_bytes: int | None = None       # None = no size cap
    wall_clock_seconds: float = DEFAULT_WALL_CLOCK_SECONDS
    idle_timeout_seconds: float = DEFAULT_IDLE_TIMEOUT_SECONDS

    def validated(self) -> "TransportLimits":
        if self.max_pack_bytes is not None:
            if (isinstance(self.max_pack_bytes, bool)
                    or not isinstance(self.max_pack_bytes, int)
                    or self.max_pack_bytes < 0):
                raise TransferLimitError(
                    "limit_invalid",
                    "A pack size limit is a whole number of bytes, "
                    "zero or more (or unset for no cap).")
        for value, label in (
                (self.wall_clock_seconds, "wall clock"),
                (self.idle_timeout_seconds, "idle timeout")):
            if (isinstance(value, bool)
                    or not isinstance(value, (int, float)) or value <= 0):
                raise TransferLimitError(
                    "limit_invalid",
                    f"A {label} limit must be a positive number of seconds.")
        return self


@dataclass(frozen=True)
class LimitDecision:
    allowed: bool
    transport: str
    kind: str                # pack_size
    measured: int
    limit: int | None
    message: str


class TransferLimits:
    """The per-transport limits policy."""

    def __init__(self, *, http: TransportLimits | None = None,
                 ssh: TransportLimits | None = None):
        base = TransportLimits()
        self._by_transport = {
            "http": (http or base).validated(),
            "ssh": (ssh or base).validated(),
        }

    def for_transport(self, transport: str) -> TransportLimits:
        if transport not in self._by_transport:
            raise TransferLimitError(
                "transport_invalid", f"Unknown transport: {transport!r}")
        return self._by_transport[transport]

    def with_limits(self, transport: str, **changes) -> "TransferLimits":
        """A new policy with one transport's limits adjusted —
        the operator's configuration move; the old policy (and
        the other transport) is untouched."""
        current = self.for_transport(transport)
        updated = replace(current, **changes).validated()
        clone = TransferLimits(
            http=self._by_transport["http"], ssh=self._by_transport["ssh"])
        clone._by_transport[transport] = updated
        return clone

    # -- pack size ---------------------------------------------------
    def check_pack_size(self, transport: str,
                        size_bytes: int) -> LimitDecision:
        limits = self.for_transport(transport)
        if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) \
                or size_bytes < 0:
            raise TransferLimitError(
                "size_invalid", "A pack size is a whole number of bytes.")
        cap = limits.max_pack_bytes
        if cap is None or size_bytes <= cap:
            return LimitDecision(
                allowed=True, transport=transport, kind="pack_size",
                measured=size_bytes, limit=cap,
                message=(f"{transport} transfer of {size_bytes} bytes "
                         f"is within its pack limit."
                         if cap is not None else
                         f"{transport} transfers have no pack size limit."))
        return LimitDecision(
            allowed=False, transport=transport, kind="pack_size",
            measured=size_bytes, limit=cap,
            message=(
                f"This {transport} transfer is too large: the pack is "
                f"{size_bytes} bytes and the {transport} limit is "
                f"{cap} bytes. Split the push into smaller pieces, "
                f"remove large objects from the history being sent, "
                f"or ask a site admin to raise the {transport} "
                f"pack limit."))

    def enforce_pack_size(self, transport: str, size_bytes: int
                          ) -> LimitDecision:
        decision = self.check_pack_size(transport, size_bytes)
        if not decision.allowed:
            raise TransferLimitError("pack_too_large", decision.message)
        return decision

    def wall_clock_timeout(self, transport: str) -> float:
        """The timeout a transport hands its pack program."""
        return float(self.for_transport(transport).wall_clock_seconds)


class WallClock:
    """A checkable wall-clock budget for one transfer."""

    def __init__(self, limits: TransportLimits, transport: str,
                 time_fn: Callable[[], float] = time.monotonic):
        self._budget = float(limits.wall_clock_seconds)
        self._transport = transport
        self._now = time_fn
        self._started = time_fn()

    def elapsed(self) -> float:
        return self._now() - self._started

    def remaining(self) -> float:
        return max(0.0, self._budget - self.elapsed())

    def check(self) -> float:
        elapsed = self.elapsed()
        if elapsed > self._budget:
            raise TransferLimitError(
                "wall_clock_exceeded",
                f"This {self._transport} transfer ran for "
                f"{elapsed:.1f} seconds and the wall-clock limit is "
                f"{self._budget:g} seconds, so it was stopped. Retry "
                f"with a smaller transfer, or ask a site admin to "
                f"raise the {self._transport} wall-clock limit.")
        return elapsed


class IdleWatch:
    """A checkable idle budget: progress calls `touch()`."""

    def __init__(self, limits: TransportLimits, transport: str,
                 time_fn: Callable[[], float] = time.monotonic):
        self._budget = float(limits.idle_timeout_seconds)
        self._transport = transport
        self._now = time_fn
        self._last = time_fn()

    def touch(self) -> None:
        self._last = self._now()

    def idle_for(self) -> float:
        return self._now() - self._last

    def check(self) -> float:
        idle = self.idle_for()
        if idle > self._budget:
            raise TransferLimitError(
                "idle_timeout",
                f"This {self._transport} transfer moved no data for "
                f"{idle:.1f} seconds and the idle limit is "
                f"{self._budget:g} seconds, so it was stopped. "
                f"Check the connection and retry, or ask a site "
                f"admin to raise the {self._transport} idle limit.")
        return idle
