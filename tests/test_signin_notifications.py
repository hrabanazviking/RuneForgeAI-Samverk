"""S-041 acceptance battery: new-sign-in notification.

Acceptance (roadmap S-041): email (if configured) + in-app
notice with IP and time — the event fires once per new
device. Proven in that form: first sighting fires on both
channels, a repeat from the same device fires nothing, a
new address or a new label fires again, an account without
email still gets its in-app notice, and the whole thing is
wired through the real login service.

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
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.login import LoginService
from samverk.sessions import SessionStore
from samverk.signin_notifications import SignInNotifier

GOOD_PW = "a long enough passphrase"


class SignInNotificationTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.user = self.accounts.register(
            "volmarr", GOOD_PW, "volmarr@example.org")
        self.no_mail = self.accounts.register("astrid", GOOD_PW)
        self.clock = [int(time.time())]
        now = lambda: self.clock[0]  # noqa: E731
        self.sent: list[tuple[str, str]] = []
        self.notifier = SignInNotifier(
            self.conn, self.accounts, audit=self.audit,
            mailer=lambda addr, msg: self.sent.append((addr, msg)),
            time_fn=now)
        self.sessions = SessionStore(self.conn, time_fn=now)
        self.login = LoginService(
            self.conn, self.accounts, self.sessions, audit=self.audit,
            signin_notifier=self.notifier.record_signin, time_fn=now)

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def test_first_signin_fires_both_channels_with_ip_and_time(self):
        fired = self.notifier.record_signin(
            self.user.id, source_ip="192.0.2.10",
            device_label="Laptop — Firefox")
        self.assertTrue(fired)
        notices = self.notifier.list_notices(self.user.id)
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0].source_ip, "192.0.2.10")
        self.assertEqual(notices[0].device_label, "Laptop — Firefox")
        self.assertEqual(notices[0].created_at, self.clock[0])
        self.assertTrue(notices[0].unread)
        self.assertEqual(len(self.sent), 1)
        addr, message = self.sent[0]
        self.assertEqual(addr, "volmarr@example.org")
        self.assertIn("192.0.2.10", message)
        self.assertIn("Laptop — Firefox", message)

    def test_once_per_new_device_never_per_signin(self):
        self.assertTrue(self.notifier.record_signin(
            self.user.id, "192.0.2.10", "Laptop — Firefox"))
        self.clock[0] += 3600
        self.assertFalse(self.notifier.record_signin(
            self.user.id, "192.0.2.10", "Laptop — Firefox"))
        self.assertFalse(self.notifier.record_signin(
            self.user.id, "192.0.2.10", "Laptop — Firefox"))
        self.assertEqual(len(self.notifier.list_notices(self.user.id)), 1)
        self.assertEqual(len(self.sent), 1)
        # A new address is a new device; so is a new label.
        self.assertTrue(self.notifier.record_signin(
            self.user.id, "198.51.100.7", "Laptop — Firefox"))
        self.assertTrue(self.notifier.record_signin(
            self.user.id, "198.51.100.7", "Phone — browser"))
        self.assertEqual(len(self.notifier.list_notices(self.user.id)), 3)
        self.assertEqual(len(self.sent), 3)

    def test_account_without_email_still_gets_in_app_notice(self):
        self.assertTrue(self.notifier.record_signin(
            self.no_mail.id, "192.0.2.30", "Tablet"))
        self.assertEqual(
            len(self.notifier.list_notices(self.no_mail.id)), 1)
        self.assertEqual(self.sent, [])

    def test_no_mailer_still_gets_in_app_notice(self):
        quiet = SignInNotifier(
            self.conn, self.accounts, time_fn=lambda: self.clock[0])
        self.assertTrue(quiet.record_signin(
            self.user.id, "192.0.2.40", "Work machine"))
        self.assertEqual(self.notifier.unread_count(self.user.id), 1)

    def test_login_service_wires_the_notice(self):
        self.login.login("volmarr", GOOD_PW, source_ip="192.0.2.10",
                         device_label="Laptop — Firefox")
        self.login.login("volmarr", GOOD_PW, source_ip="192.0.2.10",
                         device_label="Laptop — Firefox")
        self.assertEqual(len(self.notifier.list_notices(self.user.id)), 1)
        rows = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log"
            " WHERE action = 'auth.signin.notify'").fetchone()
        self.assertEqual(rows["n"], 1)

    def test_inbox_read_marks_are_owner_only(self):
        self.notifier.record_signin(
            self.user.id, "192.0.2.10", "Laptop — Firefox")
        notice = self.notifier.list_notices(self.user.id)[0]
        self.assertFalse(
            self.notifier.mark_read(self.no_mail.id, notice.id))
        self.assertEqual(self.notifier.unread_count(self.user.id), 1)
        self.assertTrue(self.notifier.mark_read(self.user.id, notice.id))
        self.assertEqual(self.notifier.unread_count(self.user.id), 0)
        self.notifier.record_signin(
            self.user.id, "198.51.100.9", "Phone — browser")
        self.assertEqual(self.notifier.mark_all_read(self.user.id), 1)
        self.assertEqual(self.notifier.unread_count(self.user.id), 0)


if __name__ == "__main__":
    unittest.main()
