"""S-056 acceptance battery: repository deletion.

Acceptance (roadmap S-056): tombstone, grace period, disk
reclaimed only after; owner-only, sudo mode, audit-logged.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog, verify_chain
from samverk.repo_deletion import RepoDeletion, RepoDeletionError
from samverk.repositories import RepositoryStore

class RepoDeletionTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.data_root = Path(self._td.name)
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.audit = AuditLog(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.other = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts, audit=self.audit)
        self.repo = self.repos.create_repository(self.owner.id, "volmarr", "doomed")
        self.now = [1_000_000.0]
        self.deletion = RepoDeletion(self.conn, self.data_root, self.accounts, self.repos, audit=self.audit, grace_seconds=100, time_fn=lambda: self.now[0])
        self.fresh = lambda uid: uid == self.owner.id

    def test_request_requires_owner_and_sudo(self):
        with self.assertRaises(RepoDeletionError) as c1:
            self.deletion.request(self.other.id, "volmarr", "doomed", self.fresh)
        self.assertEqual(c1.exception.reason, "not_repo_owner")
        with self.assertRaises(RepoDeletionError) as c2:
            self.deletion.request(self.owner.id, "volmarr", "doomed", None)
        self.assertEqual(c2.exception.reason, "sudo_required")
        with self.assertRaises(RepoDeletionError):
            self.deletion.request(self.owner.id, "volmarr", "doomed", lambda uid: False)
        self.assertFalse(self.deletion.is_pending("volmarr", "doomed"))

    def test_grace_disk_untouched_then_reclaimed_after(self):
        pending = self.deletion.request(self.owner.id, "volmarr", "doomed", self.fresh)
        path = self.repos.path_for("volmarr", "doomed")
        self.assertTrue(path.is_dir())
        self.assertFalse(self.deletion.finalize(self.repo.id))  # not due
        self.assertTrue(path.is_dir())
        self.now[0] += 101
        self.assertEqual(self.deletion.execute_due(), [self.repo.id])
        self.assertFalse(path.exists())
        self.assertIsNone(self.repos.get_repository("volmarr", "doomed"))
        ok, bad, _ = verify_chain(self.conn)
        self.assertTrue(ok, bad)
        rows = self.conn.execute("SELECT COUNT(*) c FROM audit_log WHERE action='repo.delete'").fetchone()
        self.assertEqual(rows["c"], 1)

    def test_cancel_restores_whole(self):
        self.deletion.request(self.owner.id, "volmarr", "doomed", self.fresh)
        self.assertTrue(self.deletion.cancel(self.owner.id, "volmarr", "doomed"))
        self.now[0] += 1000
        self.assertEqual(self.deletion.execute_due(), [])
        self.assertIsNotNone(self.repos.get_repository("volmarr", "doomed"))
        self.assertTrue(self.repos.path_for("volmarr", "doomed").is_dir())

    def test_double_request_refused(self):
        self.deletion.request(self.owner.id, "volmarr", "doomed", self.fresh)
        with self.assertRaises(RepoDeletionError) as caught:
            self.deletion.request(self.owner.id, "volmarr", "doomed", self.fresh)
        self.assertEqual(caught.exception.reason, "already_pending")

if __name__ == "__main__":
    unittest.main()
