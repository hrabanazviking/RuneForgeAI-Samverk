"""S-060 acceptance battery: LFS object store.

Acceptance (roadmap S-060): content-addressed layout, dedupe,
integrity verified by oid on write.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.lfs_store import (LFSError, LFSStore, make_pointer,
                               oid_for, parse_pointer)
from samverk.repo_size import measure_path
from samverk.repositories import RepositoryStore

class LFSStoreTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.data_root = Path(self._td.name)
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "lfsrepo")
        self.path = self.repos.path_for("volmarr", "lfsrepo")
        self.store = LFSStore(self.path)
        self.data = b"large-binary-blob" * 500
        self.oid = oid_for(self.data)

    def test_put_read_round_trip_and_layout(self):
        obj = self.store.put(self.oid, self.data, expected_size=len(self.data))
        self.assertFalse(obj.deduped)
        expected = self.path / "lfs" / "objects" / self.oid[:2] / self.oid[2:4] / self.oid
        self.assertTrue(expected.is_file())
        self.assertEqual(self.store.read(self.oid), self.data)
        self.assertTrue(self.store.verify(self.oid))
        self.assertEqual(self.store.size_of(self.oid), len(self.data))

    def test_integrity_mismatch_stores_nothing(self):
        wrong = oid_for(b"different bytes")
        with self.assertRaises(LFSError) as caught:
            self.store.put(wrong, self.data)
        self.assertEqual(caught.exception.reason, "oid_mismatch")
        self.assertFalse(self.store.has(wrong))
        with self.assertRaises(LFSError) as caught:
            self.store.put(self.oid, self.data, expected_size=3)
        self.assertEqual(caught.exception.reason, "size_mismatch")
        self.assertFalse(self.store.has(self.oid))

    def test_dedupe_never_rewrites(self):
        self.store.put(self.oid, self.data)
        path = self.store.path_for(self.oid)
        mtime = path.stat().st_mtime_ns
        again = self.store.put(self.oid, self.data)
        self.assertTrue(again.deduped)
        self.assertEqual(path.stat().st_mtime_ns, mtime)

    def test_bad_oid_and_missing_object(self):
        for bad in ("../escape", "zz" * 32, "AB" * 32, "abc"):
            with self.assertRaises(LFSError):
                self.store.put(bad, b"x")
        with self.assertRaises(LFSError) as caught:
            self.store.read(self.oid)
        self.assertEqual(caught.exception.reason, "object_not_found")
        self.assertFalse(self.store.verify(self.oid))

    def test_pointer_round_trip(self):
        pointer = parse_pointer(make_pointer(self.oid, len(self.data)))
        self.assertEqual((pointer.oid, pointer.size), (self.oid, len(self.data)))
        with self.assertRaises(LFSError):
            parse_pointer(b"just some text\n")

    def test_size_accounting_sees_lfs_bytes(self):
        self.store.put(self.oid, self.data)
        self.assertEqual(measure_path(self.path).lfs_bytes, len(self.data))

if __name__ == "__main__":
    unittest.main()
