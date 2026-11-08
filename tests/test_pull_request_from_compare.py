"""S-167 acceptance battery: PR from compare.

Acceptance (roadmap S-167): PR from compare — the
compare view (S-105) offers "open pull request" with
context intact.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.compare_view import CompareError, CompareService
from samverk.issues import IssueStore
from samverk.pull_request_from_compare import (
    PullRequestFromCompareStore, render_compare_offer,
    render_compare_page_with_offer)
from samverk.pull_requests import PullRequestError, PullRequestStore
from samverk.refs import RefStore
from samverk.repositories import RepositoryStore
from test_repo_home import run_git


class PullRequestFromCompareTests(unittest.TestCase):
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
        self.from_compare = PullRequestFromCompareStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.compare = CompareService(self.repos)
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")
        bare = self.repos.path_for("volmarr", "pub")
        work = self.root / "work"; work.mkdir()
        run_git(work, "init", "-b", "main")
        (work / "a.txt").write_text("base\n", encoding="utf-8")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "base commit")
        run_git(work, "checkout", "-b", "feature")
        (work / "a.txt").write_text("base\nfeature\n", encoding="utf-8")
        (work / "b.txt").write_text("new <file>\n", encoding="utf-8")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "feature <work>")
        run_git(work, "checkout", "-b", "team/feature")
        (work / "d.txt").write_text("slash\n", encoding="utf-8")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "slash <work>")
        run_git(work, "checkout", "main")
        (work / "c.txt").write_text("main side\n", encoding="utf-8")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "main moves")
        run_git(work, "checkout", "-b", "quiet", "main")
        run_git(work, "tag", "v1", "feature")
        run_git(work, "push", str(bare), "main", "feature", "team/feature", "quiet", "v1")
        self.refs = RefStore(bare)
        self.main_oid = self.refs.resolve("refs/heads/main")
        self.feature_oid = self.refs.resolve("refs/heads/feature")

    def test_offer_carries_the_compare_context(self):
        view = self.compare.compare(self.owner, "volmarr", "pub", "main", "feature")
        offer = self.from_compare.offer(self.owner, "volmarr", "pub", "main", "feature")
        self.assertEqual(offer.compare, view)
        self.assertEqual((offer.base_branch, offer.head_branch), ("main", "feature"))
        self.assertEqual((offer.compare.ahead, offer.compare.behind), (1, 1))
        self.assertTrue(offer.can_open); self.assertEqual(offer.blockers, ())
        self.assertEqual(offer.existing_open_number, 0)
        self.assertEqual(offer.suggested_title, "feature <work>")
        self.assertIn("1 ahead", offer.context_words)
        self.assertIn("1 behind", offer.context_words)
        self.assertIn("files changed", offer.context_words)
        self.assertEqual(offer.creation_url, "/volmarr/pub/pulls/new/main...feature")

    def test_rendered_compare_page_offers_link_with_context(self):
        view = self.compare.compare(self.owner, "volmarr", "pub", "main", "feature")
        offer = self.from_compare.offer(self.owner, "volmarr", "pub", "main", "feature")
        page = render_compare_page_with_offer(view, offer)
        # The S-105 page is whole: its own commit list and totals.
        self.assertIn("feature &lt;work&gt;", page)
        self.assertIn("1 ahead", page)
        # And the offer: the link, the pair, the context, the title.
        self.assertIn('<a class="open-pull-request" href="/volmarr/pub/pulls/new/main...feature">Open pull request</a>', page)
        self.assertIn("feature into main", page)
        self.assertIn("title starts as", page)
        self.assertIn("feature &lt;work&gt;", render_compare_offer(offer))

    def test_open_from_compare_creates_the_compared_pr(self):
        self.issues.create_issue(self.owner, "volmarr", "pub", "An ordinary issue")
        view = self.compare.compare(self.owner, "volmarr", "pub", "main", "feature")
        pr = self.from_compare.open_from_compare(
            self.owner, "volmarr", "pub", "main", "feature")
        self.assertEqual(pr.number, 2)
        self.assertEqual((pr.base_branch, pr.head_branch), ("main", "feature"))
        self.assertEqual((pr.base_oid, pr.head_oid), (view.base_oid, view.head_oid))
        self.assertEqual((pr.base_oid, pr.head_oid), (self.main_oid, self.feature_oid))
        self.assertEqual(pr.title, "feature <work>")
        self.assertEqual(pr.state, "open"); self.assertFalse(pr.is_draft)
        rows = self.conn.execute(
            "SELECT detail FROM audit_log WHERE action = 'repo.pull_request.create'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertIn('"same_repo":true', rows[0]["detail"])
        self.assertIn('"base":"main"', rows[0]["detail"])
        self.assertIn('"head":"feature"', rows[0]["detail"])
        self.assertEqual(
            self.prs.get_pull_request(self.owner, "volmarr", "pub", 2).number, 2)

    def test_open_from_compare_honours_title_body_and_draft(self):
        pr = self.from_compare.open_from_compare(
            self.owner, "volmarr", "pub", "main", "feature",
            title="Ship <it>", body="From the compare page.", draft=True)
        self.assertEqual((pr.title, pr.body), ("Ship <it>", "From the compare page."))
        self.assertTrue(pr.is_draft)
        self.assertEqual(pr.state_words, "draft pull request")

    def test_no_commits_pair_is_words_not_a_button(self):
        before = self.issues.last_number("volmarr", "pub")
        offer = self.from_compare.offer(self.owner, "volmarr", "pub", "main", "quiet")
        self.assertFalse(offer.can_open)
        self.assertIn("no commits", offer.blockers[0])
        html = render_compare_offer(offer)
        self.assertIn("no commits", html)
        self.assertNotIn("open-pull-request", html)
        with self.assertRaises(PullRequestError) as caught:
            self.from_compare.open_from_compare(
                self.owner, "volmarr", "pub", "main", "quiet")
        self.assertEqual(caught.exception.reason, "no_commits")
        self.assertEqual(self.issues.last_number("volmarr", "pub"), before)
        self.assertEqual(self.prs.list_pull_requests(self.owner, "volmarr", "pub"), [])

    def test_same_ref_compare_cannot_open(self):
        offer = self.from_compare.offer(self.owner, "volmarr", "pub", "main", "main")
        self.assertFalse(offer.can_open)
        self.assertTrue(any("no commits" in b for b in offer.blockers))
        with self.assertRaises(PullRequestError) as caught:
            self.from_compare.open_from_compare(
                self.owner, "volmarr", "pub", "main", "main")
        self.assertEqual(caught.exception.reason, "no_commits")

    def test_already_open_pair_names_and_links_the_open_pr(self):
        pr = self.from_compare.open_from_compare(
            self.owner, "volmarr", "pub", "main", "feature")
        offer = self.from_compare.offer(self.owner, "volmarr", "pub", "main", "feature")
        self.assertFalse(offer.can_open)
        self.assertEqual(offer.existing_open_number, pr.number)
        self.assertTrue(any(f"#{pr.number}" in b for b in offer.blockers))
        html = render_compare_offer(offer)
        self.assertIn(f'href="/volmarr/pub/pulls/{pr.number}"', html)
        self.assertIn(f"View pull request #{pr.number}", html)
        with self.assertRaises(PullRequestError) as caught:
            self.from_compare.open_from_compare(
                self.owner, "volmarr", "pub", "main", "feature")
        self.assertEqual(caught.exception.reason, "already_exists")
        self.assertIn(f"#{pr.number}", str(caught.exception))

    def test_tag_and_oid_comparisons_cannot_open(self):
        for base, head in (("main", "v1"), (self.main_oid, self.feature_oid)):
            offer = self.from_compare.offer(self.owner, "volmarr", "pub", base, head)
            self.assertIsNone(offer.creation_url)
            self.assertFalse(offer.can_open)
            self.assertTrue(any("two branches" in b for b in offer.blockers), (base, head))
            self.assertNotIn("open-pull-request", render_compare_offer(offer))
            with self.assertRaises(PullRequestError) as caught:
                self.from_compare.open_from_compare(self.owner, "volmarr", "pub", base, head)
            self.assertEqual(caught.exception.reason, "not_branches")
        self.assertEqual(self.prs.list_pull_requests(self.owner, "volmarr", "pub"), [])

    def test_full_ref_spelling_still_names_the_branch(self):
        offer = self.from_compare.offer(
            self.owner, "volmarr", "pub", "main", "refs/heads/feature")
        self.assertEqual(offer.head_branch, "feature")
        self.assertTrue(offer.can_open)
        pr = self.from_compare.open_from_compare(
            self.owner, "volmarr", "pub", "main", "refs/heads/feature")
        self.assertEqual(pr.head_branch, "feature")

    def test_slash_branch_keeps_its_name_whole(self):
        offer = self.from_compare.offer(self.owner, "volmarr", "pub", "main", "team/feature")
        self.assertEqual(offer.head_branch, "team/feature")
        self.assertTrue(offer.can_open)
        self.assertEqual(offer.creation_url, "/volmarr/pub/pulls/new/main...team/feature")
        pr = self.from_compare.open_from_compare(
            self.owner, "volmarr", "pub", "main", "team/feature")
        self.assertEqual(pr.head_branch, "team/feature")
        self.assertEqual(pr.title, "slash <work>")

    def test_reader_and_anonymous_get_words_not_the_road(self):
        for viewer in (self.reader, None):
            offer = self.from_compare.offer(viewer, "volmarr", "pub", "main", "feature")
            self.assertFalse(offer.can_open)
            self.assertTrue(any("Only a repository writer" in b for b in offer.blockers))
            self.assertNotIn("open-pull-request", render_compare_offer(offer))
        with self.assertRaises(PullRequestError) as caught:
            self.from_compare.open_from_compare(
                self.reader, "volmarr", "pub", "main", "feature")
        self.assertEqual(caught.exception.reason, "permission_denied")

    def test_stranger_to_private_repo_gets_uniform_not_found(self):
        self.repos.create_repository(self.owner.id, "volmarr", "priv", visibility="private")
        with self.assertRaises(CompareError) as caught:
            self.from_compare.offer(self.reader, "volmarr", "priv", "main", "feature")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        with self.assertRaises(CompareError) as caught:
            self.from_compare.open_from_compare(self.reader, "volmarr", "priv", "main", "feature")
        self.assertEqual(caught.exception.reason, "repo_not_found")

    def test_no_migration_no_taxonomy_and_offer_writes_nothing(self):
        self.assertEqual(db.schema_version(self.conn), 88)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 127)
        before = self.conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        offer = self.from_compare.offer(self.owner, "volmarr", "pub", "main", "feature")
        render_compare_offer(offer)
        after = self.conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        self.assertEqual(after, before)
        self.from_compare.open_from_compare(self.owner, "volmarr", "pub", "main", "feature")
        rows = self.conn.execute(
            "SELECT action FROM audit_log").fetchall()
        self.assertEqual(len(rows), before + 1)
        self.assertEqual(rows[-1]["action"], "repo.pull_request.create")


if __name__ == "__main__":
    unittest.main()
