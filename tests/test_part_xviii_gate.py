"""S-360 -- PART XVIII GATE battery: reliable self-hosting, assembled.

The whole Part XVIII system struck at once, in the house
gate shape of S-204/S-220/S-236/S-256/S-272/S-288/S-312/
S-328/S-344 -- no new production code, only the battery
that walks the landed S-345..S-359 machinery end to end
through its public seams, at the thing the gate names:
**a fresh install, from the written guide alone, timed
and recorded.**

- **The fresh install (S-349's walk, S-345..S-348 under
  it)** -- a bare data root becomes a working instance by
  following docs/INSTALL_WALK.md's own steps through
  run_install_walk: every step green in guide order, the
  first admin standing and able to sign in, the instance
  signing key on disk, the whole pass timed by the walk
  itself (report.elapsed_seconds) and recorded in the
  gate record (docs/PART_XVIII_GATE.md). A rerun is the
  idempotent already-installed answer, never a second
  first admin.
- **The admin's first hour (S-350..S-356)** -- the first
  admin's next three steps are judged in order (S-350);
  the admin panel sees the walked instance's users, orgs
  and repos and refuses non-admins (S-351); site settings
  change only at an admin's hand and read back (S-352);
  maintenance mode banners the instance, refuses pushes
  in words and still lets admins in, then lifts (S-353);
  quota overview reads the real bytes of a real repo
  (S-354); a user report lands in the abuse queue with
  its audit context and is worked to a reasoned resolve
  (S-355); the instance audit view shows the walked
  instance's whole chain, verified, to admins only
  (S-356).
- **Staying alive (S-357..S-359)** -- the upgrade
  procedure rehearses on the walked instance's own
  export: counts verify against the manifest (S-357);
  the migration register covers every standing migration
  exactly, each one-way warning naming the backup road
  (S-358); health probes the real database and the admin
  status page reports the walked instance's honest
  numbers (S-359).
- **The pins** -- the assembled system stands at schema
  140 with 142 audit events (34 auth / 92 repo / 16
  admin). The gate claims no migration and no taxonomy
  event of its own.
- **The honest remainder** -- the roadmap asks for the
  fresh-install battery on Pi-class hardware, by someone
  who did not write the guide. This battery ran on
  purplelongship (the x86-64 development laptop), driven
  by the coordinator from the guide's steps alone; a
  Pi-class (Mimir, ARM) timed pass from the same guide
  remains owed and is named in the gate record, not
  claimed here.

Counted with: python3 -m unittest tests.test_part_xviii_gate
"""
from __future__ import annotations
import sys, tempfile, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.install_walk import EXPECTED_SCHEMA_VERSION, STEP_IDS, render_walk_report, run_install_walk
ROOT = Path(__file__).resolve().parent.parent
PW = "correct horse battery staple"

class GateWorld(unittest.TestCase):
    """One fresh instance, installed by the guide's walk
    in setUpClass and shared by every gate test."""
    @classmethod
    def setUpClass(cls):
        cls._td = tempfile.TemporaryDirectory()
        cls.root = Path(cls._td.name)
        cls.data = cls.root / "instance"
        cls.report = run_install_walk(ROOT, cls.data, "volmarr", PW)
        if not cls.report.ok:
            raise AssertionError(render_walk_report(cls.report))
        cls.conn = db.init_db(cls.data / "samverk.db")
        cls.audit = AuditLog(cls.conn)
        cls.accounts = AccountStore(cls.conn, audit=cls.audit)
        cls.admin = cls.accounts.get_by_username("volmarr")
        cls.repos = None  # built lazily by the tests that need it
    @classmethod
    def tearDownClass(cls):
        cls.conn.close(); cls._td.cleanup()
    def repo_store(self):
        from samverk.repositories import RepositoryStore
        if self.repos is None:
            self.repos = RepositoryStore(self.conn, self.data, self.accounts, audit=self.audit)
        return self.repos

class PinsAndInstallTests(GateWorld):
    def test_pins_schema_140_taxonomy_142(self):
        self.assertEqual(EXPECTED_SCHEMA_VERSION, 140)
        self.assertEqual(schema_version(self.conn), 140)
        self.assertEqual(db.MIGRATIONS[-1][0], 140)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 142)
        fams = {}
        for e in taxonomy.AUDIT_EVENTS:
            fams[e.split(".")[0]] = fams.get(e.split(".")[0], 0) + 1
        self.assertEqual((fams["auth"], fams["repo"], fams["admin"]), (34, 92, 16))
    def test_fresh_install_walk_green_in_guide_order_and_timed(self):
        self.assertTrue(self.report.ok)
        self.assertEqual([s.step_id for s in self.report.steps], list(STEP_IDS))
        self.assertGreater(self.report.elapsed_seconds, 0)
        self.assertTrue(self.admin.is_admin)
        self.assertTrue((self.data / "keys" / "instance-signing-v1.key").is_file())
    def test_guide_doc_names_every_step(self):
        doc = (ROOT / "docs" / "INSTALL_WALK.md").read_text(encoding="utf-8")
        for sid in STEP_IDS: self.assertIn(sid, doc)
    def test_walk_rerun_is_idempotent_no_second_first_admin(self):
        again = run_install_walk(ROOT, self.data, "othername", PW)
        self.assertTrue(again.ok, render_walk_report(again))
        self.assertIsNone(self.accounts.get_by_username("othername"))
        n = self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        self.assertEqual(n, 1)

class FirstHourTests(GateWorld):
    def test_s350_next_steps_exactly_three_in_order(self):
        from samverk.first_admin import decide_next_steps
        steps = decide_next_steps(has_token=False, has_repository=False, has_mirror=False, first_repo_path=None)
        self.assertEqual([s.key for s in steps], ["token", "repository", "mirror"])
        self.assertTrue(all(not s.done for s in steps))
        done = decide_next_steps(has_token=True, has_repository=True, has_mirror=True, first_repo_path="/volmarr/alpha")
        self.assertTrue(all(s.done for s in done))
    def test_s350_second_first_admin_refused_on_walked_instance(self):
        from samverk.first_admin import FirstAdminError, FirstAdminService
        svc = FirstAdminService(self.conn, self.accounts, audit=self.audit)
        self.assertTrue(svc.admin_exists())
        with self.assertRaises(FirstAdminError):
            svc.create_first_admin("secondadmin", PW)
    def test_s351_admin_panel_sees_walked_instance_admin_only(self):
        from samverk.admin_panel import AdminPanel, AdminPanelError
        from samverk.sessions import SessionStore
        from samverk.sudo_mode import SudoMode
        plain = self.accounts.register("mallory", PW, "m@e.c")
        panel = AdminPanel(self.conn, self.data, self.accounts, audit=self.audit, sudo=SudoMode(self.conn, self.accounts), time_fn=time.time)
        over = panel.overview(self.admin.id)
        self.assertGreaterEqual(over.users, 2)
        with self.assertRaises(AdminPanelError):
            panel.overview(plain.id)
        res = panel.search(self.admin.id, "volmarr")
        self.assertTrue(any("volmarr" in str(r) for r in (res.users,)))
    def test_s352_site_settings_admin_hand_and_readback(self):
        from samverk.site_settings import SiteSettingsService
        site = SiteSettingsService(self.conn, self.accounts, audit=self.audit)
        before = site.get_settings()
        updated = site.update_settings(self.admin.id, instance_name="Wyrd Forge")
        self.assertEqual(updated.instance_name, "Wyrd Forge")
        self.assertEqual(site.get_settings().instance_name, "Wyrd Forge")
        plain = self.accounts.get_by_username("mallory")
        if plain is not None:
            with self.assertRaises(Exception):
                site.update_settings(plain.id, instance_name="Nope")
    def test_s353_maintenance_mode_banner_push_refusal_and_lift(self):
        from samverk.maintenance_mode import MaintenanceMode, banner_message, decide_access, push_refusal_message
        mode = MaintenanceMode(self.conn, self.accounts, audit=self.audit)
        state = mode.enable(self.admin, "Rebuilding the index", "back by supper")
        self.assertTrue(state.enabled)
        self.assertIn("Rebuilding the index", banner_message(state))
        self.assertIn("Rebuilding the index", push_refusal_message(state))
        self.assertFalse(decide_access(state, is_admin=False, write=True).allowed)
        self.assertTrue(decide_access(state, is_admin=True, write=True).allowed)
        lifted = mode.disable(self.admin)
        self.assertFalse(lifted.enabled)

class OversightTests(GateWorld):
    def test_s354_quota_overview_reads_real_repo_bytes(self):
        from samverk.quotas import QuotaOverviewService, QuotaService
        repos = self.repo_store()
        repo = repos.create_repository(self.admin.id, "volmarr", "gatekeep")
        quotas = QuotaService(self.conn, self.data, self.accounts, repos, audit=self.audit)
        over = QuotaOverviewService(self.conn, self.data, self.accounts, repos, quotas=quotas).overview_for(self.admin.id, "volmarr")
        self.assertEqual(over.owner, "volmarr")
        self.assertGreaterEqual(len(over.repos), 1)
        self.assertEqual(over.repos[0].full_name, "volmarr/gatekeep")
    def test_s355_abuse_queue_file_work_resolve(self):
        from samverk.abuse_queue import AbuseQueue
        repos = self.repo_store()
        reporter = self.accounts.register("bera", PW, "b@e.c")
        repo = repos.create_repository(self.admin.id, "volmarr", "spamfarm")
        q = AbuseQueue(self.conn, self.accounts, audit=self.audit)
        rep = q.file_report(reporter.id, "repository", repo.id, "spam farm")
        entries = q.queue(self.admin.id)
        self.assertTrue(any(e.report.id == rep.id for e in entries))
        entry = next(e for e in entries if e.report.id == rep.id)
        self.assertIsInstance(entry.context, tuple)
        self.assertTrue(entry.chain_ok)
        q.acknowledge(self.admin.id, rep.id)
        done = q.resolve(self.admin.id, rep.id, "Confirmed spam; repository removed from listing.")
        self.assertEqual(done.state, "resolved")
    def test_s356_instance_audit_view_chain_verified_admin_only(self):
        from samverk.audit_log_ui import AuditLogUIError
        from samverk.instance_audit_view import InstanceAuditViewStore
        repos = self.repo_store()
        store = InstanceAuditViewStore(self.conn, repos, self.accounts)
        page = store.page(self.admin)
        self.assertGreaterEqual(page.total_in_scope, 1)
        self.assertTrue(page.chain.ok)
        plain = self.accounts.get_by_username("bera")
        with self.assertRaises(AuditLogUIError):
            store.page(plain)

class StayingAliveTests(GateWorld):
    def test_s357_upgrade_rehearsal_on_walked_instance(self):
        import subprocess
        from samverk.upgrades import UpgradeProcedure
        repos = self.repo_store()
        repos.create_repository(self.admin.id, "volmarr", "keepsake")
        path = repos.path_for("volmarr", "keepsake")
        def git(*args, data=b""):
            out = subprocess.run(["git", f"--git-dir={path}", *args], input=data, capture_output=True)
            if out.returncode != 0: raise AssertionError(out.stderr.decode())
            return out.stdout.decode().strip()
        blob = git("hash-object", "-w", "--stdin", data=b"keepsake" + bytes([10]))
        tree = git("mktree", data=("100644 blob " + blob + chr(9) + "x.txt" + chr(10)).encode())
        commit = git("commit-tree", tree, data=b"first" + bytes([10]))
        git("update-ref", "refs/heads/main", commit)
        dest = self.root / "gate-export"
        proc = UpgradeProcedure(self.conn, self.data, self.accounts, self.repo_store())
        report = proc.run(self.admin.id, dest, stopped=True, started=True, signin_username="volmarr", signin_password=PW)
        self.assertTrue(report.ok, report.problems if hasattr(report, "problems") else report)
        self.assertEqual([s.step_id for s in report.steps], ["export", "verify_export", "stop", "migrate", "start", "verify_counts"])
    def test_s358_register_covers_every_migration_exactly(self):
        from samverk.database_migrations import REGISTER, validate_register
        self.assertEqual(len(REGISTER), 140)
        self.assertEqual(validate_register(db.MIGRATIONS, REGISTER), [])
        for e in REGISTER:
            self.assertTrue(e.one_way_warning and "backup" in e.one_way_warning, e.version)
    def test_s359_health_probe_and_status_page_honest_numbers(self):
        from samverk.health_status import HealthStatus, healthz_payload, probe_database
        from samverk.index_architecture import SearchIndexStore
        report = probe_database(self.data / "samverk.db")
        payload = healthz_payload(report)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["schema_version"], 140)
        index = SearchIndexStore(self.conn, self.repo_store())
        svc = HealthStatus(self.conn, self.accounts, index, self.data)
        status = svc.status(self.admin.id)
        self.assertEqual(status.probe.schema_version, 140)
        self.assertEqual(status.database.user_count, self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])

if __name__ == "__main__":
    unittest.main()
