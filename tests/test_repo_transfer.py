"""S-057 acceptance battery: repository transfer.

Acceptance (roadmap S-057): between users/orgs with recipient
acceptance; redirects left behind.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog, verify_chain
from samverk.repo_transfer import RepoTransfer, TransferError
from samverk.repositories import RepositoryStore

class TransferTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.data_root = Path(self._td.name)
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.audit = AuditLog(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.other = self.accounts.register("yrsa", "correct horse battery")
        self.third = self.accounts.register("tess", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts, audit=self.audit)
        self.repo = self.repos.create_repository(self.owner.id, "volmarr", "gift")
        self.transfer = RepoTransfer(self.conn, self.data_root, self.accounts, self.repos, audit=self.audit)

    def test_nothing_moves_until_recipient_accepts_then_redirect_remains(self):
        self.transfer.initiate(self.owner.id, "volmarr", "gift", "yrsa")
        self.assertIsNotNone(self.repos.get_repository("volmarr", "gift"))
        self.assertIsNone(self.repos.get_repository("yrsa", "gift"))
        moved = self.transfer.accept(self.other.id, "volmarr", "gift")
        self.assertEqual(moved.full_name, "yrsa/gift")
        self.assertIsNone(self.repos.get_repository("volmarr", "gift"))
        self.assertTrue(self.repos.path_for("yrsa", "gift").is_dir())
        self.assertFalse(self.repos.path_for("volmarr", "gift").exists())
        redirect = self.transfer.resolve_redirect("volmarr", "gift")
        self.assertIsNotNone(redirect)
        self.assertEqual(redirect.new_full_name, "yrsa/gift")
        ok, bad, _ = verify_chain(self.conn)
        self.assertTrue(ok, bad)
        rows = self.conn.execute("SELECT COUNT(*) c FROM audit_log WHERE action='repo.transfer'").fetchone()
        self.assertEqual(rows["c"], 1)

    def test_only_recipient_can_accept_or_decline(self):
        self.transfer.initiate(self.owner.id, "volmarr", "gift", "yrsa")
        with self.assertRaises(TransferError) as caught:
            self.transfer.accept(self.third.id, "volmarr", "gift")
        self.assertEqual(caught.exception.reason, "not_recipient")
        self.assertTrue(self.transfer.decline(self.other.id, "volmarr", "gift"))
        self.assertIsNone(self.transfer.pending_for(self.repo.id))
        self.assertIsNotNone(self.repos.get_repository("volmarr", "gift"))

    def test_initiate_guards(self):
        with self.assertRaises(TransferError) as c1:
            self.transfer.initiate(self.other.id, "volmarr", "gift", "tess")
        self.assertEqual(c1.exception.reason, "not_repo_owner")
        with self.assertRaises(TransferError) as c2:
            self.transfer.initiate(self.owner.id, "volmarr", "gift", "ghost")
        self.assertEqual(c2.exception.reason, "no_such_recipient")
        with self.assertRaises(TransferError) as c3:
            self.transfer.initiate(self.owner.id, "volmarr", "gift", "volmarr")
        self.assertEqual(c3.exception.reason, "transfer_to_self")
        self.repos.create_repository(self.other.id, "yrsa", "gift")
        with self.assertRaises(TransferError) as c4:
            self.transfer.initiate(self.owner.id, "volmarr", "gift", "yrsa")
        self.assertEqual(c4.exception.reason, "repo_taken")

    def test_owner_can_cancel(self):
        self.transfer.initiate(self.owner.id, "volmarr", "gift", "yrsa")
        self.assertTrue(self.transfer.cancel(self.owner.id, "volmarr", "gift"))
        with self.assertRaises(TransferError) as caught:
            self.transfer.accept(self.other.id, "volmarr", "gift")
        self.assertEqual(caught.exception.reason, "no_pending_transfer")

if __name__ == "__main__":
    unittest.main()
