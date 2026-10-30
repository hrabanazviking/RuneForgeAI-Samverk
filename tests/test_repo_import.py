"""S-069 acceptance battery: import by clone URL.

Acceptance (roadmap S-069): any public git URL becomes a
repo; private import via token credential helper, never
logged.

The interop proof serves a real source repository through a
real `git daemon` and imports from its `git://` address —
no mocks on the transport.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import os, socket, subprocess, sys, tempfile, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.proc import ProcRefused, run_git
from samverk.refs import RefStore
from samverk.repo_import import ImportService, RepoImportError
from samverk.repositories import RepositoryStore

def git(repo: Path, *args: str, input_bytes: bytes | None = None) -> str:
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@e.c",
                "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@e.c"})
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         input=input_bytes, capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode())
    return out.stdout.decode().strip()

def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]

class ImportTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        # The source repository, served by git daemon.
        self.serve_root = root / "serve"; self.serve_root.mkdir()
        self.src = self.serve_root / "src.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(self.src)],
                       check=True, capture_output=True)
        blob = git(self.src, "hash-object", "-w", "--stdin", input_bytes=b"hi\n")
        tree = git(self.src, "mktree",
                   input_bytes=f"100644 blob {blob}\tx.txt\n".encode())
        self.commit = git(self.src, "commit-tree", tree, input_bytes=b"first\n")
        git(self.src, "update-ref", "refs/heads/main", self.commit)
        self.port = free_port()
        self.daemon = subprocess.Popen(
            ["git", "daemon", "--export-all", "--reuseaddr",
             "--listen=127.0.0.1", f"--port={self.port}",
             f"--base-path={self.serve_root}", str(self.serve_root)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.daemon.terminate)
        deadline = time.time() + 10
        while True:
            try:
                with socket.create_connection(("127.0.0.1", self.port), 0.5):
                    break
            except OSError:
                if time.time() > deadline:
                    raise
                time.sleep(0.1)
        self.url = f"git://127.0.0.1:{self.port}/src.git"
        # The Samverk instance doing the importing.
        self.data_root = root / "instance"; self.data_root.mkdir()
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.other = self.accounts.register("yrsa", "correct horse battery")
        self.audit = AuditLog(self.conn)
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts,
                                     audit=self.audit)
        self.imports = ImportService(self.conn, self.data_root, self.accounts,
                                     self.repos, audit=self.audit)

    def test_public_url_imports_to_a_real_repository(self):
        created = self.imports.import_repository(
            self.owner.id, "volmarr", "imported", self.url)
        self.assertEqual(created.visibility, "private")
        self.assertEqual(created.default_branch, "main")
        path = self.repos.path_for("volmarr", "imported")
        self.assertEqual(RefStore(path).resolve("refs/heads/main"), self.commit)
        rows = self.conn.execute(
            "SELECT detail FROM audit_log WHERE action = 'repo.create'"
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertIn("127.0.0.1", rows[0]["detail"])
        self.assertIn('"import":"clone"', rows[0]["detail"])

    def test_url_law_refuses_local_credentials_and_flag_shapes(self):
        for bad in ("file:///tmp/x.git", "/tmp/x.git", "../x.git",
                    "ext::sh -c id", "ftp://host/x.git",
                    "https://user:pass@host/x.git",
                    "https://host/x.git#frag", "https://host",
                    "git://host", "--upload-pack=touch /tmp/x",
                    "https://host/x y.git", ""):
            with self.assertRaises(RepoImportError, msg=repr(bad)) as caught:
                self.imports.import_repository(
                    self.owner.id, "volmarr", "nope", bad)
            self.assertEqual(caught.exception.reason, "clone_url_invalid",
                             msg=repr(bad))
        self.assertIsNone(self.repos.get_repository("volmarr", "nope"))

    def test_generic_clone_stays_refused_outside_the_seam(self):
        with self.assertRaises(ProcRefused):
            run_git(["clone", self.url, "/tmp/elsewhere"])

    def test_only_the_owner_can_import_and_names_cannot_collide(self):
        with self.assertRaises(RepoImportError) as caught:
            self.imports.import_repository(
                self.other.id, "volmarr", "imported", self.url)
        self.assertEqual(caught.exception.reason, "not_repo_owner")
        self.imports.import_repository(self.owner.id, "volmarr", "imported",
                                       self.url)
        with self.assertRaises(RepoImportError) as caught:
            self.imports.import_repository(
                self.owner.id, "volmarr", "imported", self.url)
        self.assertEqual(caught.exception.reason, "repo_taken")

    def test_a_failed_clone_leaves_no_row_and_no_directory(self):
        missing = f"git://127.0.0.1:{self.port}/ghost.git"
        with self.assertRaises(RepoImportError) as caught:
            self.imports.import_repository(
                self.owner.id, "volmarr", "ghost", missing,
                token="TOPSECRET-TOKEN-123")
        self.assertEqual(caught.exception.reason, "clone_failed")
        self.assertNotIn("TOPSECRET", str(caught.exception))
        self.assertIsNone(self.repos.get_repository("volmarr", "ghost"))
        self.assertFalse(self.repos.path_for("volmarr", "ghost").exists())

    def test_the_token_is_never_logged_stored_or_audited(self):
        token = "TOPSECRET-TOKEN-123"
        self.imports.import_repository(
            self.owner.id, "volmarr", "imported", self.url, token=token)
        db_bytes = (self.data_root / "samverk.db").read_bytes()
        self.assertNotIn(token.encode(), db_bytes)
        details = " ".join(
            r["detail"] or "" for r in self.conn.execute(
                "SELECT detail FROM audit_log").fetchall())
        self.assertNotIn(token, details)
        self.assertEqual(
            RefStore(self.repos.path_for("volmarr", "imported"))
            .resolve("refs/heads/main"), self.commit)

if __name__ == "__main__":
    unittest.main()
