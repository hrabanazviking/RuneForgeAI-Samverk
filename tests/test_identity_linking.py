"""S-045 acceptance battery: identity-linking data shape.

Acceptance (roadmap S-045): an account may link external
identities (Samtal principal first) — shape only; the seam
itself is Part XIX. Proven: a Samtal principal links and
resolves, one principal cannot serve two accounts, one
provider cannot be linked twice by one account, invalid
shapes are refused, unlink frees the principal, and both
acts are audited. No authentication power is conferred:
this battery asserts the store exposes no authenticate
seam at all.

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
from samverk.identity_linking import (
    PROVIDER_SAMTAL, IdentityLinkError, IdentityLinkStore)

GOOD_PW = "a long enough passphrase"


class IdentityLinkingTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.user = self.accounts.register("volmarr", GOOD_PW)
        self.other = self.accounts.register("astrid", GOOD_PW)
        self.links = IdentityLinkStore(
            self.conn, self.accounts, audit=self.audit,
            time_fn=lambda: int(time.time()))

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def test_samtal_principal_links_and_resolves(self):
        link = self.links.link(self.user.id, PROVIDER_SAMTAL, "seat-14")
        self.assertEqual(link.provider, "samtal")
        self.assertEqual(
            self.links.resolve("samtal", "seat-14"), self.user.id)
        self.assertEqual(
            [x.provider for x in self.links.list_for_user(self.user.id)],
            ["samtal"])
        self.assertIsNone(self.links.resolve("samtal", "seat-99"))

    def test_one_principal_one_account_one_provider_one_link(self):
        self.links.link(self.user.id, "samtal", "seat-14")
        with self.assertRaises(IdentityLinkError) as ctx:
            self.links.link(self.other.id, "samtal", "seat-14")
        self.assertEqual(ctx.exception.reason, "already_claimed")
        with self.assertRaises(IdentityLinkError) as ctx:
            self.links.link(self.user.id, "samtal", "seat-15")
        self.assertEqual(ctx.exception.reason, "provider_already_linked")

    def test_invalid_shapes_refused(self):
        for bad_provider in ("Sam Tal", "", "UP PER", "-x"):
            with self.assertRaises(IdentityLinkError, msg=bad_provider):
                self.links.link(self.user.id, bad_provider, "x")
        with self.assertRaises(IdentityLinkError):
            self.links.link(self.user.id, "samtal", "  ")
        with self.assertRaises(IdentityLinkError):
            self.links.link(9999, "samtal", "seat-1")

    def test_unlink_frees_the_principal_and_both_acts_audited(self):
        self.links.link(self.user.id, "samtal", "seat-14")
        self.assertTrue(self.links.unlink(self.user.id, "samtal"))
        self.assertFalse(self.links.unlink(self.user.id, "samtal"))
        self.assertIsNone(self.links.resolve("samtal", "seat-14"))
        moved = self.links.link(self.other.id, "samtal", "seat-14")
        self.assertEqual(moved.user_id, self.other.id)
        actions = [r["action"] for r in self.conn.execute(
            "SELECT action FROM audit_log WHERE action LIKE"
            " 'auth.identity.%' ORDER BY seq")]
        self.assertEqual(actions, ["auth.identity.link",
                                   "auth.identity.unlink",
                                   "auth.identity.link"])

    def test_shape_only_no_authentication_power(self):
        self.assertFalse(hasattr(self.links, "authenticate"))
        self.assertFalse(hasattr(self.links, "login"))


if __name__ == "__main__":
    unittest.main()
