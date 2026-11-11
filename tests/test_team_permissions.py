"""S-189 acceptance battery: team repository permissions.

Acceptance (roadmap S-189): Team repository permissions
— the role ladder read / triage / write / maintain /
admin, applied per repo per team.

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
from samverk.organization_members import OrgMembershipStore
from samverk.organizations import (
    OrganizationError, OrganizationStore, settings_areas)
from samverk.team_nesting import NestedTeamStore
from samverk.team_permissions import (
    DEFAULT_PERMISSION, ROLES, TeamPermissionStore, higher_role,
    render_team_permissions_page, role_covers, role_rank,
    role_word, validate_role)
from samverk.teams import TeamStore


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class TeamPermissionTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.creator = self.accounts.register("volmarr", "correct horse battery")
        self.yrsa = self.accounts.register("yrsa", "correct horse battery")
        self.bryn = self.accounts.register("brynhild", "correct horse battery")
        self.admin = self.accounts.register("sitemod", "correct horse battery")
        with self.conn:
            self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (self.admin.id,))
        self.orgs = OrganizationStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.org = self.orgs.create_organization(self.creator.id, "crew")
        self.other_org = self.orgs.create_organization(self.creator.id, "othercrew")
        self.members = OrgMembershipStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.members.add_member(self.creator.id, self.org.id, self.yrsa.id)
        self.teams = TeamStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.nesting = NestedTeamStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.perms = TeamPermissionStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.parent = self.teams.create_team(self.creator.id, self.org.id, "Parent Team")
        self.child = self.teams.create_team(self.creator.id, self.org.id, "Child Team")
        self.sibling = self.teams.create_team(self.creator.id, self.org.id, "Sibling Team")

    def _updates(self):
        return self.conn.execute("SELECT COUNT(*) c FROM audit_log WHERE action = 'auth.organization.update'").fetchone()["c"]

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(OrganizationError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def _repo(self, owner, name):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO repositories (owner, owner_lower, name, name_lower, created_by, created_at, description, visibility) VALUES (?, ?, ?, ?, ?, ?, '', 'public')",
                (owner, owner.lower(), name, name.lower(), self.creator.id, 1_700_000_000))
        return int(cur.lastrowid)

    def _link(self, team, repo_id, role=None):
        self.teams.link_repo(self.creator.id, self.org.id, team.id, repo_id)
        if role is not None:
            return self.perms.set_permission(self.creator.id, self.org.id, team.id, repo_id, role)
        return None

    def _chain(self):
        self.nesting.set_parent(self.creator.id, self.org.id, self.child.id, self.parent.id)
        self.nesting.set_parent(self.creator.id, self.org.id, self.sibling.id, self.parent.id)

    # pure ladder
    def test_pure_ladder_rules(self):
        self.assertEqual(ROLES, ("read", "triage", "write", "maintain", "admin"))
        self.assertEqual([role_rank(r) for r in ROLES], [1, 2, 3, 4, 5])
        self.assertEqual(validate_role(" Write "), "write")
        self.assertEqual(validate_role("ADMIN"), "admin")
        self.assertEqual(role_word("triage"), "Triage")
        self.assertEqual(higher_role("read", "maintain"), "maintain")
        self.assertEqual(higher_role("write", None), "write")
        self.assertIsNone(higher_role(None, None))
        self.assertTrue(role_covers("write", "triage"))
        self.assertTrue(role_covers("read", "read"))
        self.assertFalse(role_covers("read", "write"))
        self.assertFalse(role_covers(None, "read"))
        for bad in ("owner", "", "  ", None, 3):
            with self.assertRaises(OrganizationError) as ctx:
                validate_role(bad)
            self.assertEqual(ctx.exception.reason, "role_invalid")

    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 110)
        self.assertEqual(db.MIGRATIONS[-1][0], 110)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)
        cols = [r["name"] for r in self.conn.execute("PRAGMA table_info(team_repositories)").fetchall()]
        self.assertIn("permission", cols)

    def test_migration_72_upgrades_existing_link_to_read(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "old.db"
            conn = db.connect(path)
            for version, statements in db.MIGRATIONS:
                if version > 71:
                    continue
                with conn:
                    for stmt in statements:
                        conn.execute(stmt)
                    conn.execute("INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('version', ?)", (str(version),))
            with conn:
                conn.execute("INSERT INTO team_repositories (team_id, repo_id, added_by, created_at) VALUES (1, 2, NULL, 1)")
            conn.close()
            conn = db.init_db(path)
            self.assertEqual(db.schema_version(conn), 110)
            row = conn.execute("SELECT permission FROM team_repositories WHERE team_id = 1 AND repo_id = 2").fetchone()
            self.assertEqual(row["permission"], "read")
            conn.close()

    # direct permissions
    def test_fresh_link_defaults_to_read(self):
        anvil = self._repo("crew", "anvil")
        link = self.teams.link_repo(self.creator.id, self.org.id, self.child.id, anvil)
        self.assertEqual(link.permission, DEFAULT_PERMISSION)
        self.assertEqual(self.perms.permission_for(self.org.id, self.child.id, anvil), "read")
        got = self.perms.get_permission(self.org.id, self.child.id, anvil)
        self.assertEqual((got.owner, got.name, got.permission), ("crew", "anvil", "read"))
        self.assertEqual(self.teams.list_repos(self.org.id, self.child.id)[0].permission, "read")

    def test_unlinked_permission_is_none(self):
        anvil = self._repo("crew", "anvil")
        self.assertIsNone(self.perms.permission_for(self.org.id, self.child.id, anvil))
        self.assertIsNone(self.perms.get_permission(self.org.id, self.child.id, anvil))
        self.assertEqual(self.perms.list_permissions(self.org.id, self.child.id), [])

    def test_set_permission_happy_and_audited(self):
        anvil = self._repo("crew", "anvil")
        self._link(self.child, anvil)
        before = self._updates()
        got = self.perms.set_permission(self.creator.id, self.org.id, self.child.id, anvil, " Maintain ")
        self.assertEqual(got.permission, "maintain")
        self.assertEqual(self.perms.permission_for(self.org.id, self.child.id, anvil), "maintain")
        self.assertEqual(self._updates(), before + 1)
        row = self.conn.execute("SELECT detail FROM audit_log WHERE action = 'auth.organization.update' ORDER BY rowid DESC LIMIT 1").fetchone()
        self.assertIn("set_permission", row["detail"])
        self.assertIn("maintain", row["detail"])

    def test_set_permission_by_site_admin(self):
        anvil = self._repo("crew", "anvil")
        self._link(self.child, anvil)
        got = self.perms.set_permission(self.admin.id, self.org.id, self.child.id, anvil, "admin")
        self.assertEqual(got.permission, "admin")

    def test_set_same_permission_is_noop_without_audit(self):
        anvil = self._repo("crew", "anvil")
        self._link(self.child, anvil, "write")
        before = self._updates()
        got = self.perms.set_permission(self.creator.id, self.org.id, self.child.id, anvil, "write")
        self.assertEqual(got.permission, "write")
        self.assertEqual(self._updates(), before)

    def test_set_permission_refusals_write_and_audit_nothing(self):
        anvil = self._repo("crew", "anvil")
        foreign = self._repo("othercrew", "foreign")
        self._link(self.child, anvil)
        before = self._updates()
        self.assertEqual(
            self._reason(self.perms.set_permission, self.yrsa.id, self.org.id, self.child.id, anvil, "write"),
            "not_org_owner")
        self.assertEqual(
            self._reason(self.perms.set_permission, self.bryn.id, self.org.id, self.child.id, anvil, "write"),
            "not_org_owner")
        self.assertEqual(
            self._reason(self.perms.set_permission, self.creator.id, self.org.id, self.child.id, anvil, "owner"),
            "role_invalid")
        self.assertEqual(
            self._reason(self.perms.set_permission, self.creator.id, self.org.id, self.child.id, 999999, "write"),
            "repo_not_found")
        self.assertEqual(
            self._reason(self.perms.set_permission, self.creator.id, self.org.id, self.child.id, foreign, "write"),
            "repo_not_in_org")
        boat = self._repo("crew", "boat")
        self.assertEqual(
            self._reason(self.perms.set_permission, self.creator.id, self.org.id, self.child.id, boat, "write"),
            "not_linked")
        self.assertEqual(
            self._reason(self.perms.set_permission, self.creator.id, self.org.id, 999999, anvil, "write"),
            "team_not_found")
        self.assertEqual(
            self._reason(self.perms.set_permission, self.creator.id, 999999, self.child.id, anvil, "write"),
            "org_not_found")
        self.assertEqual(self.perms.permission_for(self.org.id, self.child.id, anvil), "read")
        self.assertEqual(self._updates(), before)

    def test_unlink_removes_permission(self):
        anvil = self._repo("crew", "anvil")
        self._link(self.child, anvil, "admin")
        self.teams.unlink_repo(self.creator.id, self.org.id, self.child.id, anvil)
        self.assertIsNone(self.perms.permission_for(self.org.id, self.child.id, anvil))
        self.assertIsNone(self.perms.effective_permission(self.org.id, self.child.id, anvil))

    def test_list_permissions_and_permissions_for_repo(self):
        anvil = self._repo("crew", "anvil")
        boat = self._repo("crew", "boat")
        self._link(self.child, boat, "triage")
        self._link(self.child, anvil, "write")
        self._link(self.parent, anvil, "read")
        mine = self.perms.list_permissions(self.org.id, self.child.id)
        self.assertEqual([(p.name, p.permission) for p in mine],
                         [("anvil", "write"), ("boat", "triage")])
        for_repo = self.perms.permissions_for_repo(self.org.id, anvil)
        self.assertEqual([(p.team_id, p.permission) for p in for_repo],
                         [(self.child.id, "write"), (self.parent.id, "read")])

    # effective permissions: inheritance judged by the ladder
    def test_effective_inherits_highest_ancestor_grant(self):
        self._chain()
        anvil = self._repo("crew", "anvil")
        self._link(self.parent, anvil, "write")
        eff = self.perms.effective_permission(self.org.id, self.child.id, anvil)
        self.assertEqual(eff.permission, "write")
        self.assertEqual(eff.granted_by_team_id, self.parent.id)
        self.assertEqual(eff.granted_by_team_name, "Parent Team")

    def test_effective_own_higher_grant_wins(self):
        self._chain()
        anvil = self._repo("crew", "anvil")
        self._link(self.parent, anvil, "read")
        self._link(self.child, anvil, "admin")
        eff = self.perms.effective_permission(self.org.id, self.child.id, anvil)
        self.assertEqual(eff.permission, "admin")
        self.assertEqual(eff.granted_by_team_id, self.child.id)

    def test_effective_ancestor_higher_grant_lifts_child(self):
        self._chain()
        anvil = self._repo("crew", "anvil")
        self._link(self.parent, anvil, "maintain")
        self._link(self.child, anvil, "triage")
        eff = self.perms.effective_permission(self.org.id, self.child.id, anvil)
        self.assertEqual(eff.permission, "maintain")
        self.assertEqual(eff.granted_by_team_id, self.parent.id)

    def test_effective_tie_goes_to_own_grant(self):
        self._chain()
        anvil = self._repo("crew", "anvil")
        self._link(self.parent, anvil, "write")
        self._link(self.child, anvil, "write")
        eff = self.perms.effective_permission(self.org.id, self.child.id, anvil)
        self.assertEqual(eff.permission, "write")
        self.assertEqual(eff.granted_by_team_id, self.child.id)

    def test_inheritance_never_flows_up_or_sideways(self):
        self._chain()
        anvil = self._repo("crew", "anvil")
        self._link(self.child, anvil, "admin")
        self.assertIsNone(self.perms.effective_permission(self.org.id, self.parent.id, anvil))
        self.assertIsNone(self.perms.effective_permission(self.org.id, self.sibling.id, anvil))

    def test_effective_permissions_union_named_once(self):
        self._chain()
        anvil = self._repo("crew", "anvil")
        boat = self._repo("crew", "boat")
        self._link(self.parent, anvil, "write")
        self._link(self.parent, boat, "read")
        self._link(self.child, anvil, "triage")
        eff = self.perms.effective_permissions(self.org.id, self.child.id)
        self.assertEqual([(p.name, p.permission, p.granted_by_team_id) for p in eff],
                         [("anvil", "write", self.parent.id),
                          ("boat", "read", self.parent.id)])
        self.assertEqual(self.perms.effective_permissions(self.org.id, self.sibling.id)[0].permission, "write")

    # pages and settings map
    def test_permissions_page_escaped_with_ladder(self):
        org2 = self.orgs.create_organization(self.creator.id, "fleet", display_name="Fleet <script>alert(1)</script>")
        team = self.teams.create_team(self.creator.id, org2.id, "Core <b>Team</b>")
        repo_id = self._repo("fleet", "anvil")
        self.teams.link_repo(self.creator.id, org2.id, team.id, repo_id)
        self.perms.set_permission(self.creator.id, org2.id, team.id, repo_id, "maintain")
        html = render_team_permissions_page(
            org2, team,
            self.perms.list_permissions(org2.id, team.id),
            self.perms.effective_permissions(org2.id, team.id))
        self.assertNotIn("<script>", html)
        self.assertNotIn("<b>Team</b>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("fleet/anvil", html)
        self.assertIn("Maintain", html)
        self.assertIn("Read / Triage / Write / Maintain / Admin", html)
        self.assertIn("S-189", html)
        self.assertIn("S-190", html)

    def test_permissions_page_honest_empty(self):
        html = render_team_permissions_page(self.org, self.child, [], [])
        self.assertIn("no direct permission", html)
        self.assertIn("No effective permissions", html)

    def test_settings_area_team_permissions_available(self):
        by_key = {a["key"]: a for a in settings_areas()}
        self.assertTrue(by_key["team_permissions"]["available"])
        self.assertEqual(by_key["team_permissions"]["slice"], "S-189")

    def test_team_page_shows_permission(self):
        from samverk.teams import render_team_page
        anvil = self._repo("crew", "anvil")
        self._link(self.child, anvil, "write")
        html = render_team_page(self.org, self.child,
                                self.teams.list_members(self.org.id, self.child.id),
                                self.teams.list_repos(self.org.id, self.child.id))
        self.assertIn("crew/anvil", html)
        self.assertIn("Write", html)
        self.assertIn("S-189", html)


if __name__ == "__main__":
    unittest.main()
