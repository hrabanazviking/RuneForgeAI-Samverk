"""S-044 acceptance battery: account suspension.

Acceptance (roadmap S-044): admin suspend/unsuspend with
reason; suspended accounts' content hidden per policy, never
silently deleted. Proven: non-admins and reasonless attempts
refused, suspension kills sessions and login, content is
hidden through the policy seam while every row survives,
unsuspend restores the account whole, and both acts are on
the record and in the audit log.

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
from samverk.account_suspension import AccountSuspension, SuspensionError
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.login import LoginFailed, LoginService
from samverk.profiles import ProfileStore
from samverk.sessions import SessionStore

GOOD_PW = "a long enough passphrase"


class AccountSuspensionTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.audit = AuditLog(self.conn)
        self.clock = [int(time.time())]
        now = lambda: self.clock[0]  # noqa: E731
        self.accounts = AccountStore(self.conn, audit=self.audit, time_fn=now)
        self.admin = self.accounts.register("adminuser", GOOD_PW)
        with self.conn:
            self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?",
                              (self.admin.id,))
        self.user = self.accounts.register("volmarr", GOOD_PW)
        self.sessions = SessionStore(self.conn, time_fn=now)
        self.login = LoginService(
            self.conn, self.accounts, self.sessions,
            audit=self.audit, time_fn=now)
        self.susp = AccountSuspension(
            self.conn, self.accounts, self.sessions,
            audit=self.audit, time_fn=now)
        ProfileStore(self.conn, self.accounts, audit=self.audit).update_profile(
            self.user.id, display_name="Volmarr", bio="still here")

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def test_only_admins_with_a_reason_may_suspend(self):
        with self.assertRaises(SuspensionError) as ctx:
            self.susp.suspend(self.user.id, self.user.id, "spam")
        self.assertEqual(ctx.exception.reason, "not_admin")
        with self.assertRaises(SuspensionError) as ctx:
            self.susp.suspend(self.admin.id, self.user.id, "  ")
        self.assertEqual(ctx.exception.reason, "reason_required")
        with self.assertRaises(SuspensionError) as ctx:
            self.susp.suspend(self.admin.id, self.admin.id, "spam")
        self.assertEqual(ctx.exception.reason, "cannot_suspend_self")
        self.assertFalse(self.susp.is_suspended(self.user.id))

    def test_suspension_hides_but_never_deletes(self):
        token = self.login.login("volmarr", GOOD_PW)
        rec = self.susp.suspend(self.admin.id, self.user.id, "spam reports")
        self.assertEqual(rec.reason, "spam reports")
        self.assertTrue(self.susp.is_suspended(self.user.id))
        self.assertFalse(self.susp.is_content_visible(self.user.id))
        self.assertEqual(self.susp.current_reason(self.user.id),
                         "spam reports")
        # Sessions die, login is refused generically…
        self.assertIsNone(self.sessions.authenticate(token))
        with self.assertRaises(LoginFailed):
            self.login.login("volmarr", GOOD_PW)
        # …but nothing was deleted: the profile row is intact.
        profile = ProfileStore(
            self.conn, self.accounts, audit=self.audit).get_profile(
                self.user.id)
        self.assertEqual(profile.bio, "still here")
        self.assertIsNotNone(self.accounts.get_by_id(self.user.id))

    def test_unsuspend_restores_the_account_whole(self):
        self.susp.suspend(self.admin.id, self.user.id, "spam reports")
        self.susp.unsuspend(self.admin.id, self.user.id)
        self.assertFalse(self.susp.is_suspended(self.user.id))
        self.assertTrue(self.susp.is_content_visible(self.user.id))
        token = self.login.login("volmarr", GOOD_PW)
        self.assertEqual(self.sessions.authenticate(token), self.user.id)
        hist = self.susp.history(self.user.id)
        self.assertEqual([h.action for h in hist], ["suspend", "unsuspend"])
        actions = [r["action"] for r in self.conn.execute(
            "SELECT action FROM audit_log WHERE action LIKE"
            " 'admin.user.%suspend' ORDER BY seq")]
        self.assertEqual(actions,
                         ["admin.user.suspend", "admin.user.unsuspend"])
        with self.assertRaises(SuspensionError):
            self.susp.unsuspend(self.admin.id, self.user.id)


if __name__ == "__main__":
    unittest.main()
