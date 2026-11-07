"""S-177 acceptance battery: block force pushes and
branch deletion.

Acceptance (roadmap S-177): block force pushes and
branch deletion — on protected patterns, for everyone,
admins included unless S-179's bypass is used (S-179
has not landed, so no bypass exists yet).

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
from samverk.branch_housekeeping import (
    deletable_guard_reason, is_deletable_branch)
from samverk.db import schema_version
from samverk.hooks import RefUpdate
from samverk.issues import IssueStore
from samverk.protection_push_shape import (
    CREATION, DELETION, FAST_FORWARD, FORCE, NO_OP,
    PROTECTED_PUSH_REFUSED, UNPROVEN, PushShapeProtectionStore,
    PushShapeRefusedError, decide_push_shape,
    render_push_shape_decision, update_shape)
from samverk.protection_rules import (
    ProtectionRule, ProtectionRuleStore, ProtectionSettings,
    evaluate_rules)
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


def _evaluation(settings=None, pattern="main", branch="main"):
    rule = ProtectionRule(
        id=1, repo_id=1, full_name="volmarr/pub", pattern=pattern,
        settings=settings or ProtectionSettings(),
        created_by=None, created_at=0, updated_at=0)
    return evaluate_rules([rule], branch, full_name="volmarr/pub")


class ProtectionPushShapeTests(unittest.TestCase):
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
        self.gate = PushShapeProtectionStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        self.path = self.repos.path_for("volmarr", "pub")
        self.base_oid = make_commit(self.path, [], BASE_FILES, "base")
        git(self.path, "update-ref", "refs/heads/main", self.base_oid)
        self.ff_oid = make_commit(
            self.path, [self.base_oid], HEAD_FILES, "feature work")
        self.div_oid = make_commit(
            self.path, [self.base_oid], SIDE_FILES, "divergent work")

    # -- helpers ---------------------------------------------------------

    def _protect(self, repo="pub", pattern="main", **fields):
        return self.rules.create_rule(
            self.owner, "volmarr", repo, pattern, **fields)

    # -- the pure classifier ----------------------------------------------

    def test_classifier_creation(self):
        self.assertEqual(update_shape(ZERO, self.ff_oid, None), CREATION)

    def test_classifier_deletion(self):
        self.assertEqual(update_shape(self.base_oid, ZERO, None), DELETION)

    def test_classifier_no_op(self):
        self.assertEqual(
            update_shape(self.base_oid, self.base_oid, None), NO_OP)

    def test_classifier_fast_forward(self):
        self.assertEqual(
            update_shape(self.base_oid, self.ff_oid, True), FAST_FORWARD)

    def test_classifier_force(self):
        self.assertEqual(
            update_shape(self.ff_oid, self.div_oid, False), FORCE)

    def test_classifier_unproven_move(self):
        self.assertEqual(
            update_shape(self.base_oid, self.ff_oid, None), UNPROVEN)

    def test_classifier_unknown_new_is_unproven(self):
        self.assertEqual(update_shape(self.base_oid, "", None), UNPROVEN)

    # -- the pure seam ------------------------------------------------------

    def test_pure_no_rule_force_satisfied(self):
        evaluation = evaluate_rules([], "main", full_name="volmarr/pub")
        decision = decide_push_shape(
            evaluation, self.ff_oid, self.div_oid, ancestor=False)
        self.assertEqual(decision.shape, FORCE)
        self.assertTrue(decision.satisfied)

    def test_pure_force_blocked_by_default_rule(self):
        decision = decide_push_shape(
            _evaluation(), self.ff_oid, self.div_oid, ancestor=False)
        self.assertFalse(decision.satisfied)
        self.assertIn("admins included", decision.blockers[0])
        self.assertIn("force push", decision.words)

    def test_pure_force_allowed_when_block_off(self):
        settings = ProtectionSettings(block_force_pushes=False)
        decision = decide_push_shape(
            _evaluation(settings), self.ff_oid, self.div_oid,
            ancestor=False)
        self.assertTrue(decision.satisfied)
        self.assertIn("not blocked", decision.words)

    def test_pure_deletion_blocked_by_default_rule(self):
        decision = decide_push_shape(
            _evaluation(), self.base_oid, ZERO)
        self.assertEqual(decision.shape, DELETION)
        self.assertFalse(decision.satisfied)
        self.assertIn("cannot be deleted", decision.blockers[0])

    def test_pure_deletion_allowed_when_block_off(self):
        settings = ProtectionSettings(block_branch_deletion=False)
        decision = decide_push_shape(
            _evaluation(settings), self.base_oid, ZERO)
        self.assertTrue(decision.satisfied)

    def test_pure_unproven_move_blocked_when_force_block_on(self):
        decision = decide_push_shape(
            _evaluation(), self.base_oid, self.ff_oid, ancestor=None)
        self.assertEqual(decision.shape, UNPROVEN)
        self.assertFalse(decision.satisfied)

    def test_pure_unproven_move_satisfied_without_rule(self):
        evaluation = evaluate_rules([], "main", full_name="volmarr/pub")
        decision = decide_push_shape(
            evaluation, self.base_oid, self.ff_oid, ancestor=None)
        self.assertTrue(decision.satisfied)
        self.assertIn("was not proven", decision.words)

    # -- the push door --------------------------------------------------------

    def test_force_push_refused_for_the_owner(self):
        self._protect()
        with self.assertRaises(PushShapeRefusedError) as caught:
            self.gate.enforce_push_update(
                self.owner, "volmarr", "pub", "main",
                self.ff_oid, self.div_oid)
        self.assertEqual(caught.exception.reason, PROTECTED_PUSH_REFUSED)
        self.assertIn("admins included", str(caught.exception))

    def test_fast_forward_allowed(self):
        self._protect()
        decision = self.gate.enforce_push_update(
            self.owner, "volmarr", "pub", "main",
            self.base_oid, self.ff_oid)
        self.assertTrue(decision.satisfied)
        self.assertEqual(decision.shape, FAST_FORWARD)

    def test_deletion_refused(self):
        self._protect()
        with self.assertRaises(PushShapeRefusedError) as caught:
            self.gate.enforce_push_update(
                self.owner, "volmarr", "pub", "main",
                self.base_oid, ZERO)
        self.assertEqual(caught.exception.reason, PROTECTED_PUSH_REFUSED)
        decision = self.gate.check_push_update(
            self.owner, "volmarr", "pub", "main", self.base_oid, ZERO)
        self.assertEqual(decision.shape, DELETION)

    def test_deletion_allowed_when_block_off(self):
        self._protect(block_branch_deletion=False)
        decision = self.gate.enforce_push_update(
            self.owner, "volmarr", "pub", "main", self.base_oid, ZERO)
        self.assertTrue(decision.satisfied)

    def test_creation_allowed_under_rule(self):
        self._protect()
        decision = self.gate.enforce_push_update(
            self.owner, "volmarr", "pub", "main", ZERO, self.ff_oid)
        self.assertTrue(decision.satisfied)
        self.assertEqual(decision.shape, CREATION)

    def test_force_push_allowed_without_rule(self):
        decision = self.gate.enforce_push_update(
            self.owner, "volmarr", "pub", "main",
            self.ff_oid, self.div_oid)
        self.assertTrue(decision.satisfied)

    def test_force_push_allowed_on_unmatched_branch(self):
        self._protect()
        decision = self.gate.enforce_push_update(
            self.owner, "volmarr", "pub", "dev",
            self.ff_oid, self.div_oid)
        self.assertTrue(decision.satisfied)

    def test_force_push_allowed_when_rule_disabled(self):
        self._protect(enabled=False)
        decision = self.gate.enforce_push_update(
            self.owner, "volmarr", "pub", "main",
            self.ff_oid, self.div_oid)
        self.assertTrue(decision.satisfied)

    def test_unreadable_move_fails_closed(self):
        self._protect()
        decision = self.gate.check_push_update(
            self.owner, "volmarr", "pub", "main",
            "f" * 40, self.ff_oid)
        self.assertEqual(decision.shape, UNPROVEN)
        self.assertFalse(decision.satisfied)

    def test_whole_push_skips_tags_and_allows_fast_forward(self):
        self._protect()
        updates = (
            RefUpdate(ref="refs/tags/v1", old_oid=ZERO,
                      new_oid=self.ff_oid),
            RefUpdate(ref="refs/heads/main", old_oid=self.base_oid,
                      new_oid=self.ff_oid))
        decisions = self.gate.enforce_push(
            self.owner, "volmarr", "pub", updates)
        self.assertEqual(len(decisions), 1)
        self.assertTrue(decisions[0].satisfied)

    def test_whole_push_refuses_first_blocked_branch(self):
        self._protect()
        updates = (
            RefUpdate(ref="refs/heads/main", old_oid=self.base_oid,
                      new_oid=ZERO),)
        with self.assertRaises(PushShapeRefusedError):
            self.gate.enforce_push(self.owner, "volmarr", "pub", updates)

    def test_gate_plugin_vetoes_force_and_allows_fast_forward(self):
        self._protect()
        plugin = self.gate.receive_gate_plugin()
        ctx = GateContext(
            repo="volmarr/pub", owner="volmarr", repo_name="pub",
            actor="volmarr",
            updates=(RefUpdate(ref="refs/heads/main",
                               old_oid=self.ff_oid,
                               new_oid=self.div_oid),))
        with self.assertRaises(GateVeto):
            plugin(ctx)
        ok_ctx = GateContext(
            repo="volmarr/pub", owner="volmarr", repo_name="pub",
            actor="volmarr",
            updates=(RefUpdate(ref="refs/heads/main",
                               old_oid=self.base_oid,
                               new_oid=self.ff_oid),))
        self.assertIsNone(plugin(ok_ctx))

    def test_private_stranger_gets_repo_not_found(self):
        self._protect(repo="priv")
        with self.assertRaises(Exception) as caught:
            self.gate.check_push_update(
                self.reader, "volmarr", "priv", "main",
                self.base_oid, ZERO)
        self.assertEqual(getattr(caught.exception, "reason", ""),
                         "repo_not_found")

    # -- the housekeeping wiring (guard 6) -------------------------------------

    def test_housekeeping_guard_keeps_protected_branch(self):
        repo = self.repos.get_repository("volmarr", "pub")
        self.assertTrue(is_deletable_branch(repo, "release"))
        self._protect(pattern="release")
        self.assertFalse(is_deletable_branch(
            repo, "release", rules=self.rules, viewer=self.owner))
        self.assertIn("protected branch", deletable_guard_reason(
            repo, "release", rules=self.rules, viewer=self.owner))
        self.assertTrue(is_deletable_branch(
            repo, "feature", rules=self.rules, viewer=self.owner))

    # -- words, pins ---------------------------------------------------------

    def test_renderer_prints_the_decisions_words(self):
        self._protect()
        decision = self.gate.check_push_update(
            self.owner, "volmarr", "pub", "main",
            self.ff_oid, self.div_oid)
        html = render_push_shape_decision(decision)
        self.assertIn("protection-push-shape", html)
        self.assertIn("not satisfied", html)
        self.assertIn("force push", html)

    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 66)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 120)


if __name__ == "__main__":
    unittest.main()
