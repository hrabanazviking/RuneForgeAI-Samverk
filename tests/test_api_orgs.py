"""S-244 acceptance battery: users, orgs, teams API.

Acceptance (roadmap S-244): Users, orgs, teams
API -- membership and permission administration
automatable end-to-end.

The centre is samverk/api_orgs.py: the contract's
users / organizations / teams families delegating
every act to the web's own stores (S-029 profiles,
S-185 organizations, S-186 membership, S-187
teams, S-189 team permissions, S-192 the default
permission, S-191 outside collaborators), judged
through S-238's door with the profile scope as
ceiling and S-190's engine at the admin rung for
the repository-scoped children, with refusals in
S-240's one problem format. The centre test drives
the whole administration end-to-end through the
API alone: an org is created, staffed, teamed,
graded, defaulted and granted -- and S-190's
engine is asked at the end what the script built.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import base64, json, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.access_tokens import AccessTokenStore
from samverk.accounts import AccountStore
from samverk.api_contract import PROBLEM_FIELDS, get_resource
from samverk.api_orgs import (
    USERS_ORGS_TEAMS_API_PATH, UsersOrgsTeamsAPI,
    UsersOrgsTeamsAPIError, collaborator_to_dict,
    default_permission_to_dict, error_to_dict, member_to_dict,
    organization_to_dict, render_users_orgs_teams_api_page,
    team_member_to_dict, team_permission_to_dict, team_to_dict,
    user_to_dict)
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.fine_grained_tokens import FineTokenStore
from samverk.org_repositories import OrgRepoStore
from samverk.organizations import OrganizationStore
from samverk.permission_engine import PermissionEngine
from samverk.profiles import ProfileStore
from samverk.repositories import RepositoryStore

PW = "correct horse battery"


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


def basic(username, credential):
    raw = base64.b64encode(f"{username}:{credential}".encode("utf-8"))
    return "Basic " + raw.decode("ascii")


def make_world(root: Path) -> SimpleNamespace:
    conn = db.init_db(root / "samverk.db")
    clock = Clock()
    audit = AuditLog(conn, time_fn=clock)
    accounts = AccountStore(conn, audit=audit, time_fn=clock)
    owner = accounts.register("volmarr", PW)
    member = accounts.register("yrsa", PW)
    outsider = accounts.register("mallory", PW)
    admin = accounts.register("sigrid", PW)
    conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?",
                 (admin.id,))
    conn.commit()
    admin = accounts.get_by_id(admin.id)
    repos = RepositoryStore(conn, root, accounts, audit=audit)
    orgs = OrganizationStore(conn, accounts, audit=audit,
                             time_fn=clock)
    profiles = ProfileStore(conn, accounts, audit=audit,
                            time_fn=clock)
    org_repos = OrgRepoStore(conn, accounts, root, audit=audit,
                             time_fn=clock)
    api = UsersOrgsTeamsAPI(conn, accounts, repos, audit=audit,
                            time_fn=clock)
    engine = PermissionEngine(conn, accounts, audit=None,
                              time_fn=clock)
    w = SimpleNamespace(
        conn=conn, clock=clock, audit=audit, accounts=accounts,
        owner=owner, member=member, outsider=outsider, admin=admin,
        repos=repos, orgs=orgs, profiles=profiles,
        org_repos=org_repos, api=api, engine=engine, root=root)
    w.org = orgs.create_organization(
        owner.id, "Forge", display_name="The Forge",
        bio="We build tools.")
    w.pub = repos.create_repository(
        owner.id, "volmarr", "pub", visibility="public")
    classic = AccessTokenStore(conn, accounts, audit=audit,
                               time_fn=clock)
    fine = FineTokenStore(conn, accounts, audit=audit,
                          time_fn=clock)
    expiry = clock.now + 3600
    _, w.owner_profile = classic.create_token(
        owner.id, "profile", {"profile:write"}, expiry)
    _, w.owner_repo_only = classic.create_token(
        owner.id, "repoonly", {"repo:read"}, expiry)
    _, w.fine_pub = fine.create_token(
        owner.id, "volmarr", "pub", "fine pub",
        {"contents:write", "metadata:read"}, expiry)
    w.owner_basic = basic("volmarr", PW)
    w.member_basic = basic("yrsa", PW)
    w.outsider_basic = basic("mallory", PW)
    w.admin_basic = basic("sigrid", PW)
    return w


class UsersOrgsTeamsAPITests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.w = make_world(Path(self._td.name))
        self.addCleanup(self.w.conn.close)

    def reason(self, fn, *args, **kwargs):
        with self.assertRaises(UsersOrgsTeamsAPIError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    # -- pins ------------------------------------------------
    def test_schema_taxonomy_and_path_pins(self):
        self.assertEqual(schema_version(self.w.conn), 103)
        self.assertEqual(db.MIGRATIONS[-1][0], 103)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 131)
        self.assertEqual(USERS_ORGS_TEAMS_API_PATH,
                         "/api/users-orgs-teams")
        for rid in ("user", "organizations", "organization",
                    "organization-members", "organization-member",
                    "organization-teams", "team", "team-members",
                    "team-member", "team-repositories",
                    "team-repository",
                    "organization-default-permission",
                    "repository-collaborators",
                    "repository-collaborator"):
            resource = get_resource(rid)
            self.assertEqual(resource.standing, "landed", rid)
            self.assertEqual(resource.slice, "S-244", rid)

    def test_serialiser_shapes_are_the_contracts(self):
        w = self.w
        profile = w.profiles.get_profile(w.owner.id)
        self.assertEqual(
            tuple(user_to_dict(w.owner, profile).keys()),
            ("username", "display_name", "bio", "created_at"))
        self.assertEqual(
            tuple(organization_to_dict(w.org).keys()),
            ("id", "name", "display_name", "description",
             "created_at"))

    # -- users -------------------------------------------------
    def test_get_user_anonymous_shape_and_profile_facts(self):
        w = self.w
        answer = w.api.get_user(None, "yrsa")
        self.assertEqual(answer["username"], "yrsa")
        self.assertEqual(answer["display_name"], "yrsa")
        self.assertIsNone(answer["bio"])
        w.profiles.update_profile(
            w.member.id, display_name="Yrsa F.",
            bio="Seeress <script>alert(1)</script>")
        answer = w.api.get_user(None, "YRSA")
        self.assertEqual(answer["display_name"], "Yrsa F.")
        # Data carries raw values: escaping is the page's law.
        self.assertEqual(answer["bio"],
                         "Seeress <script>alert(1)</script>")

    def test_get_user_missing_and_problem_shape(self):
        w = self.w
        exc_reason = self.reason(w.api.get_user, None, "ghost")
        self.assertEqual(exc_reason, "no_such_user")
        try:
            w.api.get_user(None, "ghost")
        except UsersOrgsTeamsAPIError as exc:
            rendered = error_to_dict(exc)
        self.assertEqual(tuple(rendered.keys()), PROBLEM_FIELDS)
        self.assertEqual(rendered["status"], 404)
        self.assertEqual(
            rendered["type"], "/api/v1/problems/no_such_user")
        self.assertEqual(json.loads(json.dumps(rendered)), rendered)

    def test_user_read_scope_ceiling(self):
        w = self.w
        self.assertEqual(
            self.reason(w.api.get_user,
                        f"Bearer {w.owner_repo_only}", "yrsa"),
            "insufficient_scope")
        answer = w.api.get_user(
            f"Bearer {w.owner_profile}", "yrsa")
        self.assertEqual(answer["username"], "yrsa")
        # Fine-grained tokens hold no profile permission.
        self.assertEqual(
            self.reason(w.api.get_user,
                        f"Bearer {w.fine_pub}", "yrsa"),
            "insufficient_scope")
        self.assertEqual(
            self.reason(w.api.get_user, "Bearer svk_nope", "yrsa"),
            "credentials_invalid")

    # -- organizations ------------------------------------------
    def test_create_organization_end_to_end_refusals(self):
        w = self.w
        created = w.api.create_organization(
            w.owner_basic, {"name": "Anvil-Crew",
                            "description": "Second crew."})
        self.assertEqual(created["name"], "Anvil-Crew")
        self.assertEqual(created["description"], "Second crew.")
        self.assertEqual(
            self.reason(w.api.create_organization,
                        w.owner_basic, {"name": "anvil-crew"}),
            "org_taken")
        self.assertEqual(
            self.reason(w.api.create_organization,
                        w.owner_basic, {"name": "yrsa"}),
            "org_name_is_user")
        self.assertEqual(
            self.reason(w.api.create_organization,
                        None, {"name": "Third"}),
            "authentication_required")
        self.assertEqual(
            self.reason(w.api.create_organization,
                        w.owner_basic, {"name": "X", "bogus": 1}),
            "payload_invalid")

    def test_list_and_get_organization(self):
        w = self.w
        answer = w.api.list_organizations(None)
        self.assertEqual(answer["total"], 1)
        self.assertEqual(answer["organizations"][0]["name"], "Forge")
        self.assertTrue(answer["complete"])
        cut = w.api.list_organizations(None, limit=1)
        self.assertEqual(cut["returned"], 1)
        got = w.api.get_organization(None, "forge")
        self.assertEqual(got["display_name"], "The Forge")
        self.assertEqual(got["description"], "We build tools.")
        self.assertEqual(
            self.reason(w.api.get_organization, None, "nope"),
            "org_not_found")
        self.assertEqual(
            self.reason(w.api.list_organizations, None, limit=0),
            "limit_invalid")

    def test_update_organization_partial_and_steward_parity(self):
        w = self.w
        updated = w.api.update_organization(
            w.owner_basic, "Forge", {"display_name": "Forge Hall"})
        self.assertEqual(updated["display_name"], "Forge Hall")
        # An unnamed field is carried over untouched.
        self.assertEqual(updated["description"], "We build tools.")
        cleared = w.api.update_organization(
            w.owner_basic, "Forge", {"description": ""})
        self.assertIsNone(cleared["description"])
        # A second owner (not the S-185 steward) is refused by
        # the store exactly as on the web: parity, verbatim.
        w.api.add_member(w.owner_basic, "Forge",
                         {"username": "yrsa", "role": "owner"})
        self.assertEqual(
            self.reason(w.api.update_organization,
                        w.member_basic, "Forge",
                        {"display_name": "Nope"}),
            "not_org_steward")
        # A site admin may steward, as on the web.
        by_admin = w.api.update_organization(
            w.admin_basic, "Forge", {"display_name": "Forge Hall"})
        self.assertEqual(by_admin["display_name"], "Forge Hall")
        self.assertEqual(
            self.reason(w.api.update_organization,
                        w.owner_basic, "Forge", {}),
            "payload_invalid")

    # -- members --------------------------------------------------
    def test_member_administration_and_last_owner(self):
        w = self.w
        added = w.api.add_member(
            w.owner_basic, "Forge", {"username": "yrsa"})
        self.assertEqual(added, {"username": "yrsa",
                                 "role": "member",
                                 "since": added["since"]})
        self.assertEqual(
            self.reason(w.api.add_member, w.owner_basic, "Forge",
                        {"username": "yrsa"}),
            "already_member")
        self.assertEqual(
            self.reason(w.api.add_member, w.member_basic, "Forge",
                        {"username": "mallory"}),
            "not_org_owner")
        self.assertEqual(
            self.reason(w.api.add_member, w.owner_basic, "Forge",
                        {"username": "mallory", "role": "boss"}),
            "role_invalid")
        listing = w.api.list_members(None, "Forge")
        self.assertEqual(
            [m["username"] for m in listing["members"]],
            ["volmarr", "yrsa"])
        self.assertEqual(listing["members"][0]["role"], "owner")
        # The last owner can be neither removed nor demoted.
        self.assertEqual(
            self.reason(w.api.remove_member,
                        w.owner_basic, "Forge", "volmarr"),
            "last_owner")
        self.assertEqual(
            self.reason(w.api.update_member,
                        w.owner_basic, "Forge", "volmarr",
                        {"role": "member"}),
            "last_owner")
        promoted = w.api.update_member(
            w.owner_basic, "Forge", "yrsa", {"role": "owner"})
        self.assertEqual(promoted["role"], "owner")
        removed = w.api.remove_member(
            w.owner_basic, "Forge", "yrsa")
        self.assertTrue(removed["removed"])
        self.assertEqual(
            self.reason(w.api.remove_member,
                        w.owner_basic, "Forge", "yrsa"),
            "not_a_member")

    def test_get_member_is_administration_gated(self):
        w = self.w
        w.api.add_member(w.owner_basic, "Forge", {"username": "yrsa"})
        got = w.api.get_member(w.owner_basic, "Forge", "yrsa")
        self.assertEqual(got["role"], "member")
        self.assertEqual(
            self.reason(w.api.get_member,
                        w.member_basic, "Forge", "yrsa"),
            "not_org_owner")
        self.assertEqual(
            self.reason(w.api.get_member, None, "Forge", "yrsa"),
            "authentication_required")
        self.assertEqual(
            self.reason(w.api.get_member,
                        w.owner_basic, "Forge", "mallory"),
            "not_a_member")

    # -- teams ------------------------------------------------------
    def test_secret_team_is_invisible_to_outsiders(self):
        w = self.w
        w.api.add_member(w.owner_basic, "Forge", {"username": "yrsa"})
        w.api.create_team(w.owner_basic, "Forge",
                          {"name": "Open Crew"})
        w.api.create_team(w.owner_basic, "Forge",
                          {"name": "Hidden Crew",
                           "privacy": "secret"})
        anon = w.api.list_teams(None, "Forge")
        self.assertEqual(
            [t["slug"] for t in anon["teams"]], ["open-crew"])
        owners = w.api.list_teams(w.owner_basic, "Forge")
        self.assertEqual(owners["total"], 2)
        missing = self.reason(w.api.get_team, None, "Forge", "nope")
        hidden = self.reason(
            w.api.get_team, w.outsider_basic, "Forge", "hidden-crew")
        self.assertEqual(missing, "team_not_found")
        self.assertEqual(hidden, missing)
        member_view = w.api.get_team(
            w.member_basic, "Forge", "open-crew")
        self.assertEqual(member_view["privacy"], "visible")
        self.assertEqual(
            self.reason(w.api.create_team, w.owner_basic, "Forge",
                        {"name": "Open Crew"}),
            "team_taken")

    def test_team_update_and_nesting(self):
        w = self.w
        parent = w.api.create_team(
            w.owner_basic, "Forge", {"name": "Smiths"})
        child = w.api.create_team(
            w.owner_basic, "Forge",
            {"name": "Apprentices", "parent": "smiths"})
        self.assertEqual(child["slug"], "apprentices")
        self.assertEqual(
            self.reason(w.api.create_team, w.owner_basic, "Forge",
                        {"name": "Orphans", "parent": "ghost"}),
            "parent_not_found")
        updated = w.api.update_team(
            w.owner_basic, "Forge", "smiths",
            {"privacy": "secret"})
        self.assertEqual(updated["privacy"], "secret")
        self.assertEqual(
            self.reason(w.api.update_team, w.outsider_basic,
                        "Forge", "smiths", {"privacy": "visible"}),
            "not_org_owner")

    def test_team_members_doors(self):
        w = self.w
        w.api.create_team(w.owner_basic, "Forge", {"name": "Crew"})
        self.assertEqual(
            self.reason(w.api.add_team_member,
                        w.owner_basic, "Forge", "crew",
                        {"username": "mallory"}),
            "not_org_member")
        w.api.add_member(w.owner_basic, "Forge", {"username": "yrsa"})
        added = w.api.add_team_member(
            w.owner_basic, "Forge", "crew", {"username": "yrsa"})
        self.assertEqual(added["username"], "yrsa")
        self.assertEqual(
            self.reason(w.api.add_team_member,
                        w.owner_basic, "Forge", "crew",
                        {"username": "yrsa"}),
            "already_team_member")
        listing = w.api.list_team_members(None, "Forge", "crew")
        self.assertEqual(
            [m["username"] for m in listing["members"]],
            ["volmarr", "yrsa"])
        removed = w.api.remove_team_member(
            w.owner_basic, "Forge", "crew", "yrsa")
        self.assertTrue(removed["removed"])
        self.assertEqual(
            self.reason(w.api.remove_team_member,
                        w.owner_basic, "Forge", "crew", "yrsa"),
            "not_team_member")

    # -- team repository permissions --------------------------------
    def test_team_repository_permissions(self):
        w = self.w
        anvil = w.org_repos.create_repository(
            w.owner.id, w.org.id, "anvil", visibility="private")
        w.api.create_team(w.owner_basic, "Forge", {"name": "Crew"})
        linked = w.api.link_team_repository(
            w.owner_basic, "Forge", "crew",
            {"repository": "anvil", "permission": "write"})
        self.assertEqual(linked, {"repository": "Forge/anvil",
                                  "permission": "write"})
        self.assertEqual(
            self.reason(w.api.link_team_repository,
                        w.owner_basic, "Forge", "crew",
                        {"repository": "anvil"}),
            "already_linked")
        self.assertEqual(
            self.reason(w.api.link_team_repository,
                        w.owner_basic, "Forge", "crew",
                        {"repository": "pub"}),
            "repo_not_found")
        graded = w.api.update_team_repository(
            w.owner_basic, "Forge", "crew", "anvil",
            {"permission": "maintain"})
        self.assertEqual(graded["permission"], "maintain")
        listing = w.api.list_team_repositories(
            w.owner_basic, "Forge", "crew")
        self.assertEqual(listing["repositories"], [graded])
        w.api.add_member(w.owner_basic, "Forge", {"username": "yrsa"})
        self.assertEqual(
            self.reason(w.api.list_team_repositories,
                        w.member_basic, "Forge", "crew"),
            "not_org_owner")
        unlinked = w.api.unlink_team_repository(
            w.owner_basic, "Forge", "crew", "anvil")
        self.assertTrue(unlinked["removed"])
        self.assertEqual(
            self.reason(w.api.update_team_repository,
                        w.owner_basic, "Forge", "crew", "anvil",
                        {"permission": "read"}),
            "not_linked")

    def test_team_link_to_foreign_repo_refused_by_store(self):
        w = self.w
        # A repository owned by the org in name only is the
        # store's line: a personal repo of a same-named user
        # cannot exist (shared namespace), so the foreign
        # case is a repo of another org entirely.
        other = w.orgs.create_organization(w.owner.id, "Other")
        w.org_repos.create_repository(
            w.owner.id, other.id, "foreign", visibility="private")
        w.api.create_team(w.owner_basic, "Forge", {"name": "Crew"})
        self.assertEqual(
            self.reason(w.api.link_team_repository,
                        w.owner_basic, "Forge", "crew",
                        {"repository": "foreign"}),
            "repo_not_found")

    # -- default permission -------------------------------------------
    def test_default_permission_lifecycle(self):
        w = self.w
        unset = w.api.get_default_permission(w.owner_basic, "Forge")
        self.assertEqual(unset, {"role": "none", "is_set": False})
        self.assertEqual(
            tuple(default_permission_to_dict(
                w.api._defaults.get_default(w.org.id)).keys()),
            ("role", "is_set"))
        set_read = w.api.update_default_permission(
            w.owner_basic, "Forge", {"role": "read"})
        self.assertEqual(set_read, {"role": "read", "is_set": True})
        again = w.api.update_default_permission(
            w.owner_basic, "Forge", {"role": "read"})
        self.assertEqual(again, set_read)  # the store's no-op
        cleared = w.api.update_default_permission(
            w.owner_basic, "Forge", {"role": "none"})
        self.assertEqual(cleared, {"role": "none", "is_set": False})
        self.assertEqual(
            self.reason(w.api.update_default_permission,
                        w.owner_basic, "Forge", {"role": "boss"}),
            "role_invalid")
        self.assertEqual(
            self.reason(w.api.get_default_permission,
                        w.outsider_basic, "Forge"),
            "not_org_owner")

    # -- outside collaborators -------------------------------------------
    def test_collaborator_administration(self):
        w = self.w
        granted = w.api.add_collaborator(
            w.owner_basic, "volmarr", "pub",
            {"username": "mallory", "role": "write"})
        self.assertEqual(
            granted, {"username": "mallory", "role": "write",
                      "repository": "volmarr/pub"})
        self.assertEqual(
            tuple(collaborator_to_dict(
                w.api._collabs.get_grant(
                    w.pub.id, w.outsider.id)).keys()),
            ("username", "role", "repository"))
        self.assertEqual(
            self.reason(w.api.add_collaborator,
                        w.owner_basic, "volmarr", "pub",
                        {"username": "mallory", "role": "read"}),
            "already_collaborator")
        listing = w.api.list_collaborators(
            w.owner_basic, "volmarr", "pub")
        self.assertEqual(listing["collaborators"], [granted])
        moved = w.api.update_collaborator(
            w.owner_basic, "volmarr", "pub", "mallory",
            {"role": "triage"})
        self.assertEqual(moved["role"], "triage")
        # A stranger cannot even list: S-190 answers the one
        # repo_not_found, as for a missing repository.
        stranger = self.reason(
            w.api.list_collaborators,
            w.outsider_basic, "volmarr", "pub")
        missing = self.reason(
            w.api.list_collaborators,
            w.owner_basic, "volmarr", "ghost")
        self.assertEqual(stranger, "repo_not_found")
        self.assertEqual(missing, stranger)
        removed = w.api.remove_collaborator(
            w.owner_basic, "volmarr", "pub", "mallory")
        self.assertEqual(removed, moved)
        self.assertEqual(
            self.reason(w.api.remove_collaborator,
                        w.owner_basic, "volmarr", "pub", "mallory"),
            "not_collaborator")

    def test_collaborator_org_member_refused(self):
        w = self.w
        anvil = w.org_repos.create_repository(
            w.owner.id, w.org.id, "anvil", visibility="private")
        w.api.add_member(w.owner_basic, "Forge", {"username": "yrsa"})
        self.assertEqual(
            self.reason(w.api.add_collaborator,
                        w.owner_basic, "Forge", "anvil",
                        {"username": "yrsa", "role": "read"}),
            "already_member")
        granted = w.api.add_collaborator(
            w.owner_basic, "Forge", "anvil",
            {"username": "mallory", "role": "read"})
        self.assertEqual(granted["repository"], "Forge/anvil")
        self.assertIsNotNone(anvil)

    # -- the centre: end-to-end administration -------------------------
    def test_end_to_end_administration_through_the_api(self):
        w = self.w
        api = w.api
        # A script creates and staffs an organization.
        org = api.create_organization(
            w.owner_basic, {"name": "SecondForge"})
        self.assertEqual(org["name"], "SecondForge")
        api.add_member(w.owner_basic, "SecondForge",
                       {"username": "yrsa"})
        api.add_member(w.owner_basic, "SecondForge",
                       {"username": "mallory"})
        # A team is stood up and staffed.
        api.create_team(w.owner_basic, "SecondForge",
                        {"name": "Builders"})
        api.add_team_member(w.owner_basic, "SecondForge",
                            "builders", {"username": "yrsa"})
        # Its repository is created on the web's own org door,
        # then linked and graded through the API.
        org_row = w.orgs.get_by_name("SecondForge")
        anvil = w.org_repos.create_repository(
            w.owner.id, org_row.id, "anvil", visibility="private")
        linked = api.link_team_repository(
            w.owner_basic, "SecondForge", "builders",
            {"repository": "anvil", "permission": "write"})
        self.assertEqual(linked["permission"], "write")
        graded = api.update_team_repository(
            w.owner_basic, "SecondForge", "builders", "anvil",
            {"permission": "maintain"})
        self.assertEqual(graded["permission"], "maintain")
        # The default gives every member a floor.
        api.update_default_permission(
            w.owner_basic, "SecondForge", {"role": "read"})
        # S-190's engine reads what the script built: the team
        # member stands at maintain (her team's grant), a plain
        # member at the default's read, an outsider nowhere.
        repo = w.repos.get_repository("SecondForge", "anvil")
        self.assertEqual(
            w.engine.role_for(w.member, repo), "maintain")
        self.assertEqual(
            w.engine.role_for(w.outsider, repo), "read")
        stranger = w.accounts.register("soren", PW)
        self.assertIsNone(w.engine.role_for(stranger, repo))
        # An outside grant lands, moves, and is revoked.
        api.add_collaborator(
            w.owner_basic, "SecondForge", "anvil",
            {"username": "soren", "role": "triage"})
        self.assertEqual(w.engine.role_for(stranger, repo), "triage")
        api.remove_collaborator(
            w.owner_basic, "SecondForge", "anvil", "soren")
        self.assertIsNone(w.engine.role_for(stranger, repo))
        # The witnesses are the stores' own events.
        actions = [row["action"] for row in
                   w.conn.execute("SELECT action FROM audit_log")
                   .fetchall()]
        self.assertIn("auth.organization.create", actions)
        self.assertIn("auth.organization.update", actions)
        self.assertIn("repo.collaborator.add", actions)
        self.assertIn("repo.collaborator.remove", actions)
        self.assertIsNotNone(anvil)

    # -- the page ---------------------------------------------------------
    def test_page_speaks_plainly(self):
        page = render_users_orgs_teams_api_page()
        self.assertIn("Users, organizations and teams API", page)
        self.assertIn("automatable end-to-end", page)
        self.assertIn("last owner cannot be removed", page)


if __name__ == "__main__":
    unittest.main()
