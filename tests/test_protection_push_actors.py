"""S-178 acceptance battery: restrict who can push.

Acceptance (roadmap S-178): named users/teams only may
push matching branches directly (where direct push is
allowed at all).

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
from samverk.hooks import RefUpdate
from samverk.protection_push_actors import (
    PUSH_ACTOR_REQUIRED, PushActorProtectionStore,
    PushActorRequiredError, actor_is_named, decide_push_actor,
    render_push_actor_decision)
from samverk.protection_rules import (
    ProtectionRuleError, ProtectionRuleStore, evaluate_rules,
    ProtectionRule, ProtectionSettings)
from samverk.receive_gate import ReceiveGate
from samverk.repositories import RepositoryStore

ZERO = "0" * 40
ONE = "1" * 40
TWO = "2" * 40


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


class PushActorProtectionTests(unittest.TestCase):
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
        self.gate = PushActorProtectionStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")

    # -- helpers ---------------------------------------------------------
    def _restrict(self, pattern="main", repo="pub",
                  actors=("volmarr",), **fields):
        fields.setdefault("allowed_push_actors", list(actors))
        return self.rules.create_rule(
            self.owner, "volmarr", repo, pattern, **fields)

    def _check(self, branch="main", repo="pub", viewer=None, **kw):
        if viewer is None and "actor" not in kw:
            viewer = self.owner
        return self.gate.check_branch(
            viewer, "volmarr", repo, branch, **kw)

    # -- the core refusal --------------------------------------------------
    def test_named_user_may_push(self):
        self._restrict("main", actors=("volmarr", "yrsa"))
        decision = self._check("main")
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.restricted)
        self.assertTrue(decision.is_named)
        self.assertEqual(decision.matched, "volmarr")
        self.assertEqual(decision.reason, "")
        self.assertIn("is allowed", decision.words)
        self.assertIn("'volmarr' is named", decision.words)
        by_writer = self.gate.check_branch(
            self.writer, "volmarr", "pub", "main")
        self.assertTrue(by_writer.allowed)

    def test_unnamed_user_refused_with_reason(self):
        self._restrict("main", actors=("volmarr",))
        decision = self.gate.check_branch(
            self.writer, "volmarr", "pub", "main")
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.restricted)
        self.assertFalse(decision.is_named)
        self.assertIn("'main'", decision.reason)
        self.assertIn("volmarr/pub", decision.reason)
        self.assertIn("volmarr", decision.reason)
        self.assertIn("'yrsa' is not among them", decision.reason)
        self.assertIn("open a pull request", decision.reason)
        with self.assertRaises(PushActorRequiredError) as cm:
            self.gate.enforce_branch(
                self.writer, "volmarr", "pub", "main")
        self.assertEqual(cm.exception.reason, PUSH_ACTOR_REQUIRED)
        self.assertEqual(str(cm.exception), decision.reason)

    def test_unrestricted_branch_allows_anyone(self):
        decision = self.gate.check_branch(
            self.other, "volmarr", "pub", "feature")
        self.assertTrue(decision.allowed)
        self.assertFalse(decision.restricted)
        self.assertIn("is allowed", decision.words)
        self.assertIn("restricts who", decision.words)

    def test_rule_without_restriction_allows(self):
        self.rules.create_rule(self.owner, "volmarr", "pub", "main")
        decision = self.gate.check_branch(
            self.other, "volmarr", "pub", "main")
        self.assertTrue(decision.allowed)
        self.assertFalse(decision.restricted)

    def test_disabled_rule_allows(self):
        self._restrict("main", actors=("volmarr",), enabled=False)
        decision = self.gate.check_branch(
            self.other, "volmarr", "pub", "main")
        self.assertTrue(decision.allowed)

    def test_list_change_answers_in_both_directions(self):
        rule = self._restrict("main", actors=("volmarr",))
        self.assertFalse(self.gate.check_branch(
            self.writer, "volmarr", "pub", "main").allowed)
        self.rules.update_rule(
            self.owner, "volmarr", "pub", rule.id,
            allowed_push_actors=["volmarr", "yrsa"])
        self.assertTrue(self.gate.check_branch(
            self.writer, "volmarr", "pub", "main").allowed)
        self.rules.update_rule(
            self.owner, "volmarr", "pub", rule.id,
            allowed_push_actors=[])
        self.assertTrue(self.gate.check_branch(
            self.other, "volmarr", "pub", "main").allowed)

    def test_pattern_matched_branch_covered(self):
        self._restrict("release/*", actors=("volmarr",))
        self.assertFalse(self.gate.check_branch(
            self.writer, "volmarr", "pub", "release/1.0").allowed)
        self.assertTrue(self.gate.check_branch(
            self.writer, "volmarr", "pub", "main").allowed)
        decision = self.gate.check_branch(
            self.writer, "volmarr", "pub", "release/1.0")
        self.assertIn("'release/*'", decision.reason)

    def test_fold_is_the_intersection(self):
        self._restrict("main", actors=("volmarr", "yrsa"))
        self._restrict("m*", actors=("yrsa", "tess"))
        folded = self._check("main")
        self.assertEqual(folded.allowed_actors, ("yrsa",))
        self.assertTrue(self.gate.check_branch(
            self.writer, "volmarr", "pub", "main").allowed)
        self.assertFalse(self._check("main").allowed)
        self.assertFalse(self.gate.check_branch(
            self.other, "volmarr", "pub", "main").allowed)

    # -- teams --------------------------------------------------------------
    def test_named_team_member_may_push(self):
        self._restrict("main", actors=("volmarr/devs",))
        decision = self.gate.check_branch(
            self.other, "volmarr", "pub", "main",
            actor_teams=("volmarr/devs",))
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.matched, "volmarr/devs")
        self.assertIn("named team 'volmarr/devs'", decision.words)
        bare = self.gate.check_branch(
            self.other, "volmarr", "pub", "main",
            actor_teams=("devs",))
        self.assertTrue(bare.allowed)

    def test_team_membership_must_be_the_named_team(self):
        self._restrict("main", actors=("volmarr/devs",))
        self.assertFalse(self.gate.check_branch(
            self.other, "volmarr", "pub", "main").allowed)
        self.assertFalse(self.gate.check_branch(
            self.other, "volmarr", "pub", "main",
            actor_teams=("volmarr/ops",)).allowed)
        self.assertFalse(self.gate.check_branch(
            self.other, "volmarr", "pub", "main",
            actor_teams=("other/devs",)).allowed)

    def test_user_and_team_entries_together(self):
        self._restrict("main", actors=("yrsa", "volmarr/devs"))
        self.assertTrue(self.gate.check_branch(
            self.writer, "volmarr", "pub", "main").allowed)
        self.assertTrue(self.gate.check_branch(
            self.other, "volmarr", "pub", "main",
            actor_teams=("devs",)).allowed)
        self.assertFalse(self.gate.check_branch(
            self.other, "volmarr", "pub", "main").allowed)

    # -- nobody exempt, no side doors ----------------------------------------
    def test_owner_not_named_is_refused(self):
        self._restrict("main", actors=("yrsa",))
        decision = self._check("main")
        self.assertFalse(decision.allowed)
        self.assertIn("'volmarr' is not among them", decision.reason)

    def test_bypass_name_does_not_open_the_door_yet(self):
        self._restrict("main", actors=("yrsa",),
                       bypass_actors=["volmarr"])
        self.assertFalse(self._check("main").allowed)

    def test_anonymous_pusher_refused_when_restricted(self):
        self._restrict("main", actors=("volmarr",))
        decision = self.gate.check_branch(
            None, "volmarr", "pub", "main")
        self.assertFalse(decision.allowed)
        self.assertIsNone(decision.actor)
        self.assertIn("an anonymous pusher is not among them",
                      decision.reason)
        open_decision = self.gate.check_branch(
            None, "volmarr", "pub", "feature")
        self.assertTrue(open_decision.allowed)

    def test_names_compare_case_insensitively(self):
        self._restrict("main", actors=("Volmarr",))
        decision = self._check("main")
        self.assertTrue(decision.allowed)
        self.assertTrue(actor_is_named(("Volmarr",), "volmarr"))
        self.assertTrue(actor_is_named(
            ("volmarr/Devs",), "tess", ("devs",)))
        self.assertFalse(actor_is_named(("volmarr",), "yrsa"))

    # -- a whole push ---------------------------------------------------------
    def test_push_decisions_in_update_order(self):
        self._restrict("main", actors=("volmarr",))
        updates = (RefUpdate("refs/heads/feature", ZERO, ONE),
                   RefUpdate("refs/heads/main", ONE, TWO))
        decisions = self.gate.check_push(
            self.writer, "volmarr", "pub", updates)
        self.assertEqual(len(decisions), 2)
        self.assertTrue(decisions[0].allowed)
        self.assertFalse(decisions[1].allowed)
        with self.assertRaises(PushActorRequiredError) as cm:
            self.gate.enforce_push(
                self.writer, "volmarr", "pub", updates)
        self.assertIn("'main'", str(cm.exception))
        allowed = self.gate.enforce_push(
            self.owner, "volmarr", "pub", updates)
        self.assertTrue(all(d.allowed for d in allowed))

    def test_push_skips_non_branch_refs(self):
        self._restrict("main", actors=("volmarr",))
        updates = (RefUpdate("refs/heads/feature", ZERO, ONE),
                   RefUpdate("refs/tags/v1", ZERO, ONE))
        decisions = self.gate.enforce_push(
            self.writer, "volmarr", "pub", updates)
        self.assertEqual(len(decisions), 1)
        self.assertTrue(decisions[0].allowed)

    # -- the merge road ---------------------------------------------------------
    def test_via_pull_request_is_allowed_and_said(self):
        self._restrict("main", actors=("volmarr",))
        decision = self.gate.check_branch(
            self.writer, "volmarr", "pub", "main",
            via_pull_request=True)
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.restricted)
        self.assertIn("by pull request", decision.words)
        out = self.gate.enforce_branch(
            self.writer, "volmarr", "pub", "main",
            via_pull_request=True)
        self.assertTrue(out.allowed)

    # -- the receive gate plug-in -------------------------------------------------
    def test_receive_gate_plugin_refuses_unnamed_actor(self):
        self._restrict("main", actors=("volmarr",))
        gate = ReceiveGate()
        gate.register_protection(
            "restrict-push-actors", self.gate.receive_gate_plugin())
        result = gate.check(
            owner="volmarr", repo="pub", actor="yrsa",
            transport="ssh",
            updates=(RefUpdate("refs/heads/main", ZERO, ONE),))
        self.assertFalse(result.allowed)
        self.assertEqual(result.refused_stage, "protection")
        self.assertEqual(result.refused_by, "restrict-push-actors")
        self.assertIn("'yrsa' is not among them", result.reason)

    def test_receive_gate_plugin_allows_named_and_team(self):
        self._restrict("main", actors=("volmarr", "volmarr/devs"))
        gate = ReceiveGate()
        gate.register_protection(
            "restrict-push-actors", self.gate.receive_gate_plugin())
        named = gate.check(
            owner="volmarr", repo="pub", actor="volmarr",
            transport="ssh",
            updates=(RefUpdate("refs/heads/main", ZERO, ONE),))
        self.assertTrue(named.allowed)
        teamed = gate.check(
            owner="volmarr", repo="pub", actor="tess",
            transport="ssh",
            updates=(RefUpdate("refs/heads/main", ZERO, ONE),),
            payload={"actor_teams": ["volmarr/devs"]})
        self.assertTrue(teamed.allowed)
        landing = gate.check(
            owner="volmarr", repo="pub", actor="yrsa",
            transport="local",
            updates=(RefUpdate("refs/heads/main", ZERO, ONE),),
            payload={"via_pull_request": True})
        self.assertTrue(landing.allowed)

    def test_receive_gate_plugin_with_no_updates_judges_nothing(self):
        self._restrict("main", actors=("volmarr",))
        gate = ReceiveGate()
        gate.register_protection(
            "restrict-push-actors", self.gate.receive_gate_plugin())
        result = gate.check(owner="volmarr", repo="pub", actor="yrsa")
        self.assertTrue(result.allowed)

    # -- guards, purity, and invariants --------------------------------------------
    def test_private_repo_stranger_gets_uniform_not_found(self):
        self._restrict("main", repo="priv", actors=("volmarr",))
        with self.assertRaises(ProtectionRuleError) as cm:
            self.gate.check_branch(
                self.writer, "volmarr", "priv", "main")
        self.assertEqual(cm.exception.reason, "repo_not_found")

    def test_refusal_writes_and_audits_nothing(self):
        self._restrict("main", actors=("volmarr",))
        before = self.conn.execute(
            "SELECT COUNT(*) AS c FROM audit_log").fetchone()["c"]
        self.gate.check_branch(self.writer, "volmarr", "pub", "main")
        with self.assertRaises(PushActorRequiredError):
            self.gate.enforce_branch(
                self.writer, "volmarr", "pub", "main")
        after = self.conn.execute(
            "SELECT COUNT(*) AS c FROM audit_log").fetchone()["c"]
        self.assertEqual(before, after)

    def test_pure_half_and_invalid_inputs(self):
        rule = ProtectionRule(
            id=1, repo_id=1, full_name="volmarr/pub", pattern="main",
            settings=ProtectionSettings(
                allowed_push_actors=("volmarr", "volmarr/devs")),
            created_by=None, created_at=0, updated_at=0)
        evaluation = evaluate_rules(
            [rule], "main", full_name="volmarr/pub")
        self.assertTrue(decide_push_actor(evaluation, "volmarr").allowed)
        self.assertFalse(decide_push_actor(evaluation, "yrsa").allowed)
        self.assertTrue(decide_push_actor(
            evaluation, "tess", actor_teams=("devs",)).allowed)
        self.assertTrue(decide_push_actor(
            evaluation, "yrsa", via_pull_request=True).allowed)
        self.assertFalse(decide_push_actor(evaluation, None).allowed)
        with self.assertRaises(PushActorRequiredError) as cm:
            decide_push_actor(evaluation, "yrsa", via_pull_request="yes")
        self.assertEqual(cm.exception.reason, "push_check_invalid")
        with self.assertRaises(PushActorRequiredError):
            decide_push_actor(evaluation, 42)
        with self.assertRaises(PushActorRequiredError):
            decide_push_actor(evaluation, "yrsa", actor_teams="devs")

    def test_renderer_says_the_words_escaped(self):
        self._restrict("main", actors=("volmarr",))
        html = render_push_actor_decision(self.gate.check_branch(
            self.writer, "volmarr", "pub", "main"))
        self.assertIn("protection-push-actors", html)
        self.assertIn("is not among them", html)
        html_ok = render_push_actor_decision(self._check("main"))
        self.assertIn("is allowed", html_ok)

    def test_no_migration_no_new_taxonomy_event(self):
        self.assertEqual(schema_version(self.conn), 90)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 127)
        self.assertNotIn("repo.push.actor_required",
                         taxonomy.AUDIT_EVENTS)


if __name__ == "__main__":
    unittest.main()
