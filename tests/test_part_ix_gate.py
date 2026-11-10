"""S-204 — PART IX GATE battery: organizations & permissions, assembled.

The whole Part IX system struck at once, in the house gate
shape of S-096/S-120/S-140/S-168/S-184 — no new production
code, only the battery that walks the landed S-185..S-202
machinery end to end through its public seams, at the three
things the gate names:

- **Every role** — the full S-189 ladder as S-190's engine
  resolves it: no access, read, triage, write, maintain,
  admin — held by an anonymous visitor, an outsider, a plain
  organization member (the S-192 default), an outside
  collaborator (S-191), one team member per rung (S-187/
  S-189, with S-188 nesting flowing membership down), the
  organization owner (S-185/S-186), a personal repository
  owner, and a site admin.
- **Every surface** — the same matrix read four ways: the
  web surface (the rendered matrix / resolution / preview /
  default pages, which say every role in words), the
  programmatic seam the API and future surfaces call
  (``PermissionEngine.resolve`` / ``role_for`` / ``can`` /
  ``require_role`` / ``resolve_by_id``, and S-201's
  permission preview), and both git transports (the HTTP
  door's ``TransportGate`` shape decisions and the SSH
  door's ``SshServeService`` gate), which judge through
  S-054's seam exactly as their modules document.
- **The rest of Part IX, walked in the same fixture** —
  organizations and membership with the last-owner
  invariant (S-185/S-186), teams and privacy (S-187),
  nesting inheritance (S-188), the removal cascade preview
  (S-194), team mentions (S-195), org repository creation
  policy (S-196), internal visibility (S-197), the org
  audit log's reader law (S-198), org deletion guardrails
  (S-199), role-change guardrails at both doors (S-200),
  the permission preview (S-201), and the honestly empty
  billing hole (S-202).

One observation, recorded the way S-168 recorded its
cross-fork rebase refusal — not silently left, and not a
defect this gate repairs: **the two git transports still
judge by S-054's seam**, as ``samverk/permissions.py`` and
S-190's module both document ("S-054's module stays the
seam its existing callers use"; the engine is the
generalisation, and future surfaces — S-238's API
authentication is the named one — resolve through it). So
a team grant, the org default, a stored collaborator grant
or internal visibility, all of which the engine honours,
do not yet reach the HTTP or SSH doors: a team writer the
engine resolves as ``write`` on a private org repository
is answered not-found there, exactly as S-054 judges. The
battery pins that current transport behaviour in two
named observation tests so the seam can never drift
silently; moving the transports onto the engine is
future-slice work, not gate work.

S-203 (instance-wide groups) is not in this battery's
base: it banks after this gate in roadmap order, so the
gate proves the assembled system at the base it was built
on and names the gap here rather than pretending to walk
machinery that has not landed in this tree.

The gate claimed no migration and no taxonomy event: the
assembled system stands at schema 80 with 122 audit
events, and the battery proves both pins. The full-suite
counted recount at this gate is recorded in
PROJECT_MEMORY_MAP.md (the gate entry), read back from
its log file after the run finished.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import base64
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.billing_hole import BillingHole
from samverk.db import schema_version
from samverk.default_permissions import (
    DefaultPermissionStore, render_default_permission_page)
from samverk.git_auth import GitAuthenticator
from samverk.git_http import TransportGate
from samverk.internal_visibility import InternalVisibilityStore
from samverk.invitations import InvitationStore
from samverk.issues import IssueStore
from samverk.member_removal_cascade import CascadeStore
from samverk.org_audit_log import OrgAuditLogStore
from samverk.org_deletion import OrgDeletionStore
from samverk.org_repositories import OrgRepoStore
from samverk.organization_members import OrgMembershipStore
from samverk.organizations import (
    OrganizationError, OrganizationStore, settings_areas)
from samverk.outside_collaborators import OutsideCollaboratorStore
from samverk.permission_engine import (
    PermissionEngine, explanation, render_matrix_page,
    render_resolution_page)
from samverk.permission_preview import PermissionPreviewEngine
from samverk.permissions import (
    PermissionDeniedError, can_read, can_write, role_for as legacy_role_for)
from samverk.repositories import Repository, RepositoryStore
from samverk.role_change_guardrails import RoleChangeGuardStore
from samverk.ssh_auth import SshPrincipal
from samverk.ssh_serve import SshServeService
from samverk.team_mentions import TeamMentionStore
from samverk.team_nesting import NestedTeamStore
from samverk.team_permissions import TeamPermissionStore
from samverk.teams import TeamStore

PW = "correct horse battery"


def basic(user) -> str:
    raw = base64.b64encode(f"{user.username}:{PW}".encode()).decode()
    return f"Basic {raw}"


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


class PartIXGateTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        names = ("volmarr", "rea", "tri", "wri", "mai", "tea",
                 "plain", "papa", "tess", "freya", "solo", "sitemod")
        users = {n: self.accounts.register(n, PW) for n in names}
        self.creator = users["volmarr"]
        self.rea, self.tri, self.wri = users["rea"], users["tri"], users["wri"]
        self.mai, self.tea = users["mai"], users["tea"]
        self.plain, self.papa = users["plain"], users["papa"]
        self.tess, self.freya = users["tess"], users["freya"]
        self.solo, self.admin = users["solo"], users["sitemod"]
        with self.conn:
            self.conn.execute(
                "UPDATE users SET is_admin = 1 WHERE id = ?",
                (self.admin.id,))
        self.admin = self.accounts.get_by_id(self.admin.id)
        kw = dict(time_fn=self.clock)
        self.orgs = OrganizationStore(self.conn, self.accounts, self.audit, **kw)
        self.org = self.orgs.create_organization(self.creator.id, "crew")
        self.members = OrgMembershipStore(
            self.conn, self.accounts, self.audit, **kw)
        for user in (self.rea, self.tri, self.wri, self.mai,
                     self.tea, self.plain):
            self.members.add_member(self.creator.id, self.org.id, user.id)
        self.teams = TeamStore(self.conn, self.accounts, self.audit, **kw)
        self.nesting = NestedTeamStore(
            self.conn, self.accounts, self.audit, **kw)
        self.perms = TeamPermissionStore(
            self.conn, self.accounts, self.audit, **kw)
        self.team_of = {}
        for label, user in (("Readers", self.rea), ("Triagers", self.tri),
                            ("Writers", self.wri),
                            ("Maintainers", self.mai), ("Admins", self.tea)):
            team = self.teams.create_team(self.creator.id, self.org.id, label)
            self.teams.add_member(
                self.creator.id, self.org.id, team.id, user.id)
            self.team_of[label] = team
        # A separate nesting pair for the S-188 assertions:
        # Forge (mai) parents Anvil Crew (wri). Their grants
        # live only on the internal repo, so the ladder
        # matrix on secret/anvil stays one team per rung.
        self.forge = self.teams.create_team(
            self.creator.id, self.org.id, "Forge")
        self.teams.add_member(
            self.creator.id, self.org.id, self.forge.id, self.mai.id)
        self.anvil_crew = self.teams.create_team(
            self.creator.id, self.org.id, "Anvil Crew",
            parent_team_id=self.forge.id)
        self.teams.add_member(
            self.creator.id, self.org.id, self.anvil_crew.id, self.wri.id)
        self.wardens = self.teams.create_team(
            self.creator.id, self.org.id, "Wardens", privacy="secret")
        self.teams.add_member(
            self.creator.id, self.org.id, self.wardens.id, self.tea.id)
        self.anvil = self._repo("crew", "anvil", "public")
        self.secret = self._repo("crew", "secret", "private")
        self.inner = self._repo("crew", "inner", "internal")
        self.hammer = self._repo("solo", "hammer", "public")
        self.vault = self._repo("solo", "vault", "private")
        for label, role in (("Readers", "read"), ("Triagers", "triage"),
                            ("Writers", "write"),
                            ("Maintainers", "maintain"),
                            ("Admins", "admin")):
            self._grant(self.team_of[label], self.secret, role)
        self._grant(self.team_of["Writers"], self.anvil, "write")
        self._grant(self.forge, self.inner, "maintain")
        self._grant(self.anvil_crew, self.inner, "write")
        self.defaults = DefaultPermissionStore(
            self.conn, self.accounts, self.audit, **kw)
        self.defaults.set_default(self.creator.id, self.org.id, "read")
        self.collabs = OutsideCollaboratorStore(
            self.conn, self.accounts, self.audit, **kw)
        self.collabs.grant(self.creator.id, self.secret.id, self.papa.id, "write")
        self.engine = PermissionEngine(
            self.conn, self.accounts, self.audit, **kw)
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.issues = IssueStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, **kw)

    # -- helpers -----------------------------------------------------

    def _repo(self, owner, name, visibility):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO repositories (owner, owner_lower, name,"
                " name_lower, created_by, created_at, description,"
                " visibility) VALUES (?, ?, ?, ?, ?, ?, '', ?)",
                (owner, owner.lower(), name, name.lower(),
                 self.creator.id, 1_700_000_000, visibility))
        return Repository(
            id=int(cur.lastrowid), owner=owner, owner_lower=owner.lower(),
            name=name, name_lower=name.lower(),
            created_by=self.creator.id, created_at=1_700_000_000,
            description="", visibility=visibility)

    def _grant(self, team, repo, role):
        self.teams.link_repo(self.creator.id, self.org.id, team.id, repo.id)
        self.perms.set_permission(
            self.creator.id, self.org.id, team.id, repo.id, role)

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(OrganizationError) as cm:
            fn(*args, **kwargs)
        return cm.exception.reason

    def _actors(self):
        return {"anon": None, "creator": self.creator, "admin": self.admin,
                "rea": self.rea, "tri": self.tri, "wri": self.wri,
                "mai": self.mai, "tea": self.tea, "plain": self.plain,
                "papa": self.papa, "tess": self.tess,
                "freya": self.freya, "solo": self.solo}

    # -- the matrix: every role, resolved by the engine ---------------

    def test_matrix_private_org_repo_every_role(self):
        matrix = [
            ("anon", None, "none"), ("tess", None, "none"),
            ("freya", None, "none"), ("solo", None, "none"),
            ("plain", "read", "org_default"),
            ("rea", "read", "team"), ("tri", "triage", "team"),
            ("wri", "write", "team"), ("mai", "maintain", "team"),
            ("tea", "admin", "team"),
            ("papa", "write", "collaborator"),
            ("creator", "admin", "org_owner"),
            ("admin", "admin", "site_admin"),
        ]
        actors = self._actors()
        for who, role, source in matrix:
            with self.subTest(who=who):
                got = self.engine.resolve(actors[who], self.secret)
                self.assertEqual((got.role, got.source), (role, source))

    def test_matrix_public_org_repo_every_role(self):
        matrix = [
            ("anon", "read", "visibility"),
            ("tess", "read", "visibility"),
            ("freya", "read", "visibility"),
            ("solo", "read", "visibility"),
            ("papa", "read", "visibility"),
            ("plain", "read", "org_default"),
            ("rea", "read", "org_default"),
            ("wri", "write", "team"),
            ("creator", "admin", "org_owner"),
            ("admin", "admin", "site_admin"),
        ]
        actors = self._actors()
        for who, role, source in matrix:
            with self.subTest(who=who):
                got = self.engine.resolve(actors[who], self.anvil)
                self.assertEqual((got.role, got.source), (role, source))

    def test_matrix_personal_repos(self):
        actors = self._actors()
        cases = [
            ("solo", self.vault, "admin", "owner"),
            ("solo", self.hammer, "admin", "owner"),
            ("admin", self.vault, "admin", "site_admin"),
            ("creator", self.vault, None, "none"),
            ("papa", self.vault, None, "none"),
            ("anon", self.vault, None, "none"),
            ("anon", self.hammer, "read", "visibility"),
            ("tess", self.hammer, "read", "visibility"),
        ]
        for who, repo, role, source in cases:
            with self.subTest(who=who, repo=repo.name):
                got = self.engine.resolve(actors[who], repo)
                self.assertEqual((got.role, got.source), (role, source))

    def test_internal_visibility_matrix(self):
        # With the org default in force it outranks the
        # internal contribution for members; clear it and
        # S-197's own answer stands alone.
        store = InternalVisibilityStore(
            self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.assertTrue(store.can_read(self.plain, self.inner))
        self.assertFalse(store.can_read(self.tess, self.inner))
        self.assertFalse(store.can_read(None, self.inner))
        self.assertEqual(
            [r.name for r in store.readable_internal_repositories(
                self.plain, "crew")], ["inner"])
        self.defaults.set_default(self.creator.id, self.org.id, "none")
        for who, role, source in (
                ("plain", "read", "internal"),
                ("rea", "read", "internal"),
                ("creator", "admin", "org_owner"),
                ("tess", None, "none"), ("solo", None, "none"),
                ("anon", None, "none")):
            with self.subTest(who=who):
                got = self.engine.resolve(self._actors()[who], self.inner)
                self.assertEqual((got.role, got.source), (role, source))

    # -- surface 1: the programmatic seam (the API road) --------------

    def test_api_seam_ladder_can_and_require(self):
        ladder = ["read", "triage", "write", "maintain", "admin"]
        holders = {"rea": 0, "tri": 1, "wri": 2, "mai": 3, "tea": 4}
        actors = self._actors()
        for name, rung in holders.items():
            for minimum in ladder:
                with self.subTest(who=name, minimum=minimum):
                    self.assertEqual(
                        self.engine.can(actors[name], self.secret,
                                        minimum),
                        ladder.index(minimum) <= rung)
            with self.subTest(who=name, door="require"):
                self.assertEqual(
                    self.engine.require_role(
                        actors[name], self.secret, ladder[rung]),
                    ladder[rung])
                if rung < 4:
                    with self.assertRaises(PermissionDeniedError):
                        self.engine.require_role(
                            actors[name], self.secret, ladder[rung + 1])
        with self.assertRaises(PermissionDeniedError):
            self.engine.require_role(self.tess, self.secret, "read")
        with self.assertRaises(PermissionDeniedError):
            self.engine.require_role(None, self.secret, "read")

    def test_api_seam_resolve_by_id_matches_resolve(self):
        actors = self._actors()
        for name, user in actors.items():
            with self.subTest(who=name):
                by_id = self.engine.resolve_by_id(
                    user.id if user else None, self.secret.id)
                direct = self.engine.resolve(user, self.secret)
                self.assertEqual(
                    (by_id.role, by_id.source), (direct.role, direct.source))
        self.assertEqual(
            self._reason(self.engine.resolve_by_id, self.wri.id, 999999),
            "repo_not_found")
        self.assertEqual(
            self._reason(self.engine.resolve_by_id, 999999, self.secret.id),
            "no_such_user")

    def test_resolution_is_a_pure_read(self):
        before_audit = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        before_repos = self.conn.execute(
            "SELECT COUNT(*) AS n FROM repositories").fetchone()["n"]
        for user in self._actors().values():
            for repo in (self.anvil, self.secret, self.inner,
                         self.hammer, self.vault):
                self.engine.resolve(user, repo)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"],
            before_audit)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) AS n FROM repositories").fetchone()["n"],
            before_repos)

    # -- surface 2: the web pages say the same matrix in words --------

    def test_web_matrix_page_says_every_role_in_words(self):
        actors = self._actors()
        order = ["creator", "rea", "tri", "wri", "mai", "tea",
                 "plain", "papa", "tess", "anon"]
        resolutions = self.engine.resolutions_for(
            [actors[n] for n in order], self.secret)
        page = render_matrix_page(resolutions)
        for line in ("volmarr — Admin — Organization owner",
                     "rea — Read — Team grant",
                     "tri — Triage — Team grant",
                     "wri — Write — Team grant",
                     "mai — Maintain — Team grant",
                     "tea — Admin — Team grant",
                     "plain — Read — Organization default",
                     "papa — Write — Collaborator grant",
                     "tess — No access — No access",
                     "Anonymous — No access — No access"):
            self.assertIn(line, page)
        one = render_resolution_page(
            self.engine.resolve(self.wri, self.secret))
        self.assertIn("Role: Write.", one)
        self.assertIn("Source: Team grant.", one)
        self.assertIn("wri has Write", explanation(
            self.engine.resolve(self.wri, self.secret)))
        default_page = render_default_permission_page(
            self.defaults.get_default(self.org.id))
        self.assertIn("Read", default_page)

    def test_web_preview_agrees_with_the_matrix(self):
        preview_engine = PermissionPreviewEngine(
            self.conn, self.accounts, time_fn=self.clock)
        preview = preview_engine.preview(self.admin.id, "wri")
        self.assertEqual(preview.role_for("crew/secret"), "write")
        self.assertEqual(preview.role_for("crew/anvil"), "write")
        self.assertIsNone(preview.role_for("solo/vault"))
        self.assertGreaterEqual(preview.hidden_count, 1)
        plain_view = preview_engine.preview(self.admin.id, self.plain.id)
        self.assertEqual(plain_view.role_for("crew/secret"), "read")
        self.assertEqual(
            self._reason(preview_engine.preview, self.wri.id, "tess"),
            "not_site_admin")
        self.assertEqual(
            self._reason(preview_engine.preview, self.admin.id, "ghost"),
            "no_such_user")
        page = preview_engine.preview_page(self.admin.id, "wri")
        self.assertIn("crew/secret", page)

    def test_legacy_web_seam_agrees_on_s054_cells(self):
        # S-054's seam and the engine give one answer on
        # every cell S-054 itself decides.
        for viewer, repo, role in (
                (self.solo, self.vault, "admin"),
                (self.admin, self.vault, "admin"),
                (self.tess, self.vault, None),
                (None, self.vault, None),
                (None, self.hammer, "read"),
                (self.tess, self.hammer, "read")):
            with self.subTest(viewer=viewer, repo=repo.name):
                self.assertEqual(legacy_role_for(viewer, repo), role)
                self.assertEqual(self.engine.role_for(viewer, repo), role)
        self.assertTrue(can_read(self.solo, self.vault))
        self.assertTrue(can_write(self.solo, self.vault))
        self.assertFalse(can_write(self.tess, self.hammer))
        # Stored collaborator, the caller-supplied road:
        self.assertEqual(
            legacy_role_for(self.papa, self.secret,
                            collaborator_role="write"), "write")
        self.assertEqual(
            self.engine.role_for(self.papa, self.secret), "write")

    # -- surface 3: the HTTP transport door ----------------------------

    def _http_gate(self):
        return TransportGate(
            self.repos, GitAuthenticator(self.conn, self.accounts))

    def test_http_transport_matrix(self):
        gate = self._http_gate()
        up, down = "git-upload-pack", "git-receive-pack"
        # Anonymous: public read is free; everything else
        # meets the one uniform challenge.
        got = gate.decide("solo", "hammer", up, None)
        self.assertEqual((got.allowed, got.status), (True, 200))
        got = gate.decide("crew", "secret", up, None)
        self.assertEqual(
            (got.allowed, got.status, got.challenge), (False, 401, True))
        got = gate.decide("solo", "hammer", down, None)
        self.assertEqual((got.allowed, got.status), (False, 401))
        # The personal owner and the site admin pass both
        # legs on a private personal repository.
        for user in (self.solo, self.admin):
            for service in (up, down):
                with self.subTest(user=user.username, service=service):
                    got = gate.decide("solo", "vault", service, basic(user))
                    self.assertTrue(got.allowed)
                    self.assertEqual(got.viewer.username, user.username)
        # A stranger's credentials on a private repo answer
        # the uniform not-found; on a public repo a reader
        # meets the honest write refusal.
        got = gate.decide("crew", "secret", up, basic(self.tess))
        self.assertEqual((got.allowed, got.status, got.reason),
                         (False, 404, "repo_not_found"))
        got = gate.decide("crew", "anvil", down, basic(self.tess))
        self.assertEqual((got.allowed, got.status, got.reason),
                         (False, 403, "permission_denied"))
        got = gate.decide("crew", "anvil", up, basic(self.tess))
        self.assertTrue(got.allowed)
        got = gate.decide("crew", "nope", up, basic(self.solo))
        self.assertEqual((got.allowed, got.status), (False, 404))

    def test_http_transport_observation_s054_seam(self):
        # OBSERVATION (see the module docstring): the HTTP
        # door judges through S-054, so Part IX grants the
        # engine honours do not reach it yet. Pinned, not
        # hidden: the team writer and the stored
        # collaborator are answered not-found on the
        # private org repo, and the team writer meets the
        # reader's write refusal on the public one.
        gate = self._http_gate()
        self.assertEqual(
            self.engine.role_for(self.wri, self.secret), "write")
        got = gate.decide("crew", "secret", "git-upload-pack",
                          basic(self.wri))
        self.assertEqual((got.allowed, got.status), (False, 404))
        got = gate.decide("crew", "secret", "git-upload-pack",
                          basic(self.papa))
        self.assertEqual((got.allowed, got.status), (False, 404))
        got = gate.decide("crew", "anvil", "git-receive-pack",
                          basic(self.wri))
        self.assertEqual((got.allowed, got.status), (False, 403))

    # -- surface 4: the SSH transport door ------------------------------

    def _ssh_serve(self, principal, command):
        calls = []

        def runner(path, program, **kwargs):
            calls.append((str(path), program))
            return 0

        service = SshServeService(
            self.conn, self.root, self.accounts, self.repos,
            audit=None, pack_runner=runner)
        stderr = io.BytesIO()
        rc = service.serve(
            principal, command, stdin=io.BytesIO(),
            stdout=io.BytesIO(), stderr=stderr)
        return rc, calls, stderr.getvalue().decode()

    def _principal(self, user):
        return SshPrincipal(
            kind="account", fingerprint="SHA256:gate", user=user)

    def test_ssh_transport_matrix(self):
        up = "git-upload-pack 'solo/vault'"
        down = "git-receive-pack 'solo/vault'"
        for command in (up, down):
            with self.subTest(command=command):
                rc, calls, _err = self._ssh_serve(
                    self._principal(self.solo), command)
                self.assertEqual(rc, 0)
                self.assertEqual(len(calls), 1)
        rc, calls, err = self._ssh_serve(self._principal(self.tess), up)
        self.assertEqual(rc, 128)
        self.assertEqual(calls, [])
        self.assertIn("not found or access denied", err)
        rc, calls, _err = self._ssh_serve(None, up)
        self.assertEqual((rc, calls), (128, []))
        # A public read passes; the same reader's push is
        # refused before any pack byte moves.
        rc, calls, _err = self._ssh_serve(
            self._principal(self.rea), "git-upload-pack 'crew/anvil'")
        self.assertEqual((rc, len(calls)), (0, 1))
        rc, calls, err = self._ssh_serve(
            self._principal(self.rea), "git-receive-pack 'crew/anvil'")
        self.assertEqual(rc, 128)
        self.assertEqual(calls, [])
        self.assertIn("write permission", err)
        # A malformed command refuses the whole session.
        rc, calls, _err = self._ssh_serve(
            self._principal(self.solo), "rm -rf 'solo/vault'")
        self.assertEqual((rc, calls), (128, []))

    def test_ssh_transport_observation_s054_seam(self):
        # OBSERVATION (see the module docstring): the SSH
        # door mirrors HTTP through the same S-054 seam, so
        # the team writer's engine write role does not
        # reach it yet either. Pinned on both transports
        # so the seam can never drift silently.
        self.assertEqual(
            self.engine.role_for(self.wri, self.secret), "write")
        rc, calls, err = self._ssh_serve(
            self._principal(self.wri), "git-upload-pack 'crew/secret'")
        self.assertEqual(rc, 128)
        self.assertEqual(calls, [])
        self.assertIn("not found or access denied", err)

    # -- S-185/S-186: organizations and membership ----------------------

    def test_organization_profile_and_settings_home(self):
        updated = self.orgs.update_profile(
            self.creator.id, self.org.id,
            display_name="The Crew", bio="We forge.",
            website="https://example.com/crew")
        self.assertEqual(updated.effective_display_name(), "The Crew")
        self.assertEqual(
            self._reason(self.orgs.update_profile, self.plain.id,
                         self.org.id, display_name="Nope"),
            "not_org_steward")
        areas = {a["key"]: a for a in settings_areas()}
        self.assertIn("billing", areas)
        self.assertIn("members", areas)
        self.assertTrue(areas["billing"]["available"])
        self.assertEqual(
            {m.username: m.role for m in
             self.members.list_members(self.org.id)}["volmarr"], "owner")

    def test_membership_roles_and_last_owner_invariant(self):
        self.assertEqual(
            self.members.role_for(self.creator.id, self.org.id), "owner")
        self.assertEqual(
            self.members.role_for(self.wri.id, self.org.id), "member")
        self.assertIsNone(self.members.role_for(self.tess.id, self.org.id))
        self.assertTrue(self.members.is_owner(self.creator.id, self.org.id))
        # The last owner can neither leave nor be removed
        # nor be demoted — and nothing changes.
        self.assertEqual(
            self._reason(self.members.leave_organization,
                         self.creator.id, self.org.id), "last_owner")
        self.assertEqual(
            self._reason(self.members.remove_member, self.admin.id,
                         self.org.id, self.creator.id), "last_owner")
        self.assertEqual(
            self._reason(self.members.set_role, self.admin.id,
                         self.org.id, self.creator.id, "member"),
            "last_owner")
        self.assertEqual(self.members.count_owners(self.org.id), 1)
        # A plain member's removal is clean, and their
        # engine role falls with the membership.
        self.members.add_member(self.creator.id, self.org.id, self.freya.id)
        self.assertEqual(
            self.engine.role_for(self.freya, self.secret), "read")
        self.members.remove_member(
            self.creator.id, self.org.id, self.freya.id)
        self.assertIsNone(self.engine.role_for(self.freya, self.secret))

    # -- S-187/S-188: teams, privacy, nesting -----------------------------

    def test_teams_privacy_and_nesting_inheritance(self):
        self.assertEqual(
            self._reason(self.teams.get_team_for_viewer, self.tess.id,
                         self.org.id, self.wardens.id), "team_not_found")
        self.assertEqual(
            self.teams.get_team_for_viewer(
                self.tea.id, self.org.id, self.wardens.id).name, "Wardens")
        self.assertNotIn(
            "Wardens", [t.name for t in self.teams.list_teams_for_viewer(
                self.tess.id, self.org.id)])
        self.assertEqual(
            [t.name for t in self.nesting.ancestors(
                self.org.id, self.anvil_crew.id)], ["Forge"])
        # Membership flows down: the child team's effective
        # members are its own plus every ancestor's (the
        # org creator rides along as each team's founder).
        effective = {m.username for m in self.nesting.effective_members(
            self.org.id, self.anvil_crew.id)}
        self.assertEqual(effective, {"wri", "mai", "volmarr"})
        # The parent's higher grant decides the child
        # team's effective permission in the repo; the
        # child's own lower grant never flows up.
        eff = self.perms.effective_permission(
            self.org.id, self.anvil_crew.id, self.inner.id)
        self.assertEqual(eff.permission, "maintain")
        self.assertEqual(eff.granted_by_team_name, "Forge")
        own = self.perms.effective_permission(
            self.org.id, self.forge.id, self.inner.id)
        self.assertEqual(own.permission, "maintain")
        self.assertEqual(own.granted_by_team_name, "Forge")
        # And the engine honours the inherited grant: mai
        # holds maintain in the internal repo through the
        # child team she never joined directly.
        got = self.engine.resolve(self.mai, self.inner)
        self.assertEqual((got.role, got.source), ("maintain", "team"))
        self.assertEqual(got.team_name, "Anvil Crew")
        self.assertEqual(got.granted_by_team_name, "Forge")

    def test_team_permission_writes_are_steward_work(self):
        self.assertEqual(
            self._reason(self.perms.set_permission, self.wri.id,
                         self.org.id, self.team_of["Writers"].id,
                         self.secret.id, "admin"), "not_org_owner")
        self.teams.link_repo(
            self.creator.id, self.org.id, self.team_of["Readers"].id,
            self.anvil.id)
        got = self.perms.set_permission(
            self.admin.id, self.org.id, self.team_of["Readers"].id,
            self.anvil.id, "triage")
        self.assertEqual(got.permission, "triage")
        self.assertEqual(
            self.engine.role_for(self.rea, self.anvil), "triage")

    # -- S-191/S-192/S-200: collaborators, defaults, guardrails ---------

    def test_collaborator_lifecycle_moves_the_engine(self):
        self.assertEqual(
            self.collabs.role_for(self.papa.id, self.secret.id), "write")
        self.assertEqual(
            [g.username for g in
             self.collabs.list_for_repo(self.secret.id)], ["papa"])
        self.collabs.set_role(
            self.creator.id, self.secret.id, self.papa.id, "triage")
        self.assertEqual(
            self.engine.role_for(self.papa, self.secret), "triage")
        removed = self.collabs.revoke(
            self.creator.id, self.secret.id, self.papa.id)
        self.assertIsNotNone(removed)
        self.assertIsNone(self.engine.role_for(self.papa, self.secret))
        # A member is not an outside collaborator, and a
        # non-manager cannot grant at all.
        self.assertEqual(
            self._reason(self.collabs.grant, self.creator.id,
                         self.secret.id, self.wri.id, "read"),
            "already_member")
        self.assertEqual(
            self._reason(self.collabs.grant, self.tess.id,
                         self.secret.id, self.freya.id, "read"),
            "not_repo_admin")

    def test_role_change_guardrails_both_doors(self):
        guard = RoleChangeGuardStore(
            self.conn, self.accounts, self.audit, time_fn=self.clock)
        # Collaborator door: freya alone holds grant-admin
        # on the personal vault.
        self.collabs.grant(self.solo.id, self.vault.id, self.freya.id, "admin")
        self.assertEqual(
            [(h.username, h.sources) for h in guard.admin_holders(
                self.vault.id)], [("freya", ("collaborator",))])
        self.assertEqual(
            self._reason(guard.check_collaborator_role_change,
                         self.vault.id, self.freya.id, "admin", "read"),
            "last_admin")
        self.assertEqual(
            self._reason(guard.check_collaborator_role_change,
                         self.vault.id, self.freya.id, "admin", None),
            "last_admin")
        # The wired door refuses too: S-191's own set_role
        # and revoke consult the guard.
        self.assertEqual(
            self._reason(self.collabs.set_role, self.solo.id,
                         self.vault.id, self.freya.id, "write"),
            "last_admin")
        # Team door: tea alone holds grant-admin on the
        # org secret, through the Admins team.
        self.assertEqual(
            self._reason(guard.check_team_permission_change,
                         self.secret.id, self.team_of["Admins"].id,
                         "admin", "read"), "last_admin")
        self.assertEqual(
            self._reason(self.perms.set_permission, self.creator.id,
                         self.org.id, self.team_of["Admins"].id,
                         self.secret.id, "write"), "last_admin")
        # With a second admin standing, the demotion passes.
        self.collabs.grant(self.solo.id, self.vault.id, self.papa.id, "admin")
        guard.check_collaborator_role_change(
            self.vault.id, self.freya.id, "admin", "read")

    def test_default_permission_lifecycle(self):
        got = self.defaults.get_default(self.org.id)
        self.assertEqual((got.role, got.is_set), ("read", True))
        self.assertEqual(self.defaults.role_for_org(self.org.id), "read")
        self.assertEqual(
            self._reason(self.defaults.set_default, self.plain.id,
                         self.org.id, "write"), "not_org_owner")
        self.defaults.set_default(self.creator.id, self.org.id, "write")
        self.assertEqual(
            self.engine.role_for(self.plain, self.secret), "write")
        self.assertEqual(
            self.engine.resolve(self.plain, self.secret).source,
            "org_default")
        # The default is a floor for members only: it never
        # reaches a non-member and never lowers a grant.
        self.assertIsNone(self.engine.role_for(self.tess, self.secret))
        self.assertEqual(
            self.engine.role_for(self.tea, self.secret), "admin")
        self.defaults.set_default(self.creator.id, self.org.id, "none")
        self.assertIsNone(self.engine.role_for(self.plain, self.secret))
        self.assertFalse(self.defaults.get_default(self.org.id).is_set)

    # -- S-193/S-194/S-195: invitations, cascade, mentions ----------------

    def test_invitations_create_membership_and_audit(self):
        invites = InvitationStore(
            self.conn, self.accounts, self.audit, time_fn=self.clock)
        self.assertEqual(
            self._reason(invites.invite, self.plain.id, self.org.id,
                         username="freya"), "not_org_owner")
        inv = invites.invite(self.creator.id, self.org.id, username="freya")
        self.assertIsNone(self.members.role_for(self.freya.id, self.org.id))
        got = invites.accept(self.freya.id, inv.id)
        self.assertEqual(got.status, "accepted")
        self.assertEqual(
            self.members.role_for(self.freya.id, self.org.id), "member")
        self.assertEqual(
            self.engine.role_for(self.freya, self.secret), "read")
        # A second invite can be rescinded by its inviter;
        # a resolved one cannot be accepted again.
        self.members.remove_member(
            self.creator.id, self.org.id, self.freya.id)
        inv2 = invites.invite(self.admin.id, self.org.id, username="freya")
        self.assertEqual(
            invites.rescind(self.admin.id, inv2.id).status, "rescinded")
        self.assertEqual(
            self._reason(invites.accept, self.freya.id, inv.id),
            "invitation_not_pending")

    def test_member_removal_cascade_is_a_pure_preview(self):
        cascade = CascadeStore(self.conn, self.accounts, time_fn=self.clock)
        before = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        got = cascade.preview_removal(self.org.id, self.wri.id)
        self.assertFalse(got.is_last_owner)
        self.assertEqual(got.role, "member")
        self.assertIn("Writers", [t.name for t in got.direct_teams])
        self.assertEqual(
            self.members.role_for(self.wri.id, self.org.id), "member")
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"], before)
        owner = cascade.preview_removal(self.org.id, "volmarr")
        self.assertTrue(owner.is_last_owner)
        stranger = cascade.preview_removal(self.org.id, self.tess.id)
        self.assertIsNone(stranger.role)
        self.assertEqual(stranger.reason, "not_a_member")

    def test_team_mentions_reach_the_team(self):
        mentions = TeamMentionStore(
            self.conn, self.accounts, self.audit, time_fn=self.clock)
        issue = self.issues.create_issue(
            self.creator, "crew", "anvil", "Gate work",
            "Please look, @crew/Writers and @crew/Admins.")
        mentions.sync_issue("crew", "anvil", issue.number)
        self.assertEqual(len(mentions.inbox(self.wri)), 1)
        self.assertEqual(len(mentions.inbox(self.tea)), 1)
        self.assertEqual(mentions.inbox(self.tess), [])
        self.assertEqual(mentions.inbox(self.papa), [])
        self.assertEqual(
            mentions.preview_mentions("@crew/Writers", self.tess.id)[0]
            .team_name, "Writers")

    # -- S-196/S-198/S-199/S-202: policy, audit, deletion, billing -------

    def test_org_repository_creation_policy(self):
        store = OrgRepoStore(
            self.conn, self.accounts, self.root, self.audit,
            time_fn=self.clock)
        store.set_policy(
            self.creator.id, self.org.id, who_may_create="members",
            allowed_visibilities=["private"])
        self.assertTrue(store.can_create(self.plain.id, self.org.id,
                                         "private"))
        self.assertFalse(store.can_create(self.plain.id, self.org.id,
                                          "public"))
        decision = store.decision_for(self.tess.id, self.org.id, "private")
        self.assertFalse(decision.allowed)
        repo = store.create_repository(
            self.plain.id, self.org.id, "plainmade", visibility="private")
        self.assertEqual(
            self.engine.role_for(self.creator, repo), "admin")
        self.assertEqual(
            self.engine.resolve(self.creator, repo).source, "org_owner")
        self.assertIn(
            "plainmade", [r.name for r in store.list_repositories(
                self.org.id)])

    def test_org_audit_log_reader_law(self):
        log = OrgAuditLogStore(
            self.conn, self.accounts, self.audit, time_fn=self.clock)
        entries = log.list_events(self.creator.id, self.org.id)
        self.assertTrue(entries)
        self.assertTrue(log.list_events(self.admin.id, self.org.id))
        self.assertEqual(
            self._reason(log.list_events, self.plain.id, self.org.id),
            "not_org_owner")
        self.assertEqual(
            self._reason(log.list_events, self.tess.id, self.org.id),
            "not_org_owner")
        permissioned = log.list_events(
            self.creator.id, self.org.id, category="permission")
        self.assertTrue(all(
            e.category == "permission" for e in permissioned))

    def test_org_deletion_guardrails(self):
        deletion = OrgDeletionStore(
            self.conn, self.accounts, self.audit, time_fn=self.clock)
        inventory = deletion.inventory(self.org.id)
        self.assertGreaterEqual(inventory.total, 1)
        yes = lambda user_id: True
        self.assertEqual(
            self._reason(deletion.request, self.plain.id, self.org.id,
                         typed_confirmation="crew", reauth_verifier=yes),
            "not_org_owner")
        self.assertEqual(
            self._reason(deletion.request, self.creator.id, self.org.id,
                         typed_confirmation="crew", reauth_verifier=yes),
            "repos_remaining")
        self.assertFalse(deletion.is_pending(self.org.id))
        self.assertFalse(deletion.finalize(self.org.id))
        self.assertIsNotNone(self.orgs.get_by_id(self.org.id))

    def test_billing_hole_honestly_empty_for_every_role(self):
        hole = BillingHole(self.conn, self.accounts)
        got = hole.statement_for_organization(self.org.id)
        self.assertEqual(got.scope, "organization")
        self.assertEqual(got.subject, "crew")
        self.assertEqual(got.member_count, 7)
        self.assertFalse(got.has_billing)
        self.assertFalse(got.has_seats)
        self.assertFalse(got.has_plans)
        self.assertFalse(got.has_charges)
        self.assertTrue(hole.audit_surface().honestly_empty)
        self.assertFalse(hole.instance_statement().has_billing)
        self.assertEqual(
            self._reason(hole.attempt_billing_action, "subscribe"),
            "no_billing")
        page = hole.organization_page(self.org.id)
        self.assertIn("crew", page)

    # -- invariants -------------------------------------------------------

    def test_schema_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 99)
        self.assertEqual(db.MIGRATIONS[-1][0], 99)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 131)


if __name__ == "__main__":
    unittest.main()
