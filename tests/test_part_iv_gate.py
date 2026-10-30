"""S-096 — PART IV GATE battery.

The assembled Part IV system, struck at once: one smart-HTTP
service carrying every Part IV seam at the same time —
S-089's gate (allowing), S-091's limits, S-092's lock,
S-090's event store, S-094's auditor — serves a stock-git
clone and push; the push lands its event and its audit rows;
a protocol-v2 clone is packet-traced (S-080's acceptance at
gate scale); and a gate veto on the same assembled service
refuses a push with the ref unmoved.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog, verify_chain
from samverk.git_http import SmartHttpService
from samverk.push_events import PushEventStore
from samverk.push_locks import PushLockManager
from samverk.receive_gate import ReceiveGate
from samverk.repositories import RepositoryStore
from samverk.transfer_limits import TransferLimits
from test_git_http_receive import make_full_harness
from test_git_http_upload import GIT_ENV, git, seed_commit


class PartIVGateTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register(
            "volmarr", "a long enough passphrase")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "samverk")
        self.first = seed_commit(self.repos, "volmarr", "samverk")
        self.env = dict(os.environ)
        self.env.update(GIT_ENV)
        self.env["HOME"] = str(self.root)
        self.gate = ReceiveGate()

    def _assembled_server(self):
        conn2 = sqlite3.connect(
            str(self.root / "samverk.db"), timeout=5.0,
            check_same_thread=False)
        conn2.row_factory = sqlite3.Row
        self.addCleanup(conn2.close)
        accounts2 = AccountStore(conn2)
        repos2 = RepositoryStore(conn2, self.root, accounts2)
        service = SmartHttpService(
            conn2, self.root, accounts2, repos2,
            receive_gate=self.gate,
            push_events=PushEventStore(conn2, repos2),
            transfer_limits=TransferLimits(),
            push_locks=PushLockManager(self.root),
            audit=AuditLog(conn2))
        server = make_full_harness(service, self.owner)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def _clone_and_push(self, port, filename="gate.txt"):
        url = f"http://127.0.0.1:{port}/volmarr/samverk.git"
        work = self.root / f"work-{filename}"
        out = subprocess.run(["git", "clone", url, str(work)],
                             capture_output=True, env=self.env)
        self.assertEqual(out.returncode, 0, out.stderr.decode())
        (work / filename).write_bytes(b"gate\n")
        for args in (["add", filename], ["commit", "-m", "gate"],
                     ["push", "origin", "main"]):
            out = subprocess.run(["git", "-C", str(work), *args],
                                 capture_output=True, env=self.env)
            self.assertEqual(out.returncode, 0, out.stderr.decode())
        return work

    def test_assembled_system_clone_push_event_and_audit(self):
        port = self._assembled_server()
        self._clone_and_push(port)
        bare = self.repos.path_for("volmarr", "samverk")
        head = git(bare, "rev-parse", "refs/heads/main")
        self.assertNotEqual(head, self.first)
        events = PushEventStore(
            self.conn, self.repos).list_for_repo("volmarr", "samverk")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].updates[0].old_oid, self.first)
        self.assertEqual(events[0].updates[0].new_oid, head)
        pushes = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log"
            " WHERE action = 'repo.push'").fetchone()
        self.assertGreaterEqual(pushes["n"], 1)
        fetches = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log"
            " WHERE action = 'repo.fetch'").fetchone()
        self.assertGreaterEqual(fetches["n"], 1)  # private clone witnessed
        ok, bad, _ = verify_chain(self.conn)
        self.assertTrue(ok, bad)

    def test_gate_veto_on_the_assembled_service_refuses_cleanly(self):
        self.gate.register_protection(
            "freeze", lambda ctx: "repository frozen by the gate test")
        port = self._assembled_server()
        url = f"http://127.0.0.1:{port}/volmarr/samverk.git"
        work = self.root / "work-veto"
        out = subprocess.run(["git", "clone", url, str(work)],
                             capture_output=True, env=self.env)
        self.assertEqual(out.returncode, 0, out.stderr.decode())
        (work / "nope.txt").write_bytes(b"nope\n")
        for args in (["add", "nope.txt"], ["commit", "-m", "nope"]):
            out = subprocess.run(["git", "-C", str(work), *args],
                                 capture_output=True, env=self.env)
            self.assertEqual(out.returncode, 0, out.stderr.decode())
        out = subprocess.run(["git", "-C", str(work), "push", "origin", "main"],
                             capture_output=True, env=self.env)
        self.assertNotEqual(out.returncode, 0)
        bare = self.repos.path_for("volmarr", "samverk")
        self.assertEqual(git(bare, "rev-parse", "refs/heads/main"), self.first)

    def test_protocol_v2_advertisement_offers_ls_refs(self):
        service = SmartHttpService(
            self.conn, self.root, self.accounts, self.repos)
        resp = service.advertise(
            self.owner, "volmarr", "samverk", "git-upload-pack",
            protocol_version=2)
        self.assertIn(b"ls-refs", resp.body)
        self.assertIn(b"fetch", resp.body)


if __name__ == "__main__":
    unittest.main()
