"""S-061 acceptance battery: LFS batch API.

Acceptance (roadmap S-061): upload/download actions with
expiring signed URLs; real `git-lfs` client round-trip.

The round-trip drives the stock git-lfs client (installed on
this machine) against Samverk's own LFS endpoint handler —
no mock client anywhere in the loop.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import json, shutil, subprocess, sys, tempfile, threading, unittest, urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.lfs_api import LFSApi, LFSApiError, make_lfs_handler
from samverk.lfs_store import LFSStore, oid_for
from samverk.repositories import RepositoryStore

KEY = b"test-signing-key-not-a-real-secret"

class BatchTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.data_root = Path(self._td.name)
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.stranger = self.accounts.register("mallory", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "lfsrepo",
                                     visibility="private")
        self.clock = [1_700_000_000]
        self.api = LFSApi(self.conn, self.data_root, self.accounts, self.repos,
                          KEY, time_fn=lambda: self.clock[0])
        self.data = b"payload-bytes" * 100
        self.oid = oid_for(self.data)
        self.store = LFSStore(self.repos.path_for("volmarr", "lfsrepo"))

    def _batch(self, actor, op, objects, repo="lfsrepo"):
        return self.api.batch(actor, "volmarr", repo,
                              {"operation": op, "objects": objects},
                              base_url="http://testserver")

    def test_upload_actions_then_download_round_trip(self):
        answer = self._batch(self.owner.id, "upload",
                             [{"oid": self.oid, "size": len(self.data)}])
        entry = answer["objects"][0]
        up = entry["actions"]["upload"]["href"].rsplit("/", 1)[1]
        ver = entry["actions"]["verify"]["href"].rsplit("/", 1)[1]
        self.api.accept_upload(up, self.data)
        self.assertEqual(
            self.api.accept_verify(ver, {"oid": self.oid, "size": len(self.data)}),
            {"oid": self.oid, "size": len(self.data)})
        answer = self._batch(self.owner.id, "download",
                             [{"oid": self.oid, "size": len(self.data)}])
        down = answer["objects"][0]["actions"]["download"]["href"].rsplit("/", 1)[1]
        self.assertEqual(self.api.serve_download(down), self.data)

    def test_present_object_gets_no_upload_actions(self):
        self.store.put(self.oid, self.data)
        answer = self._batch(self.owner.id, "upload",
                             [{"oid": self.oid, "size": len(self.data)}])
        self.assertNotIn("actions", answer["objects"][0])

    def test_missing_download_object_is_per_object_404(self):
        answer = self._batch(self.owner.id, "download",
                             [{"oid": self.oid, "size": 1}])
        self.assertEqual(answer["objects"][0]["error"]["code"], 404)

    def test_signed_urls_expire_and_resist_tampering(self):
        answer = self._batch(self.owner.id, "upload",
                             [{"oid": self.oid, "size": len(self.data)}])
        token = answer["objects"][0]["actions"]["upload"]["href"].rsplit("/", 1)[1]
        with self.assertRaises(LFSApiError) as caught:
            self.api.accept_upload(token + "x", self.data)
        self.assertEqual(caught.exception.reason, "token_invalid")
        self.clock[0] += 3601
        with self.assertRaises(LFSApiError) as caught:
            self.api.accept_upload(token, self.data)
        self.assertEqual(caught.exception.reason, "token_expired")
        # A download token cannot upload, even unexpired.
        self.clock[0] -= 3601
        dl = self.api.mint_action("volmarr/lfsrepo", self.oid, "download",
                                  len(self.data))
        with self.assertRaises(LFSApiError):
            self.api.accept_upload(dl, self.data)

    def test_permissions_come_from_s054(self):
        with self.assertRaises(LFSApiError) as caught:
            self._batch(self.stranger.id, "upload",
                        [{"oid": self.oid, "size": 1}])
        self.assertEqual(caught.exception.status, 404)  # private = not there
        with self.assertRaises(LFSApiError):
            self._batch(None, "download", [{"oid": self.oid, "size": 1}])
        with self.assertRaises(LFSApiError):
            self.api.batch(self.owner.id, "volmarr", "lfsrepo",
                           {"operation": "upload", "objects": [{"oid": "bad", "size": 1}]},
                           base_url="http://t")


@unittest.skipUnless(shutil.which("git-lfs") or shutil.which("git"),
                     "git required")
class RealClientRoundTrip(unittest.TestCase):
    """The literal acceptance: a stock git-lfs client pushes and
    pulls a real object through Samverk's endpoint handler."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        self.data_root = root / "instance"
        # The endpoint handler serves from worker threads, so this
        # harness opens its connection cross-thread (a threaded
        # server's deployment wiring must do the same — sqlite's
        # default is same-thread only).
        import sqlite3
        (self.data_root).mkdir(parents=True, exist_ok=True)
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
        api = LFSApi(self.conn, self.data_root, self.accounts, self.repos, KEY)
        handler = make_lfs_handler(api, lambda headers: self.owner.id)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.shutdown)
        self.lfs_url = f"http://127.0.0.1:{self.port}/volmarr/lfsrepo/info/lfs"
        self.work = root / "work"

    def _git(self, cwd, *args, check=True):
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                                text=True, timeout=120)
        if check and result.returncode != 0:
            raise AssertionError(f"git {args} failed: {result.stdout} {result.stderr}")
        return result

    def test_git_lfs_push_and_pull(self):
        if subprocess.run(["git", "lfs", "version"], capture_output=True).returncode != 0:
            self.skipTest("git-lfs client not installed on this machine")
        payload = bytes(range(256)) * 4096  # 1 MiB of known bytes
        repo = self.work / "src"; repo.mkdir(parents=True)
        self._git(repo, "init", "-q", "-b", "main")
        self._git(repo, "config", "user.email", "t@example.invalid")
        self._git(repo, "config", "user.name", "Battery")
        self._git(repo, "lfs", "install", "--local")
        (repo / ".gitattributes").write_text("*.bin filter=lfs diff=lfs merge=lfs -text\n")
        (repo / "big.bin").write_bytes(payload)
        self._git(repo, "add", ".gitattributes", "big.bin")
        self._git(repo, "commit", "-qm", "big file")
        bare = self.work / "origin.git"
        self._git(self.work, "init", "-q", "--bare", str(bare))
        self._git(repo, "remote", "add", "origin", str(bare))
        self._git(repo, "config", "lfs.url", self.lfs_url)
        self._git(repo, "config", "lfs.locksverify", "false")
        push = self._git(repo, "lfs", "push", "--all", "origin", check=False)
        self.assertEqual(push.returncode, 0, push.stdout + push.stderr)
        # The object really landed in Samverk's store, verified by oid.
        store = LFSStore(self.repos.path_for("volmarr", "lfsrepo"))
        self.assertTrue(store.verify(oid_for(payload)))
        # Pull it back into a fresh repo through the batch API.
        repo2 = self.work / "dst"; repo2.mkdir()
        self._git(repo2, "init", "-q", "-b", "main")
        self._git(repo2, "config", "user.email", "t@example.invalid")
        self._git(repo2, "config", "user.name", "Battery")
        self._git(repo2, "lfs", "install", "--local")
        self._git(repo2, "config", "lfs.url", self.lfs_url)
        self._git(repo2, "remote", "add", "src", str(repo))
        self._git(repo2, "fetch", "-q", "src", "main")
        # Checkout runs the LFS smudge filter: the pointer becomes
        # real bytes only by downloading through Samverk's batch
        # API — repo2 has no other source for this object.
        self._git(repo2, "checkout", "-q", "-b", "main", "FETCH_HEAD")
        self.assertEqual((repo2 / "big.bin").read_bytes(), payload)

if __name__ == "__main__":
    unittest.main()
