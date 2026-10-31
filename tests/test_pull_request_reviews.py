"""S-148 acceptance battery: pull request review submission.

Acceptance (roadmap S-148): review submission — approve /
comment / request-changes as one review with a summary;
pending-review draft autosaved.

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
from samverk.issue_events_out import ISSUE_EVENT_VERBS, IssueEventOutbox
from samverk.issues import IssueStore
from samverk.pull_request_forks import ForkPullRequestStore
from samverk.pull_request_reviews import (
    PullRequestReviewStore, render_pending_review, render_review,
    render_review_summary)
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


BASE_FILES = {"a.txt": "alpha\nbeta\n"}
HEAD_FILES = {"a.txt": "alpha\nBETA\n"}


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


class ReviewSubmissionTests(unittest.TestCase):
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
        self.forks = ForkStore(self.conn, self.root, self.accounts,
                               self.repos, audit=self.audit)
        self.issues = IssueStore(self.conn, self.repos, self.accounts,
                                 audit=self.audit, time_fn=self.clock)
        self.prs = PullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.xprs = ForkPullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.reviews = PullRequestReviewStore(
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

    def _audit_count(self, action):
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM audit_log WHERE action = ?",
            (action,)).fetchone()
        return int(row["c"])

    # -- submission -----------------------------------------------------
    def test_approve_is_one_review_with_a_summary(self):
        review = self.reviews.submit_review(
            self.reader, "volmarr", "pub", self.pr.number,
            verdict="approve", summary="Looks right to me.")
        self.assertEqual(review.verdict, "approved")
        self.assertEqual(review.verdict_words, "Approved")
        self.assertEqual(review.summary, "Looks right to me.")
        self.assertEqual(review.reviewer_id, self.reader.id)
        self.assertEqual(review.head_oid, self.head_oid)
        listed = self.reviews.reviews_for(
            self.third, "volmarr", "pub", self.pr.number)
        self.assertEqual([r.id for r in listed], [review.id])
        self.assertEqual(
            self._audit_count("repo.pull_request.review_submit"), 1)
        row = self.conn.execute(
            "SELECT detail FROM audit_log"
            " WHERE action = 'repo.pull_request.review_submit'"
        ).fetchone()
        self.assertIn("approved", row["detail"])
        self.assertNotIn("Looks right", row["detail"])

    def test_each_verdict_is_stored_in_its_own_words(self):
        self.reviews.submit_review(
            self.reader, "volmarr", "pub", self.pr.number,
            verdict="comment", summary="A note, no verdict on the code.")
        change = self.reviews.submit_review(
            self.third, "volmarr", "pub", self.pr.number,
            verdict="request_changes", summary="BETA should not shout.")
        self.assertEqual(change.verdict, "changes_requested")
        self.assertEqual(change.verdict_words, "Requested changes")
        verdicts = [r.verdict for r in self.reviews.reviews_for(
            self.owner, "volmarr", "pub", self.pr.number)]
        self.assertEqual(verdicts, ["commented", "changes_requested"])

    def test_unknown_verdict_is_refused_and_stores_nothing(self):
        with self.assertRaises(PullRequestError) as caught:
            self.reviews.submit_review(
                self.reader, "volmarr", "pub", self.pr.number,
                verdict="lgtm", summary="ship it")
        self.assertEqual(caught.exception.reason, "verdict_invalid")
        self.assertEqual(self.reviews.reviews_for(
            self.owner, "volmarr", "pub", self.pr.number), [])
        self.assertEqual(
            self._audit_count("repo.pull_request.review_submit"), 0)

    def test_requesting_changes_needs_a_summary(self):
        with self.assertRaises(PullRequestError) as caught:
            self.reviews.submit_review(
                self.reader, "volmarr", "pub", self.pr.number,
                verdict="request_changes", summary="")
        self.assertEqual(caught.exception.reason, "summary_required")
        self.assertEqual(self.reviews.reviews_for(
            self.owner, "volmarr", "pub", self.pr.number), [])

    def test_the_author_cannot_verdict_their_own_pull_request(self):
        for verdict in ("approve", "request_changes"):
            with self.assertRaises(PullRequestError) as caught:
                self.reviews.submit_review(
                    self.owner, "volmarr", "pub", self.pr.number,
                    verdict=verdict, summary="My own work, surely fine.")
            self.assertEqual(caught.exception.reason, "self_review")
        note = self.reviews.submit_review(
            self.owner, "volmarr", "pub", self.pr.number,
            verdict="comment", summary="Author's note for reviewers.")
        self.assertEqual(note.verdict, "commented")

    def test_a_review_on_a_cross_fork_pull_request_records_its_head(self):
        self.forks.fork(self.reader.id, "volmarr", "pub")
        fork_path = self.repos.path_for("yrsa", "pub")
        fork_head = make_commit(
            fork_path, self.base_oid,
            {"a.txt": "alpha\nfrom the fork\n"}, "fork work")
        git(fork_path, "update-ref", "refs/heads/feature", fork_head)
        created = self.xprs.create_cross_fork_pull_request(
            self.reader, "volmarr", "pub", base_branch="main",
            head_owner="yrsa", head_repo="pub", head_branch="feature")
        review = self.reviews.submit_review(
            self.owner, "volmarr", "pub", created.number,
            verdict="approve", summary="Fork work reads well.")
        self.assertEqual(review.head_oid, fork_head)

    # -- pending review (autosave) ---------------------------------------
    def test_pending_review_autosaves_by_replacement(self):
        first = self.reviews.save_pending_review(
            self.reader, "volmarr", "pub", self.pr.number,
            verdict=None, summary="start of a thought")
        self.clock.now += 60
        second = self.reviews.save_pending_review(
            self.reader, "volmarr", "pub", self.pr.number,
            verdict="request_changes", summary="BETA should not shout.")
        self.assertEqual(second.created_at, first.created_at)
        self.assertGreater(second.updated_at, first.updated_at)
        self.assertEqual(second.verdict, "request_changes")
        found = self.reviews.pending_review_for(
            self.reader, "volmarr", "pub", self.pr.number)
        self.assertEqual(found.summary, "BETA should not shout.")
        # Autosave publishes nothing and audits nothing.
        self.assertEqual(self.reviews.reviews_for(
            self.owner, "volmarr", "pub", self.pr.number), [])
        self.assertEqual(
            self._audit_count("repo.pull_request.review_submit"), 0)

    def test_a_pending_review_is_the_reviewers_own(self):
        self.reviews.save_pending_review(
            self.reader, "volmarr", "pub", self.pr.number,
            verdict="approve", summary="draft")
        self.assertIsNone(self.reviews.pending_review_for(
            self.third, "volmarr", "pub", self.pr.number))
        self.assertIsNone(self.reviews.pending_review_for(
            None, "volmarr", "pub", self.pr.number))

    def test_submission_from_the_pending_draft_consumes_it(self):
        self.reviews.save_pending_review(
            self.reader, "volmarr", "pub", self.pr.number,
            verdict="approve", summary="Saved earlier, sent now.")
        review = self.reviews.submit_review(
            self.reader, "volmarr", "pub", self.pr.number)
        self.assertEqual(review.verdict, "approved")
        self.assertEqual(review.summary, "Saved earlier, sent now.")
        self.assertIsNone(self.reviews.pending_review_for(
            self.reader, "volmarr", "pub", self.pr.number))
        self.assertEqual(
            self._audit_count("repo.pull_request.review_submit"), 1)

    def test_explicit_submission_wins_over_the_pending_draft(self):
        self.reviews.save_pending_review(
            self.reader, "volmarr", "pub", self.pr.number,
            verdict="approve", summary="old draft words")
        review = self.reviews.submit_review(
            self.reader, "volmarr", "pub", self.pr.number,
            verdict="comment", summary="final words")
        self.assertEqual(review.verdict, "commented")
        self.assertEqual(review.summary, "final words")

    def test_discarding_the_pending_draft_leaves_nothing_to_submit(self):
        self.assertFalse(self.reviews.discard_pending_review(
            self.reader, "volmarr", "pub", self.pr.number))
        self.reviews.save_pending_review(
            self.reader, "volmarr", "pub", self.pr.number,
            verdict="approve", summary="draft")
        self.assertTrue(self.reviews.discard_pending_review(
            self.reader, "volmarr", "pub", self.pr.number))
        with self.assertRaises(PullRequestError) as caught:
            self.reviews.submit_review(
                self.reader, "volmarr", "pub", self.pr.number)
        self.assertEqual(caught.exception.reason, "verdict_invalid")

    # -- refusals -----------------------------------------------------------
    def test_a_closed_pull_request_takes_no_reviews(self):
        # No seam closes a pull request yet (the merge slices
        # own closing), so the closed state is arranged at the
        # storage layer those slices will write — the guard
        # under test reads exactly it, as in S-143's battery.
        with self.conn:
            self.conn.execute(
                "UPDATE issues SET state = 'closed' WHERE id = ?",
                (self.pr.row_id,))
        for call in (
                lambda: self.reviews.save_pending_review(
                    self.reader, "volmarr", "pub", self.pr.number,
                    verdict="approve", summary="too late"),
                lambda: self.reviews.submit_review(
                    self.reader, "volmarr", "pub", self.pr.number,
                    verdict="approve", summary="too late")):
            with self.assertRaises(PullRequestError) as caught:
                call()
            self.assertEqual(
                caught.exception.reason, "pull_request_closed")

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
                lambda: self.reviews.submit_review(
                    self.reader, "volmarr", "priv", pr.number,
                    verdict="approve", summary="x"),
                lambda: self.reviews.reviews_for(
                    self.reader, "volmarr", "priv", pr.number)):
            with self.assertRaises(PullRequestError) as caught:
                call()
            self.assertEqual(
                caught.exception.reason, "pull_request_not_found")

    # -- summary + rendering --------------------------------------------------
    def test_review_summary_counts_and_names_the_latest_verdicts(self):
        self.reviews.submit_review(
            self.reader, "volmarr", "pub", self.pr.number,
            verdict="approve", summary="yes")
        self.reviews.submit_review(
            self.third, "volmarr", "pub", self.pr.number,
            verdict="request_changes", summary="not yet")
        self.reviews.submit_review(
            self.reader, "volmarr", "pub", self.pr.number,
            verdict="comment", summary="second look")
        summary = self.reviews.review_summary(
            self.owner, "volmarr", "pub", self.pr.number)
        self.assertEqual(summary.total, 3)
        self.assertEqual(summary.approved, 1)
        self.assertEqual(summary.changes_requested, 1)
        self.assertEqual(summary.commented, 1)
        self.assertEqual(
            summary.latest_by_reviewer[self.reader.id], "commented")
        self.assertEqual(
            summary.latest_by_reviewer[self.third.id],
            "changes_requested")
        self.assertFalse(summary.has_approval)
        self.assertTrue(summary.has_change_request)
        self.assertIn("3 reviews submitted", summary.words)

    def test_rendering_says_verdicts_in_words_and_escapes_summaries(self):
        review = self.reviews.submit_review(
            self.reader, "volmarr", "pub", self.pr.number,
            verdict="comment", summary="<script>alert(1)</script>")
        html = render_review(review)
        self.assertIn("Commented", html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)
        pending_html = render_pending_review(None)
        self.assertIn("No review is being composed", pending_html)
        summary = self.reviews.review_summary(
            self.owner, "volmarr", "pub", self.pr.number)
        self.assertIn("1 review submitted", render_review_summary(summary))

    def test_submissions_reach_the_outbox(self):
        self.assertIn("repo.pull_request.review_submit", ISSUE_EVENT_VERBS)
        self.reviews.submit_review(
            self.reader, "volmarr", "pub", self.pr.number,
            verdict="approve", summary="yes")
        outbox = IssueEventOutbox(self.conn, self.repos, self.accounts)
        verbs = [event.verb for event in outbox.list_events(
            self.owner, "volmarr", "pub")]
        self.assertIn("repo.pull_request.review_submit", verbs)


if __name__ == "__main__":
    unittest.main()
