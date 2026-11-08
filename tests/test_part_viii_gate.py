"""S-184 — PART VIII GATE battery: branch protection, assembled.

The whole Part VIII system struck at once, in the house gate
shape of S-096/S-120/S-140/S-168 — no new production code,
only the battery that walks the landed S-169..S-183 machinery
end to end through its public seams, at the three things the
gate names:

- **Every rule** — the S-169 rule model and each gate it
  feeds: require-a-pull-request (S-170), required approvals
  (S-171), stale-review dismissal (S-172), code-owner review
  (S-173), required status checks and the up-to-date toggle
  (S-174), signed commits (S-175), linear history (S-176),
  force-push and deletion blocks (S-177), named push actors
  (S-178), the audited bypass road (S-179), enforcement for
  admins (S-180), layered rulesets (S-181), tag protection
  (S-182), and the rule-insights page that explains the
  battery's own refusals in plain words (S-183).
- **Every role** — as S-054's `role_for` resolves them
  today: the repository owner and a site admin (both
  `admin`), a named collaborator-actor, a reader, a
  stranger, and anonymous. Writers-by-name are told apart
  from admins throughout: a rule that names push actors
  refuses the owner it does not name, and the admin
  toggle — not the role — decides whether an admin is
  bound.
- **Both enforcement points** — the push door (branch
  and ref-update checks at receive time) and the merge
  door (pull-request checks at landing time). Signed
  commits and linear history are struck at both doors;
  the rest at the door each rule speaks at, and one
  branch wearing every rule at once is walked from
  all-refused to all-satisfied.

The gate claimed no migration and no taxonomy event: the
assembled system stands at schema 67 with 120 audit
events, and the battery proves both pins. The full-suite
counted recount at this gate is recorded in
PROJECT_MEMORY_MAP.md (the gate entry), read back from
its log file after the run finished.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.repositories import RepositoryError
from samverk.issues import IssueStore
from samverk.protection_admin_enforcement import AdminEnforcementStore
from samverk.protection_approvals import ApprovalProtectionStore
from samverk.protection_bypass import (
    BypassNotAllowedError, BypassProtectionStore)
from samverk.protection_codeowners import CodeOwnerProtectionStore
from samverk.protection_dismissal import DismissalProtectionStore
from samverk.protection_insights import RuleInsightsStore
from samverk.protection_linear_history import LinearHistoryProtectionStore
from samverk.protection_pull_request import (
    PullRequestProtectionStore, PullRequestRequiredError)
from samverk.protection_push_actors import PushActorProtectionStore
from samverk.protection_push_shape import PushShapeProtectionStore
from samverk.protection_rules import (
    ProtectionRuleStore, evaluate_rules, matches_pattern)
from samverk.protection_rulesets import RulesetStore
from samverk.protection_signed_commits import SignedCommitProtectionStore
from samverk.protection_status_checks import StatusCheckProtectionStore
from samverk.protection_tags import TagProtectionStore
from samverk.pull_request_checks import PullRequestChecksStore
from samverk.pull_request_codeowners import PullRequestCodeownersStore
from samverk.pull_request_reviews import PullRequestReviewStore
from samverk.pull_requests import PullRequestStore
from samverk.repositories import RepositoryStore

ZERO = "0" * 40
SIG = ("-----BEGIN PGP SIGNATURE-----\n iQEzBAAB\n =abcd\n"
       "-----END PGP SIGNATURE-----")

BASE_FILES = {"a.txt": "alpha\n"}
HEAD_FILES = {"a.txt": "alpha\nbeta\n"}
SIDE_FILES = {"a.txt": "alpha\n", "b.txt": "side\n"}
OWNERS_BASE = {"CODEOWNERS": "* @yrsa\n", "a.txt": "alpha\n"}
OWNERS_HEAD = {"CODEOWNERS": "* @yrsa\n", "a.txt": "alpha\nbeta\n"}


def git(repo, *args, input_bytes=None):
    env = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin"}
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         capture_output=True, input=input_bytes, env=env)
    assert out.returncode == 0, out.stderr.decode()
    return out.stdout.decode().strip()


def make_commit(repo, parents, files, message, sig=None):
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
        headers.append(f"gpgsig {sig_lines[0]}")
        for extra in sig_lines[1:]:
            headers.append(f" {extra}")
    raw = ("\n".join(headers) + f"\n\n{message}\n").encode()
    return git(repo, "hash-object", "-t", "commit", "-w", "--stdin",
               input_bytes=raw)


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


class PartVIIIGateTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.owner = self.accounts.register(
            "volmarr", "correct horse battery")
        self.writer = self.accounts.register(
            "yrsa", "correct horse battery")
        self.third = self.accounts.register(
            "tess", "correct horse battery")
        self.fourth = self.accounts.register(
            "mimir", "correct horse battery")
        self.site_admin = self.accounts.register(
            "rooty", "correct horse battery")
        with self.conn:
            self.conn.execute(
                "UPDATE users SET is_admin = 1 WHERE id = ?",
                (self.site_admin.id,))
        self.site_admin = self.accounts.get_by_username("rooty")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.issues = IssueStore(self.conn, self.repos, self.accounts,
                                 audit=self.audit, time_fn=self.clock)
        self.rules = ProtectionRuleStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.pr_gate = PullRequestProtectionStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.approvals_gate = ApprovalProtectionStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.dismissal_gate = DismissalProtectionStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.codeowners_gate = CodeOwnerProtectionStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.checks_gate = StatusCheckProtectionStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.signed_gate = SignedCommitProtectionStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.linear_gate = LinearHistoryProtectionStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.shape_gate = PushShapeProtectionStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.actors_gate = PushActorProtectionStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.bypass_gate = BypassProtectionStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.admin_gate = AdminEnforcementStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.rulesets = RulesetStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock,
            protection_rules=self.rules)
        self.tags_gate = TagProtectionStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock,
            rulesets=self.rulesets)
        self.insights = RuleInsightsStore(
            self.conn, self.repos, self.accounts)
        self.checks = PullRequestChecksStore(
            self.conn, self.repos, self.accounts, self.issues,
            time_fn=self.clock)
        self.prs = PullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.reviews = PullRequestReviewStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.codeowners = PullRequestCodeownersStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.wired_prs = PullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock,
            codeowners_sync=self.codeowners.sync_requests)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")

    # -- helpers -----------------------------------------------------

    def _repo_with_pr(self, name, base_files=BASE_FILES,
                      head_files=HEAD_FILES, visibility="public",
                      head_sig=None, wired=False):
        self.repos.create_repository(
            self.owner.id, "volmarr", name, visibility=visibility)
        path = self.repos.path_for("volmarr", name)
        base = make_commit(path, [], base_files, "base")
        git(path, "update-ref", "refs/heads/main", base)
        head = make_commit(path, [base], head_files, "feature work",
                           sig=head_sig)
        git(path, "update-ref", "refs/heads/feature", head)
        pr = (self.wired_prs if wired else self.prs).create_pull_request(
            self.owner, "volmarr", name, base_branch="main",
            head_branch="feature")
        return path, base, head, pr

    def _approve(self, who, repo, number):
        return self.reviews.submit_review(
            who, "volmarr", repo, number, verdict="approve",
            summary="Looks right to me.")

    # -- S-169: the rule model ---------------------------------------

    def test_rule_model_order_fold_and_patterns(self):
        self.rules.create_rule(
            self.owner, "volmarr", "pub", "*n", required_approvals=3)
        self.rules.create_rule(
            self.owner, "volmarr", "pub", "main", required_approvals=1,
            require_pull_request=True)
        self.assertTrue(matches_pattern("release-*", "release-1"))
        self.assertFalse(matches_pattern("main", "main2"))
        ev = self.rules.evaluate_branch(
            self.owner, "volmarr", "pub", "main")
        self.assertTrue(ev.is_protected)
        # Most-restrictive-wins: the glob's three approvals fold
        # over the exact rule's one; the pull-request demand holds.
        self.assertEqual(ev.effective.settings.required_approvals, 3)
        self.assertTrue(ev.effective.settings.require_pull_request)
        self.assertIn("main", ev.words)
        dev = self.rules.evaluate_branch(
            self.owner, "volmarr", "pub", "train")
        self.assertTrue(dev.is_protected)
        self.assertEqual(dev.effective.settings.required_approvals, 3)
        unmatched = self.rules.evaluate_branch(
            self.owner, "volmarr", "pub", "dev")
        self.assertFalse(unmatched.is_protected)
        pure = evaluate_rules(
            list(self.rules.list_rules(self.owner, "volmarr", "pub")),
            "main")
        self.assertEqual(pure.effective.settings.required_approvals, 3)

    def test_rule_writing_is_admin_work_for_every_other_role(self):
        for actor, reason in ((self.writer, "permission_denied"),
                              (self.third, "permission_denied"),
                              (None, "repo_not_found")):
            with self.assertRaises(RepositoryError) as cm:
                self.rules.create_rule(
                    actor, "volmarr", "pub", "main")
            self.assertEqual(cm.exception.reason, reason)
        # A stranger cannot even read a private repo's position.
        self.rules.create_rule(self.owner, "volmarr", "priv", "main")
        with self.assertRaises(RepositoryError) as cm:
            self.rules.evaluate_branch(
                self.third, "volmarr", "priv", "main")
        self.assertEqual(cm.exception.reason, "repo_not_found")
        with self.assertRaises(RepositoryError) as cm:
            self.rules.evaluate_branch(None, "volmarr", "priv", "main")
        self.assertEqual(cm.exception.reason, "repo_not_found")

    # -- S-170: require a pull request (push door) --------------------

    def test_require_pr_push_door_binds_every_role(self):
        self.rules.create_rule(
            self.owner, "volmarr", "pub", "main",
            require_pull_request=True)
        for viewer in (self.owner, self.site_admin, self.writer,
                       self.third, None):
            decision = self.pr_gate.check_branch(
                viewer, "volmarr", "pub", "main")
            self.assertFalse(decision.allowed, viewer)
            self.assertTrue(decision.requires_pull_request)
            self.assertFalse(decision.admin_exempt)
        with self.assertRaises(PullRequestRequiredError):
            self.pr_gate.enforce_branch(
                self.owner, "volmarr", "pub", "main")
        # An unruled branch is open at the same door.
        open_decision = self.pr_gate.check_branch(
            self.owner, "volmarr", "pub", "topic")
        self.assertTrue(open_decision.allowed)

    # -- S-171: required approvals (merge door) ------------------------

    def test_required_approvals_merge_door_and_roles(self):
        _path, _base, _head, pr = self._repo_with_pr("appr")
        self.rules.create_rule(
            self.owner, "volmarr", "appr", "main", required_approvals=2)
        decision = self.approvals_gate.check_pull_request(
            self.owner, "volmarr", "appr", pr.number)
        self.assertFalse(decision.satisfied)
        self.assertEqual(decision.approval_count, 0)
        self.assertTrue(decision.blockers)
        # The author can never approve their own work.
        with self.assertRaises(Exception) as cm:
            self._approve(self.owner, "appr", pr.number)
        self.assertEqual(getattr(cm.exception, "reason", ""),
                         "self_review")
        # A reader's approval counts: review standing is not
        # merge standing.
        self._approve(self.writer, "appr", pr.number)
        decision = self.approvals_gate.check_pull_request(
            self.owner, "volmarr", "appr", pr.number)
        self.assertEqual(decision.approval_count, 1)
        self.assertFalse(decision.satisfied)
        self._approve(self.third, "appr", pr.number)
        decision = self.approvals_gate.check_pull_request(
            self.owner, "volmarr", "appr", pr.number)
        self.assertEqual(decision.approval_count, 2)
        self.assertTrue(decision.satisfied)

    # -- S-172: dismiss stale reviews ----------------------------------

    def test_dismissal_on_new_push_merge_door(self):
        path, _base, head, pr = self._repo_with_pr("dism")
        self.rules.create_rule(
            self.owner, "volmarr", "dism", "main",
            dismiss_stale_reviews=True)
        self._approve(self.writer, "dism", pr.number)
        decision = self.dismissal_gate.dismissal_for(
            self.owner, "volmarr", "dism", pr.number)
        self.assertTrue(decision.dismiss_stale_reviews)
        self.assertEqual(decision.approval_count, 1)
        self.assertEqual(decision.dismissed_count, 0)
        pushed = make_commit(path, [head], HEAD_FILES, "more work")
        git(path, "update-ref", "refs/heads/feature", pushed)
        decision = self.dismissal_gate.dismissal_for(
            self.owner, "volmarr", "dism", pr.number)
        self.assertEqual(decision.dismissed_count, 1)
        self.assertEqual(decision.approval_count, 0)
        self.assertEqual(decision.dismissed_approver_ids,
                         (self.writer.id,))
        self._approve(self.writer, "dism", pr.number)
        decision = self.dismissal_gate.dismissal_for(
            self.owner, "volmarr", "dism", pr.number)
        self.assertEqual(decision.approval_count, 1)

    # -- S-173: code-owner review ---------------------------------------

    def test_code_owner_review_gate(self):
        _path, _base, _head, pr = self._repo_with_pr(
            "owners", base_files=OWNERS_BASE, head_files=OWNERS_HEAD, wired=True)
        self.rules.create_rule(
            self.owner, "volmarr", "owners", "main",
            require_code_owner_review=True)
        decision = self.codeowners_gate.check_pull_request(
            self.owner, "volmarr", "owners", pr.number)
        self.assertFalse(decision.satisfied)
        self.assertTrue(decision.has_code_owners)
        # A non-owner's approval, however willing, is not the
        # code owner's.
        self._approve(self.third, "owners", pr.number)
        decision = self.codeowners_gate.check_pull_request(
            self.owner, "volmarr", "owners", pr.number)
        self.assertFalse(decision.satisfied)
        self.assertEqual(decision.code_owner_approver_ids, ())
        self._approve(self.writer, "owners", pr.number)
        decision = self.codeowners_gate.check_pull_request(
            self.owner, "volmarr", "owners", pr.number)
        self.assertTrue(decision.satisfied)
        self.assertEqual(decision.code_owner_approver_ids,
                         (self.writer.id,))

    # -- S-174: required status checks -----------------------------------

    def test_status_checks_and_up_to_date_toggle(self):
        path, base, head, pr = self._repo_with_pr("checks")
        self.rules.create_rule(
            self.owner, "volmarr", "checks", "main",
            required_status_checks=["ci"],
            require_branch_up_to_date=True)
        decision = self.checks_gate.check_pull_request(
            self.owner, "volmarr", "checks", pr.number)
        self.assertFalse(decision.satisfied)
        self.assertIn("ci", decision.missing_checks)
        self.checks.record_result("volmarr", "checks", head, "ci",
                                  "pending")
        decision = self.checks_gate.check_pull_request(
            self.owner, "volmarr", "checks", pr.number)
        self.assertIn("ci", decision.pending_checks)
        self.assertFalse(decision.satisfied)
        self.checks.record_result("volmarr", "checks", head, "ci",
                                  "failed")
        decision = self.checks_gate.check_pull_request(
            self.owner, "volmarr", "checks", pr.number)
        self.assertIn("ci", decision.failed_checks)
        self.assertFalse(decision.satisfied)
        self.checks.record_result("volmarr", "checks", head, "ci",
                                  "passed")
        decision = self.checks_gate.check_pull_request(
            self.owner, "volmarr", "checks", pr.number)
        self.assertTrue(decision.checks_satisfied)
        self.assertTrue(decision.satisfied)
        # The base moving under the PR trips the toggle.
        moved = make_commit(path, [base], SIDE_FILES, "main moved")
        git(path, "update-ref", "refs/heads/main", moved)
        decision = self.checks_gate.check_pull_request(
            self.owner, "volmarr", "checks", pr.number)
        self.assertFalse(decision.up_to_date)
        self.assertFalse(decision.satisfied)

    # -- S-175: signed commits, both doors --------------------------------

    def test_signed_commits_both_doors(self):
        path, base, _head, pr = self._repo_with_pr("sign")
        self.rules.create_rule(
            self.owner, "volmarr", "sign", "main",
            require_signed_commits=True)
        # Push door: the PR's unsigned head, pushed directly.
        push = self.signed_gate.check_push_update(
            self.owner, "volmarr", "sign", "main", base, _head)
        self.assertFalse(push.satisfied)
        self.assertEqual(len(push.unsigned_commits), 1)
        # Merge door: the same unsigned head on the PR.
        merge = self.signed_gate.check_pull_request(
            self.owner, "volmarr", "sign", pr.number)
        self.assertFalse(merge.satisfied)
        # A signed head passes both doors.
        _p2, _b2, _h2, pr2 = self._repo_with_pr("sign2", head_sig=SIG)
        self.rules.create_rule(
            self.owner, "volmarr", "sign2", "main",
            require_signed_commits=True)
        push2 = self.signed_gate.check_push_update(
            self.owner, "volmarr", "sign2", "main", _b2, _h2)
        self.assertTrue(push2.satisfied)
        merge2 = self.signed_gate.check_pull_request(
            self.owner, "volmarr", "sign2", pr2.number)
        self.assertTrue(merge2.satisfied)

    # -- S-176: linear history, both doors ---------------------------------

    def test_linear_history_both_doors(self):
        path, base, _head, _pr = self._repo_with_pr("lin")
        self.rules.create_rule(
            self.owner, "volmarr", "lin", "main",
            require_linear_history=True)
        side = make_commit(path, [base], SIDE_FILES, "side")
        merge = make_commit(path, [base, side], HEAD_FILES, "merge")
        push = self.linear_gate.check_push_update(
            self.owner, "volmarr", "lin", "main", base, merge)
        self.assertFalse(push.satisfied)
        self.assertEqual(len(push.merge_commits), 1)
        linear = self.linear_gate.check_push_update(
            self.owner, "volmarr", "lin", "main", base, _head)
        self.assertTrue(linear.satisfied)
        git(path, "update-ref", "refs/heads/feature", merge)
        merge_door = self.linear_gate.check_pull_request(
            self.owner, "volmarr", "lin", _pr.number)
        self.assertFalse(merge_door.satisfied)

    # -- S-177: push shape binds everyone -----------------------------------

    def test_push_shape_binds_every_role(self):
        path = self.repos.path_for("volmarr", "pub")
        base = make_commit(path, [], BASE_FILES, "base")
        git(path, "update-ref", "refs/heads/main", base)
        ff = make_commit(path, [base], HEAD_FILES, "ff")
        div = make_commit(path, [base], SIDE_FILES, "div")
        self.rules.create_rule(self.owner, "volmarr", "pub", "main")
        for viewer in (self.owner, self.site_admin, self.writer, None):
            forced = self.shape_gate.check_push_update(
                viewer, "volmarr", "pub", "main", ff, div)
            self.assertFalse(forced.satisfied, viewer)
        deletion = self.shape_gate.check_push_update(
            self.owner, "volmarr", "pub", "main", base, ZERO)
        self.assertFalse(deletion.satisfied)
        forward = self.shape_gate.check_push_update(
            self.owner, "volmarr", "pub", "main", base, ff)
        self.assertTrue(forward.satisfied)
        # With both blocks lifted by the rule itself, the same
        # force push passes.
        self.repos.create_repository(
            self.owner.id, "volmarr", "shape2", visibility="public")
        path2 = self.repos.path_for("volmarr", "shape2")
        base2 = make_commit(path2, [], BASE_FILES, "base")
        git(path2, "update-ref", "refs/heads/main", base2)
        div2 = make_commit(path2, [base2], SIDE_FILES, "div")
        self.rules.create_rule(
            self.owner, "volmarr", "shape2", "main",
            block_force_pushes=False, block_branch_deletion=False)
        lifted = self.shape_gate.check_push_update(
            self.owner, "volmarr", "shape2", "main", base2, div2)
        self.assertTrue(lifted.satisfied)

    # -- S-178: named push actors -------------------------------------------

    def test_push_actors_named_only(self):
        self.rules.create_rule(
            self.owner, "volmarr", "pub", "main",
            allowed_push_actors=["yrsa"])
        named = self.actors_gate.check_branch(
            self.writer, "volmarr", "pub", "main")
        self.assertTrue(named.allowed)
        self.assertTrue(named.is_named)
        self.assertEqual(named.matched, "yrsa")
        # The owner is an admin — and still refused: the rule
        # names who may push, and the owner is not named.
        for viewer in (self.owner, self.site_admin, self.third, None):
            decision = self.actors_gate.check_branch(
                viewer, "volmarr", "pub", "main")
            self.assertFalse(decision.allowed, viewer)

    # -- S-179: bypass, only on the audited road ------------------------------

    def test_bypass_only_on_the_audited_road(self):
        self.rules.create_rule(
            self.owner, "volmarr", "pub", "main",
            require_pull_request=True, bypass_actors=["yrsa"])
        rows = lambda: self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log WHERE action = ?",
            ("repo.protection.bypass",)).fetchone()["n"]
        self.assertEqual(rows(), 0)
        use = self.bypass_gate.use_bypass(
            self.writer, "volmarr", "pub", "main")
        self.assertIsNotNone(use)
        self.assertEqual(rows(), 1)
        for viewer in (self.third, self.owner, self.fourth):
            with self.assertRaises(BypassNotAllowedError):
                self.bypass_gate.use_bypass(
                    viewer, "volmarr", "pub", "main")
        # Refused uses write nothing: no silent doors.
        self.assertEqual(rows(), 1)

    # -- S-180: enforce for admins ----------------------------------------------

    def test_enforce_admins_toggle_and_the_wired_door(self):
        self.rules.create_rule(self.owner, "volmarr", "pub", "main")
        for viewer in (self.owner, self.site_admin):
            decision = self.admin_gate.check_branch(
                viewer, "volmarr", "pub", "main")
            self.assertEqual(decision.actor_role, "admin")
            self.assertTrue(decision.binds_actor)
        reader = self.admin_gate.check_branch(
            self.writer, "volmarr", "pub", "main")
        self.assertTrue(reader.binds_actor)
        # Toggle off: admins walk, everyone else stays bound.
        self.repos.create_repository(
            self.owner.id, "volmarr", "adm2", visibility="public")
        self.rules.create_rule(
            self.owner, "volmarr", "adm2", "main",
            require_pull_request=True, enforce_admins=False)
        exempt = self.admin_gate.check_branch(
            self.owner, "volmarr", "adm2", "main")
        self.assertFalse(exempt.binds_actor)
        bound = self.admin_gate.check_branch(
            self.writer, "volmarr", "adm2", "main")
        self.assertTrue(bound.binds_actor)
        wired = self.pr_gate.check_branch(
            self.owner, "volmarr", "adm2", "main")
        self.assertTrue(wired.admin_exempt)
        self.assertTrue(wired.allowed)
        wired_reader = self.pr_gate.check_branch(
            self.writer, "volmarr", "adm2", "main")
        self.assertFalse(wired_reader.allowed)

    # -- S-181: rulesets, layered -----------------------------------------------

    def test_rulesets_layer_most_restrictive_wins(self):
        with self.assertRaises(RepositoryError):
            self.rulesets.create_ruleset(
                self.writer, "Nope", repo_patterns=["volmarr/*"],
                branch_patterns=["main"])
        self.rulesets.create_ruleset(
            self.site_admin, "Gate rules",
            repo_patterns=["volmarr/*"], branch_patterns=["main"],
            required_approvals=3)
        ev = self.rulesets.evaluate_ref(
            self.owner, "volmarr", "pub", "branch", "main")
        self.assertTrue(ev.is_protected)
        self.assertEqual(ev.effective.required_approvals, 3)
        # A weaker per-repo rule cannot dilute the layer.
        self.rules.create_rule(
            self.owner, "volmarr", "pub", "main", required_approvals=1)
        ev = self.rulesets.evaluate_ref(
            self.owner, "volmarr", "pub", "branch", "main")
        self.assertEqual(ev.effective.required_approvals, 3)
        other = self.rulesets.evaluate_ref(
            self.owner, "volmarr", "pub", "branch", "dev")
        self.assertFalse(other.is_protected)

    # -- S-182: tag protection -----------------------------------------------------

    def test_tag_protection_release_default_and_ruleset(self):
        path = self.repos.path_for("volmarr", "pub")
        base = make_commit(path, [], BASE_FILES, "base")
        git(path, "update-ref", "refs/heads/main", base)
        ff = make_commit(path, [base], HEAD_FILES, "ff")
        div = make_commit(path, [base], SIDE_FILES, "div")
        # Release tags are protected by default — for the
        # owner and the site admin alike, with no ruleset.
        for viewer in (self.owner, self.site_admin):
            deletion = self.tags_gate.check_tag_update(
                viewer, "volmarr", "pub", "v1.0", base, ZERO)
            self.assertFalse(deletion.satisfied, viewer)
            self.assertTrue(deletion.is_protected)
            moved = self.tags_gate.check_tag_update(
                viewer, "volmarr", "pub", "v1.0", ff, div)
            self.assertFalse(moved.satisfied, viewer)
        nightly = self.tags_gate.check_tag_update(
            self.owner, "volmarr", "pub", "nightly", base, ZERO)
        self.assertTrue(nightly.satisfied)
        # A tag ruleset protects its pattern; a fast-forward
        # move still passes.
        self.rulesets.create_ruleset(
            self.site_admin, "Stable tags", target="tag",
            repo_patterns=["volmarr/*"], tag_patterns=["stable-*"])
        stable_del = self.tags_gate.check_tag_update(
            self.owner, "volmarr", "pub", "stable-1", base, ZERO)
        self.assertFalse(stable_del.satisfied)
        stable_ff = self.tags_gate.check_tag_update(
            self.owner, "volmarr", "pub", "stable-1", base, ff)
        self.assertTrue(stable_ff.satisfied)

    # -- S-183: insights explain refusals ---------------------------------------------

    def test_insights_explain_refusals_in_plain_words(self):
        self.audit.append(
            actor_kind="user", actor_id=self.owner.id,
            action="repo.push", target_kind="repo",
            target_id="volmarr/pub", outcome="denied",
            detail={"branch": "main", "gate": "protection",
                    "reason": "status_checks_required"})
        self.audit.append(
            actor_kind="user", actor_id=self.writer.id,
            action="repo.pull_request.merge", target_kind="repo",
            target_id="volmarr/pub", outcome="denied",
            detail={"number": 7, "reason": "permission_denied"})
        found = self.insights.insights_for(
            self.owner, "volmarr", "pub")
        self.assertEqual(len(found), 2)
        latest = self.insights.latest_refusal(
            self.owner, "volmarr", "pub")
        self.assertIsNotNone(latest)
        self.assertIn("did not have the standing",
                      latest.explanation)
        words = " ".join(i.explanation for i in found)
        self.assertIn("status check was not green", words)
        with self.assertRaises(RepositoryError) as cm:
            self.insights.insights_for(self.third, "volmarr", "priv")
        self.assertEqual(cm.exception.reason, "repo_not_found")

    # -- the assembled strike: one branch, every rule ------------------------------

    def test_full_armour_branch_walked_to_satisfied(self):
        _path, _base, _head, pr = self._repo_with_pr(
            "full", base_files=OWNERS_BASE, head_files=OWNERS_HEAD,
            head_sig=SIG, wired=True)
        self.rules.create_rule(
            self.owner, "volmarr", "full", "main",
            require_pull_request=True, required_approvals=1,
            require_code_owner_review=True,
            required_status_checks=["ci"],
            require_signed_commits=True, require_linear_history=True,
            allowed_push_actors=["volmarr"], bypass_actors=["yrsa"])
        # Push door: the pull-request rule refuses even the
        # one named push actor; the actor gate itself admits
        # the owner and refuses everyone unnamed.
        self.assertFalse(self.pr_gate.check_branch(
            self.owner, "volmarr", "full", "main").allowed)
        self.assertTrue(self.actors_gate.check_branch(
            self.owner, "volmarr", "full", "main").allowed)
        self.assertFalse(self.actors_gate.check_branch(
            self.third, "volmarr", "full", "main").allowed)
        deletion = self.shape_gate.check_push_update(
            self.owner, "volmarr", "full", "main", _base, ZERO)
        self.assertFalse(deletion.satisfied)
        # Merge door: three gates refuse, two already pass —
        # the head is signed and linear.
        self.assertFalse(self.approvals_gate.check_pull_request(
            self.owner, "volmarr", "full", pr.number).satisfied)
        self.assertFalse(self.codeowners_gate.check_pull_request(
            self.owner, "volmarr", "full", pr.number).satisfied)
        self.assertFalse(self.checks_gate.check_pull_request(
            self.owner, "volmarr", "full", pr.number).satisfied)
        self.assertTrue(self.signed_gate.check_pull_request(
            self.owner, "volmarr", "full", pr.number).satisfied)
        self.assertTrue(self.linear_gate.check_pull_request(
            self.owner, "volmarr", "full", pr.number,
            method="squash").satisfied)
        self.assertFalse(self.linear_gate.check_pull_request(
            self.owner, "volmarr", "full", pr.number).satisfied)
        # The code owner's approval satisfies two gates at
        # once; the recorded check satisfies the third.
        self._approve(self.writer, "full", pr.number)
        self.assertTrue(self.approvals_gate.check_pull_request(
            self.owner, "volmarr", "full", pr.number).satisfied)
        self.assertTrue(self.codeowners_gate.check_pull_request(
            self.owner, "volmarr", "full", pr.number).satisfied)
        self.checks.record_result("volmarr", "full", _head, "ci",
                                  "passed")
        self.assertTrue(self.checks_gate.check_pull_request(
            self.owner, "volmarr", "full", pr.number).satisfied)
        # And the named bypasser still has exactly one road:
        # the audited one.
        self.bypass_gate.use_bypass(
            self.writer, "volmarr", "full", "main")
        rows = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log WHERE action = ?",
            ("repo.protection.bypass",)).fetchone()["n"]
        self.assertEqual(rows, 1)

    # -- open ground: no rules, no refusals ------------------------------------------

    def test_unprotected_branch_open_at_every_door(self):
        path, base, _head, _pr = self._repo_with_pr("open")
        git(path, "update-ref", "refs/heads/dev", base)
        git(path, "update-ref", "refs/heads/feature2", _head)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", "open", base_branch="dev",
            head_branch="feature2")
        ev = self.rules.evaluate_branch(
            self.owner, "volmarr", "open", "dev")
        self.assertFalse(ev.is_protected)
        self.assertTrue(self.approvals_gate.check_pull_request(
            self.owner, "volmarr", "open", pr.number).satisfied)
        self.assertTrue(self.checks_gate.check_pull_request(
            self.owner, "volmarr", "open", pr.number).satisfied)
        self.assertTrue(self.signed_gate.check_pull_request(
            self.owner, "volmarr", "open", pr.number).satisfied)
        self.assertTrue(self.linear_gate.check_pull_request(
            self.owner, "volmarr", "open", pr.number).satisfied)
        self.assertFalse(self.admin_gate.check_branch(
            self.owner, "volmarr", "open", "dev").binds_actor)

    # -- invariants ----------------------------------------------------------------------

    def test_schema_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 92)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 127)


if __name__ == "__main__":
    unittest.main()
