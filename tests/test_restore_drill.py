"""S-342 acceptance battery: restore drill.

Acceptance (roadmap S-342): export restored onto a scratch
instance; repos clone, users sign in, counts match the
manifest; the drill is a test, not a hope.

Counted with: python3 -m unittest tests.test_restore_drill
"""
from __future__ import annotations
import io, json, os, subprocess, sys, tarfile, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.config import Config
from samverk.db import schema_version
from samverk.lfs_store import LFSStore, oid_for
from samverk.repositories import RepositoryStore
from samverk.secrets import Secrets
from samverk.whole_instance_export import WholeInstanceExportService
from samverk.restore_drill import (ObservedCounts, RestoreDrill,
    RestoreDrillError, compare_drill_counts, operator_steps,
    render_restore_drill_page)

def git(repo: Path, *args: str, input_bytes=None) -> str:
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@e.c",
                "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@e.c"})
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         input=input_bytes, capture_output=True, env=env)
    if out.returncode != 0: raise AssertionError(out.stderr.decode())
    return out.stdout.decode().strip()

class RestoreDrillTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        self.data_root = root / "instance"; self.data_root.mkdir()
        self.dest = root / "exports"
        self.scratch = root / "scratch"
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.admin = self.accounts.register("volmarr", "correct horse battery")
        with self.conn:
            self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (self.admin.id,))
        self.other = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.config = Config(data_root=self.data_root, secret_file=self.data_root / "secrets.env")
        self.secrets = Secrets({"INSTANCE_KEY": "never-export-this-value"})
        self.service = WholeInstanceExportService(self.conn, self.data_root, self.accounts, self.repos, config=self.config, secrets=self.secrets, time_fn=lambda: 1700000000.0)
        self.commits = {}
        for name in ("alpha", "beta"):
            self.repos.create_repository(self.admin.id, "volmarr", name)
            path = self.repos.path_for("volmarr", name)
            blob = git(path, "hash-object", "-w", "--stdin", input_bytes=f"{name}\n".encode())
            tree = git(path, "mktree", input_bytes=f"100644 blob {blob}\tx.txt\n".encode())
            commit = git(path, "commit-tree", tree, input_bytes=b"first\n")
            git(path, "update-ref", "refs/heads/main", commit)
            self.commits[name] = commit
        store = LFSStore(self.repos.path_for("volmarr", "alpha"))
        self.payload = b"large payload bytes"; self.oid = oid_for(self.payload)
        store.put(self.oid, self.payload)
        self.export = self.service.export_instance(self.admin.id, self.dest)
        self.drill = RestoreDrill(time_fn=lambda: 1700000100.0)

    def test_schema_and_taxonomy_pins_unchanged(self):
        self.assertEqual(schema_version(self.conn), 139)
        self.assertEqual(db.MIGRATIONS[-1][0], 139)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 138)

    def test_compare_counts_names_every_mismatch(self):
        manifest = {"repos_included": ["o/a", "o/b"], "repos_excluded": [], "lfs_objects": 1, "entries": [{}] * 5}
        good = ObservedCounts(repos=2, lfs_objects=1, users=2, members=6, repos_in_db=2)
        self.assertEqual(compare_drill_counts(manifest, good, 2), [])
        bad = ObservedCounts(repos=1, lfs_objects=0, users=1, members=5, repos_in_db=1)
        problems = compare_drill_counts(manifest, bad, 2)
        for prefix in ("repos:", "lfs_objects:", "users:", "repos_in_db:", "members:"):
            self.assertTrue(any(p.startswith(prefix) for p in problems), prefix)

    def test_operator_steps_name_secrets_and_key_never_values(self):
        manifest = {"excluded": [{"name": "config:tls.key", "reason": "tls_private_key_never_exported"}, {"name": "config:secrets.env", "reason": "secret_file_values_never_exported"}]}
        steps = operator_steps(manifest, {"secret_names": ["INSTANCE_KEY"]})
        joined = " ".join(steps)
        self.assertIn("INSTANCE_KEY", joined); self.assertIn("tls.key", joined)
        self.assertIn("secrets.env", joined); self.assertNotIn("never-export", joined)

    def test_drill_restores_clones_signs_in_and_counts_match(self):
        report = self.drill.run(self.export.archive_path, self.scratch, "volmarr", "correct horse battery")
        self.assertTrue(report.ok, report.problems)
        self.assertEqual(report.repos_restored, 2)
        self.assertEqual(report.lfs_objects, 1)
        self.assertEqual(report.users, 2)
        self.assertEqual(report.clones, {"volmarr/alpha": self.commits["alpha"], "volmarr/beta": self.commits["beta"]})
        self.assertEqual(report.signed_in_as, "volmarr")
        restored = RepositoryStore(db.init_db(self.scratch / "samverk.db"), self.scratch, AccountStore(db.init_db(self.scratch / "samverk.db")))
        path = restored.path_for("volmarr", "alpha")
        self.assertEqual(LFSStore(path).path_for(self.oid).read_bytes(), self.payload)

    def test_drill_report_names_operator_steps_without_values(self):
        report = self.drill.run(self.export.archive_path, self.scratch, "yrsa", "correct horse battery")
        joined = " ".join(report.operator_steps)
        self.assertIn("INSTANCE_KEY", joined)
        self.assertNotIn("never-export-this-value", joined)
        page = render_restore_drill_page(report)
        self.assertIn("Restore drill", page); self.assertIn("yrsa", page)

    def test_wrong_password_is_a_named_failure_not_a_pass(self):
        report = self.drill.run(self.export.archive_path, self.scratch, "volmarr", "wrong password entirely")
        self.assertFalse(report.ok)
        self.assertTrue(any(p.startswith("sign-in:") for p in report.problems))
        self.assertIsNone(report.signed_in_as)

    def test_no_credentials_means_signin_unproven(self):
        report = self.drill.run(self.export.archive_path, self.scratch)
        self.assertFalse(report.ok)
        self.assertTrue(any("not attempted" in p for p in report.problems))

    def test_excluded_empty_repo_still_drills_clean(self):
        self.repos.create_repository(self.admin.id, "volmarr", "blank")
        dest2 = Path(self._td.name) / "exports2"
        export2 = self.service.export_instance(self.admin.id, dest2)
        scratch2 = Path(self._td.name) / "scratch2"
        report = self.drill.run(export2.archive_path, scratch2, "volmarr", "correct horse battery")
        self.assertTrue(report.ok, report.problems)
        self.assertEqual(report.repos_restored, 2)

    def test_tampered_archive_is_refused_before_restore(self):
        with tarfile.open(self.export.archive_path, "r:gz") as tar:
            members = {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}
        members["database/samverk.db"] = b"tampered"
        bad = Path(self._td.name) / "bad.tar.gz"
        with tarfile.open(bad, "w:gz") as tar:
            for name, data in members.items():
                info = tarfile.TarInfo(name); info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        with self.assertRaises(RestoreDrillError) as caught:
            self.drill.run(bad, self.scratch, "volmarr", "correct horse battery")
        self.assertEqual(caught.exception.reason, "export_unverified")
        self.assertFalse(self.scratch.exists() and any(self.scratch.iterdir()))

    def test_nonempty_scratch_is_refused(self):
        self.scratch.mkdir(); (self.scratch / "live.db").write_bytes(b"x")
        with self.assertRaises(RestoreDrillError) as caught:
            self.drill.run(self.export.archive_path, self.scratch, "volmarr", "correct horse battery")
        self.assertEqual(caught.exception.reason, "scratch_not_empty")

if __name__ == "__main__":
    unittest.main()
