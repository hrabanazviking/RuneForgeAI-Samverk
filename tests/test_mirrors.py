"""S-070 acceptance battery: mirror storage layout.

Acceptance (roadmap S-070): mirrors are ordinary bare repos
plus a mirror record; no second storage engine.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import os, socket, subprocess, sys, tempfile, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.mirrors import MirrorError, MirrorService
from samverk.refs import RefStore
from samverk.repo_size import RepoSizeAccounting
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

def make_source(base: Path, name: str = "src.git") -> tuple[Path, str]:
    src = base / name
    subprocess.run(["git", "init", "--bare", "-b", "main", str(src)],
                   check=True, capture_output=True)
    blob = git(src, "hash-object", "-w", "--stdin", input_bytes=b"hi\n")
    tree = git(src, "mktree", input_bytes=f"100644 blob {blob}\tx.txt\n".encode())
    commit = git(src, "commit-tree", tree, input_bytes=b"first\n")
    git(src, "update-ref", "refs/heads/main", commit)
    return src, commit

def add_commit(repo: Path, parent: str, text: bytes) -> str:
    blob = git(repo, "hash-object", "-w", "--stdin", input_bytes=text)
    tree = git(repo, "mktree", input_bytes=f"100644 blob {blob}\tx.txt\n".encode())
    commit = git(repo, "commit-tree", tree, "-p", parent,
                 input_bytes=b"next\n")
    git(repo, "update-ref", "refs/heads/main", commit)
    return commit

class MirrorTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        outside = root / "outside"; outside.mkdir()
        self.src, self.commit = make_source(outside)
        self.data_root = root / "instance"; self.data_root.mkdir()
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.other = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.mirrors = MirrorService(self.conn, self.data_root,
                                     self.accounts, self.repos)

    def test_a_mirror_is_an_ordinary_repo_plus_a_record(self):
        mirror = self.mirrors.create_mirror(
            self.owner.id, "volmarr", "mir", self.src)
        self.assertEqual(mirror.source_kind, "local")
        self.assertIsNone(mirror.last_status)
        # Ordinary in every way the instance can check: same row,
        # same S-013 path, listed with the owner's other repos,
        # measured by the same S-058 accounting.
        repo = self.repos.get_repository("volmarr", "mir")
        self.assertIsNotNone(repo)
        path = self.repos.path_for("volmarr", "mir")
        self.assertTrue(str(path).startswith(str(self.data_root / "repos")))
        self.assertEqual([r.name for r in self.repos.list_for_owner("volmarr")],
                         ["mir"])
        sizes = RepoSizeAccounting(self.conn, self.data_root, self.accounts,
                                   self.repos)
        self.assertGreaterEqual(
            sizes.size_for(self.owner.id, "volmarr", "mir").total_bytes, 0)
        self.assertTrue(self.mirrors.is_mirror("volmarr", "mir"))

    def test_sync_from_a_local_source_converges_and_repeats(self):
        self.mirrors.create_mirror(self.owner.id, "volmarr", "mir", self.src)
        result = self.mirrors.sync_mirror("volmarr", "mir")
        self.assertEqual(result.status, "ok")
        path = self.repos.path_for("volmarr", "mir")
        self.assertEqual(RefStore(path).resolve("refs/heads/main"), self.commit)
        record = self.mirrors.mirror_for("volmarr", "mir")
        self.assertEqual(record.last_status, "ok")
        self.assertIsNotNone(record.last_sync_at)
        second = add_commit(self.src, self.commit, b"v2\n")
        self.assertEqual(self.mirrors.sync_mirror("volmarr", "mir").status, "ok")
        self.assertEqual(RefStore(path).resolve("refs/heads/main"), second)

    def test_sync_from_a_remote_url(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
        serve = self.src.parent
        daemon = subprocess.Popen(
            ["git", "daemon", "--export-all", "--reuseaddr",
             "--listen=127.0.0.1", f"--port={port}",
             f"--base-path={serve}", str(serve)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.time() + 10
            while True:
                try:
                    with socket.create_connection(("127.0.0.1", port), 0.5):
                        break
                except OSError:
                    if time.time() > deadline:
                        raise
                    time.sleep(0.1)
            self.mirrors.create_mirror(
                self.owner.id, "volmarr", "netmir",
                f"git://127.0.0.1:{port}/src.git")
            self.assertEqual(
                self.mirrors.sync_mirror("volmarr", "netmir").status, "ok")
            path = self.repos.path_for("volmarr", "netmir")
            self.assertEqual(RefStore(path).resolve("refs/heads/main"),
                             self.commit)
        finally:
            daemon.terminate()

    def test_a_failed_sync_is_recorded_and_content_survives(self):
        self.mirrors.create_mirror(self.owner.id, "volmarr", "mir", self.src)
        self.assertEqual(self.mirrors.sync_mirror("volmarr", "mir").status, "ok")
        gone = self.src.parent / "gone.git"   # a source that does not exist
        subprocess.run(["git", "init", "--bare", "-b", "main", str(gone)],
                       check=True, capture_output=True)
        self.mirrors.detach_mirror(self.owner.id, "volmarr", "mir")
        self.mirrors.attach_mirror(self.owner.id, "volmarr", "mir",
                                   "git://127.0.0.1:9/none.git")
        result = self.mirrors.sync_mirror("volmarr", "mir")
        self.assertEqual(result.status, "failed")
        record = self.mirrors.mirror_for("volmarr", "mir")
        self.assertEqual(record.last_status, "failed")
        self.assertTrue(record.last_detail)
        path = self.repos.path_for("volmarr", "mir")
        self.assertEqual(RefStore(path).resolve("refs/heads/main"), self.commit)

    def test_mirror_management_is_owner_only_and_single(self):
        self.repos.create_repository(self.owner.id, "volmarr", "plain")
        self.assertIsNone(self.mirrors.mirror_for("volmarr", "plain"))
        with self.assertRaises(MirrorError):
            self.mirrors.sync_mirror("volmarr", "plain")   # not a mirror
        self.mirrors.attach_mirror(self.owner.id, "volmarr", "plain", self.src)
        with self.assertRaises(MirrorError) as caught:
            self.mirrors.attach_mirror(self.owner.id, "volmarr", "plain",
                                       self.src)
        self.assertEqual(caught.exception.reason, "mirror_exists")
        with self.assertRaises(MirrorError):
            self.mirrors.attach_mirror(self.other.id, "volmarr", "plain",
                                       self.src)
        with self.assertRaises(MirrorError):
            self.mirrors.detach_mirror(self.other.id, "volmarr", "plain")
        self.mirrors.detach_mirror(self.owner.id, "volmarr", "plain")
        self.assertFalse(self.mirrors.is_mirror("volmarr", "plain"))
        self.assertIsNotNone(self.repos.get_repository("volmarr", "plain"))

    def test_source_law(self):
        for bad in ("file:///tmp/x.git", "https://user:pass@h/x.git",
                    "relative/path.git", "", "ftp://h/x.git"):
            with self.assertRaises(MirrorError, msg=repr(bad)):
                self.mirrors.create_mirror(self.owner.id, "volmarr", "m2", bad)
        with self.assertRaises(MirrorError):
            self.mirrors.create_mirror(self.owner.id, "volmarr", "m2",
                                       Path("relative/src.git"))
        with self.assertRaises(MirrorError):
            self.mirrors.create_mirror(self.owner.id, "volmarr", "m2",
                                       Path("/nonexistent/src.git"))

if __name__ == "__main__":
    unittest.main()
