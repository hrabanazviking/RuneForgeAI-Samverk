"""S-191 acceptance battery: outside collaborators.

Acceptance (roadmap S-191): Outside collaborators
— per-repo grants to non-members, listed in one
auditable place, revocable in one click.

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
from samverk.organizations import OrganizationError, OrganizationStore
from samverk.outside_collaborators import (
    OutsideCollaboratorStore, decide_grant, decide_revoke,
    is_outside, render_outside_collaborators_page,
    render_owner_collaborators_page, validate_collaborator_role)
from samverk.permission_engine import PermissionEngine
from samverk.repositories import Repository


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class OutsideCollaboratorTests(unittest.TestCase):
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
        self.papa = self.accounts.register("papa", "correct horse battery")
        self.freya = self.accounts.register("freya", "correct horse battery")
        self.newbie = self.accounts.register("newbie", "correct horse battery")
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
        self.collabs = OutsideCollaboratorStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.engine = PermissionEngine(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.anvil = self._repo("crew", "anvil", "public")
        self.secret = self._repo("crew", "secret", "private")
        self.hammer = self._repo("solo", "hammer", "public")
        self.vault = self._repo("solo", "vault", "private")

    def _repo(self, owner, name, visibility):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO repositories (owner, owner_lower, name, name_lower, created_by, created_at, description, visibility) VALUES (?, ?, ?, ?, ?, ?, '', ?)",
                (owner, owner.lower(), name, name.lower(), self.creator.id, 1_700_000_000, visibility))
        repo_id = int(cur.lastrowid)
        return Repository(id=repo_id, owner=owner, owner_lower=owner.lower(), name=name, name_lower=name.lower(), created_by=self.creator.id, created_at=1_700_000_000, description="", visibility=visibility)

    def _events(self, action):
        return self.conn.execute("SELECT COUNT(*) c FROM audit_log WHERE action = ?", (action,)).fetchone()["c"]

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(OrganizationError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    # pins
    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 98)
        self.assertEqual(db.MIGRATIONS[-1][0], 98)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 131)
        self.assertIn("repo.collaborator.add", taxonomy.AUDIT_EVENTS)
        self.assertIn("repo.collaborator.remove", taxonomy.AUDIT_EVENTS)
        self.assertIn("repo.collaborator.role_change", taxonomy.AUDIT_EVENTS)
        cols = [r["name"] for r in self.conn.execute("PRAGMA table_info(outside_collaborators)").fetchall()]
        self.assertEqual(cols, ["repo_id", "user_id", "role", "granted_by", "created_at", "updated_at"])

    def test_migration_73_creates_the_table(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "old.db"
            conn = db.connect(path)
            for version, statements in db.MIGRATIONS:
                if version > 72:
                    continue
                with conn:
                    for stmt in statements:
                        conn.execute(stmt)
                    conn.execute("INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('version', ?)", (str(version),))
            self.assertEqual(db.schema_version(conn), 72)
            conn.close()
            conn = db.init_db(path)
            self.assertEqual(db.schema_version(conn), 98)
            tables = [r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()]
            self.assertIn("outside_collaborators", tables)
            conn.close()

    # pure rules
    def test_pure_role_validation(self):
        self.assertEqual(validate_collaborator_role(" Write "), "write")
        self.assertEqual(validate_collaborator_role("ADMIN"), "admin")
        for bad in ("owner", "member", "", "  ", None, 3):
            with self.assertRaises(OrganizationError) as ctx:
                validate_collaborator_role(bad)
            self.assertEqual(ctx.exception.reason, "role_invalid")

    def test_pure_outsideness_and_grant_rule(self):
        self.assertFalse(is_outside(is_repo_owner=True, org_owned=False, org_role=None))
        self.assertFalse(is_outside(is_repo_owner=False, org_owned=True, org_role="member"))
        self.assertFalse(is_outside(is_repo_owner=False, org_owned=True, org_role="owner"))
        self.assertTrue(is_outside(is_repo_owner=False, org_owned=True, org_role=None))
        self.assertTrue(is_outside(is_repo_owner=False, org_owned=False, org_role=None))
        self.assertEqual(decide_grant(is_repo_owner=True, org_owned=False, org_role=None, existing_role=None), "already_owner")
        self.assertEqual(decide_grant(is_repo_owner=False, org_owned=True, org_role="member", existing_role=None), "already_member")
        self.assertEqual(decide_grant(is_repo_owner=False, org_owned=True, org_role="owner", existing_role=None), "already_member")
        self.assertEqual(decide_grant(is_repo_owner=False, org_owned=False, org_role=None, existing_role="read"), "already_collaborator")
        self.assertIsNone(decide_grant(is_repo_owner=False, org_owned=True, org_role=None, existing_role=None))
        self.assertIsNone(decide_grant(is_repo_owner=False, org_owned=False, org_role=None, existing_role=None))

    def test_pure_revoke_rule(self):
        self.assertEqual(decide_revoke(existing_role=None, is_manager=True, is_self=False), "not_collaborator")
        self.assertEqual(decide_revoke(existing_role="write", is_manager=False, is_self=False), "not_repo_admin")
        self.assertIsNone(decide_revoke(existing_role="write", is_manager=True, is_self=False))
        self.assertIsNone(decide_revoke(existing_role="write", is_manager=False, is_self=True))

    # granting
    def test_grant_on_personal_repo_happy_and_audited(self):
        got = self.collabs.grant(self.solo.id, self.vault.id, self.freya.id, " Write ")
        self.assertEqual((got.username, got.full_name, got.role), ("freya", "solo/vault", "write"))
        self.assertEqual(got.granted_by, self.solo.id)
        self.assertEqual(got.granted_by_username, "solo")
        self.assertEqual(self.collabs.role_for(self.freya.id, self.vault.id), "write")
        self.assertEqual(self.collabs.count_for_repo(self.vault.id), 1)
        self.assertEqual(self._events("repo.collaborator.add"), 1)
        row = self.conn.execute("SELECT target_kind, target_id, detail FROM audit_log WHERE action = 'repo.collaborator.add'").fetchone()
        self.assertEqual((row["target_kind"], row["target_id"]), ("repo", "solo/vault"))
        self.assertIn('"user":"freya"', row["detail"])
        self.assertIn('"role":"write"', row["detail"])

    def test_grant_by_username_and_on_org_repo(self):
        got = self.collabs.grant(self.creator.id, self.secret.id, "papa", "triage")
        self.assertEqual((got.username, got.role), ("papa", "triage"))
        self.assertEqual(self.collabs.role_for(self.papa.id, self.secret.id), "triage")

    def test_grant_by_site_admin_anywhere(self):
        self.collabs.grant(self.admin.id, self.vault.id, self.papa.id, "read")
        self.collabs.grant(self.admin.id, self.secret.id, self.papa.id, "read")
        self.assertEqual(self.collabs.role_for(self.papa.id, self.vault.id), "read")
        self.assertEqual(self.collabs.role_for(self.papa.id, self.secret.id), "read")

    def test_grant_member_and_owner_refused_writing_nothing(self):
        self.assertEqual(self._reason(self.collabs.grant, self.creator.id, self.secret.id, self.yrsa.id, "write"), "already_member")
        self.assertEqual(self._reason(self.collabs.grant, self.admin.id, self.secret.id, self.creator.id, "write"), "already_member")
        self.assertEqual(self._reason(self.collabs.grant, self.solo.id, self.vault.id, self.solo.id, "write"), "already_owner")
        self.assertEqual(self.collabs.list_for_repo(self.secret.id), [])
        self.assertEqual(self.collabs.list_for_repo(self.vault.id), [])
        self.assertEqual(self._events("repo.collaborator.add"), 0)

    def test_grant_duplicate_and_bad_role_refused(self):
        self.collabs.grant(self.solo.id, self.vault.id, self.freya.id, "read")
        self.assertEqual(self._reason(self.collabs.grant, self.solo.id, self.vault.id, self.freya.id, "admin"), "already_collaborator")
        self.assertEqual(self._reason(self.collabs.grant, self.solo.id, self.vault.id, self.newbie.id, "owner"), "role_invalid")
        self.assertEqual(self.collabs.role_for(self.freya.id, self.vault.id), "read")
        self.assertEqual(self._events("repo.collaborator.add"), 1)

    def test_grant_unknowns_refused(self):
        self.assertEqual(self._reason(self.collabs.grant, self.solo.id, 999999, self.freya.id, "read"), "repo_not_found")
        self.assertEqual(self._reason(self.collabs.grant, self.solo.id, self.vault.id, "ghostuser", "read"), "no_such_user")
        self.assertEqual(self._reason(self.collabs.grant, 999999, self.vault.id, self.freya.id, "read"), "no_such_user")

    def test_grant_requires_stewardship(self):
        self.assertEqual(self._reason(self.collabs.grant, self.yrsa.id, self.secret.id, self.papa.id, "read"), "not_repo_admin")
        self.assertEqual(self._reason(self.collabs.grant, self.creator.id, self.vault.id, self.papa.id, "read"), "not_repo_admin")
        self.assertEqual(self._reason(self.collabs.grant, self.papa.id, self.vault.id, self.newbie.id, "read"), "not_repo_admin")
        self.collabs.grant(self.solo.id, self.vault.id, self.freya.id, "admin")
        self.assertEqual(self._reason(self.collabs.grant, self.freya.id, self.vault.id, self.newbie.id, "read"), "not_repo_admin")
        self.assertIsNone(self.collabs.role_for(self.newbie.id, self.vault.id))

    # role changes
    def test_set_role_happy_audited_and_noop(self):
        self.collabs.grant(self.solo.id, self.vault.id, self.freya.id, "read")
        got = self.collabs.set_role(self.solo.id, self.vault.id, self.freya.id, "maintain")
        self.assertEqual(got.role, "maintain")
        self.assertEqual(self._events("repo.collaborator.role_change"), 1)
        row = self.conn.execute("SELECT detail FROM audit_log WHERE action = 'repo.collaborator.role_change'").fetchone()
        self.assertIn('"from":"read"', row["detail"])
        self.assertIn('"to":"maintain"', row["detail"])
        again = self.collabs.set_role(self.solo.id, self.vault.id, self.freya.id, " Maintain ")
        self.assertEqual(again.role, "maintain")
        self.assertEqual(self._events("repo.collaborator.role_change"), 1)

    def test_set_role_refusals(self):
        self.assertEqual(self._reason(self.collabs.set_role, self.solo.id, self.vault.id, self.freya.id, "write"), "not_collaborator")
        self.collabs.grant(self.solo.id, self.vault.id, self.freya.id, "read")
        self.assertEqual(self._reason(self.collabs.set_role, self.papa.id, self.vault.id, self.freya.id, "write"), "not_repo_admin")
        self.assertEqual(self._reason(self.collabs.set_role, self.solo.id, self.vault.id, self.freya.id, "owner"), "role_invalid")
        self.assertEqual(self.collabs.role_for(self.freya.id, self.vault.id), "read")
        self.assertEqual(self._events("repo.collaborator.role_change"), 0)

    # revocation: one click
    def test_revoke_in_one_click(self):
        self.collabs.grant(self.creator.id, self.secret.id, self.papa.id, "write")
        removed = self.collabs.revoke(self.creator.id, self.secret.id, self.papa.id)
        self.assertEqual((removed.username, removed.role), ("papa", "write"))
        self.assertIsNone(self.collabs.role_for(self.papa.id, self.secret.id))
        self.assertEqual(self.collabs.list_for_repo(self.secret.id), [])
        self.assertEqual(self._events("repo.collaborator.remove"), 1)
        row = self.conn.execute("SELECT detail FROM audit_log WHERE action = 'repo.collaborator.remove'").fetchone()
        self.assertIn('"user":"papa"', row["detail"])
        self.assertEqual(self._reason(self.collabs.revoke, self.creator.id, self.secret.id, self.papa.id), "not_collaborator")

    def test_revoke_self_leave_and_stranger_refusal(self):
        self.collabs.grant(self.solo.id, self.vault.id, self.freya.id, "write")
        self.assertEqual(self._reason(self.collabs.revoke, self.newbie.id, self.vault.id, self.freya.id), "not_repo_admin")
        self.assertEqual(self.collabs.role_for(self.freya.id, self.vault.id), "write")
        removed = self.collabs.revoke(self.freya.id, self.vault.id, self.freya.id)
        self.assertEqual(removed.username, "freya")
        self.assertIsNone(self.collabs.role_for(self.freya.id, self.vault.id))
        self.assertEqual(self._events("repo.collaborator.remove"), 1)

    # the one auditable place
    def test_lists_are_the_auditable_place(self):
        self.collabs.grant(self.creator.id, self.secret.id, self.papa.id, "write")
        self.collabs.grant(self.creator.id, self.anvil.id, self.papa.id, "read")
        self.collabs.grant(self.creator.id, self.anvil.id, self.freya.id, "triage")
        self.collabs.grant(self.solo.id, self.vault.id, self.papa.id, "admin")
        mine = self.collabs.list_for_repo(self.anvil.id)
        self.assertEqual([(g.username, g.role) for g in mine], [("freya", "triage"), ("papa", "read")])
        papas = self.collabs.list_for_user(self.papa.id)
        self.assertEqual([(g.full_name, g.role) for g in papas], [("crew/anvil", "read"), ("crew/secret", "write"), ("solo/vault", "admin")])
        crews = self.collabs.list_for_owner("crew")
        self.assertEqual([(g.full_name, g.username) for g in crews], [("crew/anvil", "freya"), ("crew/anvil", "papa"), ("crew/secret", "papa")])
        solos = self.collabs.list_for_owner("SOLO")
        self.assertEqual([(g.full_name, g.username, g.role) for g in solos], [("solo/vault", "papa", "admin")])
        self.assertEqual(self._reason(self.collabs.list_for_repo, 999999), "repo_not_found")
        self.assertEqual(self._reason(self.collabs.list_for_user, 999999), "no_such_user")

    # S-190 reads the store
    def test_engine_reads_stored_grants(self):
        self.assertIsNone(self.engine.role_for(self.papa, self.secret))
        self.collabs.grant(self.creator.id, self.secret.id, self.papa.id, "write")
        got = self.engine.resolve(self.papa, self.secret)
        self.assertEqual((got.role, got.source), ("write", "collaborator"))
        self.collabs.grant(self.creator.id, self.anvil.id, self.freya.id, "triage")
        got = self.engine.resolve(self.freya, self.anvil)
        self.assertEqual((got.role, got.source), ("triage", "collaborator"))
        self.collabs.revoke(self.creator.id, self.secret.id, self.papa.id)
        self.assertIsNone(self.engine.role_for(self.papa, self.secret))

    def test_engine_explicit_role_still_wins_for_that_call(self):
        self.collabs.grant(self.solo.id, self.vault.id, self.freya.id, "write")
        got = self.engine.resolve(self.freya, self.vault, collaborator_role="read")
        self.assertEqual((got.role, got.source), ("read", "collaborator"))
        got = self.engine.resolve(self.freya, self.vault)
        self.assertEqual((got.role, got.source), ("write", "collaborator"))
        got = self.engine.resolve(None, self.vault)
        self.assertIsNone(got.role)

    # renderers
    def test_render_repo_page(self):
        self.collabs.grant(self.solo.id, self.vault.id, self.freya.id, "write")
        page = render_outside_collaborators_page(self.vault, self.collabs.list_for_repo(self.vault.id))
        self.assertIn("Outside collaborators", page)
        self.assertIn("solo/vault", page)
        self.assertIn("freya", page)
        self.assertIn("Write", page)
        self.assertIn("one click", page)
        self.assertIn("repo.collaborator.remove", page)
        empty = render_outside_collaborators_page(self.hammer, [])
        self.assertIn("no outside", empty)

    def test_render_owner_page_escapes(self):
        self.collabs.grant(self.creator.id, self.anvil.id, self.papa.id, "read")
        page = render_owner_collaborators_page("crew", self.collabs.list_for_owner("crew"))
        self.assertIn("crew/anvil", page)
        self.assertIn("papa", page)
        self.assertIn("Read", page)
        evil = render_owner_collaborators_page("<script>alert(1)</script>", [])
        self.assertNotIn("<script>alert", evil)
        self.assertIn("&lt;script&gt;", evil)


if __name__ == "__main__":
    unittest.main()
