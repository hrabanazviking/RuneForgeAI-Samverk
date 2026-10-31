"""S-147 acceptance battery: pull request review threads.

Acceptance (roadmap S-147): review threads — threaded
replies on line comments, resolve/unresolve by author
or reviewer, resolution state feeds merge gates.

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
from samverk.pull_request_line_comments import PullRequestLineCommentStore
from samverk.pull_request_review_threads import (
    PullRequestReviewThreadStore, render_thread)
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


BASE_FILES = {"a.txt": "alpha\nbeta\ngamma\n", "b.txt": "bee\n"}
HEAD_FILES = {"a.txt": "alpha\nBETA\ngamma\ndelta\n", "b.txt": "bee\n"}


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


class ReviewThreadTests(unittest.TestCase):
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
        self.threads = PullRequestReviewThreadStore(
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
        self.pr = self.prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch="feature")
        self.root_comment = self.lines.add_line_comment(
            self.reader, "volmarr", "pub", self.pr.number,
            "a.txt", "new", 2, "Why BETA in capitals?")

    def _audit_count(self, action):
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM audit_log WHERE action = ?",
            (action,)).fetchone()
        return int(row["c"])

    # -- replies ---------------------------------------------------------
    def test_replies_gather_under_the_root_in_order(self):
        first = self.threads.add_reply(
            self.owner, "volmarr", "pub", self.pr.number,
            self.root_comment.id, "Because it shouts.")
        second = self.threads.add_reply(
            self.third, "volmarr", "pub", self.pr.number,
            self.root_comment.id, "It does shout.")
        thread = self.threads.thread_for(
            self.reader, "volmarr", "pub", self.pr.number,
            self.root_comment.id)
        self.assertEqual(thread.root.id, self.root_comment.id)
        self.assertEqual([r.id for r in thread.replies],
                         [first.id, second.id])
        self.assertEqual(thread.reply_count, 2)
        self.assertFalse(thread.is_resolved)
        self.assertEqual(thread.resolution_words, "Unresolved")
        threads = self.threads.threads_for(
            self.reader, "volmarr", "pub", self.pr.number)
        self.assertEqual(len(threads), 1)

    def test_reply_to_a_missing_or_deleted_root_stores_nothing(self):
        other = self.lines.add_line_comment(
            self.reader, "volmarr", "pub", self.pr.number,
            "a.txt", "new", 3, "Gamma note.")
        self.lines.delete_line_comment(
            self.reader, "volmarr", "pub", self.pr.number, other.id)
        for target in (9999, other.id):
            with self.assertRaises(PullRequestError) as caught:
                self.threads.add_reply(
                    self.owner, "volmarr", "pub", self.pr.number,
                    target, "Anyone there?")
            self.assertEqual(caught.exception.reason, "comment_not_found")
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM pull_request_line_replies"
        ).fetchone()
        self.assertEqual(int(row["c"]), 0)

    def test_reply_edit_history_and_delete_tombstone(self):
        reply = self.threads.add_reply(
            self.owner, "volmarr", "pub", self.pr.number,
            self.root_comment.id, "First wording.")
        with self.assertRaises(PullRequestError) as caught:
            self.threads.edit_reply(
                self.third, "volmarr", "pub", self.pr.number,
                self.root_comment.id, reply.id, "Not yours.")
        self.assertEqual(caught.exception.reason, "permission_denied")
        edited = self.threads.edit_reply(
            self.owner, "volmarr", "pub", self.pr.number,
            self.root_comment.id, reply.id, "Second wording.")
        self.assertEqual(edited.body, "Second wording.")
        history = self.threads.reply_edits_for(
            self.third, "volmarr", "pub", self.pr.number,
            self.root_comment.id, reply.id)
        self.assertEqual([h.previous_body for h in history],
                         ["First wording."])
        deleted = self.threads.delete_reply(
            self.owner, "volmarr", "pub", self.pr.number,
            self.root_comment.id, reply.id)
        self.assertTrue(deleted.is_deleted)
        thread = self.threads.thread_for(
            self.owner, "volmarr", "pub", self.pr.number,
            self.root_comment.id)
        self.assertEqual(thread.replies, ())

    # -- resolution ---------------------------------------------------------
    def test_the_root_author_resolves_and_the_pr_author_unresolves(self):
        resolved = self.threads.resolve_thread(
            self.reader, "volmarr", "pub", self.pr.number,
            self.root_comment.id)
        self.assertTrue(resolved.is_resolved)
        self.assertEqual(resolved.resolved_by, self.reader.id)
        self.assertEqual(resolved.resolution_words, "Resolved")
        reopened = self.threads.unresolve_thread(
            self.owner, "volmarr", "pub", self.pr.number,
            self.root_comment.id)
        self.assertFalse(reopened.is_resolved)
        self.assertIsNone(reopened.resolved_by)

    def test_a_mere_reader_cannot_change_resolution(self):
        for call in (
                lambda: self.threads.resolve_thread(
                    self.third, "volmarr", "pub", self.pr.number,
                    self.root_comment.id),
                lambda: self.threads.unresolve_thread(
                    self.third, "volmarr", "pub", self.pr.number,
                    self.root_comment.id)):
            with self.assertRaises(PullRequestError) as caught:
                call()
            self.assertEqual(caught.exception.reason, "permission_denied")
        self.assertEqual(
            self._audit_count("repo.pull_request.thread_resolve"), 0)

    def test_a_base_writer_resolves_a_cross_fork_thread(self):
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
             "b.txt": "bee\n"}, "fork work")
        git(fork_path, "update-ref", "refs/heads/feature", fork_head)
        created = xprs.create_cross_fork_pull_request(
            self.reader, "volmarr", "pub", base_branch="main",
            head_owner="yrsa", head_repo="pub", head_branch="feature")
        root = self.lines.add_line_comment(
            self.third, "volmarr", "pub", created.number,
            "a.txt", "new", 4, "A third party's note.")
        # The owner is neither the root's author nor the
        # PR's author — a writer of the base repository.
        resolved = self.threads.resolve_thread(
            self.owner, "volmarr", "pub", created.number, root.id)
        self.assertTrue(resolved.is_resolved)

    def test_resolution_retries_are_quiet_no_ops(self):
        self.threads.resolve_thread(
            self.reader, "volmarr", "pub", self.pr.number,
            self.root_comment.id)
        again = self.threads.resolve_thread(
            self.owner, "volmarr", "pub", self.pr.number,
            self.root_comment.id)
        self.assertTrue(again.is_resolved)
        self.assertEqual(again.resolved_by, self.reader.id)
        self.assertEqual(
            self._audit_count("repo.pull_request.thread_resolve"), 1)
        self.threads.unresolve_thread(
            self.reader, "volmarr", "pub", self.pr.number,
            self.root_comment.id)
        quiet = self.threads.unresolve_thread(
            self.reader, "volmarr", "pub", self.pr.number,
            self.root_comment.id)
        self.assertFalse(quiet.is_resolved)
        self.assertEqual(
            self._audit_count("repo.pull_request.thread_unresolve"), 1)

    def test_replying_never_changes_resolution(self):
        self.threads.resolve_thread(
            self.reader, "volmarr", "pub", self.pr.number,
            self.root_comment.id)
        self.threads.add_reply(
            self.third, "volmarr", "pub", self.pr.number,
            self.root_comment.id, "One more thought.")
        thread = self.threads.thread_for(
            self.reader, "volmarr", "pub", self.pr.number,
            self.root_comment.id)
        self.assertTrue(thread.is_resolved)
        self.assertEqual(thread.reply_count, 1)

    # -- the merge-gate summary --------------------------------------------
    def test_the_summary_counts_for_the_merge_gates(self):
        empty = self.threads.resolution_summary(
            self.reader, "volmarr", "pub", self.pr.number)
        # The setUp root is the one thread so far.
        self.assertEqual(
            (empty.total, empty.resolved, empty.unresolved), (1, 0, 1))
        self.assertTrue(empty.blocks_merge)
        self.assertEqual(empty.words,
                         "1 of 1 review threads is unresolved.")
        self.lines.add_line_comment(
            self.third, "volmarr", "pub", self.pr.number,
            "a.txt", "new", 3, "Second thread.")
        self.threads.resolve_thread(
            self.reader, "volmarr", "pub", self.pr.number,
            self.root_comment.id)
        summary = self.threads.resolution_summary(
            self.reader, "volmarr", "pub", self.pr.number)
        self.assertEqual(
            (summary.total, summary.resolved, summary.unresolved),
            (2, 1, 1))
        self.assertTrue(summary.blocks_merge)
        self.assertEqual(summary.words,
                         "1 of 2 review threads is unresolved.")

    def test_an_outdated_thread_still_counts_and_resolves(self):
        new_head = make_commit(
            self.path, self.head_oid,
            {"a.txt": "alpha\nBETA2\ngamma\ndelta\n",
             "b.txt": "bee\n"}, "rewrite the line")
        git(self.path, "update-ref", "refs/heads/feature", new_head)
        thread = self.threads.thread_for(
            self.reader, "volmarr", "pub", self.pr.number,
            self.root_comment.id)
        self.assertTrue(thread.root.is_outdated)
        resolved = self.threads.resolve_thread(
            self.reader, "volmarr", "pub", self.pr.number,
            self.root_comment.id)
        self.assertTrue(resolved.is_resolved)
        summary = self.threads.resolution_summary(
            self.reader, "volmarr", "pub", self.pr.number)
        self.assertEqual(summary.words,
                         "All review threads are resolved.")
        self.assertFalse(summary.blocks_merge)

    # -- rendering + permissions ----------------------------------------------
    def test_rendering_says_resolution_in_words_and_escapes(self):
        self.threads.add_reply(
            self.owner, "volmarr", "pub", self.pr.number,
            self.root_comment.id, "Fixed in <the> next push.")
        thread = self.threads.thread_for(
            self.reader, "volmarr", "pub", self.pr.number,
            self.root_comment.id)
        page = render_thread(thread)
        self.assertIn("a.txt, line 2 on the new side", page)
        self.assertIn("Current · Unresolved", page)
        self.assertIn("Fixed in &lt;the&gt; next push.", page)
        self.assertNotIn("Fixed in <the> next push.", page)

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
        root = self.lines.add_line_comment(
            self.owner, "volmarr", "priv", pr.number,
            "s.txt", "new", 2, "Owner's note.")
        for call in (
                lambda: self.threads.thread_for(
                    self.reader, "volmarr", "priv", pr.number, root.id),
                lambda: self.threads.add_reply(
                    self.reader, "volmarr", "priv", pr.number,
                    root.id, "Stranger's reply."),
                lambda: self.threads.resolve_thread(
                    self.reader, "volmarr", "priv", pr.number, root.id),
                lambda: self.threads.resolution_summary(
                    self.reader, "volmarr", "priv", pr.number)):
            with self.assertRaises(PullRequestError) as caught:
                call()
            self.assertEqual(
                caught.exception.reason, "pull_request_not_found")


if __name__ == "__main__":
    unittest.main()
