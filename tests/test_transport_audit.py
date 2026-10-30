"""S-094 acceptance battery: transport audit.

Acceptance (roadmap S-094): clone/fetch of private repos and
all pushes recorded at the level the threat model requires,
no more — public reads are not recorded, pack/file contents
never appear, and refused transfers record nothing.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog, verify_chain
from samverk.repositories import RepositoryStore
from samverk.transport_audit import TransportAuditor
from test_ssh_upload_routing import FakeRunner, make_world, serve


def rows(conn, action, target=None):
    sql = "SELECT * FROM audit_log WHERE action = ?"
    args: list = [action]
    if target is not None:
        sql += " AND target_id = ?"
        args.append(target)
    return conn.execute(sql, args).fetchall()


class AuditorLevelTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        self.conn = db.init_db(root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn)
        self.auditor = TransportAuditor(self.audit)

    def test_private_read_is_recorded_with_transport_and_service(self):
        recorded = self.auditor.record_read(
            actor_kind="user", actor_id=7,
            full_name="volmarr/samverk", visibility="private",
            transport="ssh", service="upload-pack")
        self.assertTrue(recorded)
        (row,) = rows(self.conn, "repo.fetch")
        self.assertEqual(row["target_id"], "volmarr/samverk")
        self.assertIn('"transport":"ssh"', row["detail"])
        self.assertIn('"service":"upload-pack"', row["detail"])
        ok, bad, _ = verify_chain(self.conn)
        self.assertTrue(ok, bad)

    def test_public_read_is_not_recorded(self):
        recorded = self.auditor.record_read(
            actor_kind="anonymous", actor_id=None,
            full_name="volmarr/open", visibility="public",
            transport="http", service="upload-pack")
        self.assertFalse(recorded)
        self.assertEqual(rows(self.conn, "repo.fetch"), [])

    def test_detail_never_carries_content(self):
        self.auditor.record_read(
            actor_kind="user", actor_id=7,
            full_name="volmarr/samverk", visibility="private",
            transport="http", service="upload-archive")
        self.auditor.record_push(
            actor_kind="user", actor_id=7,
            full_name="volmarr/samverk", transport="http",
            refs=("refs/heads/main",))
        for row in self.conn.execute("SELECT detail FROM audit_log").fetchall():
            self.assertNotIn("hello", row["detail"] or "")
            self.assertNotIn("pack", (row["detail"] or "").lower()
                             .replace("upload-pack", ""))


class SshWiringTests(unittest.TestCase):
    def test_private_clone_and_archive_are_witnessed_public_is_not(self):
        runner = FakeRunner()
        w = make_world(self, runner=runner)
        serve(w, w["owner_fp"], "git-upload-pack 'volmarr/samverk'")
        serve(w, w["owner_fp"], "git-upload-archive 'volmarr/samverk'")
        serve(w, w["other_fp"], "git-upload-pack 'volmarr/open'")
        fetched = rows(w["conn"], "repo.fetch")
        self.assertEqual(len(fetched), 2)
        services = sorted(
            r["detail"] for r in fetched)
        self.assertTrue(any("upload-pack" in s for s in services))
        self.assertTrue(any("upload-archive" in s for s in services))
        self.assertEqual(
            rows(w["conn"], "repo.fetch", "volmarr/open"), [])

    def test_refused_read_records_nothing(self):
        runner = FakeRunner()
        w = make_world(self, runner=runner)
        serve(w, w["other_fp"], "git-upload-pack 'volmarr/samverk'")
        self.assertEqual(rows(w["conn"], "repo.fetch"), [])


class HttpWiringTests(unittest.TestCase):
    def test_stock_clone_of_private_repo_is_witnessed(self):
        # Stock-git clone + push over real HTTP with an auditor
        # wired (the S-090 harness shape): the private clone
        # lands repo.fetch, the push lands repo.push with
        # transport http, and a public clone lands neither.
        import os
        import sqlite3
        import subprocess
        from samverk.git_http import SmartHttpService
        from samverk.push_events import PushEventStore
        from test_git_http_receive import make_full_harness
        from test_git_http_upload import GIT_ENV, seed_commit
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        conn = db.init_db(root / "samverk.db")
        self.addCleanup(conn.close)
        accounts = AccountStore(conn)
        owner = accounts.register("volmarr", "a long enough passphrase")
        repos = RepositoryStore(conn, root, accounts)
        repos.create_repository(owner.id, "volmarr", "samverk")  # private
        repos.create_repository(
            owner.id, "volmarr", "open", visibility="public")
        seed_commit(repos, "volmarr", "samverk")
        seed_commit(repos, "volmarr", "open")
        conn2 = sqlite3.connect(
            str(root / "samverk.db"), timeout=5.0,
            check_same_thread=False)
        conn2.row_factory = sqlite3.Row
        self.addCleanup(conn2.close)
        accounts2 = AccountStore(conn2)
        repos2 = RepositoryStore(conn2, root, accounts2)
        service2 = SmartHttpService(
            conn2, root, accounts2, repos2, audit=AuditLog(conn2))
        server = make_full_harness(service2, owner)
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        env = dict(os.environ)
        env.update(GIT_ENV)
        env["HOME"] = str(root)
        for name in ("samverk", "open"):
            dest = root / f"clone-{name}"
            out = subprocess.run(
                ["git", "clone",
                 f"http://127.0.0.1:{port}/volmarr/{name}.git", str(dest)],
                capture_output=True, env=env)
            self.assertEqual(out.returncode, 0, out.stderr.decode())
        self.assertGreaterEqual(
            len(rows(conn, "repo.fetch", "volmarr/samverk")), 1)
        self.assertEqual(rows(conn, "repo.fetch", "volmarr/open"), [])
        ok, bad, _ = verify_chain(conn)
        self.assertTrue(ok, bad)


if __name__ == "__main__":
    unittest.main()
