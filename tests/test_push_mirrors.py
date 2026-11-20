"""S-333 acceptance battery: push mirrors.

Acceptance (roadmap S-333): push mirrors -- Samverk mirrors
its own repos onward (to a second machine's Samverk or
plain git remote) with the same status honesty.

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
from samverk.push_mirrors import (
    PushMirrorError, PushMirrorService, plain_push_failure_reason,
    push_target_to_dict, render_push_mirrors_page)
from samverk.repositories import RepositoryStore


def git(repo: Path, *args: str, input_bytes: bytes | None = None) -> str:
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@e.c",
                "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@e.c"})
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         input=input_bytes, capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode())
    return out.stdout.decode().strip()


def commit_to(repo: Path, parent: str | None, text: bytes,
              message: bytes) -> str:
    blob = git(repo, "hash-object", "-w", "--stdin", input_bytes=text)
    tree = git(repo, "mktree",
               input_bytes=f"100644 blob {blob}\tx.txt\n".encode())
    args = ["commit-tree", tree]
    if parent:
        args += ["-p", parent]
    commit = git(repo, *args, input_bytes=message)
    git(repo, "update-ref", "refs/heads/main", commit)
    return commit


def make_bare(base: Path, name: str) -> Path:
    dest = base / name
    subprocess.run(["git", "init", "--bare", "-b", "main", str(dest)],
                   check=True, capture_output=True)
    return dest


class PushMirrorTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        self.data_root = root / "instance"; self.data_root.mkdir()
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.other = self.accounts.register("other", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.audit = AuditLog(self.conn)
        self.clock = [1_700_000_000.0]
        self.push = PushMirrorService(
            self.conn, self.data_root, self.accounts, self.repos,
            audit=self.audit, time_fn=lambda: self.clock[0])
        self.repo = self.repos.create_repository(
            self.owner.id, "volmarr", "core")
        self.repo_path = self.repos.path_for("volmarr", "core")
        self.commit = commit_to(self.repo_path, None, b"hi\n", b"first\n")
        self.dest_dir = root / "second"; self.dest_dir.mkdir()
        self.dest = make_bare(self.dest_dir, "core.git")

    # -- pins ---------------------------------------------------
    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 136)
        self.assertEqual(db.MIGRATIONS[-1][0], 136)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 138)

    def test_migration_136_table_exists(self):
        row = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name='repo_push_mirrors'").fetchone()
        self.assertIsNotNone(row)

    # -- target management ----------------------------------------
    def test_add_target_starts_never_pushed_and_not_healthy(self):
        mirror = self.push.add_target(self.owner.id, "volmarr", "core",
                                      self.dest)
        self.assertEqual(mirror.target_kind, "local")
        self.assertEqual(mirror.state, "never_pushed")
        self.assertFalse(mirror.healthy)
        self.assertIsNone(mirror.last_attempt_at)
        self.assertIsNone(mirror.last_success_at)
        self.assertIsNone(mirror.failure_reason)
        self.assertIn("never pushed", mirror.headline)

    def test_add_target_url_accepted(self):
        mirror = self.push.add_target(
            self.owner.id, "volmarr", "core",
            "https://example.invalid/team/core.git")
        self.assertEqual(mirror.target_kind, "url")

    def test_add_target_with_credentials_in_url_refused(self):
        with self.assertRaises(PushMirrorError) as ctx:
            self.push.add_target(
                self.owner.id, "volmarr", "core",
                "https://user:secret@example.invalid/core.git")
        self.assertEqual(ctx.exception.reason, "target_invalid")
        self.assertEqual(self.push.list_targets("volmarr", "core"), [])

    def test_add_target_relative_local_refused(self):
        with self.assertRaises(PushMirrorError) as ctx:
            self.push.add_target(self.owner.id, "volmarr", "core",
                                 Path("relative/core.git"))
        self.assertEqual(ctx.exception.reason, "target_invalid")

    def test_add_target_duplicate_refused(self):
        self.push.add_target(self.owner.id, "volmarr", "core", self.dest)
        with self.assertRaises(PushMirrorError) as ctx:
            self.push.add_target(self.owner.id, "volmarr", "core", self.dest)
        self.assertEqual(ctx.exception.reason, "target_exists")

    def test_add_target_only_owner(self):
        with self.assertRaises(PushMirrorError) as ctx:
            self.push.add_target(self.other.id, "volmarr", "core", self.dest)
        self.assertEqual(ctx.exception.reason, "not_repo_owner")

    def test_add_target_ghost_repo_refused(self):
        with self.assertRaises(PushMirrorError) as ctx:
            self.push.add_target(self.owner.id, "volmarr", "ghost", self.dest)
        self.assertEqual(ctx.exception.reason, "no_such_repo")

    def test_remove_target(self):
        mirror = self.push.add_target(self.owner.id, "volmarr", "core",
                                      self.dest)
        self.push.remove_target(self.owner.id, "volmarr", "core", mirror.id)
        self.assertEqual(self.push.list_targets("volmarr", "core"), [])
        with self.assertRaises(PushMirrorError) as ctx:
            self.push.remove_target(self.owner.id, "volmarr", "core",
                                    mirror.id)
        self.assertEqual(ctx.exception.reason, "push_target_not_found")

    # -- push: success ---------------------------------------------
    def test_push_success_moves_refs_and_records_honesty(self):
        mirror = self.push.add_target(self.owner.id, "volmarr", "core",
                                      self.dest)
        result = self.push.push_to_target("volmarr", "core", mirror.id)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.objects_moved, 3)  # blob + tree + commit
        self.assertEqual(git(self.dest, "rev-parse", "refs/heads/main"),
                         self.commit)
        after = self.push.get_target("volmarr", "core", mirror.id)
        self.assertEqual(after.state, "healthy")
        self.assertTrue(after.healthy)
        self.assertEqual(after.last_attempt_at, 1_700_000_000)
        self.assertEqual(after.last_success_at, 1_700_000_000)
        self.assertEqual(after.last_objects_moved, 3)

    def test_second_push_moves_zero_and_says_so(self):
        mirror = self.push.add_target(self.owner.id, "volmarr", "core",
                                      self.dest)
        self.push.push_to_target("volmarr", "core", mirror.id)
        result = self.push.push_to_target("volmarr", "core", mirror.id)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.objects_moved, 0)
        after = self.push.get_target("volmarr", "core", mirror.id)
        self.assertEqual(after.last_objects_moved, 0)

    def test_push_after_new_commit_moves_new_objects(self):
        mirror = self.push.add_target(self.owner.id, "volmarr", "core",
                                      self.dest)
        self.push.push_to_target("volmarr", "core", mirror.id)
        commit2 = commit_to(self.repo_path, self.commit, b"two\n",
                            b"second\n")
        result = self.push.push_to_target("volmarr", "core", mirror.id)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.objects_moved, 3)
        self.assertEqual(git(self.dest, "rev-parse", "refs/heads/main"),
                         commit2)

    def test_push_all_pushes_every_target(self):
        dest2 = make_bare(self.dest_dir, "core2.git")
        self.push.add_target(self.owner.id, "volmarr", "core", self.dest)
        self.push.add_target(self.owner.id, "volmarr", "core", dest2)
        results = self.push.push_all("volmarr", "core")
        self.assertEqual([r.status for r in results], ["ok", "ok"])
        self.assertEqual(git(dest2, "rev-parse", "refs/heads/main"),
                         self.commit)

    # -- push: failure honesty ---------------------------------------
    def test_failed_push_records_attempt_but_not_success(self):
        mirror = self.push.add_target(self.owner.id, "volmarr", "core",
                                      self.dest)
        self.push.push_to_target("volmarr", "core", mirror.id)
        shutil.rmtree(self.dest)
        self.clock[0] += 60
        result = self.push.push_to_target("volmarr", "core", mirror.id)
        self.assertEqual(result.status, "failed")
        after = self.push.get_target("volmarr", "core", mirror.id)
        self.assertEqual(after.state, "failed")
        self.assertFalse(after.healthy)
        self.assertEqual(after.last_attempt_at, 1_700_000_060)
        self.assertEqual(after.last_success_at, 1_700_000_000)
        self.assertIsNotNone(after.failure_reason)
        self.assertTrue(after.last_detail)

    def test_failed_first_push_never_looks_healthy(self):
        mirror = self.push.add_target(self.owner.id, "volmarr", "core",
                                      self.dest)
        shutil.rmtree(self.dest)
        result = self.push.push_to_target("volmarr", "core", mirror.id)
        self.assertEqual(result.status, "failed")
        after = self.push.get_target("volmarr", "core", mirror.id)
        self.assertFalse(after.healthy)
        self.assertIsNone(after.last_success_at)

    def test_push_unknown_target_refused(self):
        with self.assertRaises(PushMirrorError) as ctx:
            self.push.push_to_target("volmarr", "core", 9999)
        self.assertEqual(ctx.exception.reason, "push_target_not_found")

    # -- plain words, dict, render ------------------------------------
    def test_plain_failure_reason_translations(self):
        self.assertIn("could not be looked up",
                      plain_push_failure_reason("Could not resolve host: x"))
        self.assertIn("refused the connection",
                      plain_push_failure_reason("Connection refused"))
        self.assertIn("no detail was recorded",
                      plain_push_failure_reason(None))
        self.assertIn("odd boom",
                      plain_push_failure_reason("odd boom"))

    def test_to_dict_carries_no_secret_and_honest_state(self):
        mirror = self.push.add_target(self.owner.id, "volmarr", "core",
                                      self.dest)
        data = push_target_to_dict(mirror)
        self.assertEqual(data["state"], "never_pushed")
        self.assertFalse(data["healthy"])
        self.assertNotIn("secret", str(data).lower())

    def test_render_page_states_words_and_escapes(self):
        mirror = self.push.add_target(self.owner.id, "volmarr", "core",
                                      self.dest)
        self.push.push_to_target("volmarr", "core", mirror.id)
        page = render_push_mirrors_page(
            "volmarr/core", self.push.list_targets("volmarr", "core"))
        self.assertIn("healthy -- the last push succeeded", page)
        self.assertIn("Healthy: yes.", page)
        self.assertIn("Objects moved by the last attempt: 3.", page)
        empty = render_push_mirrors_page("volmarr/core", [])
        self.assertIn("has no push mirrors", empty)


if __name__ == "__main__":
    unittest.main()
