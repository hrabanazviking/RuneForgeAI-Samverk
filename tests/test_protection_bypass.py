"""S-179 acceptance battery: bypass list.

Acceptance (roadmap S-179): named bypassers per rule;
every bypass is audit-logged and shown on the rule
(no silent doors).

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog, verify_chain
from samverk.db import schema_version
from samverk.protection_bypass import (
    BYPASS_AUDIT_REQUIRED, BYPASS_EVENT, BYPASS_NOT_ALLOWED,
    BypassError, BypassNotAllowedError, BypassProtectionStore,
    actor_may_bypass, decide_bypass, render_bypass_decision,
    render_bypass_use, render_rule_bypass, rule_bypass_words)
from samverk.protection_push_actors import PushActorProtectionStore
from samverk.protection_rules import (
    ProtectionRuleError, ProtectionRuleStore, evaluate_rules,
    ProtectionRule, ProtectionSettings)
from samverk.repositories import RepositoryStore


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


class BypassProtectionTests(unittest.TestCase):
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
        self.other = self.accounts.register(
            "tess", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.rules = ProtectionRuleStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.gate = BypassProtectionStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")

    # -- helpers ---------------------------------------------------------
    def _rule(self, pattern="main", repo="pub",
              bypass=("volmarr",), **fields):
        fields.setdefault("bypass_actors", list(bypass))
        return self.rules.create_rule(
            self.owner, "volmarr", repo, pattern, **fields)

    def _check(self, branch="main", repo="pub", viewer=None, **kw):
        if viewer is None and "actor" not in kw:
            viewer = self.owner
        return self.gate.check_branch(
            viewer, "volmarr", repo, branch, **kw)

    def _bypass_rows(self):
        return self.conn.execute(
            "SELECT actor_id, target_id, detail FROM audit_log "
            "WHERE action = ? ORDER BY seq", (BYPASS_EVENT,)).fetchall()

    # -- the core judgment -------------------------------------------------
    def test_named_user_may_bypass(self):
        self._rule("main", bypass=("volmarr", "yrsa"))
        decision = self._check("main")
        self.assertTrue(decision.may_bypass)
        self.assertTrue(decision.protected)
        self.assertEqual(decision.matched, "volmarr")
        self.assertEqual(decision.bypass_actors, ("volmarr", "yrsa"))
        self.assertEqual(decision.reason, "")
        self.assertIn("may bypass", decision.words)
        self.assertIn("audit-logged", decision.words)
        by_writer = self.gate.check_branch(
            self.writer, "volmarr", "pub", "main")
        self.assertTrue(by_writer.may_bypass)

    def test_unnamed_user_may_not_bypass(self):
        self._rule("main", bypass=("volmarr",))
        decision = self.gate.check_branch(
            self.writer, "volmarr", "pub", "main")
        self.assertFalse(decision.may_bypass)
        self.assertIsNone(decision.matched)
        self.assertIn("'main'", decision.reason)
        self.assertIn("volmarr/pub", decision.reason)
        self.assertIn("'yrsa' is not among", decision.reason)
        self.assertIn("may not bypass", decision.words)

    def test_anonymous_bypasses_nothing(self):
        self._rule("main", bypass=("volmarr",))
        decision = self.gate.check_branch(
            None, "volmarr", "pub", "main")
        self.assertFalse(decision.may_bypass)
        self.assertIn("an anonymous actor", decision.reason)

    def test_names_compare_case_insensitively(self):
        self._rule("main", bypass=("Volmarr",))
        decision = self._check("main", actor="VOLMARR")
        self.assertTrue(decision.may_bypass)
        self.assertEqual(decision.matched, "Volmarr")
        self.assertTrue(actor_may_bypass(("yrsa",), "YRSA"))

    def test_team_entry_names_stated_members(self):
        self._rule("main", bypass=("volmarr/forge-wardens",))
        full = self._check(
            "main", actor="yrsa",
            actor_teams=("volmarr/forge-wardens",))
        self.assertTrue(full.may_bypass)
        self.assertEqual(full.matched, "volmarr/forge-wardens")
        bare = self._check(
            "main", actor="yrsa", actor_teams=("forge-wardens",))
        self.assertTrue(bare.may_bypass)
        self.assertIn("named team", bare.words)

    def test_other_owners_same_named_team_names_nothing(self):
        self._rule("main", bypass=("volmarr/forge-wardens",))
        decision = self._check(
            "main", actor="yrsa",
            actor_teams=("tess/forge-wardens",))
        self.assertFalse(decision.may_bypass)

    def test_unprotected_branch_needs_no_bypass(self):
        decision = self.gate.check_branch(
            self.other, "volmarr", "pub", "feature")
        self.assertFalse(decision.protected)
        self.assertFalse(decision.may_bypass)
        self.assertEqual(decision.bypass_actors, ())
        self.assertIn("not protected", decision.words)
        self.assertEqual(decision.reason, "")

    def test_empty_bypass_list_closes_the_door(self):
        self._rule("main", bypass=("volmarr",))
        self._rule("m*", bypass=())
        decision = self._check("main")
        self.assertTrue(decision.protected)
        self.assertEqual(decision.bypass_actors, ())
        self.assertFalse(decision.may_bypass)
        self.assertIn("no silent", decision.words)
        self.assertIn("closes", decision.reason)

    def test_bypass_folds_as_intersection(self):
        self._rule("main", bypass=("volmarr", "yrsa"))
        self._rule("m*", bypass=("yrsa", "tess"))
        decision = self._check("main")
        self.assertEqual(decision.bypass_actors, ("yrsa",))
        self.assertFalse(decision.may_bypass)
        by_writer = self.gate.check_branch(
            self.writer, "volmarr", "pub", "main")
        self.assertTrue(by_writer.may_bypass)

    # -- the audited use -----------------------------------------------------
    def test_use_bypass_writes_the_audit_row(self):
        rule = self._rule("main", bypass=("volmarr",))
        use = self.gate.use_bypass(
            self.owner, "volmarr", "pub", "main", gate="force push")
        self.assertTrue(use.decision.may_bypass)
        self.assertEqual(use.gate, "force push")
        rows = self._bypass_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["actor_id"], self.owner.id)
        self.assertEqual(rows[0]["target_id"], "volmarr/pub")
        detail = json.loads(rows[0]["detail"])
        self.assertEqual(detail["branch"], "main")
        self.assertEqual(detail["patterns"], ["main"])
        self.assertEqual(detail["rule_ids"], [rule.id])
        self.assertEqual(detail["bypass_entry"], "volmarr")
        self.assertEqual(detail["gate"], "force push")
        self.assertEqual(detail["actor"], "volmarr")
        ok, bad, _count = verify_chain(self.conn)
        self.assertTrue(ok, bad)
        self.assertIn("audit-logged", use.words)
        self.assertIn(str(use.audit_seq), use.words)

    def test_use_bypass_for_another_named_account(self):
        self._rule("main", bypass=("yrsa",))
        use = self.gate.use_bypass(
            self.owner, "volmarr", "pub", "main", actor="yrsa")
        self.assertEqual(use.decision.actor, "yrsa")
        rows = self._bypass_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["actor_id"], self.writer.id)

    def test_refused_use_writes_nothing(self):
        self._rule("main", bypass=("volmarr",))
        with self.assertRaises(BypassNotAllowedError) as cm:
            self.gate.use_bypass(
                self.writer, "volmarr", "pub", "main")
        self.assertEqual(cm.exception.reason, BYPASS_NOT_ALLOWED)
        self.assertEqual(self._bypass_rows(), [])

    def test_use_without_audit_log_fails_closed(self):
        self._rule("main", bypass=("volmarr",))
        bare = BypassProtectionStore(
            self.conn, self.repos, self.accounts,
            audit=None, time_fn=self.clock)
        self.assertTrue(bare.check_branch(
            self.owner, "volmarr", "pub", "main").may_bypass)
        with self.assertRaises(BypassError) as cm:
            bare.use_bypass(self.owner, "volmarr", "pub", "main")
        self.assertEqual(cm.exception.reason, BYPASS_AUDIT_REQUIRED)
        self.assertEqual(self._bypass_rows(), [])

    def test_named_but_unknown_account_is_refused(self):
        self._rule("main", bypass=("ghost",))
        with self.assertRaises(BypassNotAllowedError) as cm:
            self.gate.use_bypass(
                self.owner, "volmarr", "pub", "main", actor="ghost")
        self.assertEqual(cm.exception.reason, BYPASS_NOT_ALLOWED)
        self.assertEqual(self._bypass_rows(), [])

    def test_check_is_a_pure_read(self):
        self._rule("main", bypass=("volmarr",))
        before = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        self._check("main")
        after = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        # Only the rule-change row from _rule stands; the check
        # itself added nothing.
        self.assertEqual(after, before)

    def test_existing_gates_still_refuse_a_bypass_name(self):
        # No silent door: S-178's plain check does not exempt a
        # bypass-named pusher; only S-179's audited road does.
        self._rule("main", bypass=("yrsa",),
                   allowed_push_actors=("volmarr",))
        actors = PushActorProtectionStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        decision = actors.check_branch(
            self.writer, "volmarr", "pub", "main")
        self.assertFalse(decision.allowed)

    # -- shown on the rule ---------------------------------------------------
    def test_rule_bypass_words_show_the_names(self):
        rule = self._rule("main", bypass=("volmarr", "yrsa"))
        words = rule_bypass_words(rule)
        self.assertIn("'main'", words)
        self.assertIn("volmarr, yrsa", words)
        self.assertIn("audit-logged", words)
        rendered = render_rule_bypass(rule)
        self.assertIn("volmarr, yrsa", rendered)
        self.assertIn('class="protection-rule-bypass"', rendered)

    def test_rule_bypass_words_show_an_empty_list(self):
        rule = self._rule("main", bypass=())
        words = rule_bypass_words(rule)
        self.assertIn("names no bypassers", words)
        self.assertIn("no silent door", words)

    def test_renderers_escape_and_say_the_words(self):
        self._rule("main", bypass=("volmarr",))
        decision = self._check("main")
        rendered = render_bypass_decision(decision)
        self.assertIn(decision.words, rendered)
        use = self.gate.use_bypass(
            self.owner, "volmarr", "pub", "main")
        rendered_use = render_bypass_use(use)
        self.assertIn(BYPASS_EVENT, rendered_use)
        self.assertIn('class="protection-bypass-use"', rendered_use)

    # -- guards and shape ------------------------------------------------------
    def test_private_repo_stranger_gets_repo_not_found(self):
        self._rule("main", repo="priv", bypass=("volmarr",))
        with self.assertRaises(ProtectionRuleError) as cm:
            self.gate.check_branch(
                self.other, "volmarr", "priv", "main")
        self.assertEqual(cm.exception.reason, "repo_not_found")

    def test_pure_decide_bypass_from_an_evaluation(self):
        settings = ProtectionSettings(bypass_actors=("yrsa",))
        rule = ProtectionRule(
            id=7, repo_id=1, full_name="volmarr/pub", pattern="main",
            settings=settings, created_by=None,
            created_at=1, updated_at=1)
        evaluation = evaluate_rules([rule], "main",
                                    full_name="volmarr/pub")
        decision = decide_bypass(evaluation, "yrsa")
        self.assertTrue(decision.may_bypass)
        refused = decide_bypass(evaluation, "tess")
        self.assertFalse(refused.may_bypass)
        self.assertIn("volmarr/pub", refused.reason)

    def test_invalid_shapes_are_refused_whole(self):
        evaluation = evaluate_rules([], "main",
                                    full_name="volmarr/pub")
        with self.assertRaises(BypassError) as cm:
            decide_bypass(evaluation, 42)
        self.assertEqual(cm.exception.reason, "bypass_check_invalid")
        with self.assertRaises(BypassError):
            decide_bypass(evaluation, "yrsa", actor_teams="forge")
        with self.assertRaises(BypassError):
            decide_bypass(evaluation, "yrsa", actor_teams=("",))
        with self.assertRaises(BypassError):
            self.gate.use_bypass(
                self.owner, "volmarr", "pub", "main", gate=" ")

    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 108)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)
        self.assertIn(BYPASS_EVENT, taxonomy.AUDIT_EVENTS)
        self.assertTrue(taxonomy.is_known_event(BYPASS_EVENT))


if __name__ == "__main__":
    unittest.main()
