"""S-035 acceptance battery: TOTP enrolment.

Acceptance (roadmap S-035): QR (provisioning URI) + manual
secret, confirm-by-code, enforced step-up for enabling —
plus the RFC 6238 known-answer vectors and the DB-leak test
(a stolen database file holds no usable second factor).

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
from samverk.totp import (
    STEP_SECONDS,
    TotpError,
    TotpStore,
    hotp,
    totp_at,
)

GOOD_PW = "a long enough passphrase"
KEY = os.urandom(32)
# RFC 6238's SHA-1 test secret: ASCII "12345678901234567890".
RFC_SECRET = b"12345678901234567890"


class TotpAlgorithmTests(unittest.TestCase):
    def test_rfc6238_known_answer_vectors(self):
        # 8-digit RFC values truncated to Samverk's 6 digits.
        vectors = [
            (59, "287082"), (1111111109, "081804"),
            (1111111111, "050471"), (1234567890, "005924"),
            (2000000000, "279037"),
        ]
        for ts, expected in vectors:
            with self.subTest(ts=ts):
                self.assertEqual(totp_at(RFC_SECRET, ts), expected)

    def test_hotp_counter_zero_vector(self):
        # RFC 4226 Appendix D, count 0 -> 755224 (6 digits).
        self.assertEqual(hotp(RFC_SECRET, 0), "755224")
        self.assertEqual(hotp(RFC_SECRET, 1), "287082")


class TotpEnrolmentTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.db_path = Path(self._td.name) / "samverk.db"
        self.conn = db.init_db(self.db_path)
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.user = self.accounts.register("volmarr", GOOD_PW)
        self.clock = [1_700_000_000]
        now = lambda: self.clock[0]  # noqa: E731
        self.fresh = [True]
        self.totp = TotpStore(
            self.conn, self.accounts, audit=self.audit,
            encryption_key=KEY,
            reauth_verifier=lambda uid: self.fresh[0], time_fn=now)

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def _code_for(self, secret_b32: str, at: int | None = None) -> str:
        raw = base64.b32decode(secret_b32)
        return totp_at(raw, self.clock[0] if at is None else at)

    def _enrolled(self) -> str:
        enr = self.totp.begin_enrolment(self.user.id)
        self.assertTrue(
            self.totp.confirm_enrolment(
                self.user.id, self._code_for(enr.secret_base32)))
        return enr.secret_base32

    def test_enrolment_requires_step_up(self):
        self.fresh[0] = False
        with self.assertRaises(TotpError) as ctx:
            self.totp.begin_enrolment(self.user.id)
        self.assertEqual(ctx.exception.reason, "sudo_required")
        self.assertFalse(self.totp.is_enabled(self.user.id))
        bare = TotpStore(self.conn, self.accounts, encryption_key=KEY)
        with self.assertRaises(TotpError):
            bare.begin_enrolment(self.user.id)

    def test_enrolment_requires_encryption_key(self):
        no_key = TotpStore(
            self.conn, self.accounts,
            reauth_verifier=lambda uid: True)
        with self.assertRaises(TotpError) as ctx:
            no_key.begin_enrolment(self.user.id)
        self.assertEqual(ctx.exception.reason, "encryption_unavailable")

    def test_manual_secret_and_provisioning_uri(self):
        enr = self.totp.begin_enrolment(self.user.id)
        self.assertEqual(len(base64.b32decode(enr.secret_base32)), 20)
        self.assertTrue(enr.provisioning_uri.startswith(
            "otpauth://totp/Samverk:volmarr?"))
        self.assertIn(f"secret={enr.secret_base32}",
                      enr.provisioning_uri)
        self.assertIn("issuer=Samverk", enr.provisioning_uri)
        self.assertFalse(self.totp.is_enabled(self.user.id))

    def test_confirm_by_code_enables_and_audits(self):
        enr = self.totp.begin_enrolment(self.user.id)
        self.assertFalse(self.totp.confirm_enrolment(
            self.user.id, "000000" if self._code_for(
                enr.secret_base32) != "000000" else "111111"))
        self.assertFalse(self.totp.is_enabled(self.user.id))
        self.assertTrue(self.totp.confirm_enrolment(
            self.user.id, self._code_for(enr.secret_base32)))
        self.assertTrue(self.totp.is_enabled(self.user.id))
        rows = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log"
            " WHERE action = 'auth.twofactor.enable'").fetchone()
        self.assertEqual(rows["n"], 1)

    def test_verify_accepts_window_and_rejects_replay(self):
        secret = self._enrolled()
        self.clock[0] += STEP_SECONDS  # move past the confirm step
        code = self._code_for(secret)
        self.assertTrue(self.totp.verify_code(self.user.id, code))
        self.assertFalse(self.totp.verify_code(self.user.id, code))
        # A code from the next step works; a malformed one does not.
        nxt = self._code_for(secret, at=self.clock[0] + STEP_SECONDS)
        self.clock[0] += STEP_SECONDS
        self.assertTrue(self.totp.verify_code(self.user.id, nxt))
        self.assertFalse(self.totp.verify_code(self.user.id, "12 34"))
        self.assertFalse(self.totp.verify_code(self.user.id, None))

    def test_unconfirmed_credential_verifies_nothing(self):
        enr = self.totp.begin_enrolment(self.user.id)
        self.assertFalse(self.totp.verify_code(
            self.user.id, self._code_for(enr.secret_base32)))

    def test_stored_secret_is_encrypted_db_leak(self):
        secret = self._enrolled()
        stored = self.conn.execute(
            "SELECT secret_enc FROM totp_credentials WHERE user_id = ?",
            (self.user.id,)).fetchone()["secret_enc"]
        self.assertNotIn(secret, stored)
        raw = self.db_path.read_bytes()
        self.assertNotIn(secret.encode("ascii"), raw)

    def test_rebegin_replaces_pending_but_not_confirmed(self):
        first = self.totp.begin_enrolment(self.user.id)
        second = self.totp.begin_enrolment(self.user.id)
        self.assertNotEqual(first.secret_base32, second.secret_base32)
        self.assertFalse(self.totp.confirm_enrolment(
            self.user.id, self._code_for(first.secret_base32)))
        self.assertTrue(self.totp.confirm_enrolment(
            self.user.id, self._code_for(second.secret_base32)))
        with self.assertRaises(TotpError) as ctx:
            self.totp.begin_enrolment(self.user.id)
        self.assertEqual(ctx.exception.reason, "already_enabled")


if __name__ == "__main__":
    unittest.main()
