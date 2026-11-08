"""S-174 acceptance battery: required status checks.

Acceptance (roadmap S-174): required status checks —
named checks must be green; branch must be
up-to-date toggle honoured.

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
from samverk.protection_rules import (
    ProtectionRuleStore, evaluate_rules)
from samverk.protection_status_checks import (
    STATUS_CHECKS_REQUIRED, StatusCheckProtectionStore,
    StatusChecksRequiredError, decide_status_checks,
    render_status_check_decision)
from samverk.pull_request_checks import (
    PullRequestCheck, PullRequestChecksStore)
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


def make_commit(repo, parents, files, message):
    lines = []
    for name in sorted(files):
        content = files[name]
        blob = git(repo, "hash-object", "-w", "--stdin",
                   input_bytes=content.encode())
        lines.append(f"100644 blob {blob}\t{name}\n")
    tree = git(repo, "mktree", input_bytes="".join(lines).encode())
    args = ["commit-tree", tree]
    for parent in parents:
        args += ["-p", parent]
    return git(repo, *args, input_bytes=(message + "\n").encode())


BASE_FILES = {"a.txt": "alpha\nbeta\n"}
HEAD_FILES = {"a.txt": "alpha\nBETA\n"}
MAIN_MOVED_FILES = {"a.txt": "alpha\nbeta\n", "b.txt": "main moved\n"}


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


class ProtectionStatusChecksTests(unittest.TestCase):
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
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.issues = IssueStore(self.conn, self.repos, self.accounts,
                                 audit=self.audit, time_fn=self.clock)
        self.rules = ProtectionRuleStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.checks = PullRequestChecksStore(
            self.conn, self.repos, self.accounts, self.issues,
            time_fn=self.clock)
        self.prs = PullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.gate = StatusCheckProtectionStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        self.path = self.repos.path_for("volmarr", "pub")
        self.base_oid = make_commit(self.path, [], BASE_FILES, "base")
        git(self.path, "update-ref", "refs/heads/main", self.base_oid)
        self.head_oid = make_commit(
            self.path, [self.base_oid], HEAD_FILES, "feature work")
        git(self.path, "update-ref", "refs/heads/feature", self.head_oid)
        self.pr = self.prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch="feature")

    # -- helpers ---------------------------------------------------------

    def _require(self, repo="pub", pattern="main", **fields):
        return self.rules.create_rule(
            self.owner, "volmarr", repo, pattern, **fields)

    def _check(self, number=None, repo="pub", viewer=None):
        return self.gate.check_pull_request(
            viewer if viewer is not None else self.owner,
            "volmarr", repo,
            self.pr.number if number is None else number)

    def _report(self, context, state, head_oid=None, repo="pub"):
        return self.checks.record_result(
            "volmarr", repo,
            self.pr.head_oid if head_oid is None else head_oid,
            context, state)

    def _move_main(self):
        moved = make_commit(
            self.path, [self.base_oid], MAIN_MOVED_FILES, "main moved")
        git(self.path, "update-ref", "refs/heads/main", moved)
        return moved

    # -- the checks half ---------------------------------------------------

    def test_no_rule_no_requirement(self):
        decision = self._check()
        self.assertEqual(decision.required_status_checks, ())
        self.assertTrue(decision.checks_satisfied)
        self.assertTrue(decision.satisfied)
        self.assertEqual(decision.blockers, ())

    def test_required_check_unreported_blocks(self):
        self._require(required_status_checks=("ci",))
        decision = self._check()
        self.assertEqual(decision.required_status_checks, ("ci",))
        self.assertEqual(decision.missing_checks, ("ci",))
        self.assertFalse(decision.satisfied)
        self.assertIn("'ci'", decision.blockers[0])
        self.assertIn("has not been reported", decision.blockers[0])

    def test_enforce_raises_with_reason(self):
        self._require(required_status_checks=("ci",))
        with self.assertRaises(StatusChecksRequiredError) as caught:
            self.gate.enforce_pull_request(
                self.owner, "volmarr", "pub", self.pr.number)
        self.assertEqual(caught.exception.reason, STATUS_CHECKS_REQUIRED)
        self.assertIn("ci", str(caught.exception))

    def test_pending_check_blocks(self):
        self._require(required_status_checks=("ci",))
        self._report("ci", "pending")
        decision = self._check()
        self.assertEqual(decision.pending_checks, ("ci",))
        self.assertFalse(decision.satisfied)

    def test_failed_check_blocks(self):
        self._require(required_status_checks=("ci",))
        self._report("ci", "failed")
        decision = self._check()
        self.assertEqual(decision.failed_checks, ("ci",))
        self.assertFalse(decision.satisfied)

    def test_passed_check_satisfies(self):
        self._require(required_status_checks=("ci",))
        self._report("ci", "passed")
        decision = self._check()
        self.assertEqual(decision.passed_checks, ("ci",))
        self.assertTrue(decision.satisfied)
        enforced = self.gate.enforce_pull_request(
            self.owner, "volmarr", "pub", self.pr.number)
        self.assertTrue(enforced.satisfied)

    def test_rereport_moves_the_state(self):
        self._require(required_status_checks=("ci",))
        self._report("ci", "pending")
        self.assertFalse(self._check().satisfied)
        self._report("ci", "passed")
        decision = self._check()
        self.assertTrue(decision.satisfied)
        self.assertEqual(len(decision.checks), 1)

    def test_result_on_another_commit_does_not_count(self):
        self._require(required_status_checks=("ci",))
        self._report("ci", "passed", head_oid=self.base_oid)
        decision = self._check()
        self.assertEqual(decision.missing_checks, ("ci",))
        self.assertFalse(decision.satisfied)

    def test_unrequired_check_does_not_bind(self):
        self._require(required_status_checks=("ci",))
        self._report("ci", "passed")
        self._report("extra", "failed")
        decision = self._check()
        self.assertTrue(decision.satisfied)

    def test_one_of_two_missing_blocks_on_the_missing_one(self):
        self._require(required_status_checks=("ci", "lint"))
        self._report("ci", "passed")
        decision = self._check()
        self.assertEqual(decision.missing_checks, ("lint",))
        self.assertFalse(decision.satisfied)
        self.assertTrue(
            all("lint" in b for b in decision.blockers))

    def test_matching_rules_union_their_checks(self):
        self._require(pattern="main", required_status_checks=("ci",))
        self._require(pattern="m*", required_status_checks=("lint",))
        decision = self._check()
        self.assertEqual(
            set(decision.required_status_checks), {"ci", "lint"})
        self._report("ci", "passed")
        self._report("lint", "passed")
        self.assertTrue(self._check().satisfied)

    def test_other_branch_rule_does_not_bind(self):
        self._require(pattern="release", required_status_checks=("ci",))
        decision = self._check()
        self.assertEqual(decision.required_status_checks, ())
        self.assertTrue(decision.satisfied)

    def test_disabled_rule_does_not_bind(self):
        self._require(required_status_checks=("ci",), enabled=False)
        decision = self._check()
        self.assertEqual(decision.required_status_checks, ())
        self.assertTrue(decision.satisfied)

    # -- the up-to-date half -------------------------------------------------

    def test_up_to_date_when_base_contained(self):
        self._require(require_branch_up_to_date=True)
        decision = self._check()
        self.assertEqual(decision.behind, 0)
        self.assertTrue(decision.up_to_date)
        self.assertTrue(decision.satisfied)

    def test_behind_base_blocks_when_toggle_on(self):
        self._require(require_branch_up_to_date=True)
        self._move_main()
        decision = self._check()
        self.assertEqual(decision.behind, 1)
        self.assertFalse(decision.up_to_date)
        self.assertFalse(decision.satisfied)
        self.assertIn("1 commit behind", decision.blockers[0])

    def test_behind_base_does_not_bind_when_toggle_off(self):
        self._require(required_status_checks=())
        self._move_main()
        decision = self._check()
        self.assertEqual(decision.behind, 1)
        self.assertFalse(decision.up_to_date)
        self.assertTrue(decision.satisfied)

    def test_catching_up_restores_the_gate(self):
        self._require(require_branch_up_to_date=True)
        moved = self._move_main()
        self.assertFalse(self._check().satisfied)
        caught_up = make_commit(
            self.path, [self.head_oid, moved], HEAD_FILES, "catch up")
        git(self.path, "update-ref", "refs/heads/feature", caught_up)
        decision = self._check()
        self.assertEqual(decision.behind, 0)
        self.assertTrue(decision.satisfied)

    def test_both_halves_together(self):
        self._require(required_status_checks=("ci",),
                      require_branch_up_to_date=True)
        self._report("ci", "passed")
        self.assertTrue(self._check().satisfied)
        self._move_main()
        decision = self._check()
        self.assertTrue(decision.checks_satisfied)
        self.assertFalse(decision.satisfied)

    # -- seams, words, pins ----------------------------------------------------

    def test_private_repo_stranger_gets_uniform_not_found(self):
        path = self.repos.path_for("volmarr", "priv")
        base = make_commit(path, [], BASE_FILES, "base")
        git(path, "update-ref", "refs/heads/main", base)
        head = make_commit(path, [base], HEAD_FILES, "feature work")
        git(path, "update-ref", "refs/heads/feature", head)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "priv", base_branch="main",
            head_branch="feature")
        self._require(repo="priv", required_status_checks=("ci",))
        with self.assertRaises(Exception) as caught:
            self.gate.check_pull_request(
                self.reader, "volmarr", "priv", pr.number)
        self.assertEqual(
            getattr(caught.exception, "reason", ""),
            "pull_request_not_found")

    def test_renderer_prints_the_decisions_words(self):
        self._require(required_status_checks=("ci",))
        decision = self._check()
        html = render_status_check_decision(decision)
        self.assertIn("protection-status-checks", html)
        self.assertIn("not satisfied", html)
        self.assertIn("has not been reported", html)

    def test_pure_seam_judges_from_records_alone(self):
        evaluation = evaluate_rules([], "main", full_name="volmarr/pub")
        row = PullRequestCheck(
            id=1, repo_id=1, number=7, head_oid="abc", context="ci",
            state="passed", target_url="", description="",
            created_at=1, updated_at=1)
        decision = decide_status_checks(
            evaluation, [row], number=7, head_branch="feature",
            head_oid="abc", behind=3)
        self.assertEqual(decision.required_status_checks, ())
        self.assertTrue(decision.satisfied)
        self.assertEqual(decision.behind, 3)
        empty = decide_status_checks(
            evaluation, [], number=7, behind=None)
        self.assertTrue(empty.satisfied)
        self.assertFalse(empty.up_to_date)

    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 85)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 123)


if __name__ == "__main__":
    unittest.main()
