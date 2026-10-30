"""S-040 acceptance battery: session management.

Acceptance (roadmap S-040): the user sees all their
sessions/devices and revokes any or all — a revoked session
dies on its very next request. Proven in that literal form,
plus owner-only revocation, the keep-current sweep, honest
status words (Active / Revoked / Expired), the audit trail
under the long-frozen `auth.session.revoke` event, and the
page rendering device labels through the escaping seam.

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
from samverk.session_management import (
    SessionManagement,
    render_sessions_page,
)
from samverk.sessions import IDLE_TTL_SECONDS, SessionStore

GOOD_PW = "a long enough passphrase"


class SessionManagementTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.user = self.accounts.register("volmarr", GOOD_PW)
        self.other = self.accounts.register("astrid", GOOD_PW)
        self.clock = [int(time.time())]
        now = lambda: self.clock[0]  # noqa: E731
        self.sessions = SessionStore(self.conn, time_fn=now)
        self.login = LoginService(
            self.conn, self.accounts, self.sessions,
            audit=self.audit, time_fn=now)
        self.mgmt = SessionManagement(
            self.conn, self.accounts, self.sessions,
            audit=self.audit, time_fn=now)
        self.laptop = self.login.login(
            "volmarr", GOOD_PW, source_ip="192.0.2.10",
            device_label="Laptop — Firefox")
        self.phone = self.login.login(
            "volmarr", GOOD_PW, source_ip="192.0.2.20",
            device_label="Phone — browser")

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def test_user_sees_all_sessions_with_devices(self):
        summaries = self.mgmt.list_sessions(
            self.user.id, current_token=self.laptop)
        self.assertEqual(len(summaries), 2)
        labels = {s.device_label for s in summaries}
        self.assertEqual(
            labels, {"Laptop — Firefox", "Phone — browser"})
        ips = {s.source_ip for s in summaries}
        self.assertEqual(ips, {"192.0.2.10", "192.0.2.20"})
        current = [s for s in summaries if s.current]
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0].device_label, "Laptop — Firefox")
        self.assertTrue(all(s.status == "Active" for s in summaries))

    def test_revoked_session_dies_on_next_request(self):
        summaries = self.mgmt.list_sessions(self.user.id)
        phone = next(s for s in summaries
                     if s.device_label == "Phone — browser")
        self.assertTrue(self.mgmt.revoke_one(self.user.id, phone.id))
        # The literal acceptance: the very next request with
        # that session's token resolves to nobody.
        self.assertIsNone(self.sessions.authenticate(self.phone))
        # And the other session is untouched.
        self.assertEqual(
            self.sessions.authenticate(self.laptop), self.user.id)
        after = {s.device_label: s.status for s in
                 self.mgmt.list_sessions(self.user.id)}
        self.assertEqual(after["Phone — browser"], "Revoked")
        self.assertEqual(after["Laptop — Firefox"], "Active")

    def test_revoke_is_owner_only(self):
        summaries = self.mgmt.list_sessions(self.user.id)
        target = summaries[0]
        self.assertFalse(self.mgmt.revoke_one(self.other.id, target.id))
        token = self.laptop if target.device_label.startswith("Laptop") \
            else self.phone
        self.assertEqual(self.sessions.authenticate(token), self.user.id)

    def test_revoke_all_spares_the_current_session(self):
        count = self.mgmt.revoke_all(
            self.user.id, keep_token=self.laptop)
        self.assertEqual(count, 1)
        self.assertIsNone(self.sessions.authenticate(self.phone))
        self.assertEqual(
            self.sessions.authenticate(self.laptop), self.user.id)
        count = self.mgmt.revoke_all(self.user.id)
        self.assertEqual(count, 1)
        self.assertIsNone(self.sessions.authenticate(self.laptop))

    def test_expired_session_reads_expired(self):
        self.clock[0] += IDLE_TTL_SECONDS + 60
        statuses = {s.status for s in
                    self.mgmt.list_sessions(self.user.id)}
        self.assertEqual(statuses, {"Expired"})

    def test_revocations_are_audited_with_scope(self):
        summaries = self.mgmt.list_sessions(self.user.id)
        self.mgmt.revoke_one(self.user.id, summaries[0].id)
        self.mgmt.revoke_all(self.user.id)
        rows = self.conn.execute(
            "SELECT detail FROM audit_log"
            " WHERE action = 'auth.session.revoke' ORDER BY seq"
        ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertIn('"one"', rows[0]["detail"])
        self.assertIn('"all"', rows[1]["detail"])

    def test_page_escapes_labels_and_offers_revoke(self):
        evil = self.login.login(
            "volmarr", GOOD_PW,
            device_label='<script>alert("x")</script>')
        summaries = self.mgmt.list_sessions(
            self.user.id, current_token=self.laptop)
        page = render_sessions_page("volmarr", summaries, "csrf-1")
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("Revoke this session", page)
        self.assertIn("Revoke all other sessions", page)
        self.assertIn("this session", page)
        self.assertIsNotNone(self.sessions.authenticate(evil))


if __name__ == "__main__":
    unittest.main()
