"""S-104 acceptance battery: diff engine.

Acceptance (roadmap S-104): unified and split rendering
shared by commits and PRs; whitespace toggle; large-diff
folding with honest counts.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.diff_engine import (commit_diff, parse_patch, range_diff,
                                 render_split, render_unified)
from samverk.repositories import RepositoryStore
from test_repo_home import run_git

PATCH = """diff --git a/x.py b/x.py
--- a/x.py
+++ b/x.py
@@ -1,3 +1,3 @@
 keep
-old <line>
+new line
 tail
"""

class DiffEngineTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "samverk", visibility="private")
        self.bare = self.repos.path_for("volmarr", "samverk")
        work = self.root / "work"; work.mkdir()
        run_git(work, "init", "-b", "main")
        (work / "a.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
        (work / "ws.txt").write_text("spaced\n", encoding="utf-8")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "root")
        self.root_oid = run_git(work, "rev-parse", "HEAD")
        (work / "a.txt").write_text("one\nTWO\nthree\nfour\n", encoding="utf-8")
        (work / "ws.txt").write_text("  spaced  \n", encoding="utf-8")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "change")
        self.head_oid = run_git(work, "rev-parse", "HEAD")
        run_git(work, "push", str(self.bare), "main")

    def test_parse_numbers_and_counts_both_sides(self):
        diffset = parse_patch(PATCH)
        self.assertEqual(len(diffset.files), 1)
        file = diffset.files[0]
        self.assertEqual((file.additions, file.deletions), (1, 1))
        kinds = [(l.kind, l.old_number, l.new_number) for l in file.lines
                 if l.kind != "meta"]
        self.assertEqual(kinds, [("context", 1, 1), ("del", 2, None),
                                 ("add", None, 2), ("context", 3, 3)])
        html = render_unified(diffset)
        self.assertIn("old &lt;line&gt;", html); self.assertNotIn("old <line>", html)

    def test_commit_and_range_diff_agree(self):
        by_commit = commit_diff(self.bare, self.head_oid)
        by_range = range_diff(self.bare, self.root_oid, self.head_oid)
        self.assertEqual(by_commit.additions, by_range.additions)
        self.assertEqual(by_commit.deletions, by_range.deletions)
        a = {f.path: f for f in by_commit.files}["a.txt"]
        self.assertEqual((a.additions, a.deletions), (2, 1))
        root_diff = commit_diff(self.bare, self.root_oid)
        self.assertEqual({f.path for f in root_diff.files}, {"a.txt", "ws.txt"})

    def test_whitespace_toggle_is_gits_own(self):
        plain = commit_diff(self.bare, self.head_oid)
        self.assertIn("ws.txt", {f.path for f in plain.files})
        toggled = commit_diff(self.bare, self.head_oid, ignore_whitespace=True)
        ws = {f.path: f for f in toggled.files}.get("ws.txt")
        self.assertTrue(ws is None or (ws.additions == 0 and ws.deletions == 0))
        a = {f.path: f for f in toggled.files}["a.txt"]
        self.assertEqual((a.additions, a.deletions), (2, 1))

    def test_split_rendering_pairs_change_blocks(self):
        diffset = commit_diff(self.bare, self.head_oid)
        html = render_split(diffset)
        self.assertIn('class="diff split"', html)
        self.assertIn("TWO", html); self.assertIn("two", html)
        unified = render_unified(diffset)
        self.assertIn('class="diff unified"', unified)

    def test_folding_names_true_counts(self):
        big = "diff --git a/big.txt b/big.txt\n--- a/big.txt\n+++ b/big.txt\n" \
              "@@ -0,0 +1,4 @@\n+alpha\n+bravo\n+charlie\n+delta\n"
        diffset = parse_patch(big)
        html = render_unified(diffset, fold_limit=3)
        self.assertIn("diff-folded", html)
        self.assertIn("are not shown", html)
        self.assertIn("+4", html)
        self.assertNotIn("alpha", html)
        self.assertNotIn("delta", html)
        unfolded = render_unified(diffset, fold_limit=100)
        self.assertIn("alpha", unfolded)

if __name__ == "__main__":
    unittest.main()
