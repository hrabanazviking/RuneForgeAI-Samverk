"""Rate limiting (S-011) — per-IP and per-account token buckets.

A token bucket is the honest shape for a rate limit: a burst up to
the bucket's capacity is allowed at once (real users are bursty —
a page load is twenty requests arriving together), then requests
flow at the refill rate, and a refusal carries a truthful
`Retry-After` — seconds until at least the refused request could
have been served — instead of a bare "slow down".

Two dimensions, one decision (`RateLimiter`):

- **per source IP** — the brake an unauthenticated flood hits
  (study 07 §3.5 names this bucket as shared with the login path);
- **per account** — the brake a single signed-in account hits, so
  one abusive account cannot hide behind many IPs, and one busy
  shared IP (a household, a NAT) does not consume an account's own
  allowance when the account bucket is the one that refuses: a
  request is charged to **both buckets or neither**. A request the
  account bucket refuses never drains the IP bucket, and vice
  versa — partial charging would let one limiter starve the other.

This is the request-rate brake. It is deliberately distinct from
S-005's `LoginThrottle`, which is a per-account *failure* backoff
(delays after wrong passwords); both guard the login door, at
different layers. Buckets are in-memory and thread-safe, like the
throttle: limits are speed bumps measured in seconds, and losing
them on restart loses nothing that matters. A later slice that
needs cross-process limits graduates this interface to SQLite
unchanged.

State hygiene: keyed buckets that have sat fully refilled for an
hour are indistinguishable from fresh ones and are pruned lazily on
access, so a flood of one-shot keys cannot grow the dicts forever.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

_PRUNE_AFTER_SECONDS = 3600.0


@dataclass
class _BucketState:
    tokens: float
    updated_at: float


def _refill(state: _BucketState, now: float, capacity: float, rate: float) -> None:
    elapsed = max(0.0, now - state.updated_at)
    state.tokens = min(capacity, state.tokens + elapsed * rate)
    state.updated_at = now


def _retry_after(state: _BucketState, capacity: float, rate: float, cost: float) -> float:
    """Seconds until *cost* tokens will be available (0 = now)."""
    if state.tokens >= cost:
        return 0.0
    if rate <= 0:
        return math.inf
    return (cost - state.tokens) / rate


def _check_cost(cost: float, capacity: float) -> None:
    if cost <= 0 or cost > capacity:
        raise ValueError(
            f"cost {cost} can never be served by a bucket of capacity {capacity}"
        )


class TokenBucket:
    """One thread-safe token bucket."""

    def __init__(
        self,
        capacity: float,
        refill_per_second: float,
        time_fn: Callable[[], float] = time.monotonic,
    ):
        if capacity <= 0 or refill_per_second <= 0:
            raise ValueError("capacity and refill rate must be positive")
        self.capacity = float(capacity)
        self.rate = float(refill_per_second)
        self._now = time_fn
        self._lock = threading.Lock()
        self._state = _BucketState(tokens=float(capacity), updated_at=self._now())

    def try_acquire(self, cost: float = 1.0) -> bool:
        _check_cost(cost, self.capacity)
        with self._lock:
            _refill(self._state, self._now(), self.capacity, self.rate)
            if self._state.tokens >= cost:
                self._state.tokens -= cost
                return True
            return False

    def retry_after(self, cost: float = 1.0) -> float:
        _check_cost(cost, self.capacity)
        with self._lock:
            _refill(self._state, self._now(), self.capacity, self.rate)
            return _retry_after(self._state, self.capacity, self.rate, cost)

    def available(self) -> float:
        with self._lock:
            _refill(self._state, self._now(), self.capacity, self.rate)
            return self._state.tokens


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    retry_after_seconds: float  # 0 when allowed
    limited_by: str | None  # "ip", "account", or None when allowed

    def retry_after_header(self) -> str | None:
        """The `Retry-After` header value for a refusal (whole
        seconds, rounded up so the promise is never early), or None
        when the request was allowed."""
        if self.allowed:
            return None
        if math.isinf(self.retry_after_seconds):
            return None
        return str(max(1, math.ceil(self.retry_after_seconds)))


class RateLimiter:
    """Per-IP + per-account buckets consulted as one decision."""

    def __init__(
        self,
        ip_capacity: float = 120.0,
        ip_refill_per_second: float = 2.0,
        account_capacity: float = 60.0,
        account_refill_per_second: float = 1.0,
        time_fn: Callable[[], float] = time.monotonic,
    ):
        for capacity, rate in (
            (ip_capacity, ip_refill_per_second),
            (account_capacity, account_refill_per_second),
        ):
            if capacity <= 0 or rate <= 0:
                raise ValueError("capacities and refill rates must be positive")
        self._ip_capacity = float(ip_capacity)
        self._ip_rate = float(ip_refill_per_second)
        self._account_capacity = float(account_capacity)
        self._account_rate = float(account_refill_per_second)
        self._now = time_fn
        self._lock = threading.Lock()
        self._ip_buckets: dict[str, _BucketState] = {}
        self._account_buckets: dict[str, _BucketState] = {}

    def _bucket(
        self, table: dict[str, _BucketState], key: str, capacity: float, rate: float, now: float
    ) -> _BucketState:
        state = table.get(key)
        if state is None:
            state = _BucketState(tokens=capacity, updated_at=now)
            table[key] = state
        else:
            _refill(state, now, capacity, rate)
        return state

    def _prune(self, table: dict[str, _BucketState], capacity: float, now: float) -> None:
        stale = [
            key
            for key, state in table.items()
            if state.tokens >= capacity and now - state.updated_at > _PRUNE_AFTER_SECONDS
        ]
        for key in stale:
            del table[key]

    def acquire(self, ip: str, account: str | None = None, cost: float = 1.0) -> RateDecision:
        """Charge *cost* against the caller's IP bucket and (when
        signed in) account bucket — both, or neither."""
        _check_cost(cost, min(self._ip_capacity, self._account_capacity)
                    if account is not None else self._ip_capacity)
        now = self._now()
        with self._lock:
            self._prune(self._ip_buckets, self._ip_capacity, now)
            if account is not None:
                self._prune(self._account_buckets, self._account_capacity, now)
            ip_state = self._bucket(self._ip_buckets, ip, self._ip_capacity, self._ip_rate, now)
            ip_wait = _retry_after(ip_state, self._ip_capacity, self._ip_rate, cost)
            if ip_wait > 0:
                return RateDecision(False, ip_wait, "ip")
            account_state = None
            if account is not None:
                account_state = self._bucket(
                    self._account_buckets, account,
                    self._account_capacity, self._account_rate, now,
                )
                account_wait = _retry_after(
                    account_state, self._account_capacity, self._account_rate, cost
                )
                if account_wait > 0:
                    return RateDecision(False, account_wait, "account")
            ip_state.tokens -= cost
            if account_state is not None:
                account_state.tokens -= cost
            return RateDecision(True, 0.0, None)
