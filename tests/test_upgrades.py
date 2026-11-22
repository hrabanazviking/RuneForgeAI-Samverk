"""S-357 acceptance battery: upgrades.

Acceptance (roadmap S-357): documented procedure:
export (S-341) -> stop -> migrate -> start -> verify
counts; a failed migration rolls back to the export,
rehearsed in the drill.

Counted with: python3 -m unittest tests.test_upgrades
"""
from __future__ import annotations
import os, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.config import Config
from samverk.db import schema_version
from samverk.lfs_store import LFSStore, oid_for
from samverk.repositories import RepositoryStore
from samverk.secrets import Secrets
from samverk.upgrades import (STEP_GUIDE, STEP_IDS, ObservedUpgradeCounts,
    UpgradeProcedure, compare_upgrade_counts, decide_rollback, decide_start,
    decide_stop, export_dest_problem, plan_upgrade, render_upgrade_report)

def git(repo, *args, input_bytes=None):
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@e.c", "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@e.c"})
    out = subprocess.run(["git", f"--git-dir={repo}", *args], input=input_bytes, capture_output=True, env=env)
    if out.returncode != 0: raise AssertionError(out.stderr.decode())
    return out.stdout.decode().strip()

def standin_next_migration(conn):
    """A rehearsed stand-in next migration: a new table
    plus the schema bump to a pretend 141, on the
    scratch database only. No such migration ships."""
    with conn:
        conn.execute("CREATE TABLE upgrade_rehearsal (id INTEGER PRIMARY KEY, note TEXT NOT NULL)")
        conn.execute("INSERT INTO upgrade_rehearsal (note) VALUES ('rehearsed')")
        conn.execute("INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('version', '141')")
    return 141

def destructive_failing_migration(conn):
    with conn:
        conn.execute("DELETE FROM users WHERE username = 'yrsa'")
        conn.execute("CREATE TABLE half_migrated_junk (id INTEGER)")
    raise RuntimeError("rehearsed migration exploded mid-way")

class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        self.data_root = root / "instance"; self.data_root.mkdir()
        self.dest = root / "exports"
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.admin = self.accounts.register("volmarr", "correct horse battery")
        with self.conn:
            self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (self.admin.id,))
        self.other = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.config = Config(data_root=self.data_root, secret_file=self.data_root / "secrets.env")
        self.secrets = Secrets({"INSTANCE_KEY": "never-export-this-value"})
        self.proc = UpgradeProcedure(self.conn, self.data_root, self.accounts, self.repos, config=self.config, secrets=self.secrets, time_fn=lambda: 1700000000.0)
        self.commits = {}
        for name in ("alpha", "beta"):
            self.repos.create_repository(self.admin.id, "volmarr", name)
            path = self.repos.path_for("volmarr", name)
            blob = git(path, "hash-object", "-w", "--stdin", input_bytes=f"{name}\n".encode())
            tree = git(path, "mktree", input_bytes=f"100644 blob {blob}\tx.txt\n".encode())
            commit = git(path, "commit-tree", tree, input_bytes=b"first\n")
            git(path, "update-ref", "refs/heads/main", commit)
            self.commits[name] = commit
        store = LFSStore(self.repos.path_for("volmarr", "alpha"))
        self.payload = b"large payload bytes"; self.oid = oid_for(self.payload)
        store.put(self.oid, self.payload)

    def run_proc(self, **kw):
        kw.setdefault("stopped", True); kw.setdefault("started", True)
        kw.setdefault("signin_username", "volmarr"); kw.setdefault("signin_password", "correct horse battery")
        return self.proc.run(self.admin.id, self.dest, **kw)

    def test_pins_no_new_migration_or_event(self):
        self.assertEqual(schema_version(self.conn), 140)
        self.assertEqual(db.MIGRATIONS[-1][0], 140)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 142)

    def test_doc_steps_pin_to_code_steps_in_order(self):
        doc = (Path(__file__).resolve().parent.parent / "docs" / "UPGRADES.md").read_text(encoding="utf-8")
        self.assertEqual(plan_upgrade(), STEP_IDS)
        positions = [doc.index(f"### {i+1}. {sid} ") for i, sid in enumerate(STEP_IDS)]
        self.assertEqual(positions, sorted(positions))
        for guide in STEP_GUIDE:
            self.assertIn(guide.failure_mode.split(":")[0], doc)

    def test_stop_and_start_are_judged_preconditions(self):
        self.assertTrue(decide_stop(True)[0]); self.assertFalse(decide_stop(False)[0])
        self.assertFalse(decide_stop(None)[0]); self.assertTrue(decide_start(True)[0])
        self.assertIn("not_stopped", decide_stop(False)[1]); self.assertIn("not_started", decide_start(False)[1])

    def test_decide_rollback_only_after_changes_begin(self):
        for step in ("export", "verify_export", "stop", None): self.assertFalse(decide_rollback(step), step)
        for step in ("migrate", "start", "verify_counts"): self.assertTrue(decide_rollback(step), step)

    def test_export_dest_inside_data_root_is_refused(self):
        self.assertIsNotNone(export_dest_problem(self.data_root, self.data_root / "exports"))
        self.assertIsNone(export_dest_problem(self.data_root, self.dest))

    def test_compare_counts_names_every_mismatch(self):
        manifest = {"repos_included": ["o/a", "o/b"], "repos_excluded": [{"name": "o/c"}], "lfs_objects": 1}
        good = ObservedUpgradeCounts(repos=2, repos_in_db=3, lfs_objects=1, users=2, schema=140)
        self.assertEqual(compare_upgrade_counts(manifest, good, 2, 140), [])
        bad = ObservedUpgradeCounts(repos=1, repos_in_db=1, lfs_objects=0, users=1, schema=139)
        problems = compare_upgrade_counts(manifest, bad, 2, 140)
        for prefix in ("repos:", "repos_in_db:", "lfs_objects:", "users:", "schema:"):
            self.assertTrue(any(p.startswith(prefix) for p in problems), prefix)

    def test_rehearsal_success_counts_verify_against_manifest(self):
        report = self.run_proc(migration_fn=standin_next_migration)
        self.assertTrue(report.ok, report.problems)
        self.assertEqual([s.step_id for s in report.steps], list(STEP_IDS))
        self.assertTrue(all(s.ok for s in report.steps))
        self.assertFalse(report.rolled_back)
        self.assertEqual((report.schema_before, report.schema_after), (140, 141))
        conn = self.proc.conn
        self.assertEqual(schema_version(conn), 141)
        self.assertEqual(conn.execute("SELECT note FROM upgrade_rehearsal").fetchone()[0], "rehearsed")
        self.assertEqual(int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]), 2)
        self.assertTrue(report.archive_path.is_file())
        self.assertIn("upgrade complete", report.headline)

    def test_rehearsal_default_migrate_is_a_clean_noop_upgrade(self):
        report = self.run_proc()
        self.assertTrue(report.ok, report.problems)
        self.assertEqual((report.schema_before, report.schema_after), (140, 140))

    def test_failed_migration_rolls_back_to_the_export(self):
        report = self.run_proc(migration_fn=destructive_failing_migration)
        self.assertFalse(report.ok)
        self.assertEqual(report.failed_step, "migrate")
        self.assertTrue(report.rolled_back, report.rollback_problems)
        self.assertIn("rolled back", report.headline)
        self.assertIn("not half-migrated", report.headline)
        self.assertIn("exploded mid-way", "; ".join(report.problems))
        conn = self.proc.conn
        self.assertEqual(schema_version(conn), 140)
        self.assertEqual(int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]), 2)
        self.assertIsNotNone(self.proc.accounts.get_by_username("yrsa"))
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("half_migrated_junk", tables); self.assertNotIn("upgrade_rehearsal", tables)
        from samverk.refs import RefStore
        path = self.proc.repositories.path_for("volmarr", "alpha")
        self.assertEqual(RefStore(path).resolve("refs/heads/main"), self.commits["alpha"])
        self.assertEqual(LFSStore(path).path_for(self.oid).read_bytes(), self.payload)
        page = render_upgrade_report(report)
        self.assertIn("rolled back", page); self.assertNotIn("never-export-this-value", page)

    def test_counts_mismatch_rolls_back(self):
        def sneaky(conn):
            with conn: conn.execute("DELETE FROM repositories WHERE name = 'beta'")
            return 139
        report = self.run_proc(migration_fn=sneaky)
        self.assertFalse(report.ok); self.assertEqual(report.failed_step, "verify_counts")
        self.assertTrue(report.rolled_back, report.rollback_problems)
        conn = self.proc.conn
        self.assertEqual(int(conn.execute("SELECT COUNT(*) FROM repositories").fetchone()[0]), 2)

    def test_not_stopped_aborts_before_any_change(self):
        report = self.run_proc(stopped=False, migration_fn=standin_next_migration)
        self.assertFalse(report.ok); self.assertEqual(report.failed_step, "stop")
        self.assertFalse(report.rolled_back)
        self.assertIn("before changing anything", report.headline)
        self.assertEqual(schema_version(self.conn), 140)
        self.assertIsNotNone(report.archive_path)

    def test_not_started_rolls_back(self):
        report = self.run_proc(started=False, migration_fn=standin_next_migration)
        self.assertFalse(report.ok); self.assertEqual(report.failed_step, "start")
        self.assertTrue(report.rolled_back, report.rollback_problems)
        self.assertEqual(schema_version(self.proc.conn), 140)

    def test_export_inside_data_root_changes_nothing(self):
        report = self.proc.run(self.admin.id, self.data_root / "exports", stopped=True, started=True)
        self.assertFalse(report.ok); self.assertEqual(report.failed_step, "export")
        self.assertIn("export_inside_data_root", "; ".join(report.problems))
        self.assertFalse((self.data_root / "exports").exists())

if __name__ == "__main__": unittest.main()
