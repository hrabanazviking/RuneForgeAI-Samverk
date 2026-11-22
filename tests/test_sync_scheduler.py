"""S-331 acceptance battery: sync scheduler.

Acceptance (roadmap S-331): sync scheduler -- per-mirror
interval (24h default, the founding cadence), jittered,
off the request path; manual "sync now" beside it.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import os, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.mirrors import MirrorService
from samverk.refs import RefStore
from samverk.repositories import RepositoryStore
from samverk.sync_scheduler import (
    DEFAULT_INTERVAL_SECONDS, SyncSchedulerError,
    SyncSchedulerService, compute_next, jittered_delay,
    schedule_to_dict, validate_interval)


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


class SyncSchedulerTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        outside = root / "outside"; outside.mkdir()
        self.src, self.commit = make_source(outside)
        self.data_root = root / "instance"; self.data_root.mkdir()
        self.db_path = self.data_root / "samverk.db"
        self.conn = db.init_db(self.db_path)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.other = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.audit = AuditLog(self.conn)
        self.clock = [1_700_000_000.0]
        self.mirrors = MirrorService(
            self.conn, self.data_root, self.accounts, self.repos,
            audit=self.audit, time_fn=lambda: self.clock[0])
        self.sched = SyncSchedulerService(
            self.conn, self.data_root, self.accounts, self.repos,
            audit=self.audit, time_fn=lambda: self.clock[0],
            rand_fn=lambda: 0.0)
        self.mirrors.create_mirror(self.owner.id, "volmarr", "mir", self.src)

    # -- defaults and pure law --------------------------------------
    def test_default_interval_is_founding_cadence(self):
        self.assertEqual(DEFAULT_INTERVAL_SECONDS, 86400)
        sched = self.sched.schedule_for("volmarr", "mir")
        self.assertIsNotNone(sched)
        self.assertEqual(sched.interval_seconds, 86400)
        self.assertTrue(sched.is_default_interval)
        self.assertIn("default", sched.headline)

    def test_validate_interval_rejects_bad_values(self):
        for bad in (True, False, 0, -5, 59, 30 * 86400 + 1,
                    "3600", 3600.5, None):
            with self.assertRaises(SyncSchedulerError) as ctx:
                validate_interval(bad)
            self.assertEqual(ctx.exception.reason, "interval_invalid", bad)
        self.assertEqual(validate_interval(60), 60)
        self.assertEqual(validate_interval(30 * 86400), 30 * 86400)

    def test_jitter_bounds(self):
        self.assertEqual(jittered_delay(3600, 0.0), 3600)
        near = jittered_delay(3600, 0.999999)
        self.assertGreaterEqual(near, 3600)
        self.assertLess(near, int(3600 * 1.1))
        self.assertEqual(compute_next(1000, 3600, 0.0), 4600)

    def test_schedule_for_non_mirror_is_none(self):
        self.repos.create_repository(self.owner.id, "volmarr", "plain")
        self.assertIsNone(self.sched.schedule_for("volmarr", "plain"))
        self.assertIsNone(self.sched.schedule_for("volmarr", "ghost"))

    # -- set / reset ----------------------------------------------------
    def test_set_interval_reschedules_within_jitter_window(self):
        now = int(self.clock[0])
        sched = self.sched.set_interval(self.owner.id, "volmarr", "mir", 3600)
        self.assertEqual(sched.interval_seconds, 3600)
        self.assertFalse(sched.is_default_interval)
        self.assertGreaterEqual(sched.next_sync_at, now + 3600)
        self.assertLess(sched.next_sync_at, now + int(3600 * 1.1))
        row = self.conn.execute(
            "SELECT sync_interval_seconds FROM repo_mirrors").fetchone()
        self.assertEqual(row["sync_interval_seconds"], 3600)

    def test_set_interval_owner_only_and_mirror_only(self):
        with self.assertRaises(SyncSchedulerError) as ctx:
            self.sched.set_interval(self.other.id, "volmarr", "mir", 3600)
        self.assertEqual(ctx.exception.reason, "not_repo_owner")
        self.repos.create_repository(self.owner.id, "volmarr", "plain")
        with self.assertRaises(SyncSchedulerError) as ctx:
            self.sched.set_interval(self.owner.id, "volmarr", "plain", 3600)
        self.assertEqual(ctx.exception.reason, "not_a_mirror")
        with self.assertRaises(SyncSchedulerError) as ctx:
            self.sched.set_interval(self.owner.id, "volmarr", "mir", 10)
        self.assertEqual(ctx.exception.reason, "interval_invalid")

    def test_reset_interval_restores_default(self):
        self.sched.set_interval(self.owner.id, "volmarr", "mir", 3600)
        sched = self.sched.reset_interval(self.owner.id, "volmarr", "mir")
        self.assertEqual(sched.interval_seconds, DEFAULT_INTERVAL_SECONDS)
        self.assertTrue(sched.is_default_interval)
        row = self.conn.execute(
            "SELECT sync_interval_seconds FROM repo_mirrors").fetchone()
        self.assertIsNone(row["sync_interval_seconds"])

    def test_interval_changes_are_witnessed(self):
        self.sched.set_interval(self.owner.id, "volmarr", "mir", 3600)
        self.sched.reset_interval(self.owner.id, "volmarr", "mir")
        rows = self.conn.execute(
            "SELECT detail FROM audit_log").fetchall()
        joined = " ".join(r["detail"] or "" for r in rows)
        self.assertIn("mirror_sync_interval.set", joined)
        self.assertIn("mirror_sync_interval.reset", joined)

    # -- ensure / due ------------------------------------------------------
    def test_ensure_schedule_idempotent_from_created_at(self):
        created = int(self.clock[0])
        first = self.sched.ensure_schedule("volmarr", "mir")
        self.assertEqual(first.next_sync_at, created + 86400)
        second = self.sched.ensure_schedule("volmarr", "mir")
        self.assertEqual(second.next_sync_at, first.next_sync_at)

    def test_due_schedules_follow_the_clock(self):
        self.sched.set_interval(self.owner.id, "volmarr", "mir", 3600)
        self.assertEqual(self.sched.due_schedules(), [])
        self.clock[0] += 3601
        due = self.sched.due_schedules()
        self.assertEqual([s.full_name for s in due], ["volmarr/mir"])

    # -- running --------------------------------------------------------------
    def test_run_due_syncs_new_content_and_advances(self):
        self.sched.sync_now(self.owner.id, "volmarr", "mir")
        second = advance_source(self.src, self.commit)
        self.sched.set_interval(self.owner.id, "volmarr", "mir", 60)
        self.clock[0] += 61
        now = int(self.clock[0])
        results = self.sched.run_due()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "ok")
        self.assertGreater(results[0].next_sync_at, now)
        path = self.repos.path_for("volmarr", "mir")
        self.assertEqual(RefStore(path).resolve("refs/heads/main"), second)
        after = self.sched.schedule_for("volmarr", "mir")
        self.assertEqual(after.last_status, "ok")
        self.assertGreater(after.next_sync_at, now)

    def test_run_due_failed_sync_still_advances(self):
        self.mirrors.create_mirror(
            self.owner.id, "volmarr", "bad",
            "https://127.0.0.1:1/private/repo.git")
        self.sched.set_interval(self.owner.id, "volmarr", "bad", 60)
        self.clock[0] += 61
        now = int(self.clock[0])
        results = {r.full_name: r for r in self.sched.run_due()}
        self.assertIn("volmarr/bad", results)
        self.assertEqual(results["volmarr/bad"].status, "failed")
        self.assertGreater(results["volmarr/bad"].next_sync_at, now)

    def test_sync_now_syncs_when_not_due_and_reschedules(self):
        self.sched.set_interval(self.owner.id, "volmarr", "mir", 86400)
        self.assertEqual(self.sched.due_schedules(), [])
        result = self.sched.sync_now(self.owner.id, "volmarr", "mir")
        self.assertEqual(result.status, "ok")
        path = self.repos.path_for("volmarr", "mir")
        self.assertEqual(RefStore(path).resolve("refs/heads/main"), self.commit)
        self.assertGreater(result.next_sync_at, int(self.clock[0]))
        with self.assertRaises(SyncSchedulerError) as ctx:
            self.sched.sync_now(self.other.id, "volmarr", "mir")
        self.assertEqual(ctx.exception.reason, "not_repo_owner")

    # -- dict / schema pins -------------------------------------------------------
    def test_schedule_to_dict_carries_no_secret(self):
        sched = self.sched.schedule_for("volmarr", "mir")
        data = schedule_to_dict(sched)
        self.assertEqual(data["interval_seconds"], 86400)
        self.assertTrue(data["is_default_interval"])
        blob = repr(data) + sched.headline + repr(sched)
        self.assertNotIn("token", blob.lower())
        self.assertNotIn("secret", blob.lower())

    def test_schema_134_carries_schedule_columns(self):
        self.assertEqual(db.schema_version(self.conn), 138)
        cols = [r["name"] for r in self.conn.execute(
            "PRAGMA table_info(repo_mirrors)").fetchall()]
        self.assertIn("sync_interval_seconds", cols)
        self.assertIn("next_sync_at", cols)


if __name__ == "__main__":
    unittest.main()
