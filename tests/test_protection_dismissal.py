"""S-172 acceptance battery: dismiss stale reviews.

Acceptance (roadmap S-172): dismiss stale reviews —
new pushes dismiss approvals per S-149, wired into
the rules engine (the S-169 `dismiss_stale_reviews`
field, judged for a pull request's base branch).

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
from samverk.protection_dismissal import (
    DismissalProtectionStore, decide_dismissal,
    render_dismissal_decision)
from samverk.protection_rules import (
    ProtectionRule, ProtectionRuleStore, ProtectionSettings,
    evaluate_rules)
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


BASE_FILES = {"a.txt": "alpha\nbeta\n"}
HEAD_FILES = {"a.txt": "alpha\nBETA\n"}
PUSHED_FILES = {"a.txt": "alpha\nBETA\ngamma\n"}


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


class ProtectionDismissalTests(unittest.TestCase):
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
        self.gate = DismissalProtectionStore(
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
    def _dismiss_rule(self, pattern="main", repo="pub", **kw):
        return self.rules.create_rule(
            self.owner, "volmarr", repo, pattern,
            dismiss_stale_reviews=True, **kw)

    def _decision(self, viewer=None):
        return self.gate.dismissal_for(
            viewer if viewer is not None else self.owner,
            "volmarr", "pub", self.pr.number)

    def _approve(self, who):
        return self.reviews.submit_review(
            who, "volmarr", "pub", self.pr.number,
            verdict="approve", summary="Looks right to me.")

    def _push(self):
        pushed = make_commit(self.path, self.head_oid, PUSHED_FILES,
                             "more feature work")
        git(self.path, "update-ref", "refs/heads/feature", pushed)
        return pushed

    # -- the stored shape --------------------------------------------------
    def test_dismiss_toggle_round_trips_through_the_rule(self):
        rule = self._dismiss_rule()
        self.assertTrue(rule.settings.dismiss_stale_reviews)
        self.assertIn("stale reviews are dismissed on new pushes",
                      "; ".join(rule.settings.requirement_words()))
        fetched = self.rules.get_rule(
            self.owner, "volmarr", "pub", rule.id)
        self.assertTrue(fetched.settings.dismiss_stale_reviews)

    def test_effective_fold_any_matching_rule_dismisses(self):
        self.rules.create_rule(self.owner, "volmarr", "pub", "main")
        self._dismiss_rule(pattern="m*")
        evaluation = self.rules.evaluate_branch(
            self.owner, "volmarr", "pub", "main")
        self.assertTrue(evaluation.effective.settings.dismiss_stale_reviews)

    # -- no rule, no dismissal ----------------------------------------------
    def test_no_rule_no_dismissal(self):
        self._approve(self.reader)
        decision = self._decision()
        self.assertFalse(decision.dismiss_stale_reviews)
        self.assertEqual(decision.dismissed_count, 0)
        self.assertEqual(decision.approval_count, 1)
        self.assertIn("does not dismiss stale reviews", decision.words)

    def test_push_without_rule_leaves_approval_counting(self):
        self._approve(self.reader)
        self._push()
        decision = self._decision()
        self.assertFalse(decision.dismiss_stale_reviews)
        self.assertEqual(decision.dismissed_count, 0)
        self.assertEqual(decision.approval_count, 1)

    def test_rule_for_another_branch_does_not_dismiss(self):
        self._dismiss_rule(pattern="release/*")
        self._approve(self.reader)
        self._push()
        decision = self._decision()
        self.assertFalse(decision.dismiss_stale_reviews)
        self.assertEqual(decision.approval_count, 1)

    def test_disabled_rule_does_not_dismiss(self):
        self._dismiss_rule(enabled=False)
        self._approve(self.reader)
        self._push()
        decision = self._decision()
        self.assertFalse(decision.dismiss_stale_reviews)
        self.assertEqual(decision.approval_count, 1)

    # -- the dismissal ---------------------------------------------------------
    def test_approval_at_current_head_counts(self):
        self._dismiss_rule()
        self._approve(self.reader)
        decision = self._decision()
        self.assertTrue(decision.dismiss_stale_reviews)
        self.assertEqual(decision.dismissed_count, 0)
        self.assertEqual(decision.approval_count, 1)
        self.assertIn("No approval stands dismissed.", decision.words)

    def test_new_push_dismisses_approval_under_default_policy(self):
        # The repository policy is the default `never`:
        # S-149 alone would keep this approval counting.
        self._dismiss_rule()
        self._approve(self.reader)
        self.assertEqual(self._decision().approval_count, 1)
        self._push()
        decision = self._decision()
        self.assertTrue(decision.dismiss_stale_reviews)
        self.assertEqual(decision.stale_count, 0)
        self.assertEqual(decision.dismissed_count, 1)
        self.assertEqual(decision.approval_count, 0)
        self.assertEqual(decision.dismissed_approver_ids, (self.reader.id,))
        entry = decision.dismissed_entries[0]
        self.assertFalse(entry.counts)
        self.assertIn("Dismissed", entry.state_words)
        self.assertIn("protection rule dismisses", entry.reason_words)
        self.assertIn("1 approval was dismissed", decision.words)

    def test_dismissal_agrees_with_s149_policy_when_both_speak(self):
        self._dismiss_rule()
        self.freshness.set_policy(self.owner, "volmarr", "pub", "approvals")
        self._approve(self.reader)
        self._push()
        decision = self._decision()
        self.assertEqual(decision.stale_count, 1)
        self.assertEqual(decision.dismissed_count, 1)
        self.assertEqual(decision.approval_count, 0)

    def test_fresh_reapproval_after_push_counts_again(self):
        self._dismiss_rule()
        self._approve(self.reader)
        self._push()
        self.assertEqual(self._decision().approval_count, 0)
        self._approve(self.reader)
        decision = self._decision()
        self.assertEqual(decision.dismissed_count, 1)
        self.assertEqual(decision.approval_count, 1)
        self.assertEqual(decision.dismissed_approver_ids, ())

    def test_change_request_is_not_dismissed_by_the_rule(self):
        self._dismiss_rule()
        self.reviews.submit_review(
            self.third, "volmarr", "pub", self.pr.number,
            verdict="request_changes", summary="Please rework this.")
        self._push()
        decision = self._decision()
        self.assertEqual(decision.dismissed_count, 0)
        self.assertEqual(
            decision.latest_counting_by_reviewer.get(self.third.id),
            "changes_requested")

    def test_comment_is_not_dismissed_by_the_rule(self):
        self._dismiss_rule()
        self.reviews.submit_review(
            self.third, "volmarr", "pub", self.pr.number,
            verdict="comment", summary="A thought, no verdict.")
        self._push()
        decision = self._decision()
        self.assertEqual(decision.dismissed_count, 0)
        self.assertEqual(decision.counting_count, 1)

    def test_turning_the_rule_off_counts_the_approval_again(self):
        rule = self._dismiss_rule()
        self._approve(self.reader)
        self._push()
        self.assertEqual(self._decision().approval_count, 0)
        self.rules.update_rule(
            self.owner, "volmarr", "pub", rule.id,
            dismiss_stale_reviews=False)
        decision = self._decision()
        self.assertEqual(decision.dismissed_count, 0)
        self.assertEqual(decision.approval_count, 1)

    # -- the pure seam ---------------------------------------------------------
    def test_pure_decision_dismisses_and_never_counts_the_author(self):
        def entry(rid, reviewer, verdict, head, stale=False):
            return ReviewFreshness(
                review=Review(
                    id=rid, pull_request_id=1, number=1,
                    reviewer_id=reviewer, verdict=verdict,
                    summary="", head_oid=head, submitted_at=rid),
                is_stale=stale)
        old, new = "a" * 40, "b" * 40
        report = FreshnessReport(
            full_name="volmarr/pub", number=1,
            policy=ReviewFreshnessPolicy(
                full_name="volmarr/pub", mode="never"),
            current_head_oid=new,
            entries=(entry(1, self.reader.id, "approved", old),
                     entry(2, self.owner.id, "approved", new)))
        rule = ProtectionRule(
            id=1, repo_id=1, full_name="volmarr/pub", pattern="main",
            settings=ProtectionSettings(dismiss_stale_reviews=True),
            created_by=None, created_at=0, updated_at=0)
        evaluation = evaluate_rules([rule], "main",
                                    full_name="volmarr/pub")
        decision = decide_dismissal(
            evaluation, report, author_id=self.owner.id)
        self.assertEqual(decision.dismissed_count, 1)
        self.assertEqual(decision.dismissed_approver_ids, (self.reader.id,))
        # The author's own fresh approval never counts.
        self.assertEqual(decision.approval_count, 0)

    # -- guards, renderer, pins -------------------------------------------------
    def test_private_stranger_gets_uniform_not_found(self):
        with self.assertRaises(Exception) as cm:
            self.gate.dismissal_for(self.reader, "volmarr", "priv", 1)
        self.assertEqual(cm.exception.reason, "pull_request_not_found")

    def test_renderer_says_the_words_escaped(self):
        self._dismiss_rule()
        self._approve(self.reader)
        self._push()
        html = render_dismissal_decision(self._decision())
        self.assertIn("protection-dismissal", html)
        self.assertIn("Dismissed", html)
        self.assertIn("approval was dismissed", html)

    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 105)
        self.assertEqual(db.MIGRATIONS[-1][0], 105)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)


if __name__ == "__main__":
    unittest.main()
