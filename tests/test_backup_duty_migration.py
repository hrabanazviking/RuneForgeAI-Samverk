"""S-378 battery — migration of the backup duty."""
import subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.backup_duty_migration import (BackupDutyMigrationError,
    BackupDutyMigrationService)
from samverk.mirrors import MirrorService
from samverk.repositories import RepositoryStore

PW = "a long enough passphrase"

def git(path, *args, input_bytes=None):
    return subprocess.run(["git", "-C", str(path), *args],
        input=input_bytes, capture_output=True, check=True).stdout

def make_source(base: Path, name: str) -> Path:
    src = base / name
    subprocess.run(["git", "init", "--bare", "-b", "main",
                    str(src)], capture_output=True, check=True)
    tree = git(src, "mktree", input_bytes=b"").strip().decode()
    commit = git(src, "commit-tree", tree,
                 input_bytes=b"first\n").strip().decode()
    git(src, "update-ref", "refs/heads/main", commit)
    git(src, "update-ref", "refs/heads/dev", commit)
    return src

class BackupDutyMigrationTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "s.db")
        self.audit = AuditLog(self.conn, time_fn=lambda: 3000)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.owner = self.accounts.register("volmarr", PW)
        self.repos = RepositoryStore(self.conn, self.root,
            self.accounts, audit=self.audit, time_fn=lambda: 3000)
        self.mirrors = MirrorService(self.conn, self.root,
            self.accounts, self.repos, audit=self.audit,
            time_fn=lambda: 3000)
        self.svc = BackupDutyMigrationService(self.conn,
            self.root, self.accounts, self.repos,
            audit=self.audit, time_fn=lambda: 3000)
        self.interim = self.root / "interim"
        self.hosted = self.root / "hosted"
        make_source(self.interim, "alpha.git")
        make_source(self.hosted, "alpha.git")
        self.mirrors.create_mirror(self.owner.id, "volmarr",
            "alpha", self.interim / "alpha.git")
        self.mirrors.sync_mirror("volmarr", "alpha")
    def tearDown(self):
        self.conn.close(); self._td.cleanup()
    def test_repoint_moves_syncs_and_verifies_ref_for_ref(self):
        entry = self.svc.repoint(self.owner.id, "volmarr",
            "alpha", interim_prefix=str(self.interim),
            hosted_base=str(self.hosted))
        self.assertEqual(entry["sync_status"], "ok")
        self.assertTrue(entry["verified"], entry["headline"])
        self.assertEqual(entry["source_refs"], 2)
        after = self.mirrors.mirror_for("volmarr", "alpha")
        self.assertEqual(after.source, str(self.hosted / "alpha.git"))
        kept = self.svc.migration_for("volmarr", "alpha")
        self.assertEqual(kept["new_source"], entry["new_source"])
        self.assertTrue(kept["verified"])
    def test_migrate_duty_moves_every_interim_mirror(self):
        report = self.svc.migrate_duty(self.owner.id,
            interim_prefix=str(self.interim),
            hosted_base=str(self.hosted))
        self.assertEqual(report["total"], 1)
        self.assertEqual(report["verified"], 1)
        self.assertEqual(report["failed"], [])
    def test_a_source_outside_the_interim_home_refuses(self):
        self.mirrors.create_mirror(self.owner.id, "volmarr",
            "beta", self.hosted / "alpha.git")
        with self.assertRaises(BackupDutyMigrationError) as ctx:
            self.svc.repoint(self.owner.id, "volmarr", "beta",
                interim_prefix=str(self.interim),
                hosted_base=str(self.hosted))
        self.assertEqual(ctx.exception.reason, "not_interim_source")
    def test_a_plain_repo_has_no_duty_to_migrate(self):
        self.repos.create_repository(self.owner.id, "volmarr", "plain")
        with self.assertRaises(BackupDutyMigrationError) as ctx:
            self.svc.repoint(self.owner.id, "volmarr", "plain",
                interim_prefix=str(self.interim),
                hosted_base=str(self.hosted))
        self.assertEqual(ctx.exception.reason, "not_a_mirror")

if __name__ == "__main__":
    unittest.main()
