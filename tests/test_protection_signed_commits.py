"""S-175 acceptance battery: require signed commits.

Acceptance (roadmap S-175): require signed commits —
pushes and merges carrying unsigned commits refused
(verification itself lands in Part XV; the rule shape
lands here).

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
from samverk.protection_rules import ProtectionRuleStore, evaluate_rules
from samverk.protection_signed_commits import (
    SIGNED_COMMITS_REQUIRED, SignedCommitProtectionStore,
    SignedCommitsRequiredError, commit_signature,
    decide_signed_commits, render_signed_commit_decision)
from samverk.pull_requests import PullRequestStore
from samverk.receive_gate import GateContext, GateVeto
from samverk.repositories import RepositoryStore

ZERO = "0" * 40
SIG = "-----BEGIN PGP SIGNATURE-----\n iQEzBAAB\n =abcd\n-----END PGP SIGNATURE-----"


def git(repo, *args, input_bytes=None):
    env = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin"}
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         capture_output=True, input=input_bytes, env=env)
    assert out.returncode == 0, out.stderr.decode()
    return out.stdout.decode().strip()


def make_commit(repo, parents, files, message, sig=None, sig_header="gpgsig"):
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
    if sig is not None:
        sig_lines = sig.split("\n")
        headers.append(f"{sig_header} {sig_lines[0]}")
        for extra in sig_lines[1:]:
            headers.append(f" {extra}")
    raw = ("\n".join(headers) + f"\n\n{message}\n").encode()
    return git(repo, "hash-object", "-t", "commit", "-w", "--stdin",
               input_bytes=raw)


BASE_FILES = {"a.txt": "alpha\nbeta\n"}
HEAD_FILES = {"a.txt": "alpha\nBETA\n"}


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class ProtectionSignedCommitsTests(unittest.TestCase):
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
        self.gate = SignedCommitProtectionStore(
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
            require_signed_commits=True)

    def _head(self, sig, message="feature work", parents=None):
        return make_commit(self.path, parents or [self.base_oid],
                           HEAD_FILES, message, sig=sig)

    # -- the pure parser ---------------------------------------------------

    def test_parser_reads_gpgsig_header(self):
        raw = (b"tree abc\ngpgsig -----BEGIN PGP SIGNATURE-----\n"
               b" abc\n\nsubject line\n")
        record = commit_signature(raw, oid="f" * 40)
        self.assertTrue(record.signed)
        self.assertEqual(record.kind, "OpenPGP")
        self.assertEqual(record.subject, "subject line")

    def test_parser_reads_gpgsig_sha256_header(self):
        raw = b"tree abc\ngpgsig-sha256 -----BEGIN-----\n x\n\nmsg\n"
        self.assertTrue(commit_signature(raw).signed)

    def test_parser_ignores_signature_in_message_body(self):
        raw = b"tree abc\n\ngpgsig -----BEGIN PGP SIGNATURE-----\n"
        self.assertFalse(commit_signature(raw).signed)

    def test_parser_empty_header_is_unsigned(self):
        raw = b"tree abc\ngpgsig \n\nmsg\n"
        self.assertFalse(commit_signature(raw).signed)

    def test_parser_plain_commit_is_unsigned(self):
        raw = b"tree abc\nauthor T <t@t> 1 +0000\n\nmsg\n"
        record = commit_signature(raw)
        self.assertFalse(record.signed)
        self.assertEqual(record.kind, "")

    # -- the pure decision ---------------------------------------------------

    def test_pure_decision_no_rule_is_satisfied(self):
        evaluation = evaluate_rules([], "main", full_name="volmarr/pub")
        decision = decide_signed_commits(evaluation, [])
        self.assertFalse(decision.required)
        self.assertTrue(decision.satisfied)

    def test_pure_decision_uncounted_fails_closed_when_required(self):
        rule = self._require()
        evaluation = self.rules.evaluate_branch(
            self.owner, "volmarr", "pub", "main")
        decision = decide_signed_commits(evaluation, None)
        self.assertTrue(decision.required)
        self.assertFalse(decision.satisfied)
        self.assertIn("could not be counted", decision.reason)
        self.assertIsNotNone(rule)

    # -- the push door ---------------------------------------------------

    def test_push_unsigned_refused_when_required(self):
        self._require()
        head = self._head(None)
        git(self.path, "update-ref", "refs/heads/feature", head)
        with self.assertRaises(SignedCommitsRequiredError) as caught:
            self.gate.enforce_push_update(
                self.owner, "volmarr", "pub", "main",
                self.base_oid, head)
        self.assertEqual(caught.exception.reason, SIGNED_COMMITS_REQUIRED)
        self.assertIn("carries no signature", str(caught.exception))

    def test_push_signed_allowed_when_required(self):
        self._require()
        head = self._head(SIG)
        decision = self.gate.enforce_push_update(
            self.owner, "volmarr", "pub", "main", self.base_oid, head)
        self.assertTrue(decision.satisfied)
        self.assertEqual(decision.signed_count, 1)

    def test_push_mixed_history_refused_naming_unsigned(self):
        self._require()
        mid = self._head(SIG, message="signed step")
        head = make_commit(self.path, [mid], HEAD_FILES, "unsigned step")
        decision = self.gate.check_push_update(
            self.owner, "volmarr", "pub", "main", self.base_oid, head)
        self.assertFalse(decision.satisfied)
        self.assertEqual(len(decision.unsigned_commits), 1)
        self.assertIn("unsigned step", decision.reason)

    def test_push_unsigned_allowed_without_rule(self):
        head = self._head(None)
        decision = self.gate.enforce_push_update(
            self.owner, "volmarr", "pub", "main", self.base_oid, head)
        self.assertTrue(decision.satisfied)

    def test_push_to_unmatched_branch_allowed(self):
        self._require()
        head = self._head(None)
        decision = self.gate.enforce_push_update(
            self.owner, "volmarr", "pub", "topic", self.base_oid, head)
        self.assertTrue(decision.satisfied)

    def test_disabled_rule_does_not_refuse(self):
        rule = self._require()
        self.rules.update_rule(
            self.owner, "volmarr", "pub", rule.id, enabled=False)
        head = self._head(None)
        decision = self.gate.enforce_push_update(
            self.owner, "volmarr", "pub", "main", self.base_oid, head)
        self.assertTrue(decision.satisfied)

    def test_branch_creation_unsigned_refused_signed_allowed(self):
        self._require(pattern="release*")
        unsigned = self._head(None)
        with self.assertRaises(SignedCommitsRequiredError):
            self.gate.enforce_push_update(
                self.owner, "volmarr", "pub", "release-1", ZERO, unsigned)
        signed = self._head(SIG)
        decision = self.gate.enforce_push_update(
            self.owner, "volmarr", "pub", "release-1", ZERO, signed)
        self.assertTrue(decision.satisfied)

    def test_branch_deletion_carries_no_commits(self):
        self._require()
        decision = self.gate.enforce_push_update(
            self.owner, "volmarr", "pub", "main", self.base_oid, ZERO)
        self.assertTrue(decision.satisfied)

    def test_check_push_skips_tags_and_judges_branches(self):
        self._require()
        head = self._head(None)
        updates = (
            RefUpdate(ref="refs/tags/v1", old_oid=ZERO, new_oid=head),
            RefUpdate(ref="refs/heads/main", old_oid=self.base_oid,
                      new_oid=head),
        )
        decisions = self.gate.check_push(
            self.owner, "volmarr", "pub", updates)
        self.assertEqual(len(decisions), 1)
        self.assertFalse(decisions[0].satisfied)
        with self.assertRaises(SignedCommitsRequiredError):
            self.gate.enforce_push(self.owner, "volmarr", "pub", updates)

    def test_gate_plugin_vetoes_unsigned_push(self):
        self._require()
        head = self._head(None)
        context = GateContext(
            repo="volmarr/pub", owner="volmarr", repo_name="pub",
            actor="volmarr",
            updates=(RefUpdate(ref="refs/heads/main",
                               old_oid=self.base_oid, new_oid=head),))
        with self.assertRaises(GateVeto) as caught:
            self.gate.receive_gate_plugin()(context)
        self.assertIn("carries no signature", caught.exception.reason)
        signed = self._head(SIG)
        ok = GateContext(
            repo="volmarr/pub", owner="volmarr", repo_name="pub",
            actor="volmarr",
            updates=(RefUpdate(ref="refs/heads/main",
                               old_oid=self.base_oid, new_oid=signed),))
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

    def test_merge_unsigned_head_refused(self):
        self._require()
        pr = self._pr(self._head(None))
        with self.assertRaises(SignedCommitsRequiredError) as caught:
            self.gate.enforce_pull_request(
                self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(caught.exception.reason, SIGNED_COMMITS_REQUIRED)
        decision = self.gate.check_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(decision.number, pr.number)
        self.assertIn("pull request", decision.words)

    def test_merge_signed_head_allowed(self):
        self._require()
        pr = self._pr(self._head(SIG))
        decision = self.gate.enforce_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertTrue(decision.satisfied)

    def test_merge_unsigned_allowed_without_rule(self):
        pr = self._pr(self._head(None))
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
        head = self._head(None)
        decision = self.gate.check_push_update(
            self.owner, "volmarr", "pub", "main", self.base_oid, head)
        html = render_signed_commit_decision(decision)
        self.assertIn("protection-signed-commits", html)
        self.assertIn("not satisfied", html)
        self.assertIn("carries no signature", html)

    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 81)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 122)


if __name__ == "__main__":
    unittest.main()
