"""S-171 acceptance battery: required approving reviews.

Acceptance (roadmap S-171): required approving reviews
— count configurable; self-approval never counts;
last-pusher approval rule available.

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
from samverk.hooks import RefUpdate
from samverk.issues import IssueStore
from samverk.protection_approvals import (
    APPROVALS_REQUIRED, ApprovalProtectionStore,
    ApprovalsRequiredError, decide_approvals,
    render_approval_decision)
from samverk.protection_rules import (
    ProtectionRule, ProtectionRuleStore, ProtectionSettings,
    evaluate_rules)
from samverk.pull_request_required_review import (
    ReviewRequirement, resolve_review_state)
from samverk.pull_request_review_freshness import (
    FreshnessReport, PullRequestReviewFreshnessStore,
    ReviewFreshness, ReviewFreshnessPolicy)
from samverk.pull_request_reviews import PullRequestReviewStore, Review
from samverk.pull_requests import PullRequestStore
from samverk.push_events import PushEventStore
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
                   input_bytes=content.encode())
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


class ProtectionApprovalsTests(unittest.TestCase):
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
        self.fourth = self.accounts.register("mimir", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.issues = IssueStore(self.conn, self.repos, self.accounts,
                                 audit=self.audit, time_fn=self.clock)
        self.rules = ProtectionRuleStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.prs = PullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.reviews = PullRequestReviewStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.freshness = PullRequestReviewFreshnessStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.pushes = PushEventStore(
            self.conn, self.repos, time_fn=self.clock)
        self.gate = ApprovalProtectionStore(
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
    def _require(self, count=1, repo="pub", **fields):
        fields.setdefault("required_approvals", count)
        return self.rules.create_rule(
            self.owner, "volmarr", repo, "main", **fields)

    def _check(self, number=None, repo="pub", viewer=None, **kw):
        return self.gate.check_pull_request(
            viewer if viewer is not None else self.owner,
            "volmarr", repo,
            self.pr.number if number is None else number, **kw)

    def _approve(self, who, number=None):
        return self.reviews.submit_review(
            who, "volmarr", "pub",
            self.pr.number if number is None else number,
            verdict="approve", summary="Looks right to me.")

    def _record_push(self, who, old, new, branch="feature"):
        return self.pushes.record_push(
            "volmarr", "pub", actor_kind="user", actor_id=who.id,
            transport="local",
            updates=(RefUpdate(ref=f"refs/heads/{branch}",
                               old_oid=old, new_oid=new),))

    # -- the stored shape (migration 66) ---------------------------------
    def test_last_pusher_toggle_round_trips_through_the_rule(self):
        rule = self._require(2, require_last_pusher_approval=True)
        self.assertEqual(rule.settings.required_approvals, 2)
        self.assertTrue(rule.settings.require_last_pusher_approval)
        self.assertIn("someone other than the most recent pusher",
                      "; ".join(rule.settings.requirement_words()))
        fetched = self.rules.get_rule(
            self.owner, "volmarr", "pub", rule.id)
        self.assertTrue(fetched.settings.require_last_pusher_approval)
        updated = self.rules.update_rule(
            self.owner, "volmarr", "pub", rule.id,
            require_last_pusher_approval=False)
        self.assertFalse(updated.settings.require_last_pusher_approval)
        self.assertEqual(updated.settings.required_approvals, 2)

    def test_effective_fold_max_count_and_any_toggle(self):
        self._require(1)
        self.rules.create_rule(
            self.owner, "volmarr", "pub", "m*",
            required_approvals=3, require_last_pusher_approval=True)
        evaluation = self.rules.evaluate_branch(
            self.owner, "volmarr", "pub", "main")
        self.assertEqual(evaluation.effective.settings.required_approvals, 3)
        self.assertTrue(
            evaluation.effective.settings.require_last_pusher_approval)

    # -- the count ---------------------------------------------------------
    def test_no_rule_no_approvals_required(self):
        decision = self._check()
        self.assertTrue(decision.satisfied)
        self.assertEqual(decision.required_approvals, 0)
        self.assertEqual(decision.approval_count, 0)
        self.assertEqual(decision.reason, "")
        self.assertIn("no approvals required", decision.words)
        out = self.gate.enforce_pull_request(
            self.owner, "volmarr", "pub", self.pr.number)
        self.assertTrue(out.satisfied)

    def test_count_unmet_refused_with_reason(self):
        self._require(2)
        decision = self._check()
        self.assertFalse(decision.satisfied)
        self.assertEqual(decision.required_approvals, 2)
        self.assertIn("0 of the 2 required approvals count",
                      decision.blockers[0])
        self.assertIn(f"#{self.pr.number}", decision.reason)
        self.assertIn("'main'", decision.reason)
        self.assertIn("volmarr/pub", decision.reason)
        with self.assertRaises(ApprovalsRequiredError) as cm:
            self.gate.enforce_pull_request(
                self.owner, "volmarr", "pub", self.pr.number)
        self.assertEqual(cm.exception.reason, APPROVALS_REQUIRED)
        self.assertEqual(str(cm.exception), decision.reason)

    def test_count_met_by_distinct_reviewers(self):
        self._require(2)
        self._approve(self.reader)
        self.assertFalse(self._check().satisfied)
        self._approve(self.third)
        decision = self._check()
        self.assertTrue(decision.satisfied)
        self.assertEqual(decision.approval_count, 2)
        self.assertIn("The approval requirement is met.", decision.words)

    def test_comment_does_not_count(self):
        self._require(1)
        self.reviews.submit_review(
            self.reader, "volmarr", "pub", self.pr.number,
            verdict="comment", summary="A thought, no verdict.")
        decision = self._check()
        self.assertFalse(decision.satisfied)
        self.assertEqual(decision.approval_count, 0)

    def test_change_request_blocks_even_when_count_met(self):
        self._require(1)
        self._approve(self.reader)
        self.reviews.submit_review(
            self.third, "volmarr", "pub", self.pr.number,
            verdict="request_changes", summary="Please rework this.")
        decision = self._check()
        self.assertFalse(decision.satisfied)
        self.assertEqual(decision.approval_count, 1)
        self.assertTrue(any("requested changes" in b
                            for b in decision.blockers))

    def test_stale_approval_does_not_count(self):
        self._require(1)
        self.freshness.set_policy(self.owner, "volmarr", "pub", "approvals")
        self._approve(self.reader)
        self.assertTrue(self._check().satisfied)
        pushed = make_commit(self.path, self.head_oid, PUSHED_FILES,
                             "more feature work")
        git(self.path, "update-ref", "refs/heads/feature", pushed)
        decision = self._check()
        self.assertFalse(decision.satisfied)
        self.assertEqual(decision.approval_count, 0)

    def test_count_is_configurable_per_branch(self):
        self._require(3)
        self._approve(self.reader)
        self._approve(self.third)
        self.assertFalse(self._check().satisfied)
        self.rules.update_rule(
            self.owner, "volmarr", "pub",
            self.rules.get_rule_by_pattern(
                self.owner, "volmarr", "pub", "main").id,
            required_approvals=2)
        self.assertTrue(self._check().satisfied)

    # -- self-approval never counts (the pure seam) -----------------------
    def test_self_approval_never_counts_pure(self):
        def review(rid, reviewer, verdict):
            return ReviewFreshness(
                review=Review(
                    id=rid, pull_request_id=1, number=1,
                    reviewer_id=reviewer, verdict=verdict,
                    summary="", head_oid="a" * 40, submitted_at=rid),
                is_stale=False)
        report = FreshnessReport(
            full_name="volmarr/pub", number=1,
            policy=ReviewFreshnessPolicy(
                full_name="volmarr/pub", mode="never"),
            current_head_oid="a" * 40,
            entries=(review(1, self.owner.id, "approved"),
                     review(2, self.reader.id, "approved")))
        state = resolve_review_state(
            full_name="volmarr/pub", number=1,
            author_id=self.owner.id, freshness=report,
            requirement=ReviewRequirement(required_approvals=2))
        self.assertEqual(state.approval_count, 1)
        rule = ProtectionRule(
            id=1, repo_id=1, full_name="volmarr/pub", pattern="main",
            settings=ProtectionSettings(required_approvals=2),
            created_by=None, created_at=0, updated_at=0)
        evaluation = evaluate_rules([rule], "main",
                                    full_name="volmarr/pub")
        decision = decide_approvals(evaluation, state)
        self.assertFalse(decision.satisfied)
        self.assertEqual(decision.approval_count, 1)

    def test_pure_decision_rejects_bool_pusher(self):
        self._require(1)
        decision = self._check()
        with self.assertRaises(ApprovalsRequiredError) as cm:
            decide_approvals(decision.evaluation, decision.review_state,
                             last_pusher_id=True)
        self.assertEqual(cm.exception.reason, "approval_check_invalid")

    # -- the last-pusher rule ----------------------------------------------
    def test_last_pusher_approval_excluded_when_stated(self):
        self._require(1, require_last_pusher_approval=True)
        self._approve(self.reader)
        decision = self._check(last_pusher_id=self.reader.id)
        self.assertFalse(decision.satisfied)
        self.assertTrue(decision.last_pusher_excluded)
        self.assertEqual(decision.approval_count, 0)
        self.assertTrue(any("last-pusher rule" in b
                            for b in decision.blockers))
        self._approve(self.third)
        decision = self._check(last_pusher_id=self.reader.id)
        self.assertTrue(decision.satisfied)
        self.assertEqual(decision.approval_count, 1)
        self.assertEqual(decision.effective_approver_ids, (self.third.id,))

    def test_last_pusher_approval_counts_when_toggle_off(self):
        self._require(1)
        self._approve(self.reader)
        decision = self._check(last_pusher_id=self.reader.id)
        self.assertTrue(decision.satisfied)
        self.assertFalse(decision.last_pusher_excluded)

    def test_last_pusher_read_from_recorded_push(self):
        self._require(1, require_last_pusher_approval=True)
        self._record_push(self.reader, self.base_oid, self.head_oid)
        self._approve(self.reader)
        decision = self._check()
        self.assertEqual(decision.last_pusher_id, self.reader.id)
        self.assertFalse(decision.satisfied)

    def test_recorded_pusher_who_did_not_approve_excludes_nobody(self):
        self._require(1, require_last_pusher_approval=True)
        self._record_push(self.reader, self.base_oid, self.head_oid)
        self._approve(self.third)
        decision = self._check()
        self.assertTrue(decision.satisfied)
        self.assertIn("most recent pusher has not approved",
                      decision.words)

    def test_no_recorded_push_excludes_nobody_and_says_so(self):
        self._require(1, require_last_pusher_approval=True)
        self._approve(self.reader)
        decision = self._check()
        self.assertIsNone(decision.last_pusher_id)
        self.assertTrue(decision.satisfied)
        self.assertIn("no push by a person stands recorded",
                      decision.words)

    def test_approval_counts_again_after_someone_else_pushes(self):
        self._require(1, require_last_pusher_approval=True)
        self._approve(self.reader)
        self._record_push(self.reader, self.base_oid, self.head_oid)
        self.assertFalse(self._check().satisfied)
        pushed = make_commit(self.path, self.head_oid, PUSHED_FILES,
                             "more feature work")
        git(self.path, "update-ref", "refs/heads/feature", pushed)
        self._record_push(self.third, self.head_oid, pushed)
        decision = self._check()
        self.assertEqual(decision.last_pusher_id, self.third.id)
        self.assertTrue(decision.satisfied)
        self.assertEqual(decision.approval_count, 1)

    def test_last_pushers_change_request_still_blocks(self):
        self._require(1, require_last_pusher_approval=True)
        self._approve(self.third)
        self.reviews.submit_review(
            self.reader, "volmarr", "pub", self.pr.number,
            verdict="request_changes", summary="Not yet.")
        decision = self._check(last_pusher_id=self.reader.id)
        self.assertFalse(decision.satisfied)
        self.assertFalse(decision.last_pusher_excluded)
        self.assertTrue(any("requested changes" in b
                            for b in decision.blockers))

    # -- guards, renderer, pins ----------------------------------------------
    def test_private_stranger_gets_uniform_not_found(self):
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv2", visibility="private")
        with self.assertRaises(Exception) as cm:
            self.gate.check_pull_request(
                self.reader, "volmarr", "priv", 1)
        self.assertEqual(cm.exception.reason, "pull_request_not_found")

    def test_renderer_says_the_words_escaped(self):
        self._require(1)
        decision = self._check()
        html = render_approval_decision(decision)
        self.assertIn("protection-approvals", html)
        self.assertIn("The approval requirement is not met", html)
        self.assertIn("Approvals are short", html)

    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 118)
        self.assertEqual(db.MIGRATIONS[-1][0], 118)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 134)


if __name__ == "__main__":
    unittest.main()
