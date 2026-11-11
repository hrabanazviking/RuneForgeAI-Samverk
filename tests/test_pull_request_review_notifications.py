"""S-165 acceptance battery: review notifications.

Acceptance (roadmap S-165): review notifications —
review requests and submissions emit Part XI events
with reasons (here: the addressed notification store
those events materialise into, one row per recipient,
the S-223 reason stored and shown on every row).

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.forks import ForkStore
from samverk.issues import IssueStore
from samverk.pull_request_codeowners import PullRequestCodeownersStore
from samverk.pull_request_forks import ForkPullRequestStore
from samverk.pull_request_review_notifications import (
    REASONS, REASON_BY_VERB, REVIEW_NOTIFICATION_VERBS,
    ReviewNotificationError, ReviewNotificationStore,
    render_review_notifications)
from samverk.pull_request_review_assignment import ReviewAssignmentStore
from samverk.pull_request_reviews import PullRequestReviewStore
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
CO_BASE_FILES = {"a.txt": "alpha\nbeta\n",
                 "CODEOWNERS": "a.txt @mimir\n"}


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


class ReviewNotificationTests(unittest.TestCase):
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
        self.codeowner = self.accounts.register("mimir", "correct horse battery")
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
        self.assignments = ReviewAssignmentStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.codeowners = PullRequestCodeownersStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.notes = ReviewNotificationStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        self.path = self.repos.path_for("volmarr", "pub")
        self.base_oid = make_commit(self.path, None, BASE_FILES, "base")
        git(self.path, "update-ref", "refs/heads/main", self.base_oid)
        self.head_oid = make_commit(
            self.path, self.base_oid, HEAD_FILES, "feature work")
        git(self.path, "update-ref", "refs/heads/feature", self.head_oid)
        self.pr = self.prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch="feature")

    # -- helpers ---------------------------------------------------------
    def _request(self, *refs, number=None):
        return self.assignments.request_reviewers(
            self.owner, "volmarr", "pub",
            self.pr.number if number is None else number, list(refs))

    def _approve(self, who, number=None):
        return self.reviews.submit_review(
            who, "volmarr", "pub",
            self.pr.number if number is None else number,
            verdict="approve", summary="Looks right to me.")

    def _open_codeowners_pr(self):
        base = make_commit(self.path, None, CO_BASE_FILES, "co base")
        git(self.path, "update-ref", "refs/heads/co-base", base)
        head = make_commit(self.path, base, HEAD_FILES, "co feature")
        git(self.path, "update-ref", "refs/heads/co-feature", head)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="co-base",
            head_branch="co-feature")
        report = self.codeowners.sync_requests(
            self.owner, "volmarr", "pub", pr.number)
        assert report.matched_owners == ("@mimir",), report.words
        return pr

    # -- requests: addressed, with the reason stored -----------------------
    def test_request_notifies_the_requested_reviewer_with_reason(self):
        self._request("@yrsa")
        self.assertEqual(self.notes.sync_repo("volmarr", "pub"), 1)
        inbox = self.notes.inbox(self.reader)
        self.assertEqual(len(inbox), 1)
        note = inbox[0]
        self.assertEqual(note.verb, "repo.pull_request.review_request")
        self.assertEqual(note.action, "review_request")
        self.assertEqual(note.reason, "review-requested")
        self.assertEqual(note.actor, "volmarr")
        self.assertEqual(note.recipient, "yrsa")
        self.assertEqual(note.repository, "volmarr/pub")
        self.assertEqual(note.number, self.pr.number)
        self.assertEqual(note.detail.get("owner_refs"), ["@yrsa"])
        self.assertEqual(self.notes.inbox(self.owner), [])
        self.assertEqual(self.notes.inbox(self.third), [])

    def test_batch_request_notifies_each_resolved_reviewer_once(self):
        self._request("@yrsa", "@tess")
        self.assertEqual(self.notes.sync_all(), 2)
        self.assertEqual(len(self.notes.inbox(self.reader)), 1)
        self.assertEqual(len(self.notes.inbox(self.third)), 1)
        self.assertEqual(self.notes.count_for_recipient(self.reader), 1)

    def test_rerequest_and_dismissal_notify_in_order(self):
        self._request("@yrsa")
        self.assignments.dismiss_request(
            self.owner, "volmarr", "pub", self.pr.number, "@yrsa")
        self._request("@yrsa")  # reactivates: a re-request act
        inbox = self.notes.inbox(self.reader)
        self.assertEqual(
            [(n.verb, n.reason) for n in inbox],
            [("repo.pull_request.review_request", "review-requested"),
             ("repo.pull_request.review_dismiss", "review-dismissed"),
             ("repo.pull_request.review_rerequest", "review-requested")])

    def test_codeowners_request_notifies_the_code_owner(self):
        pr = self._open_codeowners_pr()
        inbox = self.notes.inbox(self.codeowner)
        self.assertEqual(len(inbox), 1)
        self.assertEqual(inbox[0].verb,
                         "repo.pull_request.codeowners_request")
        self.assertEqual(inbox[0].reason, "review-requested")
        self.assertEqual(inbox[0].number, pr.number)

    def test_team_and_unknown_tokens_notify_nobody(self):
        self._request("@org/team", "@ghost")
        self.assertEqual(self.notes.sync_all(), 0)
        for user in (self.owner, self.reader, self.third, self.codeowner):
            self.assertEqual(self.notes.inbox(user), [])

    def test_a_request_the_recipient_cannot_read_notifies_nobody(self):
        path = self.repos.path_for("volmarr", "priv")
        base = make_commit(path, None, BASE_FILES, "base")
        git(path, "update-ref", "refs/heads/main", base)
        head = make_commit(path, base, HEAD_FILES, "feature work")
        git(path, "update-ref", "refs/heads/feature", head)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "priv", base_branch="main",
            head_branch="feature")
        self.assignments.request_reviewers(
            self.owner, "volmarr", "priv", pr.number, ["@yrsa"])
        # yrsa cannot read the private repository, so the
        # notification must not reveal its pull request.
        self.assertEqual(self.notes.sync_all(), 0)
        self.assertEqual(self.notes.inbox(self.reader), [])
        self.assertEqual(
            self.notes.notifications_for_pull_request(
                self.owner, "volmarr", "priv", pr.number), [])

    # -- submissions: the author hears the verdict --------------------------
    def test_submission_notifies_the_author_with_the_verdict(self):
        self._approve(self.reader)
        inbox = self.notes.inbox(self.owner)
        self.assertEqual(len(inbox), 1)
        note = inbox[0]
        self.assertEqual(note.verb, "repo.pull_request.review_submit")
        self.assertEqual(note.reason, "author")
        self.assertEqual(note.actor, "yrsa")
        self.assertEqual(note.detail.get("verdict"), "approved")
        self.assertIn("approved", note.words)
        self.assertEqual(self.notes.inbox(self.reader), [])

    def test_each_submission_is_a_fresh_notification(self):
        self._approve(self.reader)
        self.reviews.submit_review(
            self.third, "volmarr", "pub", self.pr.number,
            verdict="request_changes", summary="Please rework this.")
        inbox = self.notes.inbox(self.owner)
        self.assertEqual(len(inbox), 2)
        self.assertEqual([n.detail.get("verdict") for n in inbox],
                         ["approved", "changes_requested"])
        self.assertTrue(all(n.reason == "author" for n in inbox))

    def test_a_comment_review_notifies_the_author_too(self):
        self.reviews.submit_review(
            self.reader, "volmarr", "pub", self.pr.number,
            verdict="comment", summary="A thought, no verdict.")
        inbox = self.notes.inbox(self.owner)
        self.assertEqual(len(inbox), 1)
        self.assertEqual(inbox[0].detail.get("verdict"), "commented")
        self.assertIn("commented on", inbox[0].words)

    def test_the_actor_is_never_notified_of_their_own_act(self):
        self.reviews.submit_review(
            self.owner, "volmarr", "pub", self.pr.number,
            verdict="comment", summary="Author notes.")
        self.assertEqual(self.notes.sync_all(), 0)
        self.assertEqual(self.notes.inbox(self.owner), [])

    def test_cross_fork_submission_notifies_the_base_author(self):
        self.forks.fork(self.reader.id, "volmarr", "pub")
        fork_path = self.repos.path_for("yrsa", "pub")
        fork_head = make_commit(
            fork_path, self.base_oid,
            {"a.txt": "alpha\nbeta\nfrom the fork\n"}, "fork work")
        git(fork_path, "update-ref", "refs/heads/feature", fork_head)
        opened = self.xprs.create_cross_fork_pull_request(
            self.reader, "volmarr", "pub", base_branch="main",
            head_owner="yrsa", head_repo="pub",
            head_branch="feature", title="From the fork")
        self._approve(self.owner, number=opened.number)
        inbox = self.notes.inbox(self.reader)
        self.assertEqual(len(inbox), 1)
        self.assertEqual(inbox[0].reason, "author")
        self.assertEqual(inbox[0].number, opened.number)
        self.assertEqual(inbox[0].actor, "volmarr")

    # -- exactly-once and quiet acts -----------------------------------------
    def test_exactly_once_across_resyncs(self):
        self._request("@yrsa")
        self._approve(self.reader)
        self.assertEqual(self.notes.sync_repo("volmarr", "pub"), 2)
        self.assertEqual(self.notes.sync_repo("volmarr", "pub"), 0)
        self.assertEqual(self.notes.sync_all(), 0)
        self.assertEqual(len(self.notes.inbox(self.reader)), 1)
        self.assertEqual(len(self.notes.inbox(self.owner)), 1)
        self.assertEqual(len(self.notes.inbox(self.reader)), 1)

    def test_quiet_acts_emit_nothing(self):
        self.reviews.save_pending_review(
            self.reader, "volmarr", "pub", self.pr.number,
            verdict="approve", summary="Still drafting.")
        self._request("@yrsa")
        self._request("@yrsa")  # already requested: a quiet no-op
        with self.assertRaises(PullRequestError) as caught:
            self.reviews.submit_review(
                self.owner, "volmarr", "pub", self.pr.number,
                verdict="approve", summary="My own work.")
        self.assertEqual(caught.exception.reason, "self_review")
        self.assertEqual(self.notes.sync_all(), 1)
        self.assertEqual(len(self.notes.inbox(self.reader)), 1)

    def test_non_review_events_never_leak_in(self):
        self.assertEqual(REVIEW_NOTIFICATION_VERBS, frozenset({
            "repo.pull_request.codeowners_request",
            "repo.pull_request.review_request",
            "repo.pull_request.review_rerequest",
            "repo.pull_request.review_dismiss",
            "repo.pull_request.review_submit"}))
        self.assertNotIn("repo.pull_request.create",
                         REVIEW_NOTIFICATION_VERBS)
        self.assertNotIn("repo.pull_request.merge",
                         REVIEW_NOTIFICATION_VERBS)
        self.issues.create_issue(self.owner, "volmarr", "pub", "Plain issue")
        self.assertEqual(self.notes.sync_all(), 0)

    def test_reasons_are_the_closed_set(self):
        self.assertEqual(REASONS, frozenset({
            "review-requested", "review-dismissed", "author"}))
        self.assertEqual(set(REASON_BY_VERB),
                         set(REVIEW_NOTIFICATION_VERBS))
        self.assertEqual(set(REASON_BY_VERB.values()), set(REASONS))
        self._request("@yrsa")
        self._approve(self.reader)
        for user in (self.owner, self.reader):
            for note in self.notes.inbox(user):
                self.assertIn(note.reason, REASONS)
                self.assertEqual(REASON_BY_VERB[note.verb], note.reason)

    # -- reads: whose inbox, and the S-141 seam -------------------------------
    def test_inbox_belongs_to_its_recipient(self):
        self._request("@yrsa")
        with self.assertRaises(ReviewNotificationError) as caught:
            self.notes.inbox(None)
        self.assertEqual(caught.exception.reason,
                         "authentication_required")
        self.assertEqual(self.notes.inbox(self.third), [])
        self.assertEqual(len(self.notes.inbox(self.reader)), 1)

    def test_pull_request_listing_reads_through_the_seam(self):
        self._request("@yrsa")
        self._approve(self.reader)
        listed = self.notes.notifications_for_pull_request(
            None, "volmarr", "pub", self.pr.number)
        self.assertEqual([n.verb for n in listed],
                         ["repo.pull_request.review_request",
                          "repo.pull_request.review_submit"])
        other = self._open_codeowners_pr()
        listed = self.notes.notifications_for_pull_request(
            self.owner, "volmarr", "pub", self.pr.number)
        self.assertTrue(all(n.number == self.pr.number for n in listed))
        self.assertEqual(len(listed), 2)
        with self.assertRaises(PullRequestError) as caught:
            self.notes.notifications_for_pull_request(
                self.owner, "volmarr", "pub", 999)
        self.assertEqual(caught.exception.reason, "pull_request_not_found")
        with self.assertRaises(PullRequestError) as caught:
            self.notes.notifications_for_pull_request(
                self.reader, "volmarr", "priv", 1)
        self.assertEqual(caught.exception.reason, "pull_request_not_found")

    def test_sync_of_a_missing_repository_is_refused(self):
        with self.assertRaises(ReviewNotificationError) as caught:
            self.notes.sync_repo("volmarr", "nope")
        self.assertEqual(caught.exception.reason, "repo_not_found")

    # -- words, rendering, and what a notification never carries ---------------
    def test_words_and_the_renderer_say_the_reason(self):
        self._request("@yrsa")
        self._approve(self.reader)
        request_note = self.notes.inbox(self.reader)[0]
        self.assertIn("requested your review", request_note.words)
        self.assertIn("volmarr/pub", request_note.words)
        self.assertIn("review requested", request_note.reason_words)
        submit_note = self.notes.inbox(self.owner)[0]
        self.assertIn("you are the author", submit_note.reason_words)
        html = render_review_notifications([request_note])
        self.assertIn("review-notifications", html)
        self.assertIn("requested your review", html)
        self.assertIn("No review notifications yet",
                      render_review_notifications([]))

    def test_notifications_carry_no_summaries(self):
        self.reviews.submit_review(
            self.reader, "volmarr", "pub", self.pr.number,
            verdict="request_changes", summary="SECRET-SUMMARY-165")
        note = self.notes.inbox(self.owner)[0]
        self.assertEqual(set(note.detail),
                         {"number", "review_id", "verdict"})
        self.assertNotIn("SECRET-SUMMARY-165", note.words)
        self.assertNotIn("SECRET-SUMMARY-165",
                         render_review_notifications([note]))

    # -- the record itself ------------------------------------------------------
    def test_migration_64_shape_and_pins(self):
        self.assertEqual(schema_version(self.conn), 109)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)
        cols = {r["name"] for r in self.conn.execute(
            "PRAGMA table_info(pull_request_review_notifications)"
        ).fetchall()}
        self.assertTrue({
            "audit_seq", "recipient_id", "repo_id", "pull_request_id",
            "number", "actor_id", "verb", "reason", "detail_json",
            "created_at"} <= cols)
        audit_before = self.conn.execute(
            "SELECT COUNT(*) AS c FROM audit_log").fetchone()["c"]
        self._request("@yrsa")
        self.notes.sync_all()
        self.notes.inbox(self.reader)
        # Materialising and reading write no audit row of
        # their own: the witness count moves only by the
        # one audited request itself.
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) AS c FROM audit_log").fetchone()["c"],
            audit_before + 1)


if __name__ == "__main__":
    unittest.main()
