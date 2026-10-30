"""S-028 acceptance battery: password change and reset.

Acceptance (roadmap S-028): reset tokens single-use, expiring,
all-sessions-revoked on reset.

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
from samverk.login import LoginService
from samverk.password_reset import PasswordError, PasswordService
from samverk.sessions import SessionStore

GOOD_PW = "a long enough passphrase"
NEW_PW = "a brand new passphrase"
WRONG_PW = "a wrong long passphrase"


class FakeClock:
    def __init__(self):
        self.now = 1_700_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class PasswordServiceTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.sessions = SessionStore(self.conn)
        self.login = LoginService(
            self.conn, self.accounts, self.sessions, audit=self.audit)
        self.sent: list[tuple[str, str]] = []
        self.clock = FakeClock()
        self.service = PasswordService(
            self.conn, self.accounts, self.sessions, audit=self.audit,
            mailer=lambda a, t: self.sent.append((a, t)),
            time_fn=self.clock)
        self.user = self.accounts.register(
            "volmarr", GOOD_PW, "v@example.com")

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    # -- change -------------------------------------------------
    def test_change_revokes_all_sessions_and_swaps_password(self):
        t1 = self.login.login("volmarr", GOOD_PW)
        t2 = self.login.login("volmarr", GOOD_PW)
        revoked = self.service.change_password(self.user.id, GOOD_PW, NEW_PW)
        self.assertEqual(revoked, 2)
        self.assertIsNone(self.sessions.authenticate(t1))
        self.assertIsNone(self.sessions.authenticate(t2))
        with self.assertRaises(Exception):
            self.login.login("volmarr", GOOD_PW)
        self.assertTrue(self.login.login("volmarr", NEW_PW))

    def test_change_with_wrong_current_changes_nothing(self):
        token = self.login.login("volmarr", GOOD_PW)
        with self.assertRaises(PasswordError) as ctx:
            self.service.change_password(self.user.id, WRONG_PW, NEW_PW)
        self.assertEqual(ctx.exception.reason, "bad_current_password")
        self.assertEqual(self.sessions.authenticate(token), self.user.id)
        self.assertTrue(self.login.login("volmarr", GOOD_PW))

    def test_change_enforces_policy(self):
        with self.assertRaises(PasswordError) as ctx:
            self.service.change_password(self.user.id, GOOD_PW, "short")
        self.assertEqual(ctx.exception.reason, "password_too_short")

    # -- reset ----------------------------------------------------
    def test_reset_flow_single_use_and_revokes_sessions(self):
        session = self.login.login("volmarr", GOOD_PW)
        self.assertTrue(self.service.request_reset("v@example.com"))
        self.assertEqual(len(self.sent), 1)
        token = self.sent[0][1]
        uid = self.service.reset_password(token, NEW_PW)
        self.assertEqual(uid, self.user.id)
        self.assertIsNone(self.sessions.authenticate(session))
        self.assertTrue(self.login.login("volmarr", NEW_PW))
        with self.assertRaises(PasswordError) as ctx:
            self.service.reset_password(token, "another new passphrase")
        self.assertEqual(ctx.exception.reason, "invalid_or_expired")

    def test_reset_token_expires_after_one_hour(self):
        self.service.request_reset("volmarr")
        token = self.sent[0][1]
        self.clock.advance(3601)
        with self.assertRaises(PasswordError):
            self.service.reset_password(token, NEW_PW)

    def test_reset_request_never_enumerates(self):
        self.assertTrue(self.service.request_reset("ghost"))
        self.assertTrue(self.service.request_reset("ghost@example.com"))
        self.assertTrue(self.service.request_reset(""))
        self.assertEqual(self.sent, [])

    def test_reset_db_leak_holds_no_usable_token(self):
        self.service.request_reset("volmarr")
        raw = self.sent[0][1]
        stored = self.conn.execute(
            "SELECT token_hash FROM password_reset_tokens"
        ).fetchone()["token_hash"]
        with self.assertRaises(PasswordError):
            self.service.reset_password(stored, NEW_PW)
        self.assertNotIn(raw.encode(),
                         Path(self._td.name, "samverk.db").read_bytes())

    def test_refused_new_password_does_not_burn_token(self):
        self.service.request_reset("volmarr")
        token = self.sent[0][1]
        with self.assertRaises(PasswordError):
            self.service.reset_password(token, "short")
        self.assertEqual(self.service.reset_password(token, NEW_PW),
                         self.user.id)

    def test_operator_reset_road(self):
        token = self.service.issue_operator_reset(
            self.user.id, operator_id=99)
        self.assertEqual(self.service.reset_password(token, NEW_PW),
                         self.user.id)
        row = self.conn.execute(
            "SELECT detail FROM audit_log"
            " WHERE action='auth.password.reset'").fetchone()
        self.assertIn('"via":"operator"', row["detail"])
        ok, bad, _ = verify_chain(self.conn)
        self.assertTrue(ok, msg=f"chain broken at {bad}")

    def test_change_and_reset_are_audit_logged(self):
        self.service.change_password(self.user.id, GOOD_PW, NEW_PW)
        self.service.request_reset("volmarr")
        self.service.reset_password(self.sent[0][1], GOOD_PW)
        actions = [r["action"] for r in self.conn.execute(
            "SELECT action FROM audit_log ORDER BY seq")]
        self.assertIn("auth.password.change", actions)
        self.assertIn("auth.password.reset", actions)


if __name__ == "__main__":
    unittest.main()
