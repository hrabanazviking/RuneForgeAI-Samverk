"""S-117 acceptance battery: deep links.

Acceptance (roadmap S-117): every view URL-addressable
(file@ref#line, commit, compare) so links in chat and
issues land exactly.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.blob_view import BlobViewer
from samverk.deep_links import (DeepLinkError, blame_url, blob_url,
                                commit_url, commits_url, compare_url,
                                home_url, parse_deep_link,
                                parse_file_shorthand, plain_url, raw_url,
                                tree_url)
from samverk.repositories import RepositoryStore
from test_repo_home import run_git

OID = "0123456789abcdef0123456789abcdef01234567"

class DeepLinkTests(unittest.TestCase):
    def test_every_builder_round_trips(self):
        cases = [
            (home_url("volmarr", "samverk"),
             ("home", {})),
            (tree_url("volmarr", "samverk", "main"),
             ("tree", {"ref": "main", "path": ""})),
            (tree_url("volmarr", "samverk", "main", "docs/deep"),
             ("tree", {"ref": "main", "path": "docs/deep"})),
            (blob_url("volmarr", "samverk", "main", "src/app.py"),
             ("blob", {"ref": "main", "path": "src/app.py"})),
            (blob_url("volmarr", "samverk", OID, "src/app.py", line=7),
             ("blob", {"ref": OID, "path": "src/app.py",
                       "line_start": 7, "line_end": 7})),
            (blob_url("volmarr", "samverk", OID, "src/app.py",
                      line=7, line_end=12),
             ("blob", {"ref": OID, "path": "src/app.py",
                       "line_start": 7, "line_end": 12})),
            (raw_url("volmarr", "samverk", "main", "img/logo.png"),
             ("raw", {"ref": "main", "path": "img/logo.png"})),
            (blame_url("volmarr", "samverk", "main", "src/app.py"),
             ("blame", {"ref": "main", "path": "src/app.py"})),
            (commit_url("volmarr", "samverk", OID),
             ("commit", {"commit": OID})),
            (commits_url("volmarr", "samverk", "feature/x"),
             ("commits", {"ref": "feature/x"})),
            (compare_url("volmarr", "samverk", "feature/x", "main"),
             ("compare", {"base": "feature/x", "head": "main"})),
            (plain_url("volmarr", "samverk", "find"), ("find", {})),
            (plain_url("volmarr", "samverk", "summary"), ("summary", {})),
            (plain_url("volmarr", "samverk", "insights"), ("insights", {})),
        ]
        for url, (kind, fields) in cases:
            link = parse_deep_link(url)
            self.assertEqual(link.kind, kind, url)
            self.assertEqual((link.owner, link.repo), ("volmarr", "samverk"), url)
            for field, expected in fields.items():
                self.assertEqual(getattr(link, field), expected, url)

    def test_blob_url_is_the_s099_permalink_byte_for_byte(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        conn = db.init_db(root / "samverk.db"); self.addCleanup(conn.close)
        accounts = AccountStore(conn)
        owner = accounts.register("volmarr", "correct horse battery")
        repos = RepositoryStore(conn, root, accounts)
        repos.create_repository(owner.id, "volmarr", "samverk", visibility="private")
        bare = repos.path_for("volmarr", "samverk")
        work = root / "work"; work.mkdir()
        run_git(work, "init", "-b", "main")
        (work / "app.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "code")
        run_git(work, "push", str(bare), "main")
        view = BlobViewer(repos).view(owner, "volmarr", "samverk", path="app.py")
        self.assertEqual(
            blob_url("volmarr", "samverk", view.commit_oid, "app.py", line=2),
            view.line_permalink(2))
        self.assertEqual(plain_url("volmarr", "samverk", "find"),
                         "/volmarr/samverk/find")  # S-112 chrome's href

    def test_anchor_grammar_is_strict(self):
        for bad in ("#L0", "#L5-L3", "#Lx", "#L1-L2-L3", "#", "#12"):
            with self.assertRaises(DeepLinkError, msg=bad):
                parse_deep_link(f"/volmarr/samverk/blob/main/a.py{bad}")
        with self.assertRaises(DeepLinkError) as caught:
            parse_deep_link(f"/volmarr/samverk/commit/{OID}#L3")
        self.assertEqual(caught.exception.reason, "anchor_invalid")
        with self.assertRaises(DeepLinkError):
            blob_url("volmarr", "samverk", "main", "a.py", line=0)
        with self.assertRaises(DeepLinkError):
            blob_url("volmarr", "samverk", "main", "a.py", line=5, line_end=4)
        with self.assertRaises(DeepLinkError):
            blob_url("volmarr", "samverk", "main", "a.py", line_end=4)

    def test_slash_refs_refused_for_path_views_free_elsewhere(self):
        with self.assertRaises(DeepLinkError) as caught:
            blob_url("volmarr", "samverk", "feature/x", "a.py")
        self.assertEqual(caught.exception.reason, "ref_ambiguous")
        with self.assertRaises(DeepLinkError):
            tree_url("volmarr", "samverk", "feature/x")
        # The same ref is unambiguous where no path follows it.
        self.assertIn("feature/x", commits_url("volmarr", "samverk", "feature/x"))
        self.assertIn("feature/x...main",
                      compare_url("volmarr", "samverk", "feature/x", "main"))

    def test_bad_shapes_are_refused_with_reasons(self):
        for bad, reason in [
                ("https://example.com/volmarr/samverk", "url_invalid"),
                ("volmarr/samverk", "url_invalid"),
                ("/volmarr/samverk/wiki", "kind_unknown"),
                ("/volmarr/samverk/blob/main", "path_invalid"),
                ("/volmarr/samverk/blob/main/../secret", "path_invalid"),
                ("/volmarr/samverk/commit/short", "commit_invalid"),
                ("/volmarr/samverk/compare/main", "url_invalid"),
                ("/vol%20marr/samverk", "name_invalid")]:
            with self.assertRaises(DeepLinkError, msg=bad) as caught:
                parse_deep_link(bad)
            self.assertEqual(caught.exception.reason, reason, bad)
        with self.assertRaises(DeepLinkError):
            blob_url("volmarr", "samverk", "main", "../secret")
        with self.assertRaises(DeepLinkError):
            commit_url("volmarr", "samverk", "not-an-oid")

    def test_chat_shorthand_expands_and_refuses(self):
        url = parse_file_shorthand("docs/guide.md@main#L12",
                                   owner="volmarr", repo="samverk")
        self.assertEqual(url, "/volmarr/samverk/blob/main/docs/guide.md#L12")
        link = parse_deep_link(url)
        self.assertEqual((link.path, link.line_start), ("docs/guide.md", 12))
        ranged = parse_file_shorthand(f"src/app.py@{OID}#L3-L9",
                                      owner="volmarr", repo="samverk")
        link = parse_deep_link(ranged)
        self.assertEqual((link.line_start, link.line_end), (3, 9))
        for bad in ("docs/guide.md", "docs/guide.md@", "@main", "a.py@main#L0"):
            with self.assertRaises(DeepLinkError, msg=bad):
                parse_file_shorthand(bad, owner="volmarr", repo="samverk")

    def test_percent_encoding_round_trips(self):
        url = blob_url("volmarr", "samverk", "main", "my docs/a file.py", line=1)
        self.assertIn("my%20docs/a%20file.py", url)
        link = parse_deep_link(url)
        self.assertEqual(link.path, "my docs/a file.py")

if __name__ == "__main__":
    unittest.main()
