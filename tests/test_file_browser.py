"""S-098 acceptance battery: file browser.

Acceptance (roadmap S-098): tree navigation at any ref,
breadcrumb, last-commit-per-entry column.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import os, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.file_browser import BrowseError, FileBrowser, render_tree_page
from samverk.repositories import RepositoryStore
from test_repo_home import GIT_ENV, run_git

class FileBrowserTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.stranger = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "samverk", visibility="private")
        self.browser = FileBrowser(self.repos)
        bare = self.repos.path_for("volmarr", "samverk")
        work = self.root / "work"; work.mkdir()
        run_git(work, "init", "-b", "main")
        (work / "a.txt").write_text("a1\n", encoding="utf-8")
        (work / "src").mkdir(); (work / "src" / "main.py").write_text("x=1\n", encoding="utf-8")
        (work / "src" / "lib.py").write_text("y=2\n", encoding="utf-8")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "first commit")
        (work / "a.txt").write_text("a2\n", encoding="utf-8")
        (work / "b.txt").write_text("b\n", encoding="utf-8")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "second commit")
        run_git(work, "push", str(bare), "main")
        self.first, self.second = run_git(work, "rev-list", "--reverse", "main").splitlines()

    def test_root_listing_with_last_commits(self):
        view = self.browser.browse(self.owner, "volmarr", "samverk")
        self.assertEqual(view.path, "")
        by = {e.name: e for e in view.entries}
        self.assertEqual(set(by), {"a.txt", "b.txt", "src"})
        # directories sort before files
        self.assertEqual(view.entries[0].name, "src")
        self.assertEqual(by["a.txt"].last_commit.subject, "second commit")
        self.assertEqual(by["a.txt"].last_commit.oid, self.second)
        self.assertEqual(by["b.txt"].last_commit.oid, self.second)
        self.assertEqual(by["src"].last_commit.subject, "first commit")
        self.assertEqual(by["src"].last_commit.oid, self.first)
        self.assertIn("A U Thor", by["src"].last_commit.author)

    def test_subdirectory_and_breadcrumb(self):
        view = self.browser.browse(self.owner, "volmarr", "samverk", path="src")
        self.assertEqual({e.name for e in view.entries}, {"main.py", "lib.py"})
        self.assertEqual(view.breadcrumb, (("src", "src"),))
        for e in view.entries:
            self.assertEqual(e.last_commit.subject, "first commit")
        page = render_tree_page(view)
        self.assertIn("/volmarr/samverk/tree/main/src", page)
        self.assertIn("/volmarr/samverk/blob/main/src/main.py", page)
        self.assertIn("first commit", page)

    def test_browse_at_an_older_ref(self):
        view = self.browser.browse(self.owner, "volmarr", "samverk", ref=self.first)
        self.assertEqual({e.name for e in view.entries}, {"a.txt", "src"})
        self.assertEqual(view.commit_oid, self.first)

    def test_path_and_permission_law(self):
        for bad in ("../secret", "src/../a.txt", "/etc", "src//lib.py", "src\\lib.py"):
            with self.assertRaises(BrowseError) as caught:
                self.browser.browse(self.owner, "volmarr", "samverk", path=bad)
            self.assertEqual(caught.exception.reason, "path_invalid", bad)
        with self.assertRaises(BrowseError) as caught:
            self.browser.browse(self.owner, "volmarr", "samverk", path="nope")
        self.assertEqual(caught.exception.reason, "path_not_found")
        with self.assertRaises(BrowseError) as caught:
            self.browser.browse(self.owner, "volmarr", "samverk", path="a.txt")
        self.assertEqual(caught.exception.reason, "path_not_found")
        with self.assertRaises(BrowseError) as caught:
            self.browser.browse(self.stranger, "volmarr", "samverk")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        with self.assertRaises(BrowseError) as caught:
            self.browser.browse(self.owner, "volmarr", "samverk", ref="nope")
        self.assertEqual(caught.exception.reason, "ref_not_found")

    def test_page_escapes_commit_subjects(self):
        bare = self.repos.path_for("volmarr", "samverk")
        work = self.root / "work2"; work.mkdir()
        run_git(work, "clone", str(bare), ".")
        (work / "c.txt").write_text("c\n", encoding="utf-8")
        run_git(work, "add", ".")
        run_git(work, "commit", "-m", "<script>alert(1)</script>")
        run_git(work, "push", "origin", "main")
        page = render_tree_page(self.browser.browse(self.owner, "volmarr", "samverk"))
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)

if __name__ == "__main__":
    unittest.main()
