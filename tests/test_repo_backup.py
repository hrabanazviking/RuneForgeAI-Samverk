"""S-074 acceptance battery: repository backup primitive.

Acceptance (roadmap S-074): single-repo export (bundle +
metadata JSON) used by Part XVII.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import hashlib, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.refs import RefStore
from samverk.repo_backup import BackupError, RepoBackup
from samverk.repositories import RepositoryStore

def git(repo: Path, *args: str, input_bytes=None) -> str:
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@e.c",
                "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@e.c"})
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         input=input_bytes, capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode())
    return out.stdout.decode().strip()

class RepoBackupTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        self.data_root = root / "instance"; self.data_root.mkdir()
        self.dest = root / "exports"
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.other = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.backup = RepoBackup(self.conn, self.data_root, self.accounts, self.repos)
        self.repos.create_repository(self.owner.id, "volmarr", "alpha",
                                     description="the alpha repo")
        self.path = self.repos.path_for("volmarr", "alpha")
        blob = git(self.path, "hash-object", "-w", "--stdin", input_bytes=b"hi\n")
        tree = git(self.path, "mktree", input_bytes=f"100644 blob {blob}\tx.txt\n".encode())
        self.commit = git(self.path, "commit-tree", tree, input_bytes=b"first\n")
        git(self.path, "update-ref", "refs/heads/main", self.commit)

    def test_export_is_a_bundle_plus_metadata_that_agree(self):
        export = self.backup.export_repo(self.owner.id, "volmarr", "alpha", self.dest)
        self.assertTrue(export.bundle_path.is_file())
        meta = json.loads(export.metadata_path.read_text())
        self.assertEqual(meta["format"], "samverk-repo-export/1")
        self.assertEqual(meta["full_name"], "volmarr/alpha")
        self.assertEqual(meta["description"], "the alpha repo")
        self.assertEqual(meta["refs"], {"refs/heads/main": self.commit})
        self.assertEqual(meta["bundle_sha256"],
                         hashlib.sha256(export.bundle_path.read_bytes()).hexdigest())
        self.assertEqual(meta["bundle_bytes"], export.bundle_path.stat().st_size)
        self.assertEqual(export.bundle_sha256, meta["bundle_sha256"])

    def test_the_bundle_restores_the_repository(self):
        export = self.backup.export_repo(self.owner.id, "volmarr", "alpha", self.dest)
        restored = Path(self._td.name) / "restored.git"
        out = subprocess.run(
            ["git", "clone", "--bare", "--no-hardlinks",
             str(export.bundle_path), str(restored)], capture_output=True)
        self.assertEqual(out.returncode, 0, out.stderr.decode())
        self.assertEqual(RefStore(restored).resolve("refs/heads/main"), self.commit)

    def test_export_is_owner_or_admin_only(self):
        with self.assertRaises(BackupError) as caught:
            self.backup.export_repo(self.other.id, "volmarr", "alpha", self.dest)
        self.assertEqual(caught.exception.reason, "permission_denied")
        self.assertFalse(self.dest.exists() and any(self.dest.iterdir()))

    def test_an_export_is_never_overwritten_silently(self):
        self.backup.export_repo(self.owner.id, "volmarr", "alpha", self.dest)
        with self.assertRaises(BackupError) as caught:
            self.backup.export_repo(self.owner.id, "volmarr", "alpha", self.dest)
        self.assertEqual(caught.exception.reason, "export_exists")

    def test_an_empty_repo_is_refused_by_name_not_faked(self):
        # Found by this battery's first run: git bundle refuses
        # an empty bundle. The primitive names that plainly
        # instead of manufacturing a file that restores nothing.
        self.repos.create_repository(self.owner.id, "volmarr", "blank")
        with self.assertRaises(BackupError) as caught:
            self.backup.export_repo(self.owner.id, "volmarr", "blank", self.dest)
        self.assertEqual(caught.exception.reason, "repo_empty")
        self.assertFalse(self.dest.exists() and any(self.dest.iterdir()))

if __name__ == "__main__":
    unittest.main()
