"""S-099 acceptance battery: blob view.

Acceptance (roadmap S-099): syntax highlighting (server-side,
language detection), line numbers, line permalinks that
survive in issues/PRs.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.blob_view import BlobError, BlobViewer, detect_language, render_blob_page
from samverk.lfs_store import make_pointer, oid_for
from samverk.repositories import RepositoryStore
from test_repo_home import run_git

CODE = '''# comment with <script>
def greet(name):
    msg = "hello <b>world</b>"
    return msg + str(42)
'''

class BlobViewTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.stranger = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "samverk", visibility="private")
        self.viewer = BlobViewer(self.repos)
        bare = self.repos.path_for("volmarr", "samverk")
        work = self.root / "work"; work.mkdir()
        run_git(work, "init", "-b", "main")
        (work / "app.py").write_text(CODE, encoding="utf-8")
        (work / "notes.txt").write_text("plain\ntext\n", encoding="utf-8")
        (work / "blob.bin").write_bytes(b"\x00\x01\x02binary")
        payload = b"real lfs bytes"
        (work / "big.dat").write_bytes(make_pointer(oid_for(payload), len(payload)))
        run_git(work, "add", "."); run_git(work, "commit", "-m", "code")
        run_git(work, "push", str(bare), "main")
        self.commit = run_git(work, "rev-parse", "main")

    def test_highlighting_language_and_line_numbers(self):
        view = self.viewer.view(self.owner, "volmarr", "samverk", path="app.py")
        self.assertEqual(view.language, "python")
        self.assertEqual(view.commit_oid, self.commit)
        self.assertEqual(len(view.lines), 4)
        html = "\n".join(l.html for l in view.lines)
        self.assertIn('<span class="tok-k">def</span>', html)
        self.assertIn('<span class="tok-k">return</span>', html)
        self.assertIn('<span class="tok-c"># comment', html)
        self.assertIn('<span class="tok-s">"hello', html)
        self.assertIn('<span class="tok-n">42</span>', html)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        page = render_blob_page(view)
        self.assertIn('id="L1"', page); self.assertIn('href="#L4"', page)

    def test_permalinks_pin_the_commit_not_the_branch(self):
        view = self.viewer.view(self.owner, "volmarr", "samverk", path="app.py")
        link = view.line_permalink(2)
        self.assertEqual(link, f"/volmarr/samverk/blob/{self.commit}/app.py#L2")
        self.assertNotIn("/main/", link)
        with self.assertRaises(BlobError) as caught:
            view.line_permalink(99)
        self.assertEqual(caught.exception.reason, "line_out_of_range")

    def test_language_detection(self):
        self.assertEqual(detect_language("x.py", b""), "python")
        self.assertEqual(detect_language("x.go", b""), "go")
        self.assertEqual(detect_language("runme", b"#!/usr/bin/env python3\n"), "python")
        self.assertEqual(detect_language("runme", b"#!/bin/sh\n"), "shell")
        self.assertEqual(detect_language("x.unknownext", b"hi"), "text")
        view = self.viewer.view(self.owner, "volmarr", "samverk", path="notes.txt")
        self.assertEqual(view.language, "text")
        self.assertEqual([l.text for l in view.lines], ["plain", "text"])

    def test_binary_and_lfs_are_named_not_rendered(self):
        with self.assertRaises(BlobError) as caught:
            self.viewer.view(self.owner, "volmarr", "samverk", path="blob.bin")
        self.assertEqual(caught.exception.reason, "binary_file")
        view = self.viewer.view(self.owner, "volmarr", "samverk", path="big.dat")
        self.assertTrue(view.is_lfs_pointer)
        self.assertEqual(view.lfs_size, len(b"real lfs bytes"))
        self.assertEqual(view.lines, ())
        self.assertIn("Git LFS", render_blob_page(view))

    def test_path_and_permission_law(self):
        with self.assertRaises(BlobError) as caught:
            self.viewer.view(self.stranger, "volmarr", "samverk", path="app.py")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        with self.assertRaises(BlobError) as caught:
            self.viewer.view(self.owner, "volmarr", "samverk", path="../app.py")
        self.assertEqual(caught.exception.reason, "path_invalid")
        with self.assertRaises(BlobError) as caught:
            self.viewer.view(self.owner, "volmarr", "samverk", path="missing.py")
        self.assertEqual(caught.exception.reason, "path_not_found")
        with self.assertRaises(BlobError) as caught:
            self.viewer.view(self.owner, "volmarr", "samverk", path="")
        self.assertEqual(caught.exception.reason, "path_invalid")

if __name__ == "__main__":
    unittest.main()
