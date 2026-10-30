"""S-011 acceptance battery: rate limiting.

Acceptance (roadmap S-011): per-IP and per-account token buckets
with `Retry-After` — *limiter behaviour under burst test.*

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk.rate_limit import RateLimiter, TokenBucket


class FakeClock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class TokenBucketTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.bucket = TokenBucket(capacity=10, refill_per_second=1.0, time_fn=self.clock)

    def test_burst_up_to_capacity_then_refused(self):
        """The acceptance in its literal form: a burst drains the
        bucket exactly to its capacity, and the next request is the
        first refusal."""
        results = [self.bucket.try_acquire() for _ in range(12)]
        self.assertEqual(results, [True] * 10 + [False, False])

    def test_retry_after_is_truthful(self):
        for _ in range(10):
            self.bucket.try_acquire()
        # Empty bucket, 1 token/second: one token is 1s away.
        self.assertAlmostEqual(self.bucket.retry_after(), 1.0)
        self.clock.advance(0.5)
        self.assertAlmostEqual(self.bucket.retry_after(), 0.5)
        self.assertFalse(self.bucket.try_acquire())
        self.clock.advance(0.5)
        self.assertTrue(self.bucket.try_acquire())

    def test_refill_never_exceeds_capacity(self):
        self.clock.advance(3600)
        self.assertEqual(self.bucket.available(), 10.0)

    def test_fractional_costs_and_unservable_costs(self):
        self.assertTrue(self.bucket.try_acquire(cost=7.5))
        self.assertTrue(self.bucket.try_acquire(cost=2.5))
        self.assertFalse(self.bucket.try_acquire(cost=0.5))
        with self.assertRaises(ValueError):
            self.bucket.try_acquire(cost=11)
        with self.assertRaises(ValueError):
            self.bucket.try_acquire(cost=0)

    def test_concurrent_burst_grants_exactly_capacity(self):
        """Under a frozen clock, 20 threads racing 10 attempts each
        must be granted exactly the capacity between them — no token
        is spent twice, none is invented."""
        clock = FakeClock()
        bucket = TokenBucket(capacity=50, refill_per_second=1.0, time_fn=clock)
        granted: list[int] = []
        lock = threading.Lock()

        def hammer():
            local = sum(1 for _ in range(10) if bucket.try_acquire())
            with lock:
                granted.append(local)

        threads = [threading.Thread(target=hammer) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(granted), 50)


class RateLimiterTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.limiter = RateLimiter(
            ip_capacity=5, ip_refill_per_second=1.0,
            account_capacity=3, account_refill_per_second=0.5,
            time_fn=self.clock,
        )

    def test_ip_burst_is_limited_with_retry_after(self):
        for _ in range(5):
            self.assertTrue(self.limiter.acquire("203.0.113.7").allowed)
        decision = self.limiter.acquire("203.0.113.7")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.limited_by, "ip")
        self.assertAlmostEqual(decision.retry_after_seconds, 1.0)
        self.assertEqual(decision.retry_after_header(), "1")

    def test_ips_are_independent(self):
        for _ in range(5):
            self.limiter.acquire("203.0.113.7")
        self.assertFalse(self.limiter.acquire("203.0.113.7").allowed)
        self.assertTrue(self.limiter.acquire("198.51.100.2").allowed)

    def test_account_bucket_limits_across_ips(self):
        # An account hopping IPs still meets its own bucket (3).
        for i in range(3):
            self.assertTrue(self.limiter.acquire(f"192.0.2.{i}", account="mallory").allowed)
        decision = self.limiter.acquire("192.0.2.99", account="mallory")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.limited_by, "account")
        # Account refill is 0.5/s, so one token is 2s away.
        self.assertAlmostEqual(decision.retry_after_seconds, 2.0)
        self.assertEqual(decision.retry_after_header(), "2")

    def test_account_refusal_does_not_drain_the_ip_bucket(self):
        # Drain mallory's account bucket from another IP.
        for i in range(3):
            self.limiter.acquire(f"192.0.2.{i}", account="mallory")
        # Refused by account from a fresh IP; that IP's bucket must
        # still hold its full capacity for someone else.
        self.assertFalse(self.limiter.acquire("198.51.100.9", account="mallory").allowed)
        for _ in range(5):
            self.assertTrue(self.limiter.acquire("198.51.100.9").allowed)

    def test_allowed_decision_has_no_retry_after(self):
        decision = self.limiter.acquire("203.0.113.7", account="volmarr")
        self.assertTrue(decision.allowed)
        self.assertIsNone(decision.limited_by)
        self.assertIsNone(decision.retry_after_header())

    def test_recovery_after_the_promised_wait(self):
        for _ in range(5):
            self.limiter.acquire("203.0.113.7")
        self.assertFalse(self.limiter.acquire("203.0.113.7").allowed)
        self.clock.advance(1.0)
        self.assertTrue(self.limiter.acquire("203.0.113.7").allowed)


if __name__ == "__main__":
    unittest.main()
