"""S-192 acceptance battery: default repository permission.

Acceptance (roadmap S-192): Default repository
permission — org-wide base role for members, settable,
shown in effect on the matrix page.

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
from samverk.default_permissions import (
    DefaultPermissionStore, decide_default_change,
    render_default_permission_page, validate_default_role)
from samverk.organization_members import OrgMembershipStore
from samverk.organizations import OrganizationError, OrganizationStore
from samverk.permission_engine import (
    PermissionEngine, build_contributions, decide_permission,
    render_matrix_page)
from samverk.repositories import Repository


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class DefaultPermissionTests(unittest.TestCase):
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
        self.outsider = self.accounts.register("freya", "correct horse battery")
        self.solo = self.accounts.register("solo", "correct horse battery")
        self.admin = self.accounts.register("sitemod", "correct horse battery")
        with self.conn:
            self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (self.admin.id,))
        self.admin = self.accounts.get_by_id(self.admin.id)
        self.orgs = OrganizationStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.org = self.orgs.create_organization(self.creator.id, "crew")
        self.members = OrgMembershipStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.members.add_member(self.creator.id, self.org.id, self.yrsa.id)
        self.members.add_member(self.creator.id, self.org.id, self.bryn.id)
        self.defaults = DefaultPermissionStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.engine = PermissionEngine(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.anvil = self._repo("crew", "anvil", "public")
        self.secret = self._repo("crew", "secret", "private")
        self.hammer = self._repo("solo", "hammer", "private")

    def _repo(self, owner, name, visibility):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO repositories (owner, owner_lower, name, name_lower, created_by, created_at, description, visibility) VALUES (?, ?, ?, ?, ?, ?, '', ?)",
                (owner, owner.lower(), name, name.lower(), self.creator.id, 1_700_000_000, visibility))
        repo_id = int(cur.lastrowid)
        return Repository(id=repo_id, owner=owner, owner_lower=owner.lower(), name=name, name_lower=name.lower(), created_by=self.creator.id, created_at=1_700_000_000, description="", visibility=visibility)

    def _updates(self):
        return self.conn.execute("SELECT COUNT(*) c FROM audit_log WHERE action = 'auth.organization.update'").fetchone()["c"]

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(OrganizationError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    # pins
    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 78)
        self.assertEqual(db.MIGRATIONS[-1][0], 78)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 122)
        self.assertIn("auth.organization.update", taxonomy.AUDIT_EVENTS)
        cols = [r["name"] for r in self.conn.execute("PRAGMA table_info(org_default_permissions)").fetchall()]
        self.assertEqual(cols, ["org_id", "role", "set_by", "created_at", "updated_at"])

    def test_migration_74_creates_the_table(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "old.db"
            conn = db.connect(path)
            for version, statements in db.MIGRATIONS:
                if version > 73:
                    continue
                with conn:
                    for stmt in statements:
                        conn.execute(stmt)
                    conn.execute("INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('version', ?)", (str(version),))
            self.assertEqual(db.schema_version(conn), 73)
            conn.close()
            conn = db.init_db(path)
            self.assertEqual(db.schema_version(conn), 78)
            tables = [r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()]
            self.assertIn("org_default_permissions", tables)
            conn.close()

    # pure judgements
    def test_validate_default_role(self):
        self.assertEqual(validate_default_role("read"), "read")
        self.assertEqual(validate_default_role(" Write "), "write")
        self.assertEqual(validate_default_role("NONE"), "none")
        self.assertEqual(validate_default_role("admin"), "admin")
        for bad in ("owner", "", "superuser", None, 3):
            self.assertEqual(self._reason(validate_default_role, bad), "role_invalid")

    def test_decide_default_change(self):
        self.assertEqual(decide_default_change("none", "none"), "noop")
        self.assertEqual(decide_default_change("read", "read"), "noop")
        self.assertEqual(decide_default_change("none", "read"), "set")
        self.assertEqual(decide_default_change("write", "none"), "set")

    def test_pure_contribution_and_priority(self):
        found = build_contributions(org_role="member", org_default_role="write", visibility="public")
        decision = decide_permission(found)
        self.assertEqual(decision.role, "write")
        self.assertEqual(decision.source, "org_default")
        none_found = build_contributions(org_role="member", org_default_role="none", visibility="private")
        self.assertEqual(decide_permission(none_found).role, None)
        team = build_contributions(org_role="member", org_default_role="read", team_grants=(("core", "core", "maintain"),))
        self.assertEqual(decide_permission(team).source, "team")

    # the store
    def test_unset_default_is_none(self):
        got = self.defaults.get_default(self.org.id)
        self.assertEqual(got.role, "none")
        self.assertFalse(got.is_set)
        self.assertEqual(got.role_word(), "No permission")
        self.assertEqual(self.defaults.role_for_org(self.org.id), "none")

    def test_set_and_get_default(self):
        before = self._updates()
        got = self.defaults.set_default(self.creator.id, self.org.id, "write")
        self.assertEqual(got.role, "write")
        self.assertTrue(got.is_set)
        self.assertEqual(got.set_by, self.creator.id)
        self.assertEqual(got.set_by_username, "volmarr")
        self.assertEqual(self.defaults.role_for_org(self.org.id), "write")
        self.assertEqual(self._updates(), before + 1)
        row = self.conn.execute("SELECT detail FROM audit_log WHERE action = 'auth.organization.update' ORDER BY rowid DESC LIMIT 1").fetchone()
        self.assertIn("default_permission", row["detail"])
        self.assertIn("set_default", row["detail"])

    def test_set_is_org_owner_or_site_admin_only(self):
        self.assertEqual(self._reason(self.defaults.set_default, self.yrsa.id, self.org.id, "read"), "not_org_owner")
        got = self.defaults.set_default(self.admin.id, self.org.id, "read")
        self.assertEqual(got.role, "read")

    def test_set_refusals(self):
        self.assertEqual(self._reason(self.defaults.set_default, self.creator.id, 9999, "read"), "org_not_found")
        self.assertEqual(self._reason(self.defaults.set_default, self.creator.id, self.org.id, "owner"), "role_invalid")
        self.assertEqual(self._reason(self.defaults.get_default, 9999), "org_not_found")

    def test_same_value_set_is_noop(self):
        self.defaults.set_default(self.creator.id, self.org.id, "read")
        before = self._updates()
        got = self.defaults.set_default(self.creator.id, self.org.id, "read")
        self.assertEqual(got.role, "read")
        self.assertEqual(self._updates(), before)
        fresh = DefaultPermissionStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        before2 = self._updates()
        noop = fresh.set_default(self.creator.id, self.org.id, "read")
        self.assertTrue(noop.is_set)
        self.assertEqual(self._updates(), before2)

    def test_setting_none_clears_the_row(self):
        self.defaults.set_default(self.creator.id, self.org.id, "triage")
        got = self.defaults.set_default(self.creator.id, self.org.id, "none")
        self.assertEqual(got.role, "none")
        self.assertFalse(got.is_set)
        count = self.conn.execute("SELECT COUNT(*) c FROM org_default_permissions").fetchone()["c"]
        self.assertEqual(count, 0)

    # the engine in effect
    def test_member_gets_default_on_private_org_repo(self):
        self.assertIsNone(self.engine.role_for(self.yrsa, self.secret))
        self.defaults.set_default(self.creator.id, self.org.id, "read")
        res = self.engine.resolve(self.yrsa, self.secret)
        self.assertEqual(res.role, "read")
        self.assertEqual(res.source, "org_default")

    def test_default_beats_public_visibility_floor(self):
        self.defaults.set_default(self.creator.id, self.org.id, "write")
        res = self.engine.resolve(self.bryn, self.anvil)
        self.assertEqual(res.role, "write")
        self.assertEqual(res.source, "org_default")

    def test_default_never_reaches_non_members(self):
        self.defaults.set_default(self.creator.id, self.org.id, "admin")
        self.assertIsNone(self.engine.role_for(self.outsider, self.secret))
        self.assertEqual(self.engine.role_for(None, self.anvil), "read")
        self.assertIsNone(self.engine.role_for(self.outsider, self.hammer))

    def test_default_does_not_apply_to_personal_repos(self):
        self.defaults.set_default(self.creator.id, self.org.id, "admin")
        self.assertIsNone(self.engine.role_for(self.yrsa, self.hammer))

    def test_org_owner_still_admin_above_default(self):
        self.defaults.set_default(self.creator.id, self.org.id, "read")
        res = self.engine.resolve(self.creator, self.secret)
        self.assertEqual(res.role, "admin")
        self.assertEqual(res.source, "org_owner")

    def test_clearing_default_restores_no_access(self):
        self.defaults.set_default(self.creator.id, self.org.id, "write")
        self.assertEqual(self.engine.role_for(self.yrsa, self.secret), "write")
        self.defaults.set_default(self.creator.id, self.org.id, "none")
        self.assertIsNone(self.engine.role_for(self.yrsa, self.secret))

    def test_resolution_writes_and_audits_nothing(self):
        self.defaults.set_default(self.creator.id, self.org.id, "read")
        before = self.conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"]
        self.engine.resolve(self.yrsa, self.secret)
        self.engine.resolve(self.bryn, self.anvil)
        after = self.conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"]
        self.assertEqual(before, after)

    # shown in effect
    def test_matrix_page_shows_default_in_effect(self):
        self.defaults.set_default(self.creator.id, self.org.id, "write")
        page = render_matrix_page(self.engine.resolutions_for([self.yrsa], self.secret))
        self.assertIn("Organization default", page)
        self.assertIn("Write", page)
        self.assertIn("yrsa", page)

    def test_render_default_page_states_value_in_words(self):
        unset = render_default_permission_page(self.defaults.get_default(self.org.id))
        self.assertIn("No permission", unset)
        self.assertIn("crew", unset)
        self.defaults.set_default(self.creator.id, self.org.id, "maintain")
        page = render_default_permission_page(self.defaults.get_default(self.org.id))
        self.assertIn("Maintain", page)
        self.assertIn("Organization default", page)


if __name__ == "__main__":
    unittest.main()
