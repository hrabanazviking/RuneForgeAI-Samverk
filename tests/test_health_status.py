"""S-359 acceptance battery: health and status.

Acceptance (roadmap S-359): a `/healthz`-style
endpoint and an admin status page (disk, DB, index
lag S-215, job backlog) with honest numbers.

Counted with: python3 -m unittest tests.test_health_status
"""
from __future__ import annotations
import http.client, json, sys, tempfile, threading, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.config import Config
from samverk.data_layout import ensure_layout
from samverk.db import schema_version
from samverk.health_status import (
    EXPECTED_SCHEMA_VERSION, BacklogSource, HealthStatus,
    HealthStatusError, ProbeFacts, decide_overall_status,
    gather_disk_facts, healthz_payload, judge_probe,
    probe_connection, probe_database, render_status_page,
    summarise_backlog)
from samverk.index_architecture import SearchIndexStore
from samverk.repositories import RepositoryStore
from samverk.server import make_server
from samverk.sessions import SessionStore


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class PureLawTests(unittest.TestCase):
    def test_judge_probe_words(self):
        ok = judge_probe(ProbeFacts(True, True, 139), 139)
        self.assertEqual((ok.status, ok.http_status, ok.db), ("ok", 200, "up"))
        self.assertEqual(ok.reason, "")
        broken = judge_probe(ProbeFacts(True, False, None, "DatabaseError"), 139)
        self.assertEqual((broken.status, broken.http_status, broken.db),
                         ("down", 503, "down"))
        self.assertEqual(broken.reason, "database_unreachable")
        stale = judge_probe(ProbeFacts(True, True, 138), 139)
        self.assertEqual((stale.status, stale.http_status, stale.db),
                         ("down", 503, "up"))
        self.assertEqual(stale.reason, "schema_mismatch")
        self.assertEqual(stale.schema_version, 138)
        missing = judge_probe(ProbeFacts(False, False, None), 139)
        self.assertEqual((missing.status, missing.http_status, missing.db),
                         ("ok", 200, "missing"))
        self.assertIsNone(missing.schema_version)
        self.assertEqual(missing.reason, "database_not_initialised")

    def test_healthz_payload_carries_no_sensitive_numbers(self):
        payload = healthz_payload(judge_probe(ProbeFacts(True, True, 139), 139))
        self.assertEqual(set(payload),
                         {"status", "service", "version", "db", "schema_version"})
        self.assertEqual(payload["schema_version"], 139)
        down = healthz_payload(judge_probe(ProbeFacts(True, False, None), 139))
        self.assertEqual(down["status"], "down")
        self.assertEqual(down["reason"], "database_unreachable")

    def test_overall_folding_law(self):
        self.assertEqual(decide_overall_status("ok", "current", "sound", 0), "ok")
        self.assertEqual(decide_overall_status("ok", "queued", "sound", 0), "ok")
        self.assertEqual(decide_overall_status("ok", "stale", "sound", 0), "degraded")
        self.assertEqual(decide_overall_status("ok", "failed", "sound", 0), "degraded")
        self.assertEqual(decide_overall_status("ok", "current", "sound", 2), "degraded")
        self.assertEqual(decide_overall_status("ok", "current", "damaged", 0), "degraded")
        self.assertEqual(decide_overall_status("down", "current", "sound", 0), "down")

    def test_backlog_summary_counts_owed_and_dead_only(self):
        sources = (
            BacklogSource("index", "idx", (("pending", 2), ("running", 1), ("done", 5), ("dead", 1))),
            BacklogSource("webhooks", "wh", (("queued", 3), ("delivered", 4), ("dead", 2))),
            BacklogSource("digests", "dg", (("composed", 1), ("sent", 7))),
        )
        report = summarise_backlog(sources)
        self.assertEqual(report.total_backlog, 2 + 1 + 3 + 1)
        self.assertEqual(report.total_dead, 3)
        failed = summarise_backlog((BacklogSource("index", "idx", (), "OperationalError"),))
        self.assertEqual((failed.total_backlog, failed.total_dead), (0, 0))


class WorldTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        ensure_layout(self.root)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.admin = self.accounts.register("admina", "correct horse battery")
        with self.conn:
            self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (self.admin.id,))
        self.admin = self.accounts.get_by_id(self.admin.id)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.index = SearchIndexStore(self.conn, self.repos, time_fn=self.clock)
        self.service = HealthStatus(self.conn, self.accounts, self.index, self.root, time_fn=self.clock)
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO repositories (owner, owner_lower, name, name_lower, created_by, created_at, description, visibility) VALUES ('volmarr', 'volmarr', 'anvil', 'anvil', ?, 1700000000, '', 'public')",
                (self.owner.id,))
        self.repo_id = int(cur.lastrowid)

    def _reason(self, fn, *args):
        with self.assertRaises(HealthStatusError) as ctx:
            fn(*args)
        return ctx.exception.reason

    def test_pins_schema_140_taxonomy_142(self):
        self.assertEqual(schema_version(self.conn), 140)
        self.assertEqual(db.MIGRATIONS[-1][0], 140)
        self.assertEqual(EXPECTED_SCHEMA_VERSION, 140)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 142)

    def test_probe_healthy_database(self):
        report = probe_database(self.root / "samverk.db")
        self.assertEqual((report.status, report.db, report.schema_version), ("ok", "up", 140))
        via_conn = probe_connection(self.conn, self.root / "samverk.db")
        self.assertEqual(via_conn.status, "ok")

    def test_probe_missing_database_creates_nothing(self):
        report = probe_database(self.root / "other" / "samverk.db")
        self.assertEqual((report.status, report.db), ("ok", "missing"))
        self.assertFalse((self.root / "other").exists())

    def test_probe_broken_database_is_down(self):
        broken = self.root / "broken.db"
        broken.write_bytes(b"this is not a sqlite database")
        report = probe_database(broken)
        self.assertEqual((report.status, report.http_status, report.db), ("down", 503, "down"))

    def test_status_refuses_non_admins_before_reading(self):
        self.assertEqual(self._reason(self.service.status, 99999), "no_such_user")
        self.assertEqual(self._reason(self.service.status, self.owner.id), "not_site_admin")
        self.assertEqual(self._reason(self.service.status, None), "no_such_user")
        self.assertEqual(self._reason(self.service.status, True), "no_such_user")

    def test_status_numbers_are_real_and_fresh(self):
        first = self.service.status(self.admin.id)
        self.assertEqual(first.overall, "ok")
        self.assertEqual(first.database.schema_version, 140)
        self.assertEqual(first.database.user_count, 2)
        self.assertEqual(first.database.repo_count, 1)
        self.assertGreater(first.database.size_bytes, 0)
        self.assertEqual(first.index.lag_seconds, 0)
        self.assertEqual(first.backlog.total_backlog, 0)
        self.assertGreater(first.disk.free_bytes, 0)
        self.assertEqual(first.disk.tree_bytes, gather_disk_facts(self.root, self.root / "samverk.db").tree_bytes)
        # Change the world: an un-indexed change waits in S-205's queue.
        self.index.enqueue("volmarr", "anvil", kind="issue", trigger="mutation", target="issue:1")
        self.clock.now += 90
        second = self.service.status(self.admin.id)
        self.assertEqual(second.backlog.total_backlog, 1)
        self.assertEqual(second.index.queue.pending, 1)
        self.assertEqual(second.index.lag_seconds, 90)
        # A file lands in the tree: the disk numbers move.
        (self.root / "repos" / "blob.bin").write_bytes(b"x" * 4096)
        third = self.service.status(self.admin.id)
        self.assertEqual(third.disk.tree_bytes, first.disk.tree_bytes + 4096)
        page = render_status_page(third)
        self.assertIn("Index lag: 90 seconds", page)
        self.assertIn("1 jobs waiting or in flight", page)
        self.assertIn("schema version 140 of 140", page)

    def test_dead_work_degrades_and_page_names_it(self):
        with self.conn:
            self.conn.execute(
                "INSERT INTO webhook_deliveries (webhook_id, event_id, verb, delivery_key, url, host, payload_json, status, attempts, next_attempt_at, created_at, updated_at) VALUES (1, 1, 'push', 'k1', 'https://example.invalid/h', 'example.invalid', '{}', 'dead', 3, 1700000000, 1700000000, 1700000000)")
        status = self.service.status(self.admin.id)
        self.assertEqual(status.overall, "degraded")
        self.assertEqual(status.backlog.total_dead, 1)
        self.assertEqual(status.backlog.total_backlog, 0)
        self.assertIn("1 dead", render_status_page(status))


class HttpTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)

    def _serve(self, root):
        httpd = make_server(Config(host="127.0.0.1", port=0, data_root=root))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        return httpd.server_address[1]

    def _get(self, port, path, cookie=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        headers = {"Cookie": cookie} if cookie else {}
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    def test_healthz_bare_root_is_ok_and_named_missing(self):
        port = self._serve(self.root)
        status, body = self._get(port, "/healthz")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["db"], "missing")
        self.assertIsNone(payload["schema_version"])
        self.assertFalse((self.root / "samverk.db").exists())

    def test_healthz_real_database_and_broken_database(self):
        conn = db.init_db(self.root / "samverk.db"); conn.close()
        port = self._serve(self.root)
        status, body = self._get(port, "/healthz")
        payload = json.loads(body)
        self.assertEqual((status, payload["status"], payload["db"], payload["schema_version"]),
                         (200, "ok", "up", 140))
        (self.root / "samverk.db").write_bytes(b"garbage, not sqlite")
        status, body = self._get(port, "/healthz")
        payload = json.loads(body)
        self.assertEqual((status, payload["status"], payload["db"]), (503, "down", "down"))

    def test_admin_status_over_http(self):
        conn = db.init_db(self.root / "samverk.db")
        accounts = AccountStore(conn)
        admin = accounts.register("admina", "correct horse battery")
        member = accounts.register("volmarr", "correct horse battery")
        with conn:
            conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (admin.id,))
        sessions = SessionStore(conn)
        admin_cookie = f"session={sessions.create(admin.id)}"
        member_cookie = f"session={sessions.create(member.id)}"
        conn.close()
        port = self._serve(self.root)
        status, _ = self._get(port, "/admin/status")
        self.assertEqual(status, 401)
        status, _ = self._get(port, "/admin/status", member_cookie)
        self.assertEqual(status, 403)
        status, body = self._get(port, "/admin/status", admin_cookie)
        self.assertEqual(status, 200)
        page = body.decode("utf-8")
        self.assertIn("Instance status", page)
        self.assertIn("Index lag: 0 seconds", page)
        self.assertIn("schema version 140 of 140", page)


if __name__ == "__main__":
    unittest.main()
