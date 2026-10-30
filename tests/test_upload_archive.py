"""S-093 acceptance battery: upload-archive on the wire.

Acceptance (roadmap S-093): `git-upload-archive` over SSH and
HTTP for archive downloads (S-063 on the wire) — a stock
`git archive --remote=…` must work against both doors,
read-gated like every other read.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import os
import stat
import subprocess
import sys
import tarfile
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
from samverk.git_http import SmartHttpService, TransportError
from samverk.repositories import RepositoryStore
from test_git_http_upload import GIT_ENV, cross_thread_service, seed_commit
from test_ssh_upload_routing import WRAPPER, FakeRunner, make_world, serve


class SshArchiveRoutingTests(unittest.TestCase):
    def setUp(self):
        self.runner = FakeRunner()
        self.w = make_world(self, runner=self.runner)

    def test_owner_archive_runs_upload_archive(self):
        rc, out, _ = serve(
            self.w, self.w["owner_fp"],
            "git-upload-archive 'volmarr/samverk'")
        self.assertEqual(rc, 0)
        (path, program, _), = self.runner.calls
        self.assertEqual(program, "upload-archive")

    def test_stranger_archive_on_private_repo_sees_nothing(self):
        rc, _, err = serve(
            self.w, self.w["other_fp"],
            "git-upload-archive 'volmarr/samverk'")
        self.assertEqual(rc, 128)
        self.assertEqual(self.runner.calls, [])


class StockGitArchiveInteropTests(unittest.TestCase):
    def test_stock_git_archive_over_the_ssh_door(self):
        w = make_world(self)
        seed_commit(w["repos"], "volmarr", "samverk")
        root = w["root"]
        wrapper = root / "fake-ssh.py"
        wrapper.write_text(WRAPPER.format(
            repo_root=str(Path(__file__).resolve().parent.parent),
            root=str(root), fp=w["owner_fp"]))
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
        env = dict(os.environ)
        env.update(GIT_ENV)
        env["GIT_SSH_COMMAND"] = str(wrapper)
        dest = root / "arch.tar"
        out = subprocess.run(
            ["git", "archive",
             "--remote=git@localhost:volmarr/samverk.git",
             "--format=tar", "--output", str(dest), "HEAD"],
            capture_output=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr.decode())
        with tarfile.open(dest) as tar:
            self.assertEqual(tar.extractfile("hello.txt").read(), b"hello\n")

    def test_http_archive_post_speaks_the_protocol(self):
        # Stock git's remote-curl has no archive operation (it
        # refuses before any request — traced at this slice),
        # so the HTTP door is proven at the protocol level:
        # an upload-archive request body (argument pkt-lines +
        # flush) POSTed through a real HTTP harness comes back
        # carrying the archive's bytes on side-band 1.
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        conn = db.init_db(root / "samverk.db")
        self.addCleanup(conn.close)
        accounts = AccountStore(conn)
        owner = accounts.register("volmarr", "a long enough passphrase")
        repos = RepositoryStore(conn, root, accounts)
        repos.create_repository(
            owner.id, "volmarr", "open", visibility="public")
        seed_commit(repos, "volmarr", "open")
        service = cross_thread_service(root)

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

            def _fail(self, exc):
                self.send_response(
                    {"repo_not_found": 404}.get(exc.reason, 400))
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self):
                owner_, repo, _ = self._parts()
                svc = parse_qs(urlparse(self.path).query)["service"][0]
                try:
                    self._answer(service.advertise(None, owner_, repo, svc))
                except TransportError as exc:
                    self._fail(exc)

            def do_POST(self):
                owner_, repo, rest = self._parts()
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                try:
                    if rest == ["git-upload-archive"]:
                        self._answer(
                            service.upload_archive(None, owner_, repo, body))
                    else:
                        self._fail(TransportError("service_invalid"))
                except TransportError as exc:
                    self._fail(exc)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        from samverk.git_http import PKT_FLUSH, pkt_line
        request = (pkt_line(b"argument --format=tar\n")
                   + pkt_line(b"argument HEAD\n") + PKT_FLUSH)
        import urllib.request
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/volmarr/open.git/git-upload-archive",
            data=request, method="POST")
        with urllib.request.urlopen(req) as resp:
            body = resp.read()
        # The tar stream rides side-band 1 pkt-lines; the
        # file's name and content both appear in the payload.
        self.assertIn(b"hello.txt", body)
        self.assertIn(b"hello\n", body)

    def test_http_archive_advertise_is_read_gated(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        conn = db.init_db(root / "samverk.db")
        self.addCleanup(conn.close)
        accounts = AccountStore(conn)
        owner = accounts.register("volmarr", "a long enough passphrase")
        repos = RepositoryStore(conn, root, accounts)
        repos.create_repository(owner.id, "volmarr", "samverk")  # private
        service = SmartHttpService(conn, root, accounts, repos)
        with self.assertRaises(TransportError) as caught:
            service.advertise(None, "volmarr", "samverk", "git-upload-archive")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        resp = service.advertise(owner, "volmarr", "samverk", "git-upload-archive")
        self.assertIn(b"git-upload-archive", resp.body)


if __name__ == "__main__":
    unittest.main()
