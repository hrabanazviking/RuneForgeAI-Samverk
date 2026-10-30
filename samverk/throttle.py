"""Constant-time comparison + login throttling primitives (S-005).

Two small primitives every later auth slice uses:

1. `constant_time_equal` — the one comparison seam for secret-bearing
   values (password digests, token hashes, signatures). Wraps
   `hmac.compare_digest`; no caller compares secrets with `==`
   (threat model T-19).

2. `LoginThrottle` — per-account login backoff (study 07 §3.5):
   a few free failures, then an exponentially growing *delay* before
   the next attempt is allowed, capped. It delays; it never locks —
   a lockout an attacker can trigger against the owner is a
   denial-of-service feature, not a security feature (T-01/T-10/T-18).
   Per-source (IP) limiting is S-011's token buckets, a separate brake.

In-memory and thread-safe: a throttle is a speed bump measured in
seconds, not a record; losing it on restart loses nothing that
matters. (If that ever changes, it graduates to SQLite with the same
interface.)
"""

from __future__ import annotations

import hmac
import threading
import time
from collections.abc import Callable


def constant_time_equal(a: str | bytes, b: str | bytes) -> bool:
    """Compare two secret-bearing values in constant time."""
    if isinstance(a, str):
        a = a.encode("utf-8")
    if isinstance(b, str):
        b = b.encode("utf-8")
    return hmac.compare_digest(a, b)


class LoginThrottle:
    def __init__(
        self,
        free_attempts: int = 3,
        base_delay: float = 2.0,
        max_delay: float = 300.0,
        time_fn: Callable[[], float] = time.monotonic,
    ):
        self._free = free_attempts
        self._base = base_delay
        self._max = max_delay
        self._now = time_fn
        self._lock = threading.Lock()
        # account -> (consecutive_failures, blocked_until)
        self._state: dict[str, tuple[int, float]] = {}

    def _delay_for(self, failures: int) -> float:
        if failures <= self._free:
            return 0.0
        return min(self._base * (2 ** (failures - self._free - 1)), self._max)

    def record_failure(self, account: str) -> float:
        """Record a failed login; return the delay now in force."""
        with self._lock:
            failures, _ = self._state.get(account, (0, 0.0))
            failures += 1
            delay = self._delay_for(failures)
            self._state[account] = (failures, self._now() + delay)
            return delay

    def record_success(self, account: str) -> None:
        """A successful login clears the account's failure state."""
        with self._lock:
            self._state.pop(account, None)

    def retry_after(self, account: str) -> float:
        """Seconds the account must still wait (0 = attempt allowed)."""
        with self._lock:
            entry = self._state.get(account)
            if entry is None:
                return 0.0
            return max(0.0, entry[1] - self._now())

    def allowed(self, account: str) -> bool:
        return self.retry_after(account) == 0.0
