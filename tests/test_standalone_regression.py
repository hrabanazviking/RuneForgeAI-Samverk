"""S-377 battery — standalone regression."""
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
ROOT = Path(__file__).resolve().parent.parent
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.standalone_regression import (declared_batteries,
    exercise_standalone, regression_report)

class StandaloneRegressionTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "s.db")
        self.audit = AuditLog(self.conn, time_fn=lambda: 9000)
        self.accounts = AccountStore(self.conn, audit=self.audit)
    def tearDown(self):
        self.conn.close(); self._td.cleanup()
    def test_batteries_are_declared_counted_and_on_disk(self):
        declared = declared_batteries()
        self.assertEqual(declared["total"], 16)
        self.assertEqual(len(declared["part_iv"]), 8)
        self.assertEqual(len(declared["part_xii"]), 8)
        report = regression_report(ROOT)
        self.assertTrue(report["files"]["ok"], report["files"])
        self.assertEqual(report["files"]["declared"], 16)
    def test_the_seam_never_grew_into_the_core(self):
        report = regression_report(ROOT)
        self.assertTrue(report["isolation"]["ok"],
                        report["isolation"]["offenders"])
        self.assertEqual(report["isolation"]["core_checked"], 10)
        self.assertTrue(report["ok"])
    def test_standalone_doors_work_with_no_seam_at_all(self):
        out = exercise_standalone(self.conn, self.root,
            self.accounts, audit=self.audit, time_fn=lambda: 9000)
        self.assertTrue(out["ok"], out["checks"])
        names = [c["name"] for c in out["checks"]]
        self.assertEqual(names, ["register", "password_login",
            "create_repository", "seam_door_refuses_cleanly"])

if __name__ == "__main__":
    unittest.main()
