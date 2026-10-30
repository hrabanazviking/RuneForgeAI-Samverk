"""S-005 acceptance battery: constant-time comparison + throttling.

Acceptance (roadmap S-005): throttle trips in test after N failures,
releases after backoff.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk.throttle import LoginThrottle, constant_time_equal


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class ConstantTimeTests(unittest.TestCase):
    def test_equal_and_unequal(self):
        self.assertTrue(constant_time_equal("abc", "abc"))
        self.assertTrue(constant_time_equal(b"abc", b"abc"))
        self.assertTrue(constant_time_equal("abc", b"abc"))
        self.assertFalse(constant_time_equal("abc", "abd"))
        self.assertFalse(constant_time_equal("abc", "abcd"))
        self.assertFalse(constant_time_equal("", "x"))


class ThrottleTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.throttle = LoginThrottle(
            free_attempts=3, base_delay=2.0, max_delay=10.0,
            time_fn=self.clock)

    def test_free_attempts_have_no_delay(self):
        for _ in range(3):
            self.assertEqual(self.throttle.record_failure("alice"), 0.0)
            self.assertTrue(self.throttle.allowed("alice"))

    def test_throttle_trips_after_n_failures(self):
        for _ in range(3):
            self.throttle.record_failure("alice")
        delay = self.throttle.record_failure("alice")  # 4th failure trips
        self.assertEqual(delay, 2.0)
        self.assertFalse(self.throttle.allowed("alice"))
        self.assertEqual(self.throttle.retry_after("alice"), 2.0)

    def test_releases_after_backoff(self):
        for _ in range(4):
            self.throttle.record_failure("alice")
        self.assertFalse(self.throttle.allowed("alice"))
        self.clock.advance(1.0)
        self.assertFalse(self.throttle.allowed("alice"))
        self.assertEqual(self.throttle.retry_after("alice"), 1.0)
        self.clock.advance(1.0)
        self.assertTrue(self.throttle.allowed("alice"))
        self.assertEqual(self.throttle.retry_after("alice"), 0.0)

    def test_backoff_grows_and_caps(self):
        delays = [self.throttle.record_failure("alice") for _ in range(8)]
        # failures 1-3 free; then 2, 4, 8, capped at 10, 10
        self.assertEqual(delays, [0.0, 0.0, 0.0, 2.0, 4.0, 8.0, 10.0, 10.0])

    def test_success_clears_state(self):
        for _ in range(5):
            self.throttle.record_failure("alice")
        self.assertFalse(self.throttle.allowed("alice"))
        self.throttle.record_success("alice")
        self.assertTrue(self.throttle.allowed("alice"))
        # And the failure count restarts from the free allowance.
        self.assertEqual(self.throttle.record_failure("alice"), 0.0)

    def test_accounts_are_independent(self):
        for _ in range(5):
            self.throttle.record_failure("alice")
        self.assertFalse(self.throttle.allowed("alice"))
        self.assertTrue(self.throttle.allowed("bob"))
        self.assertEqual(self.throttle.retry_after("bob"), 0.0)


if __name__ == "__main__":
    unittest.main()
