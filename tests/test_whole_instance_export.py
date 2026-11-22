"""S-341 acceptance battery: whole-instance export.

Acceptance (roadmap S-341): one archive: all bare repos,
LFS store, database, and config, with a manifest and
checksums (built on S-074).

Counted with: python3 -m unittest tests.test_whole_instance_export
"""
from __future__ import annotations
import hashlib, io, json, os, subprocess, sys, tarfile, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.config import Config
from samverk.db import schema_version
from samverk.lfs_store import LFSStore, oid_for
from samverk.refs import RefStore
from samverk.repositories import RepositoryStore
from samverk.secrets import Secrets
from samverk.whole_instance_export import (
    FORMAT, MANIFEST_NAME, RepoFact, WholeInstanceExportError,
    WholeInstanceExportService, is_secret_name, plan_instance_export,
    render_whole_instance_export_page, verify_export, verify_manifest)


def git(repo: Path, *args: str, input_bytes=None) -> str:
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@e.c",
                "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@e.c"})
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         input=input_bytes, capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode())
    return out.stdout.decode().strip()


class WholeInstanceExportTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        self.data_root = root / "instance"; self.data_root.mkdir()
        self.dest = root / "exports"
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.admin = self.accounts.register("volmarr", "correct horse battery")
        with self.conn:
            self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?",
                              (self.admin.id,))
        self.other = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.config = Config(data_root=self.data_root,
                             secret_file=self.data_root / "secrets.env")
        self.secrets = Secrets({"INSTANCE_KEY": "never-export-this-value"})
        self.service = WholeInstanceExportService(
            self.conn, self.data_root, self.accounts, self.repos,
            config=self.config, secrets=self.secrets,
            time_fn=lambda: 1700000000.0)
        self.commits = {}
        for name in ("alpha", "beta"):
            self.repos.create_repository(self.admin.id, "volmarr", name)
            path = self.repos.path_for("volmarr", name)
            blob = git(path, "hash-object", "-w", "--stdin",
                       input_bytes=f"{name}\n".encode())
            tree = git(path, "mktree",
                       input_bytes=f"100644 blob {blob}\tx.txt\n".encode())
            commit = git(path, "commit-tree", tree, input_bytes=b"first\n")
            git(path, "update-ref", "refs/heads/main", commit)
            self.commits[name] = commit

    def manifest_of(self, export):
        return json.loads(export.manifest_path.read_text())

    def members_of(self, export):
        with tarfile.open(export.archive_path, "r:gz") as tar:
            return {m.name: tar.extractfile(m).read()
                    for m in tar.getmembers() if m.isfile()}

    # -- pins ------------------------------------------------------
    def test_schema_and_taxonomy_pins_unchanged(self):
        self.assertEqual(schema_version(self.conn), 140)
        self.assertEqual(db.MIGRATIONS[-1][0], 140)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 142)

    # -- pure judgements --------------------------------------------
    def test_secret_names_are_judged_by_name(self):
        self.assertTrue(is_secret_name("secrets.env"))
        self.assertTrue(is_secret_name("tls.key"))
        self.assertTrue(is_secret_name("certs/server-private.pem"))
        self.assertFalse(is_secret_name("tls.crt"))
        self.assertFalse(is_secret_name("samverk.ini"))
        self.assertFalse(is_secret_name(""))

    def test_plan_includes_only_disk_repos_with_refs(self):
        facts = [RepoFact("o/ok", "o", "ok", True, True),
                 RepoFact("o/empty", "o", "empty", True, False),
                 RepoFact("o/gone", "o", "gone", False, False)]
        plan = plan_instance_export(facts)
        self.assertEqual([f.full_name for f in plan.included], ["o/ok"])
        self.assertEqual(dict(plan.excluded),
                         {"o/empty": "repo_empty",
                          "o/gone": "repo_missing_on_disk"})

    def test_verify_manifest_names_every_problem(self):
        manifest = {"entries": [
            {"archive_path": "a", "bytes": 3, "sha256": hashlib.sha256(b"abc").hexdigest()},
            {"archive_path": "b", "bytes": 1, "sha256": "0" * 64}]}
        problems = verify_manifest(manifest, {"a": b"abd", "c": b"x"})
        self.assertTrue(any(p.startswith("a:") for p in problems))
        self.assertTrue(any(p.startswith("b:") for p in problems))
        self.assertTrue(any(p.startswith("c:") for p in problems))
        good = {"entries": [{"archive_path": "a", "bytes": 3, "sha256": hashlib.sha256(b"abc").hexdigest()}]}
        self.assertEqual(verify_manifest(good, {"a": b"abc", MANIFEST_NAME: b"{}"}), [])
    # -- the gate -----------------------------------------------------
    def test_export_is_admin_only(self):
        with self.assertRaises(WholeInstanceExportError) as caught:
            self.service.export_instance(self.other.id, self.dest)
        self.assertEqual(caught.exception.reason, "permission_denied")
        self.assertFalse(self.dest.exists() and any(self.dest.iterdir()))

    def test_unknown_actor_is_refused(self):
        with self.assertRaises(WholeInstanceExportError) as caught:
            self.service.export_instance(99999, self.dest)
        self.assertEqual(caught.exception.reason, "no_such_user")

    # -- the archive ---------------------------------------------------
    def test_archive_holds_repos_database_and_config(self):
        export = self.service.export_instance(self.admin.id, self.dest)
        members = self.members_of(export)
        self.assertIn(MANIFEST_NAME, members)
        self.assertIn("repos/volmarr-alpha.bundle", members)
        self.assertIn("repos/volmarr-alpha.json", members)
        self.assertIn("repos/volmarr-beta.bundle", members)
        self.assertIn("database/samverk.db", members)
        self.assertIn("config/config.json", members)
        manifest = self.manifest_of(export)
        self.assertEqual(manifest["format"], FORMAT)
        self.assertEqual(manifest["repos_included"],
                         ["volmarr/alpha", "volmarr/beta"])
        self.assertEqual(export.repos_included, 2)
        for entry in manifest["entries"]:
            data = members[entry["archive_path"]]
            self.assertEqual(entry["bytes"], len(data))
            self.assertEqual(entry["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(export.archive_sha256,
                         hashlib.sha256(export.archive_path.read_bytes()).hexdigest())

    def test_bundled_repo_restores_from_the_archive(self):
        export = self.service.export_instance(self.admin.id, self.dest)
        members = self.members_of(export)
        bundle = Path(self._td.name) / "alpha.bundle"
        bundle.write_bytes(members["repos/volmarr-alpha.bundle"])
        restored = Path(self._td.name) / "restored.git"
        out = subprocess.run(["git", "clone", "--bare", "--no-hardlinks",
                              str(bundle), str(restored)], capture_output=True)
        self.assertEqual(out.returncode, 0, out.stderr.decode())
        self.assertEqual(RefStore(restored).resolve("refs/heads/main"),
                         self.commits["alpha"])

    def test_database_snapshot_in_the_archive_opens(self):
        export = self.service.export_instance(self.admin.id, self.dest)
        members = self.members_of(export)
        snap = Path(self._td.name) / "snap.db"; snap.write_bytes(members["database/samverk.db"])
        import sqlite3 as s3
        conn = s3.connect(str(snap)); conn.row_factory = s3.Row
        try:
            self.assertEqual(schema_version(conn), 140)
            count = conn.execute("SELECT COUNT(*) FROM repositories").fetchone()[0]
            self.assertEqual(count, 2)
        finally:
            conn.close()

    def test_lfs_objects_ride_the_archive_by_oid(self):
        path = self.repos.path_for("volmarr", "alpha")
        store = LFSStore(path)
        payload = b"large payload bytes"
        oid = oid_for(payload)
        store.put(oid, payload)
        export = self.service.export_instance(self.admin.id, self.dest)
        members = self.members_of(export)
        self.assertEqual(members[f"lfs/volmarr-alpha/{oid}"], payload)
        self.assertEqual(export.lfs_objects, 1)
        self.assertEqual(self.manifest_of(export)["lfs_objects"], 1)

    def test_corrupt_lfs_object_fails_the_export(self):
        path = self.repos.path_for("volmarr", "alpha")
        store = LFSStore(path)
        oid = oid_for(b"good bytes")
        store.put(oid, b"good bytes")
        store.path_for(oid).write_bytes(b"rotted bytes")
        with self.assertRaises(WholeInstanceExportError) as caught:
            self.service.export_instance(self.admin.id, self.dest)
        self.assertEqual(caught.exception.reason, "lfs_corrupt")

    def test_empty_repo_is_excluded_by_name_not_faked(self):
        self.repos.create_repository(self.admin.id, "volmarr", "blank")
        export = self.service.export_instance(self.admin.id, self.dest)
        manifest = self.manifest_of(export)
        self.assertIn({"name": "volmarr/blank", "reason": "repo_empty"},
                      manifest["repos_excluded"])
        self.assertNotIn("repos/volmarr-blank.bundle", self.members_of(export))
        self.assertEqual(export.repos_excluded, 1)

    def test_missing_repo_is_excluded_by_name(self):
        self.repos.create_repository(self.admin.id, "volmarr", "ghost")
        import shutil; shutil.rmtree(self.repos.path_for("volmarr", "ghost"))
        export = self.service.export_instance(self.admin.id, self.dest)
        reasons = {e["name"]: e["reason"]
                   for e in self.manifest_of(export)["repos_excluded"]}
        self.assertEqual(reasons.get("volmarr/ghost"), "repo_missing_on_disk")

    def test_nothing_exportable_is_refused(self):
        self.repos.create_repository(self.admin.id, "volmarr", "blank")
        for name in ("alpha", "beta"):
            git(self.repos.path_for("volmarr", name),
                "update-ref", "-d", "refs/heads/main")
        with self.assertRaises(WholeInstanceExportError) as caught:
            self.service.export_instance(self.admin.id, self.dest)
        self.assertEqual(caught.exception.reason, "nothing_to_export")

    def test_secret_values_never_enter_the_archive(self):
        (self.data_root / "secrets.env").write_text(
            "INSTANCE_KEY=never-export-this-value\n")
        export = self.service.export_instance(self.admin.id, self.dest)
        members = self.members_of(export)
        for name, data in members.items():
            self.assertNotIn(b"never-export-this-value", data, name)
        cfg = json.loads(members["config/config.json"])
        self.assertEqual(cfg["secret_names"], ["INSTANCE_KEY"])
        reasons = {e["name"]: e["reason"]
                   for e in self.manifest_of(export)["excluded"]}
        self.assertEqual(reasons.get("config:secrets.env"),
                         "secret_file_values_never_exported")

    def test_config_file_and_tls_cert_ride_but_key_is_excluded(self):
        (self.data_root / "samverk.ini").write_text(
            "[samverk]\nport = 9999\n")
        cert = Path(self._td.name) / "tls.crt"; cert.write_bytes(b"CERT")
        key = Path(self._td.name) / "tls.key"; key.write_bytes(b"KEYSECRET")
        cfg = Config(data_root=self.data_root, tls_cert_file=cert,
                     tls_key_file=key)
        service = WholeInstanceExportService(
            self.conn, self.data_root, self.accounts, self.repos,
            config=cfg, secrets=self.secrets, time_fn=lambda: 1700000001.0)
        export = service.export_instance(self.admin.id, self.dest)
        members = self.members_of(export)
        self.assertEqual(members["config/samverk.ini"],
                         b"[samverk]\nport = 9999\n")
        self.assertEqual(members["config/tls_cert.pem"], b"CERT")
        for name, data in members.items():
            self.assertNotIn(b"KEYSECRET", data, name)
        reasons = {e["name"]: e["reason"]
                   for e in self.manifest_of(export)["excluded"]}
        self.assertEqual(reasons.get("config:tls.key"),
                         "tls_private_key_never_exported")

    def test_export_is_never_overwritten_silently(self):
        self.service.export_instance(self.admin.id, self.dest)
        with self.assertRaises(WholeInstanceExportError) as caught:
            self.service.export_instance(self.admin.id, self.dest)
        self.assertEqual(caught.exception.reason, "export_exists")

    # -- verification ---------------------------------------------------
    def test_verify_export_passes_a_fresh_archive(self):
        export = self.service.export_instance(self.admin.id, self.dest)
        verdict = verify_export(export.archive_path)
        self.assertTrue(verdict.ok, verdict.problems)
        self.assertEqual(verdict.repos_included, 2)
        self.assertGreater(verdict.entries_checked, 0)

    def test_verify_export_names_a_tampered_member(self):
        export = self.service.export_instance(self.admin.id, self.dest)
        members = self.members_of(export)
        members["database/samverk.db"] = b"tampered"
        bad = Path(self._td.name) / "bad.tar.gz"
        with tarfile.open(bad, "w:gz") as tar:
            for name, data in members.items():
                info = tarfile.TarInfo(name); info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        verdict = verify_export(bad)
        self.assertFalse(verdict.ok)
        self.assertTrue(any("database/samverk.db" in p
                            for p in verdict.problems))

    def test_verify_export_refuses_an_unreadable_archive(self):
        bad = Path(self._td.name) / "junk.tar.gz"; bad.write_bytes(b"junk")
        verdict = verify_export(bad)
        self.assertFalse(verdict.ok)
        self.assertTrue(verdict.problems)

    def test_render_page_states_the_counts(self):
        export = self.service.export_instance(self.admin.id, self.dest)
        page = render_whole_instance_export_page(export)
        self.assertIn("Whole-instance export", page)
        self.assertIn("2 repositories", page)
        self.assertIn(export.archive_sha256, page)


if __name__ == "__main__":
    unittest.main()
