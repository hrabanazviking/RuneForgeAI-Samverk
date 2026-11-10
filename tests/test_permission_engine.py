"""S-190 acceptance battery: permission resolution engine.

Acceptance (roadmap S-190): Permission resolution engine
— one function: user x repo -> role, considering
ownership, teams (with nesting), collaborator grants,
and visibility; the full matrix is a test fixture.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, permissions as legacy_permissions, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.organization_members import OrgMembershipStore
from samverk.organizations import OrganizationError, OrganizationStore
from samverk.permission_engine import (
    PermissionEngine, Resolution, build_contributions,
    decide_permission, explanation, render_matrix_page,
    render_resolution_page, source_word)
from samverk.permissions import PermissionDeniedError
from samverk.repositories import Repository
from samverk.team_nesting import NestedTeamStore
from samverk.team_permissions import TeamPermissionStore
from samverk.teams import TeamStore


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class PermissionEngineTests(unittest.TestCase):
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
        self.newbie = self.accounts.register("newbie", "correct horse battery")
        self.solo = self.accounts.register("solo", "correct horse battery")
        self.outsider = self.accounts.register("outsider", "correct horse battery")
        self.admin = self.accounts.register("sitemod", "correct horse battery")
        with self.conn:
            self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (self.admin.id,))
        self.admin = self.accounts.get_by_id(self.admin.id)
        self.orgs = OrganizationStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.org = self.orgs.create_organization(self.creator.id, "crew")
        self.members = OrgMembershipStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        for user in (self.yrsa, self.bryn, self.papa, self.newbie):
            self.members.add_member(self.creator.id, self.org.id, user.id)
        self.teams = TeamStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.nesting = NestedTeamStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.perms = TeamPermissionStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.engine = PermissionEngine(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.parent = self.teams.create_team(self.creator.id, self.org.id, "Parent Team")
        self.child = self.teams.create_team(self.creator.id, self.org.id, "Child Team")
        self.sibling = self.teams.create_team(self.creator.id, self.org.id, "Sibling Team")
        self.nesting.set_parent(self.creator.id, self.org.id, self.child.id, self.parent.id)
        self.nesting.set_parent(self.creator.id, self.org.id, self.sibling.id, self.parent.id)
        self.teams.add_member(self.creator.id, self.org.id, self.child.id, self.yrsa.id)
        self.teams.add_member(self.creator.id, self.org.id, self.parent.id, self.papa.id)
        self.teams.add_member(self.creator.id, self.org.id, self.sibling.id, self.bryn.id)
        self.anvil = self._repo("crew", "anvil", "public")
        self.secret = self._repo("crew", "secret", "private")
        self.hammer = self._repo("solo", "hammer", "public")
        self.vault = self._repo("solo", "vault", "private")
        self._grant(self.parent, self.secret, "write")
        self._grant(self.child, self.secret, "triage")
        self._grant(self.child, self.anvil, "maintain")
        self._grant(self.sibling, self.secret, "admin")

    def _repo(self, owner, name, visibility):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO repositories (owner, owner_lower, name, name_lower, created_by, created_at, description, visibility) VALUES (?, ?, ?, ?, ?, ?, '', ?)",
                (owner, owner.lower(), name, name.lower(), self.creator.id, 1_700_000_000, visibility))
        repo_id = int(cur.lastrowid)
        return Repository(id=repo_id, owner=owner, owner_lower=owner.lower(), name=name, name_lower=name.lower(), created_by=self.creator.id, created_at=1_700_000_000, description="", visibility=visibility)

    def _grant(self, team, repo, role):
        self.teams.link_repo(self.creator.id, self.org.id, team.id, repo.id)
        self.perms.set_permission(self.creator.id, self.org.id, team.id, repo.id, role)

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(OrganizationError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    # pins
    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 96)
        self.assertEqual(db.MIGRATIONS[-1][0], 96)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 131)

    # pure judgement
    def test_pure_decide_empty_is_none(self):
        got = decide_permission([])
        self.assertIsNone(got.role)
        self.assertEqual(got.source, "none")

    def test_pure_decide_highest_rung_wins(self):
        got = decide_permission(build_contributions(
            collaborator_role="read", visibility="public",
            team_grants=(("Child Team", "Parent Team", "write"),)))
        self.assertEqual((got.role, got.source), ("write", "team"))
        self.assertEqual(got.team_name, "Child Team")
        self.assertEqual(got.granted_by_team_name, "Parent Team")

    def test_pure_decide_tie_breaks_by_source_priority(self):
        got = decide_permission(build_contributions(
            is_owner=True, is_site_admin=True))
        self.assertEqual((got.role, got.source), ("admin", "owner"))
        got = decide_permission(build_contributions(
            collaborator_role="write",
            team_grants=(("Child Team", "Child Team", "write"),)))
        self.assertEqual((got.role, got.source), ("write", "team"))
        got = decide_permission(build_contributions(
            collaborator_role="read", visibility="public"))
        self.assertEqual((got.role, got.source), ("read", "collaborator"))

    def test_pure_org_member_alone_contributes_nothing(self):
        self.assertEqual(build_contributions(org_role="member"), [])
        got = decide_permission(build_contributions(
            org_role="member", visibility="private"))
        self.assertIsNone(got.role)
        got = decide_permission(build_contributions(org_role="owner"))
        self.assertEqual((got.role, got.source), ("admin", "org_owner"))

    def test_pure_invalid_roles_refused_loudly(self):
        self.assertEqual(
            self._reason(build_contributions, collaborator_role="owner"),
            "role_invalid")
        self.assertEqual(
            self._reason(build_contributions,
                         team_grants=(("T", "T", "superuser"),)),
            "role_invalid")

    def test_source_words_are_plain(self):
        self.assertEqual(source_word("team"), "Team grant")
        self.assertEqual(source_word("org_owner"), "Organization owner")
        self.assertEqual(source_word("none"), "No access")

    # THE MATRIX — the full fixture: viewer x repo -> (role, source)
    def test_matrix_fixture(self):
        v = {"anon": None, "creator": self.creator, "yrsa": self.yrsa,
             "bryn": self.bryn, "papa": self.papa, "newbie": self.newbie,
             "solo": self.solo, "outsider": self.outsider,
             "admin": self.admin}
        r = {"anvil": self.anvil, "secret": self.secret,
             "hammer": self.hammer, "vault": self.vault}
        matrix = [
            ("anon", "anvil", "read", "visibility"),
            ("anon", "secret", None, "none"),
            ("anon", "hammer", "read", "visibility"),
            ("anon", "vault", None, "none"),
            ("solo", "vault", "admin", "owner"),
            ("solo", "hammer", "admin", "owner"),
            ("solo", "secret", None, "none"),
            ("solo", "anvil", "read", "visibility"),
            ("admin", "secret", "admin", "site_admin"),
            ("admin", "vault", "admin", "site_admin"),
            ("creator", "secret", "admin", "org_owner"),
            ("creator", "anvil", "admin", "org_owner"),
            ("creator", "vault", None, "none"),
            ("creator", "hammer", "read", "visibility"),
            ("yrsa", "secret", "write", "team"),
            ("yrsa", "anvil", "maintain", "team"),
            ("yrsa", "vault", None, "none"),
            ("bryn", "secret", "admin", "team"),
            ("bryn", "anvil", "read", "visibility"),
            ("papa", "secret", "admin", "team"),
            ("papa", "anvil", "maintain", "team"),
            ("newbie", "secret", None, "none"),
            ("newbie", "anvil", "read", "visibility"),
            ("outsider", "secret", None, "none"),
            ("outsider", "anvil", "read", "visibility"),
            ("outsider", "hammer", "read", "visibility"),
        ]
        for who, repo_name, role, source in matrix:
            with self.subTest(who=who, repo=repo_name):
                got = self.engine.resolve(v[who], r[repo_name])
                self.assertEqual((got.role, got.source), (role, source))

    def test_matrix_team_cells_name_their_teams(self):
        got = self.engine.resolve(self.yrsa, self.secret)
        self.assertEqual(got.team_name, "Child Team")
        self.assertEqual(got.granted_by_team_name, "Parent Team")
        got = self.engine.resolve(self.papa, self.secret)
        self.assertEqual(got.team_name, "Sibling Team")
        self.assertEqual(got.granted_by_team_name, "Sibling Team")
        got = self.engine.resolve(self.papa, self.anvil)
        self.assertEqual((got.role, got.team_name), ("maintain", "Child Team"))

    def test_sibling_grant_never_leaks_sideways(self):
        # yrsa sits in Child, not Sibling: Sibling's admin
        # grant on secret must not reach her.
        got = self.engine.resolve(self.yrsa, self.secret)
        self.assertEqual(got.role, "write")
        self.assertNotEqual(got.granted_by_team_name, "Sibling Team")

    # collaborator grants (caller-supplied until S-191)
    def test_collaborator_grants_on_any_visibility(self):
        got = self.engine.resolve(self.outsider, self.vault, collaborator_role="triage")
        self.assertEqual((got.role, got.source), ("triage", "collaborator"))
        got = self.engine.resolve(self.outsider, self.secret, collaborator_role="write")
        self.assertEqual((got.role, got.source), ("write", "collaborator"))
        got = self.engine.resolve(None, self.anvil, collaborator_role="write")
        self.assertEqual((got.role, got.source), ("read", "visibility"))

    def test_collaborator_role_beats_and_yields_by_rung(self):
        got = self.engine.resolve(self.yrsa, self.secret, collaborator_role="admin")
        self.assertEqual((got.role, got.source), ("admin", "collaborator"))
        got = self.engine.resolve(self.yrsa, self.secret, collaborator_role="read")
        self.assertEqual((got.role, got.source), ("write", "team"))

    def test_invalid_collaborator_role_refused_loudly(self):
        self.assertEqual(
            self._reason(self.engine.resolve, self.outsider, self.vault,
                         collaborator_role="owner"),
            "role_invalid")

    # S-054 preservation
    def test_s054_answers_preserved(self):
        viewers = [None, self.solo, self.outsider, self.admin]
        repos = [self.hammer, self.vault, self.anvil, self.secret]
        for viewer in viewers:
            for repo in repos:
                for collab in (None, "read", "write", "admin"):
                    with self.subTest(viewer=viewer, repo=repo.name, collab=collab):
                        self.assertEqual(
                            self.engine.role_for(viewer, repo, collaborator_role=collab),
                            legacy_permissions.role_for(viewer, repo, collaborator_role=collab))

    # wrappers
    def test_role_for_can_and_require_role(self):
        self.assertEqual(self.engine.role_for(self.yrsa, self.secret), "write")
        self.assertTrue(self.engine.can(self.yrsa, self.secret, "write"))
        self.assertTrue(self.engine.can(self.yrsa, self.secret, "triage"))
        self.assertFalse(self.engine.can(self.yrsa, self.secret, "maintain"))
        self.assertTrue(self.engine.can(self.yrsa, self.anvil, "maintain"))
        self.assertFalse(self.engine.can(self.newbie, self.secret, "read"))
        self.assertTrue(self.engine.can(None, self.anvil))
        self.assertEqual(self.engine.require_role(self.yrsa, self.anvil, "maintain"), "maintain")
        with self.assertRaises(PermissionDeniedError):
            self.engine.require_role(self.newbie, self.secret)

    def test_resolve_by_id(self):
        got = self.engine.resolve_by_id(self.yrsa.id, self.secret.id)
        self.assertEqual((got.role, got.source), ("write", "team"))
        got = self.engine.resolve_by_id(None, self.anvil.id)
        self.assertEqual((got.role, got.username), ("read", None))
        self.assertEqual(
            self._reason(self.engine.resolve_by_id, self.yrsa.id, 999999),
            "repo_not_found")
        self.assertEqual(
            self._reason(self.engine.resolve_by_id, 999999, self.anvil.id),
            "no_such_user")

    def test_resolution_is_a_pure_read(self):
        before = self.conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"]
        for viewer in (None, self.yrsa, self.creator, self.admin):
            self.engine.resolve(viewer, self.secret)
            self.engine.resolve(viewer, self.anvil)
        after = self.conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"]
        self.assertEqual(before, after)

    # explanation + pages
    def test_explanation_sentences(self):
        text = explanation(self.engine.resolve(None, self.secret))
        self.assertIn("no access to crew/secret", text)
        self.assertIn("not found, not forbidden", text)
        text = explanation(self.engine.resolve(self.yrsa, self.secret))
        self.assertIn("yrsa has Write in crew/secret", text)
        self.assertIn("Child Team", text)
        text = explanation(self.engine.resolve(self.creator, self.secret))
        self.assertIn("they own the organization", text)

    def test_render_resolution_page(self):
        page = render_resolution_page(self.engine.resolve(self.yrsa, self.secret))
        self.assertIn("Write", page)
        self.assertIn("Team grant", page)
        self.assertIn("Parent Team", page)
        self.assertIn("read / triage / write / maintain / admin", page.lower().replace("Read / Triage / Write / Maintain / Admin", "read / triage / write / maintain / admin"))

    def test_renderers_escape_everything(self):
        evil = Resolution(user_id=1, username="<script>x</script>", repo_id=1, owner="<b>crew</b>", name="se<cret", visibility="private", role="read", source="team", detail="the <i>Team</i> team grants it", team_name="<i>Team</i>", granted_by_team_name="<i>Team</i>")
        page = render_resolution_page(evil)
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("<b>crew</b>", page)
        page = render_matrix_page([evil])
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_render_matrix_page(self):
        resolutions = self.engine.resolutions_for([None, self.yrsa, self.newbie], self.secret)
        page = render_matrix_page(resolutions)
        self.assertIn("Permission matrix — crew/secret", page)
        self.assertIn("Anonymous — No access", page)
        self.assertIn("yrsa — Write — Team grant", page)
        self.assertIn("newbie — No access", page)
        self.assertIn("No resolutions were computed.", render_matrix_page([]))


if __name__ == "__main__":
    unittest.main()
