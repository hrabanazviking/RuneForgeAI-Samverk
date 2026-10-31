"""S-149 acceptance battery: pull request review freshness.

Acceptance (roadmap S-149): review freshness — new pushes
mark affected reviews stale per repo policy; the PR shows
exactly which reviews still count.

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
from samverk.pull_request_review_freshness import (
    POLICY_MODES, PullRequestReviewFreshnessStore,
    render_freshness_policy, render_freshness_report)
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
PUSHED_FILES = {"a.txt": "alpha\nBETA\ngamma\n"}


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


class ReviewFreshnessTests(unittest.TestCase):
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
        self.freshness = PullRequestReviewFreshnessStore(
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

    # -- helpers ---------------------------------------------------------
    def _push(self):
        """A new push to the head branch: one more commit."""
        self.pushed_oid = make_commit(
            self.path, self.head_oid, PUSHED_FILES, "more feature work")
        git(self.path, "update-ref", "refs/heads/feature", self.pushed_oid)

    def _approve(self, who=None):
        return self.reviews.submit_review(
            who or self.reader, "volmarr", "pub", self.pr.number,
            verdict="approve", summary="Looks right to me.")

    def _settings_changes(self):
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM audit_log"
            " WHERE action = 'repo.settings.change'"
            " AND detail LIKE '%review_freshness_policy%'").fetchone()
        return int(row["c"])

    def _report(self, who=None):
        return self.freshness.freshness_for(
            who or self.owner, "volmarr", "pub", self.pr.number)

    # -- the policy ---------------------------------------------------------
    def test_the_default_policy_never_stale_dates_a_review(self):
        policy = self.freshness.policy_for(
            self.reader, "volmarr", "pub")
        self.assertEqual(policy.mode, "never")
        self.assertIn("never go stale", policy.words)
        self._approve()
        self._push()
        report = self._report()
        self.assertEqual(report.total, 1)
        self.assertEqual(report.stale_count, 0)
        self.assertTrue(report.entries[0].counts)
        self.assertTrue(report.has_counting_approval)
        self.assertIn("1 review still count: 1 approved", report.words)

    def test_setting_the_policy_is_audited_once_and_retries_are_quiet(self):
        policy = self.freshness.set_policy(
            self.owner, "volmarr", "pub", "approvals")
        self.assertEqual(policy.mode, "approvals")
        self.assertEqual(self._settings_changes(), 1)
        again = self.freshness.set_policy(
            self.owner, "volmarr", "pub", "approvals")
        self.assertEqual(again.mode, "approvals")
        self.assertEqual(self._settings_changes(), 1)
        self.assertEqual(
            self.freshness.policy_for(self.third, "volmarr", "pub").mode,
            "approvals")

    def test_only_a_repository_admin_can_set_the_policy(self):
        with self.assertRaises(PullRequestError) as caught:
            self.freshness.set_policy(
                self.reader, "volmarr", "pub", "approvals")
        self.assertEqual(caught.exception.reason, "permission_denied")
        self.assertIn("repository admin", str(caught.exception))
        self.assertEqual(
            self.freshness.policy_for(self.owner, "volmarr", "pub").mode,
            "never")
        self.assertEqual(self._settings_changes(), 0)

    def test_an_unknown_policy_mode_is_refused_and_stores_nothing(self):
        for mode in ("sometimes", "", None, 42):
            with self.assertRaises(PullRequestError) as caught:
                self.freshness.set_policy(
                    self.owner, "volmarr", "pub", mode)
            self.assertEqual(caught.exception.reason, "policy_invalid")
        self.assertEqual(
            self.freshness.policy_for(self.owner, "volmarr", "pub").mode,
            "never")

    def test_the_policy_modes_are_the_closed_set(self):
        self.assertEqual(POLICY_MODES, ("never", "approvals", "verdicts"))
        for mode in POLICY_MODES:
            policy = self.freshness.set_policy(
                self.owner, "volmarr", "pub", mode)
            self.assertTrue(policy.words)

    # -- freshness under each mode -------------------------------------------
    def test_approvals_mode_stale_dates_an_approval_on_a_push(self):
        self.freshness.set_policy(self.owner, "volmarr", "pub", "approvals")
        review = self._approve()
        before = self._report()
        self.assertTrue(before.entries[0].counts)
        self.assertEqual(before.current_head_oid, self.head_oid)
        self._push()
        report = self._report()
        self.assertEqual(report.current_head_oid, self.pushed_oid)
        self.assertEqual(report.entries[0].review.id, review.id)
        self.assertTrue(report.entries[0].is_stale)
        self.assertFalse(report.entries[0].counts)
        self.assertIn("Stale", report.entries[0].state_words)
        self.assertFalse(report.has_counting_approval)
        self.assertEqual(report.latest_counting_by_reviewer, {})
        self.assertIn("1 review is stale and no longer count",
                      report.words)

    def test_approvals_mode_keeps_comments_and_change_requests_counting(self):
        self.freshness.set_policy(self.owner, "volmarr", "pub", "approvals")
        self.reviews.submit_review(
            self.reader, "volmarr", "pub", self.pr.number,
            verdict="comment", summary="a note")
        self.reviews.submit_review(
            self.third, "volmarr", "pub", self.pr.number,
            verdict="request_changes", summary="not yet")
        self._push()
        report = self._report()
        self.assertEqual(report.stale_count, 0)
        self.assertEqual(report.fresh_count, 2)
        self.assertTrue(report.has_counting_change_request)

    def test_verdicts_mode_stale_dates_change_requests_too(self):
        self.freshness.set_policy(self.owner, "volmarr", "pub", "verdicts")
        self.reviews.submit_review(
            self.third, "volmarr", "pub", self.pr.number,
            verdict="request_changes", summary="not yet")
        self.reviews.submit_review(
            self.reader, "volmarr", "pub", self.pr.number,
            verdict="comment", summary="a note")
        self._push()
        report = self._report()
        by_verdict = {e.review.verdict: e for e in report.entries}
        self.assertTrue(by_verdict["changes_requested"].is_stale)
        self.assertFalse(by_verdict["commented"].is_stale)
        self.assertFalse(report.has_counting_change_request)
        self.assertEqual(
            report.latest_counting_by_reviewer,
            {self.reader.id: "commented"})

    def test_a_review_submitted_after_the_push_counts(self):
        self.freshness.set_policy(self.owner, "volmarr", "pub", "approvals")
        self._approve()
        self._push()
        self._approve(self.third)
        report = self._report()
        self.assertEqual(
            [(e.review.reviewer_id, e.counts) for e in report.entries],
            [(self.reader.id, False), (self.third.id, True)])
        self.assertTrue(report.has_counting_approval)
        self.assertEqual(
            report.latest_counting_by_reviewer,
            {self.third.id: "approved"})

    def test_freshness_is_judged_on_read_never_stored(self):
        # Submit and push under the default policy, then change
        # the policy: the already-submitted review is re-judged,
        # in both directions, with no stale flag ever written.
        self._approve()
        self._push()
        self.assertTrue(self._report().entries[0].counts)
        self.freshness.set_policy(self.owner, "volmarr", "pub", "approvals")
        self.assertTrue(self._report().entries[0].is_stale)
        self.freshness.set_policy(self.owner, "volmarr", "pub", "never")
        self.assertTrue(self._report().entries[0].counts)

    def test_no_push_no_staleness_even_under_verdicts(self):
        self.freshness.set_policy(self.owner, "volmarr", "pub", "verdicts")
        self._approve()
        report = self._report()
        self.assertEqual(report.stale_count, 0)
        self.assertTrue(report.has_counting_approval)

    # -- cross-fork and privacy ------------------------------------------------
    def test_freshness_reads_a_cross_fork_head_honestly(self):
        self.freshness.set_policy(self.owner, "volmarr", "pub", "approvals")
        self.forks.fork(self.reader.id, "volmarr", "pub")
        fork_path = self.repos.path_for("yrsa", "pub")
        fork_head = make_commit(
            fork_path, self.base_oid,
            {"a.txt": "alpha\nfrom the fork\n"}, "fork work")
        git(fork_path, "update-ref", "refs/heads/feature", fork_head)
        created = self.xprs.create_cross_fork_pull_request(
            self.reader, "volmarr", "pub", base_branch="main",
            head_owner="yrsa", head_repo="pub", head_branch="feature")
        self.reviews.submit_review(
            self.owner, "volmarr", "pub", created.number,
            verdict="approve", summary="Fork work reads well.")
        report = self.freshness.freshness_for(
            self.owner, "volmarr", "pub", created.number)
        self.assertTrue(report.entries[0].counts)
        pushed = make_commit(
            fork_path, fork_head,
            {"a.txt": "alpha\nfrom the fork\nmore\n"}, "fork push")
        git(fork_path, "update-ref", "refs/heads/feature", pushed)
        report = self.freshness.freshness_for(
            self.owner, "volmarr", "pub", created.number)
        self.assertEqual(report.current_head_oid, pushed)
        self.assertTrue(report.entries[0].is_stale)

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
        with self.assertRaises(PullRequestError) as caught:
            self.freshness.freshness_for(
                self.reader, "volmarr", "priv", pr.number)
        self.assertEqual(
            caught.exception.reason, "pull_request_not_found")
        with self.assertRaises(PullRequestError) as caught:
            self.freshness.policy_for(self.reader, "volmarr", "priv")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        with self.assertRaises(PullRequestError) as caught:
            self.freshness.set_policy(
                self.reader, "volmarr", "priv", "approvals")
        self.assertEqual(caught.exception.reason, "repo_not_found")

    # -- rendering ----------------------------------------------------------------
    def test_rendering_says_freshness_in_words(self):
        self.freshness.set_policy(self.owner, "volmarr", "pub", "approvals")
        self._approve()
        self._push()
        report = self._report()
        html = render_freshness_report(report)
        self.assertIn("Stale — no longer counts", html)
        self.assertIn("stale and no longer count", html)
        self.assertIn("Approved", html)
        policy_html = render_freshness_policy(report.policy)
        self.assertIn("Approvals go stale on a push", policy_html)


if __name__ == "__main__":
    unittest.main()
