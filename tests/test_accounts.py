"""S-025 acceptance battery: registration.

Acceptance (roadmap S-025): username rules (case, reserved
names), email optional-but-supported — *duplicate/reserved
attempts refused clearly.*

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk import db
from samverk.accounts import AccountStore, RegistrationError
from samverk.audit import AuditLog, verify_chain
from samverk.passwords import verify_password

GOOD_PW = "a long enough passphrase"


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.audit = AuditLog(self.conn)
        self.store = AccountStore(self.conn, audit=self.audit)

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def test_happy_path_no_email(self):
        user = self.store.register("Volmarr", GOOD_PW)
        self.assertEqual(user.username, "Volmarr")
        self.assertIsNone(user.email)
        self.assertEqual(user.status, "active")
        # The password is stored only as a verifiable scrypt hash.
        stored = self.store.password_hash_for(user.id)
        self.assertTrue(verify_password(GOOD_PW, stored))
        self.assertNotIn(GOOD_PW, stored)

    def test_happy_path_with_email_normalised_domain(self):
        user = self.store.register("yrsa", GOOD_PW, "Yrsa@Example.COM")
        self.assertEqual(user.email, "Yrsa@example.com")
        self.assertFalse(user.email_verified)

    def test_duplicate_username_any_case_refused_clearly(self):
        """The acceptance, literally: duplicates refused clearly,
        and case does not manufacture a second account."""
        self.store.register("Volmarr", GOOD_PW)
        for attempt in ("Volmarr", "volmarr", "VOLMARR"):
            with self.assertRaises(RegistrationError) as ctx:
                self.store.register(attempt, GOOD_PW)
            self.assertEqual(ctx.exception.reason, "username_taken")
            self.assertIn("already taken", str(ctx.exception))

    def test_lookup_is_case_insensitive(self):
        self.store.register("Volmarr", GOOD_PW)
        self.assertIsNotNone(self.store.get_by_username("vOlMaRr"))

    def test_reserved_names_refused_clearly(self):
        for name in ("admin", "Admin", "root", "support", "samverk",
                     "api", "con", "nul"):
            with self.assertRaises(RegistrationError) as ctx:
                self.store.register(name, GOOD_PW)
            self.assertIn(ctx.exception.reason,
                          ("username_reserved", "username_bad_characters"),
                          msg=name)

    def test_username_shape_rules(self):
        for name, reason in (
            ("ab", "username_too_short"),
            ("x" * 40, "username_too_long"),
            ("-volmarr", "username_bad_characters"),
            ("volmarr-", "username_bad_characters"),
            ("vol marr", "username_bad_characters"),
            ("vol/marr", "username_bad_characters"),
            ("vol..marr", "username_bad_characters"),
            ("", "username_required"),
        ):
            with self.assertRaises(RegistrationError) as ctx:
                self.store.register(name, GOOD_PW)
            self.assertEqual(ctx.exception.reason, reason, msg=name)

    def test_duplicate_email_any_case_refused(self):
        self.store.register("first", GOOD_PW, "a@example.com")
        with self.assertRaises(RegistrationError) as ctx:
            self.store.register("second", GOOD_PW, "A@EXAMPLE.com")
        self.assertEqual(ctx.exception.reason, "email_taken")

    def test_many_accounts_may_have_no_email(self):
        self.store.register("first", GOOD_PW)
        self.store.register("second", GOOD_PW)  # NULLs never collide

    def test_invalid_email_refused(self):
        for email in ("no-at", "a@b", "a@.com", "a b@c.com", ".a@c.com"):
            with self.assertRaises(RegistrationError) as ctx:
                self.store.register("someone", GOOD_PW, email)
            self.assertEqual(ctx.exception.reason, "email_invalid", msg=email)

    def test_password_policy(self):
        for pw, reason in (
            ("short", "password_too_short"),
            ("x" * 129, "password_too_long"),
            ("password123", "password_too_common"),
            ("SomeUserName", "password_too_common"),
        ):
            with self.assertRaises(RegistrationError) as ctx:
                self.store.register("someusername", pw)
            self.assertEqual(ctx.exception.reason, reason, msg=pw)

    def test_refusals_create_nothing_and_audit_both_ways(self):
        self.store.register("volmarr", GOOD_PW)
        with self.assertRaises(RegistrationError):
            self.store.register("volmarr", GOOD_PW)
        count = self.conn.execute(
            "SELECT COUNT(*) c FROM users").fetchone()["c"]
        self.assertEqual(count, 1)
        actions = [r["action"] for r in self.conn.execute(
            "SELECT action FROM audit_log ORDER BY seq")]
        self.assertEqual(actions,
                         ["auth.signup.success", "auth.signup.denied"])
        ok, bad, _ = verify_chain(self.conn)
        self.assertTrue(ok, msg=f"chain broken at {bad}")

    def test_verification_modes_set_status(self):
        smtp_user = self.store.register(
            "smtpuser", GOOD_PW, "s@example.com", verification_mode="smtp")
        self.assertEqual(smtp_user.status, "pending_verification")
        no_email = self.store.register(
            "noemail", GOOD_PW, verification_mode="smtp")
        self.assertEqual(no_email.status, "pending_approval")
        op_user = self.store.register(
            "opuser", GOOD_PW, verification_mode="operator")
        self.assertEqual(op_user.status, "pending_approval")


if __name__ == "__main__":
    unittest.main()
