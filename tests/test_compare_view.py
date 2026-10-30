"""S-105 acceptance battery: compare view.

Acceptance (roadmap S-105): any two refs compared
(commits + files changed), the pre-PR workhorse.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.compare_view import CompareError, CompareService, render_compare_page
from samverk.repositories import RepositoryStore
from test_repo_home import run_git

class CompareViewTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.stranger = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "samverk", visibility="private")
        self.service = CompareService(self.repos)
        bare = self.repos.path_for("volmarr", "samverk")
        work = self.root / "work"; work.mkdir()
        run_git(work, "init", "-b", "main")
        (work / "a.txt").write_text("base\n", encoding="utf-8")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "base commit")
        run_git(work, "checkout", "-b", "feature")
        (work / "a.txt").write_text("base\nfeature\n", encoding="utf-8")
        (work / "b.txt").write_text("new <file>\n", encoding="utf-8")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "feature <work>")
        run_git(work, "checkout", "main")
        (work / "c.txt").write_text("main side\n", encoding="utf-8")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "main moves")
        run_git(work, "push", str(bare), "main", "feature")

    def test_compare_counts_commits_and_files(self):
        view = self.service.compare(self.owner, "volmarr", "samverk",
                                    "main", "feature")
        self.assertEqual(view.ahead, 1); self.assertEqual(view.behind, 1)
        self.assertEqual([c.subject for c in view.commits], ["feature <work>"])
        # a.txt grows, b.txt is new, and c.txt (main-side) is
        # absent on feature — three files changed, +2 / −1.
        self.assertEqual(view.files_changed, 3)
        self.assertEqual(view.diff.additions, 2)
        self.assertEqual(view.diff.deletions, 1)
        page = render_compare_page(view)
        self.assertIn("1 ahead", page); self.assertIn("1 behind", page)
        self.assertIn("feature &lt;work&gt;", page)
        self.assertIn("new &lt;file&gt;", page)

    def test_same_ref_is_a_true_empty_compare(self):
        view = self.service.compare(self.owner, "volmarr", "samverk",
                                    "main", "main")
        self.assertEqual((view.ahead, view.behind, view.files_changed), (0, 0, 0))
        self.assertIn("same commit", render_compare_page(view))

    def test_ref_and_permission_law(self):
        with self.assertRaises(CompareError) as caught:
            self.service.compare(self.stranger, "volmarr", "samverk",
                                 "main", "feature")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        with self.assertRaises(CompareError) as caught:
            self.service.compare(self.owner, "volmarr", "samverk",
                                 "main", "nope")
        self.assertEqual(caught.exception.reason, "ref_not_found")

if __name__ == "__main__":
    unittest.main()
