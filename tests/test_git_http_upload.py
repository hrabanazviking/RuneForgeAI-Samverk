"""S-078 acceptance battery: smart HTTP upload-pack.

Acceptance (roadmap S-078): the POST is served by
`git upload-pack --stateless-rpc`, side-band progress passed
through — proven here by an unmodified stock git client cloning
and fetching over real HTTP through a harness that routes to the
service (the harness stands in for the server wiring; the viewer
it injects is the credential resolution S-081/S-082 will own).

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk import db
from samverk.accounts import AccountStore
from samverk.git_http import SmartHttpService, TransportError, pkt_line, PKT_FLUSH
from samverk.repositories import RepositoryStore

GIT_ENV = {
    "GIT_AUTHOR_NAME": "A U Thor", "GIT_AUTHOR_EMAIL": "a@example.com",
    "GIT_COMMITTER_NAME": "A U Thor", "GIT_COMMITTER_EMAIL": "a@example.com",
    "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1",
}


def git(repo: Path, *args: str, input_bytes: bytes | None = None) -> str:
    env = dict(os.environ); env.update(GIT_ENV)
    out = subprocess.run(
        ["git", f"--git-dir={repo}", *args], input=input_bytes,
        capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode())
    return out.stdout.decode().strip()


def seed_commit(store: RepositoryStore, owner: str, name: str,
                text: bytes = b"hello\n", parent: str | None = None,
                message: bytes = b"first\n") -> str:
    path = store.path_for(owner, name)
    blob = git(path, "hash-object", "-w", "--stdin", input_bytes=text)
    tree = git(path, "mktree",
               input_bytes=f"100644 blob {blob}\thello.txt\n".encode())
    args = ["commit-tree", tree]
    if parent:
        args += ["-p", parent]
    commit = git(path, *args, input_bytes=message)
    git(path, "update-ref", "refs/heads/main", commit)
    return commit


def cross_thread_service(data_root: Path) -> SmartHttpService:
    """A second service over the same database file, on a
    connection the harness's worker threads may use (the LFS
    batteries' proven pattern: sqlite's default connection is
    same-thread only, and a threaded server's real wiring must
    open its connections cross-thread the same way)."""
    import sqlite3
    conn = sqlite3.connect(
        str(data_root / "samverk.db"), timeout=5.0,
        check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    accounts = AccountStore(conn)
    repos = RepositoryStore(conn, data_root, accounts)
    return SmartHttpService(conn, data_root, accounts, repos)


def make_harness(service: SmartHttpService, viewer):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # silence
            pass

        def _repo_parts(self):
            parts = [p for p in urlparse(self.path).path.split("/") if p]
            return parts[0], parts[1].removesuffix(".git"), parts[2:]

        def _answer(self, resp):
            self.send_response(200)
            self.send_header("Content-Type", resp.content_type)
            self.send_header("Content-Length", str(len(resp.body)))
            self.end_headers()
            self.wfile.write(resp.body)

        def _fail(self, exc: TransportError):
            code = {"repo_not_found": 404,
                    "permission_denied": 403}.get(exc.reason, 400)
            self.send_response(code)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):
            owner, repo, rest = self._repo_parts()
            svc = parse_qs(urlparse(self.path).query)["service"][0]
            try:
                self._answer(service.advertise(viewer, owner, repo, svc))
            except TransportError as exc:
                self._fail(exc)

        def do_POST(self):
            owner, repo, rest = self._repo_parts()
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            try:
                if rest == ["git-upload-pack"]:
                    self._answer(service.upload_pack(viewer, owner, repo, body))
                else:
                    self._fail(TransportError("service_invalid"))
            except TransportError as exc:
                self._fail(exc)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def client_env(home: Path) -> dict:
    env = dict(os.environ); env.update(GIT_ENV); env["HOME"] = str(home)
    return env


class UploadPackTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.data_root = Path(self._td.name)
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.store = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.service = SmartHttpService(
            self.conn, self.data_root, self.accounts, self.store)
        self.store.create_repository(
            self.owner.id, "volmarr", "open", visibility="public")
        self.open_commit = seed_commit(self.store, "volmarr", "open")
        self.store.create_repository(
            self.owner.id, "volmarr", "secret", visibility="private")
        self.secret_commit = seed_commit(self.store, "volmarr", "secret")

    def _clone(self, server, repo: str, dest: Path):
        port = server.server_address[1]
        out = subprocess.run(
            ["git", "clone", f"http://127.0.0.1:{port}/volmarr/{repo}.git",
             str(dest)],
            capture_output=True, env=client_env(self.data_root))
        return out

    def test_stock_git_clones_public_repo_anonymously(self):
        server = make_harness(cross_thread_service(self.data_root), None)
        self.addCleanup(server.shutdown)
        dest = self.data_root / "clone-open"
        out = self._clone(server, "open", dest)
        self.assertEqual(out.returncode, 0, out.stderr.decode())
        self.assertEqual((dest / "hello.txt").read_bytes(), b"hello\n")
        head = subprocess.run(
            ["git", "-C", str(dest), "rev-parse", "HEAD"],
            capture_output=True, text=True, env=client_env(self.data_root))
        self.assertEqual(head.stdout.strip(), self.open_commit)

    def test_stock_git_clones_private_as_owner_then_fetches_update(self):
        server = make_harness(cross_thread_service(self.data_root), self.owner)
        self.addCleanup(server.shutdown)
        dest = self.data_root / "clone-secret"
        out = self._clone(server, "secret", dest)
        self.assertEqual(out.returncode, 0, out.stderr.decode())
        second = seed_commit(
            self.store, "volmarr", "secret", text=b"second\n",
            parent=self.secret_commit, message=b"second commit\n")
        fetched = subprocess.run(
            ["git", "-C", str(dest), "fetch", "origin"],
            capture_output=True, env=client_env(self.data_root))
        self.assertEqual(fetched.returncode, 0, fetched.stderr.decode())
        seen = subprocess.run(
            ["git", "-C", str(dest), "rev-parse", "origin/main"],
            capture_output=True, text=True, env=client_env(self.data_root))
        self.assertEqual(seen.stdout.strip(), second)

    def test_direct_rpc_post_returns_a_real_pack(self):
        want = pkt_line(
            f"want {self.open_commit} multi_ack_detailed "
            "side-band-64k ofs-delta\n".encode())
        body = want + PKT_FLUSH + pkt_line(b"done\n")
        resp = self.service.upload_pack(None, "volmarr", "open", body)
        self.assertEqual(
            resp.content_type, "application/x-git-upload-pack-result")
        self.assertIn(b"PACK", resp.body)

    def test_post_regates_permission_without_advertisement(self):
        body = pkt_line(
            f"want {self.secret_commit}\n".encode()) + PKT_FLUSH
        with self.assertRaises(TransportError) as caught:
            self.service.upload_pack(None, "volmarr", "secret", body)
        self.assertEqual(caught.exception.reason, "repo_not_found")
        with self.assertRaises(TransportError) as caught:
            self.service.upload_pack(self.owner, "volmarr", "nosuch", body)
        self.assertEqual(caught.exception.reason, "repo_not_found")


if __name__ == "__main__":
    unittest.main()
