"""S-170 acceptance battery: require pull request before merging.

Acceptance (roadmap S-170): direct pushes to a protected
branch refused at receive-pack with a human-readable reason.

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
from samverk.protection_pull_request import (
    PULL_REQUEST_REQUIRED, PullRequestProtectionStore,
    PullRequestRequiredError, branch_from_ref,
    decide_direct_push, render_direct_push_decision)
from samverk.protection_rules import (
    ProtectionRuleError, ProtectionRuleStore, evaluate_rules, ProtectionRule,
    ProtectionSettings)
from samverk.pull_request_merge import PullRequestMergeStore
from samverk.pull_requests import PullRequestStore
from samverk.receive_gate import GateVeto, ReceiveGate
from samverk.repositories import RepositoryStore

ZERO = "0" * 40
ONE = "1" * 40
TWO = "2" * 40


def git(repo, *args, input_bytes=None):
    env = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin"}
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         capture_output=True, input=input_bytes, env=env)
    assert out.returncode == 0, out.stderr.decode()
    return out.stdout.decode().strip()


def make_tree(repo, files):
    def build(items):
        entries = []
        dirs = {}
        for path, content in items:
            head, _, rest = path.partition("/")
            if rest:
                dirs.setdefault(head, []).append((rest, content))
            else:
                blob = git(repo, "hash-object", "-w", "--stdin",
                           input_bytes=content.encode())
                entries.append((path, f"100644 blob {blob}\t{path}"))
        for name, sub in dirs.items():
            tree = build(sub)
            entries.append((name + "/", f"040000 tree {tree}\t{name}"))
        entries.sort(key=lambda item: item[0])
        return git(repo, "mktree",
                   input_bytes=("\n".join(
                       line for _key, line in entries) + "\n").encode())
    return build(sorted(files.items()))


def make_commit(repo, parent, files, message):
    tree = make_tree(repo, files)
    args = ["commit-tree", tree]
    if parent:
        args += ["-p", parent]
    return git(repo, *args, input_bytes=(message + "\n").encode())


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


class PullRequestProtectionTests(unittest.TestCase):
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
        self.rules = ProtectionRuleStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.gate = PullRequestProtectionStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")

    # -- helpers ---------------------------------------------------------
    def _require_pr(self, pattern="main", repo="pub", **fields):
        fields.setdefault("require_pull_request", True)
        return self.rules.create_rule(
            self.owner, "volmarr", repo, pattern, **fields)

    def _check(self, branch="main", repo="pub", viewer=None, **kw):
        return self.gate.check_branch(
            viewer or self.owner, "volmarr", repo, branch, **kw)

    # -- the core refusal --------------------------------------------------
    def test_protected_branch_direct_push_refused_with_reason(self):
        self._require_pr("main")
        decision = self._check("main")
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.requires_pull_request)
        self.assertIn("'main'", decision.reason)
        self.assertIn("volmarr/pub", decision.reason)
        self.assertIn("'main'", decision.words)
        self.assertIn("requires a pull request", decision.reason)
        self.assertIn("Open a pull request", decision.reason)
        with self.assertRaises(PullRequestRequiredError) as cm:
            self.gate.enforce_branch(self.owner, "volmarr", "pub", "main")
        self.assertEqual(cm.exception.reason, PULL_REQUEST_REQUIRED)
        self.assertEqual(str(cm.exception), decision.reason)

    def test_unprotected_branch_push_allowed(self):
        decision = self._check("feature")
        self.assertTrue(decision.allowed)
        self.assertFalse(decision.requires_pull_request)
        self.assertEqual(decision.reason, "")
        self.assertIn("is allowed", decision.words)
        out = self.gate.enforce_branch(
            self.owner, "volmarr", "pub", "feature")
        self.assertTrue(out.allowed)

    def test_rule_without_requirement_allows(self):
        self.rules.create_rule(self.owner, "volmarr", "pub", "main")
        decision = self._check("main")
        self.assertTrue(decision.allowed)

    def test_rule_toggled_off_allows(self):
        rule = self._require_pr("main")
        self.assertFalse(self._check("main").allowed)
        self.rules.update_rule(
            self.owner, "volmarr", "pub", rule.id,
            require_pull_request=False)
        self.assertTrue(self._check("main").allowed)
        self.rules.update_rule(
            self.owner, "volmarr", "pub", rule.id,
            require_pull_request=True)
        self.assertFalse(self._check("main").allowed)

    def test_disabled_rule_allows(self):
        self._require_pr("main", enabled=False)
        self.assertTrue(self._check("main").allowed)

    def test_pattern_matched_branch_covered(self):
        self._require_pr("release/*")
        self.assertFalse(self._check("release/1.0").allowed)
        self.assertTrue(self._check("release").allowed)
        self.assertTrue(self._check("main").allowed)
        decision = self._check("release/1.0")
        self.assertIn("'release/*'", decision.reason)

    def test_most_restrictive_fold_across_patterns(self):
        self.rules.create_rule(self.owner, "volmarr", "pub", "main")
        self._require_pr("m*")
        decision = self._check("main")
        self.assertFalse(decision.allowed)
        self.assertIn("'m*'", decision.reason)

    # -- a whole push -------------------------------------------------------
    def test_push_with_protected_branch_refused_first_wins(self):
        self._require_pr("main")
        updates = (RefUpdate("refs/heads/feature", ZERO, ONE),
                   RefUpdate("refs/heads/main", ONE, TWO))
        decisions = self.gate.check_push(
            self.owner, "volmarr", "pub", updates)
        self.assertEqual(len(decisions), 2)
        self.assertTrue(decisions[0].allowed)
        self.assertFalse(decisions[1].allowed)
        with self.assertRaises(PullRequestRequiredError) as cm:
            self.gate.enforce_push(self.owner, "volmarr", "pub", updates)
        self.assertIn("'main'", str(cm.exception))

    def test_push_to_unprotected_and_tags_allowed(self):
        self._require_pr("main")
        updates = (RefUpdate("refs/heads/feature", ZERO, ONE),
                   RefUpdate("refs/tags/v1", ZERO, ONE))
        decisions = self.gate.enforce_push(
            self.owner, "volmarr", "pub", updates)
        self.assertEqual(len(decisions), 1)
        self.assertTrue(decisions[0].allowed)

    def test_branch_creation_and_deletion_are_direct_pushes(self):
        self._require_pr("main")
        created = self.gate.check_push(
            self.owner, "volmarr", "pub",
            (RefUpdate("refs/heads/main", ZERO, ONE),))
        self.assertFalse(created[0].allowed)
        deleted = self.gate.check_push(
            self.owner, "volmarr", "pub",
            (RefUpdate("refs/heads/main", ONE, ZERO),))
        self.assertFalse(deleted[0].allowed)

    # -- the merge road ------------------------------------------------------
    def test_via_pull_request_is_allowed_and_said(self):
        self._require_pr("main")
        decision = self._check("main", via_pull_request=True)
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.requires_pull_request)
        self.assertIn("by pull request", decision.words)
        out = self.gate.enforce_branch(
            self.owner, "volmarr", "pub", "main", via_pull_request=True)
        self.assertTrue(out.allowed)

    def test_pull_request_merge_lands_on_protected_base(self):
        self._require_pr("main")
        issues = IssueStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        prs = PullRequestStore(
            self.conn, self.repos, self.accounts, issues,
            audit=self.audit, time_fn=self.clock)
        merge = PullRequestMergeStore(
            self.conn, self.repos, self.accounts, issues,
            audit=self.audit, time_fn=self.clock)
        path = self.repos.path_for("volmarr", "pub")
        base_oid = make_commit(path, None, {"a.txt": "alpha\n"}, "base")
        git(path, "update-ref", "refs/heads/main", base_oid)
        head_oid = make_commit(
            path, base_oid, {"a.txt": "alpha\nbeta\n"}, "feature work")
        git(path, "update-ref", "refs/heads/feature", head_oid)
        pr = prs.create_pull_request(
            self.owner, "volmarr", "pub", base_branch="main",
            head_branch="feature", title="Add beta", body="")
        self.assertFalse(self._check("main").allowed)
        merged = merge.merge_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        tip = git(path, "rev-parse", "refs/heads/main")
        self.assertEqual(tip, merged.merge_commit_oid)
        self.assertNotEqual(tip, base_oid)

    # -- the receive gate plug-in ---------------------------------------------
    def test_receive_gate_plugin_refuses_protected_push(self):
        self._require_pr("main")
        gate = ReceiveGate()
        gate.register_protection(
            "require-pull-request", self.gate.receive_gate_plugin())
        result = gate.check(
            owner="volmarr", repo="pub", actor="volmarr",
            transport="ssh",
            updates=(RefUpdate("refs/heads/main", ZERO, ONE),))
        self.assertFalse(result.allowed)
        self.assertEqual(result.refused_stage, "protection")
        self.assertEqual(result.refused_by, "require-pull-request")
        self.assertIn("'main'", result.reason)
        self.assertIn("Open a pull request", result.reason)

    def test_receive_gate_plugin_allows_unprotected_push(self):
        self._require_pr("main")
        gate = ReceiveGate()
        gate.register_protection(
            "require-pull-request", self.gate.receive_gate_plugin())
        result = gate.check(
            owner="volmarr", repo="pub", actor="volmarr",
            transport="http",
            updates=(RefUpdate("refs/heads/feature", ZERO, ONE),))
        self.assertTrue(result.allowed)

    def test_receive_gate_plugin_allows_pull_request_landing(self):
        self._require_pr("main")
        gate = ReceiveGate()
        gate.register_protection(
            "require-pull-request", self.gate.receive_gate_plugin())
        result = gate.check(
            owner="volmarr", repo="pub", actor="volmarr",
            transport="local",
            updates=(RefUpdate("refs/heads/main", ZERO, ONE),),
            payload={"via_pull_request": True})
        self.assertTrue(result.allowed)

    def test_receive_gate_plugin_with_no_updates_judges_nothing(self):
        self._require_pr("main")
        gate = ReceiveGate()
        gate.register_protection(
            "require-pull-request", self.gate.receive_gate_plugin())
        result = gate.check(owner="volmarr", repo="pub", actor="volmarr")
        self.assertTrue(result.allowed)

    # -- guards, purity, and invariants -----------------------------------------
    def test_private_repo_stranger_gets_uniform_not_found(self):
        self._require_pr("main", repo="priv")
        with self.assertRaises(ProtectionRuleError) as cm:
            self.gate.check_branch(self.reader, "volmarr", "priv", "main")
        self.assertEqual(cm.exception.reason, "repo_not_found")

    def test_admin_and_bypass_names_do_not_open_the_door_yet(self):
        self._require_pr("main", bypass_actors=["volmarr"])
        self.assertFalse(self._check("main").allowed)

    def test_refusal_writes_and_audits_nothing(self):
        self._require_pr("main")
        before = self.conn.execute(
            "SELECT COUNT(*) AS c FROM audit_log").fetchone()["c"]
        self._check("main")
        with self.assertRaises(PullRequestRequiredError):
            self.gate.enforce_branch(self.owner, "volmarr", "pub", "main")
        after = self.conn.execute(
            "SELECT COUNT(*) AS c FROM audit_log").fetchone()["c"]
        self.assertEqual(before, after)

    def test_pure_half_and_ref_parsing(self):
        rule = ProtectionRule(
            id=1, repo_id=1, full_name="volmarr/pub", pattern="main",
            settings=ProtectionSettings(require_pull_request=True),
            created_by=None, created_at=0, updated_at=0)
        evaluation = evaluate_rules([rule], "main", full_name="volmarr/pub")
        self.assertFalse(decide_direct_push(evaluation).allowed)
        self.assertTrue(decide_direct_push(
            evaluation, via_pull_request=True).allowed)
        self.assertEqual(branch_from_ref("refs/heads/main"), "main")
        self.assertEqual(
            branch_from_ref("refs/heads/release/1.0"), "release/1.0")
        self.assertIsNone(branch_from_ref("refs/tags/v1"))
        self.assertIsNone(branch_from_ref("refs/heads/"))
        self.assertIsNone(branch_from_ref("main"))
        self.assertIsNone(branch_from_ref(None))
        with self.assertRaises(PullRequestRequiredError):
            decide_direct_push(evaluation, via_pull_request="yes")

    def test_renderer_says_the_words_escaped(self):
        self._require_pr("main")
        html = render_direct_push_decision(self._check("main"))
        self.assertIn("pull-request-protection", html)
        self.assertIn("requires a pull request", html)
        html_ok = render_direct_push_decision(self._check("feature"))
        self.assertIn("is allowed", html_ok)

    def test_no_migration_no_new_taxonomy_event(self):
        self.assertEqual(schema_version(self.conn), 77)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 122)
        self.assertNotIn("repo.push.pull_request_required",
                         taxonomy.AUDIT_EVENTS)


if __name__ == "__main__":
    unittest.main()
