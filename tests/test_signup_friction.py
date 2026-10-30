"""S-021 acceptance battery: signup abuse friction.

Acceptance (roadmap S-021): registration throttles and
disposable-domain policy hooks, no third-party captcha —
*a scripted signup flood is throttled.*

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk.signup_friction import (
    BlocklistDomains,
    SignupGuard,
    domain_of_email,
)


class FakeClock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FloodTests(unittest.TestCase):
    def test_scripted_flood_from_one_ip_is_throttled(self):
        """The acceptance in its literal form: a script inventing
        a fresh address per attempt meets the IP bucket."""
        clock = FakeClock()
        guard = SignupGuard(time_fn=clock)
        results = [
            guard.check("203.0.113.7", f"user{i}@example.com")
            for i in range(20)
        ]
        allowed = [r for r in results if r.allowed]
        throttled = [r for r in results if r.reason == "throttled"]
        self.assertEqual(len(allowed), 5)
        self.assertEqual(len(throttled), 15)
        self.assertTrue(all(r.retry_after_seconds > 0 for r in throttled))

    def test_one_address_from_many_ips_is_throttled(self):
        clock = FakeClock()
        guard = SignupGuard(time_fn=clock)
        results = [
            guard.check(f"198.51.100.{i}", "target@example.com")
            for i in range(10)
        ]
        self.assertEqual(sum(r.allowed for r in results), 3)
        self.assertTrue(
            all(r.reason == "throttled" for r in results[3:]))

    def test_buckets_refill_with_time(self):
        clock = FakeClock()
        guard = SignupGuard(time_fn=clock)
        for i in range(5):
            self.assertTrue(
                guard.check("203.0.113.9", f"u{i}@example.com").allowed)
        self.assertFalse(
            guard.check("203.0.113.9", "u6@example.com").allowed)
        clock.advance(3600)  # one hour: the IP bucket refills fully
        self.assertTrue(
            guard.check("203.0.113.9", "u6@example.com").allowed)

    def test_honest_pace_is_untouched(self):
        guard = SignupGuard(time_fn=FakeClock())
        decision = guard.check("192.0.2.10", "volmarr@example.com")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "ok")


class DomainPolicyTests(unittest.TestCase):
    def test_blocklist_refuses_domain_and_subdomains(self):
        guard = SignupGuard(
            domain_policy=BlocklistDomains({"throwaway.example"}),
            time_fn=FakeClock())
        for email in ("a@throwaway.example", "a@mail.throwaway.example"):
            decision = guard.check("192.0.2.1", email)
            self.assertFalse(decision.allowed, msg=email)
            self.assertEqual(decision.reason, "domain_refused")
        self.assertTrue(
            guard.check("192.0.2.1", "a@real.example").allowed)

    def test_domain_refusals_do_not_spend_throttle_tokens(self):
        guard = SignupGuard(
            domain_policy=BlocklistDomains({"throwaway.example"}),
            time_fn=FakeClock())
        for _ in range(20):
            guard.check("192.0.2.2", "a@throwaway.example")
        # The same IP's honest attempts still have a full bucket.
        self.assertTrue(
            guard.check("192.0.2.2", "a@real.example").allowed)

    def test_malformed_addresses_are_refused_as_malformed(self):
        guard = SignupGuard(time_fn=FakeClock())
        for email in ("", "no-at-sign", "a@", "@b.com", "a@b",
                      "a@b@c.com", "a@.com "):
            decision = guard.check("192.0.2.3", email)
            self.assertEqual(decision.reason, "invalid_email", msg=email)

    def test_domain_parsing_normalises(self):
        self.assertEqual(domain_of_email("A@ExAmPle.COM."), "example.com")
        self.assertIsNone(domain_of_email(None))


if __name__ == "__main__":
    unittest.main()
