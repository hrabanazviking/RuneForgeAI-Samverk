"""S-203 acceptance battery: instance-wide groups seam.

Acceptance (roadmap S-203): Instance-wide groups seam
— site-level groups share the team machinery (used by
admin policy in Part XVIII).

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.instance_groups import (
    InstanceGroupStore, group_slug, render_group_nesting_preview,
    render_group_page, render_group_tree_page, render_groups_page)
from samverk.organizations import OrganizationError


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class InstanceGroupTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.volmarr = self.accounts.register("volmarr", "correct horse battery")
        self.yrsa = self.accounts.register("yrsa", "correct horse battery")
        self.bryn = self.accounts.register("brynhild", "correct horse battery")
        self.admin = self.accounts.register("sitemod", "correct horse battery")
        self.admin2 = self.accounts.register("watcher", "correct horse battery")
        with self.conn:
            self.conn.execute("UPDATE users SET is_admin = 1 WHERE id IN (?, ?)", (self.admin.id, self.admin2.id))
        self.groups = InstanceGroupStore(self.conn, self.accounts, self.audit, time_fn=self.clock)

    def _changes(self):
        return self.conn.execute("SELECT COUNT(*) c FROM audit_log WHERE action = 'admin.settings.change'").fetchone()["c"]

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(OrganizationError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def _repo(self, owner, name):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO repositories (owner, owner_lower, name, name_lower, created_by, created_at, description, visibility) VALUES (?, ?, ?, ?, ?, ?, '', 'public')",
                (owner, owner.lower(), name, name.lower(), self.volmarr.id, 1_700_000_000))
        return int(cur.lastrowid)

    # schema pin
    def test_pins_schema_80_taxonomy_123(self):
        self.assertEqual(schema_version(self.conn), 107)
        self.assertEqual(db.MIGRATIONS[-1][0], 107)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)
        tables = {r["name"] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertIn("instance_groups", tables)
        self.assertIn("instance_group_members", tables)
        self.assertIn("instance_group_repositories", tables)

    def test_fresh_database_migrates_to_80(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.init_db(Path(td) / "fresh.db")
            self.assertEqual(db.schema_version(conn), 107)
            conn.close()

    # creation
    def test_create_group_creator_is_first_member(self):
        before = self._changes()
        group = self.groups.create_group(self.admin.id, "Core Crew", description="The core crew.")
        self.assertEqual(group.name, "Core Crew")
        self.assertEqual(group.name_lower, "core-crew")
        self.assertEqual(group_slug("Core Crew"), "core-crew")
        self.assertEqual(group.description, "The core crew.")
        self.assertEqual(group.privacy, "visible")
        self.assertIsNone(group.parent_group_id)
        self.assertTrue(self.groups.is_group_member(self.admin.id, group.id))
        self.assertEqual([m.username for m in self.groups.list_members(group.id)], ["sitemod"])
        self.assertEqual(self._changes(), before + 1)
        self.assertEqual(self.groups.get_group_by_name("core crew").id, group.id)
        self.assertIsNone(self.groups.get_group_by_name(42))

    def test_create_requires_site_admin(self):
        self.assertEqual(self._reason(self.groups.create_group, self.volmarr.id, "Crew"), "not_site_admin")
        self.assertEqual(self._reason(self.groups.create_group, 99999, "Crew"), "no_such_user")
        self.assertEqual(self.groups.list_groups(), [])
        self.assertEqual(self._changes(), 0)

    def test_create_refuses_slug_clash_and_bad_names(self):
        self.groups.create_group(self.admin.id, "Core Crew")
        self.assertEqual(self._reason(self.groups.create_group, self.admin2.id, "core crew"), "group_taken")
        self.assertEqual(self._reason(self.groups.create_group, self.admin.id, "!!!"), "team_invalid")
        self.assertEqual(self._reason(self.groups.create_group, self.admin.id, "Crew", privacy="hidden"), "privacy_invalid")
        self.assertEqual(len(self.groups.list_groups()), 1)

    def test_update_group_description_and_privacy(self):
        group = self.groups.create_group(self.admin.id, "Crew", description="Old.")
        updated = self.groups.update_group(self.admin.id, group.id, description="New words.", privacy="secret")
        self.assertEqual(updated.description, "New words.")
        self.assertEqual(updated.privacy, "secret")
        cleared = self.groups.update_group(self.admin.id, group.id, description="")
        self.assertIsNone(cleared.description)
        self.assertEqual(cleared.privacy, "secret")
        self.assertEqual(self._reason(self.groups.update_group, self.yrsa.id, group.id, description="Nope."), "not_site_admin")
        self.assertEqual(self._reason(self.groups.update_group, self.admin.id, 99999, description="Nope."), "group_not_found")

    # visibility law
    def test_secret_group_is_not_there_to_non_members(self):
        secret = self.groups.create_group(self.admin.id, "Hidden Crew", privacy="secret")
        visible = self.groups.create_group(self.admin.id, "Open Crew")
        self.assertEqual(self._reason(self.groups.get_group_for_viewer, self.yrsa.id, secret.id), "group_not_found")
        self.assertEqual(self._reason(self.groups.get_group_for_viewer, None, secret.id), "group_not_found")
        self.assertEqual(self.groups.get_group_for_viewer(self.admin.id, secret.id).id, secret.id)
        self.assertEqual(self.groups.get_group_for_viewer(self.admin2.id, secret.id).id, secret.id)
        self.groups.add_member(self.admin.id, secret.id, "yrsa")
        self.assertEqual(self.groups.get_group_for_viewer(self.yrsa.id, secret.id).id, secret.id)
        self.assertEqual([g.id for g in self.groups.list_groups_for_viewer(self.bryn.id)], [visible.id])
        self.assertEqual([g.id for g in self.groups.list_groups_for_viewer(None)], [visible.id])
        self.assertEqual({g.id for g in self.groups.list_groups_for_viewer(self.yrsa.id)}, {secret.id, visible.id})

    # members
    def test_add_and_remove_member(self):
        group = self.groups.create_group(self.admin.id, "Crew")
        membership = self.groups.add_member(self.admin.id, group.id, "yrsa")
        self.assertEqual(membership.username, "yrsa")
        self.assertEqual(membership.added_by, self.admin.id)
        by_id = self.groups.add_member(self.admin.id, group.id, self.bryn.id)
        self.assertEqual(by_id.username, "brynhild")
        self.assertEqual([m.username for m in self.groups.list_members(group.id)], ["brynhild", "sitemod", "yrsa"])
        self.assertEqual([g.id for g in self.groups.groups_for_user(self.yrsa.id)], [group.id])
        self.assertEqual(self._reason(self.groups.add_member, self.admin.id, group.id, "yrsa"), "already_group_member")
        self.assertEqual(self._reason(self.groups.add_member, self.admin.id, group.id, "ghost"), "no_such_user")
        self.assertEqual(self._reason(self.groups.add_member, self.yrsa.id, group.id, "volmarr"), "not_site_admin")
        self.groups.remove_member(self.admin.id, group.id, "yrsa")
        self.assertFalse(self.groups.is_group_member(self.yrsa.id, group.id))
        self.assertIsNone(self.groups.get_membership(group.id, self.yrsa.id))
        self.assertEqual(self._reason(self.groups.remove_member, self.admin.id, group.id, "yrsa"), "not_group_member")
        self.assertEqual(self._reason(self.groups.groups_for_user, 99999), "no_such_user")

    # repository links and the ladder
    def test_link_repo_starts_at_read_and_unlinks(self):
        group = self.groups.create_group(self.admin.id, "Crew")
        repo_id = self._repo("volmarr", "samverk")
        link = self.groups.link_repo(self.admin.id, group.id, repo_id)
        self.assertEqual(link.permission, "read")
        self.assertEqual(link.full_name if hasattr(link, "full_name") else f"{link.owner}/{link.name}", "volmarr/samverk")
        self.assertEqual([r.repo_id for r in self.groups.list_repos(group.id)], [repo_id])
        self.assertEqual(self._reason(self.groups.link_repo, self.admin.id, group.id, repo_id), "already_linked")
        self.assertEqual(self._reason(self.groups.link_repo, self.admin.id, group.id, 99999), "repo_not_found")
        self.assertEqual(self._reason(self.groups.link_repo, self.yrsa.id, group.id, repo_id), "not_site_admin")
        self.groups.unlink_repo(self.admin.id, group.id, repo_id)
        self.assertIsNone(self.groups.get_link(group.id, repo_id))
        self.assertEqual(self._reason(self.groups.unlink_repo, self.admin.id, group.id, repo_id), "not_linked")

    def test_set_permission_moves_rungs_and_noop_is_silent(self):
        group = self.groups.create_group(self.admin.id, "Crew")
        repo_id = self._repo("volmarr", "samverk")
        self.assertEqual(self._reason(self.groups.set_permission, self.admin.id, group.id, repo_id, "write"), "not_linked")
        self.groups.link_repo(self.admin.id, group.id, repo_id)
        before = self._changes()
        same = self.groups.set_permission(self.admin.id, group.id, repo_id, "read")
        self.assertEqual(same.permission, "read")
        self.assertEqual(self._changes(), before)
        moved = self.groups.set_permission(self.admin.id, group.id, repo_id, " Maintain ")
        self.assertEqual(moved.permission, "maintain")
        self.assertEqual(self._changes(), before + 1)
        self.assertEqual(self._reason(self.groups.set_permission, self.admin.id, group.id, repo_id, "owner"), "role_invalid")
        self.assertEqual(self.groups.get_link(group.id, repo_id).permission, "maintain")

    def test_effective_permission_highest_in_chain_wins(self):
        parent = self.groups.create_group(self.admin.id, "Elders")
        child = self.groups.create_group(self.admin.id, "Youngers", parent_group_id=parent.id)
        repo_id = self._repo("volmarr", "samverk")
        self.assertIsNone(self.groups.effective_permission(child.id, repo_id))
        self.groups.link_repo(self.admin.id, parent.id, repo_id)
        self.groups.set_permission(self.admin.id, parent.id, repo_id, "write")
        eff = self.groups.effective_permission(child.id, repo_id)
        self.assertEqual(eff.permission, "write")
        self.assertEqual(eff.granted_by_group_id, parent.id)
        self.assertEqual(eff.granted_by_group_name, "Elders")
        self.groups.link_repo(self.admin.id, child.id, repo_id)
        self.groups.set_permission(self.admin.id, child.id, repo_id, "admin")
        eff = self.groups.effective_permission(child.id, repo_id)
        self.assertEqual(eff.permission, "admin")
        self.assertEqual(eff.granted_by_group_id, child.id)
        own = self.groups.effective_permission(parent.id, repo_id)
        self.assertEqual(own.permission, "write")
        self.assertEqual(self._reason(self.groups.effective_permission, child.id, 99999), "repo_not_found")
        self.assertEqual(self._reason(self.groups.effective_permission, 99999, repo_id), "group_not_found")

    # nesting
    def test_nesting_inherits_members_and_repos_down_only(self):
        parent = self.groups.create_group(self.admin.id, "Elders")
        self.groups.add_member(self.admin.id, parent.id, "yrsa")
        repo_id = self._repo("volmarr", "samverk")
        self.groups.link_repo(self.admin.id, parent.id, repo_id)
        child = self.groups.create_group(self.admin.id, "Youngers", parent_group_id=parent.id)
        self.assertEqual(self.groups.get_parent(child.id).id, parent.id)
        self.assertEqual([g.id for g in self.groups.list_children(parent.id)], [child.id])
        self.assertEqual([g.id for g in self.groups.ancestors(child.id)], [parent.id])
        self.assertEqual([g.id for g in self.groups.descendants(parent.id)], [child.id])
        self.assertEqual({m.username for m in self.groups.effective_members(child.id)}, {"sitemod", "yrsa"})
        self.assertEqual([r.repo_id for r in self.groups.effective_repos(child.id)], [repo_id])
        self.assertEqual({m.username for m in self.groups.effective_members(parent.id)}, {"sitemod", "yrsa"})
        self.assertNotIn("brynhild", {m.username for m in self.groups.effective_members(parent.id)})

    def test_set_parent_cycle_and_self_refused(self):
        a = self.groups.create_group(self.admin.id, "Alpha")
        b = self.groups.create_group(self.admin.id, "Beta", parent_group_id=a.id)
        self.assertEqual(self._reason(self.groups.set_parent, self.admin.id, a.id, a.id), "group_parent_is_self")
        self.assertEqual(self._reason(self.groups.set_parent, self.admin.id, a.id, b.id), "group_parent_cycle")
        self.assertEqual(self._reason(self.groups.set_parent, self.admin.id, a.id, 99999), "parent_not_found")
        self.assertEqual(self._reason(self.groups.set_parent, self.yrsa.id, a.id, None), "not_site_admin")
        cleared = self.groups.set_parent(self.admin.id, b.id, None)
        self.assertIsNone(cleared.parent_group_id)
        self.assertIsNone(self.groups.get_parent(b.id))

    def test_preview_parent_change_is_a_pure_read(self):
        parent = self.groups.create_group(self.admin.id, "Elders")
        self.groups.add_member(self.admin.id, parent.id, "yrsa")
        repo_id = self._repo("volmarr", "samverk")
        self.groups.link_repo(self.admin.id, parent.id, repo_id)
        child = self.groups.create_group(self.admin.id, "Youngers")
        before = self._changes()
        preview = self.groups.preview_parent_change(child.id, parent.id)
        self.assertTrue(preview.allowed)
        self.assertIsNone(preview.reason)
        self.assertEqual(preview.ancestors_after, ("Elders",))
        self.assertIn("yrsa", preview.inherited_members)
        self.assertIn("volmarr/samverk", preview.inherited_repos)
        self.assertEqual(preview.lost_members, ())
        self.assertIsNone(self.groups.get_parent(child.id))
        self.assertEqual(self._changes(), before)
        refused = self.groups.preview_parent_change(parent.id, parent.id)
        self.assertFalse(refused.allowed)
        self.assertEqual(refused.reason, "group_parent_is_self")
        html = render_group_nesting_preview(preview)
        self.assertIn("Before you save: Youngers", html)
        self.assertIn("yrsa", html)

    # the Part XVIII seam
    def test_seam_effective_membership_counts_inheritance(self):
        parent = self.groups.create_group(self.admin.id, "Elders")
        child = self.groups.create_group(self.admin.id, "Youngers", parent_group_id=parent.id)
        grandchild = self.groups.create_group(self.admin.id, "Small Ones", parent_group_id=child.id)
        self.groups.add_member(self.admin.id, parent.id, "yrsa")
        self.assertTrue(self.groups.is_effective_member(self.yrsa.id, parent.id))
        self.assertTrue(self.groups.is_effective_member(self.yrsa.id, child.id))
        self.assertTrue(self.groups.is_effective_member(self.yrsa.id, grandchild.id))
        self.assertFalse(self.groups.is_effective_member(self.bryn.id, grandchild.id))
        self.assertFalse(self.groups.is_group_member(self.yrsa.id, grandchild.id))
        self.assertEqual([g.name for g in self.groups.effective_groups_for_user(self.yrsa.id)], ["Elders", "Small Ones", "Youngers"])
        self.assertEqual(self.groups.effective_groups_for_user(self.bryn.id), [])
        self.assertEqual(self._reason(self.groups.is_effective_member, 99999, child.id), "no_such_user")
        self.assertEqual(self._reason(self.groups.effective_groups_for_user, 99999), "no_such_user")

    def test_seam_group_role_for_user_resolves_highest(self):
        elders = self.groups.create_group(self.admin.id, "Elders")
        youngers = self.groups.create_group(self.admin.id, "Youngers", parent_group_id=elders.id)
        keepers = self.groups.create_group(self.admin.id, "Keepers")
        repo_id = self._repo("volmarr", "samverk")
        other_id = self._repo("yrsa", "runmal")
        self.groups.add_member(self.admin.id, elders.id, "yrsa")
        self.groups.add_member(self.admin.id, keepers.id, "yrsa")
        self.assertIsNone(self.groups.group_role_for_user(self.yrsa.id, repo_id))
        self.groups.link_repo(self.admin.id, elders.id, repo_id)
        self.groups.set_permission(self.admin.id, elders.id, repo_id, "write")
        self.groups.link_repo(self.admin.id, keepers.id, repo_id)
        self.groups.set_permission(self.admin.id, keepers.id, repo_id, "maintain")
        role = self.groups.group_role_for_user(self.yrsa.id, repo_id)
        self.assertEqual(role.role, "maintain")
        self.assertEqual(role.via_group_name, "Keepers")
        self.assertEqual(role.granted_by_group_name, "Keepers")
        self.assertEqual(role.full_name, "volmarr/samverk")
        inherited = self.groups.group_role_for_user(self.yrsa.id, other_id)
        self.assertIsNone(inherited)
        self.groups.link_repo(self.admin.id, youngers.id, other_id)
        via_child = self.groups.group_role_for_user(self.yrsa.id, other_id)
        self.assertEqual(via_child.role, "read")
        self.assertEqual(via_child.via_group_name, "Youngers")
        self.assertEqual(via_child.granted_by_group_name, "Youngers")
        self.assertIsNone(self.groups.group_role_for_user(self.bryn.id, repo_id))
        self.assertEqual(self._reason(self.groups.group_role_for_user, self.yrsa.id, 99999), "repo_not_found")

    # audit
    def test_audit_rides_admin_settings_change_on_instance(self):
        group = self.groups.create_group(self.admin.id, "Crew", source_ip="192.0.2.1")
        rows = self.conn.execute("SELECT target_kind, target_id, detail FROM audit_log WHERE action = 'admin.settings.change'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["target_kind"], "instance")
        self.assertEqual(rows[0]["target_id"], "crew")
        detail = json.loads(rows[0]["detail"])
        self.assertEqual(detail["fields"], "instance_groups")
        self.assertEqual(detail["action"], "create")
        self.assertEqual(detail["group"], "crew")
        self.groups.add_member(self.admin.id, group.id, "yrsa")
        rows = self.conn.execute("SELECT detail FROM audit_log WHERE action = 'admin.settings.change' ORDER BY seq").fetchall()
        self.assertEqual(json.loads(rows[-1]["detail"])["target"], "yrsa")
        before = self._changes()
        self._reason(self.groups.add_member, self.admin.id, group.id, "yrsa")
        self.assertEqual(self._changes(), before)

    # renders
    def test_renders_escape_and_say_the_law(self):
        group = self.groups.create_group(self.admin.id, "Crew <script>", description="Notes <b>here</b>", privacy="secret")
        self.groups.add_member(self.admin.id, group.id, "yrsa")
        repo_id = self._repo("volmarr", "samverk")
        self.groups.link_repo(self.admin.id, group.id, repo_id)
        page = render_group_page(group, self.groups.list_members(group.id), self.groups.list_repos(group.id))
        self.assertIn("Crew &lt;script&gt;", page)
        self.assertNotIn("<script>", page)
        self.assertIn("Notes &lt;b&gt;here&lt;/b&gt;", page)
        self.assertIn("Privacy: Secret", page)
        self.assertIn("volmarr/samverk — Read", page)
        self.assertIn("yrsa", page)
        listing = render_groups_page(self.groups.list_groups())
        self.assertIn("Instance-wide groups", listing)
        self.assertIn("Secret", listing)
        self.assertIn("No groups yet.", render_groups_page([]))
        child = self.groups.create_group(self.admin.id, "Youngers", parent_group_id=group.id)
        tree = render_group_tree_page(self.groups.list_groups())
        self.assertIn("Inheritance flows down, never up.", tree)
        self.assertIn("Youngers", tree)


if __name__ == "__main__":
    unittest.main()
