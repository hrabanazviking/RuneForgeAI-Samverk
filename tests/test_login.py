"""S-027 acceptance battery: login/logout.

Acceptance (roadmap S-027): session issue and revoke, failed-
login audit events, generic failure messages that leak nothing.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog, verify_chain
from samverk.login import GENERIC_FAILURE, LoginFailed, LoginService
from samverk.sessions import SessionStore
from samverk.throttle import LoginThrottle

GOOD_PW = "a long enough passphrase"
WRONG_PW = "a wrong long passphrase"


class FakeClock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class LoginTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.sessions = SessionStore(self.conn)
        self.clock = FakeClock()
        self.service = LoginService(
            self.conn, self.accounts, self.sessions, audit=self.audit,
            throttle=LoginThrottle(time_fn=self.clock))
        self.user = self.accounts.register("Volmarr", GOOD_PW)

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def test_login_issues_a_working_session_any_case(self):
        token = self.service.login("volmarr", GOOD_PW)
        self.assertEqual(self.service.authenticate_session(token),
                         self.user.id)
        token2 = self.service.login("VOLMARR", GOOD_PW)
        self.assertNotEqual(token, token2)

    def test_logout_revokes_the_session(self):
        token = self.service.login("volmarr", GOOD_PW)
        self.assertTrue(self.service.logout(token))
        self.assertIsNone(self.service.authenticate_session(token))
        # A second logout is a quiet no-op.
        self.assertFalse(self.service.logout(token))
        actions = [r["action"] for r in self.conn.execute(
            "SELECT action FROM audit_log ORDER BY seq")]
        self.assertIn("auth.logout", actions)

    def test_generic_failure_leaks_nothing(self):
        """No-such-user, wrong-password, and pending-account all
        answer with exactly the same words."""
        self.accounts.register(
            "pending", GOOD_PW, "p@example.com",
            verification_mode="operator")
        messages = set()
        for username, pw in (("ghost", GOOD_PW),
                             ("volmarr", WRONG_PW),
                             ("pending", GOOD_PW),
                             ("", "")):
            with self.assertRaises(LoginFailed) as ctx:
                self.service.login(username, pw)
            messages.add(str(ctx.exception))
        self.assertEqual(messages, {GENERIC_FAILURE})

    def test_failures_are_audit_logged(self):
        for _ in range(2):
            with self.assertRaises(LoginFailed):
                self.service.login("volmarr", WRONG_PW)
        rows = self.conn.execute(
            "SELECT detail FROM audit_log"
            " WHERE action='auth.login.failure'").fetchall()
        self.assertEqual(len(rows), 2)
        self.assertIn("volmarr", rows[0]["detail"])
        self.assertNotIn(WRONG_PW, rows[0]["detail"])
        ok, bad, _ = verify_chain(self.conn)
        self.assertTrue(ok, msg=f"chain broken at {bad}")

    def test_throttle_delays_after_repeated_failures(self):
        for _ in range(4):  # 3 free, the 4th arms the backoff
            with self.assertRaises(LoginFailed):
                self.service.login("volmarr", WRONG_PW)
        # Even the right password must wait out the delay.
        with self.assertRaises(LoginFailed) as ctx:
            self.service.login("volmarr", GOOD_PW)
        self.assertGreater(ctx.exception.retry_after_seconds, 0)
        self.clock.advance(10)
        token = self.service.login("volmarr", GOOD_PW)
        self.assertEqual(self.service.authenticate_session(token),
                         self.user.id)

    def test_success_clears_throttle_state(self):
        for _ in range(2):
            with self.assertRaises(LoginFailed):
                self.service.login("volmarr", WRONG_PW)
        self.service.login("volmarr", GOOD_PW)
        # Failure counting restarted: two more failures are free.
        for _ in range(2):
            with self.assertRaises(LoginFailed):
                self.service.login("volmarr", WRONG_PW)
        self.assertTrue(self.service.login("volmarr", GOOD_PW))

    def test_login_success_is_audit_logged(self):
        self.service.login("volmarr", GOOD_PW)
        row = self.conn.execute(
            "SELECT actor_id FROM audit_log"
            " WHERE action='auth.login.success'").fetchone()
        self.assertEqual(row["actor_id"], self.user.id)


if __name__ == "__main__":
    unittest.main()
