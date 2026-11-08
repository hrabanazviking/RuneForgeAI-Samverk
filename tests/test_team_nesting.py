"""S-188 acceptance battery: nested teams.

Acceptance (roadmap S-188): Nested teams — parent/child
teams with permission inheritance documented and
visualised before saving.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.organization_members import OrgMembershipStore
from samverk.organizations import (
    OrganizationError, OrganizationStore)
from samverk.team_nesting import (
    NestedTeamStore, ancestor_ids, descendant_ids,
    render_nesting_preview, render_team_tree_page,
    would_create_cycle)
from samverk.teams import TeamStore


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class NestedTeamTests(unittest.TestCase):
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
        self.members.add_member(self.creator.id, self.org.id, self.bryn.id)
        self.teams = TeamStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.nesting = NestedTeamStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.parent = self.teams.create_team(self.creator.id, self.org.id, "Parent Team")
        self.child = self.teams.create_team(self.creator.id, self.org.id, "Child Team")
        self.grandchild = self.teams.create_team(self.creator.id, self.org.id, "Grandchild Team")

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

    def _chain(self):
        self.nesting.set_parent(self.creator.id, self.org.id, self.child.id, self.parent.id)
        self.nesting.set_parent(self.creator.id, self.org.id, self.grandchild.id, self.child.id)

    # pure rules
    def test_pure_cycle_and_chain_rules(self):
        parent_of = {1: None, 2: 1, 3: 2}
        self.assertEqual(ancestor_ids(parent_of, 3), [2, 1])
        self.assertEqual(ancestor_ids(parent_of, 1), [])
        self.assertEqual(descendant_ids(parent_of, 1), [2, 3])
        self.assertFalse(would_create_cycle(parent_of, 1, None))
        self.assertTrue(would_create_cycle(parent_of, 1, 1))
        self.assertTrue(would_create_cycle(parent_of, 1, 3))
        self.assertFalse(would_create_cycle(parent_of, 3, 1))

    def test_schema_is_71(self):
        self.assertEqual(schema_version(self.conn), 87)

    # create with parent (S-187 extension)
    def test_create_team_with_parent(self):
        team = self.teams.create_team(self.creator.id, self.org.id, "Leaf Team", parent_team_id=self.parent.id)
        self.assertEqual(team.parent_team_id, self.parent.id)
        self.assertEqual(self.nesting.get_parent(self.org.id, team.id).id, self.parent.id)

    def test_create_team_parent_missing_or_cross_org_refused(self):
        self.assertEqual(
            self._reason(self.teams.create_team, self.creator.id, self.org.id, "Leaf", parent_team_id=99999),
            "parent_not_found")
        foreign = self.teams.create_team(self.creator.id, self.other_org.id, "Foreign Team")
        self.assertEqual(
            self._reason(self.teams.create_team, self.creator.id, self.org.id, "Leaf", parent_team_id=foreign.id),
            "parent_not_in_org")

    # set / clear parent
    def test_set_parent_happy_and_audited(self):
        before = self._updates()
        updated = self.nesting.set_parent(self.creator.id, self.org.id, self.child.id, self.parent.id)
        self.assertEqual(updated.parent_team_id, self.parent.id)
        self.assertEqual([t.id for t in self.nesting.list_children(self.org.id, self.parent.id)], [self.child.id])
        self.assertEqual(self._updates(), before + 1)

    def test_clear_parent_makes_root(self):
        self._chain()
        updated = self.nesting.set_parent(self.creator.id, self.org.id, self.child.id, None)
        self.assertIsNone(updated.parent_team_id)
        self.assertEqual(self.nesting.ancestors(self.org.id, self.grandchild.id), [self.teams.get_team(self.org.id, self.child.id)])

    def test_set_parent_refused_for_plain_member(self):
        self.assertEqual(
            self._reason(self.nesting.set_parent, self.yrsa.id, self.org.id, self.child.id, self.parent.id),
            "not_org_owner")
        self.assertIsNone(self.teams.get_team(self.org.id, self.child.id).parent_team_id)

    def test_self_parent_and_cycles_refused(self):
        self.assertEqual(
            self._reason(self.nesting.set_parent, self.creator.id, self.org.id, self.child.id, self.child.id),
            "team_parent_is_self")
        self._chain()
        self.assertEqual(
            self._reason(self.nesting.set_parent, self.creator.id, self.org.id, self.parent.id, self.grandchild.id),
            "team_parent_cycle")
        self.assertIsNone(self.teams.get_team(self.org.id, self.parent.id).parent_team_id)

    def test_set_parent_missing_and_cross_org_refused(self):
        self.assertEqual(
            self._reason(self.nesting.set_parent, self.creator.id, self.org.id, self.child.id, 99999),
            "parent_not_found")
        foreign = self.teams.create_team(self.creator.id, self.other_org.id, "Foreign Team")
        self.assertEqual(
            self._reason(self.nesting.set_parent, self.creator.id, self.org.id, self.child.id, foreign.id),
            "parent_not_in_org")

    def test_reparent_moves_whole_subtree(self):
        self._chain()
        other_root = self.teams.create_team(self.creator.id, self.org.id, "Other Root")
        self.nesting.set_parent(self.creator.id, self.org.id, self.child.id, other_root.id)
        self.assertEqual(
            [t.name for t in self.nesting.ancestors(self.org.id, self.grandchild.id)],
            ["Child Team", "Other Root"])

    def test_ancestors_and_descendants(self):
        self._chain()
        self.assertEqual(
            [t.name for t in self.nesting.ancestors(self.org.id, self.grandchild.id)],
            ["Child Team", "Parent Team"])
        self.assertEqual(
            [t.name for t in self.nesting.descendants(self.org.id, self.parent.id)],
            ["Child Team", "Grandchild Team"])

    # inheritance flows down
    def test_effective_members_flow_down_never_up(self):
        self.teams.add_member(self.creator.id, self.org.id, self.parent.id, self.yrsa.id)
        self.teams.add_member(self.creator.id, self.org.id, self.grandchild.id, self.bryn.id)
        self._chain()
        child_names = [m.username for m in self.nesting.effective_members(self.org.id, self.child.id)]
        self.assertIn("yrsa", child_names)
        grand_names = [m.username for m in self.nesting.effective_members(self.org.id, self.grandchild.id)]
        self.assertIn("yrsa", grand_names)
        self.assertIn("brynhild", grand_names)
        parent_names = [m.username for m in self.nesting.effective_members(self.org.id, self.parent.id)]
        self.assertNotIn("brynhild", parent_names)
        self.assertEqual(len(grand_names), len(set(grand_names)))

    def test_effective_repos_flow_down(self):
        repo_a = self._repo("crew", "alpha")
        repo_b = self._repo("crew", "beta")
        self.teams.link_repo(self.creator.id, self.org.id, self.parent.id, repo_a)
        self.teams.link_repo(self.creator.id, self.org.id, self.child.id, repo_b)
        self.teams.link_repo(self.creator.id, self.org.id, self.child.id, repo_a)
        self._chain()
        names = [r.name for r in self.nesting.effective_repos(self.org.id, self.grandchild.id)]
        self.assertEqual(sorted(names), ["alpha", "beta"])
        parent_names = [r.name for r in self.nesting.effective_repos(self.org.id, self.parent.id)]
        self.assertEqual(parent_names, ["alpha"])

    # preview before saving
    def test_preview_shows_effect_and_writes_nothing(self):
        self.teams.add_member(self.creator.id, self.org.id, self.parent.id, self.yrsa.id)
        repo_a = self._repo("crew", "alpha")
        self.teams.link_repo(self.creator.id, self.org.id, self.parent.id, repo_a)
        before = self._updates()
        preview = self.nesting.preview_parent_change(self.org.id, self.child.id, self.parent.id)
        self.assertTrue(preview.allowed)
        self.assertEqual(preview.ancestors_after, ("Parent Team",))
        self.assertIn("yrsa", preview.inherited_members)
        self.assertIn("crew/alpha", preview.inherited_repos)
        self.assertIsNone(self.teams.get_team(self.org.id, self.child.id).parent_team_id)
        self.assertEqual(self._updates(), before)

    def test_preview_reports_cycle_without_raising(self):
        self._chain()
        preview = self.nesting.preview_parent_change(self.org.id, self.parent.id, self.grandchild.id)
        self.assertFalse(preview.allowed)
        self.assertEqual(preview.reason, "team_parent_cycle")

    def test_preview_reports_lost_inheritance_on_clear(self):
        self.teams.add_member(self.creator.id, self.org.id, self.parent.id, self.yrsa.id)
        self._chain()
        preview = self.nesting.preview_parent_change(self.org.id, self.child.id, None)
        self.assertTrue(preview.allowed)
        self.assertEqual(preview.ancestors_after, ())
        self.assertIn("yrsa", preview.lost_members)

    # renderers
    def test_render_preview_page_escapes_and_states_law(self):
        preview = self.nesting.preview_parent_change(self.org.id, self.child.id, self.parent.id)
        page = render_nesting_preview(self.org, preview)
        self.assertIn("Before you save", page)
        self.assertIn("Nothing has been saved yet", page)
        self.assertIn("Parent Team", page)

    def test_render_tree_page_nests_children(self):
        self._chain()
        page = render_team_tree_page(self.org, self.teams.list_teams(self.org.id))
        self.assertIn("Parent Team", page)
        self.assertIn("Child Team", page)
        self.assertIn("flows down, never up", page)


if __name__ == "__main__":
    unittest.main()
