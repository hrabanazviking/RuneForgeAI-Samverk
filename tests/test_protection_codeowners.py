"""S-173 acceptance battery: require code-owner review.

Acceptance (roadmap S-173): require code-owner
review — CODEOWNERS (S-151) approval is a gate,
distinct from any-approval.

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
from samverk.issues import IssueStore
from samverk.protection_approvals import ApprovalProtectionStore
from samverk.protection_codeowners import (
    CODE_OWNER_REVIEW_REQUIRED, CodeOwnerProtectionStore,
    CodeOwnerReviewRequiredError, decide_codeowners,
    render_codeowner_decision)
from samverk.protection_rules import (
    ProtectionRule, ProtectionRuleStore, ProtectionSettings,
    evaluate_rules)
from samverk.pull_request_codeowners import PullRequestCodeownersStore
from samverk.pull_request_required_review import (
    ReviewRequirement, resolve_review_state)
from samverk.pull_request_review_assignment import (
    ReviewAssignment, ReviewAssignmentStore)
from samverk.pull_request_review_freshness import (
    FreshnessReport, PullRequestReviewFreshnessStore,
    ReviewFreshness, ReviewFreshnessPolicy)
from samverk.pull_request_reviews import PullRequestReviewStore, Review
from samverk.pull_requests import PullRequestStore
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


BASE_FILES = {"CODEOWNERS": "* @yrsa\n", "a.txt": "alpha\nbeta\n"}
HEAD_FILES = {"CODEOWNERS": "* @yrsa\n", "a.txt": "alpha\nBETA\n"}
PUSHED_FILES = {"CODEOWNERS": "* @yrsa\n", "a.txt": "alpha\nBETA\ngamma\n"}
PLAIN_BASE = {"a.txt": "alpha\nbeta\n"}
PLAIN_HEAD = {"a.txt": "alpha\nBETA\n"}
DOCS_BASE = {"CODEOWNERS": "docs/ @yrsa\n", "a.txt": "alpha\nbeta\n"}
DOCS_HEAD = {"CODEOWNERS": "docs/ @yrsa\n", "a.txt": "alpha\nBETA\n"}


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


class ProtectionCodeownersTests(unittest.TestCase):
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
        self.codeowners = PullRequestCodeownersStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.wired_prs = PullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock,
            codeowners_sync=self.codeowners.sync_requests)
        self.reviews = PullRequestReviewStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.freshness = PullRequestReviewFreshnessStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.assignments = ReviewAssignmentStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.gate = CodeOwnerProtectionStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.approvals_gate = ApprovalProtectionStore(
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
        self.pr = self.wired_prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch="feature")

    # -- helpers ---------------------------------------------------------
    def _require(self, repo="pub", **fields):
        fields.setdefault("require_code_owner_review", True)
        return self.rules.create_rule(
            self.owner, "volmarr", repo, "main", **fields)

    def _check(self, number=None, repo="pub", viewer=None):
        return self.gate.check_pull_request(
            viewer if viewer is not None else self.owner,
            "volmarr", repo,
            self.pr.number if number is None else number)

    def _approve(self, who, number=None, repo="pub"):
        return self.reviews.submit_review(
            who, "volmarr", repo,
            self.pr.number if number is None else number,
            verdict="approve", summary="Looks right to me.")

    def _plain_pr(self, repo, base_files, head_files):
        self.repos.create_repository(
            self.owner.id, "volmarr", repo, visibility="public")
        path = self.repos.path_for("volmarr", repo)
        base = make_commit(path, None, base_files, "base")
        git(path, "update-ref", "refs/heads/main", base)
        head = make_commit(path, base, head_files, "feature work")
        git(path, "update-ref", "refs/heads/feature", head)
        return self.wired_prs.create_pull_request(
            self.owner, "volmarr", repo, base_branch="main",
            head_branch="feature")

    # -- the stored shape --------------------------------------------------
    def test_toggle_round_trips_through_the_rule(self):
        rule = self._require()
        self.assertTrue(rule.settings.require_code_owner_review)
        self.assertIn("code-owner review is required",
                      "; ".join(rule.settings.requirement_words()))
        fetched = self.rules.get_rule(
            self.owner, "volmarr", "pub", rule.id)
        self.assertTrue(fetched.settings.require_code_owner_review)
        updated = self.rules.update_rule(
            self.owner, "volmarr", "pub", rule.id,
            require_code_owner_review=False)
        self.assertFalse(updated.settings.require_code_owner_review)

    def test_effective_fold_any_toggle(self):
        self.rules.create_rule(
            self.owner, "volmarr", "pub", "main")
        self.rules.create_rule(
            self.owner, "volmarr", "pub", "m*",
            require_code_owner_review=True)
        evaluation = self.rules.evaluate_branch(
            self.owner, "volmarr", "pub", "main")
        self.assertTrue(
            evaluation.effective.settings.require_code_owner_review)

    # -- the gate ------------------------------------------------------------
    def test_no_rule_no_code_owner_review_required(self):
        decision = self._check()
        self.assertTrue(decision.satisfied)
        self.assertFalse(decision.require_code_owner_review)
        self.assertEqual(decision.reason, "")
        self.assertIn("code-owner review is not required", decision.words)
        out = self.gate.enforce_pull_request(
            self.owner, "volmarr", "pub", self.pr.number)
        self.assertTrue(out.satisfied)

    def test_owner_recorded_from_codeowners_on_open(self):
        decision = self._check()
        self.assertEqual(decision.code_owner_user_ids, (self.reader.id,))

    def test_unmet_refused_with_reason(self):
        self._require()
        decision = self._check()
        self.assertFalse(decision.satisfied)
        self.assertTrue(decision.require_code_owner_review)
        self.assertEqual(decision.code_owner_approver_ids, ())
        self.assertIn("no code owner has a counting approval",
                      decision.blockers[0])
        self.assertIn("does not satisfy this gate", decision.blockers[0])
        self.assertIn(f"#{self.pr.number}", decision.reason)
        self.assertIn("'main'", decision.reason)
        self.assertIn("volmarr/pub", decision.reason)
        with self.assertRaises(CodeOwnerReviewRequiredError) as cm:
            self.gate.enforce_pull_request(
                self.owner, "volmarr", "pub", self.pr.number)
        self.assertEqual(cm.exception.reason, CODE_OWNER_REVIEW_REQUIRED)
        self.assertEqual(str(cm.exception), decision.reason)

    def test_non_owner_approval_does_not_satisfy(self):
        self._require()
        self._approve(self.third)
        decision = self._check()
        self.assertFalse(decision.satisfied)
        self.assertEqual(decision.counting_approver_ids, (self.third.id,))
        self.assertEqual(decision.code_owner_approver_ids, ())

    def test_code_owner_approval_satisfies(self):
        self._require()
        self._approve(self.reader)
        decision = self._check()
        self.assertTrue(decision.satisfied)
        self.assertEqual(decision.code_owner_approver_ids, (self.reader.id,))
        self.assertIn("The code-owner requirement is met.", decision.words)
        out = self.gate.enforce_pull_request(
            self.owner, "volmarr", "pub", self.pr.number)
        self.assertTrue(out.satisfied)

    def test_distinct_from_the_any_approval_gate(self):
        self._require(required_approvals=1)
        self._approve(self.third)
        approvals = self.approvals_gate.check_pull_request(
            self.owner, "volmarr", "pub", self.pr.number)
        self.assertTrue(approvals.satisfied)
        self.assertFalse(self._check().satisfied)
        self._approve(self.reader)
        approvals = self.approvals_gate.check_pull_request(
            self.owner, "volmarr", "pub", self.pr.number)
        self.assertTrue(approvals.satisfied)
        self.assertTrue(self._check().satisfied)

    def test_toggle_off_satisfied_without_owner_approval(self):
        self._require()
        self.rules.update_rule(
            self.owner, "volmarr", "pub",
            self.rules.get_rule_by_pattern(
                self.owner, "volmarr", "pub", "main").id,
            require_code_owner_review=False)
        decision = self._check()
        self.assertTrue(decision.satisfied)
        self.assertFalse(decision.require_code_owner_review)

    def test_rule_on_other_branch_does_not_speak(self):
        self.rules.create_rule(
            self.owner, "volmarr", "pub", "release",
            require_code_owner_review=True)
        decision = self._check()
        self.assertTrue(decision.satisfied)
        self.assertFalse(decision.require_code_owner_review)

    def test_disabled_rule_does_not_speak(self):
        self._require(enabled=False)
        decision = self._check()
        self.assertTrue(decision.satisfied)
        self.assertFalse(decision.require_code_owner_review)

    # -- met by construction --------------------------------------------------
    def test_no_codeowners_file_met_by_construction(self):
        pr = self._plain_pr("plain", PLAIN_BASE, PLAIN_HEAD)
        self._require(repo="plain")
        decision = self._check(number=pr.number, repo="plain")
        self.assertTrue(decision.satisfied)
        self.assertEqual(decision.code_owner_user_ids, ())
        self.assertIn("met by construction", decision.words)

    def test_codeowners_matching_no_changed_file_met_by_construction(self):
        pr = self._plain_pr("docsrepo", DOCS_BASE, DOCS_HEAD)
        self._require(repo="docsrepo")
        decision = self._check(number=pr.number, repo="docsrepo")
        self.assertTrue(decision.satisfied)
        self.assertEqual(decision.code_owner_user_ids, ())
        self.assertIn("met by construction", decision.words)

    def test_dismissed_request_leaves_no_owner_of_record(self):
        self._require()
        self.assignments.dismiss_request(
            self.owner, "volmarr", "pub", self.pr.number, "@yrsa")
        decision = self._check()
        self.assertTrue(decision.satisfied)
        self.assertEqual(decision.code_owner_user_ids, ())
        self.assertIn("met by construction", decision.words)

    # -- counting is S-149's word ------------------------------------------------
    def test_stale_code_owner_approval_does_not_count(self):
        self._require()
        self.freshness.set_policy(self.owner, "volmarr", "pub", "approvals")
        self._approve(self.reader)
        self.assertTrue(self._check().satisfied)
        pushed = make_commit(self.path, self.head_oid, PUSHED_FILES,
                             "more feature work")
        git(self.path, "update-ref", "refs/heads/feature", pushed)
        decision = self._check()
        self.assertFalse(decision.satisfied)
        self.assertEqual(decision.code_owner_user_ids, (self.reader.id,))
        self.assertEqual(decision.code_owner_approver_ids, ())

    def test_code_owner_change_request_blocks_until_they_approve(self):
        self._require()
        self.reviews.submit_review(
            self.reader, "volmarr", "pub", self.pr.number,
            verdict="request_changes", summary="Please rework this.")
        decision = self._check()
        self.assertFalse(decision.satisfied)
        self.assertEqual(decision.code_owner_blocking_ids, (self.reader.id,))
        self.assertTrue(any("code owner has requested changes" in b
                            for b in decision.blockers))
        self._approve(self.reader)
        self.assertTrue(self._check().satisfied)

    def test_non_owner_change_request_does_not_block_this_gate(self):
        self._require()
        self._approve(self.reader)
        self.reviews.submit_review(
            self.third, "volmarr", "pub", self.pr.number,
            verdict="request_changes", summary="A concern, not ownership.")
        decision = self._check()
        self.assertTrue(decision.satisfied)
        self.assertEqual(decision.code_owner_blocking_ids, ())

    def test_comment_from_code_owner_does_not_satisfy(self):
        self._require()
        self.reviews.submit_review(
            self.reader, "volmarr", "pub", self.pr.number,
            verdict="comment", summary="A thought, no verdict.")
        decision = self._check()
        self.assertFalse(decision.satisfied)
        self.assertEqual(decision.code_owner_approver_ids, ())

    # -- the pure seam -------------------------------------------------------------
    def test_pure_decision_owner_and_author(self):
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
                     review(2, self.third.id, "approved"),
                     review(3, self.reader.id, "approved")))
        assignment = ReviewAssignment(
            id=1, pull_request_id=1, number=1, owner_ref="@yrsa",
            user_id=self.reader.id, source="codeowners",
            head_oid="a" * 40, created_at=1)
        team_assignment = ReviewAssignment(
            id=2, pull_request_id=1, number=1,
            owner_ref="@volmarr/core", user_id=None,
            source="codeowners", head_oid="a" * 40, created_at=2)
        state = resolve_review_state(
            full_name="volmarr/pub", number=1,
            author_id=self.owner.id, freshness=report,
            assignments=(assignment, team_assignment),
            requirement=ReviewRequirement(require_code_owner_review=True))
        self.assertEqual(state.code_owner_user_ids, (self.reader.id,))
        self.assertEqual(state.code_owner_approver_ids, (self.reader.id,))
        rule = ProtectionRule(
            id=1, repo_id=1, full_name="volmarr/pub", pattern="main",
            settings=ProtectionSettings(require_code_owner_review=True),
            created_by=None, created_at=0, updated_at=0)
        evaluation = evaluate_rules([rule], "main",
                                    full_name="volmarr/pub")
        decision = decide_codeowners(evaluation, state)
        self.assertTrue(decision.satisfied)
        self.assertNotIn(self.owner.id, decision.counting_approver_ids)

    def test_pure_decision_unmet_without_owner_approval(self):
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
            entries=(review(1, self.third.id, "approved"),))
        assignment = ReviewAssignment(
            id=1, pull_request_id=1, number=1, owner_ref="@yrsa",
            user_id=self.reader.id, source="codeowners",
            head_oid="a" * 40, created_at=1)
        state = resolve_review_state(
            full_name="volmarr/pub", number=1,
            author_id=self.owner.id, freshness=report,
            assignments=(assignment,),
            requirement=ReviewRequirement(require_code_owner_review=True))
        rule = ProtectionRule(
            id=1, repo_id=1, full_name="volmarr/pub", pattern="main",
            settings=ProtectionSettings(require_code_owner_review=True),
            created_by=None, created_at=0, updated_at=0)
        evaluation = evaluate_rules([rule], "main",
                                    full_name="volmarr/pub")
        decision = decide_codeowners(evaluation, state)
        self.assertFalse(decision.satisfied)
        self.assertEqual(decision.code_owner_approver_ids, ())

    # -- guards, renderer, pins ------------------------------------------------------
    def test_private_stranger_gets_uniform_not_found(self):
        with self.assertRaises(Exception) as cm:
            self.gate.check_pull_request(
                self.reader, "volmarr", "priv", 1)
        self.assertEqual(cm.exception.reason, "pull_request_not_found")

    def test_renderer_says_the_words_escaped(self):
        self._require()
        decision = self._check()
        html = render_codeowner_decision(decision)
        self.assertIn("protection-codeowners", html)
        self.assertIn("The code-owner requirement is not met", html)
        self.assertIn("no code owner has a counting approval", html)

    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 93)
        self.assertEqual(db.MIGRATIONS[-1][0], 93)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 129)


if __name__ == "__main__":
    unittest.main()
