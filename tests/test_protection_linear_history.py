"""S-176 acceptance battery: require linear history.

Acceptance (roadmap S-176): require linear history —
merge commits refused on the branch; squash/rebase
merges remain available.

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
from samverk.protection_linear_history import (
    LINEAR_HISTORY_REQUIRED, LinearHistoryProtectionStore,
    LinearHistoryRequiredError, commit_parents,
    decide_linear_history, render_linear_history_decision)
from samverk.protection_rules import ProtectionRuleStore, evaluate_rules
from samverk.pull_requests import PullRequestStore
from samverk.receive_gate import GateContext, GateVeto
from samverk.repositories import RepositoryStore

ZERO = "0" * 40


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
        blob = git(repo, "hash-object", "-w", "--stdin",
                   input_bytes=files[name].encode())
        lines.append(f"100644 blob {blob}\t{name}\n")
    tree = git(repo, "mktree", input_bytes="".join(lines).encode())
    headers = [f"tree {tree}"]
    for parent in parents:
        headers.append(f"parent {parent}")
    headers.append("author T <t@t> 1700000000 +0000")
    headers.append("committer T <t@t> 1700000000 +0000")
    raw = ("\n".join(headers) + f"\n\n{message}\n").encode()
    return git(repo, "hash-object", "-t", "commit", "-w", "--stdin",
               input_bytes=raw)


BASE_FILES = {"a.txt": "alpha\nbeta\n"}
HEAD_FILES = {"a.txt": "alpha\nBETA\n"}
SIDE_FILES = {"a.txt": "alpha\nbeta\n", "b.txt": "side\n"}


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class ProtectionLinearHistoryTests(unittest.TestCase):
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
        self.prs = PullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.gate = LinearHistoryProtectionStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        self.path = self.repos.path_for("volmarr", "pub")
        self.base_oid = make_commit(self.path, [], BASE_FILES, "base")
        git(self.path, "update-ref", "refs/heads/main", self.base_oid)

    # -- helpers ---------------------------------------------------------

    def _require(self, repo="pub", pattern="main"):
        return self.rules.create_rule(
            self.owner, "volmarr", repo, pattern,
            require_linear_history=True)

    def _linear(self, message="feature work", parents=None):
        return make_commit(self.path, parents or [self.base_oid],
                           HEAD_FILES, message)

    def _merge(self, message="merge work"):
        side = make_commit(self.path, [self.base_oid], SIDE_FILES, "side")
        return make_commit(
            self.path, [self.base_oid, side], HEAD_FILES, message)

    # -- the pure parser ---------------------------------------------------

    def test_parser_two_parents_is_a_merge(self):
        raw = (b"tree abc\nparent aaa\nparent bbb\n"
               b"author T <t@t> 1 +0000\n\nsubject line\n")
        record = commit_parents(raw, oid="f" * 40)
        self.assertTrue(record.is_merge)
        self.assertEqual(record.parents, ("aaa", "bbb"))
        self.assertEqual(record.subject, "subject line")

    def test_parser_one_parent_is_linear(self):
        raw = b"tree abc\nparent aaa\n\nmsg\n"
        record = commit_parents(raw)
        self.assertFalse(record.is_merge)
        self.assertEqual(record.parents, ("aaa",))

    def test_parser_root_commit_is_linear(self):
        raw = b"tree abc\nauthor T <t@t> 1 +0000\n\nmsg\n"
        record = commit_parents(raw)
        self.assertFalse(record.is_merge)
        self.assertEqual(record.parents, ())

    def test_parser_ignores_parent_line_in_message_body(self):
        raw = b"tree abc\nparent aaa\n\nparent bbb\nmore text\n"
        record = commit_parents(raw)
        self.assertFalse(record.is_merge)
        self.assertEqual(record.parents, ("aaa",))

    def test_parser_octopus_merge_counts_all_parents(self):
        raw = b"tree abc\nparent a\nparent b\nparent c\n\nmsg\n"
        record = commit_parents(raw)
        self.assertTrue(record.is_merge)
        self.assertEqual(len(record.parents), 3)

    # -- the pure decision ---------------------------------------------------

    def test_pure_decision_no_rule_is_satisfied(self):
        evaluation = evaluate_rules([], "main", full_name="volmarr/pub")
        decision = decide_linear_history(evaluation, [])
        self.assertFalse(decision.required)
        self.assertTrue(decision.satisfied)

    def test_pure_decision_uncounted_fails_closed_when_required(self):
        rule = self._require()
        evaluation = self.rules.evaluate_branch(
            self.owner, "volmarr", "pub", "main")
        decision = decide_linear_history(evaluation, None)
        self.assertTrue(decision.required)
        self.assertFalse(decision.satisfied)
        self.assertIn("could not be counted", decision.reason)
        self.assertIsNotNone(rule)

    def test_pure_decision_unknown_method_refused(self):
        evaluation = evaluate_rules([], "main", full_name="volmarr/pub")
        with self.assertRaises(ValueError):
            decide_linear_history(evaluation, [], number=1, method="fast")

    # -- the push door ---------------------------------------------------

    def test_push_merge_commit_refused_when_required(self):
        self._require()
        head = self._merge()
        git(self.path, "update-ref", "refs/heads/feature", head)
        with self.assertRaises(LinearHistoryRequiredError) as caught:
            self.gate.enforce_push_update(
                self.owner, "volmarr", "pub", "main",
                self.base_oid, head)
        self.assertEqual(caught.exception.reason, LINEAR_HISTORY_REQUIRED)
        self.assertIn("is a merge commit", str(caught.exception))

    def test_push_linear_allowed_when_required(self):
        self._require()
        head = self._linear()
        decision = self.gate.enforce_push_update(
            self.owner, "volmarr", "pub", "main", self.base_oid, head)
        self.assertTrue(decision.satisfied)
        self.assertEqual(decision.linear_count, 1)

    def test_push_mixed_history_refused_naming_the_merge(self):
        self._require()
        merge = self._merge(message="the merge step")
        head = make_commit(self.path, [merge], HEAD_FILES, "linear step")
        decision = self.gate.check_push_update(
            self.owner, "volmarr", "pub", "main", self.base_oid, head)
        self.assertFalse(decision.satisfied)
        self.assertEqual(len(decision.merge_commits), 1)
        self.assertIn("the merge step", decision.reason)

    def test_push_merge_allowed_without_rule(self):
        head = self._merge()
        decision = self.gate.enforce_push_update(
            self.owner, "volmarr", "pub", "main", self.base_oid, head)
        self.assertTrue(decision.satisfied)

    def test_push_to_unmatched_branch_allowed(self):
        self._require()
        head = self._merge()
        decision = self.gate.enforce_push_update(
            self.owner, "volmarr", "pub", "topic", self.base_oid, head)
        self.assertTrue(decision.satisfied)

    def test_disabled_rule_does_not_refuse(self):
        rule = self._require()
        self.rules.update_rule(
            self.owner, "volmarr", "pub", rule.id, enabled=False)
        head = self._merge()
        decision = self.gate.enforce_push_update(
            self.owner, "volmarr", "pub", "main", self.base_oid, head)
        self.assertTrue(decision.satisfied)

    def test_branch_creation_merge_refused_linear_allowed(self):
        self._require(pattern="release*")
        merge = self._merge()
        with self.assertRaises(LinearHistoryRequiredError):
            self.gate.enforce_push_update(
                self.owner, "volmarr", "pub", "release-1", ZERO, merge)
        linear = self._linear()
        decision = self.gate.enforce_push_update(
            self.owner, "volmarr", "pub", "release-1", ZERO, linear)
        self.assertTrue(decision.satisfied)

    def test_branch_deletion_carries_no_commits(self):
        self._require()
        decision = self.gate.enforce_push_update(
            self.owner, "volmarr", "pub", "main", self.base_oid, ZERO)
        self.assertTrue(decision.satisfied)

    def test_check_push_skips_tags_and_judges_branches(self):
        self._require()
        head = self._merge()
        updates = (
            RefUpdate(ref="refs/tags/v1", old_oid=ZERO, new_oid=head),
            RefUpdate(ref="refs/heads/main", old_oid=self.base_oid,
                      new_oid=head),
        )
        decisions = self.gate.check_push(
            self.owner, "volmarr", "pub", updates)
        self.assertEqual(len(decisions), 1)
        self.assertFalse(decisions[0].satisfied)
        with self.assertRaises(LinearHistoryRequiredError):
            self.gate.enforce_push(self.owner, "volmarr", "pub", updates)

    def test_gate_plugin_vetoes_merge_push(self):
        self._require()
        head = self._merge()
        context = GateContext(
            repo="volmarr/pub", owner="volmarr", repo_name="pub",
            actor="volmarr",
            updates=(RefUpdate(ref="refs/heads/main",
                               old_oid=self.base_oid, new_oid=head),))
        with self.assertRaises(GateVeto) as caught:
            self.gate.receive_gate_plugin()(context)
        self.assertIn("is a merge commit", caught.exception.reason)
        linear = self._linear()
        ok = GateContext(
            repo="volmarr/pub", owner="volmarr", repo_name="pub",
            actor="volmarr",
            updates=(RefUpdate(ref="refs/heads/main",
                               old_oid=self.base_oid, new_oid=linear),))
        self.assertIsNone(self.gate.receive_gate_plugin()(ok))

    def test_private_repo_stranger_gets_repo_not_found(self):
        self._require(repo="priv")
        with self.assertRaises(Exception) as caught:
            self.gate.check_push_update(
                self.reader, "volmarr", "priv", "main", ZERO, self.base_oid)
        self.assertEqual(getattr(caught.exception, "reason", ""),
                         "repo_not_found")

    # -- the merge door ---------------------------------------------------

    def _pr(self, head, repo="pub"):
        git(self.path, "update-ref", "refs/heads/feature", head)
        return self.prs.create_pull_request(
            self.owner, "volmarr", repo, base_branch="main",
            head_branch="feature")

    def test_merge_method_refused_even_with_linear_head(self):
        self._require()
        pr = self._pr(self._linear())
        with self.assertRaises(LinearHistoryRequiredError) as caught:
            self.gate.enforce_pull_request(
                self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(caught.exception.reason, LINEAR_HISTORY_REQUIRED)
        self.assertIn("squash or rebase", str(caught.exception))
        decision = self.gate.check_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(decision.number, pr.number)
        self.assertIn("pull request", decision.words)

    def test_merge_method_names_carried_merge_commits(self):
        self._require()
        pr = self._pr(self._merge(message="head merge"))
        decision = self.gate.check_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertFalse(decision.satisfied)
        self.assertEqual(len(decision.blockers), 2)
        self.assertIn("head merge", decision.blockers[1])

    def test_squash_landing_allowed_and_flattens_merges(self):
        self._require()
        pr = self._pr(self._merge())
        decision = self.gate.enforce_pull_request(
            self.owner, "volmarr", "pub", pr.number, method="squash")
        self.assertTrue(decision.satisfied)
        self.assertIn("squash", decision.words)
        self.assertEqual(len(decision.merge_commits), 1)

    def test_rebase_landing_allowed_with_linear_head(self):
        self._require()
        pr = self._pr(self._linear())
        decision = self.gate.enforce_pull_request(
            self.owner, "volmarr", "pub", pr.number, method="rebase")
        self.assertTrue(decision.satisfied)

    def test_merge_method_allowed_without_rule(self):
        pr = self._pr(self._merge())
        decision = self.gate.enforce_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertTrue(decision.satisfied)

    def test_private_pr_stranger_gets_not_found(self):
        path = self.repos.path_for("volmarr", "priv")
        base = make_commit(path, [], BASE_FILES, "base")
        git(path, "update-ref", "refs/heads/main", base)
        head = make_commit(path, [base], HEAD_FILES, "work")
        git(path, "update-ref", "refs/heads/feature", head)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "priv", base_branch="main",
            head_branch="feature")
        self._require(repo="priv")
        with self.assertRaises(Exception) as caught:
            self.gate.check_pull_request(
                self.reader, "volmarr", "priv", pr.number)
        self.assertEqual(getattr(caught.exception, "reason", ""),
                         "pull_request_not_found")

    # -- words, pins ---------------------------------------------------------

    def test_renderer_prints_the_decisions_words(self):
        self._require()
        head = self._merge()
        decision = self.gate.check_push_update(
            self.owner, "volmarr", "pub", "main", self.base_oid, head)
        html = render_linear_history_decision(decision)
        self.assertIn("protection-linear-history", html)
        self.assertIn("not satisfied", html)
        self.assertIn("is a merge commit", html)

    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 66)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 119)


if __name__ == "__main__":
    unittest.main()
