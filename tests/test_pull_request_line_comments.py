"""S-146 acceptance battery: pull request line comments.

Acceptance (roadmap S-146): line comments — comments
anchored to diff lines with outdated marking when the
lines move.

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
from samverk.pull_request_forks import ForkPullRequestStore
from samverk.pull_request_line_comments import (
    PullRequestLineCommentStore, render_line_comments)
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


BASE_FILES = {"a.txt": "alpha\nbeta\ngamma\n", "b.txt": "bee\n",
              "d.txt": "dee\n"}
HEAD_FILES = {"a.txt": "alpha\nBETA\ngamma\ndelta\n", "b.txt": "bee\n",
              "d.txt": "dee\n"}


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


class LineCommentTests(unittest.TestCase):
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
        self.lines = PullRequestLineCommentStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.path = self.repos.path_for("volmarr", "pub")
        self.base_oid = make_commit(self.path, None, BASE_FILES, "base")
        git(self.path, "update-ref", "refs/heads/main", self.base_oid)
        self.head_oid = make_commit(
            self.path, self.base_oid, HEAD_FILES, "feature work")
        git(self.path, "update-ref", "refs/heads/feature", self.head_oid)

    def _open(self):
        return self.prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch="feature")

    def _push(self, files, message="more work"):
        oid = make_commit(self.path, self.head_oid, files, message)
        git(self.path, "update-ref", "refs/heads/feature", oid)
        self.head_oid = oid
        return oid

    def _count(self):
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM pull_request_line_comments"
        ).fetchone()
        return int(row["c"])

    # -- anchoring ---------------------------------------------------------
    def test_comment_anchors_to_the_exact_diff_line(self):
        pr = self._open()
        comment = self.lines.add_line_comment(
            self.reader, "volmarr", "pub", pr.number,
            "a.txt", "new", 2, "This rename reads better.")
        self.assertEqual(comment.file_path, "a.txt")
        self.assertEqual((comment.side, comment.line_number), ("new", 2))
        self.assertEqual(comment.line_text, "BETA")
        self.assertEqual(comment.head_oid, self.head_oid)
        self.assertFalse(comment.is_outdated)
        self.assertEqual(comment.state_words, "Current")
        self.assertEqual(comment.anchor_words,
                         "a.txt, line 2 on the new side")
        listed = self.lines.list_line_comments(
            self.third, "volmarr", "pub", pr.number)
        self.assertEqual([c.id for c in listed], [comment.id])
        self.assertFalse(listed[0].is_outdated)
        only_a = self.lines.list_line_comments(
            self.third, "volmarr", "pub", pr.number, file_path="a.txt")
        self.assertEqual(len(only_a), 1)
        self.assertEqual(self.lines.list_line_comments(
            self.third, "volmarr", "pub", pr.number, file_path="d.txt"),
            [])

    def test_old_side_anchors_removed_and_context_lines(self):
        pr = self._open()
        removed = self.lines.add_line_comment(
            self.reader, "volmarr", "pub", pr.number,
            "a.txt", "old", 2, "Why is beta going away?")
        self.assertEqual(removed.line_text, "beta")
        context = self.lines.add_line_comment(
            self.reader, "volmarr", "pub", pr.number,
            "a.txt", "old", 3, "Gamma stays.")
        self.assertEqual(context.line_text, "gamma")

    def test_a_line_that_is_not_on_that_side_is_refused(self):
        pr = self._open()
        # 'delta' exists only on the new side (line 4);
        # 'beta' (removed) exists only on the old side.
        for side, line in (("old", 4), ("new", 99), ("old", 0)):
            with self.assertRaises(PullRequestError) as caught:
                self.lines.add_line_comment(
                    self.reader, "volmarr", "pub", pr.number,
                    "a.txt", side, line, "Nowhere to sit.")
            self.assertEqual(caught.exception.reason, "line_not_found")
        self.assertEqual(self._count(), 0)

    def test_bad_side_and_unknown_file_store_nothing(self):
        pr = self._open()
        with self.assertRaises(PullRequestError) as caught:
            self.lines.add_line_comment(
                self.reader, "volmarr", "pub", pr.number,
                "a.txt", "middle", 1, "Which side?")
        self.assertEqual(caught.exception.reason, "side_invalid")
        for path in ("b.txt", "nope.txt", ""):
            with self.assertRaises(PullRequestError) as caught:
                self.lines.add_line_comment(
                    self.reader, "volmarr", "pub", pr.number,
                    path, "new", 1, "Not in the diff.")
            self.assertEqual(caught.exception.reason, "file_not_found")
        self.assertEqual(self._count(), 0)

    # -- outdated marking ------------------------------------------------------
    def test_a_push_that_rewrites_the_line_marks_it_outdated(self):
        pr = self._open()
        changed = self.lines.add_line_comment(
            self.reader, "volmarr", "pub", pr.number,
            "a.txt", "new", 2, "About BETA.")
        steady = self.lines.add_line_comment(
            self.reader, "volmarr", "pub", pr.number,
            "a.txt", "new", 3, "Gamma is fine.")
        self._push({"a.txt": "alpha\nBETA2\ngamma\ndelta\n",
                    "b.txt": "bee\n", "d.txt": "dee\n"})
        by_id = {c.id: c for c in self.lines.list_line_comments(
            self.reader, "volmarr", "pub", pr.number)}
        self.assertTrue(by_id[changed.id].is_outdated)
        self.assertIn("Outdated", by_id[changed.id].state_words)
        # The anchor itself never moved silently.
        self.assertEqual(
            (by_id[changed.id].line_number,
             by_id[changed.id].line_text), (2, "BETA"))
        self.assertFalse(by_id[steady.id].is_outdated)

    def test_a_push_that_shifts_the_line_marks_it_outdated(self):
        pr = self._open()
        comment = self.lines.add_line_comment(
            self.reader, "volmarr", "pub", pr.number,
            "a.txt", "new", 3, "Gamma note.")
        self._push({"a.txt": "zero\nalpha\nBETA\ngamma\ndelta\n",
                    "b.txt": "bee\n", "d.txt": "dee\n"})
        listed = self.lines.list_line_comments(
            self.reader, "volmarr", "pub", pr.number)
        self.assertTrue(listed[0].is_outdated)
        self.assertEqual(listed[0].id, comment.id)

    def test_an_unrelated_push_leaves_the_comment_current(self):
        pr = self._open()
        self.lines.add_line_comment(
            self.reader, "volmarr", "pub", pr.number,
            "a.txt", "new", 3, "Gamma note.")
        self._push({"a.txt": HEAD_FILES["a.txt"], "b.txt": "bee\n",
                    "d.txt": "dee\nmore dee\n"})
        listed = self.lines.list_line_comments(
            self.reader, "volmarr", "pub", pr.number)
        self.assertFalse(listed[0].is_outdated)
        self.assertEqual(listed[0].state_words, "Current")

    def test_a_file_leaving_the_diff_marks_its_comments_outdated(self):
        pr = self._open()
        self.lines.add_line_comment(
            self.reader, "volmarr", "pub", pr.number,
            "a.txt", "new", 2, "About BETA.")
        # a.txt returns to its base content; d.txt still differs,
        # so the pull request still has a diff — without a.txt.
        self._push({"a.txt": BASE_FILES["a.txt"], "b.txt": "bee\n",
                    "d.txt": "dee\nmore dee\n"})
        listed = self.lines.list_line_comments(
            self.reader, "volmarr", "pub", pr.number)
        self.assertTrue(listed[0].is_outdated)

    # -- the honest record -------------------------------------------------------
    def test_edit_keeps_history_and_only_the_author_edits(self):
        pr = self._open()
        comment = self.lines.add_line_comment(
            self.reader, "volmarr", "pub", pr.number,
            "a.txt", "new", 2, "First wording.")
        with self.assertRaises(PullRequestError) as caught:
            self.lines.edit_line_comment(
                self.third, "volmarr", "pub", pr.number,
                comment.id, "Someone else's words.")
        self.assertEqual(caught.exception.reason, "permission_denied")
        edited = self.lines.edit_line_comment(
            self.reader, "volmarr", "pub", pr.number,
            comment.id, "Second wording.")
        self.assertEqual(edited.body, "Second wording.")
        self.assertTrue(edited.was_edited)
        self.assertEqual(
            (edited.side, edited.line_number, edited.line_text),
            ("new", 2, "BETA"))
        history = self.lines.edits_for(
            self.third, "volmarr", "pub", pr.number, comment.id)
        self.assertEqual([h.previous_body for h in history],
                         ["First wording."])

    def test_delete_is_a_tombstone_by_author_or_admin(self):
        pr = self._open()
        mine = self.lines.add_line_comment(
            self.reader, "volmarr", "pub", pr.number,
            "a.txt", "new", 2, "Mine.")
        theirs = self.lines.add_line_comment(
            self.third, "volmarr", "pub", pr.number,
            "a.txt", "new", 3, "Theirs.")
        with self.assertRaises(PullRequestError) as caught:
            self.lines.delete_line_comment(
                self.reader, "volmarr", "pub", pr.number, theirs.id)
        self.assertEqual(caught.exception.reason, "permission_denied")
        # The repository owner is its admin and may remove it.
        removed = self.lines.delete_line_comment(
            self.owner, "volmarr", "pub", pr.number, theirs.id)
        self.assertTrue(removed.is_deleted)
        deleted = self.lines.delete_line_comment(
            self.reader, "volmarr", "pub", pr.number, mine.id)
        self.assertTrue(deleted.is_deleted)
        self.assertEqual(self.lines.list_line_comments(
            self.reader, "volmarr", "pub", pr.number), [])
        tombstone = self.lines.get_line_comment(
            self.reader, "volmarr", "pub", pr.number, mine.id)
        self.assertTrue(tombstone.is_deleted)
        self.assertEqual(tombstone.body, "")

    # -- cross-fork + rendering + permissions ---------------------------------------
    def test_cross_fork_line_comments_anchor_on_the_fork_diff(self):
        forks = ForkStore(self.conn, self.root, self.accounts,
                          self.repos, audit=self.audit)
        xprs = ForkPullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        forks.fork(self.reader.id, "volmarr", "pub")
        fork_path = self.repos.path_for("yrsa", "pub")
        fork_head = make_commit(
            fork_path, self.base_oid,
            {"a.txt": "alpha\nbeta\ngamma\nfork line\n",
             "b.txt": "bee\n", "d.txt": "dee\n"}, "fork work")
        git(fork_path, "update-ref", "refs/heads/feature", fork_head)
        created = xprs.create_cross_fork_pull_request(
            self.reader, "volmarr", "pub", base_branch="main",
            head_owner="yrsa", head_repo="pub", head_branch="feature")
        comment = self.lines.add_line_comment(
            self.owner, "volmarr", "pub", created.number,
            "a.txt", "new", 4, "From the fork.")
        self.assertEqual(comment.line_text, "fork line")
        self.assertFalse(comment.is_outdated)

    def test_rendering_says_anchor_and_state_in_words_and_escapes(self):
        pr = self._open()
        self.lines.add_line_comment(
            self.reader, "volmarr", "pub", pr.number,
            "a.txt", "new", 2, "Watch <this> line.")
        page = render_line_comments(self.lines.list_line_comments(
            self.reader, "volmarr", "pub", pr.number))
        self.assertIn("a.txt, line 2 on the new side · Current", page)
        self.assertIn("Watch &lt;this&gt; line.", page)
        self.assertNotIn("Watch <this> line.", page)
        self.assertIn("No line comments", render_line_comments([]))

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
        comment = self.lines.add_line_comment(
            self.owner, "volmarr", "priv", pr.number,
            "s.txt", "new", 2, "Owner's note.")
        for call in (
                lambda: self.lines.list_line_comments(
                    self.reader, "volmarr", "priv", pr.number),
                lambda: self.lines.add_line_comment(
                    self.reader, "volmarr", "priv", pr.number,
                    "s.txt", "new", 2, "Stranger's note."),
                lambda: self.lines.get_line_comment(
                    self.reader, "volmarr", "priv", pr.number,
                    comment.id)):
            with self.assertRaises(PullRequestError) as caught:
                call()
            self.assertEqual(
                caught.exception.reason, "pull_request_not_found")


if __name__ == "__main__":
    unittest.main()
