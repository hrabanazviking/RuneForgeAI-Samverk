"""S-103 acceptance battery: commit detail.

Acceptance (roadmap S-103): full diff with per-file
collapse, parent links, and "browse at this point" into
S-098.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.commit_detail import CommitDetailError, CommitDetailService, render_commit_page
from samverk.repositories import RepositoryStore
from test_repo_home import run_git

class CommitDetailTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.stranger = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "samverk", visibility="private")
        self.service = CommitDetailService(self.repos)
        bare = self.repos.path_for("volmarr", "samverk")
        work = self.root / "work"; work.mkdir()
        run_git(work, "init", "-b", "main")
        (work / "a.txt").write_text("one\ntwo\n", encoding="utf-8")
        (work / "b.txt").write_text("bee\n", encoding="utf-8")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "root <commit>")
        self.root_oid = run_git(work, "rev-parse", "HEAD")
        (work / "a.txt").write_text("one\nTWO\nthree\n", encoding="utf-8")
        run_git(work, "mv", "b.txt", "c.txt")
        (work / "bin.dat").write_bytes(b"\x00\x01\x02")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "second commit")
        self.head_oid = run_git(work, "rev-parse", "HEAD")
        run_git(work, "push", str(bare), "main")

    def test_full_diff_per_file_with_counts(self):
        detail = self.service.detail(self.owner, "volmarr", "samverk", self.head_oid)
        self.assertEqual(detail.subject, "second commit")
        self.assertEqual(detail.parents, (self.root_oid,))
        by_path = {f.path: f for f in detail.files}
        self.assertEqual(by_path["a.txt"].additions, 2)
        self.assertEqual(by_path["a.txt"].deletions, 1)
        self.assertIn("+TWO", "\n".join(by_path["a.txt"].patch_lines))
        self.assertEqual(by_path["c.txt"].old_path, "b.txt")
        self.assertEqual(by_path["c.txt"].new_path, "c.txt")
        self.assertTrue(by_path["bin.dat"].is_binary)
        self.assertEqual(detail.total_additions, 2)
        page = render_commit_page(detail)
        self.assertEqual(page.count('<details class="file-diff">'), 3)
        self.assertIn("Binary file", page)
        self.assertIn("b.txt → c.txt", page)

    def test_parent_links_and_browse_at_this_point(self):
        detail = self.service.detail(self.owner, "volmarr", "samverk", "main")
        self.assertEqual(detail.browse_url,
                         f"/volmarr/samverk/tree/{self.head_oid}")
        page = render_commit_page(detail)
        self.assertIn(f'href="/volmarr/samverk/commit/{self.root_oid}"', page)
        self.assertIn("Browse files at this point", page)
        root = self.service.detail(self.owner, "volmarr", "samverk", self.root_oid)
        self.assertEqual(root.parents, ())
        self.assertIn("Root commit", render_commit_page(root))
        self.assertEqual(root.subject, "root <commit>")
        self.assertIn("root &lt;commit&gt;", render_commit_page(root))

    def test_ref_and_permission_law(self):
        with self.assertRaises(CommitDetailError) as caught:
            self.service.detail(self.stranger, "volmarr", "samverk", self.head_oid)
        self.assertEqual(caught.exception.reason, "repo_not_found")
        with self.assertRaises(CommitDetailError) as caught:
            self.service.detail(self.owner, "volmarr", "samverk", "no-such")
        self.assertEqual(caught.exception.reason, "ref_not_found")
        by_tag = self.service.detail(self.owner, "volmarr", "samverk", self.root_oid[:12])
        self.assertEqual(by_tag.oid, self.root_oid)

if __name__ == "__main__":
    unittest.main()
