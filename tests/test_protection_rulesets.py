"""S-181 acceptance battery: rulesets.

Acceptance (roadmap S-181): one ruleset targets many
repos/branches/tags; layered rules resolve
most-restrictive-wins; the evaluation is a tested
matrix.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import json, random, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.protection_rules import (
    ProtectionRule, ProtectionRuleStore, ProtectionSettings,
    evaluate_rules, fold_settings)
from samverk.protection_rulesets import (
    LayeredEvaluation, Ruleset, RulesetError, RulesetStore,
    evaluate_layered, evaluate_rulesets, order_rulesets,
    render_layered_evaluation, render_ruleset,
    render_ruleset_evaluation, validate_ruleset_name,
    validate_target)
from samverk.repositories import RepositoryStore


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


def bare_ruleset(rs_id, name, target="branch", repos=("volmarr/*",),
                 branches=("main",), tags=("v*",), **settings):
    return Ruleset(
        id=rs_id, name=name, target=target,
        repo_patterns=tuple(repos), branch_patterns=tuple(branches),
        tag_patterns=tuple(tags),
        settings=ProtectionSettings(**settings),
        created_by=None, created_at=0, updated_at=0)


def bare_rule(rule_id, pattern, **settings):
    return ProtectionRule(
        id=rule_id, repo_id=1, full_name="volmarr/pub",
        pattern=pattern, settings=ProtectionSettings(**settings),
        created_by=None, created_at=0, updated_at=0)


class RulesetTests(unittest.TestCase):
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
        self.conn.execute(
            "UPDATE users SET is_admin = 1 WHERE id = ?",
            (self.owner.id,))
        self.conn.commit()
        self.admin = self.accounts.get_by_id(self.owner.id)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts)
        self.rules = ProtectionRuleStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.store = RulesetStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock,
            protection_rules=self.rules)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        self.repos.create_repository(
            self.owner.id, "volmarr", "other", visibility="public")

    # -- helpers ---------------------------------------------------------
    def _audit_rows(self, action="repo.protection.change"):
        return self.conn.execute(
            "SELECT detail FROM audit_log WHERE action = ?"
            " ORDER BY seq", (action,)).fetchall()

    def _create(self, name="Baseline", **kw):
        kw.setdefault("repo_patterns", ["volmarr/*"])
        kw.setdefault("branch_patterns", ["main"])
        return self.store.create_ruleset(self.admin, name, **kw)

    def _rule(self, pattern="main", repo="pub", **fields):
        return self.rules.create_rule(
            self.owner, "volmarr", repo, pattern, **fields)

    # -- creation ----------------------------------------------------------
    def test_create_defaults_and_words(self):
        rs = self._create()
        self.assertEqual(rs.name, "Baseline")
        self.assertEqual(rs.target, "branch")
        self.assertEqual(rs.repo_patterns, ("volmarr/*",))
        self.assertEqual(rs.branch_patterns, ("main",))
        self.assertEqual(rs.tag_patterns, ())
        self.assertEqual(rs.created_by, self.admin.id)
        s = rs.settings
        self.assertTrue(s.enabled)
        self.assertTrue(s.block_force_pushes)
        self.assertTrue(s.enforce_admins)
        self.assertIn("'Baseline'", rs.words)
        self.assertIn("enabled", rs.words)
        self.assertIn("'volmarr/*'", rs.words)
        self.assertIn("force pushes are blocked", rs.words)
        rows = self._audit_rows()
        self.assertEqual(len(rows), 1)
        detail = json.loads(rows[0]["detail"])
        self.assertEqual(detail["ruleset"], "create")
        self.assertEqual(detail["ruleset_id"], rs.id)
        self.assertEqual(detail["name"], "Baseline")

    def test_create_full_settings_round_trip(self):
        rs = self._create(
            "Strict", target="all", tag_patterns=["v*"],
            require_pull_request=True, required_approvals=2,
            required_status_checks=["ci", "lint", "ci"],
            require_signed_commits=True,
            allowed_push_actors=["volmarr"],
            bypass_actors=["volmarr"])
        again = self.store.get_ruleset(self.admin, rs.id)
        s = again.settings
        self.assertTrue(s.require_pull_request)
        self.assertEqual(s.required_approvals, 2)
        self.assertEqual(s.required_status_checks, ("ci", "lint"))
        self.assertTrue(s.require_signed_commits)
        self.assertEqual(s.allowed_push_actors, ("volmarr",))
        self.assertEqual(s.bypass_actors, ("volmarr",))
        self.assertEqual(again.target, "all")
        self.assertEqual(again.tag_patterns, ("v*",))
        self.assertIn("2 approvals are required", again.words)

    def test_create_with_settings_object(self):
        shape = ProtectionSettings(require_pull_request=True)
        rs = self._create("Shaped", settings=shape)
        self.assertTrue(rs.settings.require_pull_request)
        with self.assertRaises(RulesetError) as caught:
            self._create("Both", settings=shape,
                         require_pull_request=True)
        self.assertEqual(caught.exception.reason,
                         "protection_ruleset_invalid")

    def test_name_and_target_validation(self):
        self.assertEqual(validate_ruleset_name("  Core  "), "Core")
        self.assertEqual(validate_target("all"), "all")
        for bad in ("", "  ", "x" * 101, "-lead", "a<b", 7, None):
            with self.assertRaises(RulesetError) as caught:
                validate_ruleset_name(bad)
            self.assertEqual(caught.exception.reason,
                             "protection_ruleset_invalid")
        with self.assertRaises(RulesetError):
            validate_target("push")
        # Refusals write nothing and emit no event.
        with self.assertRaises(RulesetError):
            self._create("bad<name")
        self.assertEqual(self.store.list_rulesets(self.admin), [])
        self.assertEqual(self._audit_rows(), [])

    def test_pattern_requirements_refused(self):
        cases = [
            dict(repo_patterns=[]),                       # no repos
            dict(branch_patterns=[]),                     # branch, none
            dict(target="tag"),                           # tag, no tags
            dict(target="all"),                           # all, no tags
            dict(repo_patterns=["volmarr//x"]),           # bad repo pat
            dict(branch_patterns=["release//x"]),         # bad branch
            dict(branch_patterns=["***"]),                # names nothing
        ]
        for i, kw in enumerate(cases):
            with self.assertRaises(RulesetError) as caught:
                self._create(f"Case {i}", **kw)
            self.assertEqual(caught.exception.reason,
                             "protection_ruleset_invalid",
                             msg=f"case {i}: {kw}")
        self.assertEqual(self.store.list_rulesets(self.admin), [])
        self.assertEqual(self._audit_rows(), [])

    def test_duplicate_name_taken_case_insensitive(self):
        self._create("Baseline")
        for dupe in ("Baseline", "baseline", "BASELINE"):
            with self.assertRaises(RulesetError) as caught:
                self._create(dupe)
            self.assertEqual(caught.exception.reason,
                             "protection_ruleset_taken")
        self.assertEqual(len(self.store.list_rulesets(self.admin)), 1)
        self.assertEqual(len(self._audit_rows()), 1)

    def test_writes_are_site_admin_acts(self):
        for actor in (self.reader, None):
            with self.assertRaises(RulesetError) as caught:
                self.store.create_ruleset(
                    actor, "Nope", repo_patterns=["volmarr/*"],
                    branch_patterns=["main"])
            self.assertEqual(caught.exception.reason,
                             "permission_denied")
        rs = self._create()
        for actor in (self.reader, None):
            with self.assertRaises(RulesetError) as caught:
                self.store.update_ruleset(
                    actor, rs.id, required_approvals=3)
            self.assertEqual(caught.exception.reason,
                             "permission_denied")
            with self.assertRaises(RulesetError):
                self.store.delete_ruleset(actor, rs.id)
            with self.assertRaises(RulesetError):
                self.store.list_rulesets(actor)
            with self.assertRaises(RulesetError):
                self.store.get_ruleset(actor, rs.id)
        # A repository admin who is not a site admin is refused
        # too: rulesets are instance policy. (self.owner IS the
        # site admin here; the repo-only admin is reader on priv
        # via ownership transfer is out of scope — reader stands
        # for every non-site-admin.)
        self.assertEqual(len(self._audit_rows()), 1)

    # -- update / delete -----------------------------------------------------
    def test_update_fields_patterns_and_noop(self):
        rs = self._create("Baseline")
        self.clock.now += 60
        updated = self.store.update_ruleset(
            self.admin, rs.id, required_approvals=2,
            branch_patterns=["main", "release/*"])
        self.assertEqual(updated.settings.required_approvals, 2)
        self.assertEqual(updated.branch_patterns,
                         ("main", "release/*"))
        self.assertEqual(updated.updated_at, self.clock.now)
        self.assertEqual(len(self._audit_rows()), 2)
        # Same-value update: quiet no-op, no audit, no timestamp move.
        self.clock.now += 60
        same = self.store.update_ruleset(
            self.admin, rs.id, required_approvals=2,
            branch_patterns=["main", "release/*"])
        self.assertEqual(same.updated_at, updated.updated_at)
        self.assertEqual(len(self._audit_rows()), 2)
        # Whole-shape update and unknown field refusal.
        shaped = self.store.update_ruleset(
            self.admin, rs.id,
            settings=ProtectionSettings(enabled=False))
        self.assertFalse(shaped.settings.enabled)
        with self.assertRaises(RulesetError) as caught:
            self.store.update_ruleset(self.admin, rs.id, bogus=1)
        self.assertEqual(caught.exception.reason,
                         "protection_ruleset_invalid")

    def test_update_rename_collision_and_retarget(self):
        self._create("Alpha")
        beta = self._create("Beta")
        with self.assertRaises(RulesetError) as caught:
            self.store.update_ruleset(self.admin, beta.id, name="alpha")
        self.assertEqual(caught.exception.reason,
                         "protection_ruleset_taken")
        moved = self.store.update_ruleset(
            self.admin, beta.id, target="tag", tag_patterns=["v*"])
        self.assertEqual(moved.target, "tag")
        with self.assertRaises(RulesetError) as caught:
            self.store.update_ruleset(
                self.admin, beta.id, target="branch",
                branch_patterns=[])
        self.assertEqual(caught.exception.reason,
                         "protection_ruleset_invalid")
        with self.assertRaises(RulesetError) as caught:
            self.store.update_ruleset(self.admin, 9999, name="Ghost")
        self.assertEqual(caught.exception.reason,
                         "protection_ruleset_not_found")

    def test_delete_and_get_by_name(self):
        rs = self._create("Baseline")
        found = self.store.get_ruleset_by_name(self.admin, "baseline")
        self.assertEqual(found.id, rs.id)
        gone = self.store.delete_ruleset(self.admin, rs.id)
        self.assertEqual(gone.id, rs.id)
        self.assertEqual(self.store.list_rulesets(self.admin), [])
        with self.assertRaises(RulesetError) as caught:
            self.store.get_ruleset(self.admin, rs.id)
        self.assertEqual(caught.exception.reason,
                         "protection_ruleset_not_found")
        rows = self._audit_rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(json.loads(rows[1]["detail"])["ruleset"],
                         "delete")

    # -- pure matching ---------------------------------------------------------
    def test_matching_globs_and_targets(self):
        rs = bare_ruleset(
            1, "Core", target="all", repos=("volmarr/*",),
            branches=("release/*",), tags=("v*",))
        self.assertTrue(rs.matches("volmarr/pub", "branch",
                                   "release/1.0"))
        self.assertFalse(rs.matches("volmarr/pub", "branch",
                                    "release/x/y"))   # * stops at /
        self.assertTrue(rs.matches("volmarr/pub", "tag", "v1.2"))
        self.assertFalse(rs.matches("other/pub", "branch",
                                    "release/1.0"))   # repo pattern
        self.assertFalse(rs.matches("volmarr/pub", "branch", "main"))
        deep = bare_ruleset(
            2, "Deep", repos=("**",), branches=("release/**",),
            tags=())
        self.assertTrue(deep.matches("a/b", "branch", "release/x/y"))
        branch_only = bare_ruleset(3, "B", target="branch",
                                   tags=("v*",))
        self.assertFalse(branch_only.matches(
            "volmarr/pub", "tag", "v1"))
        tag_only = bare_ruleset(4, "T", target="tag",
                                branches=("main",))
        self.assertFalse(tag_only.matches(
            "volmarr/pub", "branch", "main"))
        off = bare_ruleset(5, "Off", enabled=False)
        self.assertFalse(off.matches("volmarr/pub", "branch", "main"))
        self.assertIsNone(off.matched_ref_pattern(
            "volmarr/pub", "branch", "main"))
        self.assertEqual(
            rs.matched_ref_pattern("volmarr/pub", "tag", "v9"), "v*")

    def test_ruleset_order_deterministic(self):
        sets = [bare_ruleset(3, "charlie"), bare_ruleset(1, "Alpha"),
                bare_ruleset(2, "beta"), bare_ruleset(4, "alpha")]
        want = ["Alpha", "alpha", "beta", "charlie"]
        self.assertEqual([r.name for r in order_rulesets(sets)], want)
        for seed in range(8):
            shuffled = list(sets)
            random.Random(seed).shuffle(shuffled)
            self.assertEqual(
                [r.name for r in order_rulesets(shuffled)], want)

    def test_fold_settings_is_s169s_algebra(self):
        a = ProtectionSettings(
            required_approvals=1, require_signed_commits=True,
            required_status_checks=("ci",),
            allowed_push_actors=("volmarr", "yrsa"),
            bypass_actors=("volmarr", "yrsa"))
        b = ProtectionSettings(
            required_approvals=3, require_pull_request=True,
            required_status_checks=("lint", "ci"),
            allowed_push_actors=("yrsa",),
            bypass_actors=("yrsa",))
        folded = fold_settings([a, b])
        via_rules = evaluate_rules(
            [bare_rule(1, "main", required_approvals=1,
                       require_signed_commits=True,
                       required_status_checks=("ci",),
                       allowed_push_actors=("volmarr", "yrsa"),
                       bypass_actors=("volmarr", "yrsa")),
             bare_rule(2, "m*", required_approvals=3,
                       require_pull_request=True,
                       required_status_checks=("lint", "ci"),
                       allowed_push_actors=("yrsa",),
                       bypass_actors=("yrsa",))],
            "main", full_name="volmarr/pub")
        self.assertEqual(folded, via_rules.effective.settings)
        self.assertEqual(folded.required_approvals, 3)
        self.assertEqual(folded.required_status_checks,
                         ("ci", "lint"))
        self.assertEqual(folded.allowed_push_actors, ("yrsa",))
        self.assertEqual(folded.bypass_actors, ("yrsa",))
        self.assertIsNone(fold_settings([]))

    def test_ruleset_fold_empty_bypass_closes_door(self):
        open_rs = bare_ruleset(1, "A", bypass_actors=("volmarr",))
        shut_rs = bare_ruleset(2, "B")   # names nobody
        ev = evaluate_rulesets(
            [open_rs, shut_rs], "volmarr/pub", "branch", "main")
        self.assertEqual([r.name for r in ev.matching], ["A", "B"])
        self.assertEqual(ev.effective.bypass_actors, ())
        self.assertTrue(ev.is_protected)
        self.assertIn("A", ev.words)

    # -- the tested matrix -----------------------------------------------------
    def test_evaluation_matrix(self):
        # Layers: per-repo rules R1 (main: 1 approval, ci) and
        # R2 (release/*: signed); rulesets A "Alpha" (volmarr/*
        # branches main+release/*: PR required, 2 approvals,
        # lint), B "Beta" (volmarr/pub branches: 3 approvals,
        # bypass volmarr), C "Tags" (volmarr/* tags v*: signed,
        # linear), D "Elsewhere" (other/* : 9 approvals).
        repo_rules = [
            bare_rule(1, "main", required_approvals=1,
                      required_status_checks=("ci",),
                      bypass_actors=("volmarr",)),
            bare_rule(2, "release/*", require_signed_commits=True,
                      bypass_actors=("volmarr",)),
        ]
        rulesets = [
            bare_ruleset(1, "Alpha", repos=("volmarr/*",),
                         branches=("main", "release/*"),
                         require_pull_request=True,
                         required_approvals=2,
                         required_status_checks=("lint",),
                         bypass_actors=("volmarr",)),
            bare_ruleset(2, "Beta", repos=("volmarr/pub",),
                         branches=("**",), required_approvals=3,
                         bypass_actors=("volmarr",)),
            bare_ruleset(3, "Tags", target="tag",
                         repos=("volmarr/*",), tags=("v*",),
                         branches=(),
                         require_signed_commits=True,
                         require_linear_history=True),
            bare_ruleset(4, "Elsewhere", repos=("other/*",),
                         branches=("main",), required_approvals=9),
        ]
        # (repo, kind, ref, want_rules, want_rulesets, approvals,
        #  pr, signed, linear, checks)
        cases = [
            ("volmarr/pub", "branch", "main",
             ("main",), ("Alpha", "Beta"), 3, True, False, False,
             ("ci", "lint")),
            ("volmarr/pub", "branch", "release/1",
             ("release/*",), ("Alpha", "Beta"), 3, True, True,
             False, ("lint",)),
            ("volmarr/pub", "branch", "feature",
             (), ("Beta",), 3, False, False, False, ()),
            ("volmarr/other", "branch", "main",
             ("main",), ("Alpha",), 2, True, False, False,
             ("ci", "lint")),
            ("volmarr/other", "branch", "dev",
             (), (), 0, False, False, False, ()),
            ("volmarr/pub", "tag", "v1.0",
             (), ("Tags",), 0, False, True, True, ()),
            ("volmarr/pub", "tag", "nightly",
             (), (), 0, False, False, False, ()),
            ("other/pub", "branch", "main",
             ("main",), ("Elsewhere",), 9, False, False, False,
             ("ci",)),
        ]
        for (repo, kind, ref, want_rules, want_sets, approvals,
             pr, signed, linear, checks) in cases:
            with self.subTest(repo=repo, kind=kind, ref=ref):
                # Per-repo rules belong to volmarr/pub's repo in
                # R1/R2's own record; for other repos the layer is
                # the same rule shapes judged for that repo name.
                ev = evaluate_layered(
                    repo_rules, rulesets, repo, kind, ref)
                self.assertEqual(
                    tuple(r.pattern for r in ev.matching_rules),
                    want_rules if kind == "branch" else ())
                self.assertEqual(
                    tuple(r.name for r in ev.matching_rulesets),
                    want_sets)
                if not want_rules and not want_sets:
                    self.assertIsNone(ev.effective)
                    self.assertFalse(ev.is_protected)
                    continue
                self.assertTrue(ev.is_protected)
                s = ev.effective
                self.assertEqual(s.required_approvals, approvals)
                self.assertEqual(s.require_pull_request, pr)
                self.assertEqual(s.require_signed_commits, signed)
                self.assertEqual(s.require_linear_history, linear)
                self.assertEqual(s.required_status_checks, checks)

    def test_layered_bypass_and_push_intersection(self):
        repo_rules = [bare_rule(
            1, "main", allowed_push_actors=("volmarr", "yrsa"),
            bypass_actors=("volmarr", "yrsa"))]
        rulesets = [bare_ruleset(
            1, "Alpha", allowed_push_actors=("yrsa", "carol"),
            bypass_actors=("yrsa",))]
        ev = evaluate_layered(
            repo_rules, rulesets, "volmarr/pub", "branch", "main")
        self.assertEqual(ev.effective.allowed_push_actors, ("yrsa",))
        self.assertEqual(ev.effective.bypass_actors, ("yrsa",))
        # A ruleset alone (no repo rule) still protects, and a
        # repo rule alone is untouched by an absent ruleset layer.
        only_set = evaluate_layered(
            [], rulesets, "volmarr/pub", "branch", "main")
        self.assertEqual(only_set.effective.allowed_push_actors,
                         ("yrsa", "carol"))
        only_rule = evaluate_layered(
            repo_rules, [], "volmarr/pub", "branch", "main")
        self.assertEqual(only_rule.effective.bypass_actors,
                         ("volmarr", "yrsa"))
        self.assertIn("most-restrictive-wins", only_rule.words)

    # -- store-level evaluation --------------------------------------------------
    def test_evaluate_ref_layers_store_rules(self):
        self._rule("main", required_approvals=1,
                   bypass_actors=["volmarr"])
        self._create("Alpha", require_pull_request=True,
                     required_approvals=2, bypass_actors=["volmarr"])
        ev = self.store.evaluate_ref(
            self.reader, "volmarr", "pub", "branch", "main")
        self.assertIsInstance(ev, LayeredEvaluation)
        self.assertTrue(ev.is_protected)
        self.assertEqual(ev.effective.required_approvals, 2)
        self.assertTrue(ev.effective.require_pull_request)
        self.assertEqual(
            tuple(r.name for r in ev.matching_rulesets), ("Alpha",))
        self.assertEqual(
            tuple(r.pattern for r in ev.matching_rules), ("main",))
        self.assertTrue(self.store.is_protected(
            self.reader, "volmarr", "pub", "branch", "main"))
        miss = self.store.evaluate_ref(
            self.reader, "volmarr", "pub", "branch", "dev")
        self.assertFalse(miss.is_protected)
        self.assertIn("not protected", miss.words)

    def test_evaluate_ref_tag_ignores_branch_rules(self):
        self._rule("v*", require_pull_request=True)  # branch rule
        self._create("TagLaw", target="tag", branch_patterns=[],
                     tag_patterns=["v*"], require_signed_commits=True)
        ev = self.store.evaluate_ref(
            self.reader, "volmarr", "pub", "tag", "v1.0")
        self.assertEqual(ev.matching_rules, ())
        self.assertIsNone(ev.repo_evaluation)
        self.assertTrue(ev.effective.require_signed_commits)
        self.assertFalse(ev.effective.require_pull_request)
        branch = self.store.evaluate_ref(
            self.reader, "volmarr", "pub", "branch", "v1.0")
        self.assertTrue(branch.effective.require_pull_request)

    def test_evaluate_ref_repo_scoping_and_private_guard(self):
        self._create("PubOnly", repo_patterns=["volmarr/pub"])
        ev = self.store.evaluate_ref(
            self.reader, "volmarr", "other", "branch", "main")
        self.assertFalse(ev.is_protected)
        priv = self.store.evaluate_ref(
            self.owner, "volmarr", "priv", "branch", "main")
        self.assertFalse(priv.is_protected)  # pattern is pub only
        for viewer in (self.reader, None):
            with self.assertRaises(RulesetError) as caught:
                self.store.evaluate_ref(
                    viewer, "volmarr", "priv", "branch", "main")
            self.assertEqual(caught.exception.reason,
                             "repo_not_found")
        with self.assertRaises(RulesetError) as caught:
            self.store.evaluate_ref(
                self.reader, "volmarr", "ghost", "branch", "main")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        with self.assertRaises(RulesetError) as caught:
            self.store.evaluate_ref(
                self.reader, "volmarr", "pub", "push", "main")
        self.assertEqual(caught.exception.reason,
                         "protection_ruleset_invalid")

    def test_disabled_ruleset_protects_nothing(self):
        self._create("Off", enabled=False, required_approvals=5)
        ev = self.store.evaluate_ref(
            self.reader, "volmarr", "pub", "branch", "main")
        self.assertFalse(ev.is_protected)
        listed = self.store.list_rulesets(self.admin)
        self.assertIn("disabled", listed[0].words)

    # -- renderers -----------------------------------------------------------------
    def test_renderers_say_the_words_escaped(self):
        rs = self._create("Alpha")
        html = render_ruleset(rs)
        self.assertIn("protection-ruleset", html)
        self.assertIn("Alpha", html)
        ev = self.store.evaluate_ref(
            self.reader, "volmarr", "pub", "branch", "main")
        layered_html = render_layered_evaluation(ev)
        self.assertIn("most-restrictive-wins", layered_html)
        rs_html = render_ruleset_evaluation(ev.ruleset_evaluation)
        self.assertIn("Alpha", rs_html)
        evil = bare_ruleset(9, "x<script>", repos=("a<b",),
                            branches=("main",))
        self.assertIn("&lt;script&gt;", render_ruleset(evil))
        self.assertNotIn("<script>", render_ruleset(evil))

    # -- pins -------------------------------------------------------------------------
    def test_migration_67_and_taxonomy_120(self):
        self.assertEqual(schema_version(self.conn), 90)
        self.assertEqual(db.MIGRATIONS[-1][0], 90)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 127)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 31)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 83)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        cols = [r["name"] for r in self.conn.execute(
            "PRAGMA table_info(protection_rulesets)").fetchall()]
        for col in ("id", "name", "name_lower", "target",
                    "repo_patterns", "branch_patterns",
                    "tag_patterns", "enabled",
                    "require_pull_request", "required_approvals",
                    "require_last_pusher_approval",
                    "required_status_checks", "enforce_admins",
                    "allowed_push_actors", "bypass_actors",
                    "created_by", "created_at", "updated_at"):
            self.assertIn(col, cols)
        # Upgrade path: a v66 database gains the table and
        # keeps its protection rules.
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "old.db"
            conn = db.connect(path)
            for version, statements in db.MIGRATIONS:
                if version > 66:
                    continue
                with conn:
                    for stmt in statements:
                        conn.execute(stmt)
                    conn.execute(
                        "INSERT OR REPLACE INTO schema_meta"
                        " (key, value) VALUES ('version', ?)",
                        (str(version),))
            conn.close()
            conn = db.init_db(path)
            self.assertEqual(db.schema_version(conn), 90)
            names = [r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master"
                " WHERE type = 'table'"
                " AND name = 'protection_rulesets'").fetchall()]
            self.assertEqual(names, ["protection_rulesets"])
            conn.close()


if __name__ == "__main__":
    unittest.main()
