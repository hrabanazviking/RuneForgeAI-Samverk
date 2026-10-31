"""S-145 acceptance battery: pull request files view.

Acceptance (roadmap S-145): PR files view — the shared
diff engine (S-104) with per-file viewed-state per
reviewer.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.forks import ForkStore
from samverk.issues import IssueStore
from samverk.pull_request_files import (
    PullRequestFilesStore, patch_hash, render_files_page)
from samverk.pull_request_forks import ForkPullRequestStore
from samverk.pull_requests import PullRequestError, PullRequestStore
from samverk.repositories import RepositoryStore


def git(repo, *args, input_bytes=None):
    env = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin"}
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         capture_output=True, input=input_bytes, env=env)
    assert out.returncode == 0, out.stderr.decode()
    return out.stdout.decode().strip()


def make_commit(repo, parent, files, message):
    lines = []
    for name in sorted(files):
        content = files[name]
        blob = git(repo, "hash-object", "-w", "--stdin",
                   input_bytes=content if isinstance(content, bytes)
                   else content.encode())
        lines.append(f"100644 blob {blob}\t{name}\n")
    tree = git(repo, "mktree", input_bytes="".join(lines).encode())
    args = ["commit-tree", tree]
    if parent:
        args += ["-p", parent]
    return git(repo, *args, input_bytes=(message + "\n").encode())


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now

    def set(self, now):
        self.now = now


class PullRequestFilesTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.reader = self.accounts.register("yrsa", "correct horse battery")
        self.third = self.accounts.register("tess", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.issues = IssueStore(self.conn, self.repos, self.accounts,
                                 audit=self.audit, time_fn=self.clock)
        self.prs = PullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.files = PullRequestFilesStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.base_path = self.repos.path_for("volmarr", "pub")
        self.base_oid = make_commit(
            self.base_path, None,
            {"a.txt": "base\n", "b.txt": "bee\n"}, "base commit")
        git(self.base_path, "update-ref", "refs/heads/main", self.base_oid)
        self.head_oid = make_commit(
            self.base_path, self.base_oid,
            {"a.txt": "base\nfeature\n", "b.txt": "bee\n",
             "c.txt": "new <file>\n"}, "feature work")
        git(self.base_path, "update-ref", "refs/heads/feature", self.head_oid)

    def _open(self):
        return self.prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch="feature")

    def _by_path(self, view):
        return {f.path: f for f in view.files}

    # -- the diff itself ---------------------------------------------------
    def test_files_view_is_the_shared_diff_over_current_branches(self):
        pr = self._open()
        view = self.files.files_for(self.reader, "volmarr", "pub", pr.number)
        self.assertEqual(view.full_name, "volmarr/pub")
        self.assertEqual(
            (view.base_branch, view.head_branch), ("main", "feature"))
        self.assertEqual(
            (view.base_oid, view.head_oid), (self.base_oid, self.head_oid))
        self.assertEqual(
            [f.path for f in view.files], ["a.txt", "c.txt"])
        by = self._by_path(view)
        self.assertEqual(
            (by["a.txt"].file.additions, by["a.txt"].file.deletions), (1, 0))
        self.assertEqual(
            (by["c.txt"].file.additions, by["c.txt"].file.deletions), (1, 0))
        self.assertEqual((view.additions, view.deletions), (2, 0))
        self.assertEqual(view.viewed_count, 0)
        self.assertEqual(view.progress_words, "0 of 2 files viewed")
        for entry in view.files:
            self.assertFalse(entry.is_viewed)
            self.assertFalse(entry.changed_since_viewed)
            self.assertEqual(entry.state_words, "Not viewed")
            self.assertEqual(len(patch_hash(entry.file)), 64)

    def test_whitespace_toggle_is_the_engines_own(self):
        ws_oid = make_commit(
            self.base_path, self.base_oid,
            {"a.txt": "base \n", "b.txt": "bee\n"}, "whitespace only")
        git(self.base_path, "update-ref", "refs/heads/ws", ws_oid)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch="ws")
        plain = self.files.files_for(self.owner, "volmarr", "pub", pr.number)
        self.assertEqual([f.path for f in plain.files], ["a.txt"])
        toggled = self.files.files_for(
            self.owner, "volmarr", "pub", pr.number, ignore_whitespace=True)
        self.assertEqual(toggled.files, ())

    # -- viewed state ---------------------------------------------------------
    def test_mark_viewed_is_per_reviewer(self):
        pr = self._open()
        marked = self.files.mark_viewed(
            self.reader, "volmarr", "pub", pr.number, "a.txt")
        self.assertTrue(marked.is_viewed)
        self.assertEqual(marked.state_words, "Viewed")
        mine = self._by_path(self.files.files_for(
            self.reader, "volmarr", "pub", pr.number))
        self.assertTrue(mine["a.txt"].is_viewed)
        self.assertFalse(mine["c.txt"].is_viewed)
        # Another reviewer's progress is their own.
        theirs = self._by_path(self.files.files_for(
            self.third, "volmarr", "pub", pr.number))
        self.assertFalse(theirs["a.txt"].is_viewed)
        owners = self._by_path(self.files.files_for(
            self.owner, "volmarr", "pub", pr.number))
        self.assertFalse(owners["a.txt"].is_viewed)
        view = self.files.files_for(self.reader, "volmarr", "pub", pr.number)
        self.assertEqual(view.progress_words, "1 of 2 files viewed")

    def test_mark_unviewed_removes_the_mark_and_retries_quietly(self):
        pr = self._open()
        self.files.mark_viewed(self.reader, "volmarr", "pub", pr.number, "a.txt")
        removed = self.files.mark_unviewed(
            self.reader, "volmarr", "pub", pr.number, "a.txt")
        self.assertFalse(removed.is_viewed)
        again = self.files.mark_unviewed(
            self.reader, "volmarr", "pub", pr.number, "a.txt")
        self.assertFalse(again.is_viewed)
        self.assertEqual(self.files.files_for(
            self.reader, "volmarr", "pub", pr.number).viewed_count, 0)

    def test_marking_a_file_not_in_the_diff_stores_nothing(self):
        pr = self._open()
        for call in (
                lambda: self.files.mark_viewed(
                    self.reader, "volmarr", "pub", pr.number, "b.txt"),
                lambda: self.files.mark_viewed(
                    self.reader, "volmarr", "pub", pr.number, "nope.txt"),
                lambda: self.files.mark_unviewed(
                    self.reader, "volmarr", "pub", pr.number, "")):
            with self.assertRaises(PullRequestError) as caught:
                call()
            self.assertEqual(caught.exception.reason, "file_not_found")
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM pull_request_file_views").fetchone()
        self.assertEqual(int(row["c"]), 0)

    def test_a_push_that_changes_a_file_unviews_only_that_file(self):
        pr = self._open()
        self.files.mark_viewed(self.reader, "volmarr", "pub", pr.number, "a.txt")
        self.files.mark_viewed(self.reader, "volmarr", "pub", pr.number, "c.txt")
        # A new head commit changes a.txt and leaves c.txt's
        # patch exactly as it was.
        new_head = make_commit(
            self.base_path, self.head_oid,
            {"a.txt": "base\nfeature\nmore\n", "b.txt": "bee\n",
             "c.txt": "new <file>\n"}, "more work on a")
        git(self.base_path, "update-ref", "refs/heads/feature", new_head)
        view = self.files.files_for(self.reader, "volmarr", "pub", pr.number)
        self.assertEqual(view.head_oid, new_head)
        by = self._by_path(view)
        self.assertFalse(by["a.txt"].is_viewed)
        self.assertTrue(by["a.txt"].changed_since_viewed)
        self.assertEqual(
            by["a.txt"].state_words,
            "Changed since you viewed it — not viewed")
        self.assertTrue(by["c.txt"].is_viewed)
        self.assertEqual(view.viewed_count, 1)
        # Re-marking the changed file vouches for the new patch.
        self.files.mark_viewed(self.reader, "volmarr", "pub", pr.number, "a.txt")
        by = self._by_path(self.files.files_for(
            self.reader, "volmarr", "pub", pr.number))
        self.assertTrue(by["a.txt"].is_viewed)
        self.assertFalse(by["a.txt"].changed_since_viewed)

    def test_anonymous_reader_sees_files_but_no_personal_state(self):
        pr = self._open()
        self.files.mark_viewed(self.reader, "volmarr", "pub", pr.number, "a.txt")
        view = self.files.files_for(None, "volmarr", "pub", pr.number)
        self.assertEqual(view.total_files, 2)
        self.assertEqual(view.viewed_count, 0)
        self.assertTrue(all(not f.is_viewed for f in view.files))

    # -- cross-fork --------------------------------------------------------------
    def test_cross_fork_files_view_compares_in_the_fork(self):
        forks = ForkStore(self.conn, self.root, self.accounts,
                          self.repos, audit=self.audit)
        xprs = ForkPullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        forks.fork(self.reader.id, "volmarr", "pub")
        fork_path = self.repos.path_for("yrsa", "pub")
        fork_head = make_commit(
            fork_path, self.base_oid,
            {"a.txt": "base\nfrom the fork\n", "b.txt": "bee\n"},
            "fork work")
        git(fork_path, "update-ref", "refs/heads/feature", fork_head)
        created = xprs.create_cross_fork_pull_request(
            self.reader, "volmarr", "pub", base_branch="main",
            head_owner="yrsa", head_repo="pub", head_branch="feature")
        view = self.files.files_for(
            self.owner, "volmarr", "pub", created.number)
        self.assertEqual([f.path for f in view.files], ["a.txt"])
        self.assertEqual(view.head_oid, fork_head)
        self.files.mark_viewed(
            self.owner, "volmarr", "pub", created.number, "a.txt")
        self.assertEqual(self.files.files_for(
            self.owner, "volmarr", "pub", created.number).viewed_count, 1)

    # -- rendering + permissions ---------------------------------------------------
    def test_rendering_says_progress_and_viewed_state_in_words(self):
        pr = self._open()
        self.files.mark_viewed(self.reader, "volmarr", "pub", pr.number, "a.txt")
        page = render_files_page(self.files.files_for(
            self.reader, "volmarr", "pub", pr.number))
        self.assertIn("1 of 2 files viewed", page)
        self.assertIn("a.txt +1 −0 · Viewed", page)
        self.assertIn("c.txt +1 −0 · Not viewed", page)
        # The patch renders through the escaping seam.
        self.assertIn("new &lt;file&gt;", page)
        self.assertNotIn("new <file>", page)

    def test_private_repository_answers_uniformly(self):
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        priv_path = self.repos.path_for("volmarr", "priv")
        priv_base = make_commit(priv_path, None, {"s.txt": "s\n"}, "one")
        git(priv_path, "update-ref", "refs/heads/main", priv_base)
        priv_head = make_commit(
            priv_path, priv_base, {"s.txt": "s\nmore\n"}, "two")
        git(priv_path, "update-ref", "refs/heads/feature", priv_head)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "priv", base_branch="main",
            head_branch="feature")
        for call in (
                lambda: self.files.files_for(
                    self.reader, "volmarr", "priv", pr.number),
                lambda: self.files.mark_viewed(
                    self.reader, "volmarr", "priv", pr.number, "s.txt"),
                lambda: self.files.mark_unviewed(
                    self.reader, "volmarr", "priv", pr.number, "s.txt")):
            with self.assertRaises(PullRequestError) as caught:
                call()
            self.assertEqual(
                caught.exception.reason, "pull_request_not_found")


if __name__ == "__main__":
    unittest.main()
