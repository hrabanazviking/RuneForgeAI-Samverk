"""S-371 battery — village backup unity."""
import hashlib, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.config import Config
from samverk.repositories import RepositoryStore
from samverk.secrets import Secrets
from samverk.village_backup import VillageBackupError, VillageBackupService, verify_bundle
from samverk.whole_instance_export import WholeInstanceExportError, verify_export

ON = {"seam.samtal.enabled": True}

def git(repo, *args, input_bytes=None):
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@e.c", "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@e.c"})
    out = subprocess.run(["git", f"--git-dir={repo}", *args], input=input_bytes, capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode())
    return out.stdout.decode().strip()

class VillageBackupTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        self.data_root = root / "instance"; self.data_root.mkdir()
        self.dest = root / "bundle"
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn, audit=self.audit)
        self.admin = self.accounts.register("volmarr", "correct horse battery")
        with self.conn:
            self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (self.admin.id,))
        self.other = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        for name in ("alpha", "beta"):
            self.repos.create_repository(self.admin.id, "volmarr", name)
            path = self.repos.path_for("volmarr", name)
            blob = git(path, "hash-object", "-w", "--stdin", input_bytes=f"{name}\n".encode())
            tree = git(path, "mktree", input_bytes=f"100644 blob {blob}\tx.txt\n".encode())
            commit = git(path, "commit-tree", tree, input_bytes=b"first\n")
            git(path, "update-ref", "refs/heads/main", commit)
        self.config = Config(data_root=self.data_root, secret_file=self.data_root / "secrets.env")
        self.secrets = Secrets({"INSTANCE_KEY": "never-export-this-value"})
        self.svc = VillageBackupService(self.conn, self.data_root, self.accounts, self.repos, config=self.config, secrets=self.secrets, settings=ON, audit=self.audit, time_fn=lambda: 1700000000.0)
        self.sections = {"halls": b"hall talk bytes", "members": "the village roll"}
    def tearDown(self):
        self.conn.close()
    def _reason(self, fn, *a, **k):
        with self.assertRaises(VillageBackupError) as ctx: fn(*a, **k)
        return ctx.exception.reason
    def test_bundle_keeps_talk_and_work_in_one_keeping(self):
        bundle = self.svc.build_bundle(self.admin.id, self.sections, self.dest)
        self.assertEqual(bundle.samtal_sections, ("halls", "members"))
        self.assertEqual(bundle.samverk_repos, 2)
        manifest = json.loads(bundle.manifest_path.read_text())
        self.assertEqual(manifest["format"], "samverk-village-bundle/1")
        samverk = manifest["sections"]["samverk"]
        self.assertEqual(samverk["repos_included"], 2)
        self.assertTrue((self.dest / samverk["archive"]).is_file())
        self.assertEqual(verify_bundle(bundle.manifest_path), [])
    def test_samverk_section_is_the_real_s341_export(self):
        bundle = self.svc.build_bundle(self.admin.id, self.sections, self.dest)
        verdict = verify_export(bundle.export_archive)
        self.assertTrue(verdict.ok, verdict.headline)
        manifest = json.loads(bundle.manifest_path.read_text())
        digest = hashlib.sha256(bundle.export_archive.read_bytes()).hexdigest()
        self.assertEqual(manifest["sections"]["samverk"]["sha256"], digest)
    def test_samtal_sections_written_and_checksummed(self):
        bundle = self.svc.build_bundle(self.admin.id, self.sections, self.dest)
        self.assertEqual((self.dest / "samtal-halls").read_bytes(), b"hall talk bytes")
        self.assertEqual((self.dest / "samtal-members").read_text(), "the village roll")
        manifest = json.loads(bundle.manifest_path.read_text())
        halls = [e for e in manifest["sections"]["samtal"] if e["name"] == "halls"][0]
        self.assertEqual(halls["sha256"], hashlib.sha256(b"hall talk bytes").hexdigest())
    def test_tampered_bundle_is_named_not_trusted(self):
        bundle = self.svc.build_bundle(self.admin.id, self.sections, self.dest)
        (self.dest / "samtal-halls").write_bytes(b"forged talk")
        problems = verify_bundle(bundle.manifest_path)
        self.assertEqual(len(problems), 1)
        self.assertIn("halls", problems[0])
    def test_non_admin_refused_by_s341s_own_guard(self):
        with self.assertRaises(WholeInstanceExportError) as ctx:
            self.svc.build_bundle(self.other.id, self.sections, self.dest)
        self.assertEqual(ctx.exception.reason, "permission_denied")
    def test_section_names_and_payloads_judged(self):
        self.assertEqual(self._reason(self.svc.build_bundle, self.admin.id, {"../escape": b"x"}, self.dest), "section_name_invalid")
        self.assertEqual(self._reason(self.svc.build_bundle, self.admin.id, {"samverk": b"x"}, self.dest), "section_name_invalid")
        self.assertEqual(self._reason(self.svc.build_bundle, self.admin.id, {"ok": 42}, self.dest), "section_payload_invalid")
    def test_seam_disabled_refuses(self):
        off = VillageBackupService(self.conn, self.data_root, self.accounts, self.repos, config=self.config, secrets=self.secrets, settings={}, audit=self.audit, time_fn=lambda: 1700000000.0)
        self.assertEqual(self._reason(off.build_bundle, self.admin.id, self.sections, self.dest), "seam_disabled")

if __name__ == "__main__":
    unittest.main()
