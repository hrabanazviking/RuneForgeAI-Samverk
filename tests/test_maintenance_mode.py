"""S-353 acceptance battery: maintenance mode.

Acceptance (roadmap S-353): read-only banner with reason
and expected return; transports refuse pushes with the
message; admins retain access.

Counted with: python3 -m unittest tests.test_maintenance_mode
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.git_http import SmartHttpService, TransportError, pkt_line, PKT_FLUSH
from samverk.maintenance_mode import (
    MaintenanceError, MaintenanceMode, MaintenanceState, decide_access,
    maintenance_state_from_rows, push_refusal_message, read_state,
    render_maintenance_banner, render_maintenance_page, state_to_dict)
from samverk.receive_gate import ReceiveGate
from samverk.repositories import RepositoryStore
from samverk.ssh_serve import REFUSAL_EXIT
from test_git_http_upload import seed_commit
from test_ssh_upload_routing import FakeRunner, make_world, serve

PW = "a long enough passphrase"
REASON = "Disk swap on the forge host"
RETURN = "Sunday 18:00"
ON = MaintenanceState(enabled=True, reason=REASON, expected_return=RETURN)


class PureJudgementTests(unittest.TestCase):
    def test_off_allows_reads_and_pushes_for_everyone(self):
        off = MaintenanceState(enabled=False)
        for admin in (False, True):
            for write in (False, True):
                self.assertTrue(decide_access(off, is_admin=admin, write=write).allowed)

    def test_on_allows_reads_for_everyone(self):
        for admin in (False, True):
            self.assertTrue(decide_access(ON, is_admin=admin, write=False).allowed)

    def test_on_refuses_non_admin_push_with_the_message(self):
        d = decide_access(ON, is_admin=False, write=True)
        self.assertFalse(d.allowed)
        self.assertEqual(d.reason, "maintenance_mode")
        self.assertIn(REASON, d.message)
        self.assertIn(RETURN, d.message)

    def test_on_allows_admin_push_admins_retain_access(self):
        self.assertTrue(decide_access(ON, is_admin=True, write=True).allowed)

    def test_refusal_message_carries_reason_and_return(self):
        msg = push_refusal_message(ON)
        self.assertIn(REASON, msg); self.assertIn(RETURN, msg)
        self.assertIn("read-only", msg)

    def test_state_from_rows_defaults_off(self):
        self.assertFalse(maintenance_state_from_rows({}).enabled)
        self.assertFalse(maintenance_state_from_rows({"maintenance.enabled": "yes"}).enabled)
        s = maintenance_state_from_rows({
            "maintenance.enabled": "1", "maintenance.reason": REASON,
            "maintenance.expected_return": RETURN,
            "maintenance.set_by": "root", "maintenance.set_at": "42"})
        self.assertTrue(s.enabled); self.assertEqual(s.set_at, 42)
        self.assertEqual(state_to_dict(s)["reason"], REASON)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        self.conn = db.init_db(root / "samverk.db"); self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn)
        self.admin = self.accounts.register("rootadmin", PW)
        self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (self.admin.id,))
        self.admin = self.accounts.get_by_id(self.admin.id)
        self.user = self.accounts.register("volmarr", PW)
        self.mode = MaintenanceMode(self.conn, self.accounts, audit=self.audit)

    def test_enable_sets_state_and_persists(self):
        state = self.mode.enable(self.admin, REASON, RETURN)
        self.assertTrue(state.enabled)
        self.assertEqual(state.set_by, "rootadmin")
        fresh = MaintenanceMode(self.conn, self.accounts)
        self.assertTrue(fresh.current().enabled)
        self.assertEqual(read_state(self.conn).reason, REASON)

    def test_enable_is_admin_only(self):
        for actor in (self.user, None):
            with self.assertRaises(MaintenanceError) as caught:
                self.mode.enable(actor, REASON, RETURN)
            self.assertEqual(caught.exception.reason, "admin_required")
        self.assertFalse(self.mode.current().enabled)

    def test_disable_is_admin_only_and_turns_off(self):
        self.mode.enable(self.admin, REASON, RETURN)
        with self.assertRaises(MaintenanceError):
            self.mode.disable(self.user)
        self.assertTrue(self.mode.current().enabled)
        self.assertFalse(self.mode.disable(self.admin).enabled)

    def test_enable_requires_reason_and_expected_return(self):
        for bad in ("", "  ", None, 42):
            with self.assertRaises(MaintenanceError) as caught:
                self.mode.enable(self.admin, bad, RETURN)
            self.assertEqual(caught.exception.reason, "reason_required")
            with self.assertRaises(MaintenanceError) as caught:
                self.mode.enable(self.admin, REASON, bad)
            self.assertEqual(caught.exception.reason, "expected_return_required")
        self.assertFalse(self.mode.current().enabled)

    def test_changes_are_audit_logged_with_the_standing_event(self):
        self.mode.enable(self.admin, REASON, RETURN)
        self.mode.disable(self.admin)
        rows = self.conn.execute(
            "SELECT action, target_id, outcome FROM audit_log"
            " WHERE action = 'admin.settings.change'").fetchall()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r[1] == "maintenance" for r in rows))

    def test_no_migration_and_no_new_taxonomy_event(self):
        self.assertEqual(schema_version(self.conn), 139)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 138)


class BannerTests(unittest.TestCase):
    def test_banner_is_empty_when_off(self):
        self.assertEqual(render_maintenance_banner(MaintenanceState(enabled=False)), "")
        self.assertIn("off", render_maintenance_page(MaintenanceState(enabled=False)))

    def test_banner_shows_reason_and_expected_return(self):
        html = render_maintenance_banner(ON)
        self.assertIn(REASON, html); self.assertIn(RETURN, html)
        self.assertIn("read-only", html)
        page = render_maintenance_page(ON)
        self.assertIn(REASON, page); self.assertIn(RETURN, page)

    def test_banner_escapes_operator_words(self):
        evil = MaintenanceState(enabled=True, reason="<script>alert(1)</script>", expected_return='"x"')
        html = render_maintenance_banner(evil)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)


class HttpTransportTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        root = Path(self._td.name); self.root = root
        self.conn = db.init_db(root / "samverk.db"); self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", PW)
        self.repos = RepositoryStore(self.conn, root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "open", visibility="public")
        self.commit = seed_commit(self.repos, "volmarr", "open")
        self.service = SmartHttpService(self.conn, root, self.accounts, self.repos)
        self.mode = MaintenanceMode(self.conn, self.accounts)
        self.admin = self.accounts.register("rootadmin", PW)
        self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (self.admin.id,))
        self.admin = self.accounts.get_by_id(self.admin.id)

    def test_push_refused_with_message_reads_work(self):
        self.mode.enable(self.admin, REASON, RETURN)
        with self.assertRaises(TransportError) as caught:
            self.service.advertise(self.owner, "volmarr", "open", "git-receive-pack")
        self.assertEqual(caught.exception.reason, "maintenance_mode")
        self.assertIn(REASON, str(caught.exception))
        self.assertIn(RETURN, str(caught.exception))
        body = pkt_line(f"{'0'*40} {'1'*40} refs/heads/main\0 report-status\n".encode()) + PKT_FLUSH
        with self.assertRaises(TransportError) as caught:
            self.service.receive_pack(self.owner, "volmarr", "open", body)
        self.assertEqual(caught.exception.reason, "maintenance_mode")
        resp = self.service.advertise(None, "volmarr", "open", "git-upload-pack")
        self.assertIn(b"git-upload-pack", resp.body)

    def test_admin_owner_retains_push_door(self):
        self.mode.enable(self.admin, REASON, RETURN)
        self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (self.owner.id,))
        admin_owner = self.accounts.get_by_id(self.owner.id)
        resp = self.service.advertise(admin_owner, "volmarr", "open", "git-receive-pack")
        self.assertIn(b"git-receive-pack", resp.body)

    def test_off_behaves_as_before(self):
        resp = self.service.advertise(self.owner, "volmarr", "open", "git-receive-pack")
        self.assertIn(b"git-receive-pack", resp.body)
        self.mode.enable(self.admin, REASON, RETURN)
        self.mode.disable(self.admin)
        resp = self.service.advertise(self.owner, "volmarr", "open", "git-receive-pack")
        self.assertIn(b"git-receive-pack", resp.body)


class SshTransportTests(unittest.TestCase):
    def test_ssh_push_refused_with_message_reads_work(self):
        runner = FakeRunner()
        w = make_world(self, runner=runner)
        admin = w["accounts"].register("rootadmin", PW)
        w["conn"].execute("UPDATE users SET is_admin = 1 WHERE id = ?", (admin.id,))
        admin = w["accounts"].get_by_id(admin.id)
        MaintenanceMode(w["conn"], w["accounts"]).enable(admin, REASON, RETURN)
        rc, _, err = serve(w, w["owner_fp"], "git-receive-pack 'volmarr/samverk'")
        self.assertEqual(rc, REFUSAL_EXIT)
        self.assertIn(REASON.encode(), err); self.assertIn(RETURN.encode(), err)
        self.assertEqual(runner.calls, [])
        rc, out, _ = serve(w, w["owner_fp"], "git-upload-pack 'volmarr/samverk'")
        self.assertEqual(rc, 0); self.assertEqual(out, b"PACK-OK")

    def test_ssh_admin_retains_access_and_off_is_normal(self):
        runner = FakeRunner()
        w = make_world(self, runner=runner)
        w["conn"].execute("UPDATE users SET is_admin = 1 WHERE id = ?", (w["owner"].id,))
        admin_owner = w["accounts"].get_by_id(w["owner"].id)
        mode = MaintenanceMode(w["conn"], w["accounts"])
        rc, _, _ = serve(w, w["owner_fp"], "git-receive-pack 'volmarr/samverk'")
        self.assertEqual(rc, 0)
        mode.enable(admin_owner, REASON, RETURN)
        rc, _, _ = serve(w, w["owner_fp"], "git-receive-pack 'volmarr/samverk'")
        self.assertEqual(rc, 0)  # admin retains access


class GatePluginTests(unittest.TestCase):
    def test_gate_refuses_non_admin_and_allows_admin(self):
        td = tempfile.TemporaryDirectory(); self.addCleanup(td.cleanup)
        root = Path(td.name)
        conn = db.init_db(root / "samverk.db"); self.addCleanup(conn.close)
        accounts = AccountStore(conn)
        owner = accounts.register("volmarr", PW)
        admin = accounts.register("rootadmin", PW)
        conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (admin.id,))
        admin = accounts.get_by_id(admin.id)
        mode = MaintenanceMode(conn, accounts)
        gate = ReceiveGate(); gate.register_protection("maintenance", mode.gate_plugin)
        self.assertTrue(gate.check(owner="volmarr", repo="x", actor="volmarr").allowed)
        mode.enable(admin, REASON, RETURN)
        result = gate.check(owner="volmarr", repo="x", actor="volmarr")
        self.assertFalse(result.allowed)
        self.assertIn(REASON, result.reason); self.assertIn(RETURN, result.reason)
        self.assertTrue(gate.check(owner="volmarr", repo="x", actor="rootadmin").allowed)


if __name__ == "__main__":
    unittest.main()
