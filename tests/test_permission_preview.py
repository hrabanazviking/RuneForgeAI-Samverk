"""S-201 acceptance battery: permission preview.

Acceptance (roadmap S-201): Permission preview —
"view as" for admins: see the instance exactly as a
chosen member sees it (the findability and safety
tool).

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
from samverk.organizations import OrganizationError, OrganizationStore
from samverk.organization_members import OrgMembershipStore
from samverk.outside_collaborators import OutsideCollaboratorStore
from samverk.permission_engine import PermissionEngine, Resolution
from samverk.permission_preview import (
    PermissionPreview, PermissionPreviewEngine, decide_preview,
    render_permission_preview_page, visible_resolutions)
from samverk.repositories import Repository
from samverk.team_permissions import TeamPermissionStore
from samverk.teams import TeamStore


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class PermissionPreviewTests(unittest.TestCase):
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
        self.teams = TeamStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.perms = TeamPermissionStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.team = self.teams.create_team(self.creator.id, self.org.id, "Crew Team")
        self.teams.add_member(self.creator.id, self.org.id, self.team.id, self.yrsa.id)
        self.engine = PermissionEngine(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.preview = PermissionPreviewEngine(self.conn, self.accounts, time_fn=self.clock)
        self.collaborators = OutsideCollaboratorStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.defaults = DefaultPermissionStore(self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.anvil = self._repo("crew", "anvil", "public")
        self.inner = self._repo("crew", "inner", "internal")
        self.secret = self._repo("crew", "secret", "private")
        self.hammer = self._repo("solo", "hammer", "public")
        self.vault = self._repo("solo", "vault", "private")
        self.teams.link_repo(self.creator.id, self.org.id, self.team.id, self.secret.id)
        self.perms.set_permission(self.creator.id, self.org.id, self.team.id, self.secret.id, "write")
        self.collaborators.grant(self.solo.id, self.vault.id, self.outsider.id, "write")
        self.all_repos = [self.anvil, self.inner, self.secret, self.hammer, self.vault]

    def _repo(self, owner, name, visibility):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO repositories (owner, owner_lower, name, name_lower, created_by, created_at, description, visibility) VALUES (?, ?, ?, ?, ?, ?, '', ?)",
                (owner, owner.lower(), name, name.lower(), self.creator.id, 1_700_000_000, visibility))
        repo_id = int(cur.lastrowid)
        return Repository(id=repo_id, owner=owner, owner_lower=owner.lower(), name=name, name_lower=name.lower(), created_by=self.creator.id, created_at=1_700_000_000, description="", visibility=visibility)

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(OrganizationError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def _table_counts(self):
        tables = ("users", "repositories", "organizations",
                  "organization_members", "teams", "team_members",
                  "team_repositories", "outside_collaborators",
                  "org_default_permissions", "audit_log")
        return {t: self.conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"] for t in tables}

    # pins
    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 90)
        self.assertEqual(db.MIGRATIONS[-1][0], 90)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 127)
        tables = [r["name"] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()]
        self.assertNotIn("permission_previews", tables)
        self.assertNotIn("permission_preview", tables)

    # pure judgements
    def test_decide_preview_pure(self):
        self.assertIsNone(decide_preview(actor_exists=True, actor_is_admin=True, target_exists=True))
        self.assertEqual(decide_preview(actor_exists=False, actor_is_admin=False, target_exists=True), "no_such_user")
        self.assertEqual(decide_preview(actor_exists=True, actor_is_admin=False, target_exists=True), "not_site_admin")
        self.assertEqual(decide_preview(actor_exists=True, actor_is_admin=True, target_exists=False), "no_such_user")
        self.assertEqual(decide_preview(actor_exists=True, actor_is_admin=False, target_exists=False), "not_site_admin")

    def test_visible_resolutions_pure(self):
        def res(name, role):
            return Resolution(user_id=1, username="yrsa", repo_id=1, owner="crew", name=name, visibility="private", role=role, source="team" if role else "none", detail="x")
        visible, hidden = visible_resolutions([res("a", "read"), res("b", None), res("c", "admin")])
        self.assertEqual([r.name for r in visible], ["a", "c"])
        self.assertEqual(hidden, 1)
        self.assertEqual(visible_resolutions([]), ([], 0))

    # the guard
    def test_admin_can_preview_member(self):
        got = self.preview.preview(self.admin.id, self.yrsa.id)
        self.assertEqual(got.actor_username, "sitemod")
        self.assertEqual(got.target_username, "yrsa")
        self.assertFalse(got.target_is_admin)
        self.assertEqual(got.total_count, 5)
        self.assertEqual(got.role_for("crew/secret"), "write")
        self.assertEqual(got.role_for("crew/anvil"), "read")

    def test_non_admin_member_refused(self):
        self.assertEqual(self._reason(self.preview.preview, self.yrsa.id, self.bryn.id), "not_site_admin")

    def test_org_owner_is_not_enough(self):
        self.assertEqual(self._reason(self.preview.preview, self.creator.id, self.yrsa.id), "not_site_admin")

    def test_unknown_actor_refused(self):
        self.assertEqual(self._reason(self.preview.preview, 999999, self.yrsa.id), "no_such_user")

    def test_unknown_target_refused_by_id_and_name(self):
        self.assertEqual(self._reason(self.preview.preview, self.admin.id, 999999), "no_such_user")
        self.assertEqual(self._reason(self.preview.preview, self.admin.id, "nosuchperson"), "no_such_user")

    def test_non_admin_cannot_probe_targets(self):
        self.assertEqual(self._reason(self.preview.preview, self.yrsa.id, 999999), "not_site_admin")
        self.assertEqual(self._reason(self.preview.preview, self.yrsa.id, "nosuchperson"), "not_site_admin")

    def test_target_by_username_case_insensitive(self):
        by_id = self.preview.preview(self.admin.id, self.yrsa.id)
        by_name = self.preview.preview(self.admin.id, "YRSA")
        self.assertEqual(by_id.target_id, by_name.target_id)
        self.assertEqual([e.full_name for e in by_id.entries], [e.full_name for e in by_name.entries])

    def test_admin_may_preview_themself(self):
        got = self.preview.preview(self.admin.id, self.admin.id)
        self.assertTrue(got.target_is_admin)
        self.assertEqual(got.hidden_count, 0)
        self.assertEqual(got.visible_count, 5)

    # exactness against S-190
    def test_preview_matches_engine_for_every_target(self):
        for target in (self.yrsa, self.bryn, self.outsider, self.solo, self.creator, self.admin):
            got = self.preview.preview(self.admin.id, target.id)
            seen = {e.full_name: e for e in got.entries}
            self.assertEqual(got.total_count, len(self.all_repos))
            self.assertEqual(got.visible_count + got.hidden_count, got.total_count)
            for repo in self.all_repos:
                expected = self.engine.resolve(target, repo)
                if expected.role is None:
                    self.assertNotIn(repo.full_name, seen)
                else:
                    entry = seen[repo.full_name]
                    self.assertEqual(entry.role, expected.role)
                    self.assertEqual(entry.source, expected.source)
                    self.assertEqual(entry.detail, expected.detail)

    def test_member_view_team_internal_and_public(self):
        got = self.preview.preview(self.admin.id, self.yrsa.id)
        by_name = {e.full_name: e for e in got.entries}
        self.assertEqual((by_name["crew/secret"].role, by_name["crew/secret"].source), ("write", "team"))
        self.assertEqual((by_name["crew/inner"].role, by_name["crew/inner"].source), ("read", "internal"))
        self.assertEqual((by_name["crew/anvil"].role, by_name["crew/anvil"].source), ("read", "visibility"))
        self.assertEqual((by_name["solo/hammer"].role, by_name["solo/hammer"].source), ("read", "visibility"))
        self.assertNotIn("solo/vault", by_name)
        self.assertEqual(got.hidden_count, 1)

    def test_outsider_view_collaborator_grant_only(self):
        got = self.preview.preview(self.admin.id, self.outsider.id)
        by_name = {e.full_name: e for e in got.entries}
        self.assertEqual((by_name["solo/vault"].role, by_name["solo/vault"].source), ("write", "collaborator"))
        self.assertNotIn("crew/secret", by_name)
        self.assertNotIn("crew/inner", by_name)
        self.assertEqual(got.hidden_count, 2)

    def test_owner_view_own_repos_admin(self):
        got = self.preview.preview(self.admin.id, self.solo.id)
        self.assertEqual(got.role_for("solo/vault"), "admin")
        self.assertEqual(got.role_for("solo/hammer"), "admin")
        entry = [e for e in got.entries if e.full_name == "solo/vault"][0]
        self.assertEqual(entry.source, "owner")
        self.assertEqual(got.hidden_count, 2)

    def test_admin_target_sees_everything_as_site_admin(self):
        got = self.preview.preview(self.admin.id, self.admin.id)
        for entry in got.entries:
            self.assertEqual(entry.role, "admin")
        vault = [e for e in got.entries if e.full_name == "solo/vault"][0]
        self.assertEqual(vault.source, "site_admin")

    def test_org_default_shown_in_effect(self):
        self.defaults.set_default(self.creator.id, self.org.id, "read")
        got = self.preview.preview(self.admin.id, self.bryn.id)
        entry = [e for e in got.entries if e.full_name == "crew/secret"][0]
        self.assertEqual((entry.role, entry.source), ("read", "org_default"))
        yrsa = self.preview.preview(self.admin.id, self.yrsa.id)
        secret = [e for e in yrsa.entries if e.full_name == "crew/secret"][0]
        self.assertEqual((secret.role, secret.source), ("write", "team"))

    def test_entries_in_repository_order_and_counts(self):
        got = self.preview.preview(self.admin.id, self.yrsa.id)
        names = [e.full_name for e in got.entries]
        self.assertEqual(names, sorted(names, key=lambda n: (n.split("/")[0].lower(), n.split("/")[1].lower())))
        self.assertEqual(got.counts_by_role(), {"read": 3, "write": 1})

    # safety: pure read, no grant, no impersonation
    def test_preview_mutates_nothing_and_audits_nothing(self):
        before = self._table_counts()
        self.preview.preview(self.admin.id, self.yrsa.id)
        self.preview.preview(self.admin.id, self.outsider.id)
        self.preview.preview_page(self.admin.id, self.bryn.id)
        self.assertEqual(self._table_counts(), before)

    def test_preview_grants_nothing(self):
        before = {repo.full_name: self.engine.resolve(self.bryn, repo).role for repo in self.all_repos}
        self.preview.preview(self.admin.id, self.bryn.id)
        after = {repo.full_name: self.engine.resolve(self.bryn, repo).role for repo in self.all_repos}
        self.assertEqual(before, after)
        self.assertIsNone(after["solo/vault"])
        self.assertIsNone(after["crew/secret"])

    def test_refused_preview_writes_nothing(self):
        before = self._table_counts()
        self._reason(self.preview.preview, self.yrsa.id, self.bryn.id)
        self._reason(self.preview.preview, self.admin.id, 999999)
        self.assertEqual(self._table_counts(), before)

    # the page
    def test_page_states_preview_and_roles_in_words(self):
        page = self.preview.preview_page(self.admin.id, self.yrsa.id)
        self.assertIn("Permission preview", page)
        self.assertIn("Preview only", page)
        self.assertIn("not a sign-in", page)
        self.assertIn("crew/secret", page)
        self.assertIn("Write", page)
        self.assertIn("Team grant", page)
        self.assertIn("hidden", page)

    def test_page_never_names_hidden_repositories(self):
        page = self.preview.preview_page(self.admin.id, self.yrsa.id)
        self.assertNotIn("solo/vault", page)
        self.assertIn("solo/hammer", page)
        page2 = self.preview.preview_page(self.admin.id, self.outsider.id)
        self.assertNotIn("crew/secret", page2)
        self.assertNotIn("crew/inner", page2)
        self.assertIn("solo/vault", page2)

    def test_page_escapes_every_value(self):
        evil = Resolution(user_id=7, username="<script>alert(1)</script>", repo_id=1, owner="<b>crew</b>", name="a&b", visibility="private", role="read", source="visibility", detail="<img src=x onerror=alert(1)>")
        preview = PermissionPreview(actor_id=1, actor_username="<i>admin</i>", target_id=7, target_username="<script>alert(1)</script>", target_is_admin=False, entries=(evil,), hidden_count=1, total_count=2)
        page = render_permission_preview_page(preview)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertNotIn("<img src=x", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("a&amp;b", page)

    def test_empty_instance_preview_and_page(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.init_db(Path(td) / "empty.db")
            accounts = AccountStore(conn, time_fn=self.clock)
            boss = accounts.register("bosslady", "correct horse battery")
            member = accounts.register("memberone", "correct horse battery")
            with conn:
                conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (boss.id,))
            engine = PermissionPreviewEngine(conn, accounts, time_fn=self.clock)
            got = engine.preview(boss.id, member.id)
            self.assertEqual(got.entries, ())
            self.assertEqual((got.hidden_count, got.total_count), (0, 0))
            page = render_permission_preview_page(got)
            self.assertIn("can see no repositories", page)
            self.assertIn("No repositories are hidden", page)
            conn.close()


if __name__ == "__main__":
    unittest.main()
