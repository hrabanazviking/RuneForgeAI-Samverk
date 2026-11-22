"""S-374 battery — seam battery (the end-to-end walk)."""
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.seam_battery import SeamWalk

ON = {"seam.samtal.enabled": True}
PW = "a long enough passphrase"
SECRET = b"walk-secret-for-tests-only"
EXPECTED_STEPS = ["link_identity", "enter_by_sso", "push_code",
                  "hall_sees_push", "panel_from_samtal", "open_pr_from_samtal",
                  "hall_sees_pr", "review_approves", "mention_crosses",
                  "unfurl_in_conversation", "merge_lands", "hall_sees_merge"]

class SeamBatteryTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "s.db")
        self.audit = AuditLog(self.conn, time_fn=lambda: 5000)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.villager = self.accounts.register("villager", PW)
        self.reviewer = self.accounts.register("reviewer", PW)
        self.walk = SeamWalk(self.conn, self.root, self.accounts,
                             settings=ON, secret=SECRET, audit=self.audit,
                             time_fn=lambda: 5000)
    def tearDown(self):
        self.conn.close(); self._td.cleanup()
    def test_the_walk_is_all_green(self):
        report = self.walk.run(self.villager, self.reviewer)
        self.assertEqual([s.name for s in report.steps], EXPECTED_STEPS)
        self.assertTrue(report.all_green, report.summary() +
                        " | " + " | ".join(f"{s.name}: {s.detail}" for s in report.steps))
        self.assertIsNone(report.failed_step)
        self.assertIn("all green", report.summary())
    def test_the_walk_lands_real_things(self):
        report = self.walk.run(self.villager, self.reviewer)
        self.assertTrue(report.all_green, report.summary())
        self.assertEqual(report.pr_number, 1)
        self.assertEqual(len(report.hall_cards), 3)
        self.assertTrue(any("merged" in t for t in report.hall_cards))
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM pull_requests").fetchone()
        self.assertEqual(row["n"], 1)
    def test_seam_disabled_walk_fails_at_the_first_step(self):
        off = SeamWalk(self.conn, self.root, self.accounts, settings={},
                       secret=SECRET, audit=self.audit, time_fn=lambda: 5000)
        report = off.run(self.villager, self.reviewer)
        self.assertFalse(report.all_green)
        self.assertEqual(report.failed_step, "link_identity")
        self.assertIn("seam_disabled", report.steps[0].detail)

if __name__ == "__main__":
    unittest.main()
