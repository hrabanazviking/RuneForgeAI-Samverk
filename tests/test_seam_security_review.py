"""S-379 battery -- seam security review (S-311 extended to the seam)."""
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.seam_security_review import (FINDINGS_FIXED, FINDINGS_NAMED,
                                          SeamSecurityReview)

ON = {"seam.samtal.enabled": True}
SECRET = b"review-secret-for-tests-only"

class SeamSecurityReviewTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "s.db")
        self.audit = AuditLog(self.conn, time_fn=lambda: 5000)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.review = SeamSecurityReview(
            self.conn, self.root, self.accounts, settings=ON, secret=SECRET,
            audit=self.audit, time_fn=lambda: 5000)
        self.report = self.review.run()
    def tearDown(self):
        self.conn.close(); self._td.cleanup()
    def test_every_attack_held(self):
        fell = [f"{o.name}: expected {o.expected}, got {o.observed}"
                for o in self.report.outcomes if not o.held]
        self.assertEqual(fell, [], self.report.summary())
        self.assertTrue(self.report.all_held)
    def test_counts_by_family(self):
        counts = self.report.family_counts()
        self.assertEqual(counts["token_exchange"], (15, 15))
        self.assertEqual(counts["link_unfurling"], (10, 10))
        self.assertEqual(counts["event_posting"], (9, 9))
        self.assertEqual(self.report.total, 34)
    def test_findings_register_is_honest(self):
        self.assertTrue(any(f.startswith("F-1") for f in FINDINGS_FIXED))
        self.assertTrue(any(f.startswith("N-1") for f in FINDINGS_NAMED))
        d = self.report.to_dict()
        self.assertEqual(d["held"], d["total"])
        self.assertEqual(d["findings_fixed"], list(FINDINGS_FIXED))
    def test_refused_attacks_minted_nothing_extra(self):
        # Exactly one honest SSO session (the replay attack's first
        # use) and one honest link (the linkme fixture completion)
        # may stand after the whole battery.
        rows = self.conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()
        self.assertEqual(rows["n"], 1)
        links = self.conn.execute(
            "SELECT COUNT(*) AS n FROM external_identities").fetchone()
        self.assertEqual(links["n"], 2)

if __name__ == "__main__":
    unittest.main()
