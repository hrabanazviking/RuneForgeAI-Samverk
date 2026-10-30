"""S-091 acceptance battery: transfer limits.

Acceptance (roadmap S-091): pack size, wall-clock, and idle
timeouts per transport, configurable; refusals explain
themselves — every refusal message names the transport, the
measured amount, the limit, and the remedy.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db
from samverk.accounts import AccountStore
from samverk.git_http import SmartHttpService, TransportError
from samverk.repositories import RepositoryStore
from samverk.transfer_limits import (
    IdleWatch,
    TransferLimitError,
    TransferLimits,
    TransportLimits,
    WallClock,
)


class PolicyTests(unittest.TestCase):
    def test_defaults_exist_for_both_transports(self):
        policy = TransferLimits()
        for transport in ("http", "ssh"):
            limits = policy.for_transport(transport)
            self.assertIsNone(limits.max_pack_bytes)   # size: unset = no cap
            self.assertGreater(limits.wall_clock_seconds, 0)
            self.assertGreater(limits.idle_timeout_seconds, 0)

    def test_transports_are_configured_independently(self):
        policy = TransferLimits(
            http=TransportLimits(max_pack_bytes=100))
        self.assertEqual(policy.for_transport("http").max_pack_bytes, 100)
        self.assertIsNone(policy.for_transport("ssh").max_pack_bytes)
        tightened = policy.with_limits("ssh", max_pack_bytes=50)
        self.assertEqual(tightened.for_transport("ssh").max_pack_bytes, 50)
        self.assertEqual(tightened.for_transport("http").max_pack_bytes, 100)
        self.assertIsNone(policy.for_transport("ssh").max_pack_bytes)

    def test_invalid_limits_are_refused_at_construction(self):
        for bad in (TransportLimits(max_pack_bytes=-1),
                    TransportLimits(wall_clock_seconds=0),
                    TransportLimits(idle_timeout_seconds=-5)):
            with self.assertRaises(TransferLimitError):
                TransferLimits(http=bad)

    def test_pack_size_refusal_explains_itself(self):
        policy = TransferLimits(http=TransportLimits(max_pack_bytes=100))
        decision = policy.check_pack_size("http", 250)
        self.assertFalse(decision.allowed)
        for fragment in ("http", "250", "100", "smaller"):
            self.assertIn(fragment, decision.message)
        with self.assertRaises(TransferLimitError) as caught:
            policy.enforce_pack_size("http", 250)
        self.assertEqual(caught.exception.reason, "pack_too_large")
        self.assertEqual(str(caught.exception), decision.message)
        self.assertTrue(policy.check_pack_size("http", 100).allowed)
        self.assertTrue(policy.check_pack_size("ssh", 10**9).allowed)


class ClockTests(unittest.TestCase):
    def test_wall_clock_check_raises_past_the_budget(self):
        now = [1000.0]
        clock = WallClock(
            TransportLimits(wall_clock_seconds=30), "ssh",
            time_fn=lambda: now[0])
        self.assertEqual(clock.check(), 0.0)
        now[0] += 29
        self.assertEqual(clock.check(), 29.0)
        now[0] += 2
        with self.assertRaises(TransferLimitError) as caught:
            clock.check()
        self.assertEqual(caught.exception.reason, "wall_clock_exceeded")
        self.assertIn("ssh", str(caught.exception))
        self.assertIn("31", str(caught.exception))

    def test_idle_watch_resets_on_progress(self):
        now = [0.0]
        watch = IdleWatch(
            TransportLimits(idle_timeout_seconds=10), "http",
            time_fn=lambda: now[0])
        now[0] += 9
        watch.touch()
        now[0] += 9
        self.assertEqual(watch.check(), 9.0)   # progress reset the clock
        now[0] += 2
        with self.assertRaises(TransferLimitError) as caught:
            watch.check()
        self.assertEqual(caught.exception.reason, "idle_timeout")
        self.assertIn("http", str(caught.exception))


class HttpWiringTests(unittest.TestCase):
    def test_oversized_pack_is_refused_before_git_and_ref_stays(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        conn = db.init_db(root / "samverk.db")
        self.addCleanup(conn.close)
        accounts = AccountStore(conn)
        owner = accounts.register("volmarr", "a long enough passphrase")
        repos = RepositoryStore(conn, root, accounts)
        repos.create_repository(owner.id, "volmarr", "samverk")
        policy = TransferLimits(http=TransportLimits(max_pack_bytes=8))
        service = SmartHttpService(
            conn, root, accounts, repos, transfer_limits=policy)
        with self.assertRaises(TransportError) as caught:
            service.receive_pack(owner, "volmarr", "samverk", b"x" * 64)
        self.assertEqual(caught.exception.reason, "pack_too_large")
        self.assertIn("64", str(caught.exception))
        self.assertIn("8 bytes", str(caught.exception))
        # The wall clock is the timeout this door hands git.
        self.assertEqual(policy.wall_clock_timeout("http"), 600.0)
        custom = TransferLimits(
            http=TransportLimits(wall_clock_seconds=42))
        self.assertEqual(custom.wall_clock_timeout("http"), 42.0)


if __name__ == "__main__":
    unittest.main()
