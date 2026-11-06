"""S-159 acceptance battery (Builder-2): the merge hook
and the restore action of branch housekeeping.

Acceptance (roadmap S-159): branch housekeeping —
delete head branch on merge (opt-in), restore branch
action, fork sync hint. This battery covers the
merge-completion hook (`on_pull_request_merged`) and
the restore action at the service layer, against the
designer's settled schema (migration 58). There is no
merge code yet (S-153..S-155 land in parallel), so a
merged pull request is simulated exactly where the
merge slices will mark it: the shared issue row's
state is set to 'merged' directly, and the hook's
re-read goes through its `_is_merged_state` seam.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.branch_housekeeping import (
    BranchHousekeepingError, BranchHousekeepingService,
    deletable_guard_reason, is_deletable_branch,
    render_deleted_branches, render_merge_note)
from samverk.forks import ForkStore
from samverk.issues import IssueStore
from samverk.pull_request_forks import ForkPullRequestStore
from samverk.pull_requests import PullRequestStore
from samverk.refs import RefError, RefStore
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


def make_tree(repo, files):
    def build(items):
        entries = []
        dirs = {}
        for path, content in items:
            head, _, rest = path.partition("/")
            if rest:
                dirs.setdefault(head, []).append((rest, content))
            else:
                blob = git(repo, "hash-object", "-w", "--stdin",
                           input_bytes=content.encode())
                entries.append((path, f"100644 blob {blob}\t{path}"))
        for name, sub in dirs.items():
            tree = build(sub)
            entries.append((name + "/", f"040000 tree {tree}\t{name}"))
        entries.sort(key=lambda item: item[0])
        return git(repo, "mktree",
                   input_bytes=("\n".join(
                       line for _key, line in entries) + "\n").encode())
    return build(sorted(files.items()))


def make_commit(repo, parents, files, message):
    tree = make_tree(repo, files)
    args = ["commit-tree", tree]
    for parent in parents:
        args += ["-p", parent]
    return git(repo, *args, input_bytes=(message + "\n").encode())


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


class MergeHousekeepingTests(unittest.TestCase):
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
        self.reader = self.accounts.register(
            "yrsa", "correct horse battery")
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts)
        self.forks = ForkStore(self.conn, self.root, self.accounts,
                               self.repos, audit=self.audit)
        self.issues = IssueStore(self.conn, self.repos, self.accounts,
                                 audit=self.audit, time_fn=self.clock)
        self.prs = PullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.xprs = ForkPullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.settings = RepoSettingsService(
            self.conn, self.root, self.accounts, self.repos,
            audit=self.audit, time_fn=self.clock)
        self.house = BranchHousekeepingService(
            self.conn, self.root, self.accounts, self.repos,
            audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.path = self.repos.path_for("volmarr", "pub")

    # -- helpers -----------------------------------------------------
    def _open(self, *, head="feature", base="main"):
        base_oid = make_commit(
            self.path, [], {"a.txt": "alpha\n"}, "base")
        git(self.path, "update-ref", "refs/heads/main", base_oid)
        head_oid = make_commit(
            self.path, [base_oid], {"a.txt": "alpha\nbeta\n"},
            "feature work")
        git(self.path, "update-ref", f"refs/heads/{head}", head_oid)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "pub",
            base_branch=base, head_branch=head)
        merge_oid = make_commit(
            self.path, [base_oid, head_oid],
            {"a.txt": "alpha\nbeta\n"}, "merge")
        return pr, base_oid, head_oid, merge_oid

    def _mark_merged(self, pr, merge_oid=None, *,
                     path=None, base="main"):
        """Where S-153..S-155 will mark the merge: the
        shared row's state, in their transaction — and,
        when a merge oid is given, the merge landing on
        the base branch (its ref moves to the merge
        commit), which the hook verifies."""
        row_id = getattr(pr, "row_id", None)
        if row_id is None:  # CrossForkPullRequest wraps one
            row_id = pr.pull_request.row_id
        with self.conn:
            self.conn.execute(
                "UPDATE issues SET state = 'merged' WHERE id = ?",
                (row_id,))
        if merge_oid is not None:
            git(path or self.path, "update-ref",
                f"refs/heads/{base}", merge_oid)

    def _opt_in(self, user_id, owner, repo):
        self.settings.update_settings(
            user_id, owner, repo, delete_branch_on_merge=True)

    def _branch_oid(self, path, name):
        return RefStore(path).resolve(f"refs/heads/{name}")

    def _audit_count(self, action):
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM audit_log WHERE action = ?",
            (action,)).fetchone()
        return int(row["c"])

    def _rows(self, owner="volmarr", repo="pub", viewer=None):
        return self.house.deleted_branches(
            viewer or self.owner, owner, repo)

    # -- the opt-in and the setting surface ---------------------------
    def test_setting_defaults_off_and_round_trips(self):
        settings = self.settings.settings_for(
            self.owner, "volmarr", "pub")
        self.assertFalse(settings.delete_branch_on_merge)
        self.settings.update_settings(
            self.owner.id, "volmarr", "pub",
            delete_branch_on_merge=True)
        settings = self.settings.settings_for(
            self.owner, "volmarr", "pub")
        self.assertTrue(settings.delete_branch_on_merge)
        rows = self.conn.execute(
            "SELECT detail FROM audit_log"
            " WHERE action = 'repo.settings.change'").fetchall()
        self.assertTrue(any(
            '"key":"delete_branch_on_merge"' in r["detail"]
            and '"to":true' in r["detail"] for r in rows))

    def test_setting_rejects_non_bool_and_non_owner(self):
        with self.assertRaises(SettingsError) as cm:
            self.settings.update_settings(
                self.owner.id, "volmarr", "pub",
                delete_branch_on_merge="yes")
        self.assertEqual(cm.exception.reason,
                         "delete_branch_on_merge_invalid")
        with self.assertRaises(SettingsError) as cm:
            self.settings.update_settings(
                self.reader.id, "volmarr", "pub",
                delete_branch_on_merge=True)
        self.assertEqual(cm.exception.reason, "not_repo_owner")
        self.assertFalse(self.settings.settings_for(
            self.owner, "volmarr", "pub").delete_branch_on_merge)

    # -- guard 1+2: opt-in and merged ----------------------------------
    def test_opted_out_keeps_branch_and_records_nothing(self):
        pr, _b, head_oid, merge_oid = self._open()
        self._mark_merged(pr, merge_oid)
        out = self.house.on_pull_request_merged(
            self.owner.id, pr.number, merge_oid)
        self.assertEqual(out.outcome, "opted_out")
        self.assertFalse(out.deleted)
        self.assertEqual(
            self._branch_oid(self.path, "feature"), head_oid)
        self.assertEqual(self._rows(), ())
        self.assertEqual(
            self._audit_count("repo.branch.delete_on_merge"), 0)

    def test_unmerged_pull_request_is_skipped(self):
        pr, _b, head_oid, merge_oid = self._open()
        self._opt_in(self.owner.id, "volmarr", "pub")
        out = self.house.on_pull_request_merged(
            self.owner.id, pr.number, merge_oid)
        self.assertEqual(out.outcome, "not_merged")
        self.assertEqual(
            self._branch_oid(self.path, "feature"), head_oid)
        self.assertEqual(self._rows(), ())

    def test_state_flip_without_landed_merge_deletes_nothing(self):
        # The converged hook's landed-merge test (Builder-1's
        # fix): a bare merged marking whose merge commit is
        # not the base branch's tip deletes nothing.
        pr, _b, head_oid, merge_oid = self._open()
        self._opt_in(self.owner.id, "volmarr", "pub")
        self._mark_merged(pr)  # state only; main never moved
        out = self.house.on_pull_request_merged(
            self.owner.id, pr.number, merge_oid)
        self.assertEqual(out.outcome, "not_merged")
        self.assertEqual(
            self._branch_oid(self.path, "feature"), head_oid)
        self.assertEqual(self._rows(), ())

    def test_unknown_number_is_a_quiet_skip(self):
        out = self.house.on_pull_request_merged(
            self.owner.id, 999, "a" * 40)
        self.assertEqual(out.outcome, "pr_not_found")

    def test_programmer_errors_raise(self):
        pr, _b, _h, merge_oid = self._open()
        with self.assertRaises(BranchHousekeepingError):
            self.house.on_pull_request_merged(
                self.owner.id, pr.number, "")
        with self.assertRaises(BranchHousekeepingError):
            self.house.on_pull_request_merged(
                999999, pr.number, merge_oid)

    # -- the deletion itself ---------------------------------------------
    def test_merge_deletes_records_exact_oid_and_audits(self):
        pr, _b, head_oid, merge_oid = self._open()
        self._opt_in(self.owner.id, "volmarr", "pub")
        self._mark_merged(pr, merge_oid)
        out = self.house.on_pull_request_merged(
            self.owner.id, pr.number, merge_oid)
        self.assertEqual(out.outcome, "deleted")
        self.assertTrue(out.deleted)
        self.assertIsNone(self._branch_oid(self.path, "feature"))
        record = out.record
        self.assertIsNotNone(record)
        repo = self.repos.get_repository("volmarr", "pub")
        self.assertEqual(record.repo_id, repo.id)
        self.assertEqual(record.branch_name, "feature")
        self.assertEqual(record.head_oid, head_oid)
        self.assertEqual(record.merge_oid, merge_oid)
        self.assertEqual(record.pr_number, pr.number)
        self.assertEqual(record.pull_request_id, pr.id)
        self.assertEqual(record.deleted_by, self.owner.id)
        self.assertFalse(record.is_restored)
        self.assertEqual(
            self._audit_count("repo.branch.delete_on_merge"), 1)
        row = self.conn.execute(
            "SELECT detail FROM audit_log"
            " WHERE action = 'repo.branch.delete_on_merge'"
        ).fetchone()
        self.assertIn(f'"oid":"{head_oid}"', row["detail"])
        self.assertIn(f'"merge":"{merge_oid}"', row["detail"])
        self.assertIn('"head_repo":"volmarr/pub"', row["detail"])
        # Idempotent: a second call does nothing, emits nothing.
        again = self.house.on_pull_request_merged(
            self.owner.id, pr.number, merge_oid)
        self.assertEqual(again.outcome, "already_gone")
        self.assertEqual(len(self._rows()), 1)
        self.assertEqual(
            self._audit_count("repo.branch.delete_on_merge"), 1)

    def test_stale_ref_race_skips_silently(self):
        pr, _b, head_oid, merge_oid = self._open()
        self._opt_in(self.owner.id, "volmarr", "pub")
        self._mark_merged(pr, merge_oid)
        with mock.patch.object(
                RefStore, "delete_branch",
                side_effect=RefError("stale_ref", "raced")):
            out = self.house.on_pull_request_merged(
                self.owner.id, pr.number, merge_oid)
        self.assertEqual(out.outcome, "stale_ref")
        self.assertEqual(
            self._branch_oid(self.path, "feature"), head_oid)
        self.assertEqual(self._rows(), ())
        self.assertEqual(
            self._audit_count("repo.branch.delete_on_merge"), 0)

    # -- guards 3-6: the predicate ---------------------------------------
    def test_predicate_guards(self):
        repo = self.repos.get_repository("volmarr", "pub")
        self.assertFalse(is_deletable_branch(repo, "main"))
        self.assertIn("default branch",
                      deletable_guard_reason(repo, "main"))
        self.assertFalse(is_deletable_branch(
            repo, "feature", base_branch="feature"))
        self.assertFalse(is_deletable_branch(
            repo, "feature", head_target="refs/heads/feature"))
        self.assertTrue(is_deletable_branch(repo, "feature"))

    def test_default_branch_head_is_kept(self):
        base_oid = make_commit(
            self.path, [], {"a.txt": "alpha\n"}, "base")
        git(self.path, "update-ref", "refs/heads/main", base_oid)
        dev_oid = make_commit(
            self.path, [base_oid], {"a.txt": "alpha\ndev\n"}, "dev")
        git(self.path, "update-ref", "refs/heads/dev", dev_oid)
        main_oid = make_commit(
            self.path, [dev_oid], {"a.txt": "alpha\ndev\nmore\n"},
            "main work")
        git(self.path, "update-ref", "refs/heads/main", main_oid)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "pub",
            base_branch="dev", head_branch="main")
        self._opt_in(self.owner.id, "volmarr", "pub")
        merge_oid = make_commit(
            self.path, [dev_oid, main_oid],
            {"a.txt": "alpha\ndev\nmore\n"}, "merge")
        self._mark_merged(pr, merge_oid, base="dev")
        out = self.house.on_pull_request_merged(
            self.owner.id, pr.number, merge_oid)
        self.assertEqual(out.outcome, "not_deletable")
        self.assertIn("default branch", out.reason)
        self.assertEqual(self._branch_oid(self.path, "main"), main_oid)
        self.assertEqual(self._rows(), ())

    # -- cross-fork --------------------------------------------------------
    def _open_cross_fork(self, *, maintainer_can_edit=True):
        base_oid = make_commit(
            self.path, [], {"a.txt": "alpha\n"}, "base")
        git(self.path, "update-ref", "refs/heads/main", base_oid)
        self.forks.fork(self.reader.id, "volmarr", "pub")
        fork_path = self.repos.path_for("yrsa", "pub")
        fork_head = make_commit(
            fork_path, [base_oid], {"a.txt": "alpha\nfork\n"},
            "fork work")
        git(fork_path, "update-ref", "refs/heads/feature", fork_head)
        pr = self.xprs.create_cross_fork_pull_request(
            self.reader, "volmarr", "pub", base_branch="main",
            head_owner="yrsa", head_repo="pub", head_branch="feature",
            maintainer_can_edit=maintainer_can_edit)
        merge_oid = make_commit(
            self.path, [base_oid],
            {"a.txt": "alpha\nfork\n"}, "merge")
        return pr, fork_path, fork_head, merge_oid

    def test_cross_fork_deletes_in_fork_under_forks_opt_in(self):
        pr, fork_path, fork_head, merge_oid = self._open_cross_fork()
        # The BASE opting in alone must not delete in the fork.
        self._opt_in(self.owner.id, "volmarr", "pub")
        self._mark_merged(pr, merge_oid)
        out = self.house.on_pull_request_merged(
            self.reader.id, pr.number, merge_oid)
        self.assertEqual(out.outcome, "opted_out")
        self.assertEqual(
            self._branch_oid(fork_path, "feature"), fork_head)
        # The fork opts in; its owner merged; the branch goes.
        self._opt_in(self.reader.id, "yrsa", "pub")
        out = self.house.on_pull_request_merged(
            self.reader.id, pr.number, merge_oid)
        self.assertEqual(out.outcome, "deleted")
        self.assertIsNone(self._branch_oid(fork_path, "feature"))
        self.assertIsNotNone(self._branch_oid(self.path, "main"))
        record = out.record
        fork_repo = self.repos.get_repository("yrsa", "pub")
        self.assertEqual(record.repo_id, fork_repo.id)
        self.assertEqual(record.head_oid, fork_head)

    def test_cross_fork_rider_denies_actor_without_rights(self):
        pr, fork_path, fork_head, merge_oid = self._open_cross_fork(
            maintainer_can_edit=False)
        self._opt_in(self.reader.id, "yrsa", "pub")
        self._mark_merged(pr, merge_oid)
        # The base owner merged but has no rights in the fork
        # and maintainer edits are off: silent skip.
        out = self.house.on_pull_request_merged(
            self.owner.id, pr.number, merge_oid)
        self.assertEqual(out.outcome, "fork_no_rights")
        self.assertEqual(
            self._branch_oid(fork_path, "feature"), fork_head)
        self.assertEqual(self._rows("yrsa", "pub"), ())

    def test_cross_fork_rider_maintainer_path(self):
        pr, fork_path, fork_head, merge_oid = self._open_cross_fork(
            maintainer_can_edit=True)
        self._opt_in(self.reader.id, "yrsa", "pub")
        self._mark_merged(pr, merge_oid)
        out = self.house.on_pull_request_merged(
            self.owner.id, pr.number, merge_oid)
        self.assertEqual(out.outcome, "deleted")
        self.assertIsNone(self._branch_oid(fork_path, "feature"))

    # -- restore -----------------------------------------------------------
    def _deleted(self):
        pr, _b, head_oid, merge_oid = self._open()
        self._opt_in(self.owner.id, "volmarr", "pub")
        self._mark_merged(pr, merge_oid)
        out = self.house.on_pull_request_merged(
            self.owner.id, pr.number, merge_oid)
        assert out.deleted, out
        return out.record, head_oid

    def test_restore_recreates_at_exact_oid(self):
        record, head_oid = self._deleted()
        restored = self.house.restore_branch(
            self.owner.id, "volmarr", "pub", record.id)
        self.assertTrue(restored.is_restored)
        self.assertEqual(restored.restored_by, self.owner.id)
        self.assertEqual(
            self._branch_oid(self.path, "feature"), head_oid)
        self.assertEqual(
            self._audit_count("repo.branch.restore"), 1)
        row = self.conn.execute(
            "SELECT detail FROM audit_log"
            " WHERE action = 'repo.branch.restore'").fetchone()
        self.assertIn(f'"deleted_branch_id":{record.id}',
                      row["detail"])
        # The row is kept, said as restored.
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].state_words, "restored")
        note = render_merge_note(restored)
        self.assertIn("restored to", note)

    def test_restore_refusals_write_nothing(self):
        record, head_oid = self._deleted()
        with self.assertRaises(BranchHousekeepingError) as cm:
            self.house.restore_branch(
                self.owner.id, "volmarr", "pub", 999999)
        self.assertEqual(cm.exception.reason,
                         "deleted_branch_not_found")
        # A branch re-taken since deletion is never overwritten.
        RefStore(self.path).create_branch("feature", head_oid)
        with self.assertRaises(BranchHousekeepingError) as cm:
            self.house.restore_branch(
                self.owner.id, "volmarr", "pub", record.id)
        self.assertEqual(cm.exception.reason, "branch_exists")
        self.assertFalse(self._rows()[0].is_restored)
        self.assertEqual(
            self._audit_count("repo.branch.restore"), 0)

    def test_restore_already_restored_and_permission(self):
        record, _h = self._deleted()
        self.house.restore_branch(
            self.owner.id, "volmarr", "pub", record.id)
        with self.assertRaises(BranchHousekeepingError) as cm:
            self.house.restore_branch(
                self.owner.id, "volmarr", "pub", record.id)
        self.assertEqual(cm.exception.reason, "already_restored")
        record2, _h2 = self._deleted()
        with self.assertRaises(BranchHousekeepingError) as cm:
            self.house.restore_branch(
                self.reader.id, "volmarr", "pub", record2.id)
        self.assertEqual(cm.exception.reason, "permission_denied")

    def test_restore_oid_unavailable(self):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO deleted_branches"
                " (repo_id, branch_name, head_oid, deleted_at,"
                " deleted_by, pull_request_id, pr_number,"
                " merge_oid) VALUES (?, 'gone', ?, 1, ?, 1, 1, '')",
                (self.repos.get_repository("volmarr", "pub").id,
                 "c" * 40, self.owner.id))
            ghost_id = int(cur.lastrowid)
        with self.assertRaises(BranchHousekeepingError) as cm:
            self.house.restore_branch(
                self.owner.id, "volmarr", "pub", ghost_id)
        self.assertEqual(cm.exception.reason, "oid_unavailable")
        self.assertIn("commits are gone", str(cm.exception))

    def test_restore_stranger_to_private_repo_gets_not_found(self):
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        with self.assertRaises(BranchHousekeepingError) as cm:
            self.house.restore_branch(
                self.reader.id, "volmarr", "priv", 1)
        self.assertEqual(cm.exception.reason, "no_such_repo")
        with self.assertRaises(BranchHousekeepingError) as cm:
            self.house.deleted_branches(
                self.reader, "volmarr", "priv")
        self.assertEqual(cm.exception.reason, "no_such_repo")

    def test_redeletion_inserts_a_new_row(self):
        record, head_oid = self._deleted()
        self.house.restore_branch(
            self.owner.id, "volmarr", "pub", record.id)
        new_head = make_commit(
            self.path, [head_oid],
            {"a.txt": "alpha\nbeta\ngamma\n"}, "more work")
        git(self.path, "update-ref", "refs/heads/feature", new_head)
        pr2 = self.prs.create_pull_request(
            self.owner, "volmarr", "pub",
            base_branch="main", head_branch="feature")
        merge_oid = make_commit(
            self.path,
            [self._branch_oid(self.path, "main"), new_head],
            {"a.txt": "alpha\nbeta\ngamma\n"}, "merge 2")
        self._mark_merged(pr2, merge_oid)
        out = self.house.on_pull_request_merged(
            self.owner.id, pr2.number, merge_oid)
        self.assertEqual(out.outcome, "deleted")
        rows = self._rows()
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0].id, rows[1].id)
        self.assertEqual(
            sorted(r.state_words for r in rows),
            ["deleted", "restored"])

    def test_render_says_state_in_words(self):
        record, head_oid = self._deleted()
        html = render_deleted_branches(self._rows())
        self.assertIn("feature", html)
        self.assertIn("deleted", html)
        self.assertIn(head_oid, html)
        self.assertIn("No branches have been deleted",
                      render_deleted_branches(()))
        note = render_merge_note(record)
        self.assertIn("was deleted when this pull request merged",
                      note)
        found = self.house.deleted_branch_for_pull_request(
            self.owner, "volmarr", "pub", record.pr_number)
        self.assertEqual(found.id, record.id)


if __name__ == "__main__":
    unittest.main()
