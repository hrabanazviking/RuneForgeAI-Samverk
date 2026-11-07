"""Team repository permissions (S-189).

The role ladder applied per repo per team.

- **The ladder is five rungs, in order.** ``ROLES``
  is ``read`` < ``triage`` < ``write`` < ``maintain``
  < ``admin``: read may look; triage may additionally
  manage issues and pull requests without writing
  code; write may additionally push; maintain may
  additionally manage the repository's settings that
  are not destructive; admin is full control. The
  order is judged purely by ``role_rank`` /
  ``role_covers`` / ``higher_role`` — nothing anywhere
  re-derives it from the words. A role outside the
  ladder is refused ``role_invalid`` by the pure
  ``validate_role``; roles are written as a person
  writes them and judged case-insensitively, trimmed.
- **A permission lives on a link.** S-187's
  ``team_repositories`` linkage is the grant itself:
  migration 72 adds its ``permission`` column, and a
  fresh link starts at the ladder's foot, ``read``
  (``DEFAULT_PERMISSION``) — linking a repository
  never silently grants more. ``set_permission``
  moves a linked team up or down the ladder for one
  repository; moving it is refused ``not_linked``
  when the team is not linked to the repository,
  ``repo_not_found`` when no such repository exists,
  and ``repo_not_in_org`` when the repository belongs
  to another owner. Unlinking (S-187) removes the
  permission with the link. Setting the permission a
  team already holds is a no-op success that writes
  nothing and audits nothing (S-186's same-role law,
  mirrored).
- **Inheritance is S-188's set, judged by the ladder.**
  A team's *effective* permission in a repository is
  the highest direct permission held for that
  repository by the team itself or any ancestor
  (``effective_permission`` / ``effective_permissions``
  over S-188's chain, nearest first): the team's own
  grant wins a tie, a higher ancestor grant lifts the
  team, and nothing ever flows up — a child's grant
  never lifts its parent, and one sibling inherits
  nothing from another. The result names the team
  whose grant decided it (``granted_by_team_id``), so
  the ladder is auditable, never a mystery number.
- **Only stewardship manages.** Setting a permission
  is an organization owner / site admin act (the
  S-186/S-187 guard, mirrored; ``not_org_owner``
  otherwise). Reads are plain reads over stored rows.
- **What this slice is not.** Resolving one *person's*
  role in a repository — ownership, every team they
  sit in (with nesting), collaborator grants and
  visibility in one function — is S-190's engine.
  This slice judges teams only, and says so.
- **Audit:** successful changes ride the existing
  ``auth.organization.update`` event (no new
  taxonomy event — 122 events stand) with detail
  ``{"fields": "teams", "action": "set_permission",
  ...}``; refusals and no-op sets write nothing and
  audit nothing.
- **Storage** is migration 72's ``permission``
  column on S-187's ``team_repositories`` table
  (schema 71 to 72). Teams, members, links and the
  parent tree stay S-187/S-188 ground and are only
  read (and, for the one column, written) here.
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .organization_members import OrgMembershipStore
from .organizations import Organization, OrganizationError
from .team_nesting import ancestor_ids
from .teams import Team, TeamStore

__all__ = [
    "DEFAULT_PERMISSION", "ROLES", "ROLE_RANK",
    "EffectiveTeamPermission", "TeamPermission",
    "TeamPermissionStore", "higher_role", "render_team_permissions_page",
    "role_covers", "role_rank", "role_word", "validate_role",
]

ROLES = ("read", "triage", "write", "maintain", "admin")
ROLE_RANK = {role: rank for rank, role in enumerate(ROLES, start=1)}
DEFAULT_PERMISSION = "read"

_ROLE_WORDS = {
    "read": "Read",
    "triage": "Triage",
    "write": "Write",
    "maintain": "Maintain",
    "admin": "Admin",
}


def validate_role(role: object) -> str:
    """Return the canonical ladder role or refuse
    plainly: the role must be one of ROLES, written
    as text, judged trimmed and case-insensitively."""
    if isinstance(role, str) and role.strip().lower() in ROLE_RANK:
        return role.strip().lower()
    raise OrganizationError(
        "role_invalid",
        "A team repository permission is one of: "
        "read, triage, write, maintain, admin.")


def role_rank(role: str) -> int:
    """The rung a role stands on (1..5), judged over
    the validated ladder."""
    return ROLE_RANK[validate_role(role)]


def role_word(role: str) -> str:
    """The role said in a word a person reads."""
    return _ROLE_WORDS.get(validate_role(role), role)


def higher_role(first: str | None, second: str | None) -> str | None:
    """The higher of two roles; None yields to the
    other, and two Nones stay None."""
    if first is None:
        return second
    if second is None:
        return first
    return first if ROLE_RANK[first] >= ROLE_RANK[second] else second


def role_covers(role: str | None, minimum: str) -> bool:
    """Pure rank check: does ``role`` stand at or
    above ``minimum`` on the ladder? No role covers
    nothing."""
    if role is None:
        return False
    return ROLE_RANK[validate_role(role)] >= ROLE_RANK[validate_role(minimum)]


@dataclass(frozen=True)
class TeamPermission:
    """One team's direct permission in one repository:
    the S-187 link, with its ladder role."""
    team_id: int
    repo_id: int
    owner: str
    name: str
    permission: str


@dataclass(frozen=True)
class EffectiveTeamPermission:
    """One team's effective permission in one
    repository: the highest direct grant in its
    ancestor chain (itself first), and the team whose
    grant decided it."""
    team_id: int
    repo_id: int
    owner: str
    name: str
    permission: str
    granted_by_team_id: int
    granted_by_team_name: str


class TeamPermissionStore:
    def __init__(
        self, conn: sqlite3.Connection, accounts: AccountStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._audit = audit
        self._now = time_fn
        self._org_members = OrgMembershipStore(
            conn, accounts, audit=None, time_fn=time_fn)
        self._teams = TeamStore(conn, accounts, audit=None,
                                time_fn=time_fn)

    # -- guards (S-187's, mirrored) ----------------------
    def _require_org_row(self, org_id: int) -> sqlite3.Row:
        row = self._conn.execute(
            "SELECT * FROM organizations WHERE id = ?",
            (org_id,)).fetchone()
        if row is None:
            raise OrganizationError(
                "org_not_found", "No such organization.")
        return row

    def _require_owner_or_admin(self, actor_id: int,
                                org_row: sqlite3.Row) -> User:
        actor = self._accounts.get_by_id(actor_id)
        if actor is None:
            raise OrganizationError(
                "no_such_user", "No such account.")
        if actor.is_admin:
            return actor
        if self._org_members.role_for(actor.id, org_row["id"]) != "owner":
            raise OrganizationError(
                "not_org_owner",
                "Only an organization owner or a site admin "
                "can manage this organization's teams.")
        return actor

    def _require_repo_row(self, org_row: sqlite3.Row,
                          repo_id: int) -> sqlite3.Row:
        repo = self._conn.execute(
            "SELECT * FROM repositories WHERE id = ?",
            (repo_id,)).fetchone()
        if repo is None:
            raise OrganizationError(
                "repo_not_found", "No such repository.")
        if repo["owner_lower"] != org_row["name_lower"]:
            raise OrganizationError(
                "repo_not_in_org",
                "Team permissions only apply to repositories "
                "that belong to the team's organization.")
        return repo

    def _link_row(self, team_id: int, repo_id: int):
        return self._conn.execute(
            "SELECT l.team_id AS team_id, l.repo_id AS repo_id,"
            " l.permission AS permission,"
            " r.owner AS owner, r.name AS name"
            " FROM team_repositories l"
            " JOIN repositories r ON r.id = l.repo_id"
            " WHERE l.team_id = ? AND l.repo_id = ?",
            (team_id, repo_id)).fetchone()

    @staticmethod
    def _to_permission(row) -> TeamPermission:
        return TeamPermission(
            team_id=row["team_id"], repo_id=row["repo_id"],
            owner=row["owner"], name=row["name"],
            permission=row["permission"] or DEFAULT_PERMISSION)

    def _audit_change(self, actor: User, org_row: sqlite3.Row,
                      team: Team, repo: sqlite3.Row, role: str,
                      source_ip: str | None = None):
        if self._audit is None:
            return
        self._audit.append(
            actor_kind="user", actor_id=actor.id,
            action="auth.organization.update",
            target_kind="organization",
            target_id=org_row["name_lower"],
            outcome="success", source_ip=source_ip,
            detail={"fields": "teams", "action": "set_permission",
                    "team": team.name_lower,
                    "repo": f"{repo['owner_lower']}/{repo['name_lower']}",
                    "permission": role})

    # -- direct permissions --------------------------------
    def permission_for(self, org_id: int, team_id: int,
                       repo_id: int) -> str | None:
        """The team's direct ladder role in the
        repository, or None when the team is not
        linked to it."""
        self._teams.get_team(org_id, team_id)
        row = self._link_row(team_id, repo_id)
        if row is None:
            return None
        return row["permission"] or DEFAULT_PERMISSION

    def get_permission(self, org_id: int, team_id: int,
                       repo_id: int) -> TeamPermission | None:
        self._teams.get_team(org_id, team_id)
        row = self._link_row(team_id, repo_id)
        return self._to_permission(row) if row else None

    def list_permissions(self, org_id: int,
                         team_id: int) -> list[TeamPermission]:
        """Every direct grant the team holds, ordered
        by repository name."""
        self._teams.get_team(org_id, team_id)
        rows = self._conn.execute(
            "SELECT l.team_id AS team_id, l.repo_id AS repo_id,"
            " l.permission AS permission,"
            " r.owner AS owner, r.name AS name"
            " FROM team_repositories l"
            " JOIN repositories r ON r.id = l.repo_id"
            " WHERE l.team_id = ? ORDER BY r.name_lower",
            (team_id,)).fetchall()
        return [self._to_permission(r) for r in rows]

    def permissions_for_repo(self, org_id: int,
                             repo_id: int) -> list[TeamPermission]:
        """Every team's direct grant in one repository
        of the organization — the auditable list —
        ordered by team name."""
        org_row = self._require_org_row(org_id)
        self._require_repo_row(org_row, repo_id)
        rows = self._conn.execute(
            "SELECT l.team_id AS team_id, l.repo_id AS repo_id,"
            " l.permission AS permission,"
            " r.owner AS owner, r.name AS name"
            " FROM team_repositories l"
            " JOIN repositories r ON r.id = l.repo_id"
            " JOIN teams t ON t.id = l.team_id"
            " WHERE l.repo_id = ? AND t.org_id = ?"
            " ORDER BY t.name_lower",
            (repo_id, org_id)).fetchall()
        return [self._to_permission(r) for r in rows]

    def set_permission(
        self, actor_id: int, org_id: int, team_id: int,
        repo_id: int, role: object,
        source_ip: str | None = None,
    ) -> TeamPermission:
        """Set a linked team's ladder role in one
        repository. Owner/admin only; the role is
        validated, the repository must belong to the
        organization, and the team must already be
        linked to it (S-187 links, this slice grades).
        Setting the role already held is a no-op
        success: nothing is written, nothing audited."""
        org_row = self._require_org_row(org_id)
        actor = self._require_owner_or_admin(actor_id, org_row)
        team = self._teams.get_team(org_id, team_id)
        repo = self._require_repo_row(org_row, repo_id)
        clean_role = validate_role(role)
        row = self._link_row(team.id, repo_id)
        if row is None:
            raise OrganizationError(
                "not_linked",
                "That repository is not linked to this team: "
                "link it first, then set its permission.")
        current = row["permission"] or DEFAULT_PERMISSION
        if current == clean_role:
            return self._to_permission(row)
        with self._conn:
            self._conn.execute(
                "UPDATE team_repositories SET permission = ?"
                " WHERE team_id = ? AND repo_id = ?",
                (clean_role, team.id, repo_id))
        self._audit_change(actor, org_row, team, repo, clean_role,
                           source_ip=source_ip)
        result = self.get_permission(org_id, team.id, repo_id)
        assert result is not None
        return result

    # -- effective permissions (S-188's chain, judged) -----
    def _chain(self, org_id: int, team_id: int) -> list[Team]:
        teams = self._teams.list_teams(org_id)
        by_id = {t.id: t for t in teams}
        parent_of = {t.id: t.parent_team_id for t in teams}
        ids = [team_id] + ancestor_ids(parent_of, team_id)
        return [by_id[i] for i in ids if i in by_id]

    def effective_permission(self, org_id: int, team_id: int,
                             repo_id: int) -> EffectiveTeamPermission | None:
        """The team's effective role in the repository:
        the highest direct grant in its ancestor chain,
        its own grant winning a tie; None when no team
        in the chain is linked to the repository."""
        self._teams.get_team(org_id, team_id)
        best: EffectiveTeamPermission | None = None
        for holder in self._chain(org_id, team_id):
            row = self._link_row(holder.id, repo_id)
            if row is None:
                continue
            role = row["permission"] or DEFAULT_PERMISSION
            if best is None or ROLE_RANK[role] > ROLE_RANK[best.permission]:
                best = EffectiveTeamPermission(
                    team_id=team_id, repo_id=repo_id,
                    owner=row["owner"], name=row["name"],
                    permission=role,
                    granted_by_team_id=holder.id,
                    granted_by_team_name=holder.name)
        return best

    def effective_permissions(self, org_id: int,
                              team_id: int) -> list[EffectiveTeamPermission]:
        """Every repository the team effectively holds
        a grant in — its own links plus every ancestor's,
        each repository named once with its effective
        role — ordered by repository name."""
        self._teams.get_team(org_id, team_id)
        found: dict[int, EffectiveTeamPermission] = {}
        for holder in self._chain(org_id, team_id):
            for perm in self.list_permissions(org_id, holder.id):
                current = found.get(perm.repo_id)
                if current is None or (
                        ROLE_RANK[perm.permission]
                        > ROLE_RANK[current.permission]):
                    found[perm.repo_id] = EffectiveTeamPermission(
                        team_id=team_id, repo_id=perm.repo_id,
                        owner=perm.owner, name=perm.name,
                        permission=perm.permission,
                        granted_by_team_id=holder.id,
                        granted_by_team_name=holder.name)
        return [found[key] for key in sorted(
            found, key=lambda rid: found[rid].name.lower())]


def render_team_permissions_page(
    org: Organization, team: Team,
    direct: list[TeamPermission],
    effective: list[EffectiveTeamPermission],
) -> str:
    """The team's repository permissions page: the
    ladder said in plain words, then each direct grant
    and each effective grant with the team whose grant
    decided it — every value escaped through S-010."""
    ladder = " / ".join(role_word(r) for r in ROLES)
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Repository permissions — "
        f"{escape_html_text(team.name)} — "
        f"{escape_html_text(org.name)} — Samverk</title></head>",
        "<body>",
        f"<h1>Repository permissions — "
        f"{escape_html_text(team.name)}</h1>",
        f'<p class="org-name">A team in '
        f"{escape_html_text(org.effective_display_name())}</p>",
        f"<p>The permission ladder (S-189) is: "
        f"{escape_html_text(ladder)}. Read may look; triage "
        "may manage issues and pull requests without writing "
        "code; write may push; maintain may manage "
        "non-destructive repository settings; admin is full "
        "control. A higher rung includes every rung below it.</p>",
        "<h2>Direct permissions</h2>",
    ]
    if direct:
        parts.append("<ul>")
        for perm in direct:
            label = escape_html_text(f"{perm.owner}/{perm.name}")
            parts.append(
                f"<li>{label} — "
                f"{escape_html_text(role_word(perm.permission))}</li>")
        parts.append("</ul>")
    else:
        parts.append(
            "<p>This team is not linked to any repository yet, "
            "so it holds no direct permission.</p>")
    parts.append("<h2>Effective permissions</h2>")
    parts.append(
        "<p>Effective permission is the highest grant held by "
        "this team or any ancestor above it; inheritance flows "
        "down, never up.</p>")
    if effective:
        parts.append("<ul>")
        for perm in effective:
            label = escape_html_text(f"{perm.owner}/{perm.name}")
            holder = escape_html_text(perm.granted_by_team_name)
            parts.append(
                f"<li>{label} — "
                f"{escape_html_text(role_word(perm.permission))} "
                f"(granted by {holder})</li>")
        parts.append("</ul>")
    else:
        parts.append(
            "<p>No effective permissions: neither this team nor "
            "any ancestor is linked to a repository.</p>")
    parts.append(
        "<p>Resolving one person's role in a repository — "
        "ownership, teams, collaborator grants and visibility "
        "in one answer — is the S-190 permission engine; this "
        "page judges teams only.</p>")
    parts.append("</body></html>")
    return "\n".join(parts)
