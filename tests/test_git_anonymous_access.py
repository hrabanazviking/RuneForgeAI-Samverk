"""S-083 acceptance battery: anonymous public read + uniform shape.

Acceptance (roadmap S-083): public repos clone without
credentials; private repos never leak existence — the uniform
404/401 shape is decided (in `TransportGate`'s docstring) and
tested here, including byte-equality of the private and
nonexistent answers.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db
from samverk.accounts import AccountStore
from samverk.git_auth import GitAuthenticator
from samverk.git_http import SmartHttpService, TransportGate, WWW_AUTHENTICATE
from samverk.repositories import RepositoryStore
from test_git_basic_auth import basic
from test_git_http_upload import seed_commit
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from samverk.git_http import TransportError
from test_git_http_upload import cross_thread_service


class ShapeTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.data_root = Path(self._td.name)
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.other = self.accounts.register("yrsa", "correct horse battery")
        self.store = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.gate = TransportGate(
            self.store, GitAuthenticator(self.conn, self.accounts))
        self.store.create_repository(
            self.owner.id, "volmarr", "open", visibility="public")
        seed_commit(self.store, "volmarr", "open")
        self.store.create_repository(
            self.owner.id, "volmarr", "secret", visibility="private")
        seed_commit(self.store, "volmarr", "secret")

    def shape(self, decision):
        return (decision.allowed, decision.status,
                decision.reason, decision.challenge)

    def test_anonymous_public_read_is_allowed(self):
        d = self.gate.decide("volmarr", "open", "git-upload-pack", None)
        self.assertTrue(d.allowed)
        self.assertIsNone(d.viewer)

    def test_anonymous_private_and_missing_are_indistinguishable(self):
        private = self.gate.decide("volmarr", "secret", "git-upload-pack", None)
        missing = self.gate.decide("volmarr", "nosuch", "git-upload-pack", None)
        self.assertEqual(self.shape(private), self.shape(missing))
        self.assertEqual(self.shape(private),
                         (False, 401, "credentials_needed", True))
        push = self.gate.decide("volmarr", "open", "git-receive-pack", None)
        self.assertEqual(self.shape(push),
                         (False, 401, "credentials_needed", True))

    def test_bad_credentials_private_and_missing_are_indistinguishable(self):
        bad = basic("volmarr", "wrong horse battery")
        private = self.gate.decide("volmarr", "secret", "git-upload-pack", bad)
        missing = self.gate.decide("volmarr", "nosuch", "git-upload-pack", bad)
        self.assertEqual(self.shape(private), self.shape(missing))
        self.assertEqual(self.shape(private),
                         (False, 404, "repo_not_found", False))

    def test_valid_credentials_open_the_private_door(self):
        d = self.gate.decide(
            "volmarr", "secret", "git-upload-pack",
            basic("volmarr", "correct horse battery"))
        self.assertTrue(d.allowed)
        self.assertEqual(d.viewer.id, self.owner.id)

    def test_strangers_valid_credentials_still_meet_the_uniform_404(self):
        d = self.gate.decide(
            "volmarr", "secret", "git-upload-pack",
            basic("yrsa", "correct horse battery"))
        self.assertEqual(self.shape(d), (False, 404, "repo_not_found", False))

    def test_reader_at_the_write_gate_meets_an_honest_403(self):
        d = self.gate.decide(
            "volmarr", "open", "git-receive-pack",
            basic("yrsa", "correct horse battery"))
        self.assertEqual(self.shape(d),
                         (False, 403, "permission_denied", False))

    def test_bad_credentials_on_a_free_read_are_ignored(self):
        d = self.gate.decide(
            "volmarr", "open", "git-upload-pack",
            basic("volmarr", "wrong horse battery"))
        self.assertTrue(d.allowed)
        self.assertIsNone(d.viewer)


class WireShapeTests(unittest.TestCase):
    """The decided shape on the real wire: a gated harness whose
    401s for private and missing repos are byte-identical."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.data_root = Path(self._td.name)
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.store = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.store.create_repository(
            self.owner.id, "volmarr", "secret", visibility="private")
        seed_commit(self.store, "volmarr", "secret")
        service = cross_thread_service(self.data_root)
        # The gate serving from harness threads needs the same
        # cross-thread connection treatment as the service.
        import sqlite3
        conn2 = sqlite3.connect(
            str(self.data_root / "samverk.db"), timeout=5.0,
            check_same_thread=False)
        conn2.row_factory = sqlite3.Row
        accounts2 = AccountStore(conn2)
        gate = TransportGate(
            RepositoryStore(conn2, self.data_root, accounts2),
            GitAuthenticator(conn2, accounts2))

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                parts = [p for p in urlparse(self.path).path.split("/") if p]
                owner, repo = parts[0], parts[1].removesuffix(".git")
                svc = parse_qs(urlparse(self.path).query)["service"][0]
                decision = gate.decide(
                    owner, repo, svc, self.headers.get("Authorization"))
                if not decision.allowed:
                    self.send_response(decision.status)
                    if decision.challenge:
                        self.send_header("WWW-Authenticate", WWW_AUTHENTICATE)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                try:
                    resp = service.advertise(decision.viewer, owner, repo, svc)
                except TransportError as exc:
                    self.send_response(
                        404 if exc.reason == "repo_not_found" else 403)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", resp.content_type)
                self.send_header("Content-Length", str(len(resp.body)))
                self.end_headers()
                self.wfile.write(resp.body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]

    def _get(self, repo: str):
        url = (f"http://127.0.0.1:{self.port}/volmarr/{repo}.git/"
               "info/refs?service=git-upload-pack")
        try:
            with urllib.request.urlopen(url) as resp:
                return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as err:
            return err.code, err.headers, err.read()

    def test_private_and_missing_401s_are_byte_identical(self):
        code_a, head_a, body_a = self._get("secret")
        code_b, head_b, body_b = self._get("nosuch")
        self.assertEqual(code_a, 401)
        self.assertEqual(code_a, code_b)
        self.assertEqual(head_a.get("WWW-Authenticate"), WWW_AUTHENTICATE)
        self.assertEqual(head_a.get("WWW-Authenticate"),
                         head_b.get("WWW-Authenticate"))
        self.assertEqual(body_a, body_b)


if __name__ == "__main__":
    unittest.main()
