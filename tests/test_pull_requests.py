"""S-141 acceptance battery: pull request creation, same-repo.

Acceptance (roadmap S-141): PR creation, same-repo —
base/head branch pickers with compare preview (S-105)
before opening.

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
from samverk.issues import IssueStore
from samverk.pull_requests import (
    PullRequestError, PullRequestStore, render_creation_page)
from samverk.refs import RefStore
from samverk.repositories import RepositoryStore
from test_repo_home import run_git


class PullRequestCreationTests(unittest.TestCase):
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
        self.prs = PullRequestStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")
        bare = self.repos.path_for("volmarr", "pub")
        work = self.root / "work"; work.mkdir()
        run_git(work, "init", "-b", "main")
        (work / "a.txt").write_text("base\n", encoding="utf-8")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "base commit")
        run_git(work, "checkout", "-b", "feature")
        (work / "a.txt").write_text("base\nfeature <work>\n", encoding="utf-8")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "feature <work>")
        run_git(work, "checkout", "-b", "quiet", "main")
        run_git(work, "push", str(bare), "main", "feature", "quiet")
        self.refs = RefStore(bare)
        self.feature_oid = self.refs.resolve("refs/heads/feature")
        self.main_oid = self.refs.resolve("refs/heads/main")
        self.issues.create_issue(self.owner, "volmarr", "pub", "An ordinary issue")

    def test_pickers_list_real_branches(self):
        self.assertEqual(
            self.prs.branch_names(self.owner, "volmarr", "pub"),
            ("feature", "main", "quiet"))

    def test_preview_is_the_compare_with_blockers_in_words(self):
        preview = self.prs.preview_creation(
            self.owner, "volmarr", "pub", "main", "feature")
        self.assertTrue(preview.can_open)
        self.assertEqual(preview.blockers, ())
        self.assertEqual((preview.compare.ahead, preview.compare.behind), (1, 0))
        self.assertEqual(preview.compare.files_changed, 1)
        self.assertEqual(preview.suggested_title, "feature <work>")
        page = render_creation_page(preview)
        self.assertIn('<select name="base_branch">', page)
        self.assertIn('<select name="head_branch">', page)
        self.assertIn('<option value="main" selected>', page)
        self.assertIn("feature &lt;work&gt;", page)
        self.assertIn("Open pull request", page)
        # A no-commits pair previews its blocker instead of the button.
        blocked = self.prs.preview_creation(
            self.owner, "volmarr", "pub", "main", "quiet")
        self.assertFalse(blocked.can_open)
        self.assertIn("no commits", blocked.blockers[0])
        blocked_page = render_creation_page(blocked)
        self.assertIn("no commits", blocked_page)
        self.assertNotIn("Open pull request</button>", blocked_page)

    def test_creation_claims_shared_number_and_records_pair(self):
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "pub",
            base_branch="main", head_branch="feature")
        # The issue in setUp is #1; the PR claims the shared next number.
        self.assertEqual(pr.number, 2)
        self.assertFalse(pr.is_draft)
        self.assertEqual(pr.state_words, "open pull request")
        self.assertEqual(pr.title, "feature <work>")  # default: head subject
        self.assertEqual((pr.base_branch, pr.head_branch), ("main", "feature"))
        self.assertEqual((pr.base_oid, pr.head_oid),
                         (self.main_oid, self.feature_oid))
        self.assertEqual(pr.source_issue_number, 0)
        item = self.issues.resolve_number("volmarr", "pub", 2)
        self.assertEqual(item.kind, "pull_request")
        listed = self.prs.list_pull_requests(self.reader, "volmarr", "pub")
        self.assertEqual([p.number for p in listed], [2])
        rows = self.conn.execute(
            "SELECT action, detail FROM audit_log"
            " WHERE action = 'repo.pull_request.create'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertIn('"same_repo":true', rows[0]["detail"])

    def test_explicit_title_and_body(self):
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch="feature", title="Ship <it>", body="Notes.")
        self.assertEqual((pr.title, pr.body), ("Ship <it>", "Notes."))

    def test_refusals_burn_nothing(self):
        before = self.issues.last_number("volmarr", "pub")
        cases = [
            (dict(base_branch="main", head_branch="main"), "same_branch"),
            (dict(base_branch="nope", head_branch="feature"), "base_not_found"),
            (dict(base_branch="main", head_branch="nope"), "head_not_found"),
            (dict(base_branch="main", head_branch="quiet"), "no_commits"),
            (dict(base_branch="bad..name", head_branch="feature"), "branch_invalid"),
            (dict(base_branch="main", head_branch="feature", title="  "),
             "title_required"),
        ]
        for kwargs, reason in cases:
            with self.assertRaises(PullRequestError) as caught:
                self.prs.create_pull_request(self.owner, "volmarr", "pub", **kwargs)
            self.assertEqual(caught.exception.reason, reason, kwargs)
        self.assertEqual(self.issues.last_number("volmarr", "pub"), before)
        self.assertEqual(self.prs.list_pull_requests(
            self.owner, "volmarr", "pub"), [])

    def test_second_open_for_same_pair_refused(self):
        self.prs.create_pull_request(
            self.owner, "volmarr", "pub",
            base_branch="main", head_branch="feature")
        with self.assertRaises(PullRequestError) as caught:
            self.prs.create_pull_request(
                self.owner, "volmarr", "pub",
                base_branch="main", head_branch="feature")
        self.assertEqual(caught.exception.reason, "already_exists")
        self.assertIn("#2", str(caught.exception))
        preview = self.prs.preview_creation(
            self.owner, "volmarr", "pub", "main", "feature")
        self.assertFalse(preview.can_open)
        self.assertIn("#2", preview.blockers[0])

    def test_permissions(self):
        # A reader on a public repo cannot open from a same-repo branch.
        with self.assertRaises(PullRequestError) as caught:
            self.prs.create_pull_request(
                self.reader, "volmarr", "pub",
                base_branch="main", head_branch="feature")
        self.assertEqual(caught.exception.reason, "permission_denied")
        # A stranger to a private repo gets the uniform answer everywhere.
        self.repos.create_repository(self.owner.id, "volmarr", "priv",
                                     visibility="private")
        for call in (
                lambda: self.prs.branch_names(self.reader, "volmarr", "priv"),
                lambda: self.prs.create_pull_request(
                    self.reader, "volmarr", "priv",
                    base_branch="main", head_branch="feature"),
                lambda: self.prs.get_pull_request(
                    self.reader, "volmarr", "priv", 1)):
            with self.assertRaises(PullRequestError):
                call()
        with self.assertRaises(PullRequestError) as caught:
            self.prs.get_pull_request(self.reader, "volmarr", "priv", 1)
        self.assertEqual(caught.exception.reason, "pull_request_not_found")

    def test_preview_pair_refusals(self):
        with self.assertRaises(PullRequestError) as caught:
            self.prs.preview_creation(self.owner, "volmarr", "pub", "main", "main")
        self.assertEqual(caught.exception.reason, "same_branch")
        with self.assertRaises(PullRequestError) as caught:
            self.prs.preview_creation(self.owner, "volmarr", "pub", "main", "nope")
        self.assertEqual(caught.exception.reason, "head_not_found")


if __name__ == "__main__":
    unittest.main()
