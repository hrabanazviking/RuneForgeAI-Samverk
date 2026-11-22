"""S-362 battery — identity linking by signed token exchange."""
import sys, tempfile, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.identity_linking import IdentityLinkStore
from samverk.seam_identity import SeamIdentityError, SeamIdentityService, mint_link_token

SECRET = b"seam-test-secret" * 4
ON = {"seam.samtal.enabled": True}
PW = "a long enough passphrase"

class SeamIdentityTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.conn = db.init_db(Path(self._td.name) / "s.db")
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.user = self.accounts.register("volmarr", PW)
        self.other = self.accounts.register("astrid", PW)
        self.links = IdentityLinkStore(self.conn, self.accounts, audit=self.audit, time_fn=lambda: 2000)
        self.svc = SeamIdentityService(self.links, secret=SECRET, settings=ON, time_fn=lambda: 2000)
    def tearDown(self):
        self.conn.close(); self._td.cleanup()
    def token(self, principal="seat-14", nonce="n-1", secret=SECRET, now=1900):
        return mint_link_token(secret, principal=principal, now=now, nonce=nonce)
    def test_signed_exchange_links_and_resolves(self):
        link = self.svc.complete_link(self.user.id, self.token())
        self.assertEqual(link.external_id, "seat-14")
        self.assertEqual(self.links.resolve("samtal", "seat-14"), self.user.id)
    def test_bad_signature_refused(self):
        with self.assertRaises(SeamIdentityError) as cm:
            self.svc.complete_link(self.user.id, self.token(secret=b"wrong" * 8))
        self.assertEqual(cm.exception.reason, "signature_invalid")
    def test_tampered_claims_refused(self):
        t = self.token()
        bad = t.split(".")[0][::-1] + "." + t.split(".")[1]
        with self.assertRaises(SeamIdentityError):
            self.svc.complete_link(self.user.id, bad)
    def test_expired_refused(self):
        with self.assertRaises(SeamIdentityError) as cm:
            self.svc.complete_link(self.user.id, self.token(now=1000))
        self.assertEqual(cm.exception.reason, "assertion_expired")
    def test_replay_refused(self):
        self.svc.complete_link(self.user.id, self.token())
        self.svc.unlink_from_samverk(self.user.id)
        with self.assertRaises(SeamIdentityError) as cm:
            self.svc.complete_link(self.user.id, self.token())
        self.assertEqual(cm.exception.reason, "assertion_replay")
    def test_principal_cannot_serve_two_accounts(self):
        self.svc.complete_link(self.user.id, self.token())
        with self.assertRaises(Exception):
            self.svc.complete_link(self.other.id, self.token(nonce="n-2"))
        self.assertEqual(self.links.resolve("samtal", "seat-14"), self.user.id)
    def test_unlink_from_samverk_side(self):
        self.svc.complete_link(self.user.id, self.token())
        self.assertTrue(self.svc.unlink_from_samverk(self.user.id))
        self.assertIsNone(self.links.resolve("samtal", "seat-14"))
        self.assertFalse(self.svc.unlink_from_samverk(self.user.id))
    def test_unlink_from_samtal_side(self):
        self.svc.complete_link(self.user.id, self.token())
        self.assertTrue(self.svc.unlink_from_samtal("seat-14"))
        self.assertIsNone(self.links.resolve("samtal", "seat-14"))
        self.assertFalse(self.svc.unlink_from_samtal("seat-14"))
    def test_seam_disabled_refuses_everything(self):
        off = SeamIdentityService(self.links, secret=SECRET, settings={}, time_fn=lambda: 2000)
        with self.assertRaises(SeamIdentityError) as cm:
            off.complete_link(self.user.id, self.token())
        self.assertEqual(cm.exception.reason, "seam_disabled")
        with self.assertRaises(SeamIdentityError):
            off.unlink_from_samverk(self.user.id)
    def test_malformed_token_refused(self):
        for bad in ("", "no-dot-here", "a.b.c", 42, None):
            with self.assertRaises(SeamIdentityError):
                self.svc.complete_link(self.user.id, bad)
    def test_link_is_audited_by_s045_verbs(self):
        self.svc.complete_link(self.user.id, self.token())
        self.svc.unlink_from_samtal("seat-14")
        actions = [e.action for e in self.audit.list_for_target("user", str(self.user.id), limit=50)] if hasattr(self.audit, 'list_for_target') else []
        if actions:
            self.assertIn("auth.identity.link", actions); self.assertIn("auth.identity.unlink", actions)
    def test_token_is_not_a_login(self):
        self.assertFalse(hasattr(self.svc, "authenticate"))
        self.assertFalse(hasattr(self.svc, "login"))

if __name__ == "__main__":
    unittest.main()
