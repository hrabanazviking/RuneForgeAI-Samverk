"""S-349 acceptance battery: install walk.

Acceptance (roadmap S-349): from bare machine to first
admin in one documented pass, timed; every step's
failure mode named in the guide.
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.db import schema_version
from samverk.install_walk import (
    EXPECTED_SCHEMA_VERSION, STEP_GUIDE, STEP_IDS, InstallWalkError,
    create_first_admin, decide_checkout, decide_dependency,
    decide_first_admin, decide_python_ok, judge_health_payload,
    render_walk_report, run_install_walk)
ROOT = Path(__file__).resolve().parent.parent
PW = "correct horse battery staple"

class PureJudgementTests(unittest.TestCase):
    def test_schema_and_taxonomy_pins_unchanged(self):
        self.assertEqual(EXPECTED_SCHEMA_VERSION, 139)
        self.assertEqual(db.MIGRATIONS[-1][0], 139)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 138)
    def test_python_floor(self):
        self.assertTrue(decide_python_ok((3, 11, 0))); self.assertTrue(decide_python_ok((3, 14, 4)))
        self.assertFalse(decide_python_ok((3, 10, 9))); self.assertFalse(decide_python_ok((2, 7, 18)))
    def test_dependency_judgement(self):
        self.assertEqual(decide_dependency(False, None), (False, "dependency_missing"))
        self.assertEqual(decide_dependency(True, None), (False, "dependency_broken"))
        self.assertEqual(decide_dependency(True, "46.0.5"), (True, "46.0.5"))
    def test_checkout_judgement(self):
        self.assertEqual(decide_checkout({"pyproject.toml", "samverk/__init__.py", "samverk/cli.py", "samverk/db.py", "samverk/server.py"}), [])
        self.assertIn("samverk/db.py", decide_checkout({"pyproject.toml"}))
    def test_first_admin_three_way_law(self):
        self.assertEqual(decide_first_admin(0, 0), "create")
        self.assertEqual(decide_first_admin(3, 1), "already_present")
        self.assertEqual(decide_first_admin(2, 0), "refuse_nonempty_no_admin")
    def test_health_judgement(self):
        self.assertTrue(judge_health_payload(200, b'{"status":"ok","service":"samverk","version":"0.1.0"}')[0])
        self.assertFalse(judge_health_payload(500, b'{}')[0])
        self.assertFalse(judge_health_payload(200, b'not json')[0])
        self.assertFalse(judge_health_payload(200, b'{"status":"ok","service":"other"}')[0])
    def test_every_step_names_failure_and_remedy(self):
        self.assertEqual(len(STEP_GUIDE), 9); self.assertEqual(len(set(STEP_IDS)), 9)
        for g in STEP_GUIDE:
            self.assertTrue(g.failure_mode.strip()); self.assertTrue(g.remedy.strip()); self.assertTrue(g.title.strip())
    def test_guide_doc_mirrors_step_ids(self):
        doc = (ROOT / "docs" / "INSTALL_WALK.md").read_text(encoding="utf-8")
        for sid in STEP_IDS: self.assertIn(sid, doc)
        for g in STEP_GUIDE: self.assertIn(g.failure_mode.split(":")[0], doc)

class FirstAdminTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.conn = db.init_db(Path(self._td.name) / "samverk.db"); self.addCleanup(self.conn.close)
    def test_create_first_admin_promotes_and_audits(self):
        from samverk.audit import AuditLog
        user = create_first_admin(self.conn, "volmarr", PW, audit=AuditLog(self.conn))
        self.assertTrue(user.is_admin); self.assertEqual(user.status, "active")
        rows = self.conn.execute("SELECT action FROM audit_log ORDER BY seq").fetchall()
        actions = [r[0] for r in rows]
        self.assertIn("auth.signup.success", actions); self.assertIn("admin.user.role_change", actions)
    def test_second_bootstrap_refused(self):
        create_first_admin(self.conn, "volmarr", PW)
        with self.assertRaises(InstallWalkError) as cm: create_first_admin(self.conn, "secondadmin", PW)
        self.assertEqual(cm.exception.reason, "first_admin_exists")
    def test_nonempty_no_admin_refused(self):
        AccountStore(self.conn).register("plainuser", PW)
        with self.assertRaises(InstallWalkError) as cm: create_first_admin(self.conn, "volmarr", PW)
        self.assertEqual(cm.exception.reason, "accounts_without_admin")
    def test_registration_law_still_applies(self):
        with self.assertRaises(InstallWalkError) as cm: create_first_admin(self.conn, "volmarr", "short")
        self.assertEqual(cm.exception.reason, "password_too_short")
        with self.assertRaises(InstallWalkError) as cm: create_first_admin(self.conn, "admin", PW)
        self.assertEqual(cm.exception.reason, "username_reserved")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)

class WalkRunTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.data = Path(self._td.name) / "instance"
    def test_full_walk_bare_to_first_admin(self):
        report = run_install_walk(ROOT, self.data, "volmarr", PW)
        self.assertTrue(report.ok, render_walk_report(report))
        self.assertEqual([s.step_id for s in report.steps], list(STEP_IDS))
        self.assertGreater(report.elapsed_seconds, 0)
        conn = db.init_db(self.data / "samverk.db")
        try:
            self.assertEqual(schema_version(conn), 139)
            admin = AccountStore(conn).get_by_username("volmarr")
            self.assertIsNotNone(admin); self.assertTrue(admin.is_admin)
        finally: conn.close()
        self.assertTrue((self.data / "keys" / "instance-signing-v1.key").is_file())
    def test_walk_rerun_is_idempotent(self):
        first = run_install_walk(ROOT, self.data, "volmarr", PW); self.assertTrue(first.ok)
        second = run_install_walk(ROOT, self.data, "othername", PW)
        self.assertTrue(second.ok, render_walk_report(second))
        self.assertEqual(second.step("first_admin").state, "already_present")
        conn = db.init_db(self.data / "samverk.db")
        try: self.assertEqual(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)
        finally: conn.close()
    def test_walk_without_admin_credentials_fails_at_first_admin(self):
        report = run_install_walk(ROOT, self.data)
        self.assertFalse(report.ok)
        self.assertEqual(report.step("first_admin").state, "first_admin_refused")
        self.assertEqual(report.step("server_health").state, "skipped")
    def test_walk_bad_checkout_fails_early_and_skips_rest(self):
        empty = Path(self._td.name) / "empty"; empty.mkdir()
        report = run_install_walk(empty, self.data, "volmarr", PW)
        self.assertFalse(report.ok); self.assertEqual(report.step("checkout_layout").state, "checkout_incomplete")
        self.assertEqual(report.step("database_init").state, "skipped")
    def test_walk_weak_password_named_not_silent(self):
        report = run_install_walk(ROOT, self.data, "volmarr", "short")
        self.assertFalse(report.ok); self.assertIn("password_too_short", report.step("first_admin").detail)
    def test_render_report_names_failures_and_timing(self):
        report = run_install_walk(ROOT, self.data)
        text = render_walk_report(report)
        self.assertIn("WALK FAILED", text); self.assertIn("remedy:", text); self.assertIn("first_admin", text.lower())
        ok_report = run_install_walk(ROOT, Path(self._td.name) / "i2", "volmarr", PW)
        self.assertIn("WALK OK", render_walk_report(ok_report))

if __name__ == "__main__": unittest.main()
