"""S-135 acceptance battery: issue search UI.

Acceptance (roadmap S-135): qualifier language subset
(is:open, label:, author:, assignee:, milestone:) with
the full grammar documented in research file 19.

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
from samverk.issue_search import (
    IssueSearch, SearchError, parse_query, render_search_page)
from samverk.issues import IssueStore
from samverk.labels import LabelStore
from samverk.milestones import MilestoneStore
from samverk.repositories import RepositoryStore


class IssueSearchTests(unittest.TestCase):
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
        self.milestones = MilestoneStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.search = IssueSearch(
            self.conn, self.repos, self.accounts, self.issues,
            self.labels, self.assignees)
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")
        self.issues.create_issue(self.reader, "volmarr", "pub",
                                 "Crash on startup", "It falls over")
        self.issues.create_issue(self.owner, "volmarr", "pub",
                                 "Add export", "Please add CSV export")
        self.issues.create_issue(self.owner, "volmarr", "pub",
                                 "Crash in export", "Export falls over too")
        self.labels.add_to_issue(self.owner, "volmarr", "pub", 1, "bug")
        self.labels.add_to_issue(self.owner, "volmarr", "pub", 3, "bug")
        self.labels.add_to_issue(self.owner, "volmarr", "pub", 3,
                                 "good first issue")
        self.assignees.assign(self.owner, "volmarr", "pub", 2, "yrsa")
        self.milestones.create_milestone(self.owner, "volmarr", "pub", "Launch 1")
        self.milestones.set_issue_milestone(self.owner, "volmarr", "pub", 2, "Launch 1")
        self.issues.close_issue(self.owner, "volmarr", "pub", 3)

    def numbers(self, query, viewer=None, repo="pub"):
        return [i.number for i in self.search.search(viewer, "volmarr", repo, query)]

    def test_state_and_kind_qualifiers(self):
        self.assertEqual(self.numbers("is:open"), [1, 2])
        self.assertEqual(self.numbers("is:closed"), [3])
        self.assertEqual(self.numbers("is:issue is:open"), [1, 2])
        self.assertEqual(self.numbers("is:open is:closed"), [])
        self.assertEqual(self.numbers(""), [1, 2, 3])

    def test_label_author_assignee_milestone_qualifiers(self):
        self.assertEqual(self.numbers("label:bug"), [1, 3])
        self.assertEqual(self.numbers('label:"good first issue"'), [3])
        self.assertEqual(self.numbers("label:bug label:enhancement"), [])
        self.assertEqual(self.numbers("author:yrsa"), [1])
        self.assertEqual(self.numbers("author:VOLMARR"), [2, 3])
        self.assertEqual(self.numbers("assignee:yrsa"), [2])
        self.assertEqual(self.numbers('milestone:"Launch 1"'), [2])
        self.assertEqual(self.numbers("label:nope"), [])

    def test_free_text_and_composition(self):
        self.assertEqual(self.numbers("crash"), [1, 3])
        self.assertEqual(self.numbers("crash is:open"), [1])
        self.assertEqual(self.numbers('"falls over" label:bug'), [1, 3])
        self.assertEqual(self.numbers("export author:volmarr is:closed"), [3])

    def test_malformed_queries_fail_closed(self):
        for bad in ("is:banana", "label:", "repo:volmarr/pub",
                    'label:"unterminated', "sort:created-asc"):
            with self.assertRaises(SearchError) as caught:
                parse_query(bad)
            self.assertEqual(caught.exception.reason, "query_invalid", msg=bad)

    def test_private_repo_search_is_uniform_not_found(self):
        self.repos.create_repository(self.owner.id, "volmarr", "priv",
                                     visibility="private")
        self.issues.create_issue(self.owner, "volmarr", "priv", "Secret crash")
        from samverk.issues import IssueError
        with self.assertRaises(IssueError) as caught:
            self.search.search(None, "volmarr", "priv", "crash")
        self.assertEqual(caught.exception.reason, "issue_not_found")
        self.assertEqual(self.numbers("crash", viewer=self.owner, repo="priv"), [1])

    def test_page_renders_form_help_results_and_empty_state(self):
        results = self.search.search(None, "volmarr", "pub", "label:bug")
        page = render_search_page("volmarr", "pub", "label:bug", results)
        self.assertIn('value="label:bug"', page)
        self.assertIn("is:open / is:closed", page)
        self.assertIn("#1 Crash on startup", page)
        self.assertIn("closed as completed", page)
        empty = render_search_page("volmarr", "pub", "label:nope", [])
        self.assertIn("No issues match", empty)

    def test_page_escapes_hostile_query_and_title(self):
        self.issues.create_issue(self.owner, "volmarr", "pub",
                                 "<script>alert(1)</script>")
        results = self.search.search(None, "volmarr", "pub", "<script>")
        page = render_search_page("volmarr", "pub", '"><script>', results)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_grammar_is_documented_in_research_19(self):
        text = (Path(__file__).resolve().parent.parent
                / "research" / "19-issue-search-and-queries.md").read_text()
        for needle in ("is:", "label:", "author:", "assignee:",
                       "milestone:", "S-206", "query_invalid"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
