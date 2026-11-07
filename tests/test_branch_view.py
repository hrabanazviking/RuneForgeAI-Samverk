"""S-159 acceptance battery (Builder-3): branch surfaces.

Acceptance (roadmap S-159, UI legs): the
delete_branch_on_merge opt-in on S-066's RepoSettings
surface (migration 58 column, default off, owner-only,
strict-bool refused delete_branch_on_merge_invalid,
audited under repo.settings.change only on a real
change) with its settings form; the branch list and
the deleted-branches page carrying one real restore
form per unrestored tombstone (posting
deleted_branch_id to /{owner}/{repo}/branches/restore);
and the fork sync hint rendered on the repository home
under the header and on the branch list, only when the
fork is behind.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.branch_view import (
    BranchViewError, BranchViewStore, render_branch_list,
    render_deleted_branches_page, render_housekeeping_settings_form)
from samverk.forks import ForkStore
from samverk.repo_home import RepoHomeService, render_repo_home_page
from samverk.repo_settings import RepoSettingsService, SettingsError
from samverk.repositories import RepositoryStore


def git(repo, *args, input_bytes=None):
    env = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin"}
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         capture_output=True, input=input_bytes, env=env)
    assert out.returncode == 0, out.stderr.decode()
    return out.stdout.decode().strip()


def make_commit(repo, parent, text, message):
    blob = git(repo, "hash-object", "-w", "--stdin",
               input_bytes=text.encode())
    tree = git(repo, "mktree",
               input_bytes=f"100644 blob {blob}\ta.txt\n".encode())
    args = ["commit-tree", tree]
    if parent:
        args += ["-p", parent]
    return git(repo, *args, input_bytes=(message + "\n").encode())


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


class BranchViewTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.owner = self.accounts.register(
            "volmarr", "correct horse battery")
        self.other = self.accounts.register(
            "yrsa", "correct horse battery")
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts, audit=self.audit)
        self.forks = ForkStore(
            self.conn, self.root, self.accounts, self.repos,
            audit=self.audit)
        self.settings = RepoSettingsService(
            self.conn, self.root, self.accounts, self.repos,
            audit=self.audit, time_fn=self.clock)
        self.view = BranchViewStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.repo = self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.path = self.repos.path_for("volmarr", "pub")
        self.c1 = make_commit(self.path, None, "one\n", "first")
        git(self.path, "update-ref", "refs/heads/main", self.c1)
        self.c2 = make_commit(self.path, self.c1, "two\n", "feature work")
        git(self.path, "update-ref", "refs/heads/feature", self.c2)

    def _flag_audits(self):
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM audit_log"
            " WHERE action = 'repo.settings.change'"
            " AND detail LIKE '%delete_branch_on_merge%'"
        ).fetchone()
        return int(row["c"])

    def _tombstone(self, branch="old-topic", pr_number=3):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO deleted_branches"
                " (repo_id, branch_name, head_oid, deleted_at,"
                " deleted_by, pull_request_id, pr_number,"
                " merge_oid) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (self.repo.id, branch, self.c2, self.clock.now,
                 self.owner.id, 1, pr_number, self.c1))
        return int(cur.lastrowid)

    # -- migration -------------------------------------------------------
    def test_migration_62_is_the_schema_version(self):
        self.assertEqual(db.schema_version(self.conn), 75)
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("deleted_branches", tables)
        cols = {r["name"] for r in self.conn.execute(
            "PRAGMA table_info(repo_settings)")}
        self.assertIn("delete_branch_on_merge", cols)

    # -- the opt-in on the S-066 settings surface ------------------------
    def test_flag_defaults_off_on_repo_settings(self):
        settings = self.settings.settings_for(
            self.other, "volmarr", "pub")
        self.assertFalse(settings.delete_branch_on_merge)

    def test_flag_round_trip_audits_once_per_real_change(self):
        out = self.settings.update_settings(
            self.owner.id, "volmarr", "pub",
            delete_branch_on_merge=True)
        self.assertTrue(out.delete_branch_on_merge)
        self.assertTrue(self.settings.settings_for(
            self.other, "volmarr", "pub").delete_branch_on_merge)
        self.assertEqual(self._flag_audits(), 1)
        self.settings.update_settings(
            self.owner.id, "volmarr", "pub",
            delete_branch_on_merge=True)
        self.assertEqual(self._flag_audits(), 1)
        self.settings.update_settings(
            self.owner.id, "volmarr", "pub",
            delete_branch_on_merge=False)
        self.assertFalse(self.settings.settings_for(
            self.owner, "volmarr", "pub").delete_branch_on_merge)
        self.assertEqual(self._flag_audits(), 2)
        # Website/topics on the same row were never disturbed.
        s = self.settings.settings_for(self.owner, "volmarr", "pub")
        self.assertEqual((s.website, s.topics), ("", ()))

    def test_flag_refuses_non_bool_and_non_owner(self):
        with self.assertRaises(SettingsError) as caught:
            self.settings.update_settings(
                self.owner.id, "volmarr", "pub",
                delete_branch_on_merge="yes")
        self.assertEqual(caught.exception.reason,
                         "delete_branch_on_merge_invalid")
        with self.assertRaises(SettingsError) as caught:
            self.settings.update_settings(
                self.other.id, "volmarr", "pub",
                delete_branch_on_merge=True)
        self.assertEqual(caught.exception.reason, "not_repo_owner")
        self.assertFalse(self.settings.settings_for(
            self.owner, "volmarr", "pub").delete_branch_on_merge)
        self.assertEqual(self._flag_audits(), 0)

    def test_settings_form_says_state_in_words(self):
        off = self.settings.settings_for(self.owner, "volmarr", "pub")
        html = render_housekeeping_settings_form(off)
        self.assertIn('name="delete_branch_on_merge"', html)
        self.assertNotIn(" checked", html)
        self.assertIn("kept on merge", html)
        self.settings.update_settings(
            self.owner.id, "volmarr", "pub",
            delete_branch_on_merge=True)
        on = self.settings.settings_for(self.owner, "volmarr", "pub")
        html = render_housekeeping_settings_form(on)
        self.assertIn(" checked", html)
        self.assertIn("deleted on merge", html)

    # -- the branch list and the restore affordance -----------------------
    def test_branch_list_names_live_branches_and_default(self):
        view = self.view.branch_list(self.other, "volmarr", "pub")
        self.assertEqual([r.name for r in view.branches],
                         ["feature", "main"])
        self.assertTrue(view.branches[1].is_default)
        self.assertEqual(view.fork_sync.state, "not_a_fork")
        html = render_branch_list(view)
        self.assertIn("(default branch)", html)
        self.assertIn("no deleted branches to restore", html.lower())
        self.assertNotIn("fork-sync-hint", html)

    def test_deleted_page_carries_one_restore_form_per_record(self):
        record_id = self._tombstone()
        view = self.view.branch_list(self.other, "volmarr", "pub")
        self.assertEqual([d.id for d in view.deleted], [record_id])
        self.assertIn("pull request #3", view.deleted[0].words)
        for html in (render_branch_list(view),
                     render_deleted_branches_page(view)):
            self.assertIn('action="/volmarr/pub/branches/restore"',
                          html)
            self.assertIn('name="deleted_branch_id"', html)
            self.assertIn(f'value="{record_id}"', html)
            self.assertIn("Restore branch old-topic", html)
        # A restored record leaves the affordance list.
        with self.conn:
            self.conn.execute(
                "UPDATE deleted_branches SET restored_at = ?,"
                " restored_by = ? WHERE id = ?",
                (self.clock.now, self.owner.id, record_id))
        view = self.view.branch_list(self.other, "volmarr", "pub")
        self.assertEqual(view.deleted, ())
        self.assertNotIn("Restore branch",
                         render_deleted_branches_page(view))
        history = self.view.deleted_branches(
            self.other, "volmarr", "pub", include_restored=True)
        self.assertEqual(len(history), 1)
        self.assertFalse(history[0].is_restorable)

    def test_branch_list_of_a_private_repo_is_not_found_for_strangers(self):
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        with self.assertRaises(BranchViewError) as caught:
            self.view.branch_list(self.other, "volmarr", "priv")
        self.assertEqual(caught.exception.reason, "repo_not_found")

    # -- the hint on the fork's home and branch list -----------------------
    def _make_fork_behind(self):
        fork = self.forks.fork(self.other.id, "volmarr", "pub")
        tip = make_commit(self.path, self.c2, "three\n", "upstream moves")
        git(self.path, "update-ref", "refs/heads/main", tip)
        return fork

    def test_repo_home_carries_payload_and_banner_only_when_behind(self):
        self._make_fork_behind()
        home_service = RepoHomeService(
            self.repos, http_base="https://example.test")
        home = home_service.home_for(self.other, "yrsa", "pub")
        self.assertIsNotNone(home.fork_sync)
        self.assertEqual(home.fork_sync.state, "behind")
        self.assertEqual(home.fork_sync.to_dict()["behind"], 2)
        page = render_repo_home_page(home)
        self.assertIn("fork-sync-hint", page)
        self.assertIn("2 commits behind", page)
        # The upstream's own home: payload present, no banner.
        home = home_service.home_for(self.other, "volmarr", "pub")
        self.assertEqual(home.fork_sync.state, "not_a_fork")
        self.assertNotIn("fork-sync-hint",
                         render_repo_home_page(home))

    def test_branch_list_of_a_behind_fork_carries_the_hint(self):
        self._make_fork_behind()
        view = self.view.branch_list(self.other, "yrsa", "pub")
        self.assertEqual(view.fork_sync.state, "behind")
        html = render_branch_list(view)
        self.assertIn("fork-sync-hint", html)
        self.assertIn("This fork is behind volmarr/pub", html)


if __name__ == "__main__":
    unittest.main()
