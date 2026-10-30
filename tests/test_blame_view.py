"""S-101 acceptance battery: blame view.

Acceptance (roadmap S-101): per-line commit attribution via
`git blame`, paginated for long files, honest about rename
limits.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import os, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.blame_view import BlameError, BlameViewer, render_blame_page
from samverk.lfs_store import make_pointer, oid_for
from samverk.repositories import RepositoryStore
from test_repo_home import run_git

def run_as(cwd: Path, name: str, email: str, date: str, *args: str) -> str:
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
                "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email,
                "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date,
                "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"})
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode())
    return out.stdout.decode().strip()

class BlameViewTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.stranger = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "samverk", visibility="private")
        self.viewer = BlameViewer(self.repos)
        bare = self.repos.path_for("volmarr", "samverk")
        work = self.root / "work"; work.mkdir()
        run_git(work, "init", "-b", "main")
        (work / "code.py").write_text("alpha <x>\nbeta\ngamma\n", encoding="utf-8")
        run_as(work, "Alice A", "alice@example.com", "2024-01-01T00:00:00Z",
               "add", ".")
        run_as(work, "Alice A", "alice@example.com", "2024-01-01T00:00:00Z",
               "commit", "-m", "first words")
        self.commit1 = run_git(work, "rev-parse", "HEAD")
        (work / "code.py").write_text("alpha <x>\nBETA\ngamma\ndelta\n", encoding="utf-8")
        run_as(work, "Bob B", "bob@example.com", "2024-06-01T00:00:00Z",
               "add", ".")
        run_as(work, "Bob B", "bob@example.com", "2024-06-01T00:00:00Z",
               "commit", "-m", "second <words>")
        self.commit2 = run_git(work, "rev-parse", "HEAD")
        (work / "blob.bin").write_bytes(b"\x00\x01binary")
        payload = b"real lfs bytes"
        (work / "big.dat").write_bytes(make_pointer(oid_for(payload), len(payload)))
        run_git(work, "add", "."); run_git(work, "commit", "-m", "extras")
        run_git(work, "push", str(bare), "main")

    def test_per_line_attribution(self):
        view = self.viewer.blame(self.owner, "volmarr", "samverk", path="code.py")
        self.assertEqual(view.total_lines, 4)
        by_no = {l.number: l for l in view.lines}
        self.assertEqual(by_no[1].commit_oid, self.commit1)
        self.assertEqual(by_no[1].author, "Alice A")
        self.assertEqual(by_no[1].summary, "first words")
        self.assertEqual(by_no[3].commit_oid, self.commit1)
        self.assertEqual(by_no[2].commit_oid, self.commit2)
        self.assertEqual(by_no[2].author, "Bob B")
        self.assertEqual(by_no[2].summary, "second <words>")
        self.assertEqual(by_no[4].commit_oid, self.commit2)
        self.assertGreater(by_no[2].author_time, by_no[1].author_time)
        self.assertEqual(by_no[1].filename, "code.py")
        page = render_blame_page(view)
        self.assertIn("Alice A", page); self.assertIn("second &lt;words&gt;", page)
        self.assertIn("alpha &lt;x&gt;", page)
        self.assertNotIn("second <words>", page)

    def test_consecutive_lines_from_one_commit_blame(self):
        # Regression (found by the S-120 gate battery): git
        # omits the group-count field from the porcelain
        # header of every line after the first in a
        # same-commit group, and the parser once refused
        # those headers — blame failed outright on any
        # file with consecutive lines from one commit.
        self.repos.create_repository(
            self.owner.id, "volmarr", "multi", visibility="private")
        bare = self.repos.path_for("volmarr", "multi")
        work = self.root / "work-multi"; work.mkdir()
        run_git(work, "init", "-b", "main")
        (work / "multi.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
        run_as(work, "Alice A", "alice@example.com",
               "2024-01-01T00:00:00Z", "add", ".")
        run_as(work, "Alice A", "alice@example.com",
               "2024-01-01T00:00:00Z", "commit", "-m", "all at once")
        run_git(work, "push", str(bare), "main")
        view = self.viewer.blame(self.owner, "volmarr", "multi",
                                 path="multi.py")
        self.assertEqual(view.total_lines, 3)
        self.assertEqual([l.text for l in view.lines],
                         ["one", "two", "three"])
        self.assertTrue(all(l.author == "Alice A" for l in view.lines))
        self.assertTrue(all(l.summary == "all at once" for l in view.lines))

    def test_pagination_walks_long_files_honestly(self):
        page1 = self.viewer.blame(self.owner, "volmarr", "samverk",
                                  path="code.py", page=1, per_page=2)
        self.assertEqual([l.number for l in page1.lines], [1, 2])
        self.assertEqual(page1.total_lines, 4); self.assertEqual(page1.total_pages, 2)
        self.assertTrue(page1.has_next); self.assertFalse(page1.has_previous)
        page2 = self.viewer.blame(self.owner, "volmarr", "samverk",
                                  path="code.py", page=2, per_page=2)
        self.assertEqual([l.number for l in page2.lines], [3, 4])
        self.assertFalse(page2.has_next); self.assertTrue(page2.has_previous)
        beyond = self.viewer.blame(self.owner, "volmarr", "samverk",
                                   path="code.py", page=9, per_page=2)
        self.assertEqual(beyond.lines, ()); self.assertEqual(beyond.total_lines, 4)
        html = render_blame_page(page1)
        self.assertIn("Page 1 of 2", html); self.assertIn("?page=2", html)
        clamped = self.viewer.blame(self.owner, "volmarr", "samverk",
                                    path="code.py", per_page=99999)
        self.assertEqual(clamped.per_page, 500)

    def test_rename_history_stays_visible(self):
        bare = self.repos.path_for("volmarr", "samverk")
        work = self.root / "work2"; work.mkdir()
        run_git(work, "clone", str(bare), ".")
        run_git(work, "mv", "code.py", "renamed.py")
        with open(work / "renamed.py", "a", encoding="utf-8") as fh:
            fh.write("epsilon\n")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "rename it")
        run_git(work, "push", "origin", "main")
        view = self.viewer.blame(self.owner, "volmarr", "samverk", path="renamed.py")
        self.assertEqual(view.total_lines, 5)
        self.assertEqual(view.lines[0].commit_oid, self.commit1)
        self.assertEqual(view.lines[0].filename, "code.py")
        self.assertEqual(view.lines[4].filename, "renamed.py")
        self.assertIn("copy/move tracing", view.rename_note)
        self.assertIn("copy/move tracing", render_blame_page(view))

    def test_binary_and_lfs_are_named_not_blamed(self):
        with self.assertRaises(BlameError) as caught:
            self.viewer.blame(self.owner, "volmarr", "samverk", path="blob.bin")
        self.assertEqual(caught.exception.reason, "binary_file")
        view = self.viewer.blame(self.owner, "volmarr", "samverk", path="big.dat")
        self.assertTrue(view.is_lfs_pointer); self.assertEqual(view.lines, ())
        self.assertIn("Git LFS", render_blame_page(view))

    def test_path_and_permission_law(self):
        with self.assertRaises(BlameError) as caught:
            self.viewer.blame(self.stranger, "volmarr", "samverk", path="code.py")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        with self.assertRaises(BlameError) as caught:
            self.viewer.blame(self.owner, "volmarr", "samverk", path="../code.py")
        self.assertEqual(caught.exception.reason, "path_invalid")
        with self.assertRaises(BlameError) as caught:
            self.viewer.blame(self.owner, "volmarr", "samverk", path="missing.py")
        self.assertEqual(caught.exception.reason, "path_not_found")

if __name__ == "__main__":
    unittest.main()
