"""S-062 acceptance battery: LFS locking.

Acceptance (roadmap S-062): lock/unlock/list per the LFS
spec; git-lfs client interop test.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import shutil, sqlite3, subprocess, sys, tempfile, threading, unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.lfs_api import LFSApi, make_lfs_handler
from samverk.lfs_locks import LFSLockError, LFSLocking
from samverk.repositories import RepositoryStore

class LockTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.data_root = Path(self._td.name)
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.other = self.accounts.register("mallory", "correct horse battery")
        self.admin = self.accounts.register("adminuser", "correct horse battery")
        with self.conn:
            self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?",
                              (self.admin.id,))
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "lfsrepo",
                                     visibility="public")
        self.locks = LFSLocking(self.conn, self.data_root, self.accounts,
                                self.repos)

    def test_lock_unlock_cycle_and_conflict(self):
        created = self.locks.lock(self.owner.id, "volmarr", "lfsrepo", "big.bin")
        self.assertEqual(created["owner"]["name"], "volmarr")
        self.assertEqual(created["path"], "big.bin")
        with self.assertRaises(LFSLockError) as caught:
            self.locks.lock(self.admin.id, "volmarr", "lfsrepo", "big.bin")
        self.assertEqual(caught.exception.reason, "already_locked")
        self.assertEqual(caught.exception.existing["id"], created["id"])
        with self.assertRaises(LFSLockError) as caught:
            self.locks.unlock(self.admin.id, "volmarr", "lfsrepo", created["id"])
        self.assertEqual(caught.exception.reason, "not_lock_owner")
        released = self.locks.unlock(self.owner.id, "volmarr", "lfsrepo",
                                     created["id"])
        self.assertEqual(released["id"], created["id"])
        self.assertEqual(self.locks.list_locks(self.owner.id, "volmarr", "lfsrepo"), [])

    def test_verify_splits_ours_and_theirs(self):
        self.locks.lock(self.owner.id, "volmarr", "lfsrepo", "a.bin")
        self.locks.lock(self.admin.id, "volmarr", "lfsrepo", "b.bin")
        split = self.locks.verify(self.owner.id, "volmarr", "lfsrepo")
        self.assertEqual([l["path"] for l in split["ours"]], ["a.bin"])
        self.assertEqual([l["path"] for l in split["theirs"]], ["b.bin"])

    def test_admin_force_unlock_and_bad_paths(self):
        created = self.locks.lock(self.owner.id, "volmarr", "lfsrepo", "a.bin")
        self.locks.unlock(self.admin.id, "volmarr", "lfsrepo", created["id"],
                          force=True)
        self.assertEqual(self.locks.list_locks(self.owner.id, "volmarr", "lfsrepo"), [])
        for bad in ("", "/abs.bin", "../escape.bin", "a\\b"):
            with self.assertRaises(LFSLockError):
                self.locks.lock(self.owner.id, "volmarr", "lfsrepo", bad)

    def test_list_filters(self):
        self.locks.lock(self.owner.id, "volmarr", "lfsrepo", "a.bin")
        self.locks.lock(self.owner.id, "volmarr", "lfsrepo", "b.bin")
        self.assertEqual(
            [l["path"] for l in self.locks.list_locks(
                self.owner.id, "volmarr", "lfsrepo", path="b.bin")], ["b.bin"])

    def test_write_needed_to_lock(self):
        self.repos.create_repository(self.other.id, "mallory", "priv",
                                     visibility="private")
        with self.assertRaises(LFSLockError) as caught:
            self.locks.lock(self.owner.id, "mallory", "priv", "a.bin")
        self.assertEqual(caught.exception.status, 404)


@unittest.skipUnless(shutil.which("git-lfs"), "git-lfs client not installed")
class RealClientLockInterop(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        self.data_root = root / "instance"
        self.data_root.mkdir(parents=True)
        self.conn = sqlite3.connect(
            str(self.data_root / "samverk.db"), timeout=5.0,
            check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        db.migrate(self.conn)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "lfsrepo",
                                     visibility="public")
        api = LFSApi(self.conn, self.data_root, self.accounts, self.repos, b"k")
        locks = LFSLocking(self.conn, self.data_root, self.accounts, self.repos)
        handler = make_lfs_handler(api, lambda h: self.owner.id, locks=locks)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.shutdown)
        self.work = root / "work"; self.work.mkdir()

    def _git(self, cwd, *args, check=True):
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                                text=True, timeout=120)
        if check and result.returncode != 0:
            raise AssertionError(f"git {args} failed: {result.stdout} {result.stderr}")
        return result

    def test_git_lfs_lock_unlock(self):
        repo = self.work / "src"; repo.mkdir()
        self._git(repo, "init", "-q", "-b", "main")
        self._git(repo, "config", "user.email", "t@example.invalid")
        self._git(repo, "config", "user.name", "Battery")
        self._git(repo, "lfs", "install", "--local")
        (repo / ".gitattributes").write_text(
            "*.bin filter=lfs diff=lfs merge=lfs -text\n")
        (repo / "big.bin").write_bytes(b"z" * 100)
        self._git(repo, "add", ".gitattributes", "big.bin")
        self._git(repo, "commit", "-qm", "tracked file")
        self._git(repo, "config", "lfs.url",
                  f"http://127.0.0.1:{self.port}/volmarr/lfsrepo/info/lfs")
        locked = self._git(repo, "lfs", "lock", "big.bin")
        self.assertIn("big.bin", locked.stdout + locked.stderr)
        listed = self._git(repo, "lfs", "locks")
        self.assertIn("big.bin", listed.stdout)
        unlocked = self._git(repo, "lfs", "unlock", "big.bin")
        self.assertIn("big.bin", unlocked.stdout + unlocked.stderr)
        listed = self._git(repo, "lfs", "locks")
        self.assertNotIn("big.bin", listed.stdout)

if __name__ == "__main__":
    unittest.main()
