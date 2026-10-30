"""S-071 acceptance battery: consistency checker.

Acceptance (roadmap S-071): DB rows ↔ disk repos ↔ LFS objects
reconciled, drift reported, never silently "fixed".

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import hashlib, os, shutil, sqlite3, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.consistency import ConsistencyChecker
from samverk.lfs_store import LFSStore, oid_for
from samverk.repositories import RepositoryStore

def snapshot(root: Path, conn) -> dict:
    files = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink():
            files[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    rows = conn.execute("SELECT COUNT(*) c FROM repositories").fetchone()["c"]
    return {"files": files, "repo_rows": rows}

class ConsistencyTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        self.data_root = root / "instance"; self.data_root.mkdir()
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.checker = ConsistencyChecker(self.conn, self.data_root, self.repos)
        self.repo = self.repos.create_repository(self.owner.id, "volmarr", "alpha")

    def test_a_clean_instance_reports_no_drift(self):
        report = self.checker.check()
        self.assertTrue(report.is_clean, report.drifts)
        self.assertEqual(report.repos_checked, 1)
        self.assertEqual(report.disk_repos_seen, 1)
        self.assertEqual(report.lfs_objects_checked, 0)

    def test_a_row_whose_disk_vanished_is_named(self):
        path = self.repos.path_for("volmarr", "alpha")
        shutil.rmtree(path)
        report = self.checker.check()
        self.assertFalse(report.is_clean)
        kinds = [d.kind for d in report.drifts]
        self.assertIn("repo_missing_on_disk", kinds)
        drift = report.by_kind("repo_missing_on_disk")[0]
        self.assertEqual(drift.repo, "volmarr/alpha")

    def test_an_unregistered_disk_repo_is_named_never_adopted(self):
        stray = self.data_root / "repos" / "volmarr" / "stray.git"
        subprocess_note = stray.mkdir(parents=True)
        (stray / "HEAD").write_text("ref: refs/heads/main\n")
        (stray / "objects").mkdir()
        report = self.checker.check()
        self.assertIn("repo_unregistered_on_disk", [d.kind for d in report.drifts])
        # Reported, not adopted: still no row for it afterwards.
        self.assertIsNone(self.repos.get_repository("volmarr", "stray"))

    def test_lfs_objects_are_reconciled_by_oid(self):
        path = self.repos.path_for("volmarr", "alpha")
        store = LFSStore(path)
        data = b"large-ish payload\n" * 10
        store.put(oid_for(data), data)
        report = self.checker.check()
        self.assertTrue(report.is_clean, report.drifts)
        self.assertEqual(report.lfs_objects_checked, 1)
        # Corrupt the stored bytes: the oid no longer matches.
        obj = store.path_for(oid_for(data))
        obj.write_bytes(b"tampered")
        report = self.checker.check()
        self.assertIn("lfs_object_corrupt", [d.kind for d in report.drifts])

    def test_a_misplaced_lfs_object_is_named(self):
        path = self.repos.path_for("volmarr", "alpha")
        store = LFSStore(path)
        data = b"payload\n"
        oid = oid_for(data)
        store.put(oid, data)
        src = store.path_for(oid)
        wrong = path / "lfs" / "objects" / "ff" / "ff" / oid
        wrong.parent.mkdir(parents=True)
        shutil.move(str(src), str(wrong))
        report = self.checker.check()
        self.assertIn("lfs_object_misplaced", [d.kind for d in report.drifts])

    def test_the_sweep_fixes_nothing(self):
        # Plant two kinds of drift, snapshot everything, sweep,
        # and prove byte-for-byte that nothing was "helpfully"
        # repaired, adopted, or deleted.
        path = self.repos.path_for("volmarr", "alpha")
        stray = self.data_root / "repos" / "volmarr" / "stray.git"
        stray.mkdir(parents=True); (stray / "HEAD").write_text("ref: x\n")
        (stray / "objects").mkdir()
        store = LFSStore(path); data = b"payload\n"; oid = oid_for(data)
        store.put(oid, data); store.path_for(oid).write_bytes(b"tampered")
        before = snapshot(self.data_root, self.conn)
        report = self.checker.check()
        self.assertFalse(report.is_clean)
        after = snapshot(self.data_root, self.conn)
        # The DB file itself may gain WAL bookkeeping from reads;
        # repository content and rows — the stores reconciled —
        # must be identical.
        repo_files_before = {k: v for k, v in before["files"].items() if k.startswith("repos/")}
        repo_files_after = {k: v for k, v in after["files"].items() if k.startswith("repos/")}
        self.assertEqual(repo_files_before, repo_files_after)
        self.assertEqual(before["repo_rows"], after["repo_rows"])

if __name__ == "__main__":
    unittest.main()
