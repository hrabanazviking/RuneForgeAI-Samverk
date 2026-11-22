"""S-376 battery — embedded-mode polish."""
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.embedded_polish import (EmbeddedPolishError,
    EmbeddedPolishService, explain_refusal)

ON = {"seam.samtal.enabled": True}
PW = "a long enough passphrase"
SECRET = b"polish-secret-for-tests-only"

class EmbeddedPolishTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "s.db")
        self.audit = AuditLog(self.conn, time_fn=lambda: 7000)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.villager = self.accounts.register("villager", PW)
        self.reviewer = self.accounts.register("reviewer", PW)
        self.svc = EmbeddedPolishService(
            self.conn, self.root, self.accounts, settings=ON,
            secret=SECRET, audit=self.audit, time_fn=lambda: 7000)
    def tearDown(self):
        self.conn.close(); self._td.cleanup()
    def test_exercise_runs_the_real_walk_green(self):
        report = self.svc.run_exercise(self.villager, self.reviewer)
        self.assertTrue(report["exercise"]["all_green"],
                        report["exercise"]["summary"])
        self.assertEqual(len(report["exercise"]["steps"]), 12)
        self.assertIsNone(report["exercise"]["failed_step"])
    def test_every_friction_is_logged_and_disposed(self):
        report = self.svc.run_exercise(self.villager, self.reviewer)
        ids = [f["id"] for f in report["frictions"]]
        self.assertEqual(ids, ["bare_reason_codes",
            "panel_no_backup_duty", "friction_ledger_not_in_samtal"])
        for f in report["frictions"]:
            self.assertIn(f["status"], ("fixed", "deferred"))
            self.assertTrue(f["resolution"])
        self.assertEqual(report["fixed"], 1)
        self.assertEqual(report["deferred"], 2)
    def test_the_worst_friction_fix_translates_refusals(self):
        for reason in ("seam_disabled", "not_linked",
                       "link_required", "permission_denied",
                       "not_hall_member", "claim_mismatch",
                       "assertion_expired", "link_unknown",
                       "not_found"):
            out = explain_refusal(reason)
            self.assertEqual(out["reason"], reason)
            self.assertGreater(len(out["plain"]), 30)
        unknown = explain_refusal("some_new_reason")
        self.assertIn("some_new_reason", unknown["plain"])
    def test_ledger_persists_across_service_instances(self):
        self.svc.run_exercise(self.villager, self.reviewer)
        again = EmbeddedPolishService(
            self.conn, self.root, self.accounts, settings=ON,
            secret=SECRET, audit=self.audit, time_fn=lambda: 7000)
        self.assertEqual(len(again.frictions()), 3)
        self.assertTrue(again.report()["exercise"]["all_green"])
    def test_seam_off_refuses_the_exercise_plainly(self):
        off = EmbeddedPolishService(
            self.conn, self.root, self.accounts, settings={},
            secret=SECRET, audit=self.audit, time_fn=lambda: 7000)
        with self.assertRaises(EmbeddedPolishError) as ctx:
            off.run_exercise(self.villager, self.reviewer)
        self.assertEqual(ctx.exception.reason, "seam_disabled")
        self.assertIn("switched off", str(ctx.exception))

if __name__ == "__main__":
    unittest.main()
