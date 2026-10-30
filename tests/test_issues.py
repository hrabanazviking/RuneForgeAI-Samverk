"""S-122 acceptance battery: issue create/read/update.

Acceptance (roadmap S-122): title, Markdown body, author,
state; commit-before-answer under concurrent edits.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.issues import IssueError, IssueStore
from samverk.repositories import RepositoryStore

class IssueCrudTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.reader = self.accounts.register("yrsa", "correct horse battery")
        self.stranger = self.accounts.register("mallory", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.issues = IssueStore(self.conn, self.repos, self.accounts, audit=self.audit)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")

    def test_create_assigns_shared_number_and_open_state(self):
        first = self.issues.create_issue(
            self.reader, "volmarr", "pub", "  First bug  ", "It **breaks**.")
        self.assertEqual(first.number, 1); self.assertEqual(first.ref, "#1")
        self.assertEqual(first.title, "First bug")  # stripped
        self.assertEqual(first.body, "It **breaks**.")
        self.assertEqual(first.state, "open"); self.assertEqual(first.version, 1)
        self.assertEqual(first.author_id, self.reader.id)
        pr = self.issues.claim_number("volmarr", "pub", "pull_request", self.owner.id)
        second = self.issues.create_issue(self.owner, "volmarr", "pub", "Second")
        self.assertEqual((pr.number, second.number), (2, 3))  # shared sequence
        actions = [r["action"] for r in self.conn.execute(
            "SELECT action FROM audit_log WHERE action LIKE 'repo.issue%'")]
        self.assertEqual(actions.count("repo.issue.create"), 2)

    def test_title_and_body_law(self):
        for title, reason in (("", "title_required"), ("   ", "title_required"),
                              (None, "title_required"),
                              ("x" * 257, "title_invalid"),
                              ("bad\x00title", "title_invalid")):
            with self.assertRaises(IssueError) as caught:
                self.issues.create_issue(self.owner, "volmarr", "pub", title)
            self.assertEqual(caught.exception.reason, reason)
        with self.assertRaises(IssueError) as caught:
            self.issues.create_issue(
                self.owner, "volmarr", "pub", "T", "x" * 65537)
        self.assertEqual(caught.exception.reason, "body_invalid")
        self.assertEqual(self.issues.last_number("volmarr", "pub"), 0)

    def test_reads_follow_repo_permission_and_hide_private(self):
        pub = self.issues.create_issue(self.owner, "volmarr", "pub", "Public one")
        priv = self.issues.create_issue(self.owner, "volmarr", "priv", "Secret one")
        self.assertEqual(
            self.issues.get_issue(None, "volmarr", "pub", pub.number).title,
            "Public one")
        for viewer in (None, self.stranger):
            with self.assertRaises(IssueError) as caught:
                self.issues.get_issue(viewer, "volmarr", "priv", priv.number)
            self.assertEqual(caught.exception.reason, "issue_not_found")
        # A PR's number is not an issue, and a missing number is the
        # same answer — no enumeration oracle.
        pr = self.issues.claim_number("volmarr", "pub", "pull_request", self.owner.id)
        for number in (pr.number, 999):
            with self.assertRaises(IssueError) as caught:
                self.issues.get_issue(self.owner, "volmarr", "pub", number)
            self.assertEqual(caught.exception.reason, "issue_not_found")
        with self.assertRaises(IssueError):
            self.issues.create_issue(self.stranger, "volmarr", "priv", "Nope")

    def test_list_filters_by_state(self):
        self.issues.create_issue(self.owner, "volmarr", "pub", "One")
        two = self.issues.create_issue(self.owner, "volmarr", "pub", "Two")
        with self.conn:
            self.conn.execute(
                "UPDATE issues SET state = 'closed' WHERE id = ?", (two.id,))
        self.assertEqual(
            [i.title for i in self.issues.list_issues(None, "volmarr", "pub")],
            ["One", "Two"])
        self.assertEqual(
            [i.title for i in self.issues.list_issues(
                None, "volmarr", "pub", state="open")], ["One"])
        self.assertEqual(
            [i.title for i in self.issues.list_issues(
                None, "volmarr", "pub", state="closed")], ["Two"])
        with self.assertRaises(IssueError) as caught:
            self.issues.list_issues(None, "volmarr", "pub", state="weird")
        self.assertEqual(caught.exception.reason, "state_invalid")

    def test_update_by_author_and_writer_not_by_reader(self):
        issue = self.issues.create_issue(
            self.reader, "volmarr", "pub", "Old title", "old body")
        edited = self.issues.update_issue(
            self.reader, "volmarr", "pub", issue.number,
            title="New title", body="new body")
        self.assertEqual((edited.title, edited.body, edited.version),
                         ("New title", "new body", 2))
        by_owner = self.issues.update_issue(
            self.owner, "volmarr", "pub", issue.number, title="Owner edit")
        self.assertEqual(by_owner.version, 3)
        with self.assertRaises(IssueError) as caught:
            self.issues.update_issue(
                self.stranger, "volmarr", "pub", issue.number, title="Hijack")
        self.assertEqual(caught.exception.reason, "permission_denied")
        self.assertEqual(
            self.issues.get_issue(None, "volmarr", "pub", issue.number).title,
            "Owner edit")

    def test_stale_expected_version_conflicts_and_changes_nothing(self):
        issue = self.issues.create_issue(self.owner, "volmarr", "pub", "Base")
        self.issues.update_issue(
            self.owner, "volmarr", "pub", issue.number,
            title="First edit", expected_version=1)
        with self.assertRaises(IssueError) as caught:
            self.issues.update_issue(
                self.owner, "volmarr", "pub", issue.number,
                title="Stale edit", expected_version=1)
        self.assertEqual(caught.exception.reason, "edit_conflict")
        current = self.issues.get_issue(self.owner, "volmarr", "pub", issue.number)
        self.assertEqual((current.title, current.version), ("First edit", 2))

    def test_created_issue_is_visible_to_a_second_connection(self):
        # Commit-before-answer: a fresh connection sees the issue
        # the moment create_issue returns.
        issue = self.issues.create_issue(self.owner, "volmarr", "pub", "Durable")
        other = db.init_db(self.root / "samverk.db"); self.addCleanup(other.close)
        store = IssueStore(other, RepositoryStore(other, self.root,
                                                  AccountStore(other)),
                           AccountStore(other))
        seen = store.get_issue(self.owner, "volmarr", "pub", issue.number)
        self.assertEqual(seen.title, "Durable")

if __name__ == "__main__":
    unittest.main()
