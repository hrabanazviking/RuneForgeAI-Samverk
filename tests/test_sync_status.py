"""S-332 acceptance battery: sync status.

Acceptance (roadmap S-332): sync status -- last attempt,
last success, objects moved, and failure reason in plain
words on the repo page; a failed mirror never looks
healthy.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.mirrors import MirrorService
from samverk.pull_mirrors import PullMirrorService
from samverk.repositories import RepositoryStore
from samverk.sync_status import (
    SyncStatusService, plain_failure_reason,
    render_sync_status_page, status_to_dict)


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


class SyncStatusTests(unittest.TestCase):
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
        self.clock = [1_700_000_000.0]
        self.mirrors = MirrorService(
            self.conn, self.data_root, self.accounts, self.repos,
            audit=self.audit, time_fn=lambda: self.clock[0])
        self.status = SyncStatusService(
            self.conn, self.data_root, self.accounts, self.repos)
        self.mirrors.create_mirror(self.owner.id, "volmarr", "mir", self.src)

    # -- pins ---------------------------------------------------
    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 139)
        self.assertEqual(db.MIGRATIONS[-1][0], 139)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 138)

    def test_migration_135_columns_exist(self):
        cols = {r["name"] for r in self.conn.execute(
            "PRAGMA table_info(repo_mirrors)").fetchall()}
        self.assertIn("last_success_at", cols)
        self.assertIn("last_objects_moved", cols)

    # -- never synced --------------------------------------------
    def test_never_synced_is_not_healthy(self):
        st = self.status.status_for("volmarr", "mir")
        self.assertIsNotNone(st)
        self.assertEqual(st.state, "never_synced")
        self.assertFalse(st.healthy)
        self.assertIsNone(st.last_attempt_at)
        self.assertIsNone(st.last_success_at)
        self.assertIsNone(st.failure_reason)
        self.assertIn("never synced", st.headline)

    def test_status_for_non_mirror_and_ghost_is_none(self):
        self.repos.create_repository(self.owner.id, "volmarr", "plain")
        self.assertIsNone(self.status.status_for("volmarr", "plain"))
        self.assertIsNone(self.status.status_for("volmarr", "ghost"))

    # -- success ---------------------------------------------------
    def test_successful_sync_records_attempt_success_and_objects(self):
        result = self.mirrors.sync_mirror("volmarr", "mir")
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.objects_moved, 3)  # blob + tree + commit
        st = self.status.status_for("volmarr", "mir")
        self.assertEqual(st.state, "healthy")
        self.assertTrue(st.healthy)
        self.assertEqual(st.last_attempt_at, 1_700_000_000)
        self.assertEqual(st.last_success_at, 1_700_000_000)
        self.assertEqual(st.objects_moved, 3)
        self.assertIsNone(st.failure_reason)

    def test_resync_without_change_moves_zero(self):
        self.mirrors.sync_mirror("volmarr", "mir")
        self.clock[0] += 60
        result = self.mirrors.sync_mirror("volmarr", "mir")
        self.assertEqual(result.objects_moved, 0)
        st = self.status.status_for("volmarr", "mir")
        self.assertEqual(st.objects_moved, 0)
        self.assertEqual(st.last_success_at, 1_700_000_060)

    def test_second_sync_moves_new_objects_and_advances_success(self):
        self.mirrors.sync_mirror("volmarr", "mir")
        advance_source(self.src, self.commit)
        self.clock[0] += 3600
        result = self.mirrors.sync_mirror("volmarr", "mir")
        self.assertEqual(result.objects_moved, 3)
        st = self.status.status_for("volmarr", "mir")
        self.assertEqual(st.last_success_at, 1_700_003_600)
        self.assertTrue(st.healthy)

    # -- failure -----------------------------------------------------
    def _break_source(self):
        shutil.rmtree(self.src)

    def test_failed_sync_never_looks_healthy_and_keeps_last_success(self):
        self.mirrors.sync_mirror("volmarr", "mir")
        self._break_source()
        self.clock[0] += 7200
        result = self.mirrors.sync_mirror("volmarr", "mir")
        self.assertEqual(result.status, "failed")
        st = self.status.status_for("volmarr", "mir")
        self.assertEqual(st.state, "failed")
        self.assertFalse(st.healthy)
        self.assertEqual(st.last_attempt_at, 1_700_007_200)
        # the earlier success stands -- failure never rewrites it
        self.assertEqual(st.last_success_at, 1_700_000_000)
        self.assertIsNotNone(st.failure_reason)
        self.assertIn("not healthy", st.headline)

    def test_failed_first_sync_has_no_success(self):
        self._break_source()
        result = self.mirrors.sync_mirror("volmarr", "mir")
        self.assertEqual(result.status, "failed")
        st = self.status.status_for("volmarr", "mir")
        self.assertFalse(st.healthy)
        self.assertIsNone(st.last_success_at)
        self.assertIsNotNone(st.failure_reason)

    def test_mirror_record_carries_s332_fields(self):
        self.mirrors.sync_mirror("volmarr", "mir")
        mirror = self.mirrors.mirror_for("volmarr", "mir")
        self.assertEqual(mirror.last_success_at, 1_700_000_000)
        self.assertEqual(mirror.last_objects_moved, 3)

    # -- pending state through the pull road --------------------------
    def test_pending_pull_mirror_is_not_healthy(self):
        pulls = PullMirrorService(
            self.conn, self.data_root, self.accounts, self.repos,
            audit=self.audit, time_fn=lambda: self.clock[0])
        pulls.begin_pull_mirror(self.owner.id, "volmarr", "pm", self.src)
        st = self.status.status_for("volmarr", "pm")
        self.assertEqual(st.state, "pending")
        self.assertFalse(st.healthy)

    # -- plain words ----------------------------------------------------
    def test_plain_failure_reason_translations(self):
        self.assertIn("credential", plain_failure_reason(
            "credential_unavailable: the named credential is gone"))
        self.assertIn("host name", plain_failure_reason(
            "fatal: could not resolve host example.invalid"))
        self.assertIn("refused the connection", plain_failure_reason(
            "fatal: Connection refused"))
        self.assertIn("ran out of time", plain_failure_reason(
            "fatal: fetch timed out after 120s"))
        self.assertIn("sign-in", plain_failure_reason(
            "fatal: Authentication failed for source"))
        self.assertIn("could not be found", plain_failure_reason(
            "fatal: repository not found"))

    def test_plain_failure_reason_fallback_keeps_detail(self):
        reason = plain_failure_reason("some odd fetch complaint")
        self.assertIn("The last sync failed", reason)
        self.assertIn("some odd fetch complaint", reason)
        self.assertIn("no detail", plain_failure_reason(""))
        self.assertIn("no detail", plain_failure_reason(None))

    # -- dict + page ------------------------------------------------------
    def test_status_to_dict_shape_and_no_secrets(self):
        self.mirrors.sync_mirror("volmarr", "mir")
        d = status_to_dict(self.status.status_for("volmarr", "mir"))
        self.assertEqual(d["full_name"], "volmarr/mir")
        self.assertEqual(d["state"], "healthy")
        self.assertTrue(d["healthy"])
        self.assertEqual(d["objects_moved"], 3)
        for key in d:
            self.assertNotIn("source", key)
            self.assertNotIn("credential", key)
            self.assertNotIn("token", key)

    def test_page_shows_attempt_success_objects(self):
        self.mirrors.sync_mirror("volmarr", "mir")
        page = render_sync_status_page(self.status.status_for("volmarr", "mir"))
        self.assertIn("Last attempt:", page)
        self.assertIn("Last success:", page)
        self.assertIn("Objects moved by the last attempt: 3.", page)
        self.assertIn("Healthy: yes.", page)

    def test_page_for_failed_mirror_says_not_healthy_with_reason(self):
        self.mirrors.sync_mirror("volmarr", "mir")
        self._break_source()
        self.mirrors.sync_mirror("volmarr", "mir")
        page = render_sync_status_page(self.status.status_for("volmarr", "mir"))
        self.assertIn("Healthy: no.", page)
        self.assertNotIn("Healthy: yes.", page)
        self.assertIn("Failure reason:", page)
        self.assertIn("not healthy", page)

    def test_page_escapes_recorded_detail(self):
        with self.conn:
            self.conn.execute(
                "UPDATE repo_mirrors SET last_status = 'failed',"
                " last_detail = ? WHERE repo_id = "
                "(SELECT id FROM repositories WHERE name = 'mir')",
                ("<script>alert(1)</script>",))
        page = render_sync_status_page(self.status.status_for("volmarr", "mir"))
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_page_for_never_synced_says_never(self):
        page = render_sync_status_page(self.status.status_for("volmarr", "mir"))
        self.assertIn("Last attempt: never.", page)
        self.assertIn("Last success: never.", page)
        self.assertIn("Healthy: no.", page)


if __name__ == "__main__":
    unittest.main()
