"""S-154 acceptance battery: squash merge.

One commit, combined message, author preserved,
closings executed. Foreground, counted, read back
from its log file.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.forks import ForkStore
from samverk.issues import IssueStore
from samverk.pull_request_squash import PullRequestSquashStore
from samverk.pull_request_forks import ForkPullRequestStore
from samverk.pull_requests import PullRequestError, PullRequestStore
from samverk.repositories import RepositoryStore


def git(repo, *args, input_bytes=None):
    env = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin"}
    r = subprocess.run(["git", f"--git-dir={repo}", *args],
                       input=input_bytes, capture_output=True, env=env)
    assert r.returncode == 0, r.stderr.decode()
    return r.stdout.decode().strip()


def make_tree(repo, files):
    entries = []
    for name, text in sorted(files.items()):
        oid = git(repo, "hash-object", "-w", "--stdin",
                  input_bytes=text.encode())
        entries.append(f"100644 blob {oid}\t{name}")
    return git(repo, "mktree", input_bytes=("\n".join(entries) + "\n").encode())


def make_commit(repo, parent, files, message):
    tree = make_tree(repo, files)
    args = ["commit-tree", tree]
    if parent:
        args += ["-p", parent]
    return git(repo, *args, input_bytes=(message + "\n").encode())


class Clock:
    now = 1_700_000_000
    def __call__(self):
        return self.now


BASE_FILES = {"a.txt": "alpha\nbeta\n"}
MID_FILES = {"a.txt": "alpha\nbeta\n", "b.txt": "one\n"}
HEAD_FILES = {"a.txt": "alpha\nBETA\n", "b.txt": "one\ntwo\n"}


class SquashTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.reader = self.accounts.register("yrsa", "correct horse battery")
        self.admin = self.accounts.register("tess", "correct horse battery")
        self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (self.admin.id,))
        self.conn.commit()
        self.admin = self.accounts.get_by_id(self.admin.id)
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.forks = ForkStore(self.conn, self.root, self.accounts, self.repos, audit=self.audit)
        self.issues = IssueStore(self.conn, self.repos, self.accounts, audit=self.audit, time_fn=self.clock)
        self.prs = PullRequestStore(self.conn, self.repos, self.accounts, self.issues, audit=self.audit, time_fn=self.clock)
        self.squash = PullRequestSquashStore(self.conn, self.repos, self.accounts, self.issues, audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")
        self.path = self.repos.path_for("volmarr", "pub")
        self.base_oid = make_commit(self.path, None, BASE_FILES, "base")
        git(self.path, "update-ref", "refs/heads/main", self.base_oid)
        self.mid_oid = make_commit(self.path, self.base_oid, MID_FILES, "add b")
        self.head_oid = make_commit(self.path, self.mid_oid, HEAD_FILES, "finish b")
        git(self.path, "update-ref", "refs/heads/feature", self.head_oid)
        self.pr = self.prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch="feature", title="Feature work", body="Body text.")

    def _base_tip(self):
        return git(self.path, "rev-parse", "refs/heads/main")

    def _audit_actions(self):
        rows = self.conn.execute("SELECT action FROM audit_log ORDER BY rowid").fetchall()
        return [r["action"] for r in rows]

    # 1. clean squash: one commit, one parent, tree, record, PR closed
    def test_clean_squash_lands_one_commit(self):
        report = self.squash.squash_pull_request(self.owner, "volmarr", "pub", self.pr.number)
        self.assertEqual(report.strategy, "squash")
        self.assertEqual(self._base_tip(), report.commit_oid)
        parents = git(self.path, "rev-list", "--parents", "-n", "1", report.commit_oid).split()
        self.assertEqual(parents, [report.commit_oid, self.base_oid])
        tree = git(self.path, "rev-parse", f"{report.commit_oid}^{{tree}}")
        head_tree = git(self.path, "rev-parse", f"{self.head_oid}^{{tree}}")
        self.assertEqual(tree, head_tree)
        self.assertEqual(git(self.path, "rev-parse", "refs/heads/feature"), self.head_oid)
        pr = self.prs.get_pull_request(self.owner, "volmarr", "pub", self.pr.number)
        self.assertEqual(pr.state, "closed")
        record = self.squash.merged_record(self.owner, "volmarr", "pub", self.pr.number)
        self.assertIsNotNone(record)
        self.assertEqual(record.strategy, "squash")
        self.assertEqual(record.merge_commit_oid, report.commit_oid)
        self.assertIn("repo.pull_request.squash_merge", self._audit_actions())

    # 2. combined message: title + PR body + head commit messages
    def test_combined_message(self):
        report = self.squash.squash_pull_request(self.owner, "volmarr", "pub", self.pr.number)
        message = git(self.path, "log", "-1", "--format=%B", report.commit_oid)
        self.assertTrue(message.startswith("Feature work"))
        self.assertIn("Body text.", message)
        self.assertIn("add b", message)
        self.assertIn("finish b", message)
        self.assertFalse(report.message_edited)
        preview = self.squash.preview_squash(self.owner, "volmarr", "pub", self.pr.number)
        self.assertEqual(preview.head_commit_count, 2)

    # 3. author preserved, committer is the merger
    def test_author_preserved_committer_is_merger(self):
        report = self.squash.squash_pull_request(self.admin, "volmarr", "pub", self.pr.number)
        author = git(self.path, "log", "-1", "--format=%an", report.commit_oid)
        committer = git(self.path, "log", "-1", "--format=%cn", report.commit_oid)
        self.assertEqual(author, "volmarr")
        self.assertEqual(committer, "tess")
        self.assertEqual(report.author, "volmarr")
        self.assertEqual(report.merged_by, "tess")

    # 4. edited message: title-only and body-only edits, PR unchanged
    def test_edited_message(self):
        report = self.squash.squash_pull_request(
            self.owner, "volmarr", "pub", self.pr.number,
            message_title="Squashed feature", message_body="")
        message = git(self.path, "log", "-1", "--format=%B", report.commit_oid)
        self.assertEqual(message, "Squashed feature")
        self.assertTrue(report.message_edited)
        pr_row = self.conn.execute("SELECT title, body FROM issues WHERE id = ?", (self.pr.row_id,)).fetchone()
        self.assertEqual(pr_row["title"], "Feature work")
        with self.assertRaises(PullRequestError) as ctx:
            self.squash.squash_pull_request(self.owner, "volmarr", "pub", 999)
        self.assertEqual(ctx.exception.reason, "pull_request_not_found")

    # 5. closings executed on landing
    def test_closings_executed(self):
        issue = self.issues.create_issue(self.owner, "volmarr", "pub", "Bug one")
        pr2 = self.prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch="feature", title="Fix it",
            body=f"Fixes #{issue.number}") if False else None
        # PR already exists for this branch pair in setUp; use its body path:
        # create the closing PR on a fresh branch instead.
        head2 = make_commit(self.path, self.head_oid, {**HEAD_FILES, "c.txt": "c\n"}, "more work")
        git(self.path, "update-ref", "refs/heads/feature2", head2)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch="feature2", title="Fix it",
            body=f"Fixes #{issue.number}")
        report = self.squash.squash_pull_request(self.owner, "volmarr", "pub", pr.number)
        closed = self.issues.get_issue(self.owner, "volmarr", "pub", issue.number)
        self.assertEqual(closed.state, "closed")
        self.assertEqual(closed.state_reason, "completed")
        outcomes = [(c.number, c.outcome) for c in report.closings]
        self.assertIn((issue.number, "closed"), outcomes)
        closings = self.squash.closings_for(self.owner, "volmarr", "pub", pr.number)
        self.assertEqual([(c.number, c.outcome) for c in closings], outcomes)
        self.assertIn("repo.issue.close", self._audit_actions())

    def test_closing_from_head_commit_message_and_edited_message(self):
        i1 = self.issues.create_issue(self.owner, "volmarr", "pub", "Bug A")
        i2 = self.issues.create_issue(self.owner, "volmarr", "pub", "Bug B")
        head2 = make_commit(self.path, self.base_oid, MID_FILES, f"work\n\nFixes #{i1.number}")
        git(self.path, "update-ref", "refs/heads/feature3", head2)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch="feature3", title="Plain", body="")
        report = self.squash.squash_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(self.issues.get_issue(self.owner, "volmarr", "pub", i1.number).state, "closed")
        head3 = make_commit(self.path, self.base_oid, MID_FILES, "more")
        git(self.path, "update-ref", "refs/heads/feature3b", head3)
        pr2 = self.prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch="feature3b", title="Plain2", body="")
        report2 = self.squash.squash_pull_request(
            self.owner, "volmarr", "pub", pr2.number,
            message_body=f"Edited.\n\nCloses #{i2.number}")
        self.assertEqual(self.issues.get_issue(self.owner, "volmarr", "pub", i2.number).state, "closed")
        self.assertTrue(report2.message_edited)

    def test_closing_outcomes_already_closed_and_pr_target(self):
        done = self.issues.create_issue(self.owner, "volmarr", "pub", "Done bug")
        self.issues.close_issue(self.owner, "volmarr", "pub", done.number)
        head2 = make_commit(self.path, self.base_oid, MID_FILES, "work")
        git(self.path, "update-ref", "refs/heads/feature4", head2)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch="feature4", title="T",
            body=f"Fixes #{done.number} and fixes #{self.pr.number}")
        report = self.squash.squash_pull_request(self.owner, "volmarr", "pub", pr.number)
        outcomes = {c.number: c.outcome for c in report.closings}
        self.assertEqual(outcomes.get(done.number), "already_closed")
        self.assertEqual(outcomes.get(self.pr.number), "not_executed_not_an_issue")
        self.assertNotIn(pr.number, outcomes)

    # 6. refusals
    def test_refusals(self):
        with self.assertRaises(PullRequestError) as ctx:
            self.squash.squash_pull_request(self.reader, "volmarr", "pub", self.pr.number)
        self.assertEqual(ctx.exception.reason, "permission_denied")
        self.squash.squash_pull_request(self.owner, "volmarr", "pub", self.pr.number)
        with self.assertRaises(PullRequestError) as ctx:
            self.squash.squash_pull_request(self.owner, "volmarr", "pub", self.pr.number)
        self.assertEqual(ctx.exception.reason, "already_merged")

    def test_draft_refused(self):
        head2 = make_commit(self.path, self.base_oid, MID_FILES, "draft work")
        git(self.path, "update-ref", "refs/heads/feature5", head2)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch="feature5", title="Drafty", draft=True)
        with self.assertRaises(PullRequestError) as ctx:
            self.squash.squash_pull_request(self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(ctx.exception.reason, "pull_request_draft")
        self.assertEqual(self._base_tip(), self.base_oid)

    def test_stale_pins_refused(self):
        with self.assertRaises(PullRequestError) as ctx:
            self.squash.squash_pull_request(
                self.owner, "volmarr", "pub", self.pr.number,
                expected_base_oid="0" * 40)
        self.assertEqual(ctx.exception.reason, "stale_base")
        with self.assertRaises(PullRequestError) as ctx:
            self.squash.squash_pull_request(
                self.owner, "volmarr", "pub", self.pr.number,
                expected_head_oid="0" * 40)
        self.assertEqual(ctx.exception.reason, "stale_head")

    def test_invalid_edited_title_refused_whole(self):
        with self.assertRaises(PullRequestError) as ctx:
            self.squash.squash_pull_request(
                self.owner, "volmarr", "pub", self.pr.number, message_title="")
        self.assertEqual(ctx.exception.reason, "title_required")
        self.assertEqual(self._base_tip(), self.base_oid)

    # 7. conflict refused, nothing lands, nothing closes
    def test_conflict_refused(self):
        issue = self.issues.create_issue(self.owner, "volmarr", "pub", "Bug C")
        base2 = make_commit(self.path, self.base_oid, {"a.txt": "alpha\nBASE\n"}, "base moves")
        git(self.path, "update-ref", "refs/heads/main", base2)
        head2 = make_commit(self.path, self.base_oid, {"a.txt": "alpha\nHEAD\n"}, "head moves")
        git(self.path, "update-ref", "refs/heads/feature6", head2)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch="feature6", title="Conflicting",
            body=f"Fixes #{issue.number}")
        preview = self.squash.preview_squash(self.owner, "volmarr", "pub", pr.number)
        self.assertFalse(preview.can_squash)
        self.assertIn("a.txt", preview.conflicted_files)
        with self.assertRaises(PullRequestError) as ctx:
            self.squash.squash_pull_request(self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(ctx.exception.reason, "merge_conflict")
        self.assertIn("a.txt", str(ctx.exception))
        self.assertEqual(self._base_tip(), base2)
        self.assertEqual(self.issues.get_issue(self.owner, "volmarr", "pub", issue.number).state, "open")
        self.assertIsNone(self.squash.merged_record(self.owner, "volmarr", "pub", pr.number))

    # 8. preview lands nothing
    def test_preview_lands_nothing(self):
        preview = self.squash.preview_squash(self.owner, "volmarr", "pub", self.pr.number)
        self.assertTrue(preview.can_squash)
        self.assertEqual(preview.default_title, "Feature work")
        self.assertIn("add b", preview.default_body)
        self.assertEqual(self._base_tip(), self.base_oid)
        self.assertIsNone(self.squash.merged_record(self.owner, "volmarr", "pub", self.pr.number))

    # 8b. cross-fork squash lands in the base repo, fork untouched
    def test_cross_fork_squash(self):
        xprs = ForkPullRequestStore(self.conn, self.repos, self.accounts, self.issues, audit=self.audit, time_fn=self.clock)
        self.forks.fork(self.reader.id, "volmarr", "pub")
        fork_path = self.repos.path_for("yrsa", "pub")
        fhead = make_commit(fork_path, self.base_oid, {"a.txt": "alpha\nbeta\n", "f.txt": "fork\n"}, "fork work")
        git(fork_path, "update-ref", "refs/heads/feature", fhead)
        pr = xprs.create_cross_fork_pull_request(
            self.reader, "volmarr", "pub", base_branch="main",
            head_owner="yrsa", head_repo="pub", head_branch="feature",
            title="Fork feature", body="")
        report = self.squash.squash_pull_request(self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(self._base_tip(), report.commit_oid)
        self.assertEqual(git(fork_path, "rev-parse", "refs/heads/feature"), fhead)
        refs = git(self.path, "for-each-ref", "refs/samverk/squash")
        self.assertEqual(refs, "")
        author = git(self.path, "log", "-1", "--format=%an", report.commit_oid)
        self.assertEqual(author, "yrsa")

    # 9. taxonomy event detail carries no message text
    def test_audit_detail_has_no_message(self):
        self.squash.squash_pull_request(self.owner, "volmarr", "pub", self.pr.number)
        rows = self.conn.execute("SELECT detail FROM audit_log WHERE action = 'repo.pull_request.squash_merge'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertNotIn("Body text.", rows[0]["detail"])
        self.assertIn('"strategy": "squash"', rows[0]["detail"]) if '"strategy": "squash"' in rows[0]["detail"] else self.assertIn('"strategy":"squash"', rows[0]["detail"])


if __name__ == "__main__":
    unittest.main()
