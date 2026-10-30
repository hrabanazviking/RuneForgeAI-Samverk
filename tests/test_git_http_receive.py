"""S-079 acceptance battery: smart HTTP receive-pack.

Acceptance (roadmap S-079): the POST is gated by write
permission before advertisement — fail-closed; the
unauthenticated receive-pack hole is a named test
(`test_the_unauthenticated_receive_pack_hole_is_closed`).

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
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db
from samverk.accounts import AccountStore
from samverk.git_http import SmartHttpService, TransportError, pkt_line, PKT_FLUSH
from samverk.repositories import RepositoryStore
from test_git_http_upload import cross_thread_service, seed_commit, GIT_ENV


def make_full_harness(service: SmartHttpService, viewer):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _parts(self):
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
            owner, repo, _ = self._parts()
            svc = parse_qs(urlparse(self.path).query)["service"][0]
            try:
                self._answer(service.advertise(viewer, owner, repo, svc))
            except TransportError as exc:
                self._fail(exc)

        def do_POST(self):
            owner, repo, rest = self._parts()
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            try:
                if rest == ["git-upload-pack"]:
                    self._answer(service.upload_pack(viewer, owner, repo, body))
                elif rest == ["git-receive-pack"]:
                    self._answer(service.receive_pack(viewer, owner, repo, body))
                else:
                    self._fail(TransportError("service_invalid"))
            except TransportError as exc:
                self._fail(exc)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def push_body(old: str, new: str) -> bytes:
    return (pkt_line(f"{old} {new} refs/heads/main\0 report-status\n".encode())
            + PKT_FLUSH)


class ReceivePackTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.data_root = Path(self._td.name)
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.other = self.accounts.register("yrsa", "correct horse battery")
        self.store = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.service = SmartHttpService(
            self.conn, self.data_root, self.accounts, self.store)
        self.store.create_repository(
            self.owner.id, "volmarr", "open", visibility="public")
        self.open_commit = seed_commit(self.store, "volmarr", "open")
        self.store.create_repository(
            self.owner.id, "volmarr", "secret", visibility="private")
        self.secret_commit = seed_commit(self.store, "volmarr", "secret")

    def _main_ref(self, name: str) -> str:
        out = subprocess.run(
            ["git", f"--git-dir={self.store.path_for('volmarr', name)}",
             "rev-parse", "refs/heads/main"],
            capture_output=True, text=True)
        return out.stdout.strip()

    def test_the_unauthenticated_receive_pack_hole_is_closed(self):
        # A public repo is readable by everyone; that must never
        # become push access. Both receive legs refuse anonymous
        # callers, and the ref does not move.
        with self.assertRaises(TransportError) as caught:
            self.service.advertise(None, "volmarr", "open", "git-receive-pack")
        self.assertEqual(caught.exception.reason, "permission_denied")
        with self.assertRaises(TransportError) as caught:
            self.service.receive_pack(
                None, "volmarr", "open",
                push_body(self.open_commit, "0" * 40))
        self.assertEqual(caught.exception.reason, "permission_denied")
        self.assertEqual(self._main_ref("open"), self.open_commit)

    def test_readers_cannot_push_and_private_stays_absent(self):
        with self.assertRaises(TransportError) as caught:
            self.service.receive_pack(
                self.other, "volmarr", "open",
                push_body(self.open_commit, "0" * 40))
        self.assertEqual(caught.exception.reason, "permission_denied")
        for viewer in (None, self.other):
            with self.assertRaises(TransportError) as caught:
                self.service.receive_pack(
                    viewer, "volmarr", "secret",
                    push_body(self.secret_commit, "0" * 40))
            self.assertEqual(caught.exception.reason, "repo_not_found")
        self.assertEqual(self._main_ref("secret"), self.secret_commit)

    def test_owner_receive_advertisement_offers_report_status(self):
        resp = self.service.advertise(
            self.owner, "volmarr", "secret", "git-receive-pack")
        self.assertEqual(
            resp.content_type,
            "application/x-git-receive-pack-advertisement")
        self.assertIn(b"# service=git-receive-pack\n", resp.body)
        self.assertIn(b"report-status", resp.body)

    def test_stock_git_pushes_over_real_http(self):
        server = make_full_harness(
            cross_thread_service(self.data_root), self.owner)
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        env = dict(os.environ); env.update(GIT_ENV)
        env["HOME"] = str(self.data_root)
        dest = self.data_root / "work"
        clone = subprocess.run(
            ["git", "clone",
             f"http://127.0.0.1:{port}/volmarr/secret.git", str(dest)],
            capture_output=True, env=env)
        self.assertEqual(clone.returncode, 0, clone.stderr.decode())
        (dest / "hello.txt").write_bytes(b"pushed over http\n")
        for args in (["add", "hello.txt"],
                     ["commit", "-m", "via smart http"]):
            out = subprocess.run(["git", "-C", str(dest), *args],
                                 capture_output=True, env=env)
            self.assertEqual(out.returncode, 0, out.stderr.decode())
        push = subprocess.run(
            ["git", "-C", str(dest), "push", "origin", "main"],
            capture_output=True, env=env)
        self.assertEqual(push.returncode, 0, push.stderr.decode())
        head = subprocess.run(
            ["git", "-C", str(dest), "rev-parse", "HEAD"],
            capture_output=True, text=True, env=env)
        self.assertEqual(self._main_ref("secret"), head.stdout.strip())
        self.assertNotEqual(self._main_ref("secret"), self.secret_commit)


if __name__ == "__main__":
    unittest.main()
