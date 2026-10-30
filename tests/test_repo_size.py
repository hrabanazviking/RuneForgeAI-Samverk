"""S-058 acceptance battery: repository size accounting.

Acceptance (roadmap S-058): object store + LFS + assets
measured and shown to owners and admins.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.repo_size import RepoSizeAccounting, SizeError, measure_path
from samverk.repositories import RepositoryStore

class SizeTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.data_root = Path(self._td.name)
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.other = self.accounts.register("yrsa", "correct horse battery")
        self.admin = self.accounts.register("adminuser", "correct horse battery")
        with self.conn:
            self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (self.admin.id,))
        self.admin = self.accounts.get_by_id(self.admin.id)
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.repo = self.repos.create_repository(self.owner.id, "volmarr", "sized", visibility="private")
        self.sizes = RepoSizeAccounting(self.conn, self.data_root, self.accounts, self.repos)
        self.path = self.repos.path_for("volmarr", "sized")

    def test_categories_sum_to_total_and_lfs_is_counted(self):
        lfs_obj = self.path / "lfs" / "objects" / "ab" / "cd" / "deadbeef"
        lfs_obj.parent.mkdir(parents=True)
        lfs_obj.write_bytes(b"x" * 1234)
        size = self.sizes.size_for(self.owner.id, "volmarr", "sized")
        self.assertEqual(size.lfs_bytes, 1234)
        self.assertEqual(size.total_bytes, size.git_objects_bytes + size.lfs_bytes + size.other_bytes)
        self.assertGreater(size.total_bytes, 1234)
        self.assertGreater(size.file_count, 0)
        self.assertEqual(size.full_name, "volmarr/sized")

    def test_git_objects_grow_with_real_content(self):
        before = self.sizes.size_for(self.owner.id, "volmarr", "sized")
        payload = self.data_root / "payload.bin"
        payload.write_bytes(b"y" * 5000)
        subprocess.run(["git", f"--git-dir={self.path}", "hash-object", "-w", str(payload)], capture_output=True, check=True)
        after = self.sizes.size_for(self.owner.id, "volmarr", "sized")
        self.assertGreater(after.git_objects_bytes, before.git_objects_bytes)

    def test_shown_to_owner_and_admin_only(self):
        self.assertEqual(self.sizes.size_for(self.admin.id, "volmarr", "sized").full_name, "volmarr/sized")
        with self.assertRaises(SizeError) as caught:
            self.sizes.size_for(self.other.id, "volmarr", "sized")
        self.assertEqual(caught.exception.reason, "permission_denied")
        listed = self.sizes.sizes_for_owner(self.owner.id, "volmarr")
        self.assertEqual([s.full_name for s in listed], ["volmarr/sized"])

    def test_missing_repo_is_named_and_empty_dir_measures_zero(self):
        with self.assertRaises(SizeError) as caught:
            self.sizes.size_for(self.owner.id, "volmarr", "ghost")
        self.assertEqual(caught.exception.reason, "no_such_repo")
        empty = measure_path(self.data_root / "nope")
        self.assertEqual((empty.total_bytes, empty.file_count), (0, 0))

if __name__ == "__main__":
    unittest.main()
