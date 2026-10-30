"""S-037 acceptance battery: recovery codes.

Acceptance (roadmap S-037): generated hashed, single-use,
regenerating invalidates the old set loudly — plus the
DB-leak test and both gates (sudo, two-factor-enabled).

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
from samverk.recovery_codes import (
    CODES_PER_SET,
    RecoveryCodeStore,
    RecoveryError,
)
from samverk.totp import TotpStore, totp_at

GOOD_PW = "a long enough passphrase"
KEY = os.urandom(32)


class RecoveryCodeTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.db_path = Path(self._td.name) / "samverk.db"
        self.conn = db.init_db(self.db_path)
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.user = self.accounts.register("volmarr", GOOD_PW)
        self.other = self.accounts.register("astrid", GOOD_PW)
        self.clock = [int(time.time())]
        now = lambda: self.clock[0]  # noqa: E731
        self.fresh = [True]
        verify = lambda uid: self.fresh[0]  # noqa: E731
        self.totp = TotpStore(
            self.conn, self.accounts, audit=self.audit,
            encryption_key=KEY, reauth_verifier=verify, time_fn=now)
        self.codes = RecoveryCodeStore(
            self.conn, self.accounts, self.totp, audit=self.audit,
            reauth_verifier=verify, time_fn=now)

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def _enable_totp(self, user_id: int):
        enr = self.totp.begin_enrolment(user_id)
        code = totp_at(base64.b32decode(enr.secret_base32),
                       self.clock[0])
        self.assertTrue(self.totp.confirm_enrolment(user_id, code))
        self.clock[0] += 60  # leave the confirm step behind

    def test_generate_requires_twofactor_and_sudo(self):
        with self.assertRaises(RecoveryError) as ctx:
            self.codes.generate(self.user.id)
        self.assertEqual(ctx.exception.reason, "twofactor_required")
        self._enable_totp(self.user.id)
        self.fresh[0] = False
        with self.assertRaises(RecoveryError) as ctx:
            self.codes.generate(self.user.id)
        self.assertEqual(ctx.exception.reason, "sudo_required")
        self.assertEqual(self.codes.remaining(self.user.id), 0)

    def test_generated_set_shape_and_remaining(self):
        self._enable_totp(self.user.id)
        result = self.codes.generate(self.user.id)
        self.assertEqual(len(result.codes), CODES_PER_SET)
        self.assertEqual(result.invalidated, 0)
        self.assertEqual(len(set(result.codes)), CODES_PER_SET)
        for code in result.codes:
            self.assertRegex(code, r"^[A-Z2-9]{5}-[A-Z2-9]{5}$")
        self.assertEqual(
            self.codes.remaining(self.user.id), CODES_PER_SET)

    def test_codes_are_single_use_and_account_bound(self):
        self._enable_totp(self.user.id)
        result = self.codes.generate(self.user.id)
        code = result.codes[0]
        self.assertFalse(self.codes.redeem(self.other.id, code))
        self.assertTrue(self.codes.redeem(self.user.id, code))
        self.assertFalse(self.codes.redeem(self.user.id, code))
        self.assertFalse(self.codes.redeem(self.user.id, "AAAAA-AAAAA"))
        self.assertFalse(self.codes.redeem(self.user.id, None))
        # Entry forgiveness: lowercase, spaces, no dash all work.
        sloppy = result.codes[1].lower().replace("-", " ")
        self.assertTrue(self.codes.redeem(self.user.id, sloppy))
        self.assertEqual(
            self.codes.remaining(self.user.id), CODES_PER_SET - 2)

    def test_regeneration_invalidates_the_old_set_loudly(self):
        self._enable_totp(self.user.id)
        first = self.codes.generate(self.user.id)
        self.assertTrue(self.codes.redeem(self.user.id, first.codes[0]))
        second = self.codes.generate(self.user.id)
        self.assertEqual(second.invalidated, CODES_PER_SET)
        for old in first.codes[1:]:
            self.assertFalse(self.codes.redeem(self.user.id, old))
        self.assertEqual(
            self.codes.remaining(self.user.id), CODES_PER_SET)
        self.assertTrue(
            self.codes.redeem(self.user.id, second.codes[0]))

    def test_plaintext_codes_never_touch_the_database(self):
        self._enable_totp(self.user.id)
        result = self.codes.generate(self.user.id)
        raw = self.db_path.read_bytes()
        for code in result.codes:
            self.assertNotIn(code.encode("ascii"), raw)
            self.assertNotIn(
                code.replace("-", "").encode("ascii"), raw)

    def test_generation_and_use_are_audited_without_codes(self):
        self._enable_totp(self.user.id)
        result = self.codes.generate(self.user.id)
        self.codes.redeem(self.user.id, result.codes[0])
        rows = self.conn.execute(
            "SELECT action, detail FROM audit_log"
            " WHERE action LIKE 'auth.recovery.%' ORDER BY seq"
        ).fetchall()
        self.assertEqual([r["action"] for r in rows],
                         ["auth.recovery.generate", "auth.recovery.use"])
        for row in rows:
            for code in result.codes:
                self.assertNotIn(code, row["detail"] or "")


if __name__ == "__main__":
    unittest.main()
