"""S-116 acceptance battery: print and export of code views.

Acceptance (roadmap S-116): a readable print stylesheet
for blob and diff pages.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import re, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.blob_view import BlobViewer, render_blob_page
from samverk.diff_engine import parse_patch
from samverk.print_export import (PRINT_CSS, PRINT_STYLESHEET_PATH,
                                  PrintError, export_blob_text,
                                  export_diff_text, print_stylesheet,
                                  render_blob_print_page,
                                  render_diff_print_page,
                                  stylesheet_link_tag)
from samverk.repositories import RepositoryStore
from test_repo_home import run_git

CODE = "def greet():\n    return \"hi <b>there</b>\"\n"

PATCH = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,2 +1,2 @@
 def greet():
-    return "old"
+    return "new"
diff --git a/new.txt b/new.txt
--- /dev/null
+++ b/new.txt
@@ -0,0 +1 @@
+brand new
diff --git a/logo.png b/logo.png
Binary files a/logo.png and b/logo.png differ
"""

class PrintExportTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "samverk", visibility="private")
        self.viewer = BlobViewer(self.repos)
        bare = self.repos.path_for("volmarr", "samverk")
        work = self.root / "work"; work.mkdir()
        run_git(work, "init", "-b", "main")
        (work / "app.py").write_text(CODE, encoding="utf-8")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "code")
        run_git(work, "push", str(bare), "main")
        self.commit = run_git(work, "rev-parse", "main")
        self.view = self.viewer.view(self.owner, "volmarr", "samverk", path="app.py")

    def test_stylesheet_is_print_only_grayscale_and_marker_true(self):
        css = print_stylesheet()
        self.assertEqual(css, PRINT_CSS)
        self.assertIn("@media print", css)
        self.assertIn("@page", css)
        self.assertIn("display: none", css)          # chrome/forms never print
        self.assertIn(".tok-k { font-weight: bold; }", css)   # meaning w/o colour
        self.assertIn(".tok-c { font-style: italic; }", css)
        self.assertIn('content: "+ "', css)          # diff markers restored
        self.assertIn('content: "- "', css)
        hexes = set(re.findall(r"#[0-9a-fA-F]{3,6}\b", css))
        self.assertLessEqual(hexes, {"#000", "#fff"})  # black on white only
        self.assertNotIn("<style", css)

    def test_link_tag_is_external_and_pages_carry_it(self):
        tag = stylesheet_link_tag()
        self.assertIn('rel="stylesheet"', tag)
        self.assertIn('media="print"', tag)
        self.assertIn(PRINT_STYLESHEET_PATH, tag)
        self.assertIn(tag, render_blob_page(self.view))

    def test_blob_print_page_names_its_pin_and_escapes(self):
        page = render_blob_print_page(self.view)
        self.assertIn("volmarr/samverk", page)
        self.assertIn("app.py", page)
        self.assertIn(self.commit, page)             # full pin, not a branch
        self.assertIn("2 lines", page)
        self.assertIn("&lt;b&gt;there&lt;/b&gt;", page)
        self.assertNotIn("<b>there</b>", page)
        self.assertNotIn("<details", page)
        self.assertNotIn("<style", page)
        self.assertNotIn("<script", page)
        self.assertIn(stylesheet_link_tag(), page)

    def test_diff_print_page_open_sections_fold_and_binary_named(self):
        diffset = parse_patch(PATCH)
        page = render_diff_print_page(diffset, title="volmarr/samverk — change")
        self.assertNotIn("<details", page)
        self.assertIn('<section class="file-diff">', page)
        self.assertIn("3 files changed", page)
        self.assertIn("Binary file — no patch shown.", page)
        self.assertIn('class="dl-add"', page)
        big = parse_patch(
            "diff --git a/big.py b/big.py\n--- a/big.py\n+++ b/big.py\n"
            "@@ -0,0 +1,500 @@\n" + "".join(f"+line {i}\n" for i in range(500)))
        folded = render_diff_print_page(big, title="big change")
        self.assertIn("folded", folded)
        self.assertIn("501 patch lines", folded)  # 500 adds + the hunk header, as S-104 counts
        self.assertNotIn("+line 499", folded)  # the fold is real, counts named

    def test_blob_text_export_and_lfs_refusal(self):
        self.assertEqual(export_blob_text(self.view), CODE)
        lfs = self.viewer.view(self.owner, "volmarr", "samverk", path="app.py")
        from samverk.blob_view import BlobView
        pointer_view = BlobView(
            full_name="volmarr/samverk", current_ref="main",
            commit_oid=self.commit, path="big.dat", language="text",
            size=10, lines=(), is_lfs_pointer=True,
            lfs_oid="a" * 64, lfs_size=1234)
        with self.assertRaises(PrintError) as caught:
            export_blob_text(pointer_view)
        self.assertEqual(caught.exception.reason, "lfs_pointer")
        self.assertIn("Git LFS", render_blob_print_page(pointer_view))

    def test_diff_text_export_round_trips_through_the_parser(self):
        original = parse_patch(PATCH)
        exported = export_diff_text(original)
        reparsed = parse_patch(exported)
        self.assertEqual(reparsed, original)
        self.assertIn("diff --git a/app.py b/app.py", exported)
        self.assertIn("Binary files a/logo.png and b/logo.png differ", exported)
        # Export is complete even where the page folds.
        big = parse_patch(
            "diff --git a/big.py b/big.py\n--- a/big.py\n+++ b/big.py\n"
            "@@ -0,0 +1,500 @@\n" + "".join(f"+line {i}\n" for i in range(500)))
        self.assertIn("+line 499", export_diff_text(big))
        self.assertEqual(export_diff_text(parse_patch("")), "")

if __name__ == "__main__":
    unittest.main()
