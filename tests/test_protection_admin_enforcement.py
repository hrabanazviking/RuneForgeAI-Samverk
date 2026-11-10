"""S-180 acceptance battery: enforce for admins.

Acceptance (roadmap S-180): the enforce-for-admins
toggle — default ON for Samverk instances, so the
owner's rules bind the owner; when every matching
rule leaves it off, an admin alone is exempt.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.protection_admin_enforcement import (
    ADMIN_ENFORCEMENT_INVALID, AdminEnforcementError,
    AdminEnforcementStore, decide_admin_enforcement,
    render_admin_enforcement_decision)
from samverk.protection_pull_request import (
    PullRequestProtectionStore, PullRequestRequiredError)
from samverk.protection_rules import (
    ProtectionRule, ProtectionRuleStore, ProtectionSettings,
    evaluate_rules)
from samverk.repositories import RepositoryStore


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


def _rule(rid, pattern, full_name="volmarr/pub", **fields):
    return ProtectionRule(
        id=rid, repo_id=1, full_name=full_name, pattern=pattern,
        settings=ProtectionSettings(**fields),
        created_by=None, created_at=0, updated_at=0)


def _pure(rules, branch="main", role="admin"):
    return decide_admin_enforcement(
        evaluate_rules(rules, branch, full_name="volmarr/pub"),
        actor_role=role)


class PureAdminEnforcementTests(unittest.TestCase):
    def test_unprotected_branch_binds_and_exempts_nobody(self):
        d = _pure([], role="admin")
        self.assertFalse(d.is_protected)
        self.assertFalse(d.binds_actor)
        self.assertFalse(d.exempt)
        self.assertFalse(d.enforce_admins)
        self.assertIn("not protected", d.words)

    def test_default_rule_binds_admin(self):
        d = _pure([_rule(1, "main")], role="admin")
        self.assertTrue(d.is_protected)
        self.assertTrue(d.enforce_admins)
        self.assertTrue(d.is_admin)
        self.assertTrue(d.binds_actor)
        self.assertFalse(d.exempt)
        self.assertIn("binds this admin", d.words)
        self.assertIn("owner's rules bind the owner", d.words)

    def test_toggle_off_exempts_admin(self):
        d = _pure([_rule(1, "main", enforce_admins=False)], role="admin")
        self.assertTrue(d.is_protected)
        self.assertFalse(d.enforce_admins)
        self.assertTrue(d.exempt)
        self.assertFalse(d.binds_actor)
        self.assertIn("does not bind this admin", d.words)
        self.assertIn("Every other actor remains bound", d.words)

    def test_toggle_off_still_binds_non_admins(self):
        rules = [_rule(1, "main", enforce_admins=False)]
        for role in ("write", "read", None):
            d = _pure(rules, role=role)
            self.assertTrue(d.binds_actor, role)
            self.assertFalse(d.exempt, role)
            self.assertIn("does not hold admin standing", d.words)

    def test_any_matching_rule_on_binds_admin(self):
        rules = [_rule(1, "main", enforce_admins=False),
                 _rule(2, "m*", enforce_admins=True)]
        d = _pure(rules, role="admin")
        self.assertTrue(d.enforce_admins)
        self.assertTrue(d.binds_actor)
        self.assertFalse(d.exempt)

    def test_all_matching_rules_off_exempts_admin(self):
        rules = [_rule(1, "main", enforce_admins=False),
                 _rule(2, "m*", enforce_admins=False)]
        d = _pure(rules, role="admin")
        self.assertTrue(d.exempt)

    def test_disabled_rule_speaks_for_nothing(self):
        d = _pure([_rule(1, "main", enabled=False,
                         enforce_admins=False)], role="admin")
        self.assertFalse(d.is_protected)
        self.assertFalse(d.binds_actor)
        self.assertFalse(d.exempt)

    def test_non_matching_branch_is_unprotected(self):
        d = _pure([_rule(1, "release/*", enforce_admins=False)],
                  branch="main", role="admin")
        self.assertFalse(d.is_protected)

    def test_unknown_role_refused(self):
        with self.assertRaises(AdminEnforcementError) as cm:
            _pure([_rule(1, "main")], role="superuser")
        self.assertEqual(cm.exception.reason,
                         ADMIN_ENFORCEMENT_INVALID)

    def test_renderer_escapes_words(self):
        ev = evaluate_rules(
            [_rule(1, "main", full_name="a&b/pub")], "main",
            full_name="a&b/pub")
        html = render_admin_enforcement_decision(
            decide_admin_enforcement(ev, actor_role="admin"))
        self.assertIn("a&amp;b/pub", html)
        self.assertNotIn("a&b/pub", html)


class StoreAdminEnforcementTests(unittest.TestCase):
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
        self.reader = self.accounts.register(
            "yrsa", "correct horse battery")
        self.site_admin = self.accounts.register(
            "rooty", "correct horse battery")
        with self.conn:
            self.conn.execute(
                "UPDATE users SET is_admin = 1 WHERE id = ?",
                (self.site_admin.id,))
        self.site_admin = self.accounts.get_by_username("rooty")
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts)
        self.rules = ProtectionRuleStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.gate = AdminEnforcementStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.pr_gate = PullRequestProtectionStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")

    def _check(self, viewer, repo="pub", branch="main"):
        return self.gate.check_branch(viewer, "volmarr", repo, branch)

    def _audit_count(self):
        return self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]

    # -- the toggle at the store -------------------------------------
    def test_owner_bound_by_default(self):
        self.rules.create_rule(self.owner, "volmarr", "pub", "main")
        d = self._check(self.owner)
        self.assertEqual(d.actor_role, "admin")
        self.assertTrue(d.binds_actor)
        self.assertFalse(d.exempt)

    def test_owner_exempt_when_toggle_off(self):
        self.rules.create_rule(
            self.owner, "volmarr", "pub", "main",
            enforce_admins=False)
        d = self._check(self.owner)
        self.assertTrue(d.exempt)
        self.assertTrue(self.gate.exempt_actor(
            self.owner, "volmarr", "pub", "main"))
        self.assertFalse(self.gate.binds_actor(
            self.owner, "volmarr", "pub", "main"))

    def test_site_admin_shares_the_toggle(self):
        self.rules.create_rule(self.owner, "volmarr", "pub", "main")
        self.assertTrue(self._check(self.site_admin).binds_actor)
        rule = self.rules.list_rules(self.owner, "volmarr", "pub")[0]
        self.rules.update_rule(
            self.owner, "volmarr", "pub", rule.id,
            enforce_admins=False)
        self.assertTrue(self._check(self.site_admin).exempt)

    def test_reader_bound_even_when_toggle_off(self):
        self.rules.create_rule(
            self.owner, "volmarr", "pub", "main",
            enforce_admins=False)
        d = self._check(self.reader)
        self.assertEqual(d.actor_role, "read")
        self.assertTrue(d.binds_actor)
        self.assertFalse(d.exempt)

    def test_anonymous_bound_on_public_never_exempt(self):
        self.rules.create_rule(
            self.owner, "volmarr", "pub", "main",
            enforce_admins=False)
        d = self._check(None)
        self.assertEqual(d.actor_role, "read")
        self.assertTrue(d.binds_actor)
        self.assertFalse(d.exempt)

    def test_private_stranger_gets_repo_not_found(self):
        self.rules.create_rule(self.owner, "volmarr", "priv", "main")
        with self.assertRaises(Exception) as cm:
            self._check(self.reader, repo="priv")
        self.assertEqual(cm.exception.reason, "repo_not_found")
        with self.assertRaises(Exception) as cm:
            self._check(None, repo="priv")
        self.assertEqual(cm.exception.reason, "repo_not_found")

    def test_toggle_flip_changes_next_check_both_ways(self):
        rule = self.rules.create_rule(
            self.owner, "volmarr", "pub", "main")
        self.assertTrue(self._check(self.owner).binds_actor)
        self.rules.update_rule(
            self.owner, "volmarr", "pub", rule.id,
            enforce_admins=False)
        self.assertTrue(self._check(self.owner).exempt)
        self.rules.update_rule(
            self.owner, "volmarr", "pub", rule.id,
            enforce_admins=True)
        self.assertTrue(self._check(self.owner).binds_actor)

    def test_checks_write_and_audit_nothing(self):
        self.rules.create_rule(
            self.owner, "volmarr", "pub", "main",
            enforce_admins=False)
        before = self._audit_count()
        self._check(self.owner)
        self._check(self.reader)
        self.assertEqual(self._audit_count(), before)

    # -- the first door: S-170's direct-push check -------------------
    def _require_pr(self, **fields):
        return self.rules.create_rule(
            self.owner, "volmarr", "pub", "main",
            require_pull_request=True, **fields)

    def test_admin_direct_push_refused_by_default(self):
        self._require_pr()
        d = self.pr_gate.check_branch(
            self.owner, "volmarr", "pub", "main")
        self.assertFalse(d.allowed)
        with self.assertRaises(PullRequestRequiredError):
            self.pr_gate.enforce_branch(
                self.owner, "volmarr", "pub", "main")

    def test_admin_direct_push_allowed_when_toggle_off(self):
        self._require_pr(enforce_admins=False)
        d = self.pr_gate.check_branch(
            self.owner, "volmarr", "pub", "main")
        self.assertTrue(d.allowed)
        self.assertIn("admin", d.words)
        self.assertIn("exempt", d.words)
        got = self.pr_gate.enforce_branch(
            self.owner, "volmarr", "pub", "main")
        self.assertTrue(got.allowed)

    def test_non_admin_direct_push_still_refused_when_toggle_off(self):
        self._require_pr(enforce_admins=False)
        d = self.pr_gate.check_branch(
            self.reader, "volmarr", "pub", "main")
        self.assertFalse(d.allowed)
        with self.assertRaises(PullRequestRequiredError):
            self.pr_gate.enforce_branch(
                self.reader, "volmarr", "pub", "main")

    def test_site_admin_direct_push_follows_toggle(self):
        self._require_pr(enforce_admins=False)
        d = self.pr_gate.check_branch(
            self.site_admin, "volmarr", "pub", "main")
        self.assertTrue(d.allowed)

    # -- claims ---------------------------------------------------------
    def test_claims_no_migration_no_new_event(self):
        self.assertEqual(schema_version(self.conn), 99)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 131)


if __name__ == "__main__":
    unittest.main()
