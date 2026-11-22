"""S-330 acceptance battery: mirror credentials.

Acceptance (roadmap S-330): tokens for private sources stored
under S-003's secrets law, referenced by the mirror, never
embedded in stored URLs or logs.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import os, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.mirror_credentials import (
    MirrorCredentialError, MirrorCredentialService)
from samverk.mirrors import MirrorService
from samverk.refs import RefStore
from samverk.repositories import RepositoryStore
from samverk.secrets import Secrets

TOKEN = "s330-private-token-9f8e7d6c"
NAME = "MIRROR_GITHUB_TOKEN"


def git(repo: Path, *args: str, input_bytes: bytes | None = None) -> str:
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@e.c",
                "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@e.c"})
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         input=input_bytes, capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode())
    return out.stdout.decode().strip()


def make_source(base: Path, name: str = "src.git") -> tuple[Path, str]:
    src = base / name
    subprocess.run(["git", "init", "--bare", "-b", "main", str(src)],
                   check=True, capture_output=True)
    blob = git(src, "hash-object", "-w", "--stdin", input_bytes=b"hi\n")
    tree = git(src, "mktree", input_bytes=f"100644 blob {blob}\tx.txt\n".encode())
    commit = git(src, "commit-tree", tree, input_bytes=b"first\n")
    git(src, "update-ref", "refs/heads/main", commit)
    return src, commit


class MirrorCredentialTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        outside = root / "outside"; outside.mkdir()
        self.src, self.commit = make_source(outside)
        self.data_root = root / "instance"; self.data_root.mkdir()
        self.db_path = self.data_root / "samverk.db"
        self.conn = db.init_db(self.db_path)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.other = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.audit = AuditLog(self.conn)
        self.mirrors = MirrorService(self.conn, self.data_root,
                                     self.accounts, self.repos,
                                     audit=self.audit)
        self.creds = MirrorCredentialService(
            self.conn, self.data_root, self.accounts, self.repos,
            audit=self.audit)
        self.mirrors.create_mirror(self.owner.id, "volmarr", "mir", self.src)

    # -- the reference law -------------------------------------------
    def test_set_stores_name_only_never_value(self):
        cred = self.creds.set_credential(self.owner.id, "volmarr", "mir", NAME)
        self.assertEqual(cred.secret_name, NAME)
        self.assertTrue(cred.has_credential)
        row = self.conn.execute(
            "SELECT * FROM repo_mirrors").fetchone()
        self.assertEqual(row["credential_name"], NAME)
        self.assertNotIn(TOKEN, row["source"])
        self.assertNotIn("@", row["source"])
        self.assertNotIn(TOKEN.encode(), self.db_path.read_bytes())

    def test_headline_names_secret_never_value(self):
        cred = self.creds.set_credential(self.owner.id, "volmarr", "mir", NAME)
        self.assertIn(NAME, cred.headline)
        self.assertNotIn(TOKEN, cred.headline)
        self.assertNotIn(TOKEN, repr(cred))

    def test_no_credential_by_default(self):
        cred = self.creds.credential_for("volmarr", "mir")
        self.assertIsNotNone(cred)
        self.assertIsNone(cred.secret_name)
        self.assertFalse(cred.has_credential)
        self.assertIn("no stored credential", cred.headline)

    def test_clear_withdraws_reference(self):
        self.creds.set_credential(self.owner.id, "volmarr", "mir", NAME)
        cred = self.creds.clear_credential(self.owner.id, "volmarr", "mir")
        self.assertIsNone(cred.secret_name)
        row = self.conn.execute(
            "SELECT credential_name FROM repo_mirrors").fetchone()
        self.assertIsNone(row["credential_name"])

    def test_credential_for_non_mirror_is_none(self):
        self.repos.create_repository(self.owner.id, "volmarr", "plain")
        self.assertIsNone(self.creds.credential_for("volmarr", "plain"))
        with self.assertRaises(MirrorCredentialError) as ctx:
            self.creds.set_credential(self.owner.id, "volmarr", "plain", NAME)
        self.assertEqual(ctx.exception.reason, "not_a_mirror")

    # -- guards ---------------------------------------------------------
    def test_only_owner_manages_credential(self):
        with self.assertRaises(MirrorCredentialError) as ctx:
            self.creds.set_credential(self.other.id, "volmarr", "mir", NAME)
        self.assertEqual(ctx.exception.reason, "not_repo_owner")
        self.creds.set_credential(self.owner.id, "volmarr", "mir", NAME)
        with self.assertRaises(MirrorCredentialError):
            self.creds.clear_credential(self.other.id, "volmarr", "mir")

    def test_bad_secret_names_refused(self):
        for bad in ("lowercase", "HAS-DASH", "1LEADING", "", "HAS SPACE",
                    "https://user:tok@host/repo.git", TOKEN):
            with self.assertRaises(MirrorCredentialError) as ctx:
                self.creds.set_credential(self.owner.id, "volmarr", "mir", bad)
            self.assertEqual(ctx.exception.reason, "secret_name_invalid",
                             bad)

    # -- resolution -------------------------------------------------------
    def test_resolve_returns_value_from_secrets_only(self):
        self.creds.set_credential(self.owner.id, "volmarr", "mir", NAME)
        token = self.creds.resolve_token(
            "volmarr", "mir", Secrets({NAME: TOKEN}))
        self.assertEqual(token, TOKEN)

    def test_resolve_without_credential_is_none(self):
        self.assertIsNone(self.creds.resolve_token(
            "volmarr", "mir", Secrets({})))

    def test_named_but_unloaded_secret_fails_closed(self):
        self.creds.set_credential(self.owner.id, "volmarr", "mir", NAME)
        for secrets in (Secrets({}), Secrets({"OTHER": "x"}), None):
            with self.assertRaises(MirrorCredentialError) as ctx:
                self.creds.resolve_token("volmarr", "mir", secrets)
            self.assertEqual(ctx.exception.reason, "credential_unavailable")
            self.assertIn(NAME, str(ctx.exception))
            self.assertNotIn(TOKEN, str(ctx.exception))

    # -- sync ---------------------------------------------------------------
    def test_sync_with_credential_completes(self):
        self.creds.set_credential(self.owner.id, "volmarr", "mir", NAME)
        result = self.creds.sync_mirror(
            "volmarr", "mir", secrets=Secrets({NAME: TOKEN}))
        self.assertEqual(result.status, "ok")
        path = self.repos.path_for("volmarr", "mir")
        self.assertEqual(RefStore(path).resolve("refs/heads/main"), self.commit)

    def test_sync_without_loaded_secret_refuses_before_fetch(self):
        self.creds.set_credential(self.owner.id, "volmarr", "mir", NAME)
        with self.assertRaises(MirrorCredentialError):
            self.creds.sync_mirror("volmarr", "mir", secrets=Secrets({}))
        path = self.repos.path_for("volmarr", "mir")
        self.assertIsNone(RefStore(path).resolve("refs/heads/main"))

    def test_failed_sync_records_no_token_anywhere(self):
        self.mirrors.create_mirror(
            self.owner.id, "volmarr", "bad",
            "https://127.0.0.1:1/private/repo.git")
        self.creds.set_credential(self.owner.id, "volmarr", "bad", NAME)
        result = self.creds.sync_mirror(
            "volmarr", "bad", secrets=Secrets({NAME: TOKEN}))
        self.assertEqual(result.status, "failed")
        self.assertNotIn(TOKEN, result.detail)
        row = self.conn.execute(
            "SELECT * FROM repo_mirrors WHERE source LIKE '%127%'").fetchone()
        for key in row.keys():
            value = row[key]
            if isinstance(value, str):
                self.assertNotIn(TOKEN, value, key)
        self.assertNotIn(TOKEN.encode(), self.db_path.read_bytes())

    def test_audit_names_secret_never_value(self):
        self.creds.set_credential(self.owner.id, "volmarr", "mir", NAME)
        self.creds.sync_mirror(
            "volmarr", "mir", secrets=Secrets({NAME: TOKEN}))
        self.creds.clear_credential(self.owner.id, "volmarr", "mir")
        rows = self.conn.execute(
            "SELECT detail FROM audit_log").fetchall()
        joined = " ".join(r["detail"] or "" for r in rows)
        self.assertIn("mirror_credential.set", joined)
        self.assertIn(NAME, joined)
        self.assertNotIn(TOKEN, joined)
        self.assertNotIn(TOKEN.encode(), self.db_path.read_bytes())

    # -- pins -----------------------------------------------------------------
    def test_schema_133_carries_credential_name(self):
        self.assertEqual(db.schema_version(self.conn), 138)
        cols = [r["name"] for r in self.conn.execute(
            "PRAGMA table_info(repo_mirrors)").fetchall()]
        self.assertIn("credential_name", cols)


if __name__ == "__main__":
    unittest.main()
