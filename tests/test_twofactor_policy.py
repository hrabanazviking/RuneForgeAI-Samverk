"""S-038 acceptance battery: two-factor enforcement policy.

Acceptance (roadmap S-038): instance/org may require 2FA for
admins, with a grace period and honest warnings. The org
scope is refused with its reason named (organisations land
in a later part); the instance scope is proven end to end:
non-admins untouched, grace warns without blocking, expiry
blocks, enrolment satisfies, re-saving never restarts grace.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import base64
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.totp import TotpStore, totp_at
from samverk.twofactor_policy import (
    DEFAULT_GRACE_SECONDS,
    PolicyError,
    TwoFactorPolicy,
)

GOOD_PW = "a long enough passphrase"
KEY = os.urandom(32)
DAY = 24 * 3600


class TwoFactorPolicyTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.admin = self.accounts.register("volmarr", GOOD_PW)
        self.plain = self.accounts.register("astrid", GOOD_PW)
        with self.conn:
            self.conn.execute(
                "UPDATE users SET is_admin = 1 WHERE id = ?",
                (self.admin.id,))
        self.clock = [int(time.time())]
        now = lambda: self.clock[0]  # noqa: E731
        self.totp = TotpStore(
            self.conn, self.accounts, audit=self.audit,
            encryption_key=KEY, reauth_verifier=lambda uid: True,
            time_fn=now)
        self.policy = TwoFactorPolicy(
            self.conn, self.accounts, self.totp, audit=self.audit,
            time_fn=now)

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def _enable_totp(self, user_id: int):
        enr = self.totp.begin_enrolment(user_id)
        code = totp_at(base64.b32decode(enr.secret_base32),
                       self.clock[0])
        self.assertTrue(self.totp.confirm_enrolment(user_id, code))

    def test_no_policy_no_requirement(self):
        status = self.policy.status_for(self.admin.id)
        self.assertFalse(status.required)
        self.assertTrue(status.compliant)
        self.assertFalse(status.blocked)
        self.assertIsNone(status.warning)

    def test_admin_in_grace_is_warned_not_blocked(self):
        self.policy.set_requirement(True)
        status = self.policy.status_for(self.admin.id)
        self.assertTrue(status.required)
        self.assertFalse(status.compliant)
        self.assertTrue(status.in_grace)
        self.assertFalse(status.blocked)
        self.assertEqual(
            status.grace_ends_at,
            self.clock[0] + DEFAULT_GRACE_SECONDS)
        self.assertIn("grace", status.warning)
        self.assertFalse(self.policy.is_blocked(self.admin.id))

    def test_non_admin_is_outside_the_policy(self):
        self.policy.set_requirement(True)
        self.clock[0] += DEFAULT_GRACE_SECONDS + DAY
        status = self.policy.status_for(self.plain.id)
        self.assertFalse(status.required)
        self.assertTrue(status.compliant)
        self.assertFalse(status.blocked)
        self.assertIsNone(status.warning)

    def test_after_grace_the_admin_is_blocked(self):
        self.policy.set_requirement(True, grace_seconds=DAY)
        self.clock[0] += DAY
        status = self.policy.status_for(self.admin.id)
        self.assertFalse(status.in_grace)
        self.assertTrue(status.blocked)
        self.assertIn("grace period has ended", status.warning)
        self.assertTrue(self.policy.is_blocked(self.admin.id))

    def test_enrolment_satisfies_even_after_grace(self):
        self.policy.set_requirement(True, grace_seconds=DAY)
        self.clock[0] += 2 * DAY
        self.assertTrue(self.policy.is_blocked(self.admin.id))
        self._enable_totp(self.admin.id)
        status = self.policy.status_for(self.admin.id)
        self.assertTrue(status.twofactor_enabled)
        self.assertTrue(status.compliant)
        self.assertFalse(status.blocked)
        self.assertIsNone(status.warning)

    def test_resaving_never_restarts_grace_and_off_clears(self):
        self.policy.set_requirement(True, grace_seconds=DAY)
        first_end = self.policy.status_for(self.admin.id).grace_ends_at
        self.clock[0] += 3600
        self.policy.set_requirement(True, grace_seconds=DAY)
        self.assertEqual(
            self.policy.status_for(self.admin.id).grace_ends_at,
            first_end)
        self.policy.set_requirement(False)
        status = self.policy.status_for(self.admin.id)
        self.assertFalse(status.required)
        self.assertFalse(status.blocked)
        rows = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log"
            " WHERE action = 'admin.settings.change'").fetchone()
        self.assertEqual(rows["n"], 3)

    def test_org_scope_is_refused_with_its_reason(self):
        with self.assertRaises(PolicyError) as ctx:
            self.policy.set_requirement(True, scope="org:hearth")
        self.assertEqual(ctx.exception.reason,
                         "org_scope_not_available")
        self.assertFalse(
            self.policy.status_for(self.admin.id).required)


if __name__ == "__main__":
    unittest.main()
