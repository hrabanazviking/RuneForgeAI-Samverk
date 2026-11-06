"""S-161 acceptance battery: pull request search.

Acceptance (roadmap S-161): PR search — the Part X
qualifier language extended (is:pr, review:, status:).

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.issues import IssueStore
from samverk.labels import LabelStore
from samverk.pull_request_review_assignment import ReviewAssignmentStore
from samverk.pull_request_reviews import PullRequestReviewStore
from samverk.pull_request_search import (
    PullRequestSearch, parse_pr_query, render_pr_search_page)
from samverk.issue_search import SearchError
from samverk.pull_requests import PullRequestError, PullRequestStore
from samverk.repositories import RepositoryStore


def git(repo, *args, input_bytes=None):
    env = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin"}
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         capture_output=True, input=input_bytes, env=env)
    assert out.returncode == 0, out.stderr.decode()
    return out.stdout.decode().strip()


def make_commit(repo, parent, files, message):
    lines = []
    for name in sorted(files):
        blob = git(repo, "hash-object", "-w", "--stdin",
                   input_bytes=files[name].encode())
        lines.append(f"100644 blob {blob}\t{name}\n")
    tree = git(repo, "mktree", input_bytes="".join(lines).encode())
    args = ["commit-tree", tree]
    if parent:
        args += ["-p", parent]
    return git(repo, *args, input_bytes=(message + "\n").encode())


class PullRequestSearchTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.reader = self.accounts.register("yrsa", "correct horse battery")
        self.third = self.accounts.register("tess", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.issues = IssueStore(self.conn, self.repos, self.accounts,
                                 audit=self.audit)
        self.labels = LabelStore(self.conn, self.repos, self.accounts,
                                 self.issues, audit=self.audit)
        self.prs = PullRequestStore(self.conn, self.repos, self.accounts,
                                    self.issues, audit=self.audit)
        self.reviews = PullRequestReviewStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit)
        self.assign = ReviewAssignmentStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit)
        self.search = PullRequestSearch(
            self.conn, self.repos, self.accounts, self.prs,
            self.labels, self.reviews, self.assign)
        self.repos.create_repository(self.owner.id, "volmarr", "pub",
                                     visibility="public")
        self.path = self.repos.path_for("volmarr", "pub")
        base = make_commit(self.path, None, {"a.txt": "alpha\n"}, "base")
        git(self.path, "update-ref", "refs/heads/main", base)
        self._base = base
        self.pr1 = self._open_pr("f1", "Fix crash in parser",
                                 "The parser falls over")
        self.pr2 = self._open_pr("f2", "Add export button",
                                 "Please add CSV export")
        self.pr3 = self._open_pr("f3", "Rework settings page",
                                 "Still being designed", draft=True)
        # PR1: approved by yrsa, then closed.
        self.reviews.submit_review(self.reader, "volmarr", "pub", 1,
                                   verdict="approve", summary="Good.")
        with self.conn:
            self.conn.execute(
                "UPDATE issues SET state = 'closed' WHERE id = ?",
                (self.pr1.row_id,))
        # PR2: yrsa approves then comments (latest wins);
        # tess requests changes.
        self.reviews.submit_review(self.reader, "volmarr", "pub", 2,
                                   verdict="approve", summary="Good.")
        self.reviews.submit_review(self.reader, "volmarr", "pub", 2,
                                   verdict="comment", summary="A note.")
        self.reviews.submit_review(self.third, "volmarr", "pub", 2,
                                   verdict="request_changes",
                                   summary="Needs work.")
        # PR3: no reviews; an active review request for yrsa.
        self.assign.request_reviewers(self.owner, "volmarr", "pub", 3,
                                      ["@yrsa"])
        # Label assignments live on the shared numbered
        # row (issue_labels.issue_id is the PR row in
        # issues). LabelStore.add_to_issue is issue-kind
        # only by design (IssueStore.get_issue refuses
        # pull request numbers), so the battery attaches
        # the label at the row itself.
        repo = self.repos.get_repository("volmarr", "pub")
        bug = self.conn.execute(
            "SELECT id FROM labels WHERE repo_id = ?"
            " AND name_lower = 'bug'", (repo.id,)).fetchone()
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO issue_labels"
                " (issue_id, label_id, created_at)"
                " VALUES (?, ?, 0)", (self.pr1.row_id, bug[0]))

    def _open_pr(self, branch, title, body, draft=False):
        head = make_commit(self.path, self._base,
                           {"a.txt": f"alpha\n{branch}\n"}, branch)
        git(self.path, "update-ref", f"refs/heads/{branch}", head)
        return self.prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch=branch, title=title, body=body, draft=draft)

    def numbers(self, query, viewer=None, repo="pub"):
        return [p.number for p in
                self.search.search(viewer, "volmarr", repo, query)]

    def test_kind_and_state_qualifiers(self):
        self.assertEqual(self.numbers("is:pr"), [1, 2, 3])
        self.assertEqual(self.numbers(""), [1, 2, 3])
        self.assertEqual(self.numbers("is:pr is:open"), [2, 3])
        self.assertEqual(self.numbers("is:closed"), [1])
        self.assertEqual(self.numbers("is:draft"), [3])
        self.assertEqual(self.numbers("is:open is:closed"), [])

    def test_status_qualifier_says_the_whole_position(self):
        self.assertEqual(self.numbers("status:open"), [2])
        self.assertEqual(self.numbers("status:draft"), [3])
        self.assertEqual(self.numbers("status:closed"), [1])
        self.assertEqual(self.numbers("status:open status:draft"), [])
        self.assertEqual(self.numbers("is:open status:draft"), [3])

    def test_review_qualifier_reads_the_latest_verdicts(self):
        self.assertEqual(self.numbers("review:approved"), [1])
        self.assertEqual(self.numbers("review:commented"), [2])
        self.assertEqual(self.numbers("review:changes_requested"), [2])
        self.assertEqual(self.numbers("review:changes-requested"), [2])
        self.assertEqual(self.numbers("review:none"), [3])
        self.assertEqual(self.numbers("review:requested"), [3])
        self.assertEqual(self.numbers("review:none review:requested"), [3])
        self.assertEqual(self.numbers("review:approved review:none"), [])

    def test_text_label_and_author_compose(self):
        self.assertEqual(self.numbers("crash"), [1])
        self.assertEqual(self.numbers("crash is:pr review:approved"), [1])
        self.assertEqual(self.numbers("export status:open"), [2])
        self.assertEqual(self.numbers("label:bug"), [1])
        self.assertEqual(self.numbers("label:bug status:open"), [])
        self.assertEqual(self.numbers("author:volmarr"), [1, 2, 3])
        self.assertEqual(self.numbers("author:yrsa"), [])

    def test_malformed_queries_fail_closed(self):
        for bad in ("is:banana", "is:issue", "review:banana",
                    "status:merged", "status:", "assignee:yrsa",
                    "sort:created-asc", 'label:"unterminated'):
            with self.assertRaises(SearchError) as caught:
                parse_pr_query(bad)
            self.assertEqual(caught.exception.reason, "query_invalid",
                             msg=bad)

    def test_parse_records_the_new_qualifiers(self):
        parsed = parse_pr_query(
            "is:pr review:approved status:open label:bug fix")
        self.assertEqual(parsed.reviews, ("approved",))
        self.assertEqual(parsed.statuses, ("open",))
        self.assertEqual(parsed.labels, ("bug",))
        self.assertEqual(parsed.text_terms, ("fix",))
        self.assertFalse(parsed.is_empty)
        self.assertTrue(parse_pr_query("").is_empty)
        self.assertTrue(parse_pr_query("is:draft").draft_only)

    def test_private_repo_search_answers_uniformly(self):
        self.repos.create_repository(self.owner.id, "volmarr", "priv",
                                     visibility="private")
        with self.assertRaises(PullRequestError) as caught:
            self.search.search(None, "volmarr", "priv", "is:pr")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        self.assertEqual(self.numbers("is:pr", viewer=self.owner,
                                      repo="priv"), [])

    def test_page_renders_form_help_results_and_empty_state(self):
        results = self.search.search(None, "volmarr", "pub", "is:pr")
        page = render_pr_search_page(
            "volmarr", "pub", "is:pr", results,
            review_words={1: "1 review submitted: 1 approved."})
        self.assertIn('value="is:pr"', page)
        self.assertIn("review:approved", page)
        self.assertIn("status:draft", page)
        self.assertIn("#1 Fix crash in parser", page)
        self.assertIn("closed pull request", page)
        self.assertIn("draft pull request", page)
        self.assertIn("1 review submitted: 1 approved.", page)
        empty = render_pr_search_page("volmarr", "pub", "label:nope", [])
        self.assertIn("No pull requests match", empty)

    def test_page_escapes_hostile_query_and_title(self):
        page = render_pr_search_page(
            "volmarr", "pub", '"><script>', self.search.search(
                None, "volmarr", "pub", "is:pr"))
        self.assertNotIn('"><script>', page)
        self.assertIn("&lt;script&gt;", page)


if __name__ == "__main__":
    unittest.main()
