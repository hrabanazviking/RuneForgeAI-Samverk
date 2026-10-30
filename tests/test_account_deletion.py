"""S-043 acceptance battery: account deletion.

Acceptance (roadmap S-043): grace period, typed confirmation,
data inventory shown before the act; irreversible steps
audit-logged. Proven: the inventory counts what exists, a
wrong typed name or a missing sudo grant schedules nothing,
a request inside grace destroys nothing and can be
cancelled whole, execution before grace destroys nothing,
and execution after grace deletes the account and all its
per-user data, kills its sessions, tombstones its name, and
leaves the audit chain intact with the steps recorded.

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
from samverk.account_deletion import (
    GRACE_SECONDS, AccountDeletion, DeletionError)
from samverk.accounts import AccountStore
from samverk.audit import AuditLog, verify_chain
from samverk.login import LoginFailed, LoginService
from samverk.profiles import ProfileStore
from samverk.sessions import SessionStore

GOOD_PW = "a long enough passphrase"


class AccountDeletionTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.audit = AuditLog(self.conn)
        self.clock = [int(time.time())]
        now = lambda: self.clock[0]  # noqa: E731
        self.accounts = AccountStore(self.conn, audit=self.audit, time_fn=now)
        self.user = self.accounts.register("volmarr", GOOD_PW, "v@example.org")
        self.sessions = SessionStore(self.conn, time_fn=now)
        self.login = LoginService(
            self.conn, self.accounts, self.sessions,
            audit=self.audit, time_fn=now)
        self.deletion = AccountDeletion(
            self.conn, self.accounts, audit=self.audit, time_fn=now)
        self.ok = lambda uid: True  # noqa: E731

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def test_inventory_counts_what_the_account_holds(self):
        self.login.login("volmarr", GOOD_PW)
        ProfileStore(self.conn, self.accounts, audit=self.audit).update_profile(
            self.user.id, display_name="Volmarr", bio="hi")
        inv = self.deletion.inventory(self.user.id)
        self.assertEqual(inv.username, "volmarr")
        self.assertEqual(inv.counts["sessions"], 1)
        self.assertEqual(inv.counts["profiles"], 1)
        self.assertGreaterEqual(inv.total, 2)

    def test_typed_confirmation_and_sudo_gate(self):
        with self.assertRaises(DeletionError) as ctx:
            self.deletion.request(self.user.id, "notmyname", self.ok)
        self.assertEqual(ctx.exception.reason, "confirmation_mismatch")
        with self.assertRaises(DeletionError) as ctx:
            self.deletion.request(self.user.id, "volmarr", None)
        self.assertEqual(ctx.exception.reason, "sudo_required")
        with self.assertRaises(DeletionError) as ctx:
            self.deletion.request(self.user.id, "volmarr", lambda uid: False)
        self.assertEqual(ctx.exception.reason, "sudo_required")
        self.assertIsNone(self.deletion.pending_for(self.user.id))
        self.assertEqual(self.accounts.get_by_id(self.user.id).status, "active")

    def test_grace_period_and_cancel_restores_whole(self):
        token = self.login.login("volmarr", GOOD_PW)
        pending = self.deletion.request(self.user.id, "Volmarr", self.ok)
        self.assertEqual(pending.scheduled_at - pending.requested_at,
                         GRACE_SECONDS)
        # Inside grace: nothing destroyed, login refused by status.
        self.assertIsNotNone(self.accounts.get_by_id(self.user.id))
        with self.assertRaises(LoginFailed):
            self.login.login("volmarr", GOOD_PW)
        self.assertFalse(self.deletion.finalize(self.user.id))
        self.assertTrue(self.deletion.cancel(self.user.id))
        self.assertEqual(self.accounts.get_by_id(self.user.id).status, "active")
        token2 = self.login.login("volmarr", GOOD_PW)
        self.assertEqual(self.sessions.authenticate(token2), self.user.id)
        self.assertIsNotNone(token)

    def test_execution_after_grace_deletes_everything(self):
        token = self.login.login("volmarr", GOOD_PW)
        self.deletion.request(self.user.id, "volmarr", self.ok)
        self.clock[0] += GRACE_SECONDS + 1
        self.assertEqual(self.deletion.execute_due(), [self.user.id])
        self.assertIsNone(self.accounts.get_by_id(self.user.id))
        self.assertIsNone(self.sessions.authenticate(token))
        for table in ("sessions", "profiles"):
            n = self.conn.execute(
                f"SELECT COUNT(*) c FROM {table} WHERE user_id = ?",
                (self.user.id,)).fetchone()["c"]
            self.assertEqual(n, 0, table)
        # The name is held against instant impersonation.
        from samverk.accounts import RegistrationError
        with self.assertRaises(RegistrationError):
            self.accounts.register("volmarr", GOOD_PW)
        # Audit witness survives, chain verifies, steps recorded.
        ok, bad, _ = verify_chain(self.conn)
        self.assertTrue(ok, bad)
        actions = [r["action"] for r in self.conn.execute(
            "SELECT action FROM audit_log WHERE action LIKE"
            " 'auth.deletion.%' ORDER BY seq")]
        self.assertEqual(actions,
                         ["auth.deletion.request", "auth.deletion.execute"])


if __name__ == "__main__":
    unittest.main()
