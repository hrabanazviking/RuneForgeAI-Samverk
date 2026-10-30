"""S-143 acceptance battery: draft pull requests.

Acceptance (roadmap S-143): draft pull requests —
visible, reviewable, unmergeable until marked ready;
conversion is an event.

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
from samverk.issue_conversion import IssueConversionStore
from samverk.issue_events_out import ISSUE_EVENT_VERBS, IssueEventOutbox
from samverk.issues import IssueStore
from samverk.pull_request_drafts import (
    PullRequestDraftStore, merge_blocker, render_readiness)
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
        blob = git(repo, "hash-object", "-w", "--stdin",
                   input_bytes=files[name].encode())
        lines.append(f"100644 blob {blob}\t{name}\n")
    tree = git(repo, "mktree", input_bytes="".join(lines).encode())
    args = ["commit-tree", tree]
    if parent:
        args += ["-p", parent]
    return git(repo, *args, input_bytes=(message + "\n").encode())


class DraftPullRequestTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.reader = self.accounts.register("yrsa", "correct horse battery")
        self.third = self.accounts.register("tess", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.forks = ForkStore(self.conn, self.root, self.accounts,
                               self.repos, audit=self.audit)
        self.issues = IssueStore(self.conn, self.repos, self.accounts,
                                 audit=self.audit)
        self.prs = PullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit)
        self.xprs = ForkPullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit)
        self.drafts = PullRequestDraftStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        base_path = self.repos.path_for("volmarr", "pub")
        self.base_oid = make_commit(
            base_path, None, {"a.txt": "base\n"}, "base commit")
        git(base_path, "update-ref", "refs/heads/main", self.base_oid)
        feature_oid = make_commit(
            base_path, self.base_oid,
            {"a.txt": "base\nfeature\n"}, "feature work")
        git(base_path, "update-ref", "refs/heads/feature", feature_oid)
        self.issue = self.issues.create_issue(
            self.owner, "volmarr", "pub", "An ordinary issue")

    def _audit_count(self, action):
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM audit_log WHERE action = ?",
            (action,)).fetchone()
        return int(row["c"])

    def _open(self, draft=False):
        return self.prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch="feature", draft=draft)

    # -- birth ------------------------------------------------------------
    def test_draft_born_through_the_same_repo_seam(self):
        pr = self._open(draft=True)
        self.assertTrue(pr.is_draft)
        self.assertEqual(pr.state_words, "draft pull request")
        listed = self.prs.list_pull_requests(
            self.reader, "volmarr", "pub")
        self.assertEqual([p.number for p in listed], [pr.number])
        readiness = self.drafts.readiness(
            self.reader, "volmarr", "pub", pr.number)
        self.assertTrue(readiness.is_draft)
        self.assertFalse(readiness.can_merge)
        self.assertIn("draft", readiness.merge_blocker)
        self.assertIn("Mark it ready", readiness.merge_blocker)
        line = render_readiness(readiness)
        self.assertIn("draft pull request", line)
        self.assertIn("cannot be merged", line)
        rows = self.conn.execute(
            "SELECT detail FROM audit_log"
            " WHERE action = 'repo.pull_request.create'").fetchall()
        self.assertIn('"draft":true', rows[0]["detail"])

    def test_ordinary_creation_is_born_ready(self):
        pr = self._open()
        self.assertFalse(pr.is_draft)
        readiness = self.drafts.readiness(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(readiness.merge_blocker, "")
        self.assertTrue(readiness.can_merge)
        self.assertIn("Ready for review", readiness.words)

    # -- the conversions ------------------------------------------------------
    def test_mark_ready_is_an_event_and_retries_are_quiet(self):
        pr = self._open(draft=True)
        ready = self.drafts.mark_ready(
            self.owner, "volmarr", "pub", pr.number)
        self.assertFalse(ready.is_draft)
        self.assertEqual(ready.state_words, "open pull request")
        self.assertEqual(
            self._audit_count("repo.pull_request.mark_ready"), 1)
        again = self.drafts.mark_ready(
            self.owner, "volmarr", "pub", pr.number)
        self.assertFalse(again.is_draft)
        self.assertEqual(
            self._audit_count("repo.pull_request.mark_ready"), 1)
        self.assertEqual(merge_blocker(ready), "")

    def test_convert_back_to_draft_is_an_event(self):
        pr = self._open()
        drafted = self.drafts.convert_to_draft(
            self.owner, "volmarr", "pub", pr.number)
        self.assertTrue(drafted.is_draft)
        self.assertEqual(
            self._audit_count("repo.pull_request.convert_to_draft"), 1)
        self.drafts.convert_to_draft(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(
            self._audit_count("repo.pull_request.convert_to_draft"), 1)
        # And the round trip back is a second, real mark-ready event.
        self.drafts.mark_ready(self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(
            self._audit_count("repo.pull_request.mark_ready"), 1)

    def test_conversion_born_draft_can_be_marked_ready(self):
        conversion = IssueConversionStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit)
        pr = conversion.convert_issue(
            self.owner, "volmarr", "pub", self.issue.number)
        self.assertTrue(pr.is_draft)
        ready = self.drafts.mark_ready(
            self.owner, "volmarr", "pub", pr.number)
        self.assertFalse(ready.is_draft)
        self.assertEqual(
            self._audit_count("repo.pull_request.mark_ready"), 1)

    def test_cross_fork_draft_and_a_base_writer_marks_it_ready(self):
        self.forks.fork(self.reader.id, "volmarr", "pub")
        fork_path = self.repos.path_for("yrsa", "pub")
        head_oid = make_commit(
            fork_path, self.base_oid,
            {"a.txt": "base\nfrom the fork\n"}, "fork work")
        git(fork_path, "update-ref", "refs/heads/feature", head_oid)
        created = self.xprs.create_cross_fork_pull_request(
            self.reader, "volmarr", "pub", base_branch="main",
            head_owner="yrsa", head_repo="pub", head_branch="feature",
            draft=True)
        self.assertTrue(created.pull_request.is_draft)
        # A mere reader of the base who is not the author cannot.
        with self.assertRaises(PullRequestError) as caught:
            self.drafts.mark_ready(
                self.third, "volmarr", "pub", created.number)
        self.assertEqual(caught.exception.reason, "permission_denied")
        # The base repository's owner — a writer, not the
        # author — can; so can the author herself afterwards.
        ready = self.drafts.mark_ready(
            self.owner, "volmarr", "pub", created.number)
        self.assertFalse(ready.is_draft)
        drafted = self.drafts.convert_to_draft(
            self.reader, "volmarr", "pub", created.number)
        self.assertTrue(drafted.is_draft)

    # -- refusals ----------------------------------------------------------------
    def test_reader_cannot_convert_and_closed_cannot_change(self):
        pr = self._open(draft=True)
        with self.assertRaises(PullRequestError) as caught:
            self.drafts.mark_ready(
                self.reader, "volmarr", "pub", pr.number)
        self.assertEqual(caught.exception.reason, "permission_denied")
        # No seam closes a pull request yet (S-130's issue
        # seam refuses PR rows by kind; closing/merging a PR
        # is the merge slices' road), so the closed state is
        # arranged at the storage layer those slices will
        # write — the guard under test reads exactly it.
        with self.conn:
            self.conn.execute(
                "UPDATE issues SET state = 'closed' WHERE id = ?",
                (pr.row_id,))
        for call in (self.drafts.mark_ready,
                     self.drafts.convert_to_draft):
            with self.assertRaises(PullRequestError) as caught:
                call(self.owner, "volmarr", "pub", pr.number)
            self.assertEqual(
                caught.exception.reason, "pull_request_closed")
        readiness = self.drafts.readiness(
            self.owner, "volmarr", "pub", pr.number)
        self.assertIn("closed", readiness.merge_blocker)

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
            head_branch="feature", draft=True)
        for call in (
                lambda: self.drafts.mark_ready(
                    self.reader, "volmarr", "priv", pr.number),
                lambda: self.drafts.readiness(
                    self.reader, "volmarr", "priv", pr.number)):
            with self.assertRaises(PullRequestError) as caught:
                call()
            self.assertEqual(
                caught.exception.reason, "pull_request_not_found")

    # -- events out ------------------------------------------------------------------
    def test_transitions_reach_the_outbox(self):
        self.assertIn("repo.pull_request.mark_ready", ISSUE_EVENT_VERBS)
        self.assertIn(
            "repo.pull_request.convert_to_draft", ISSUE_EVENT_VERBS)
        pr = self._open(draft=True)
        self.drafts.mark_ready(self.owner, "volmarr", "pub", pr.number)
        outbox = IssueEventOutbox(self.conn, self.repos, self.accounts)
        verbs = [event.verb for event in outbox.list_events(
            self.owner, "volmarr", "pub")]
        self.assertIn("repo.pull_request.create", verbs)
        self.assertIn("repo.pull_request.mark_ready", verbs)


if __name__ == "__main__":
    unittest.main()
