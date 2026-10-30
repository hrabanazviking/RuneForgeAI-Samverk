"""S-102 acceptance battery: commit list.

Acceptance (roadmap S-102): paginated history for any ref
with author, message, and verification badge slot (Part XV
fills it).

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.commit_list import CommitListError, CommitLister, render_commit_list_page
from samverk.repositories import RepositoryStore
from test_repo_home import run_git

class CommitListTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.stranger = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "samverk", visibility="private")
        self.lister = CommitLister(self.repos)
        bare = self.repos.path_for("volmarr", "samverk")
        work = self.root / "work"; work.mkdir()
        run_git(work, "init", "-b", "main")
        self.oids = []
        for i in range(1, 6):
            (work / "f.txt").write_text(f"line {i}\n", encoding="utf-8")
            run_git(work, "add", ".")
            run_git(work, "commit", "-m", f"step <{i}>", "-m", f"body {i}")
            self.oids.append(run_git(work, "rev-parse", "HEAD"))
        run_git(work, "push", str(bare), "main")

    def test_history_newest_first_with_author_and_message(self):
        listing = self.lister.list(self.owner, "volmarr", "samverk")
        self.assertEqual(listing.total_commits, 5)
        self.assertEqual([c.oid for c in listing.commits],
                         list(reversed(self.oids)))
        head = listing.commits[0]
        self.assertEqual(head.subject, "step <5>")
        self.assertEqual(head.body, "body 5")
        self.assertEqual(head.author_name, "A U Thor")
        self.assertEqual(head.author_email, "a@example.com")
        self.assertEqual(head.parents, (self.oids[3],))
        self.assertEqual(listing.commits[-1].parents, ())
        page = render_commit_list_page(listing)
        self.assertIn("step &lt;5&gt;", page); self.assertNotIn("step <5>", page)

    def test_verification_slot_is_present_and_unfilled(self):
        listing = self.lister.list(self.owner, "volmarr", "samverk")
        self.assertTrue(all(c.verification_badge is None
                            for c in listing.commits))
        page = render_commit_list_page(listing)
        self.assertIn('data-state="not-checked"', page)
        self.assertIn("Not checked", page)
        self.assertNotIn("Verified", page)

    def test_pagination_totals_are_true(self):
        page1 = self.lister.list(self.owner, "volmarr", "samverk",
                                 page=1, per_page=2)
        self.assertEqual([c.subject for c in page1.commits],
                         ["step <5>", "step <4>"])
        self.assertEqual(page1.total_pages, 3); self.assertTrue(page1.has_next)
        page3 = self.lister.list(self.owner, "volmarr", "samverk",
                                 page=3, per_page=2)
        self.assertEqual([c.subject for c in page3.commits], ["step <1>"])
        self.assertFalse(page3.has_next)
        beyond = self.lister.list(self.owner, "volmarr", "samverk",
                                  page=8, per_page=2)
        self.assertEqual(beyond.commits, ()); self.assertEqual(beyond.total_commits, 5)
        html = render_commit_list_page(page1)
        self.assertIn("Page 1 of 3", html); self.assertIn("?page=2", html)

    def test_ref_and_permission_law(self):
        listing = self.lister.list(self.owner, "volmarr", "samverk",
                                   ref=self.oids[1])
        self.assertEqual(listing.total_commits, 2)
        with self.assertRaises(CommitListError) as caught:
            self.lister.list(self.stranger, "volmarr", "samverk")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        with self.assertRaises(CommitListError) as caught:
            self.lister.list(self.owner, "volmarr", "samverk", ref="nope")
        self.assertEqual(caught.exception.reason, "ref_not_found")

if __name__ == "__main__":
    unittest.main()
