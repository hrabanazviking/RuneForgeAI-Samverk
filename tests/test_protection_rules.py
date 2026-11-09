"""S-169 acceptance battery: protection rule model.

Acceptance (roadmap S-169): protection rule model —
rules attach to branch-name patterns per repo;
evaluation order is documented and deterministic.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import json, random, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog, verify_chain
from samverk.db import schema_version
from samverk.protection_rules import (
    ProtectionRule, ProtectionRuleError, ProtectionRuleStore,
    ProtectionSettings, evaluate_rules, matches_pattern, order_rules,
    render_protection_evaluation, render_protection_rule,
    validate_pattern)
from samverk.repositories import RepositoryStore


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


def bare_rule(rule_id, pattern, **settings):
    return ProtectionRule(
        id=rule_id, repo_id=1, full_name="volmarr/pub",
        pattern=pattern, settings=ProtectionSettings(**settings),
        created_by=None, created_at=0, updated_at=0)


class ProtectionRuleTests(unittest.TestCase):
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
        self.store = ProtectionRuleStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")

    # -- helpers ---------------------------------------------------------
    def _audit_rows(self, action="repo.protection.change"):
        return self.conn.execute(
            "SELECT detail FROM audit_log WHERE action = ? ORDER BY seq",
            (action,)).fetchall()

    def _create(self, pattern="main", repo="pub", **fields):
        return self.store.create_rule(
            self.owner, "volmarr", repo, pattern, **fields)

    # -- creation ----------------------------------------------------------
    def test_create_defaults_and_words(self):
        rule = self._create("main")
        self.assertEqual(rule.pattern, "main")
        self.assertEqual(rule.full_name, "volmarr/pub")
        self.assertEqual(rule.created_by, self.owner.id)
        s = rule.settings
        self.assertTrue(s.enabled)
        self.assertFalse(s.require_pull_request)
        self.assertEqual(s.required_approvals, 0)
        self.assertEqual(s.required_status_checks, ())
        self.assertTrue(s.block_force_pushes)
        self.assertTrue(s.block_branch_deletion)
        self.assertTrue(s.enforce_admins)
        self.assertIn("'main'", rule.words)
        self.assertIn("force pushes are blocked", rule.words)
        self.assertIn("enforced for admins", rule.words)
        rows = self._audit_rows()
        self.assertEqual(len(rows), 1)
        detail = json.loads(rows[0]["detail"])
        self.assertEqual(detail["branch"], "main")
        self.assertEqual(detail["rule"], "create")
        self.assertEqual(detail["rule_id"], rule.id)

    def test_create_with_full_settings_round_trips(self):
        rule = self._create(
            "release/*", require_pull_request=True, required_approvals=2,
            dismiss_stale_reviews=True, require_code_owner_review=True,
            required_status_checks=["ci", "lint", "ci"],
            require_branch_up_to_date=True, require_signed_commits=True,
            require_linear_history=True, block_force_pushes=False,
            allowed_push_actors=["volmarr"], bypass_actors=["volmarr"])
        again = self.store.get_rule(self.owner, "volmarr", "pub", rule.id)
        s = again.settings
        self.assertTrue(s.require_pull_request)
        self.assertEqual(s.required_approvals, 2)
        self.assertTrue(s.dismiss_stale_reviews)
        self.assertTrue(s.require_code_owner_review)
        self.assertEqual(s.required_status_checks, ("ci", "lint"))
        self.assertTrue(s.require_branch_up_to_date)
        self.assertTrue(s.require_signed_commits)
        self.assertTrue(s.require_linear_history)
        self.assertFalse(s.block_force_pushes)
        self.assertEqual(s.allowed_push_actors, ("volmarr",))
        self.assertEqual(s.bypass_actors, ("volmarr",))
        self.assertIn("2 approvals are required", again.words)

    def test_create_with_settings_object(self):
        shape = ProtectionSettings(require_pull_request=True)
        rule = self.store.create_rule(
            self.owner, "volmarr", "pub", "dev", settings=shape)
        self.assertTrue(rule.settings.require_pull_request)
        with self.assertRaises(ProtectionRuleError) as cm:
            self.store.create_rule(
                self.owner, "volmarr", "pub", "dev2", settings=shape,
                required_approvals=1)
        self.assertEqual(cm.exception.reason, "protection_rule_invalid")

    def test_duplicate_pattern_refused_and_stores_nothing(self):
        self._create("main")
        with self.assertRaises(ProtectionRuleError) as cm:
            self._create("main", required_approvals=3)
        self.assertEqual(cm.exception.reason, "protection_rule_taken")
        self.assertEqual(len(self.store.list_rules(
            self.owner, "volmarr", "pub")), 1)
        self.assertEqual(len(self._audit_rows()), 1)

    def test_same_pattern_in_another_repo_is_a_different_rule(self):
        a = self._create("main", repo="pub")
        b = self._create("main", repo="priv")
        self.assertNotEqual(a.id, b.id)
        self.assertEqual(b.full_name, "volmarr/priv")

    # -- pattern law ---------------------------------------------------------
    def test_pattern_validation(self):
        for bad in ("", "  ", "*", "**", "???", "foo//bar", "../x",
                    "/main", "main/", "a b", "re[", "re]", "x@{y",
                    "x" * 201, 42, None, "main.lock", "release/"):
            with self.assertRaises(ProtectionRuleError) as cm:
                validate_pattern(bad)
            self.assertEqual(
                cm.exception.reason, "protection_pattern_invalid", bad)
        for good in ("main", "release/*", "release/**", "feat-?",
                     "v[0-9]*", "release/1.0", "hotfix-*"):
            self.assertEqual(validate_pattern(good), good)

    def test_matches_pattern_matrix(self):
        cases = [
            ("main", "main", True), ("main", "main2", False),
            ("release/*", "release/1.0", True),
            ("release/*", "release/a/b", False),
            ("release/*", "release/", True),
            ("release/**", "release/a/b", True),
            ("release/**", "release/1.0", True),
            ("feat-?", "feat-a", True), ("feat-?", "feat-ab", False),
            ("feat-?", "feat-/", False),
            ("v[0-9]*", "v2x", True), ("v[0-9]*", "vx", False),
            ("**", "any/thing", True), ("*", "any/thing", False),
            ("*", "plain", True),
        ]
        for pattern, branch, expected in cases:
            self.assertEqual(matches_pattern(pattern, branch), expected,
                             (pattern, branch))

    def test_settings_validation(self):
        for fields in ({"required_approvals": -1},
                       {"required_approvals": True},
                       {"required_approvals": "2"},
                       {"require_pull_request": "yes"},
                       {"required_status_checks": ["ci", ""]},
                       {"required_status_checks": "ci"},
                       {"allowed_push_actors": ["not a name"]},
                       {"bypass_actors": ["@" ]},
                       {"nonsense_field": True}):
            with self.assertRaises(ProtectionRuleError) as cm:
                self._create("main", **fields)
            self.assertEqual(
                cm.exception.reason, "protection_rule_invalid", fields)
        self.assertEqual(self.store.list_rules(
            self.owner, "volmarr", "pub"), [])
        self.assertEqual(self._audit_rows(), [])

    # -- update and delete ---------------------------------------------------
    def test_update_fields_noop_and_pattern_rename(self):
        rule = self._create("main")
        self.clock.now += 60
        updated = self.store.update_rule(
            self.owner, "volmarr", "pub", rule.id, required_approvals=2)
        self.assertEqual(updated.settings.required_approvals, 2)
        self.assertEqual(updated.updated_at, self.clock.now)
        self.assertEqual(len(self._audit_rows()), 2)
        # A same-value retry is a quiet no-op (S-149 pattern).
        self.clock.now += 60
        again = self.store.update_rule(
            self.owner, "volmarr", "pub", rule.id, required_approvals=2)
        self.assertEqual(again.updated_at, updated.updated_at)
        self.assertEqual(len(self._audit_rows()), 2)
        renamed = self.store.update_rule(
            self.owner, "volmarr", "pub", rule.id, pattern="trunk")
        self.assertEqual(renamed.pattern, "trunk")
        detail = json.loads(self._audit_rows()[-1]["detail"])
        self.assertEqual(detail["rule"], "update")
        self.assertEqual(detail["branch"], "trunk")

    def test_update_rename_onto_existing_pattern_refused(self):
        self._create("main")
        other = self._create("dev")
        with self.assertRaises(ProtectionRuleError) as cm:
            self.store.update_rule(
                self.owner, "volmarr", "pub", other.id, pattern="main")
        self.assertEqual(cm.exception.reason, "protection_rule_taken")
        self.assertEqual(self.store.get_rule(
            self.owner, "volmarr", "pub", other.id).pattern, "dev")

    def test_update_whole_settings_and_unknown_field(self):
        rule = self._create("main", required_approvals=1)
        updated = self.store.update_rule(
            self.owner, "volmarr", "pub", rule.id,
            settings=ProtectionSettings(require_signed_commits=True))
        self.assertTrue(updated.settings.require_signed_commits)
        self.assertEqual(updated.settings.required_approvals, 0)
        with self.assertRaises(ProtectionRuleError) as cm:
            self.store.update_rule(
                self.owner, "volmarr", "pub", rule.id, bogus=True)
        self.assertEqual(cm.exception.reason, "protection_rule_invalid")
        with self.assertRaises(ProtectionRuleError) as cm:
            self.store.update_rule(
                self.owner, "volmarr", "pub", 9999, required_approvals=1)
        self.assertEqual(cm.exception.reason, "protection_rule_not_found")

    def test_delete_rule(self):
        rule = self._create("main")
        deleted = self.store.delete_rule(
            self.owner, "volmarr", "pub", rule.id)
        self.assertEqual(deleted.pattern, "main")
        with self.assertRaises(ProtectionRuleError) as cm:
            self.store.get_rule(self.owner, "volmarr", "pub", rule.id)
        self.assertEqual(cm.exception.reason, "protection_rule_not_found")
        detail = json.loads(self._audit_rows()[-1]["detail"])
        self.assertEqual(detail["rule"], "delete")
        with self.assertRaises(ProtectionRuleError):
            self.store.delete_rule(self.owner, "volmarr", "pub", rule.id)

    def test_list_rules_creation_order_and_get_by_pattern(self):
        self._create("zeta*")
        self._create("main")
        self._create("release/*")
        listed = self.store.list_rules(self.reader, "volmarr", "pub")
        self.assertEqual([r.pattern for r in listed],
                         ["zeta*", "main", "release/*"])
        found = self.store.get_rule_by_pattern(
            self.reader, "volmarr", "pub", "main")
        self.assertEqual(found.pattern, "main")
        with self.assertRaises(ProtectionRuleError) as cm:
            self.store.get_rule_by_pattern(
                self.reader, "volmarr", "pub", "nope")
        self.assertEqual(cm.exception.reason, "protection_rule_not_found")

    # -- permissions -----------------------------------------------------------
    def test_writes_are_admin_only(self):
        with self.assertRaises(ProtectionRuleError) as cm:
            self.store.create_rule(self.reader, "volmarr", "pub", "main")
        self.assertEqual(cm.exception.reason, "permission_denied")
        rule = self._create("main")
        with self.assertRaises(ProtectionRuleError) as cm:
            self.store.update_rule(
                self.reader, "volmarr", "pub", rule.id,
                required_approvals=9)
        self.assertEqual(cm.exception.reason, "permission_denied")
        with self.assertRaises(ProtectionRuleError) as cm:
            self.store.delete_rule(self.reader, "volmarr", "pub", rule.id)
        self.assertEqual(cm.exception.reason, "permission_denied")
        self.assertEqual(len(self._audit_rows()), 1)

    def test_private_repo_is_uniform_not_found_for_strangers(self):
        rule = self._create("main", repo="priv")
        for call in (
                lambda: self.store.list_rules(self.reader, "volmarr", "priv"),
                lambda: self.store.get_rule(
                    self.reader, "volmarr", "priv", rule.id),
                lambda: self.store.evaluate_branch(
                    self.reader, "volmarr", "priv", "main"),
                lambda: self.store.list_rules(None, "volmarr", "priv")):
            with self.assertRaises(ProtectionRuleError) as cm:
                call()
            self.assertEqual(cm.exception.reason, "repo_not_found")
        self.assertEqual(len(self.store.list_rules(
            self.owner, "volmarr", "priv")), 1)
        # A stranger's write attempt on a private repo is also
        # the uniform not-found, never a permission answer.
        with self.assertRaises(ProtectionRuleError) as cm:
            self.store.create_rule(self.reader, "volmarr", "priv", "dev")
        self.assertEqual(cm.exception.reason, "repo_not_found")

    # -- evaluation order -------------------------------------------------------
    def test_evaluation_order_is_documented_and_deterministic(self):
        rules = [
            bare_rule(5, "release/1.0"),
            bare_rule(2, "release/*"),
            bare_rule(1, "release/**"),
            bare_rule(3, "re*"),
            bare_rule(4, "**"),
            bare_rule(9, "release/*"),
        ]
        expected = ["release/1.0", "release/*", "release/*",
                    "release/**", "re*", "**"]
        expected_ids = [5, 2, 9, 1, 3, 4]
        self.assertEqual([r.pattern for r in order_rules(rules)], expected)
        self.assertEqual([r.id for r in order_rules(rules)], expected_ids)
        rng = random.Random(169)
        for _ in range(25):
            shuffled = list(rules)
            rng.shuffle(shuffled)
            self.assertEqual(
                [r.id for r in order_rules(shuffled)], expected_ids)

    def test_evaluate_folds_most_restrictive_wins(self):
        rules = [
            bare_rule(1, "main", required_approvals=1,
                      required_status_checks=("ci",),
                      bypass_actors=("volmarr", "yrsa")),
            bare_rule(2, "ma*", required_approvals=3,
                      require_pull_request=True,
                      required_status_checks=("ci", "lint"),
                      bypass_actors=("yrsa", "tess"),
                      allowed_push_actors=("volmarr", "yrsa")),
            bare_rule(3, "m*", allowed_push_actors=("yrsa", "tess"),
                      bypass_actors=("yrsa", "volmarr")),
        ]
        ev = evaluate_rules(rules, "main", full_name="volmarr/pub")
        self.assertTrue(ev.is_protected)
        self.assertEqual([r.pattern for r in ev.matching],
                         ["main", "ma*", "m*"])
        s = ev.effective.settings
        self.assertEqual(s.required_approvals, 3)
        self.assertTrue(s.require_pull_request)
        self.assertEqual(s.required_status_checks, ("ci", "lint"))
        self.assertEqual(s.bypass_actors, ("yrsa",))
        self.assertEqual(s.allowed_push_actors, ("yrsa",))
        self.assertEqual(ev.effective.rule_ids, (1, 2, 3))
        self.assertIn("'main'", ev.words)
        self.assertIn("3 approvals are required", ev.words)

    def test_evaluate_empty_bypass_list_closes_the_door(self):
        rules = [
            bare_rule(1, "main", bypass_actors=("volmarr",)),
            bare_rule(2, "ma*"),
        ]
        ev = evaluate_rules(rules, "main", full_name="volmarr/pub")
        self.assertEqual(ev.effective.settings.bypass_actors, ())

    def test_disabled_rule_never_matches(self):
        rule = self._create("main")
        self.assertTrue(self.store.is_protected(
            self.owner, "volmarr", "pub", "main"))
        self.store.update_rule(
            self.owner, "volmarr", "pub", rule.id, enabled=False)
        self.assertFalse(self.store.is_protected(
            self.owner, "volmarr", "pub", "main"))
        ev = self.store.evaluate_branch(self.owner, "volmarr", "pub", "main")
        self.assertFalse(ev.is_protected)
        self.assertIn("not protected", ev.words)
        listed = self.store.list_rules(self.owner, "volmarr", "pub")
        self.assertEqual(len(listed), 1)
        self.assertIn("disabled", listed[0].words)

    def test_store_evaluation_across_patterns(self):
        self._create("main", required_approvals=1)
        self._create("release/*", require_pull_request=True)
        ev = self.store.evaluate_branch(
            self.reader, "volmarr", "pub", "release/2.0")
        self.assertTrue(ev.is_protected)
        self.assertEqual([r.pattern for r in ev.matching], ["release/*"])
        self.assertTrue(ev.effective.settings.require_pull_request)
        matching = self.store.rules_for_branch(
            self.reader, "volmarr", "pub", "main")
        self.assertEqual([r.pattern for r in matching], ["main"])
        ev_none = self.store.evaluate_branch(
            self.reader, "volmarr", "pub", "dev")
        self.assertFalse(ev_none.is_protected)
        self.assertIsNone(ev_none.effective)
        self.assertEqual(ev_none.matching, ())

    def test_renderers_say_the_words(self):
        rule = self._create("main", required_approvals=1)
        html = render_protection_rule(rule)
        self.assertIn("1 approval is required", html)
        ev = self.store.evaluate_branch(self.owner, "volmarr", "pub", "main")
        html2 = render_protection_evaluation(ev)
        self.assertIn("evaluation order", html2)
        self.assertIn("'main'", html2)

    # -- invariants -------------------------------------------------------------
    def test_migration_67_and_taxonomy_120(self):
        self.assertEqual(schema_version(self.conn), 93)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 129)
        self.assertEqual(db.MIGRATIONS[-1][0], 93)
        row = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name='protection_rules'").fetchone()
        self.assertIsNotNone(row)

    def test_audit_chain_verifies_over_rule_changes(self):
        rule = self._create("main")
        self.store.update_rule(
            self.owner, "volmarr", "pub", rule.id, required_approvals=2)
        self.store.delete_rule(self.owner, "volmarr", "pub", rule.id)
        ok, bad, checked = verify_chain(self.conn)
        self.assertTrue(ok)
        self.assertIsNone(bad)
        self.assertGreaterEqual(checked, 3)


if __name__ == "__main__":
    unittest.main()
