"""S-164 acceptance battery: required-review seam.

Acceptance (roadmap S-164): required-review seam — Part
VIII's rules consult review state through one function;
this slice builds the function.

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
from samverk.pull_request_required_review import (
    PullRequestRequiredReviewStore, ReviewRequirement,
    render_required_review_state, resolve_review_state)
from samverk.pull_request_review_assignment import ReviewAssignmentStore
from samverk.pull_request_review_freshness import (
    FreshnessReport, PullRequestReviewFreshnessStore,
    ReviewFreshness, ReviewFreshnessPolicy)
from samverk.pull_request_reviews import PullRequestReviewStore, Review
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
CO_BASE_FILES = {"a.txt": "alpha\nbeta\n",
                 "CODEOWNERS": "a.txt @mimir\n"}


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


class RequiredReviewTests(unittest.TestCase):
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
        self.freshness = PullRequestReviewFreshnessStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.assignments = ReviewAssignmentStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.codeowners = PullRequestCodeownersStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.seam = PullRequestRequiredReviewStore(
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
    def _state(self, requirement=None, *, viewer=None, repo="pub",
               number=None):
        return self.seam.review_state_for(
            viewer if viewer is not None else self.owner,
            "volmarr", repo,
            self.pr.number if number is None else number,
            requirement=requirement)

    def _approve(self, who, number=None):
        return self.reviews.submit_review(
            who, "volmarr", "pub",
            self.pr.number if number is None else number,
            verdict="approve", summary="Looks right to me.")

    def _request_changes(self, who):
        return self.reviews.submit_review(
            who, "volmarr", "pub", self.pr.number,
            verdict="request_changes", summary="Please rework this.")

    def _comment(self, who):
        return self.reviews.submit_review(
            who, "volmarr", "pub", self.pr.number,
            verdict="comment", summary="A thought, no verdict.")

    def _push(self):
        pushed = make_commit(self.path, self.head_oid, PUSHED_FILES,
                             "more feature work")
        git(self.path, "update-ref", "refs/heads/feature", pushed)
        return pushed

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

    # -- the empty position ------------------------------------------------
    def test_no_reviews_meets_an_empty_requirement(self):
        state = self._state()
        self.assertEqual(state.total, 0)
        self.assertEqual(state.approval_count, 0)
        self.assertFalse(state.has_change_request)
        self.assertTrue(state.satisfied)
        self.assertEqual(state.blockers, ())
        self.assertIn("No reviews have been submitted yet.", state.words)
        self.assertIn("requirement is met", state.words)

    def test_no_reviews_falls_short_of_a_count_requirement(self):
        state = self._state(ReviewRequirement(required_approvals=1))
        self.assertFalse(state.satisfied)
        self.assertEqual(len(state.blockers), 1)
        self.assertIn("0 of the 1 required approvals count",
                      state.blockers[0])
        self.assertIn("not met", state.words)

    # -- approvals: counting, distinctness, latest-wins ---------------------
    def test_one_approval_meets_a_one_approval_requirement(self):
        self._approve(self.reader)
        state = self._state(ReviewRequirement(required_approvals=1))
        self.assertTrue(state.satisfied)
        self.assertEqual(state.approval_count, 1)
        self.assertEqual(state.counting_approver_ids, (self.reader.id,))
        self.assertTrue(state.has_approved(self.reader.id))
        self.assertEqual(state.verdict_for(self.reader.id), "approved")

    def test_two_approvals_need_two_distinct_reviewers(self):
        self._approve(self.reader)
        self._approve(self.reader)  # again: still one reviewer
        state = self._state(ReviewRequirement(required_approvals=2))
        self.assertEqual(state.total, 2)
        self.assertEqual(state.approval_count, 1)
        self.assertFalse(state.satisfied)
        self._approve(self.third)
        state = self._state(ReviewRequirement(required_approvals=2))
        self.assertEqual(state.approval_count, 2)
        self.assertTrue(state.satisfied)

    def test_latest_counting_verdict_speaks_for_the_reviewer(self):
        self._approve(self.reader)
        self._request_changes(self.reader)
        state = self._state(ReviewRequirement(required_approvals=1))
        self.assertEqual(state.approval_count, 0)
        self.assertEqual(state.blocking_reviewer_ids, (self.reader.id,))
        self.assertFalse(state.satisfied)
        self._approve(self.reader)
        state = self._state(ReviewRequirement(required_approvals=1))
        self.assertEqual(state.approval_count, 1)
        self.assertEqual(state.blocking_reviewer_ids, ())
        self.assertTrue(state.satisfied)

    def test_a_change_request_blocks_even_an_empty_requirement(self):
        self._request_changes(self.third)
        state = self._state()
        self.assertTrue(state.has_change_request)
        self.assertFalse(state.satisfied)
        self.assertTrue(any("requested changes" in b
                            for b in state.blockers))

    def test_a_comment_neither_approves_nor_blocks(self):
        self._comment(self.reader)
        state = self._state()
        self.assertEqual(state.approval_count, 0)
        self.assertFalse(state.has_change_request)
        self.assertEqual(state.commented_reviewer_ids, (self.reader.id,))
        self.assertTrue(state.satisfied)
        state = self._state(ReviewRequirement(required_approvals=1))
        self.assertFalse(state.satisfied)

    # -- freshness: stale approvals vouch for nothing ------------------------
    def test_a_stale_approval_no_longer_counts(self):
        self._approve(self.reader)
        self.freshness.set_policy(self.owner, "volmarr", "pub", "approvals")
        self._push()
        state = self._state(ReviewRequirement(required_approvals=1))
        self.assertEqual(state.policy_mode, "approvals")
        self.assertEqual(state.total, 1)
        self.assertEqual(state.counting_count, 0)
        self.assertEqual(state.stale_count, 1)
        self.assertEqual(state.approval_count, 0)
        self.assertFalse(state.satisfied)

    def test_returning_the_policy_to_never_counts_it_again(self):
        self._approve(self.reader)
        self.freshness.set_policy(self.owner, "volmarr", "pub", "approvals")
        self._push()
        self.freshness.set_policy(self.owner, "volmarr", "pub", "never")
        state = self._state(ReviewRequirement(required_approvals=1))
        self.assertEqual(state.approval_count, 1)
        self.assertTrue(state.satisfied)

    # -- the author never counts (the pure seam, handed a bad record) --------
    def test_the_authors_own_verdict_never_counts(self):
        def entry(reviewer_id, verdict):
            review = Review(
                id=reviewer_id, pull_request_id=self.pr.id,
                number=self.pr.number, reviewer_id=reviewer_id,
                verdict=verdict, summary="", head_oid="abc",
                submitted_at=1_700_000_000)
            return ReviewFreshness(review=review, is_stale=False)
        report = FreshnessReport(
            full_name="volmarr/pub", number=self.pr.number,
            policy=ReviewFreshnessPolicy(
                full_name="volmarr/pub", mode="never"),
            current_head_oid="abc",
            entries=(entry(self.owner.id, "approved"),
                     entry(self.owner.id, "changes_requested"),
                     entry(self.reader.id, "approved")))
        state = resolve_review_state(
            full_name="volmarr/pub", number=self.pr.number,
            author_id=self.owner.id, freshness=report,
            requirement=ReviewRequirement(required_approvals=1))
        self.assertEqual(state.counting_approver_ids, (self.reader.id,))
        self.assertEqual(state.blocking_reviewer_ids, ())
        self.assertTrue(state.satisfied)

    def test_a_lone_author_approval_meets_nothing(self):
        review = Review(
            id=1, pull_request_id=self.pr.id, number=self.pr.number,
            reviewer_id=self.owner.id, verdict="approved", summary="",
            head_oid="abc", submitted_at=1_700_000_000)
        report = FreshnessReport(
            full_name="volmarr/pub", number=self.pr.number,
            policy=ReviewFreshnessPolicy(
                full_name="volmarr/pub", mode="never"),
            current_head_oid="abc",
            entries=(ReviewFreshness(review=review, is_stale=False),))
        state = resolve_review_state(
            full_name="volmarr/pub", number=self.pr.number,
            author_id=self.owner.id, freshness=report,
            requirement=ReviewRequirement(required_approvals=1))
        self.assertEqual(state.approval_count, 0)
        self.assertFalse(state.satisfied)

    # -- code owners ----------------------------------------------------------
    def test_code_owner_review_is_a_distinct_gate(self):
        pr = self._open_codeowners_pr()
        requirement = ReviewRequirement(
            required_approvals=1, require_code_owner_review=True)
        state = self._state(requirement, number=pr.number)
        self.assertEqual(state.code_owner_user_ids, (self.codeowner.id,))
        self.assertTrue(state.has_code_owners)
        self.assertFalse(state.code_owner_satisfied)
        self.assertIn(self.codeowner.id, state.outstanding_user_ids)
        # A non-owner approval meets the count, not the gate.
        self.reviews.submit_review(
            self.reader, "volmarr", "pub", pr.number,
            verdict="approve", summary="Looks right to me.")
        state = self._state(requirement, number=pr.number)
        self.assertEqual(state.approval_count, 1)
        self.assertEqual(state.code_owner_approver_ids, ())
        self.assertFalse(state.satisfied)
        self.assertTrue(any("Code-owner" in b for b in state.blockers))
        # The code owner's own approval meets both.
        self.reviews.submit_review(
            self.codeowner, "volmarr", "pub", pr.number,
            verdict="approve", summary="My path, my word.")
        state = self._state(requirement, number=pr.number)
        self.assertEqual(state.code_owner_approver_ids, (self.codeowner.id,))
        self.assertTrue(state.code_owner_satisfied)
        self.assertTrue(state.satisfied)
        self.assertNotIn(self.codeowner.id, state.outstanding_user_ids)

    def test_code_owner_requirement_is_vacuous_without_code_owners(self):
        state = self._state(ReviewRequirement(
            require_code_owner_review=True))
        self.assertFalse(state.has_code_owners)
        self.assertTrue(state.code_owner_satisfied)
        self.assertTrue(state.satisfied)

    def test_a_dismissed_code_owner_request_no_longer_stands(self):
        pr = self._open_codeowners_pr()
        self.assignments.dismiss_request(
            self.owner, "volmarr", "pub", pr.number, "@mimir")
        state = self._state(ReviewRequirement(
            require_code_owner_review=True), number=pr.number)
        self.assertEqual(state.code_owner_user_ids, ())
        self.assertFalse(state.has_code_owners)
        self.assertTrue(state.code_owner_satisfied)

    # -- requested and outstanding ---------------------------------------------
    def test_a_requested_reviewer_is_outstanding_until_they_review(self):
        self.assignments.request_reviewers(
            self.owner, "volmarr", "pub", self.pr.number, ["@yrsa"])
        state = self._state()
        self.assertEqual(state.requested_user_ids, (self.reader.id,))
        self.assertEqual(state.outstanding_user_ids, (self.reader.id,))
        self._comment(self.reader)
        state = self._state()
        self.assertEqual(state.requested_user_ids, (self.reader.id,))
        self.assertEqual(state.outstanding_user_ids, ())

    # -- the seam: visibility first, then the position --------------------------
    def test_a_private_repository_is_hidden_from_a_stranger(self):
        path = self.repos.path_for("volmarr", "priv")
        base = make_commit(path, None, BASE_FILES, "base")
        git(path, "update-ref", "refs/heads/main", base)
        head = make_commit(path, base, HEAD_FILES, "feature work")
        git(path, "update-ref", "refs/heads/feature", head)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "priv", base_branch="main",
            head_branch="feature")
        with self.assertRaises(PullRequestError) as caught:
            self.seam.review_state_for(
                self.reader, "volmarr", "priv", pr.number)
        self.assertEqual(caught.exception.reason, "pull_request_not_found")
        state = self.seam.review_state_for(
            self.owner, "volmarr", "priv", pr.number)
        self.assertEqual(state.full_name, "volmarr/priv")

    def test_a_missing_pull_request_is_not_found(self):
        with self.assertRaises(PullRequestError) as caught:
            self._state(number=999)
        self.assertEqual(caught.exception.reason, "pull_request_not_found")

    def test_an_anonymous_reader_of_a_public_repository_can_resolve(self):
        self._approve(self.reader)
        state = self.seam.review_state_for(
            None, "volmarr", "pub", self.pr.number,
            requirement=ReviewRequirement(required_approvals=1))
        self.assertEqual(state.approval_count, 1)
        self.assertTrue(state.satisfied)

    def test_a_cross_fork_approval_counts(self):
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
        self.reviews.submit_review(
            self.owner, "volmarr", "pub", opened.number,
            verdict="approve", summary="Sound work.")
        state = self.seam.review_state_for(
            self.owner, "volmarr", "pub", opened.number,
            requirement=ReviewRequirement(required_approvals=1))
        self.assertEqual(state.author_id, self.reader.id)
        self.assertEqual(state.approval_count, 1)
        self.assertTrue(state.satisfied)

    # -- the requirement itself -------------------------------------------------
    def test_requirement_validation_refuses_unlawful_requirements(self):
        for build in (lambda: ReviewRequirement(required_approvals=-1),
                      lambda: ReviewRequirement(required_approvals="1"),
                      lambda: ReviewRequirement(required_approvals=True),
                      lambda: ReviewRequirement(
                          require_code_owner_review="yes")):
            with self.assertRaises(PullRequestError) as caught:
                build()
            self.assertEqual(caught.exception.reason, "requirement_invalid")
        with self.assertRaises(PullRequestError) as caught:
            self._state(requirement="two approvals, please")
        self.assertEqual(caught.exception.reason, "requirement_invalid")

    def test_requirement_words(self):
        self.assertIn("No review requirement",
                      ReviewRequirement().words)
        words = ReviewRequirement(
            required_approvals=2, require_code_owner_review=True).words
        self.assertIn("2 required approvals from reviewers", words)
        self.assertIn("code-owner review required", words)

    # -- words, blockers, render --------------------------------------------------
    def test_words_and_the_renderer_say_the_position(self):
        self._approve(self.reader)
        self._request_changes(self.third)
        state = self._state(ReviewRequirement(required_approvals=1))
        self.assertIn("2 of 2 reviews still count", state.words)
        self.assertIn("1 approved", state.words)
        self.assertIn("1 requested changes", state.words)
        self.assertIn("not met", state.words)
        html = render_required_review_state(state)
        self.assertIn("required-review-state", html)
        self.assertIn("requested changes", html)
        self.assertIn("<li>", html)

    def test_the_renderer_lists_blockers_only_when_they_exist(self):
        short = self._state(ReviewRequirement(required_approvals=1))
        html = render_required_review_state(short)
        self.assertIn("<li>", html)
        self.assertIn("Approvals are short", html)
        self._approve(self.reader)
        met = self._state(ReviewRequirement(required_approvals=1))
        self.assertNotIn("<li>", render_required_review_state(met))

    # -- hygiene: a pure read ------------------------------------------------------
    def test_the_read_mutates_nothing_and_claims_nothing(self):
        self._approve(self.reader)
        audit_before = self.conn.execute(
            "SELECT COUNT(*) AS c FROM audit_log").fetchone()["c"]
        reviews_before = self.conn.execute(
            "SELECT COUNT(*) AS c FROM pull_request_reviews"
        ).fetchone()["c"]
        self._state(ReviewRequirement(
            required_approvals=1, require_code_owner_review=True))
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) AS c FROM audit_log").fetchone()["c"],
            audit_before)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) AS c FROM pull_request_reviews"
            ).fetchone()["c"], reviews_before)
        self.assertEqual(schema_version(self.conn), 114)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)


if __name__ == "__main__":
    unittest.main()
