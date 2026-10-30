"""S-137 acceptance battery: issue -> PR conversion path.

Acceptance (roadmap S-137): branch-from-issue shortcut
creating a linked branch and draft PR.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.issue_conversion import (
    ConversionError, IssueConversionStore, render_pull_request)
from samverk.issue_timeline import TimelineStore, describe_event
from samverk.issues import IssueStore
from samverk.refs import RefStore
from samverk.repositories import RepositoryStore
from test_repo_home import run_git


class IssueConversionTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.reader = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.issues = IssueStore(self.conn, self.repos, self.accounts, audit=self.audit)
        self.conv = IssueConversionStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.timeline = TimelineStore(self.conn, self.repos, self.accounts, self.issues)
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")
        # A real base commit on main in the bare store.
        bare = self.repos.path_for("volmarr", "pub")
        work = self.root / "work"; work.mkdir()
        run_git(work, "init", "-b", "main")
        (work / "a.txt").write_text("base\n", encoding="utf-8")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "base commit")
        run_git(work, "push", str(bare), "main")
        self.refs = RefStore(bare)
        self.main_oid = self.refs.resolve("refs/heads/main")
        self.first = self.issues.create_issue(
            self.reader, "volmarr", "pub", "Fix the <crash> on startup")
        self.second = self.issues.create_issue(
            self.owner, "volmarr", "pub", "Add export")

    def test_conversion_creates_linked_branch_and_draft_pr(self):
        pr = self.conv.convert_issue(self.owner, "volmarr", "pub", 1)
        # The PR claims the next shared number (issues are #1, #2).
        self.assertEqual(pr.number, 3)
        self.assertTrue(pr.is_draft)
        self.assertEqual(pr.state_words, "draft pull request")
        self.assertEqual(pr.title, "Fix the <crash> on startup")
        self.assertEqual(pr.source_issue_number, 1)
        self.assertEqual((pr.base_branch, pr.head_branch),
                         ("main", "1-fix-the-crash-on-startup"))
        self.assertEqual(pr.base_oid, self.main_oid)
        self.assertEqual(pr.head_oid, self.main_oid)
        # The branch is real, in git, at the base commit.
        self.assertEqual(
            self.refs.resolve("refs/heads/1-fix-the-crash-on-startup"),
            self.main_oid)
        # The shared sequence knows #3 as a pull request, not an issue.
        item = self.issues.resolve_number("volmarr", "pub", 3)
        self.assertEqual(item.kind, "pull_request")
        with self.assertRaises(Exception):
            self.issues.get_issue(self.owner, "volmarr", "pub", 3)
        # The link reads both ways.
        self.assertEqual(
            self.conv.pull_request_for_issue(
                self.owner, "volmarr", "pub", 1).number, 3)
        self.assertIsNone(
            self.conv.pull_request_for_issue(self.owner, "volmarr", "pub", 2))
        self.assertIn("Draft pull request for #1", pr.body)

    def test_explicit_branch_and_base(self):
        pr = self.conv.convert_issue(
            self.owner, "volmarr", "pub", 2, branch_name="export-work")
        self.assertEqual(pr.head_branch, "export-work")
        self.assertEqual(self.refs.resolve("refs/heads/export-work"),
                         self.main_oid)

    def test_refusals_burn_nothing(self):
        before = self.issues.last_number("volmarr", "pub")
        # Invalid branch name.
        with self.assertRaises(ConversionError) as caught:
            self.conv.convert_issue(self.owner, "volmarr", "pub", 1,
                                    branch_name="bad..name")
        self.assertEqual(caught.exception.reason, "branch_invalid")
        # Missing base branch.
        with self.assertRaises(ConversionError) as caught:
            self.conv.convert_issue(self.owner, "volmarr", "pub", 1,
                                    base_branch="nope")
        self.assertEqual(caught.exception.reason, "base_not_found")
        # A branch that already exists.
        self.refs.create_branch("taken", self.main_oid)
        with self.assertRaises(ConversionError) as caught:
            self.conv.convert_issue(self.owner, "volmarr", "pub", 1,
                                    branch_name="taken")
        self.assertEqual(caught.exception.reason, "branch_taken")
        self.assertEqual(self.issues.last_number("volmarr", "pub"), before)
        self.assertIsNone(
            self.conv.pull_request_for_issue(self.owner, "volmarr", "pub", 1))

    def test_second_conversion_refused(self):
        self.conv.convert_issue(self.owner, "volmarr", "pub", 1)
        with self.assertRaises(ConversionError) as caught:
            self.conv.convert_issue(self.owner, "volmarr", "pub", 1,
                                    branch_name="another")
        self.assertEqual(caught.exception.reason, "already_converted")
        self.assertIn("#3", str(caught.exception))
        self.assertIsNone(self.refs.resolve("refs/heads/another"))

    def test_permissions_and_closed_issue(self):
        # The issue's author is only a reader on a public repo:
        # reporting is not writing, and a branch is a write act.
        with self.assertRaises(ConversionError) as caught:
            self.conv.convert_issue(self.reader, "volmarr", "pub", 1)
        self.assertEqual(caught.exception.reason, "permission_denied")
        # A stranger to a private repo gets the uniform issue answer.
        self.repos.create_repository(self.owner.id, "volmarr", "priv",
                                     visibility="private")
        self.issues.create_issue(self.owner, "volmarr", "priv", "Secret work")
        with self.assertRaises(Exception) as caught:
            self.conv.convert_issue(self.reader, "volmarr", "priv", 1)
        self.assertEqual(caught.exception.reason, "issue_not_found")
        # A closed issue must be reopened first.
        self.issues.close_issue(self.owner, "volmarr", "pub", 2)
        with self.assertRaises(ConversionError) as caught:
            self.conv.convert_issue(self.owner, "volmarr", "pub", 2)
        self.assertEqual(caught.exception.reason, "issue_closed")

    def test_empty_repository_has_no_base(self):
        self.repos.create_repository(self.owner.id, "volmarr", "empty",
                                     visibility="public")
        self.issues.create_issue(self.owner, "volmarr", "empty", "First work")
        with self.assertRaises(ConversionError) as caught:
            self.conv.convert_issue(self.owner, "volmarr", "empty", 1)
        self.assertEqual(caught.exception.reason, "base_not_found")

    def test_audit_and_timeline_say_it_in_words(self):
        self.conv.convert_issue(self.owner, "volmarr", "pub", 1)
        actions = [r["action"] for r in self.conn.execute(
            "SELECT action FROM audit_log WHERE action IN"
            " ('repo.issue.convert', 'repo.pull_request.create') ORDER BY seq")]
        self.assertEqual(actions,
                         ["repo.issue.convert", "repo.pull_request.create"])
        events = self.timeline.timeline_for(self.owner, "volmarr", "pub", 1)
        converted = [e for e in events if e.kind == "converted"]
        self.assertEqual(len(converted), 1)
        words = describe_event(converted[0])
        self.assertIn("1-fix-the-crash-on-startup", words)
        self.assertIn("draft pull request #3", words)

    def test_render_says_draft_in_words_and_escapes(self):
        pr = self.conv.convert_issue(self.owner, "volmarr", "pub", 1)
        html = render_pull_request(pr)
        self.assertIn("draft pull request", html)
        self.assertIn("Fix the &lt;crash&gt; on startup", html)
        self.assertIn("into main", html)
        # A stranger cannot read a private repo's PR.
        self.repos.create_repository(self.owner.id, "volmarr", "priv2",
                                     visibility="private")
        with self.assertRaises(ConversionError) as caught:
            self.conv.get_pull_request(self.reader, "volmarr", "priv2", 1)
        self.assertEqual(caught.exception.reason, "pull_request_not_found")


if __name__ == "__main__":
    unittest.main()
