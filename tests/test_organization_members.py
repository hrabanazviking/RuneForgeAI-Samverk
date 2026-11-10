"""S-186 acceptance battery: org membership.

Acceptance (roadmap S-186): Org membership — owners
and members; the last owner cannot leave or be
removed (invariant proven in test).

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
from samverk.organization_members import (
    OrgMembershipStore, decide_removal, decide_role_change,
    render_members_page, role_word, validate_role)
from samverk.organizations import (
    OrganizationError, OrganizationStore, settings_areas)


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class OrgMembershipTests(unittest.TestCase):
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
        self.members = OrgMembershipStore(self.conn, self.accounts, self.audit, time_fn=self.clock)

    def _updates(self):
        return self.conn.execute("SELECT COUNT(*) c FROM audit_log WHERE action = 'auth.organization.update'").fetchone()["c"]

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(OrganizationError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    # founding owner
    def test_creator_seeded_as_owner(self):
        self.assertEqual(self.members.role_for(self.creator.id, self.org.id), "owner")
        self.assertTrue(self.members.is_owner(self.creator.id, self.org.id))
        self.assertTrue(self.members.is_member(self.creator.id, self.org.id))
        self.assertEqual(self.members.count_owners(self.org.id), 1)
        listed = self.members.list_members(self.org.id)
        self.assertEqual([m.username for m in listed], ["volmarr"])
        self.assertEqual(listed[0].role, "owner")

    def test_seeding_is_idempotent(self):
        self.members.list_members(self.org.id)
        self.members.list_members(self.org.id)
        self.members.role_for(self.creator.id, self.org.id)
        rows = self.conn.execute("SELECT COUNT(*) c FROM organization_members WHERE org_id = ?", (self.org.id,)).fetchone()["c"]
        self.assertEqual(rows, 1)

    # add
    def test_add_member_happy_and_audits_once(self):
        made = self.members.add_member(self.creator.id, self.org.id, self.yrsa.id)
        self.assertEqual(made.role, "member")
        self.assertEqual(made.username, "yrsa")
        self.assertEqual(self.members.role_for(self.yrsa.id, self.org.id), "member")
        self.assertEqual(self._updates(), 1)

    def test_add_member_by_username(self):
        made = self.members.add_member(self.creator.id, self.org.id, "YRSA", role="owner")
        self.assertEqual(made.user_id, self.yrsa.id)
        self.assertEqual(made.role, "owner")
        self.assertEqual(self.members.count_owners(self.org.id), 2)

    def test_add_member_by_site_admin(self):
        made = self.members.add_member(self.admin.id, self.org.id, self.yrsa.id)
        self.assertEqual(made.role, "member")

    def test_add_refused_for_plain_member_actor(self):
        self.members.add_member(self.creator.id, self.org.id, self.yrsa.id)
        reason = self._reason(self.members.add_member, self.yrsa.id, self.org.id, self.bryn.id)
        self.assertEqual(reason, "not_org_owner")
        self.assertIsNone(self.members.role_for(self.bryn.id, self.org.id))

    def test_add_refused_for_non_member_actor(self):
        reason = self._reason(self.members.add_member, self.bryn.id, self.org.id, self.yrsa.id)
        self.assertEqual(reason, "not_org_owner")

    def test_add_duplicate_refused(self):
        self.members.add_member(self.creator.id, self.org.id, self.yrsa.id)
        reason = self._reason(self.members.add_member, self.creator.id, self.org.id, self.yrsa.id)
        self.assertEqual(reason, "already_member")
        reason = self._reason(self.members.add_member, self.creator.id, self.org.id, self.creator.id)
        self.assertEqual(reason, "already_member")

    def test_add_unknown_target_refused(self):
        self.assertEqual(self._reason(self.members.add_member, self.creator.id, self.org.id, 999999), "no_such_user")
        self.assertEqual(self._reason(self.members.add_member, self.creator.id, self.org.id, "ghost"), "no_such_user")

    def test_add_unknown_org_refused(self):
        self.assertEqual(self._reason(self.members.add_member, self.creator.id, 424242, self.yrsa.id), "org_not_found")

    def test_add_unknown_actor_refused(self):
        self.assertEqual(self._reason(self.members.add_member, 999999, self.org.id, self.yrsa.id), "no_such_user")

    def test_add_invalid_role_refused(self):
        self.assertEqual(self._reason(self.members.add_member, self.creator.id, self.org.id, self.yrsa.id, role="superuser"), "role_invalid")
        self.assertIsNone(self.members.role_for(self.yrsa.id, self.org.id))
        with self.assertRaises(OrganizationError) as ctx:
            validate_role("superuser")
        self.assertEqual(ctx.exception.reason, "role_invalid")
        self.assertEqual(validate_role(" Owner "), "owner")
        self.assertEqual(validate_role("member"), "member")

    # reads
    def test_list_order_owners_first_then_username(self):
        self.members.add_member(self.creator.id, self.org.id, self.bryn.id)
        self.members.add_member(self.creator.id, self.org.id, self.yrsa.id, role="owner")
        listed = self.members.list_members(self.org.id)
        self.assertEqual([(m.username, m.role) for m in listed], [("volmarr", "owner"), ("yrsa", "owner"), ("brynhild", "member")])

    def test_role_matrix_for_non_member(self):
        self.assertIsNone(self.members.role_for(self.bryn.id, self.org.id))
        self.assertFalse(self.members.is_owner(self.bryn.id, self.org.id))
        self.assertFalse(self.members.is_member(self.bryn.id, self.org.id))
        self.assertEqual(self._reason(self.members.role_for, self.bryn.id, 424242), "org_not_found")

    # remove
    def test_remove_member_happy(self):
        self.members.add_member(self.creator.id, self.org.id, self.yrsa.id)
        self.members.remove_member(self.creator.id, self.org.id, self.yrsa.id)
        self.assertIsNone(self.members.role_for(self.yrsa.id, self.org.id))
        self.assertEqual(self._updates(), 2)

    def test_remove_last_owner_refused_and_unchanged(self):
        before = self._updates()
        reason = self._reason(self.members.remove_member, self.admin.id, self.org.id, self.creator.id)
        self.assertEqual(reason, "last_owner")
        self.assertEqual(self.members.role_for(self.creator.id, self.org.id), "owner")
        self.assertEqual(self.members.count_owners(self.org.id), 1)
        self.assertEqual(self._updates(), before)

    def test_pure_helpers_prove_last_owner_rule(self):
        self.assertEqual(decide_removal("owner", 1), "last_owner")
        self.assertIsNone(decide_removal("owner", 2))
        self.assertIsNone(decide_removal("member", 1))
        self.assertIsNone(decide_removal(None, 0))
        self.assertEqual(decide_role_change("owner", "member", 1), "last_owner")
        self.assertIsNone(decide_role_change("owner", "member", 2))
        self.assertIsNone(decide_role_change("member", "owner", 1))
        self.assertIsNone(decide_role_change("owner", "owner", 1))

    def test_remove_owner_with_second_owner_works(self):
        self.members.add_member(self.creator.id, self.org.id, self.yrsa.id, role="owner")
        self.members.remove_member(self.yrsa.id, self.org.id, self.creator.id)
        self.assertIsNone(self.members.role_for(self.creator.id, self.org.id))
        self.assertEqual(self.members.count_owners(self.org.id), 1)

    def test_remove_non_member_refused(self):
        self.assertEqual(self._reason(self.members.remove_member, self.creator.id, self.org.id, self.bryn.id), "not_a_member")

    def test_remove_by_non_owner_refused(self):
        self.members.add_member(self.creator.id, self.org.id, self.yrsa.id)
        self.members.add_member(self.creator.id, self.org.id, self.bryn.id)
        self.assertEqual(self._reason(self.members.remove_member, self.yrsa.id, self.org.id, self.bryn.id), "not_org_owner")
        self.assertEqual(self.members.role_for(self.bryn.id, self.org.id), "member")

    # leave
    def test_leave_as_member_works(self):
        self.members.add_member(self.creator.id, self.org.id, self.yrsa.id)
        self.members.leave_organization(self.yrsa.id, self.org.id)
        self.assertIsNone(self.members.role_for(self.yrsa.id, self.org.id))

    def test_leave_as_last_owner_refused(self):
        self.assertEqual(self._reason(self.members.leave_organization, self.creator.id, self.org.id), "last_owner")
        self.assertEqual(self.members.role_for(self.creator.id, self.org.id), "owner")

    def test_leave_as_non_member_refused(self):
        self.assertEqual(self._reason(self.members.leave_organization, self.bryn.id, self.org.id), "not_a_member")

    # roles
    def test_promote_then_original_owner_can_leave(self):
        self.members.add_member(self.creator.id, self.org.id, self.yrsa.id)
        made = self.members.set_role(self.creator.id, self.org.id, self.yrsa.id, "owner")
        self.assertEqual(made.role, "owner")
        self.assertEqual(self.members.count_owners(self.org.id), 2)
        self.members.leave_organization(self.creator.id, self.org.id)
        self.assertIsNone(self.members.role_for(self.creator.id, self.org.id))
        self.assertEqual(self.members.role_for(self.yrsa.id, self.org.id), "owner")

    def test_demote_last_owner_refused(self):
        self.assertEqual(self._reason(self.members.set_role, self.admin.id, self.org.id, self.creator.id, "member"), "last_owner")
        self.assertEqual(self.members.role_for(self.creator.id, self.org.id), "owner")

    def test_demote_owner_with_second_owner_works(self):
        self.members.add_member(self.creator.id, self.org.id, self.yrsa.id, role="owner")
        made = self.members.set_role(self.creator.id, self.org.id, self.creator.id, "member")
        self.assertEqual(made.role, "member")
        self.assertEqual(self.members.count_owners(self.org.id), 1)

    def test_set_role_by_non_owner_refused(self):
        self.members.add_member(self.creator.id, self.org.id, self.yrsa.id)
        self.members.add_member(self.creator.id, self.org.id, self.bryn.id)
        self.assertEqual(self._reason(self.members.set_role, self.yrsa.id, self.org.id, self.bryn.id, "owner"), "not_org_owner")
        self.assertEqual(self.members.role_for(self.bryn.id, self.org.id), "member")

    def test_set_role_same_role_is_noop_success(self):
        self.members.add_member(self.creator.id, self.org.id, self.yrsa.id)
        before = self._updates()
        made = self.members.set_role(self.creator.id, self.org.id, self.yrsa.id, "member")
        self.assertEqual(made.role, "member")
        self.assertEqual(self._updates(), before)

    def test_set_role_non_member_refused(self):
        self.assertEqual(self._reason(self.members.set_role, self.creator.id, self.org.id, self.bryn.id, "owner"), "not_a_member")

    def test_refusals_audit_nothing(self):
        before = self._updates()
        for fn, args in (
            (self.members.add_member, (self.bryn.id, self.org.id, self.yrsa.id)),
            (self.members.remove_member, (self.admin.id, self.org.id, self.creator.id)),
            (self.members.leave_organization, (self.creator.id, self.org.id)),
            (self.members.set_role, (self.creator.id, self.org.id, self.creator.id, "member")),
        ):
            with self.assertRaises(OrganizationError):
                fn(*args)
        self.assertEqual(self._updates(), before)

    # page + settings
    def test_members_page_escapes_and_states_rule(self):
        org2 = self.orgs.create_organization(self.creator.id, "fleet", display_name="Fleet <script>alert(1)</script>")
        self.members.add_member(self.creator.id, org2.id, self.yrsa.id)
        html = render_members_page(org2, self.members.list_members(org2.id))
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("volmarr", html)
        self.assertIn("yrsa", html)
        self.assertIn("Owner", html)
        self.assertIn("Member", html)
        self.assertIn("the last owner cannot leave or be removed", html)
        self.assertEqual(role_word("owner"), "Owner")
        self.assertEqual(role_word("member"), "Member")

    def test_settings_areas_members_available(self):
        by_key = {a["key"]: a for a in settings_areas()}
        self.assertTrue(by_key["members"]["available"])
        self.assertEqual(by_key["members"]["slice"], "S-186")

    # pins
    def test_migration_69_pin(self):
        self.assertEqual(schema_version(self.conn), 104)
        self.assertEqual(db.MIGRATIONS[-1][0], 104)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 131)
        cols = [r["name"] for r in self.conn.execute("PRAGMA table_info(organization_members)").fetchall()]
        for col in ("org_id", "user_id", "role", "added_by", "created_at", "updated_at"):
            self.assertIn(col, cols)
        idx = [r["name"] for r in self.conn.execute("PRAGMA index_list(organization_members)").fetchall()]
        self.assertIn("idx_organization_members_org", idx)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "old.db"
            conn = db.connect(path)
            for version, statements in db.MIGRATIONS:
                if version > 68:
                    continue
                with conn:
                    for stmt in statements:
                        conn.execute(stmt)
                    conn.execute("INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('version', ?)", (str(version),))
            conn.close()
            conn = db.init_db(path)
            self.assertEqual(db.schema_version(conn), 104)
            names = [r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'organization_members'").fetchall()]
            self.assertEqual(names, ["organization_members"])
            conn.close()


if __name__ == "__main__":
    unittest.main()
