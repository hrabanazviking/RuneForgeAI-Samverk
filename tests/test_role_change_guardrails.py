"""S-200 acceptance battery: role change guardrails.

Acceptance (roadmap S-200): Role change guardrails
— demoting the last admin of a repo is refused with
the reason stated.

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
from samverk.default_permissions import DefaultPermissionStore
from samverk.organization_members import OrgMembershipStore
from samverk.organizations import OrganizationError, OrganizationStore
from samverk.outside_collaborators import OutsideCollaboratorStore
from samverk.permission_engine import PermissionEngine
from samverk.repositories import Repository
from samverk.role_change_guardrails import (
    AdminHolder, RoleChangeGuardStore, decide_last_admin,
    render_role_guardrails_page, source_word)
from samverk.team_nesting import NestedTeamStore
from samverk.team_permissions import TeamPermissionStore
from samverk.teams import TeamStore


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class RoleChangeGuardrailTests(unittest.TestCase):
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
        self.teams = TeamStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.nesting = NestedTeamStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.perms = TeamPermissionStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.collabs = OutsideCollaboratorStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.defaults = DefaultPermissionStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.guard = RoleChangeGuardStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.engine = PermissionEngine(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.parent = self.teams.create_team(self.creator.id, self.org.id, "Parent Team")
        self.child = self.teams.create_team(self.creator.id, self.org.id, "Child Team")
        self.anvil = self._repo("crew", "anvil", "public")
        self.secret = self._repo("crew", "secret", "private")
        self.vault = self._repo("solo", "vault", "private")

    def _repo(self, owner, name, visibility):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO repositories (owner, owner_lower, name, name_lower, created_by, created_at, description, visibility) VALUES (?, ?, ?, ?, ?, ?, '', ?)",
                (owner, owner.lower(), name, name.lower(), self.creator.id, 1_700_000_000, visibility))
        repo_id = int(cur.lastrowid)
        return Repository(id=repo_id, owner=owner, owner_lower=owner.lower(), name=name, name_lower=name.lower(), created_by=self.creator.id, created_at=1_700_000_000, description="", visibility=visibility)

    def _link(self, team, repo, role=None):
        self.teams.link_repo(self.creator.id, self.org.id, team.id, repo.id)
        if role is not None:
            self.perms.set_permission(self.creator.id, self.org.id, team.id, repo.id, role)

    def _events(self, action):
        return self.conn.execute("SELECT COUNT(*) c FROM audit_log WHERE action = ?", (action,)).fetchone()["c"]

    def _audit_total(self):
        return self.conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"]

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(OrganizationError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def _holder_names(self, repo):
        return [(h.username, h.sources) for h in self.guard.admin_holders(repo.id)]

    # pins
    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 108)
        self.assertEqual(db.MIGRATIONS[-1][0], 108)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)

    # the pure rule
    def test_pure_decide_last_admin(self):
        self.assertEqual(decide_last_admin(current_role="admin", new_role="write", holders_before={7}, holders_after=set()), "last_admin")
        self.assertEqual(decide_last_admin(current_role="admin", new_role=None, holders_before={7}, holders_after=set()), "last_admin")
        self.assertIsNone(decide_last_admin(current_role="admin", new_role="write", holders_before={7, 8}, holders_after={8}))
        self.assertIsNone(decide_last_admin(current_role="admin", new_role="admin", holders_before={7}, holders_after={7}))
        self.assertIsNone(decide_last_admin(current_role="maintain", new_role="read", holders_before={7}, holders_after=set()))
        self.assertIsNone(decide_last_admin(current_role="admin", new_role="write", holders_before=set(), holders_after=set()))
        self.assertIsNone(decide_last_admin(current_role=None, new_role="read", holders_before={7}, holders_after=set()))
        self.assertEqual(source_word("team"), "Team grant")
        self.assertEqual(source_word("collaborator"), "Collaborator grant")

    # who counts: grants only, intrinsic admin excluded
    def test_holders_count_grants_not_intrinsic_admin(self):
        # crew/secret: creator is org owner (intrinsic) — no grant-holders.
        self.assertEqual(self._holder_names(self.secret), [])
        # solo/vault: solo is the personal owner (intrinsic) — none either.
        self.assertEqual(self._holder_names(self.vault), [])
        self.collabs.grant(self.solo.id, self.vault.id, self.freya.id, "admin")
        self.assertEqual(self._holder_names(self.vault), [("freya", ("collaborator",))])
        self.assertEqual(self._reason(self.guard.admin_holders, 999999), "repo_not_found")

    def test_holders_from_teams_and_default(self):
        self.teams.add_member(self.creator.id, self.org.id, self.child.id, self.yrsa.id)
        self._link(self.child, self.secret, "admin")
        # S-187 seeds the team's creator as its first member,
        # so volmarr holds the grant beside yrsa
        self.assertEqual(self._holder_names(self.secret), [("volmarr", ("team",)), ("yrsa", ("team",))])
        self.defaults.set_default(self.creator.id, self.org.id, "admin")
        self.assertEqual(
            self._holder_names(self.secret),
            [("brynhild", ("org_default",)), ("volmarr", ("team",)), ("yrsa", ("org_default", "team"))])

    # collaborator demotion door
    def test_demoting_sole_collaborator_admin_refused(self):
        self.collabs.grant(self.solo.id, self.vault.id, self.freya.id, "admin")
        before_audit = self._audit_total()
        with self.assertRaises(OrganizationError) as ctx:
            self.collabs.set_role(self.solo.id, self.vault.id, self.freya.id, "write")
        self.assertEqual(ctx.exception.reason, "last_admin")
        self.assertIn("last admin", str(ctx.exception))
        self.assertIn("at least one admin", str(ctx.exception))
        self.assertEqual(self.collabs.role_for(self.freya.id, self.vault.id), "admin")
        self.assertEqual(self.engine.role_for(self.freya, self.vault), "admin")
        self.assertEqual(self._audit_total(), before_audit)
        self.assertEqual(self._events("repo.collaborator.role_change"), 0)

    def test_demoting_one_of_two_collaborator_admins_allowed(self):
        self.collabs.grant(self.solo.id, self.vault.id, self.freya.id, "admin")
        self.collabs.grant(self.solo.id, self.vault.id, self.papa.id, "admin")
        got = self.collabs.set_role(self.solo.id, self.vault.id, self.freya.id, "maintain")
        self.assertEqual(got.role, "maintain")
        self.assertEqual(self._events("repo.collaborator.role_change"), 1)
        # now papa is the last admin: his demotion is refused
        self.assertEqual(self._reason(self.collabs.set_role, self.solo.id, self.vault.id, self.papa.id, "read"), "last_admin")

    def test_demotion_allowed_when_admin_also_held_via_team(self):
        self.teams.add_member(self.creator.id, self.org.id, self.child.id, self.yrsa.id)
        self._link(self.child, self.secret, "admin")
        # yrsa is an org member, so she cannot be an outside collaborator
        # on a crew repo; use freya on the personal vault for the pure
        # collaborator case and a team-only second holder here instead:
        self.collabs.grant(self.creator.id, self.secret.id, self.freya.id, "admin")
        got = self.collabs.set_role(self.creator.id, self.secret.id, self.freya.id, "write")
        self.assertEqual(got.role, "write")
        self.assertEqual(self._holder_names(self.secret), [("volmarr", ("team",)), ("yrsa", ("team",))])

    def test_promotions_and_lower_changes_unguarded(self):
        self.collabs.grant(self.solo.id, self.vault.id, self.freya.id, "read")
        got = self.collabs.set_role(self.solo.id, self.vault.id, self.freya.id, "admin")
        self.assertEqual(got.role, "admin")
        again = self.collabs.set_role(self.solo.id, self.vault.id, self.freya.id, "admin")
        self.assertEqual(again.role, "admin")
        self.assertEqual(self._events("repo.collaborator.role_change"), 1)
        self.collabs.grant(self.solo.id, self.vault.id, self.papa.id, "write")
        got = self.collabs.set_role(self.solo.id, self.vault.id, self.papa.id, "read")
        self.assertEqual(got.role, "read")

    # collaborator revocation door (removal path)
    def test_revoking_sole_collaborator_admin_refused(self):
        self.collabs.grant(self.solo.id, self.vault.id, self.freya.id, "admin")
        before_audit = self._audit_total()
        self.assertEqual(self._reason(self.collabs.revoke, self.solo.id, self.vault.id, self.freya.id), "last_admin")
        # even the holder leaving is refused while she is the last admin
        self.assertEqual(self._reason(self.collabs.revoke, self.freya.id, self.vault.id, self.freya.id), "last_admin")
        self.assertEqual(self.collabs.role_for(self.freya.id, self.vault.id), "admin")
        self.assertEqual(self._audit_total(), before_audit)
        self.assertEqual(self._events("repo.collaborator.remove"), 0)

    def test_revoking_one_of_two_admins_and_non_admin_allowed(self):
        self.collabs.grant(self.solo.id, self.vault.id, self.freya.id, "admin")
        self.collabs.grant(self.solo.id, self.vault.id, self.papa.id, "admin")
        removed = self.collabs.revoke(self.solo.id, self.vault.id, self.freya.id)
        self.assertEqual(removed.role, "admin")
        self.collabs.grant(self.solo.id, self.vault.id, self.bryn.id, "write")
        removed = self.collabs.revoke(self.bryn.id, self.vault.id, self.bryn.id)
        self.assertEqual(removed.role, "write")
        self.assertEqual(self._events("repo.collaborator.remove"), 2)

    # team demotion door
    def test_demoting_sole_admin_team_refused(self):
        self.teams.add_member(self.creator.id, self.org.id, self.child.id, self.yrsa.id)
        self._link(self.child, self.secret, "admin")
        before_audit = self._audit_total()
        with self.assertRaises(OrganizationError) as ctx:
            self.perms.set_permission(self.creator.id, self.org.id, self.child.id, self.secret.id, "write")
        self.assertEqual(ctx.exception.reason, "last_admin")
        self.assertIn("at least one admin", str(ctx.exception))
        self.assertEqual(self.perms.permission_for(self.org.id, self.child.id, self.secret.id), "admin")
        self.assertEqual(self.engine.role_for(self.yrsa, self.secret), "admin")
        self.assertEqual(self._audit_total(), before_audit)

    def test_demoting_one_of_two_admin_teams_allowed(self):
        self.teams.add_member(self.creator.id, self.org.id, self.child.id, self.yrsa.id)
        self.teams.add_member(self.creator.id, self.org.id, self.parent.id, self.bryn.id)
        self._link(self.child, self.secret, "admin")
        self._link(self.parent, self.secret, "admin")
        got = self.perms.set_permission(self.creator.id, self.org.id, self.child.id, self.secret.id, "maintain")
        self.assertEqual(got.permission, "maintain")
        # the parent team is now the last admin grant: refused
        self.assertEqual(self._reason(self.perms.set_permission, self.creator.id, self.org.id, self.parent.id, self.secret.id, "read"), "last_admin")

    def test_team_demotion_allowed_when_ancestor_still_grants(self):
        self.nesting.set_parent(self.creator.id, self.org.id, self.child.id, self.parent.id)
        self.teams.add_member(self.creator.id, self.org.id, self.child.id, self.yrsa.id)
        self._link(self.parent, self.secret, "admin")
        self._link(self.child, self.secret, "admin")
        got = self.perms.set_permission(self.creator.id, self.org.id, self.child.id, self.secret.id, "read")
        self.assertEqual(got.permission, "read")
        self.assertEqual(self.engine.role_for(self.yrsa, self.secret), "admin")

    def test_team_demotion_of_empty_team_allowed(self):
        # an admin grant held by a team with no members at all:
        # no person holds admin through it, so demoting it
        # takes no one's admin away (S-187 seeds the creator
        # as first member, so the fixture unseeds the team)
        with self.conn:
            self.conn.execute("DELETE FROM team_members WHERE team_id = ?", (self.child.id,))
        self._link(self.child, self.secret, "admin")
        self.assertEqual(self._holder_names(self.secret), [])
        got = self.perms.set_permission(self.creator.id, self.org.id, self.child.id, self.secret.id, "write")
        self.assertEqual(got.permission, "write")

    def test_default_admin_floor_saves_collaborator_demotion(self):
        self.defaults.set_default(self.creator.id, self.org.id, "admin")
        self.collabs.grant(self.creator.id, self.secret.id, self.freya.id, "admin")
        got = self.collabs.set_role(self.creator.id, self.secret.id, self.freya.id, "triage")
        self.assertEqual(got.role, "triage")
        names = [name for name, _ in self._holder_names(self.secret)]
        self.assertEqual(names, ["brynhild", "yrsa"])

    # the guard itself is a pure read
    def test_guard_reads_write_and_audit_nothing(self):
        self.collabs.grant(self.solo.id, self.vault.id, self.freya.id, "admin")
        before_audit = self._audit_total()
        holders = self.guard.admin_holders(self.vault.id)
        self.assertEqual([(h.username, h.sources) for h in holders], [("freya", ("collaborator",))])
        self.assertIsInstance(holders[0], AdminHolder)
        self._reason(self.collabs.set_role, self.solo.id, self.vault.id, self.freya.id, "read")
        self.assertEqual(self._audit_total(), before_audit)

    # page
    def test_guardrails_page_escaped_with_holders(self):
        self.collabs.grant(self.solo.id, self.vault.id, self.freya.id, "admin")
        page = render_role_guardrails_page(self.vault, self.guard.admin_holders(self.vault.id))
        self.assertIn("freya", page)
        self.assertIn("Collaborator grant", page)
        self.assertIn("at least one admin", page)
        evil = self._repo("solo", "v<script>", "private")
        page = render_role_guardrails_page(evil, [])
        self.assertNotIn("<script>", page)
        self.assertIn("No one holds admin", page)


if __name__ == "__main__":
    unittest.main()
