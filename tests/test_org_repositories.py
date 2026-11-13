"""S-196 acceptance battery: org repositories.

Acceptance (roadmap S-196): Org repositories —
creation policies (who may create, allowed
visibilities), org repo list with filters.

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
from samverk.org_repositories import (
    OrgRepoStore, decide_creation, decide_policy_change,
    render_policy_page, render_repo_list_page,
    repo_matches_filters, validate_allowed_visibilities,
    validate_who_may_create)
from samverk.organization_members import OrgMembershipStore
from samverk.organizations import (
    OrganizationError, OrganizationStore, settings_areas)
from samverk.repositories import Repository, RepositoryError


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class OrgRepoTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.data_root = self.root / "data"
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.creator = self.accounts.register("volmarr", "correct horse battery")
        self.yrsa = self.accounts.register("yrsa", "correct horse battery")
        self.outsider = self.accounts.register("freya", "correct horse battery")
        self.admin = self.accounts.register("sitemod", "correct horse battery")
        with self.conn:
            self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (self.admin.id,))
        self.admin = self.accounts.get_by_id(self.admin.id)
        self.orgs = OrganizationStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.org = self.orgs.create_organization(self.creator.id, "crew")
        self.members = OrgMembershipStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.members.add_member(self.creator.id, self.org.id, self.yrsa.id)
        self.store = OrgRepoStore(self.conn, self.accounts, self.data_root, self.audit, time_fn=self.clock)

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(OrganizationError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def _repo_reason(self, fn, *args, **kwargs):
        with self.assertRaises(RepositoryError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def _updates(self):
        return self.conn.execute("SELECT COUNT(*) c FROM audit_log WHERE action = 'auth.organization.update'").fetchone()["c"]

    def _creates(self):
        return self.conn.execute("SELECT COUNT(*) c FROM audit_log WHERE action = 'repo.create'").fetchone()["c"]

    def _seed_repo(self, name, visibility, description=""):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO repositories (owner, owner_lower, name, name_lower, created_by, created_at, description, visibility) VALUES ('crew', 'crew', ?, ?, ?, 1700000000, ?, ?)",
                (name, name.lower(), self.creator.id, description, visibility))
        return Repository(id=int(cur.lastrowid), owner="crew", owner_lower="crew",
                          name=name, name_lower=name.lower(), created_by=self.creator.id,
                          created_at=1700000000, description=description, visibility=visibility)

    # pins
    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 125)
        self.assertEqual(db.MIGRATIONS[-1][0], 125)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        self.assertIn("auth.organization.update", taxonomy.AUDIT_EVENTS)
        self.assertIn("repo.create", taxonomy.AUDIT_EVENTS)
        cols = [r["name"] for r in self.conn.execute("PRAGMA table_info(org_repo_policies)").fetchall()]
        self.assertEqual(cols, ["org_id", "who_may_create", "allowed_visibilities", "set_by", "created_at", "updated_at"])

    def test_upgrade_from_76(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "old.db"
            conn = db.connect(path)
            for version, statements in db.MIGRATIONS:
                if version > 76:
                    continue
                with conn:
                    for stmt in statements:
                        conn.execute(stmt)
                    conn.execute("INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('version', ?)", (str(version),))
            self.assertEqual(db.schema_version(conn), 76)
            conn.close()
            conn = db.init_db(path)
            self.assertEqual(db.schema_version(conn), 125)
            tables = [r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'org_repo_policies'").fetchall()]
            self.assertEqual(tables, ["org_repo_policies"])
            conn.close()

    def test_settings_area_repositories_available(self):
        by_key = {a["key"]: a for a in settings_areas()}
        self.assertTrue(by_key["repositories"]["available"])
        self.assertEqual(by_key["repositories"]["slice"], "S-196")

    # pure judgements
    def test_validate_who(self):
        self.assertEqual(validate_who_may_create(" Owners "), "owners")
        self.assertEqual(validate_who_may_create("MEMBERS"), "members")
        self.assertEqual(validate_who_may_create("none"), "none")
        for bad in ("admins", "", "anyone", None, 3):
            self.assertEqual(self._reason(validate_who_may_create, bad), "who_may_create_invalid")

    def test_validate_visibilities(self):
        self.assertEqual(validate_allowed_visibilities(["private", "public", "private"]), ("public", "private"))
        self.assertEqual(validate_allowed_visibilities("private"), ("private",))
        self.assertEqual(validate_allowed_visibilities("Public, private"), ("public", "private"))
        self.assertEqual(self._reason(validate_allowed_visibilities, []), "visibilities_invalid")
        self.assertEqual(self._reason(validate_allowed_visibilities, ""), "visibilities_invalid")
        self.assertEqual(self._reason(validate_allowed_visibilities, None), "visibilities_invalid")
        self.assertEqual(validate_allowed_visibilities(["internal"]), ("internal",))
        self.assertEqual(self._reason(validate_allowed_visibilities, ["everywhere"]), "visibility_invalid")
        self.assertEqual(self._reason(validate_allowed_visibilities, ["public", 3]), "visibility_invalid")

    def test_decide_creation_matrix(self):
        both = ("public", "private")
        pub = ("public",)
        self.assertIsNone(decide_creation("owner", False, "owners", "private", both))
        self.assertEqual(decide_creation("member", False, "owners", "private", both), "owner_only")
        self.assertIsNone(decide_creation("member", False, "members", "private", both))
        self.assertEqual(decide_creation(None, False, "members", "private", both), "not_org_member")
        self.assertEqual(decide_creation("owner", False, "none", "public", both), "creation_disabled")
        self.assertEqual(decide_creation("member", False, "none", "public", both), "creation_disabled")
        self.assertEqual(decide_creation(None, False, "none", "public", both), "creation_disabled")
        self.assertIsNone(decide_creation(None, True, "none", "public", both))
        self.assertIsNone(decide_creation("member", True, "owners", "private", both))
        self.assertEqual(decide_creation("owner", False, "owners", "private", pub), "visibility_not_allowed")
        self.assertEqual(decide_creation(None, True, "members", "private", pub), "visibility_not_allowed")
        # who gate speaks before the visibility gate
        self.assertEqual(decide_creation("member", False, "owners", "private", pub), "owner_only")

    def test_decide_policy_change(self):
        self.assertEqual(decide_policy_change("owners", ("public", "private"), "owners", ("public", "private")), "noop")
        self.assertEqual(decide_policy_change("owners", ("public", "private"), "members", ("public", "private")), "set")
        self.assertEqual(decide_policy_change("owners", ("public", "private"), "owners", ("public",)), "set")

    def test_repo_matches_filters_pure(self):
        repo = self._seed_repo("anvil", "public", "Heavy hammer")
        self.assertTrue(repo_matches_filters(repo))
        self.assertTrue(repo_matches_filters(repo, "public", "HAM"))
        self.assertTrue(repo_matches_filters(repo, None, "anv"))
        self.assertFalse(repo_matches_filters(repo, "private"))
        self.assertFalse(repo_matches_filters(repo, None, "feather"))

    # policy store
    def test_default_policy_unset(self):
        policy = self.store.get_policy(self.org.id)
        self.assertFalse(policy.is_set)
        self.assertEqual(policy.who_may_create, "owners")
        self.assertEqual(policy.allowed_visibilities, ("public", "private"))
        self.assertEqual(self._reason(self.store.get_policy, 99999), "org_not_found")

    def test_set_policy_owner_and_noop(self):
        before = self._updates()
        policy = self.store.set_policy(self.creator.id, self.org.id, who_may_create="members", allowed_visibilities=["private"])
        self.assertTrue(policy.is_set)
        self.assertEqual(policy.who_may_create, "members")
        self.assertEqual(policy.allowed_visibilities, ("private",))
        self.assertEqual(policy.set_by_username, "volmarr")
        self.assertEqual(self._updates(), before + 1)
        again = self.store.set_policy(self.creator.id, self.org.id, who_may_create="members", allowed_visibilities=["private"])
        self.assertEqual(again.who_may_create, "members")
        self.assertEqual(self._updates(), before + 1)

    def test_set_policy_partial_keeps_other_field(self):
        self.store.set_policy(self.creator.id, self.org.id, allowed_visibilities=["public"])
        policy = self.store.set_policy(self.creator.id, self.org.id, who_may_create="none")
        self.assertEqual(policy.who_may_create, "none")
        self.assertEqual(policy.allowed_visibilities, ("public",))

    def test_set_policy_guards(self):
        self.assertEqual(self._reason(self.store.set_policy, self.yrsa.id, self.org.id, who_may_create="members"), "not_org_owner")
        self.assertEqual(self._reason(self.store.set_policy, self.outsider.id, self.org.id, who_may_create="members"), "not_org_owner")
        self.assertEqual(self._reason(self.store.set_policy, 99999, self.org.id, who_may_create="members"), "no_such_user")
        self.assertEqual(self._reason(self.store.set_policy, self.creator.id, 99999, who_may_create="members"), "org_not_found")
        self.assertEqual(self._reason(self.store.set_policy, self.creator.id, self.org.id, who_may_create="anyone"), "who_may_create_invalid")
        policy = self.store.set_policy(self.admin.id, self.org.id, who_may_create="members")
        self.assertEqual(policy.who_may_create, "members")

    # creation through the policy
    def test_create_default_policy_owner_only(self):
        repo = self.store.create_repository(self.creator.id, self.org.id, "anvil", visibility="private", description="Heavy")
        self.assertEqual(repo.full_name, "crew/anvil")
        self.assertEqual(repo.visibility, "private")
        self.assertTrue((self.data_root / "repos" / "crew" / "anvil.git").exists())
        self.assertEqual(self._creates(), 1)
        self.assertEqual(self._reason(self.store.create_repository, self.yrsa.id, self.org.id, "hammer"), "owner_only")
        self.assertEqual(self._reason(self.store.create_repository, self.outsider.id, self.org.id, "hammer"), "not_org_member")
        self.assertEqual(self._creates(), 1)

    def test_create_members_policy_and_visibility_gate(self):
        self.store.set_policy(self.creator.id, self.org.id, who_may_create="members", allowed_visibilities=["public"])
        repo = self.store.create_repository(self.yrsa.id, self.org.id, "hammer", visibility="public")
        self.assertEqual(repo.owner_lower, "crew")
        self.assertEqual(self._reason(self.store.create_repository, self.yrsa.id, self.org.id, "secret", visibility="private"), "visibility_not_allowed")
        self.assertEqual(self._reason(self.store.create_repository, self.yrsa.id, self.org.id, "bad", visibility="internal"), "visibility_not_allowed")

    def test_create_disabled_and_admin_visibility_bound(self):
        self.store.set_policy(self.creator.id, self.org.id, who_may_create="none", allowed_visibilities=["public"])
        self.assertEqual(self._reason(self.store.create_repository, self.creator.id, self.org.id, "anvil", visibility="public"), "creation_disabled")
        repo = self.store.create_repository(self.admin.id, self.org.id, "anvil", visibility="public")
        self.assertEqual(repo.name, "anvil")
        self.assertEqual(self._reason(self.store.create_repository, self.admin.id, self.org.id, "secret", visibility="private"), "visibility_not_allowed")

    def test_create_taken_and_invalid(self):
        self.store.create_repository(self.creator.id, self.org.id, "anvil")
        self.assertEqual(self._repo_reason(self.store.create_repository, self.creator.id, self.org.id, "ANVIL"), "repo_taken")
        self.assertEqual(self._repo_reason(self.store.create_repository, self.creator.id, self.org.id, "bad name"), "repo_invalid")

    def test_decision_for_and_can_create(self):
        self.assertTrue(self.store.can_create(self.creator.id, self.org.id, "private"))
        decision = self.store.decision_for(self.yrsa.id, self.org.id, "private")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "owner_only")
        self.assertEqual(decision.member_role, "member")
        self.assertFalse(decision.policy.is_set)
        self.assertEqual(self._reason(self.store.decision_for, self.creator.id, 99999, "public"), "org_not_found")

    # the list
    def _seed_three(self):
        self._seed_repo("anvil", "public", "Heavy hammer")
        self._seed_repo("bellows", "private", "Air for the forge")
        self._seed_repo("crucible", "private", "Heavy metal pot")

    def test_list_filters(self):
        self._seed_three()
        self.assertEqual([r.name for r in self.store.list_repositories(self.org.id)], ["anvil", "bellows", "crucible"])
        self.assertEqual([r.name for r in self.store.list_repositories(self.org.id, visibility="private")], ["bellows", "crucible"])
        self.assertEqual([r.name for r in self.store.list_repositories(self.org.id, query="heavy")], ["anvil", "crucible"])
        self.assertEqual([r.name for r in self.store.list_repositories(self.org.id, visibility="private", query="heavy")], ["crucible"])
        self.assertEqual(self.store.list_repositories(self.org.id, visibility="internal"), [])
        self.assertEqual(self._reason(self.store.list_repositories, 99999), "org_not_found")

    def test_list_visible_never_leaks_private(self):
        self._seed_three()
        outsider_view = self.store.list_visible(self.org.id, self.outsider)
        self.assertEqual([r.name for r in outsider_view], ["anvil"])
        anon_view = self.store.list_visible(self.org.id, None)
        self.assertEqual([r.name for r in anon_view], ["anvil"])
        member_view = self.store.list_visible(self.org.id, self.yrsa)
        self.assertEqual([r.name for r in member_view], ["anvil"])
        owner_view = self.store.list_visible(self.org.id, self.creator)
        self.assertEqual([r.name for r in owner_view], ["anvil", "bellows", "crucible"])
        admin_view = self.store.list_visible(self.org.id, self.admin)
        self.assertEqual(len(admin_view), 3)

    def test_list_visible_member_with_default_permission(self):
        self._seed_three()
        from samverk.default_permissions import DefaultPermissionStore
        defaults = DefaultPermissionStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        defaults.set_default(self.creator.id, self.org.id, "read")
        member_view = self.store.list_visible(self.org.id, self.yrsa)
        self.assertEqual([r.name for r in member_view], ["anvil", "bellows", "crucible"])

    # rendering
    def test_render_policy_page(self):
        policy = self.store.get_policy(self.org.id)
        html = render_policy_page(policy)
        self.assertIn("default policy applies", html)
        self.assertIn("Organization owners only", html)
        self.assertIn("Public and Private", html)
        self.store.set_policy(self.creator.id, self.org.id, who_may_create="members", allowed_visibilities=["private"])
        html = render_policy_page(self.store.get_policy(self.org.id))
        self.assertIn("Any organization member", html)
        self.assertIn("set by volmarr", html)

    def test_render_repo_list_page_escapes(self):
        self._seed_repo("<script>", "public", "x")
        repos = self.store.list_repositories(self.org.id)
        html = render_repo_list_page("crew", repos, visibility="public", query="script")
        self.assertIn("Filters:", html)
        self.assertIn("1 repository shown", html)
        evil = self._seed_repo("evil", "public", "<b>bold</b>")
        html = render_repo_list_page("crew", [evil])
        self.assertNotIn("<b>bold</b>", html)
        self.assertIn("&lt;b&gt;", html)


if __name__ == "__main__":
    unittest.main()
