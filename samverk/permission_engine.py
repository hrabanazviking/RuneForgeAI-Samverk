"""Permission resolution engine (S-190).

One function: user x repo -> role. ``PermissionEngine.resolve``
is that function (``role_for`` is its thin wrapper), and every
future surface that needs a person's role in a repository —
S-197's internal visibility, S-238's API authentication,
S-365's village repositories — resolves through this seam,
never through a second place where the law could differ.

- **The ladder is S-189's, imported, never re-derived.**
  Five rungs in order: ``read`` < ``triage`` < ``write``
  < ``maintain`` < ``admin``, judged only by the rank
  helpers in ``samverk/team_permissions.py``. A role
  outside the ladder is refused ``role_invalid`` by the
  shared ``validate_role`` — loudly, never silently
  ignored.
- **The answer is the highest contribution, and it
  names its source.** Every fact that could grant a
  role is gathered as a *contribution* — a role, a
  source, and the reason said in plain words — and the
  pure ``decide_permission`` picks the winner: the
  highest rung wins; on a tie of rungs the more
  specific source wins, in the order owner, site
  admin, organization owner, team, collaborator,
  visibility. The returned ``Resolution`` carries the
  winning role *and* source *and* reason, so an answer
  is always explainable, never a mystery number.
- **Ownership.** The repository's owner holds ``admin``
  (source ``owner``). An instance site admin holds
  ``admin`` (source ``site_admin``; S-054's law —
  hiding repositories from instance administration
  would be theatre, not security). When the
  repository's owner is an organization (the shared
  S-185 namespace means an owner name is a person or
  an organization, never both), the organization's
  owners hold ``admin`` (source ``org_owner``).
- **Teams, with nesting both ways S-188 defined it.**
  A person acts through every team they are an
  *effective* member of — a direct member, or a member
  of any ancestor, because S-188's membership flows
  down into child teams. Each such team contributes
  its S-189 *effective* permission in the repository
  — its own direct grant or the highest grant in its
  ancestor chain, the granting team named. A sibling
  team's grant contributes nothing, a child's grant
  never lifts a parent team's members beyond what
  that parent team itself effectively holds, and
  inheritance never flows up.
- **Collaborator grants are caller-supplied until
  S-191.** No collaborator store exists yet (S-191
  builds it), so — exactly as S-054's ``role_for`` —
  the caller who holds a grant passes its role in.
  A valid grant contributes on any visibility,
  including private repositories; an invalid one is
  refused ``role_invalid``. A grant belongs to a
  person: an anonymous visitor holds none, exactly
  as S-054 judged. When S-191 lands its
  store, the grant will be read there instead and
  the answers for stored grants will not change.
- **Visibility is a floor, never a grant of more.**
  A public repository contributes ``read`` to
  everyone, including anonymous visitors (source
  ``visibility``). A private repository contributes
  nothing: a person with no other grant has role
  ``None``, which surfaces must render as *not
  found*, not *forbidden* — a private repository's
  existence is itself private (S-054's law).
- **Organization membership alone grants nothing
  yet.** Being a plain member of the owning
  organization contributes no role in this slice;
  the org-wide default repository permission is
  S-192, and until it lands a member's role comes
  only from the sources above. Internal visibility
  is S-197: it will add its contribution here, in
  this one function, when it lands.
- **S-054's answers are preserved.** For every case
  S-054 decided — personal ownership, site admin,
  a collaborator grant (its read / write / admin
  rungs are a subset of this ladder), public and
  private visibility — this engine returns the same
  role ``samverk/permissions.py`` returns; the
  battery proves the equality cell by cell. S-054's
  module stays the seam its existing callers use;
  this engine is the generalisation it promised.
- **Resolution is a pure read.** It writes nothing
  and audits nothing, claims no migration (schema
  stays 72) and no taxonomy event (122 stand).
  Storage stays where the earlier slices put it:
  repositories (S-049/S-050), organizations
  (S-185), memberships (S-186), teams and links
  (S-187), the parent tree (S-188), and the ladder
  on the link (S-189) are only read here.
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
from .organizations import OrganizationError, OrganizationStore
from .permissions import PermissionDeniedError
from .repositories import Repository
from .team_nesting import NestedTeamStore
from .team_permissions import (
    ROLE_RANK, ROLES, TeamPermissionStore, role_covers,
    role_word, validate_role)
from .teams import TeamStore

__all__ = [
    "ROLES", "SOURCE_PRIORITY", "Contribution",
    "PermissionDecision", "PermissionEngine", "Resolution",
    "build_contributions", "decide_permission", "explanation",
    "render_matrix_page", "render_resolution_page",
    "source_word",
]

# Tie-break order between sources that grant the same
# rung: the more specific relationship to this
# repository wins the naming. The number never grants
# anything by itself — it only chooses which true
# reason is reported when two reasons tie.
SOURCE_PRIORITY = {
    "owner": 60,
    "site_admin": 50,
    "org_owner": 40,
    "team": 30,
    "collaborator": 20,
    "visibility": 10,
    "none": 0,
}

_SOURCE_WORDS = {
    "owner": "Repository owner",
    "site_admin": "Site admin",
    "org_owner": "Organization owner",
    "team": "Team grant",
    "collaborator": "Collaborator grant",
    "visibility": "Public repository",
    "none": "No access",
}


def source_word(source: str) -> str:
    """The source of a role, said in words a person
    reads — never a colour or an icon alone."""
    return _SOURCE_WORDS.get(source, source)


@dataclass(frozen=True)
class Contribution:
    """One fact that grants a role: the role, the
    source that grants it, and the reason in plain
    words. Team contributions also name the team the
    person acts through and the team whose grant
    decided that team's effective permission."""
    role: str
    source: str
    detail: str
    team_name: str | None = None
    granted_by_team_name: str | None = None


@dataclass(frozen=True)
class PermissionDecision:
    """The pure outcome: the winning role (or None),
    its source, and its reason in plain words."""
    role: str | None
    source: str
    detail: str
    team_name: str | None = None
    granted_by_team_name: str | None = None


def build_contributions(
    *,
    is_owner: bool = False,
    is_site_admin: bool = False,
    org_role: str | None = None,
    team_grants: tuple[tuple[str, str, str], ...] = (),
    collaborator_role: str | None = None,
    visibility: str = "private",
) -> list[Contribution]:
    """Every contribution the stated facts make, in
    plain order. Pure: no storage is read here, and a
    collaborator or team role outside the ladder is
    refused ``role_invalid`` by the shared validator.
    ``team_grants`` entries are (team the person acts
    through, team whose grant decided it, role)."""
    found: list[Contribution] = []
    if is_owner:
        found.append(Contribution(
            role="admin", source="owner",
            detail="they own the repository"))
    if is_site_admin:
        found.append(Contribution(
            role="admin", source="site_admin",
            detail="site admins hold admin on every "
                   "repository"))
    if org_role == "owner":
        found.append(Contribution(
            role="admin", source="org_owner",
            detail="they own the organization that "
                   "owns the repository"))
    for team_name, granted_by, role in team_grants:
        clean = validate_role(role)
        if granted_by == team_name:
            detail = f"the {team_name} team grants it"
        else:
            detail = (f"the {team_name} team holds it "
                      f"by the {granted_by} team's grant")
        found.append(Contribution(
            role=clean, source="team", detail=detail,
            team_name=team_name,
            granted_by_team_name=granted_by))
    if collaborator_role is not None:
        found.append(Contribution(
            role=validate_role(collaborator_role),
            source="collaborator",
            detail="a collaborator grant on this "
                   "repository"))
    if visibility == "public":
        found.append(Contribution(
            role="read", source="visibility",
            detail="the repository is public, and "
                   "public repositories are readable "
                   "by everyone"))
    return found


def decide_permission(
    contributions: list[Contribution],
) -> PermissionDecision:
    """The one judgement: the highest rung wins, and
    a tie of rungs is named by the more specific
    source. No contributions means no role — source
    ``none``."""
    best: Contribution | None = None
    best_key: tuple[int, int] | None = None
    for item in contributions:
        clean = validate_role(item.role)
        key = (ROLE_RANK[clean],
               SOURCE_PRIORITY.get(item.source, 0))
        if best_key is None or key > best_key:
            best_key = key
            best = Contribution(
                role=clean, source=item.source,
                detail=item.detail,
                team_name=item.team_name,
                granted_by_team_name=item.granted_by_team_name)
    if best is None:
        return PermissionDecision(
            role=None, source="none",
            detail="no grant applies")
    return PermissionDecision(
        role=best.role, source=best.source,
        detail=best.detail, team_name=best.team_name,
        granted_by_team_name=best.granted_by_team_name)


@dataclass(frozen=True)
class Resolution:
    """One person's resolved role in one repository:
    the role (or None for no access), the source that
    granted it, and the reason in plain words. A team
    answer also names the team the person acts through
    and the team whose grant decided it."""
    user_id: int | None
    username: str | None
    repo_id: int
    owner: str
    name: str
    visibility: str
    role: str | None
    source: str
    detail: str
    team_name: str | None = None
    granted_by_team_name: str | None = None

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"

    def role_word(self) -> str:
        """The role said in a word a person reads;
        no access is said in words too."""
        if self.role is None:
            return "No access"
        return role_word(self.role)


def explanation(resolution: Resolution) -> str:
    """The whole answer in one plain sentence: who,
    what role, in which repository, and why."""
    who = resolution.username or "An anonymous visitor"
    if resolution.role is None:
        if resolution.visibility == "public":
            why = "no grant applies to them"
        else:
            why = ("the repository is private and no "
                   "grant applies to them, so its "
                   "existence stays private: surfaces "
                   "answer not found, not forbidden")
        return (f"{who} has no access to "
                f"{resolution.full_name}: {why}.")
    return (f"{who} has {resolution.role_word()} in "
            f"{resolution.full_name} because "
            f"{resolution.detail}.")


class PermissionEngine:
    """The resolver itself: gather the facts the
    earlier slices stored, build their contributions,
    and let the pure judgement decide. Reads only."""

    def __init__(
        self, conn: sqlite3.Connection, accounts: AccountStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._audit = audit
        self._now = time_fn
        self._orgs = OrganizationStore(
            conn, accounts, audit=None, time_fn=time_fn)
        self._org_members = OrgMembershipStore(
            conn, accounts, audit=None, time_fn=time_fn)
        self._teams = TeamStore(conn, accounts, audit=None,
                                time_fn=time_fn)
        self._nesting = NestedTeamStore(
            conn, accounts, audit=None, time_fn=time_fn)
        self._perms = TeamPermissionStore(
            conn, accounts, audit=None, time_fn=time_fn)

    @staticmethod
    def _repo_from_row(row: sqlite3.Row) -> Repository:
        keys = row.keys()
        return Repository(
            id=row["id"], owner=row["owner"],
            owner_lower=row["owner_lower"],
            name=row["name"], name_lower=row["name_lower"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            description=row["description"]
            if "description" in keys else "",
            visibility=row["visibility"]
            if "visibility" in keys else "private",
            default_branch=row["default_branch"]
            if "default_branch" in keys else "main",
            fork_of_id=row["fork_of_id"]
            if "fork_of_id" in keys else None,
            is_template=bool(row["is_template"])
            if "is_template" in keys else False,
            template_of_id=row["template_of_id"]
            if "template_of_id" in keys else None)

    def _team_grants(self, viewer: User, org_id: int,
                     repo_id: int) -> tuple[tuple[str, str, str], ...]:
        """(team acted through, granting team, role)
        for every team the viewer is an effective
        member of (S-188: direct members plus every
        ancestor's members) that effectively holds a
        grant in this repository (S-189)."""
        grants: list[tuple[str, str, str]] = []
        for team in self._teams.list_teams(org_id):
            member_ids = {m.user_id for m in
                          self._nesting.effective_members(
                              org_id, team.id)}
            if viewer.id not in member_ids:
                continue
            eff = self._perms.effective_permission(
                org_id, team.id, repo_id)
            if eff is not None:
                grants.append((team.name,
                               eff.granted_by_team_name,
                               eff.permission))
        return tuple(grants)

    # -- the one function --------------------------------
    def resolve(
        self, viewer: User | None, repo: Repository,
        *, collaborator_role: str | None = None,
    ) -> Resolution:
        """The viewer's role in *repo*, with its source
        and reason. ``collaborator_role`` is the grant
        the caller holds for this repository until
        S-191's store lands; it is validated loudly."""
        is_owner = False
        is_site_admin = False
        org_role: str | None = None
        team_grants: tuple[tuple[str, str, str], ...] = ()
        if viewer is not None:
            is_owner = (viewer.username_lower
                        == repo.owner_lower)
            is_site_admin = bool(viewer.is_admin)
            org = self._orgs.get_by_name(repo.owner)
            if org is not None and not is_owner:
                org_role = self._org_members.role_for(
                    viewer.id, org.id)
                if not is_site_admin and org_role != "owner":
                    team_grants = self._team_grants(
                        viewer, org.id, repo.id)
        decision = decide_permission(build_contributions(
            is_owner=is_owner, is_site_admin=is_site_admin,
            org_role=org_role, team_grants=team_grants,
            collaborator_role=collaborator_role
            if viewer is not None else None,
            visibility=repo.visibility))
        detail = decision.detail
        if decision.role is None and repo.visibility != "public":
            detail = ("the repository is private and no "
                      "grant applies")
        return Resolution(
            user_id=viewer.id if viewer else None,
            username=viewer.username if viewer else None,
            repo_id=repo.id, owner=repo.owner,
            name=repo.name, visibility=repo.visibility,
            role=decision.role, source=decision.source,
            detail=detail, team_name=decision.team_name,
            granted_by_team_name=decision.granted_by_team_name)

    def role_for(
        self, viewer: User | None, repo: Repository,
        *, collaborator_role: str | None = None,
    ) -> str | None:
        """Just the role: 'admin', 'maintain', 'write',
        'triage', 'read', or None (no access — render
        as not-found)."""
        return self.resolve(
            viewer, repo,
            collaborator_role=collaborator_role).role

    def can(
        self, viewer: User | None, repo: Repository,
        minimum: str = "read",
        *, collaborator_role: str | None = None,
    ) -> bool:
        """Rank check over the resolved role: does it
        stand at or above *minimum* on the ladder?"""
        return role_covers(
            self.role_for(viewer, repo,
                          collaborator_role=collaborator_role),
            minimum)

    def require_role(
        self, viewer: User | None, repo: Repository,
        minimum: str = "read",
        *, collaborator_role: str | None = None,
    ) -> str:
        """The resolved role when it meets *minimum*,
        else PermissionDeniedError (S-054's error) —
        the guard handlers call before serving."""
        role = self.role_for(
            viewer, repo, collaborator_role=collaborator_role)
        if not role_covers(role, minimum):
            raise PermissionDeniedError()
        return role  # type: ignore[return-value]

    def resolve_by_id(
        self, viewer_id: int | None, repo_id: int,
        *, collaborator_role: str | None = None,
    ) -> Resolution:
        """Resolve by stored ids: an unknown repository
        is ``repo_not_found`` and an unknown viewer id
        is ``no_such_user``; None as the viewer id is
        the anonymous visitor."""
        row = self._conn.execute(
            "SELECT * FROM repositories WHERE id = ?",
            (repo_id,)).fetchone()
        if row is None:
            raise OrganizationError(
                "repo_not_found", "No such repository.")
        viewer: User | None = None
        if viewer_id is not None:
            viewer = self._accounts.get_by_id(viewer_id)
            if viewer is None:
                raise OrganizationError(
                    "no_such_user", "No such account.")
        return self.resolve(
            viewer, self._repo_from_row(row),
            collaborator_role=collaborator_role)

    def resolutions_for(
        self, viewers: list[User | None], repo: Repository,
        *, collaborator_role: str | None = None,
    ) -> list[Resolution]:
        """The matrix helper: one resolution per
        viewer, in the order the viewers were given."""
        return [self.resolve(v, repo,
                             collaborator_role=collaborator_role)
                for v in viewers]


def render_resolution_page(resolution: Resolution) -> str:
    """One person's permission, explained: the role
    and its source said in words (never colour-only),
    the plain-language reason, and the ladder stated
    whole — every value escaped through S-010."""
    ladder = " / ".join(role_word(r) for r in ROLES)
    who = resolution.username or "An anonymous visitor"
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Permission — "
        f"{escape_html_text(resolution.full_name)} — "
        f"Samverk</title></head>",
        "<body>",
        f"<h1>Permission in "
        f"{escape_html_text(resolution.full_name)}</h1>",
        f"<p>{escape_html_text(explanation(resolution))}</p>",
        f"<p>Role: {escape_html_text(resolution.role_word())}. "
        f"Source: {escape_html_text(source_word(resolution.source))}."
        "</p>",
        f"<p>The permission ladder (S-189) is: "
        f"{escape_html_text(ladder)}. Read may look; triage "
        "may manage issues and pull requests without writing "
        "code; write may push; maintain may manage "
        "non-destructive repository settings; admin is full "
        "control. A higher rung includes every rung below it.</p>",
        "<p>The engine (S-190) judges ownership, site "
        "administration, organization ownership, team grants "
        "with nesting, collaborator grants and visibility in "
        "one function, and reports the highest role with the "
        "source that granted it. Organization membership "
        "alone grants nothing until the default repository "
        "permission (S-192) lands; collaborator grants are "
        "stored per repository from S-191.</p>",
        f"<p>Viewer: {escape_html_text(who)}.</p>",
        "</body></html>",
    ]
    return "\n".join(parts)


def render_matrix_page(resolutions: list[Resolution]) -> str:
    """The permission matrix for one repository: every
    viewer's role and source in words, in the order the
    resolutions were computed — every value escaped
    through S-010."""
    if resolutions:
        label = resolutions[0].full_name
    else:
        label = "no repository"
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Permission matrix — "
        f"{escape_html_text(label)} — Samverk</title></head>",
        "<body>",
        f"<h1>Permission matrix — "
        f"{escape_html_text(label)}</h1>",
        "<p>Each person's resolved role (S-190), with the "
        "source that granted it, said in words. The highest "
        "applicable grant wins; a private repository answers "
        "no access — rendered as not found — to everyone "
        "without a grant.</p>",
    ]
    if resolutions:
        parts.append("<ul>")
        for res in resolutions:
            who = res.username or "Anonymous"
            parts.append(
                f"<li>{escape_html_text(who)} — "
                f"{escape_html_text(res.role_word())} — "
                f"{escape_html_text(source_word(res.source))}: "
                f"{escape_html_text(res.detail)}</li>")
        parts.append("</ul>")
    else:
        parts.append("<p>No resolutions were computed.</p>")
    parts.append("</body></html>")
    return "\n".join(parts)
