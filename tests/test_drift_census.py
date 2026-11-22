"""S-343 acceptance battery: drift census.

Acceptance (roadmap S-343): a weekly read-only job comparing
mirror heads against source heads; drift beyond the sync
interval is reported to the owner, quietly and factually.

Counted with: python3 -m unittest tests.test_drift_census
"""
from __future__ import annotations
import os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.drift_census import (
    CENSUS_INTERVAL_SECONDS, DriftCensusService, assess_drift,
    census_due, census_to_dict, entry_to_dict, main,
    render_drift_census_page)
from samverk.mirrors import MirrorService
from samverk.repositories import RepositoryStore
from samverk.sync_scheduler import DEFAULT_INTERVAL_SECONDS


def git(repo: Path, *args: str, input_bytes: bytes | None = None) -> str:
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@e.c",
                "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@e.c"})
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         input=input_bytes, capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode())
    return out.stdout.decode().strip()


def make_source(base: Path, name: str = "src.git") -> tuple[Path, str]:
    src = base / name
    subprocess.run(["git", "init", "--bare", "-b", "main", str(src)],
                   check=True, capture_output=True)
    blob = git(src, "hash-object", "-w", "--stdin", input_bytes=b"hi\n")
    tree = git(src, "mktree", input_bytes=f"100644 blob {blob}\tx.txt\n".encode())
    commit = git(src, "commit-tree", tree, input_bytes=b"first\n")
    git(src, "update-ref", "refs/heads/main", commit)
    return src, commit


def advance_source(src: Path, parent: str) -> str:
    blob = git(src, "hash-object", "-w", "--stdin", input_bytes=b"two\n")
    tree = git(src, "mktree", input_bytes=f"100644 blob {blob}\tx.txt\n".encode())
    commit = git(src, "commit-tree", tree, "-p", parent,
                 input_bytes=b"second\n")
    git(src, "update-ref", "refs/heads/main", commit)
    return commit


NOW = 1_700_000_000
SRC = {"refs/heads/main": "a" * 40}
SAME = {"refs/heads/main": "a" * 40}
MOVED = {"refs/heads/main": "b" * 40}


class PureJudgementTests(unittest.TestCase):
    def test_matching_heads_are_in_sync_at_any_age(self):
        v = assess_drift(SRC, SAME, NOW - 10 * 86400, NOW, 86400)
        self.assertEqual(v.state, "in_sync")
        self.assertTrue(v.heads_match)
        self.assertEqual(v.age_seconds, 10 * 86400)

    def test_matching_heads_never_synced_still_in_sync(self):
        v = assess_drift(SRC, SAME, None, NOW, 86400)
        self.assertEqual(v.state, "in_sync")
        self.assertIsNone(v.age_seconds)

    def test_differing_heads_within_interval_are_behind(self):
        v = assess_drift(MOVED, SAME, NOW - 3600, NOW, 86400)
        self.assertEqual(v.state, "behind")
        self.assertEqual(v.diverged, 1)

    def test_exactly_at_interval_is_still_within(self):
        v = assess_drift(MOVED, SAME, NOW - 86400, NOW, 86400)
        self.assertEqual(v.state, "behind")

    def test_differing_heads_beyond_interval_are_drifted(self):
        v = assess_drift(MOVED, SAME, NOW - 86401, NOW, 86400)
        self.assertEqual(v.state, "drifted")
        self.assertEqual(v.age_seconds, 86401)

    def test_differing_heads_without_success_are_never_synced(self):
        v = assess_drift(MOVED, {}, None, NOW, 86400)
        self.assertEqual(v.state, "never_synced")
        self.assertEqual(v.missing, 1)
        self.assertIsNone(v.age_seconds)

    def test_extra_refs_in_mirror_count_as_difference(self):
        wider = {"refs/heads/main": "a" * 40, "refs/heads/old": "c" * 40}
        v = assess_drift(SRC, wider, NOW - 90000, NOW, 86400)
        self.assertEqual(v.state, "drifted")
        self.assertEqual(v.extra, 1)

    def test_census_due_weekly_cadence(self):
        self.assertEqual(CENSUS_INTERVAL_SECONDS, 7 * 86400)
        self.assertTrue(census_due(None, NOW))
        self.assertFalse(census_due(NOW - 6 * 86400, NOW))
        self.assertTrue(census_due(NOW - 7 * 86400, NOW))
        self.assertTrue(census_due(NOW - 8 * 86400, NOW))


class CensusServiceTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        outside = root / "outside"; outside.mkdir()
        self.src, self.commit = make_source(outside)
        self.data_root = root / "instance"; self.data_root.mkdir()
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.audit = AuditLog(self.conn)
        self.clock = [float(NOW)]
        self.mirrors = MirrorService(
            self.conn, self.data_root, self.accounts, self.repos,
            audit=self.audit, time_fn=lambda: self.clock[0])
        self.census = DriftCensusService(
            self.conn, self.data_root, self.accounts, self.repos,
            time_fn=lambda: self.clock[0])
        self.mirrors.create_mirror(self.owner.id, "volmarr", "mir", self.src)

    # -- pins ---------------------------------------------------
    def test_schema_and_taxonomy_pins_stand(self):
        self.assertEqual(schema_version(self.conn), 140)
        self.assertEqual(db.MIGRATIONS[-1][0], 140)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 142)

    # -- census states -------------------------------------------
    def test_synced_mirror_is_in_sync(self):
        self.mirrors.sync_mirror("volmarr", "mir")
        report = self.census.run_census()
        self.assertEqual(report.total, 1)
        entry = report.entries[0]
        self.assertEqual(entry.state, "in_sync")
        self.assertEqual(entry.interval_seconds, DEFAULT_INTERVAL_SECONDS)
        self.assertEqual(entry.matched, 1)
        self.assertEqual(report.in_sync_count, 1)
        self.assertEqual(report.drifted, [])

    def test_unsynced_mirror_is_never_synced(self):
        report = self.census.run_census()
        self.assertEqual(report.entries[0].state, "never_synced")

    def test_source_moved_within_interval_is_behind_not_drifted(self):
        self.mirrors.sync_mirror("volmarr", "mir")
        advance_source(self.src, self.commit)
        self.clock[0] = float(NOW + 3600)
        report = self.census.run_census()
        entry = report.entries[0]
        self.assertEqual(entry.state, "behind")
        self.assertEqual(entry.diverged, 1)
        self.assertEqual(report.drifted, [])
        self.assertIn("1 behind", report.headline)

    def test_source_moved_beyond_interval_is_drifted(self):
        self.mirrors.sync_mirror("volmarr", "mir")
        advance_source(self.src, self.commit)
        self.clock[0] = float(NOW + 86401)
        report = self.census.run_census()
        entry = report.entries[0]
        self.assertEqual(entry.state, "drifted")
        self.assertEqual([e.full_name for e in report.drifted],
                         ["volmarr/mir"])
        self.assertIn("1 drifted beyond", report.headline)

    def test_custom_interval_governs_the_drift_line(self):
        self.mirrors.sync_mirror("volmarr", "mir")
        with self.conn:
            self.conn.execute(
                "UPDATE repo_mirrors SET sync_interval_seconds = 60")
        advance_source(self.src, self.commit)
        self.clock[0] = float(NOW + 120)
        report = self.census.run_census()
        self.assertEqual(report.entries[0].state, "drifted")
        self.assertEqual(report.entries[0].interval_seconds, 60)

    def test_unreadable_source_is_stated_and_census_completes(self):
        self.mirrors.sync_mirror("volmarr", "mir")
        self.mirrors.create_mirror(self.owner.id, "volmarr", "gone", self.src)
        shutil.rmtree(self.src)
        report = self.census.run_census()
        self.assertEqual(report.total, 2)
        states = {e.full_name: e.state for e in report.entries}
        self.assertEqual(states["volmarr/gone"], "unreadable")
        self.assertEqual(states["volmarr/mir"], "unreadable")
        gone = [e for e in report.entries
                if e.full_name == "volmarr/gone"][0]
        self.assertTrue(gone.detail)

    # -- read-only law ----------------------------------------------
    def test_census_writes_nothing(self):
        self.mirrors.sync_mirror("volmarr", "mir")
        advance_source(self.src, self.commit)
        rows_before = [tuple(r) for r in self.conn.execute(
            "SELECT * FROM repo_mirrors ORDER BY repo_id").fetchall()]
        events_before = self.conn.execute(
            "SELECT COUNT(*) FROM audit_log").fetchone()[0]
        mirror_path = self.repos.path_for("volmarr", "mir")
        head_before = git(mirror_path, "rev-parse", "refs/heads/main")
        self.clock[0] = float(NOW + 90000)
        self.census.run_census()
        rows_after = [tuple(r) for r in self.conn.execute(
            "SELECT * FROM repo_mirrors ORDER BY repo_id").fetchall()]
        self.assertEqual(rows_before, rows_after)
        self.assertEqual(events_before, self.conn.execute(
            "SELECT COUNT(*) FROM audit_log").fetchone()[0])
        # the census did not sync: the mirror still holds the old head
        self.assertEqual(git(mirror_path, "rev-parse", "refs/heads/main"),
                         head_before)
        self.assertNotEqual(head_before, git(self.src, "rev-parse",
                                             "refs/heads/main"))

    # -- report faces -------------------------------------------------
    def test_dict_faces_carry_no_source(self):
        self.mirrors.sync_mirror("volmarr", "mir")
        report = self.census.run_census()
        entry = entry_to_dict(report.entries[0])
        self.assertNotIn("source", entry)
        whole = census_to_dict(report)
        self.assertEqual(whole["total"], 1)
        self.assertEqual(whole["in_sync"], 1)
        self.assertNotIn(str(self.src), str(whole))

    def test_render_page_is_quiet_and_factual(self):
        self.mirrors.sync_mirror("volmarr", "mir")
        advance_source(self.src, self.commit)
        self.clock[0] = float(NOW + 90000)
        page = render_drift_census_page(self.census.run_census())
        self.assertIn("Drift census", page)
        self.assertIn("volmarr/mir", page)
        self.assertIn("drifted", page)
        for alarm in ("ALERT", "WARNING", "CRITICAL", "URGENT"):
            self.assertNotIn(alarm, page)

    def test_empty_instance_reports_no_mirrors(self):
        with self.conn:
            self.conn.execute("DELETE FROM repo_mirrors")
        report = self.census.run_census()
        self.assertEqual(report.total, 0)
        self.assertIn("no mirrors are recorded", report.headline)

    def test_main_usage_and_run(self):
        self.assertEqual(main([]), 2)
        self.mirrors.sync_mirror("volmarr", "mir")
        rc = main([str(self.data_root / "samverk.db"), str(self.data_root)])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
