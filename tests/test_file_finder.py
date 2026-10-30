"""S-110 acceptance battery: file finder.

Acceptance (roadmap S-110): fuzzy path search within a
repo (the `t` habit), keyboard-first.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.file_finder import (FinderError, FileFinder, rank_paths,
                                 render_finder_page, score_path)
from samverk.repositories import RepositoryStore
from test_repo_home import run_git

class FileFinderTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.stranger = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "samverk", visibility="private")
        self.finder = FileFinder(self.repos)
        bare = self.repos.path_for("volmarr", "samverk")
        work = self.root / "work"; work.mkdir()
        run_git(work, "init", "-b", "main")
        files = {
            "README.md": "hi\n",
            "samverk/file_browser.py": "x=1\n",
            "samverk/file_finder.py": "x=2\n",
            "samverk/blob_view.py": "x=3\n",
            "tests/test_file_browser.py": "t=1\n",
            "docs/deep/nested/thing.txt": "deep\n",
        }
        for rel, text in files.items():
            p = work / rel; p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "seed")
        run_git(work, "push", str(bare), "main")

    def test_fuzzy_subsequence_finds_files(self):
        result = self.finder.find(self.owner, "volmarr", "samverk", query="fbrowser")
        paths = [m.path for m in result.matches]
        self.assertIn("samverk/file_browser.py", paths)
        self.assertIn("tests/test_file_browser.py", paths)
        # A query whose letters never appear in order matches nothing.
        result2 = self.finder.find(self.owner, "volmarr", "samverk", query="zzqq")
        self.assertEqual(result2.total_matches, 0)
        self.assertEqual(result2.matches, ())

    def test_ranking_prefers_basename_and_contiguous(self):
        ranked = rank_paths("file_browser", [
            "docs/deep/nested/thing.txt",
            "tests/test_file_browser.py",
            "samverk/file_browser.py",
        ])
        self.assertEqual(ranked[0].path, "samverk/file_browser.py")
        self.assertIsNone(score_path("xyz", "samverk/file_browser.py"))
        self.assertIsNotNone(score_path("sfb", "samverk/file_browser.py"))
        # Case-insensitive.
        result = self.finder.find(self.owner, "volmarr", "samverk", query="README")
        self.assertEqual(result.matches[0].path, "README.md")

    def test_empty_query_lists_all_and_limits_are_named(self):
        result = self.finder.find(self.owner, "volmarr", "samverk", query="")
        self.assertEqual(result.total_files, 6)
        self.assertEqual(result.total_matches, 6)
        self.assertFalse(result.truncated)
        limited = self.finder.find(self.owner, "volmarr", "samverk", query="", limit=2)
        self.assertEqual(len(limited.matches), 2)
        self.assertTrue(limited.truncated)
        self.assertEqual(limited.total_matches, 6)
        page = render_finder_page(limited)
        self.assertIn("Showing 2 of 6", page)
        self.assertIn("More files match than are shown", page)

    def test_page_is_keyboard_first_and_escaped(self):
        evil = self.finder.find(self.owner, "volmarr", "samverk", query="file")
        page = render_finder_page(evil)
        self.assertIn("autofocus", page)
        self.assertIn("<kbd>t</kbd>", page)
        self.assertIn("/volmarr/samverk/blob/main/samverk/file_browser.py", page)
        with self.assertRaises(FinderError) as caught:
            self.finder.find(self.owner, "volmarr", "samverk", query="x" * 201)
        self.assertEqual(caught.exception.reason, "query_too_long")

    def test_permission_and_ref_law(self):
        with self.assertRaises(FinderError) as caught:
            self.finder.find(self.stranger, "volmarr", "samverk", query="file")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        with self.assertRaises(FinderError) as caught:
            self.finder.find(None, "volmarr", "samverk", query="file")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        with self.assertRaises(FinderError) as caught:
            self.finder.find(self.owner, "volmarr", "samverk", query="file", ref="nope")
        self.assertEqual(caught.exception.reason, "ref_not_found")
        with self.assertRaises(FinderError) as caught:
            self.finder.find(self.owner, "volmarr", "missing", query="file")
        self.assertEqual(caught.exception.reason, "repo_not_found")

if __name__ == "__main__":
    unittest.main()
