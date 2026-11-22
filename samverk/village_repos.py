"""Village repositories (S-365).

A Samtal hall may own repositories. The hall stands in
Samverk as an organization (S-185): the hall's repos are
the org's repos, hall membership is org membership
(owner / member, S-186), and what a hall member may do in
a hall repo is decided by one owner-defined mapping from
hall role to repo role, resolved through the S-190
permission engine — never by a second permission law.

The mapping is the hall owner's word, and it is shown
before it is saved: preview_mapping renders the exact
effect in plain words and returns a token over the
canonical mapping; save_mapping refuses any mapping
whose token does not match a preview of that same
mapping (mapping_not_previewed). Saving applies the
mapping through the standing team machinery: two hall
teams (members and owners) are linked to the repo and
graded through TeamPermissionStore (S-189), and hall
membership is synced into those teams, so S-190's
resolve() answers for hall members with the mapped role
and names the hall team as its source.

Guards: the seam must be enabled (seam_disabled); only
a hall owner may preview-save or sync (not_hall_owner);
unknown hall roles, repo roles, halls, and repos are
refused with named reasons. No migration and no new
taxonomy event: the mapping rides the settings table,
as S-354's per-user quotas do.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .accounts import AccountStore, User
from .escaping import escape_html_text
from .organization_members import OrgMembershipStore
from .organizations import Organization, OrganizationStore
from .permission_engine import PermissionEngine
from .repositories import Repository
from .seam_contract import seam_enabled
from .team_permissions import ROLES as REPO_ROLES
from .team_permissions import TeamPermissionStore
from .teams import TeamStore

HALL_ROLES = ("owner", "member")
NO_ROLE = "none"
_VALID_REPO = set(REPO_ROLES) | {NO_ROLE}


class VillageRepoError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class MappingPreview:
    hall: str
    repo: str
    lines: tuple[str, ...]
    token: str

    def text(self) -> str:
        return "\n".join(self.lines)


def _canonical(mapping: object) -> dict[str, str]:
    if not isinstance(mapping, dict) or not mapping:
        raise VillageRepoError(
            "mapping_required",
            "A hall mapping names a repo role for each hall role.")
    clean: dict[str, str] = {}
    for hall_role, repo_role in mapping.items():
        if hall_role not in HALL_ROLES:
            raise VillageRepoError(
                "unknown_hall_role",
                f"Unknown hall role: {hall_role!r}. Hall roles are owner and member.")
        if not isinstance(repo_role, str) or repo_role not in _VALID_REPO:
            raise VillageRepoError(
                "unknown_repo_role",
                f"Unknown repo role: {repo_role!r}. Repo roles are "
                + ", ".join(REPO_ROLES) + ", or none.")
        clean[hall_role] = repo_role
    for role in HALL_ROLES:
        clean.setdefault(role, NO_ROLE)
    return clean


def _token(hall_lower: str, repo_lower: str, clean: dict[str, str]) -> str:
    blob = json.dumps([hall_lower, repo_lower, clean], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


class VillageRepoService:
    def __init__(self, conn, accounts: AccountStore,
                 *, settings: dict | None = None, audit=None,
                 time_fn=None):
        self._conn = conn
        self._accounts = accounts
        self._settings = settings
        self._orgs = OrganizationStore(conn, accounts, audit=audit, time_fn=time_fn)
        self._members = OrgMembershipStore(conn, accounts, audit=audit, time_fn=time_fn)
        self._teams = TeamStore(conn, accounts, audit=audit, time_fn=time_fn)
        self._perms = TeamPermissionStore(conn, accounts, audit=audit, time_fn=time_fn)
        self._engine = PermissionEngine(conn, accounts, audit=audit, time_fn=time_fn)

    def _require_seam(self) -> None:
        if not seam_enabled(self._settings):
            raise VillageRepoError(
                "seam_disabled", "The Samtal seam is not enabled.")

    def _require_hall(self, hall: object) -> Organization:
        org = self._orgs.get_by_name(hall) if isinstance(hall, str) else None
        if org is None:
            raise VillageRepoError("no_such_hall", "No such Samtal hall.")
        return org

    def _require_owner(self, actor: User | None, org: Organization) -> None:
        if actor is None:
            raise VillageRepoError("not_hall_owner", "Only a hall owner may do this.")
        m = self._members.get_membership(actor.id, org.id)
        if m is None or m.role != "owner":
            raise VillageRepoError(
                "not_hall_owner",
                "Only a hall owner may define the hall's repo mapping.")

    def _require_repo(self, org: Organization, repo_name: object) -> Repository:
        if not isinstance(repo_name, str) or not repo_name.strip():
            raise VillageRepoError("no_such_repo", "No such repository.")
        row = self._conn.execute(
            "SELECT * FROM repositories WHERE owner_lower = ? AND name_lower = ?",
            (org.name_lower, repo_name.strip().lower())).fetchone()
        if row is None:
            raise VillageRepoError(
                "no_such_repo", "That repository does not belong to this hall.")
        keys = row.keys()
        return Repository(
            id=row["id"], owner=row["owner"], owner_lower=row["owner_lower"],
            name=row["name"], name_lower=row["name_lower"],
            created_by=row["created_by"], created_at=row["created_at"],
            description=row["description"] if "description" in keys else "",
            visibility=row["visibility"] if "visibility" in keys else "private",
            default_branch=row["default_branch"] if "default_branch" in keys else "main",
            fork_of_id=row["fork_of_id"] if "fork_of_id" in keys else None,
            is_template=bool(row["is_template"]) if "is_template" in keys else False,
            template_of_id=row["template_of_id"] if "template_of_id" in keys else None)

    # -- the mapping, shown before saving ----------------------
    def preview_mapping(self, actor: User | None, hall: object,
                        repo_name: object, mapping: object) -> MappingPreview:
        """Render the mapping's exact effect, before any save."""
        self._require_seam()
        org = self._require_hall(hall)
        self._require_owner(actor, org)
        repo = self._require_repo(org, repo_name)
        clean = _canonical(mapping)
        lines = [f"Hall {org.name} — repository {repo.owner}/{repo.name}:"]
        for hall_role in HALL_ROLES:
            role = clean[hall_role]
            if role == NO_ROLE:
                lines.append(f"  Hall {hall_role}s get no role in this repository.")
            else:
                lines.append(f"  Hall {hall_role}s get the {role} role in this repository.")
        lines.append("Saving applies exactly this, through the S-190 permission engine.")
        return MappingPreview(
            hall=org.name, repo=repo.full_name, lines=tuple(lines),
            token=_token(org.name_lower, repo.name_lower, clean))

    def save_mapping(self, actor: User | None, hall: object, repo_name: object,
                     mapping: object, preview_token: object) -> MappingPreview:
        """Save a mapping already shown: token must match its preview."""
        preview = self.preview_mapping(actor, hall, repo_name, mapping)
        if preview_token != preview.token:
            raise VillageRepoError(
                "mapping_not_previewed",
                "This mapping was not shown before saving; preview it first.")
        org = self._require_hall(hall)
        repo = self._require_repo(org, repo_name)
        clean = _canonical(mapping)
        member_team = self._hall_team(actor, org, "members")
        owner_team = self._hall_team(actor, org, "owners")
        self._apply(actor, org, member_team, repo, clean["member"])
        self._apply(actor, org, owner_team, repo, clean["owner"])
        self._sync_teams(actor, org, member_team, owner_team)
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (f"seam.hall.{org.id}.repo.{repo.id}.mapping",
                 json.dumps(clean, sort_keys=True)))
        return preview

    def saved_mapping(self, hall: object, repo_name: object) -> dict[str, str] | None:
        org = self._require_hall(hall)
        repo = self._require_repo(org, repo_name)
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (f"seam.hall.{org.id}.repo.{repo.id}.mapping",)).fetchone()
        return json.loads(row["value"]) if row else None

    # -- team machinery ----------------------------------------
    def _hall_team(self, actor: User, org: Organization, kind: str):
        name = f"hall-{org.name_lower}-{kind}"
        for team in self._teams.list_teams(org.id):
            if team.name_lower == name:
                return team
        return self._teams.create_team(actor.id, org.id, name)

    def _apply(self, actor: User, org: Organization, team, repo: Repository,
               role: str) -> None:
        if role == NO_ROLE:
            # Linking alone would grant the S-189 default
            # (read); a mapped none means no link at all.
            try:
                self._teams.unlink_repo(actor.id, org.id, team.id, repo.id)
            except Exception:
                pass  # not linked; none already in effect
            return
        try:
            self._teams.link_repo(actor.id, org.id, team.id, repo.id)
        except Exception:
            pass  # already linked; grading below is the act
        self._perms.set_permission(actor.id, org.id, team.id, repo.id, role)

    def _sync_teams(self, actor: User, org: Organization, member_team, owner_team) -> None:
        members = self._members.list_members(org.id)
        want = {"member": set(), "owner": set()}
        for m in members:
            want[m.role].add(m.user_id)
        for team, role in ((member_team, "member"), (owner_team, "owner")):
            current = {m.user_id for m in self._teams.list_members(org.id, team.id)}
            for uid in want[role] - current:
                self._teams.add_member(actor.id, org.id, team.id, uid)
            for uid in current - want[role]:
                try:
                    self._teams.remove_member(actor.id, org.id, team.id, uid)
                except Exception:
                    pass

    def sync_hall(self, actor: User | None, hall: object) -> None:
        """Re-sync hall membership into the hall teams."""
        self._require_seam()
        org = self._require_hall(hall)
        self._require_owner(actor, org)
        self._sync_teams(actor, org,
                         self._hall_team(actor, org, "members"),
                         self._hall_team(actor, org, "owners"))

    # -- resolution through S-190 -------------------------------
    def role_for(self, viewer: User | None, hall: object, repo_name: object) -> str | None:
        """A hall member's role in a hall repo, via S-190 only."""
        self._require_seam()
        org = self._require_hall(hall)
        repo = self._require_repo(org, repo_name)
        return self._engine.resolve(viewer, repo).role


def render_mapping_preview(preview: MappingPreview) -> str:
    lines = ['<section class="hall-mapping">', "<h2>Hall repository mapping</h2>"]
    for line in preview.lines:
        lines.append(f"<p>{escape_html_text(line)}</p>")
    lines.append(f'<p class="token">Preview token: {escape_html_text(preview.token)}</p>')
    lines.append("</section>")
    return "\n".join(lines) + "\n"
