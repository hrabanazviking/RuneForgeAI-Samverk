"""S-080 acceptance battery: protocol v2.

Acceptance (roadmap S-080): `Git-Protocol: version=2` honoured,
`ls-refs` command served; interop proven with a
`GIT_TRACE_PACKET` run of stock git.

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
from samverk.git_http import (
    SmartHttpService, TransportError, pkt_line, PKT_DELIMITER, PKT_FLUSH,
    protocol_version_from_header,
)
from samverk.repositories import RepositoryStore
from test_git_http_upload import cross_thread_service, seed_commit, GIT_ENV


def make_v2_harness(service: SmartHttpService, viewer):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _parts(self):
            parts = [p for p in urlparse(self.path).path.split("/") if p]
            return parts[0], parts[1].removesuffix(".git"), parts[2:]

        def _version(self):
            return protocol_version_from_header(
                self.headers.get("Git-Protocol"))

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
                self._answer(service.advertise(
                    viewer, owner, repo, svc,
                    protocol_version=self._version()))
            except TransportError as exc:
                self._fail(exc)

        def do_POST(self):
            owner, repo, rest = self._parts()
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            try:
                if rest == ["git-upload-pack"]:
                    self._answer(service.upload_pack(
                        viewer, owner, repo, body,
                        protocol_version=self._version()))
                else:
                    self._fail(TransportError("service_invalid"))
            except TransportError as exc:
                self._fail(exc)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class ProtocolV2Tests(unittest.TestCase):
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
        self.commit = seed_commit(self.store, "volmarr", "open")

    def test_header_parser_reads_version_2_only(self):
        self.assertEqual(protocol_version_from_header("version=2"), 2)
        self.assertEqual(
            protocol_version_from_header("version=2:agent=git/2.43"), 2)
        self.assertIsNone(protocol_version_from_header("version=1"))
        self.assertIsNone(protocol_version_from_header(None))
        self.assertIsNone(protocol_version_from_header(""))

    def test_v2_advertisement_offers_capabilities_not_refs(self):
        resp = self.service.advertise(
            None, "volmarr", "open", protocol_version=2)
        self.assertIn(b"version 2\n", resp.body)
        self.assertIn(b"ls-refs=", resp.body)
        self.assertIn(b"fetch=", resp.body)
        # Capabilities replace the ref list in v2: the tip oid is
        # not disclosed in the advertisement itself.
        self.assertNotIn(self.commit.encode(), resp.body)

    def test_v2_ls_refs_command_is_served(self):
        request = (
            pkt_line(b"command=ls-refs\n")
            + pkt_line(b"agent=git/2.43.0\n")
            + pkt_line(b"object-format=sha1\n")
            + PKT_DELIMITER
            + pkt_line(b"ref-prefix refs/heads/\n")
            + PKT_FLUSH)
        resp = self.service.upload_pack(
            None, "volmarr", "open", request, protocol_version=2)
        self.assertIn(self.commit.encode(), resp.body)
        self.assertIn(b"refs/heads/main", resp.body)

    def test_stock_git_clone_with_packet_trace_speaks_v2(self):
        server = make_v2_harness(cross_thread_service(self.data_root), None)
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        trace = self.data_root / "trace.log"
        env = dict(os.environ); env.update(GIT_ENV)
        env["HOME"] = str(self.data_root)
        env["GIT_TRACE_PACKET"] = str(trace)
        dest = self.data_root / "clone-v2"
        out = subprocess.run(
            ["git", "-c", "protocol.version=2", "clone",
             f"http://127.0.0.1:{port}/volmarr/open.git", str(dest)],
            capture_output=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr.decode())
        self.assertEqual((dest / "hello.txt").read_bytes(), b"hello\n")
        trace_bytes = trace.read_bytes()
        self.assertIn(b"command=ls-refs", trace_bytes)
        # The packet spelling of the dialect (the header's
        # "version=2" becomes "version 2" on the wire).
        self.assertIn(b"version 2", trace_bytes)

    def test_v0_remains_the_default_dialect(self):
        resp = self.service.advertise(None, "volmarr", "open")
        self.assertIn(self.commit.encode(), resp.body)
        self.assertNotIn(b"version 2\n", resp.body)


if __name__ == "__main__":
    unittest.main()
