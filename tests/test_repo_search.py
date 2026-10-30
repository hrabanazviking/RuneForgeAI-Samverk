"""S-118 acceptance battery: search box in repo scope.

Acceptance (roadmap S-118): a search box in repo scope
that jumps to Part X's code search pre-filtered to the
repo.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.repo_search import (SearchBoxError, clean_terms,
                                 extract_repo_scope, render_repo_search_box,
                                 repo_search_url, scoped_query,
                                 search_box_for)
from samverk.repositories import RepositoryStore

class RepoSearchTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.stranger = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "priv", visibility="private")
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")

    def test_jump_url_is_prefiltered_code_search(self):
        url = repo_search_url("volmarr", "samverk", "hello world")
        parsed = urlparse(url)
        self.assertEqual(parsed.path, "/search")
        params = parse_qs(parsed.query)
        self.assertEqual(params["q"], ["repo:volmarr/samverk hello world"])
        self.assertEqual(params["type"], ["code"])
        self.assertEqual(scoped_query("volmarr", "samverk"),
                         "repo:volmarr/samverk")
        self.assertEqual(scoped_query("volmarr", "samverk", "  a\t b\n c "),
                         "repo:volmarr/samverk a b c")
        self.assertEqual(clean_terms("a\x00b\x7fc"), "abc")

    def test_scope_extraction_round_trips_and_refuses_malformed(self):
        self.assertEqual(
            extract_repo_scope("repo:volmarr/samverk hello world"),
            ("volmarr", "samverk", "hello world"))
        self.assertEqual(
            extract_repo_scope("hello repo:volmarr/samverk world"),
            ("volmarr", "samverk", "hello world"))
        self.assertIsNone(extract_repo_scope("just words"))
        self.assertIsNone(extract_repo_scope(""))
        for bad in ("repo:", "repo:volmarr", "repo:a/b/c", "repo:../x"):
            with self.assertRaises(SearchBoxError, msg=bad) as caught:
                extract_repo_scope(bad)
            self.assertIn(caught.exception.reason,
                          ("scope_invalid", "name_invalid"), bad)

    def test_box_shows_its_scope_and_escapes_terms(self):
        box = render_repo_search_box("volmarr", "samverk")
        self.assertIn('action="/search"', box)
        self.assertIn('method="get"', box)
        self.assertIn('name="q"', box)
        self.assertIn('value="repo:volmarr/samverk "', box)
        self.assertIn('name="type" value="code"', box)
        self.assertIn("Search this repository", box)
        self.assertIn("Searching only volmarr/samverk", box)
        self.assertIn("delete the repo:volmarr/samverk part", box)
        hostile = render_repo_search_box(
            "volmarr", "samverk", terms='"><script>alert(1)</script>')
        self.assertNotIn("<script>", hostile)
        self.assertIn("&lt;script&gt;", hostile)
        self.assertIn("repo:volmarr/samverk", hostile)

    def test_permission_law_no_box_for_strangers(self):
        with self.assertRaises(SearchBoxError) as caught:
            search_box_for(self.repos, self.stranger, "volmarr", "priv")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        with self.assertRaises(SearchBoxError):
            search_box_for(self.repos, None, "volmarr", "priv")
        with self.assertRaises(SearchBoxError):
            search_box_for(self.repos, self.owner, "volmarr", "missing")
        self.assertIn("repo:volmarr/priv",
                      search_box_for(self.repos, self.owner, "volmarr", "priv"))
        self.assertIn("repo:volmarr/pub",
                      search_box_for(self.repos, None, "volmarr", "pub"))

    def test_names_ride_the_s013_law(self):
        with self.assertRaises(SearchBoxError):
            repo_search_url("bad name", "samverk")
        with self.assertRaises(SearchBoxError):
            render_repo_search_box("volmarr", "..")
        self.assertIn("repo%3Avolmarr%2Fsamverk",
                      repo_search_url("volmarr", "samverk"))

if __name__ == "__main__":
    unittest.main()
