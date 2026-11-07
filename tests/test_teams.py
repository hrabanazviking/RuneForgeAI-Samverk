"""S-187 acceptance battery: teams.

Acceptance (roadmap S-187): Teams — create, describe,
privacy (visible/secret), team pages listing members
and repos.

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
from samverk.teams import (
    TeamStore, decide_team_visibility, privacy_word,
    render_team_page, render_teams_page, team_slug,
    validate_privacy, validate_team_name)


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class TeamTests(unittest.TestCase):
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
        self.members.add_member(self.creator.id, self.org.id, self.yrsa.id)
        self.teams = TeamStore(self.conn, self.accounts, self.audit, time_fn=self.clock)

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

    # pure rules
    def test_pure_privacy_and_slug_rules(self):
        self.assertEqual(validate_privacy(" Visible "), "visible")
        self.assertEqual(validate_privacy("SECRET"), "secret")
        with self.assertRaises(OrganizationError) as ctx:
            validate_privacy("hidden")
        self.assertEqual(ctx.exception.reason, "privacy_invalid")
        self.assertEqual(privacy_word("visible"), "Visible")
        self.assertEqual(privacy_word("secret"), "Secret")
        self.assertEqual(team_slug("Core Team"), "core-team")
        self.assertEqual(team_slug("  Release__Crew!! "), "release-crew")
        self.assertEqual(validate_team_name("Core Team"), ("Core Team", "core-team"))
        self.assertTrue(decide_team_visibility("visible", False, False))
        self.assertFalse(decide_team_visibility("secret", False, False))
        self.assertTrue(decide_team_visibility("secret", True, False))
        self.assertTrue(decide_team_visibility("secret", False, True))

    def test_invalid_team_names_refused(self):
        for bad in ("", "   ", "!!!", "x" * 51, "core\x01team", 42):
            with self.assertRaises(OrganizationError):
                validate_team_name(bad)
        self.assertEqual(
            self._reason(self.teams.create_team, self.creator.id, self.org.id, "!!!"),
            "team_invalid")
        self.assertEqual(self.teams.list_teams(self.org.id), [])

    # create
    def test_create_visible_team_creator_is_first_member(self):
        before = self._updates()
        team = self.teams.create_team(self.creator.id, self.org.id, "Core Team", description="The core crew.")
        self.assertEqual(team.name, "Core Team")
        self.assertEqual(team.name_lower, "core-team")
        self.assertEqual(team.description, "The core crew.")
        self.assertEqual(team.privacy, "visible")
        self.assertTrue(self.teams.is_team_member(self.creator.id, team.id))
        self.assertEqual([m.username for m in self.teams.list_members(self.org.id, team.id)], ["volmarr"])
        self.assertEqual(self._updates(), before + 1)
        self.assertEqual(self.teams.get_team_by_name(self.org.id, "core team").id, team.id)

    def test_create_secret_team_by_site_admin(self):
        team = self.teams.create_team(self.admin.id, self.org.id, "wardens", privacy="secret")
        self.assertEqual(team.privacy, "secret")
        self.assertTrue(self.teams.is_team_member(self.admin.id, team.id))

    def test_create_refused_for_plain_member_and_outsider(self):
        self.assertEqual(
            self._reason(self.teams.create_team, self.yrsa.id, self.org.id, "core"),
            "not_org_owner")
        self.assertEqual(
            self._reason(self.teams.create_team, self.bryn.id, self.org.id, "core"),
            "not_org_owner")
        self.assertEqual(self.teams.list_teams(self.org.id), [])

    def test_create_unknown_org_and_actor(self):
        self.assertEqual(
            self._reason(self.teams.create_team, self.creator.id, 424242, "core"),
            "org_not_found")
        self.assertEqual(
            self._reason(self.teams.create_team, 999999, self.org.id, "core"),
            "no_such_user")

    def test_duplicate_slug_refused_same_name_elsewhere_ok(self):
        self.teams.create_team(self.creator.id, self.org.id, "Core Team")
        self.assertEqual(
            self._reason(self.teams.create_team, self.creator.id, self.org.id, "core  team"),
            "team_taken")
        org2 = self.orgs.create_organization(self.creator.id, "fleet")
        other = self.teams.create_team(self.creator.id, org2.id, "Core Team")
        self.assertEqual(other.org_id, org2.id)

    def test_create_invalid_privacy_and_description_refused(self):
        self.assertEqual(
            self._reason(self.teams.create_team, self.creator.id, self.org.id, "core", privacy="hidden"),
            "privacy_invalid")
        self.assertEqual(
            self._reason(self.teams.create_team, self.creator.id, self.org.id, "core", description="x" * 501),
            "description_too_long")
        self.assertEqual(
            self._reason(self.teams.create_team, self.creator.id, self.org.id, "core", description="bad\x01desc"),
            "description_invalid")
        self.assertEqual(self.teams.list_teams(self.org.id), [])

    # update
    def test_update_description_and_privacy(self):
        team = self.teams.create_team(self.creator.id, self.org.id, "core")
        updated = self.teams.update_team(self.creator.id, self.org.id, team.id, description="New words.", privacy="secret")
        self.assertEqual(updated.description, "New words.")
        self.assertEqual(updated.privacy, "secret")
        kept = self.teams.update_team(self.creator.id, self.org.id, team.id, description="")
        self.assertIsNone(kept.description)
        self.assertEqual(kept.privacy, "secret")
        self.assertEqual(
            self._reason(self.teams.update_team, self.yrsa.id, self.org.id, team.id, description="nope"),
            "not_org_owner")

    # members
    def test_add_org_member_to_team(self):
        team = self.teams.create_team(self.creator.id, self.org.id, "core")
        made = self.teams.add_member(self.creator.id, self.org.id, team.id, "YRSA")
        self.assertEqual(made.username, "yrsa")
        self.assertEqual([m.username for m in self.teams.list_members(self.org.id, team.id)], ["volmarr", "yrsa"])
        self.assertEqual(
            self._reason(self.teams.add_member, self.creator.id, self.org.id, team.id, self.yrsa.id),
            "already_team_member")

    def test_add_non_org_member_refused_plainly(self):
        team = self.teams.create_team(self.creator.id, self.org.id, "core")
        self.assertEqual(
            self._reason(self.teams.add_member, self.creator.id, self.org.id, team.id, self.bryn.id),
            "not_org_member")
        self.assertFalse(self.teams.is_team_member(self.bryn.id, team.id))
        self.assertEqual(
            self._reason(self.teams.add_member, self.creator.id, self.org.id, team.id, "ghost"),
            "no_such_user")

    def test_remove_team_member(self):
        team = self.teams.create_team(self.creator.id, self.org.id, "core")
        self.teams.add_member(self.creator.id, self.org.id, team.id, self.yrsa.id)
        self.teams.remove_member(self.creator.id, self.org.id, team.id, self.yrsa.id)
        self.assertFalse(self.teams.is_team_member(self.yrsa.id, team.id))
        self.assertEqual(
            self._reason(self.teams.remove_member, self.creator.id, self.org.id, team.id, self.yrsa.id),
            "not_team_member")
        self.assertEqual(
            self._reason(self.teams.add_member, self.yrsa.id, self.org.id, team.id, self.bryn.id),
            "not_org_owner")

    # repos
    def test_link_and_list_org_repos(self):
        team = self.teams.create_team(self.creator.id, self.org.id, "core")
        anvil = self._repo("crew", "anvil")
        boat = self._repo("crew", "boat")
        self.teams.link_repo(self.creator.id, self.org.id, team.id, boat)
        link = self.teams.link_repo(self.creator.id, self.org.id, team.id, anvil)
        self.assertEqual(link.name, "anvil")
        self.assertEqual([r.name for r in self.teams.list_repos(self.org.id, team.id)], ["anvil", "boat"])
        self.assertEqual(
            self._reason(self.teams.link_repo, self.creator.id, self.org.id, team.id, anvil),
            "already_linked")

    def test_link_foreign_or_missing_repo_refused(self):
        team = self.teams.create_team(self.creator.id, self.org.id, "core")
        foreign = self._repo("yrsa", "diary")
        self.assertEqual(
            self._reason(self.teams.link_repo, self.creator.id, self.org.id, team.id, foreign),
            "repo_not_in_org")
        self.assertEqual(
            self._reason(self.teams.link_repo, self.creator.id, self.org.id, team.id, 999999),
            "repo_not_found")
        self.assertEqual(self.teams.list_repos(self.org.id, team.id), [])

    def test_unlink_repo(self):
        team = self.teams.create_team(self.creator.id, self.org.id, "core")
        anvil = self._repo("crew", "anvil")
        self.assertEqual(
            self._reason(self.teams.unlink_repo, self.creator.id, self.org.id, team.id, anvil),
            "not_linked")
        self.teams.link_repo(self.creator.id, self.org.id, team.id, anvil)
        self.teams.unlink_repo(self.creator.id, self.org.id, team.id, anvil)
        self.assertEqual(self.teams.list_repos(self.org.id, team.id), [])

    # privacy / viewers
    def test_secret_team_hidden_from_non_members(self):
        secret = self.teams.create_team(self.creator.id, self.org.id, "wardens", privacy="secret")
        visible = self.teams.create_team(self.creator.id, self.org.id, "core")
        self.assertEqual(
            self._reason(self.teams.get_team_for_viewer, self.yrsa.id, self.org.id, secret.id),
            "team_not_found")
        self.assertEqual(
            self._reason(self.teams.get_team_for_viewer, self.yrsa.id, self.org.id, 999999),
            "team_not_found")
        self.assertEqual(
            [t.name for t in self.teams.list_teams_for_viewer(self.yrsa.id, self.org.id)],
            ["core"])
        self.assertEqual(self.teams.get_team_for_viewer(self.yrsa.id, self.org.id, visible.id).id, visible.id)
        self.assertEqual(self.teams.get_team_for_viewer(None, self.org.id, visible.id).id, visible.id)
        self.assertEqual(
            self._reason(self.teams.get_team_for_viewer, None, self.org.id, secret.id),
            "team_not_found")

    def test_secret_team_visible_to_members_and_admin(self):
        secret = self.teams.create_team(self.creator.id, self.org.id, "wardens", privacy="secret")
        self.teams.add_member(self.creator.id, self.org.id, secret.id, self.yrsa.id)
        self.assertEqual(self.teams.get_team_for_viewer(self.yrsa.id, self.org.id, secret.id).id, secret.id)
        self.assertEqual(self.teams.get_team_for_viewer(self.admin.id, self.org.id, secret.id).id, secret.id)
        self.assertEqual(
            [t.name for t in self.teams.list_teams_for_viewer(self.yrsa.id, self.org.id)],
            ["wardens"])

    def test_refusals_audit_nothing(self):
        before = self._updates()
        team = self.teams.create_team(self.creator.id, self.org.id, "core")
        mid = self._updates()
        self.assertEqual(mid, before + 1)
        for fn, args, kwargs in (
            (self.teams.create_team, (self.yrsa.id, self.org.id, "nope"), {}),
            (self.teams.add_member, (self.creator.id, self.org.id, team.id, self.bryn.id), {}),
            (self.teams.link_repo, (self.creator.id, self.org.id, team.id, 999999), {}),
        ):
            with self.assertRaises(OrganizationError):
                fn(*args, **kwargs)
        self.assertEqual(self._updates(), mid)

    # pages
    def test_team_page_lists_members_and_repos_escaped(self):
        org2 = self.orgs.create_organization(self.creator.id, "fleet", display_name="Fleet <script>alert(1)</script>")
        team = self.teams.create_team(self.creator.id, org2.id, "Core <b>Team</b>", description="We <i>build</i> things.", privacy="secret")
        self.members.add_member(self.creator.id, org2.id, self.yrsa.id)
        self.teams.add_member(self.creator.id, org2.id, team.id, self.yrsa.id)
        repo_id = self._repo("fleet", "anvil")
        self.teams.link_repo(self.creator.id, org2.id, team.id, repo_id)
        html = render_team_page(org2, team, self.teams.list_members(org2.id, team.id), self.teams.list_repos(org2.id, team.id))
        self.assertNotIn("<script>", html)
        self.assertNotIn("<b>Team</b>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("volmarr", html)
        self.assertIn("yrsa", html)
        self.assertIn("fleet/anvil", html)
        self.assertIn("Secret", html)
        self.assertIn("S-189", html)

    def test_team_page_empty_repos_honest_and_teams_page(self):
        team = self.teams.create_team(self.creator.id, self.org.id, "core", description="The core crew.")
        html = render_team_page(self.org, team, self.teams.list_members(self.org.id, team.id), self.teams.list_repos(self.org.id, team.id))
        self.assertIn("No repositories are linked to this team yet", html)
        self.assertIn("Visible", html)
        listing = render_teams_page(self.org, self.teams.list_teams(self.org.id))
        self.assertIn("core", listing)
        self.assertIn("The core crew.", listing)
        empty = render_teams_page(self.org, [])
        self.assertIn("No teams yet.", empty)

    def test_settings_areas_teams_available(self):
        by_key = {a["key"]: a for a in settings_areas()}
        self.assertTrue(by_key["teams"]["available"])
        self.assertEqual(by_key["teams"]["slice"], "S-187")

    # pins
    def test_migration_70_pin(self):
        self.assertEqual(schema_version(self.conn), 71)
        self.assertEqual(db.MIGRATIONS[-1][0], 71)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 122)
        for table, cols in (
            ("teams", ("id", "org_id", "name", "name_lower", "description", "privacy", "created_by", "created_at", "updated_at")),
            ("team_members", ("team_id", "user_id", "added_by", "created_at")),
            ("team_repositories", ("team_id", "repo_id", "added_by", "created_at")),
        ):
            have = [r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})").fetchall()]
            for col in cols:
                self.assertIn(col, have)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "old.db"
            conn = db.connect(path)
            for version, statements in db.MIGRATIONS:
                if version > 69:
                    continue
                with conn:
                    for stmt in statements:
                        conn.execute(stmt)
                    conn.execute("INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('version', ?)", (str(version),))
            conn.close()
            conn = db.init_db(path)
            self.assertEqual(db.schema_version(conn), 71)
            names = [r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('teams', 'team_members', 'team_repositories') ORDER BY name").fetchall()]
            self.assertEqual(names, ["team_members", "team_repositories", "teams"])
            conn.close()


if __name__ == "__main__":
    unittest.main()
