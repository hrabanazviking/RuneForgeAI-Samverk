"""S-026 acceptance battery: email verification.

Acceptance (roadmap S-026): token flow when SMTP is configured;
operator-approval path when it is not; both audit-logged.

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
from samverk.email_verification import EmailVerification, VerificationError

GOOD_PW = "a long enough passphrase"


class FakeClock:
    def __init__(self):
        self.now = 1_700_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TokenFlowTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.sent: list[tuple[str, str]] = []
        self.clock = FakeClock()
        self.verify_svc = EmailVerification(
            self.conn, self.accounts, audit=self.audit,
            mailer=lambda addr, tok: self.sent.append((addr, tok)),
            time_fn=self.clock)
        self.user = self.accounts.register(
            "volmarr", GOOD_PW, "v@example.com",
            verification_mode="smtp")

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def test_token_flow_verifies_and_activates(self):
        self.assertEqual(self.user.status, "pending_verification")
        self.assertTrue(self.verify_svc.request_verification(self.user.id))
        self.assertEqual(len(self.sent), 1)
        addr, token = self.sent[0]
        self.assertEqual(addr, "v@example.com")
        verified = self.verify_svc.verify(token)
        self.assertTrue(verified.email_verified)
        self.assertEqual(verified.status, "active")

    def test_token_is_single_use(self):
        self.verify_svc.request_verification(self.user.id)
        token = self.sent[0][1]
        self.verify_svc.verify(token)
        with self.assertRaises(VerificationError) as ctx:
            self.verify_svc.verify(token)
        self.assertEqual(ctx.exception.reason, "invalid_or_expired")

    def test_token_expires(self):
        self.verify_svc.request_verification(self.user.id)
        token = self.sent[0][1]
        self.clock.advance(24 * 3600 + 1)
        with self.assertRaises(VerificationError):
            self.verify_svc.verify(token)

    def test_new_request_retires_old_token(self):
        self.verify_svc.request_verification(self.user.id)
        old = self.sent[0][1]
        self.verify_svc.request_verification(self.user.id)
        new = self.sent[1][1]
        with self.assertRaises(VerificationError):
            self.verify_svc.verify(old)
        self.assertTrue(self.verify_svc.verify(new).email_verified)

    def test_db_leak_holds_no_usable_token(self):
        """As S-006: values stolen from the DB redeem nothing, and
        the raw token appears nowhere in the database file."""
        self.verify_svc.request_verification(self.user.id)
        raw = self.sent[0][1]
        stored = self.conn.execute(
            "SELECT token_hash FROM email_verification_tokens"
        ).fetchone()["token_hash"]
        with self.assertRaises(VerificationError):
            self.verify_svc.verify(stored)
        db_bytes = Path(self._td.name, "samverk.db").read_bytes()
        self.assertNotIn(raw.encode(), db_bytes)

    def test_both_outcomes_audit_logged(self):
        self.verify_svc.request_verification(self.user.id)
        with self.assertRaises(VerificationError):
            self.verify_svc.verify("forged-token-value")
        self.verify_svc.verify(self.sent[0][1])
        rows = self.conn.execute(
            "SELECT outcome FROM audit_log WHERE action='auth.email.verify'"
            " ORDER BY seq").fetchall()
        self.assertEqual([r["outcome"] for r in rows],
                         ["denied", "success"])
        ok, bad, _ = verify_chain(self.conn)
        self.assertTrue(ok, msg=f"chain broken at {bad}")


class OperatorPathTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.verify_svc = EmailVerification(
            self.conn, self.accounts, audit=self.audit, mailer=None)

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def test_no_smtp_means_operator_road(self):
        user = self.accounts.register(
            "pending", GOOD_PW, "p@example.com",
            verification_mode="smtp")
        # No mailer: no token is minted or pretended.
        self.assertFalse(self.verify_svc.request_verification(user.id))
        count = self.conn.execute(
            "SELECT COUNT(*) c FROM email_verification_tokens"
        ).fetchone()["c"]
        self.assertEqual(count, 0)
        moved = self.accounts.get_by_id(user.id)
        self.assertEqual(moved.status, "pending_approval")
        approved = self.verify_svc.approve_user(user.id, operator_id=99)
        self.assertEqual(approved.status, "active")

    def test_no_email_account_takes_operator_road(self):
        user = self.accounts.register(
            "noemail", GOOD_PW, verification_mode="operator")
        with self.assertRaises(VerificationError) as ctx:
            self.verify_svc.request_verification(user.id)
        self.assertEqual(ctx.exception.reason, "no_email")
        self.assertEqual(
            self.verify_svc.approve_user(
                user.id, operator_id=99).status, "active")

    def test_approval_is_audit_logged_with_operator(self):
        user = self.accounts.register(
            "pending", GOOD_PW, verification_mode="operator")
        self.verify_svc.approve_user(user.id, operator_id=99)
        row = self.conn.execute(
            "SELECT actor_kind, actor_id FROM audit_log"
            " WHERE action='admin.user.approve'").fetchone()
        self.assertEqual((row["actor_kind"], row["actor_id"]),
                         ("admin", 99))

    def test_double_approval_refused(self):
        user = self.accounts.register(
            "pending", GOOD_PW, verification_mode="operator")
        self.verify_svc.approve_user(user.id, operator_id=99)
        with self.assertRaises(VerificationError) as ctx:
            self.verify_svc.approve_user(user.id, operator_id=99)
        self.assertEqual(ctx.exception.reason, "already_active")


if __name__ == "__main__":
    unittest.main()
