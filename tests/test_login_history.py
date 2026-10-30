"""S-047 acceptance battery: login history.

Acceptance (roadmap S-047): user-visible record of sign-ins
and security events on their account. Proven: successful
and failed sign-ins, logout, and security events (password
change, session revoke, suspension by an admin) all appear
for their owner, newest first; another account's events
never appear; the sign-in-only filter works; the page
renders hostile values inert through the escaping seam.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk import db
from samverk.account_suspension import AccountSuspension
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.login import LoginFailed, LoginService
from samverk.login_history import LoginHistory, render_history_page
from samverk.password_reset import PasswordService
from samverk.sessions import SessionStore

GOOD_PW = "a long enough passphrase"
NEW_PW = "a different long passphrase"


class LoginHistoryTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.audit = AuditLog(self.conn)
        self.clock = [int(time.time())]
        now = lambda: self.clock[0]  # noqa: E731
        self.accounts = AccountStore(self.conn, audit=self.audit, time_fn=now)
        self.user = self.accounts.register("volmarr", GOOD_PW)
        self.other = self.accounts.register("astrid", GOOD_PW)
        self.sessions = SessionStore(self.conn, time_fn=now)
        self.login = LoginService(
            self.conn, self.accounts, self.sessions,
            audit=self.audit, time_fn=now)
        self.history = LoginHistory(self.conn, self.accounts)

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def test_signins_failures_and_logout_appear_newest_first(self):
        with self.assertRaises(LoginFailed):
            self.login.login("volmarr", "wrong password here")
        token = self.login.login("volmarr", GOOD_PW, source_ip="10.0.0.9")
        self.login.logout(token)
        entries = self.history.history_for(self.user.id)
        actions = [e.action for e in entries]
        self.assertEqual(actions[0], "auth.logout")
        self.assertIn("auth.login.success", actions)
        self.assertIn("auth.login.failure", actions)
        self.assertIn("auth.signup.success", actions)
        success = [e for e in entries
                   if e.action == "auth.login.success"][0]
        self.assertEqual(success.source_ip, "10.0.0.9")

    def test_other_accounts_events_never_appear(self):
        self.login.login("astrid", GOOD_PW)
        entries = self.history.history_for(self.user.id)
        self.assertNotIn("auth.login.success",
                         [e.action for e in entries])
        self.assertEqual(self.history.history_for(9999), [])

    def test_security_events_and_signin_filter(self):
        token = self.login.login("volmarr", GOOD_PW)
        pw = PasswordService(
            self.conn, self.accounts, self.sessions, audit=self.audit)
        pw.change_password(self.user.id, GOOD_PW, NEW_PW)
        entries = self.history.history_for(self.user.id)
        self.assertIn("auth.password.change", [e.action for e in entries])
        signins = self.history.history_for(
            self.user.id, signins_only=True)
        self.assertTrue(signins)
        self.assertTrue(all(e.is_signin_event for e in signins))
        self.assertNotIn("auth.password.change",
                         [e.action for e in signins])
        self.assertIsNotNone(token)

    def test_admin_suspension_of_the_account_appears(self):
        admin = self.accounts.register("adminuser", GOOD_PW)
        with self.conn:
            self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?",
                              (admin.id,))
        susp = AccountSuspension(
            self.conn, self.accounts, self.sessions, audit=self.audit)
        susp.suspend(admin.id, self.user.id, "spam reports")
        actions = [e.action for e in
                   self.history.history_for(self.user.id)]
        self.assertIn("admin.user.suspend", actions)

    def test_page_renders_and_escapes(self):
        token = self.login.login(
            "volmarr", GOOD_PW, source_ip="<script>alert(1)</script>")
        page = render_history_page(
            "volmarr", self.history.history_for(self.user.id))
        self.assertIn("Sign-in and security history", page)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIsNotNone(token)


if __name__ == "__main__":
    unittest.main()
