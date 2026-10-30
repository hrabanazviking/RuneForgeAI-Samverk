"""S-136 acceptance battery: saved filters.

Acceptance (roadmap S-136): per-user saved searches for
issues and PRs, shown in the sidebar.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.assignees import AssigneeStore
from samverk.audit import AuditLog
from samverk.issue_search import IssueSearch
from samverk.issues import IssueStore
from samverk.labels import LabelStore
from samverk.repositories import RepositoryStore
from samverk.saved_filters import (
    SavedFilterError, SavedFilterStore, render_sidebar)


class SavedFilterTests(unittest.TestCase):
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
        self.labels = LabelStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.assignees = AssigneeStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        search = IssueSearch(self.conn, self.repos, self.accounts,
                             self.issues, self.labels, self.assignees)
        self.filters = SavedFilterStore(
            self.conn, self.repos, self.accounts, search)
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")
        self.issues.create_issue(self.reader, "volmarr", "pub", "Crash on startup")
        self.issues.create_issue(self.owner, "volmarr", "pub", "Add export")
        self.labels.add_to_issue(self.owner, "volmarr", "pub", 1, "bug")

    def test_save_list_and_run(self):
        saved = self.filters.save_filter(
            self.reader, "volmarr", "pub", "My bugs", "label:bug is:open")
        self.assertEqual(saved.query, "label:bug is:open")
        listed = self.filters.list_filters(self.reader, "volmarr", "pub")
        self.assertEqual([f.name for f in listed], ["My bugs"])
        ran = self.filters.run_filter(self.reader, "volmarr", "pub", "my bugs")
        self.assertEqual([i.number for i in ran], [1])

    def test_filters_are_personal(self):
        self.filters.save_filter(self.reader, "volmarr", "pub", "Mine", "is:open")
        self.assertEqual(self.filters.list_filters(self.owner, "volmarr", "pub"), [])
        with self.assertRaises(SavedFilterError) as caught:
            self.filters.get_filter(self.owner, "volmarr", "pub", "Mine")
        self.assertEqual(caught.exception.reason, "filter_not_found")
        # The same name is free for another account.
        self.filters.save_filter(self.owner, "volmarr", "pub", "Mine", "is:closed")
        with self.assertRaises(SavedFilterError) as caught:
            self.filters.save_filter(self.reader, "volmarr", "pub", "MINE", "is:open")
        self.assertEqual(caught.exception.reason, "name_taken")

    def test_invalid_query_refused_at_save(self):
        for bad in ("is:banana", "repo:x/y"):
            with self.assertRaises(SavedFilterError) as caught:
                self.filters.save_filter(self.reader, "volmarr", "pub", "Bad", bad)
            self.assertEqual(caught.exception.reason, "query_invalid")
        self.assertEqual(self.filters.list_filters(self.reader, "volmarr", "pub"), [])

    def test_targets_and_delete(self):
        self.filters.save_filter(self.reader, "volmarr", "pub", "PRs", "is:open",
                                 target="pull_requests")
        self.assertEqual(
            [f.name for f in self.filters.list_filters(
                self.reader, "volmarr", "pub", target="pull_requests")], ["PRs"])
        self.assertEqual(
            self.filters.list_filters(self.reader, "volmarr", "pub", target="issues"), [])
        with self.assertRaises(SavedFilterError) as caught:
            self.filters.save_filter(self.reader, "volmarr", "pub", "X", "is:open",
                                     target="wiki")
        self.assertEqual(caught.exception.reason, "target_invalid")
        self.filters.delete_filter(self.reader, "volmarr", "pub", "PRs")
        self.assertEqual(self.filters.list_filters(self.reader, "volmarr", "pub"), [])

    def test_sidebar_groups_and_escapes(self):
        self.filters.save_filter(self.reader, "volmarr", "pub",
                                 "Open <bugs>", "label:bug is:open")
        self.filters.save_filter(self.reader, "volmarr", "pub", "Reviews",
                                 "is:open", target="pull_requests")
        html = render_sidebar("volmarr", "pub",
                              self.filters.list_filters(self.reader, "volmarr", "pub"))
        self.assertIn("Issues", html)
        self.assertIn("Pull requests", html)
        self.assertIn("Open &lt;bugs&gt;", html)
        self.assertIn("issues?q=label%3Abug%20is%3Aopen", html)
        self.assertIn("No saved filters yet",
                      render_sidebar("volmarr", "pub", []))

    def test_private_repo_filters_follow_read_gate(self):
        self.repos.create_repository(self.owner.id, "volmarr", "priv",
                                     visibility="private")
        with self.assertRaises(SavedFilterError) as caught:
            self.filters.save_filter(self.reader, "volmarr", "priv", "X", "is:open")
        self.assertEqual(caught.exception.reason, "repo_not_found")


if __name__ == "__main__":
    unittest.main()
