"""Users, orgs, teams API (S-244).

Users, orgs, teams API -- membership and
permission administration automatable end-to-end.
S-237's contract named this slice as the builder
of the remaining resource family (one user, one
organization, its members, its teams); this
module is that family, in the shape the contract
ratified, extended in this slice -- in the
contract itself, before the code -- with the
administration children the acceptance names:
one member, one team, its members, its
repository permissions, the organization's
default permission, and a repository's outside
collaborators. Without those children the family
could be read but not administered, and the
roadmap's acceptance is administration
automatable end-to-end.

- **No API-only back doors, by construction.**
  Every act delegates to the very store the web
  uses, so the API can do nothing a signed-in
  person cannot, and is refused exactly what the
  web refuses: a user is S-029's `ProfileStore`
  over S-004's accounts; organization creation
  and profile are S-185's `OrganizationStore`;
  membership (add, role, remove) is S-186's
  `OrgMembershipStore`, last-owner invariant
  included; teams and their members and
  repository links are S-187's `TeamStore`;
  a team's ladder role in a repository is
  S-189's `TeamPermissionStore` (graded through
  S-188's chain only as a read of the direct
  grant this face sets); the organization-wide
  default is S-192's `DefaultPermissionStore`;
  and a repository's outside grants are S-191's
  `OutsideCollaboratorStore`, with S-200's
  role-change guardrails riding inside those
  stores exactly as they ride on the web. The
  stores' own audits witness each act exactly
  as the same act on the web is witnessed; this
  face adds no event of its own.
- **What the web has no writer for, the API
  does not invent.** There is no team deletion
  on the web, so there is none here; an
  organization's name is its address and the
  web offers no rename, so an org PATCH carries
  the profile fields alone (display name,
  description, website); and a user PATCH is
  not offered at all -- the contract's user
  resource is a read, and a person's own
  profile edits stay the signed-in web flow
  they already are. Invitations (S-193) carry
  no contracted resource, so they stay
  web-only in this slice: membership
  administration here is the direct door
  S-186's owners use on the web.
- **Every call resolves through S-238 and
  S-190.** The header is resolved by S-238's
  door (`ApiAuthenticator`) and nothing else.
  Repository-scoped administration (outside
  collaborators) is then judged by
  `authorize_identity` at the admin rung --
  S-190's permission engine alone, with the
  token's scope as a ceiling over it, checked
  after it. Organization-scoped acts are judged
  by the very membership facts S-190's engine
  itself reads: an org write is an org owner's
  or a site admin's act, decided by S-186's
  own role record (the stores re-judge it
  themselves before writing, exactly as on the
  web), and organization administration reads
  (team permissions, the default, the member
  administration surfaces) stand behind the
  same owner-or-admin gate at this face, so a
  secret team's grants are never listed to a
  caller the web would not show them to.
- **Token scope is the profile ceiling.**
  S-238's scope law names the `profile` family
  for exactly this surface: a classic token
  must carry `profile:read` for this family's
  reads and `profile:write` for its writes
  (repository collaborators ride the repo
  family's ceiling through `authorize_identity`
  instead). Fine-grained tokens hold no profile
  permission in S-033's model -- their fine
  answer is None, which no grant satisfies --
  so a fine-grained token is refused
  `insufficient_scope` on this family, exactly
  as S-238's door already judges it. Password
  callers carry their account's own standing.
- **Public reads stay public, in the web's own
  shape.** An organization, its members, its
  visible teams, a visible team's members, and
  a person's profile are readable without a
  credential, exactly as their pages are; a
  secret team is indistinguishable from a
  missing one to a caller who may not see it
  (S-187's viewer law, `team_not_found`), and a
  missing organization or user is the one
  refusal `org_not_found` / `no_such_user`.
- **Shapes are the contract's.** A user is
  S-237's (username, display_name, bio,
  created_at) -- the display name the profile's
  effective one, the bio the profile's own; an
  organization is (id, name, display_name,
  description, created_at) -- the display name
  its effective one, the description its bio,
  the very words its page shows; a member is
  (username, role, since); a team is (id, slug,
  name, privacy); and the administration
  children carry the shapes the contract now
  states for them. Lists speak the one
  envelope -- the filtered `total` tallied
  before the cap, the `returned` count the cap
  allowed, a `complete` flag, and the `limit`
  honoured (default 100, at most 500, the
  landed faces' bounds).
- **Refusals are S-240's shape.** Every refusal
  is a `UsersOrgsTeamsAPIError` with a
  machine-branchable reason -- S-238's reasons
  verbatim for authentication and scope, the
  stores' own reasons verbatim for the acts
  they refuse -- rendered by `error_to_dict`
  in the one problem format through
  samverk/error_shape.py.
- **What a read witnesses.** Reads write no
  row and audit nothing (S-186's founding-owner
  seed is the membership store's own first
  touch, on reads as on the web); the writes
  are the stores' own acts, witnessed by the
  stores. No migration (schema stays 94), no
  taxonomy event (129 stand: 33 auth / 83 repo
  / 13 admin).
"""
from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable

from .accounts import AccountStore, User
from .api_auth import (
    ApiAuthError, ApiAuthenticator, ApiIdentity, decide_token_scope)
from .default_permissions import (
    DefaultPermission, DefaultPermissionStore)
from .error_shape import problem_from_error, problem_to_dict
from .escaping import escape_html_text
from .organization_members import OrgMembership, OrgMembershipStore
from .organizations import (
    Organization, OrganizationError, OrganizationStore)
from .outside_collaborators import (
    OutsideCollaborator, OutsideCollaboratorStore)
from .profiles import Profile, ProfileError, ProfileStore
from .repositories import RepositoryStore
from .team_permissions import TeamPermission, TeamPermissionStore
from .teams import Team, TeamMembership, TeamStore

__all__ = [
    "DEFAULT_LIMIT", "MAX_LIMIT", "USERS_ORGS_TEAMS_API_PATH",
    "UsersOrgsTeamsAPI", "UsersOrgsTeamsAPIError",
    "collaborator_to_dict", "default_permission_to_dict",
    "error_to_dict", "member_to_dict", "organization_to_dict",
    "render_users_orgs_teams_api_page", "team_member_to_dict",
    "team_permission_to_dict", "team_to_dict", "to_json",
    "user_to_dict",
]

USERS_ORGS_TEAMS_API_PATH = "/api/users-orgs-teams"

# The landed faces' own bounds (S-231/S-242): an
# API limit lives inside them or is refused.
DEFAULT_LIMIT = 100
MAX_LIMIT = 500

_ORG_NOT_FOUND = "No such organization."
_TEAM_NOT_FOUND = "No such team."
_NO_SUCH_USER = "No such user."
_NOT_ORG_ADMIN = (
    "Only an organization owner or a site admin "
    "can administer this organization.")

_ORG_CREATE_KEYS = frozenset(
    {"name", "display_name", "description", "website"})
_ORG_PATCH_KEYS = frozenset(
    {"display_name", "description", "website"})
_MEMBER_ADD_KEYS = frozenset({"username", "role"})
_MEMBER_PATCH_KEYS = frozenset({"role"})
_TEAM_CREATE_KEYS = frozenset(
    {"name", "description", "privacy", "parent"})
_TEAM_PATCH_KEYS = frozenset({"description", "privacy"})
_TEAM_MEMBER_ADD_KEYS = frozenset({"username"})
_TEAM_REPO_ADD_KEYS = frozenset({"repository", "permission"})
_TEAM_REPO_PATCH_KEYS = frozenset({"permission"})
_DEFAULT_PATCH_KEYS = frozenset({"role"})
_COLLABORATOR_ADD_KEYS = frozenset({"username", "role"})
_COLLABORATOR_PATCH_KEYS = frozenset({"role"})

_STORE_ERRORS = (OrganizationError, ProfileError)


class UsersOrgsTeamsAPIError(ValueError):
    """One refused users/orgs/teams-API call: a
    machine-branchable reason with its human
    detail."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def error_to_dict(exc: UsersOrgsTeamsAPIError) -> dict:
    """One refusal as data, in S-240's one problem
    format (samverk/error_shape.py): type, title,
    status, detail, error_id -- nothing else."""
    return problem_to_dict(problem_from_error(exc))


def to_json(payload: dict) -> str:
    """One payload as a JSON text: keys sorted so
    the same answer renders byte-identically
    twice."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


# ------------------------------------------------------------------
# Serialisers -- one user, one organization, one
# member, one team and its administration kin
# ------------------------------------------------------------------

def user_to_dict(user: User, profile: Profile) -> dict:
    """One person as JSON-safe data, in S-237's
    contracted field order exactly: username,
    display_name, bio, created_at -- the facts
    the profile page shows: the display name the
    profile's effective one (the username when
    none was set), the bio the profile's own
    (null when none). Data carries the raw
    values -- S-010 escaping is the page's law,
    not the wire's."""
    return {
        "username": user.username,
        "display_name": profile.effective_display_name(
            user.username),
        "bio": profile.bio,
        "created_at": user.created_at,
    }


def organization_to_dict(org: Organization) -> dict:
    """One organization as JSON-safe data, in
    S-237's contracted field order exactly: id,
    name, display_name, description, created_at
    -- the display name its effective one, the
    description its bio, as its page shows
    them."""
    return {
        "id": org.id,
        "name": org.name,
        "display_name": org.effective_display_name(),
        "description": org.bio,
        "created_at": org.created_at,
    }


def member_to_dict(member: OrgMembership) -> dict:
    """One organization membership as JSON-safe
    data, in the contract's field order:
    username, role, since -- the role the web
    records (owner or member), `since` the time
    the membership began."""
    return {
        "username": member.username,
        "role": member.role,
        "since": member.created_at,
    }


def team_to_dict(team: Team) -> dict:
    """One team as JSON-safe data, in the
    contract's field order: id, slug, name,
    privacy -- the slug its canonical name, the
    privacy said in its stored word (visible or
    secret)."""
    return {
        "id": team.id,
        "slug": team.name_lower,
        "name": team.name,
        "privacy": team.privacy,
    }


def team_member_to_dict(member: TeamMembership) -> dict:
    """One team membership as JSON-safe data, in
    the contract's field order: username, since.
    A team carries no second role ladder for its
    members -- membership itself is the fact."""
    return {
        "username": member.username,
        "since": member.created_at,
    }


def team_permission_to_dict(permission: TeamPermission) -> dict:
    """One team's direct repository permission as
    JSON-safe data, in the contract's field
    order: repository (its full name), permission
    (its S-189 ladder role)."""
    return {
        "repository": f"{permission.owner}/{permission.name}",
        "permission": permission.permission,
    }


def default_permission_to_dict(
        default: DefaultPermission) -> dict:
    """One organization's default repository
    permission as JSON-safe data, in the
    contract's field order: role (a ladder rung,
    or none), is_set (whether an owner ever set
    it -- an unset default reads as role none,
    not set, exactly as S-192 reads it)."""
    return {
        "role": default.role,
        "is_set": default.is_set,
    }


def collaborator_to_dict(grant: OutsideCollaborator) -> dict:
    """One outside collaborator grant as JSON-safe
    data, in the contract's field order: username,
    role, repository (its full name) -- the grant
    S-191 records, no more."""
    return {
        "username": grant.username,
        "role": grant.role,
        "repository": grant.full_name,
    }


# ------------------------------------------------------------------
# The API face
# ------------------------------------------------------------------

class UsersOrgsTeamsAPI:
    """The S-244 executor: the contract's users,
    organizations and teams families, answered in
    data. It owns no store and no permission law
    of its own -- S-238's door, S-190's engine
    (for the repository-scoped children), S-186's
    membership record (for the organization
    gate), and the web's own stores (profiles,
    organizations, membership, teams, team
    permissions, the default permission, outside
    collaborators) are built once here and every
    call delegates to them, so parity is by
    construction, not by copy."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        accounts: AccountStore,
        repositories: RepositoryStore,
        audit=None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._repos = repositories
        self._audit = audit
        self._auth = ApiAuthenticator(
            conn, accounts, repositories, audit=audit,
            time_fn=time_fn)
        self._profiles = ProfileStore(
            conn, accounts, audit=audit, time_fn=time_fn)
        self._orgs = OrganizationStore(
            conn, accounts, audit=audit, time_fn=time_fn)
        self._members = OrgMembershipStore(
            conn, accounts, audit=audit, time_fn=time_fn)
        self._teams = TeamStore(
            conn, accounts, audit=audit, time_fn=time_fn)
        self._team_perms = TeamPermissionStore(
            conn, accounts, audit=audit, time_fn=time_fn)
        self._defaults = DefaultPermissionStore(
            conn, accounts, audit=audit, time_fn=time_fn)
        self._collabs = OutsideCollaboratorStore(
            conn, accounts, audit=audit, time_fn=time_fn)

    # -- shared judgements --------------------------------
    @staticmethod
    def _check_limit(limit: object) -> int:
        if (isinstance(limit, bool) or not isinstance(limit, int)
                or limit < 1 or limit > MAX_LIMIT):
            raise UsersOrgsTeamsAPIError(
                "limit_invalid",
                f"limit must be an integer between 1 and {MAX_LIMIT}.")
        return limit

    @staticmethod
    def _envelope(kind: str, items: list, *, limit: int) -> dict:
        """One list answer in the contract's
        envelope: the filtered total tallied before
        the cap, how many the cap returned, whether
        the answer is complete under that cap, and
        the limit honoured."""
        page = items[:limit]
        return {
            "total": len(items),
            "returned": len(page),
            "complete": len(items) <= len(page),
            "limit": limit,
            kind: page,
        }

    @staticmethod
    def _payload(payload: object, allowed: frozenset, *,
                 required: bool) -> dict:
        """One request body as a dict of known keys:
        a body that is not an object, or carries a
        key this resource does not take, is refused
        `payload_invalid` -- the API never guesses
        at a body's meaning and never silently drops
        a field its caller named."""
        if payload is None:
            if required:
                raise UsersOrgsTeamsAPIError(
                    "payload_invalid",
                    "This call needs a JSON object body.")
            return {}
        if not isinstance(payload, dict):
            raise UsersOrgsTeamsAPIError(
                "payload_invalid",
                "This call needs a JSON object body.")
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise UsersOrgsTeamsAPIError(
                "payload_invalid",
                "This resource does not take the field "
                f"{unknown[0]!r}.")
        return payload

    @staticmethod
    def _store_error(exc: Exception) -> "UsersOrgsTeamsAPIError":
        """One store refusal carried onto this face:
        the store's reason verbatim, in this face's
        error."""
        return UsersOrgsTeamsAPIError(exc.reason, str(exc))

    def _caller(self, header: object, *, required: bool) -> ApiIdentity:
        """The caller of one call, through S-238's
        door alone: its refusals ride this face's
        error verbatim (reason and detail)."""
        try:
            return self._auth.resolve_caller(header, required=required)
        except ApiAuthError as exc:
            raise UsersOrgsTeamsAPIError(
                exc.reason, str(exc)) from None

    def _require_profile_scope(self, identity: ApiIdentity,
                               level: str) -> None:
        """The token-scope ceiling of this family:
        S-238's `profile` family, judged by its own
        pure seam -- a classic token must carry
        profile:read / profile:write, a fine-grained
        token holds no profile permission and never
        passes, and a password caller carries their
        account's own standing."""
        if identity.kind not in ("classic_token", "fine_token"):
            return
        granted = (identity.scopes if identity.kind == "classic_token"
                   else identity.permissions)
        if not decide_token_scope(
                identity.kind, frozenset(granted), "profile",
                level, bound_matches=True):
            raise UsersOrgsTeamsAPIError(
                "insufficient_scope",
                "That token does not carry the scope for "
                "this call.")

    def _org(self, org_name: object) -> Organization:
        """One organization by its name, or the one
        refusal `org_not_found`."""
        org = self._orgs.get_by_name(org_name)
        if org is None:
            raise UsersOrgsTeamsAPIError(
                "org_not_found", _ORG_NOT_FOUND)
        return org

    def _require_org_admin(self, identity: ApiIdentity,
                           org: Organization) -> User:
        """The organization administration gate: the
        caller must be signed in and stand as an
        owner of this organization (S-186's own
        record -- the same fact S-190's engine
        reads) or as a site admin. Anyone else is
        refused `not_org_owner`, the membership
        store's own reason for the same line."""
        user = identity.user
        if user is None:
            raise UsersOrgsTeamsAPIError(
                "authentication_required",
                "This API call needs a credential: a Bearer "
                "token, or Basic authentication for scripts.")
        if user.is_admin:
            return user
        try:
            role = self._members.role_for(user.id, org.id)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        if role != "owner":
            raise UsersOrgsTeamsAPIError(
                "not_org_owner", _NOT_ORG_ADMIN)
        return user

    def _team(self, org: Organization, slug: object) -> Team:
        """One team of the organization by its slug,
        or the one refusal `team_not_found`."""
        team = self._teams.get_team_by_name(org.id, slug)
        if team is None:
            raise UsersOrgsTeamsAPIError(
                "team_not_found", _TEAM_NOT_FOUND)
        return team

    def _team_for_viewer(self, identity: ApiIdentity,
                         org: Organization, slug: object) -> Team:
        """One team as this caller may know it:
        S-187's viewer law -- a secret team the
        caller may not see is `team_not_found`,
        exactly as if it did not exist."""
        team = self._team(org, slug)
        viewer_id = identity.user.id if identity.user else None
        try:
            return self._teams.get_team_for_viewer(
                viewer_id, org.id, team.id)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None

    def _repo_admin(self, header: object, owner: object,
                    repo: object):
        """One repository-scoped administration call
        judged whole through S-238's seam: the
        caller resolved, then S-190 at the admin
        rung with the token's scope as ceiling.
        Its refusals ride this face's error
        verbatim."""
        identity = self._caller(header, required=True)
        try:
            auth = self._auth.authorize_identity(
                identity, owner, repo, minimum="admin",
                resource="repo")
        except ApiAuthError as exc:
            raise UsersOrgsTeamsAPIError(
                exc.reason, str(exc)) from None
        return identity, auth

    # -- users: one person ----------------------------------
    def get_user(self, header: object, username: object) -> dict:
        """One person's public profile as data:
        exactly the facts the profile page shows --
        the account's username and age, and S-029's
        profile (its effective display name and its
        bio). A missing account is `no_such_user`.
        No credential is needed; a token caller is
        judged by the profile scope ceiling."""
        identity = self._caller(header, required=False)
        self._require_profile_scope(identity, "read")
        user = self._accounts.get_by_username(username)
        if user is None:
            raise UsersOrgsTeamsAPIError(
                "no_such_user", _NO_SUCH_USER)
        try:
            profile = self._profiles.get_profile(user.id)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        return user_to_dict(user, profile)

    # -- organizations: the collection ----------------------
    def list_organizations(self, header: object, *,
                           limit: int = DEFAULT_LIMIT) -> dict:
        """Every organization on the instance, in
        name order, in the list envelope: the org
        directory the web's own listing shows, with
        no credential needed."""
        limit = self._check_limit(limit)
        identity = self._caller(header, required=False)
        self._require_profile_scope(identity, "read")
        found = self._orgs.list_organizations()
        items = [organization_to_dict(org) for org in found]
        return self._envelope("organizations", items, limit=limit)

    def create_organization(self, header: object, payload: object,
                            *, source_ip: str | None = None) -> dict:
        """Create one organization, through S-185's
        own creation: its shared-namespace name law
        (a user's name, a reserved name, a taken
        name all refused by the store, verbatim)
        and its `auth.organization.create` witness
        are the store's, unchanged. The payload
        names `name` and may name `display_name`,
        `description` and `website`. A signed-in
        caller is required; a token must
        additionally carry the profile write
        scope."""
        body = self._payload(payload, _ORG_CREATE_KEYS, required=True)
        identity = self._caller(header, required=True)
        self._require_profile_scope(identity, "write")
        user = identity.user
        assert user is not None
        try:
            org = self._orgs.create_organization(
                user.id, body.get("name"),
                display_name=body.get("display_name"),
                bio=body.get("description"),
                website=body.get("website"),
                source_ip=source_ip)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        return organization_to_dict(org)

    # -- organizations: one organization ---------------------
    def get_organization(self, header: object, org: object) -> dict:
        """One organization as data: its profile as
        its page shows it, readable with no
        credential. A missing organization is
        `org_not_found`."""
        identity = self._caller(header, required=False)
        self._require_profile_scope(identity, "read")
        return organization_to_dict(self._org(org))

    def update_organization(self, header: object, org: object,
                            payload: object, *,
                            source_ip: str | None = None) -> dict:
        """Change one organization's profile,
        through S-185's own update: the payload may
        name `display_name`, `description` and
        `website`; a named field is set through
        the store's cleaners (an empty value
        clears it, as the web's form does), and an
        unnamed field is carried over untouched --
        a PATCH changes only what it names. The
        store's steward law judges the act exactly
        as on the web (the organization's steward
        or a site admin, until the web widens it),
        and its refusal rides verbatim."""
        body = self._payload(payload, _ORG_PATCH_KEYS, required=True)
        if not body:
            raise UsersOrgsTeamsAPIError(
                "payload_invalid",
                "This call names no field to update.")
        identity = self._caller(header, required=True)
        self._require_profile_scope(identity, "write")
        user = identity.user
        assert user is not None
        current = self._org(org)
        try:
            updated = self._orgs.update_profile(
                user.id, current.id,
                display_name=(body["display_name"]
                              if "display_name" in body
                              else current.display_name),
                bio=(body["description"]
                     if "description" in body else current.bio),
                website=(body["website"]
                         if "website" in body else current.website),
                source_ip=source_ip)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        return organization_to_dict(updated)

    # -- organizations: members -------------------------------
    def list_members(self, header: object, org: object, *,
                     limit: int = DEFAULT_LIMIT) -> dict:
        """The organization's members in the list
        envelope, owners first then by name --
        S-186's own listing, each with the role the
        web records for them. Readable with no
        credential, as the members page is."""
        limit = self._check_limit(limit)
        identity = self._caller(header, required=False)
        self._require_profile_scope(identity, "read")
        found_org = self._org(org)
        try:
            found = self._members.list_members(found_org.id)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        items = [member_to_dict(member) for member in found]
        answer = self._envelope("members", items, limit=limit)
        return {"organization": found_org.name, **answer}

    def add_member(self, header: object, org: object,
                   payload: object, *,
                   source_ip: str | None = None) -> dict:
        """Add one member, through S-186's own
        door: an org owner or a site admin adds a
        real account, as `member` unless the
        payload's `role` names `owner`; already a
        member is the store's `already_member`,
        and its `auth.organization.update` witness
        is the store's, unchanged. A signed-in
        caller is required; a token must
        additionally carry the profile write
        scope."""
        body = self._payload(payload, _MEMBER_ADD_KEYS, required=True)
        identity = self._caller(header, required=True)
        self._require_profile_scope(identity, "write")
        user = identity.user
        assert user is not None
        found_org = self._org(org)
        try:
            member = self._members.add_member(
                user.id, found_org.id, body.get("username"),
                body.get("role", "member"), source_ip=source_ip)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        return member_to_dict(member)

    def get_member(self, header: object, org: object,
                   username: object) -> dict:
        """One membership as data: the named
        person's role in the organization. A
        person who is not a member answers
        `not_a_member`, and a missing account
        `no_such_user` -- the administration
        surface names its own rows, as the web's
        members settings do."""
        identity = self._caller(header, required=True)
        self._require_profile_scope(identity, "read")
        found_org = self._org(org)
        self._require_org_admin(identity, found_org)
        target = self._accounts.get_by_username(username)
        if target is None:
            raise UsersOrgsTeamsAPIError(
                "no_such_user", _NO_SUCH_USER)
        try:
            member = self._members.get_membership(
                target.id, found_org.id)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        if member is None:
            raise UsersOrgsTeamsAPIError(
                "not_a_member",
                "That person is not a member of this organization.")
        return member_to_dict(member)

    def update_member(self, header: object, org: object,
                      username: object, payload: object, *,
                      source_ip: str | None = None) -> dict:
        """Set one member's role, through S-186's
        own role change: owner or member, with the
        last-owner invariant judged by the store
        (demoting the last owner is its
        `last_owner` refusal, verbatim). The
        payload names `role`."""
        body = self._payload(payload, _MEMBER_PATCH_KEYS, required=True)
        if "role" not in body:
            raise UsersOrgsTeamsAPIError(
                "payload_invalid",
                "This call names no field to update.")
        identity = self._caller(header, required=True)
        self._require_profile_scope(identity, "write")
        user = identity.user
        assert user is not None
        found_org = self._org(org)
        try:
            member = self._members.set_role(
                user.id, found_org.id, username, body.get("role"),
                source_ip=source_ip)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        return member_to_dict(member)

    def remove_member(self, header: object, org: object,
                      username: object, *,
                      source_ip: str | None = None) -> dict:
        """Remove one member, through S-186's own
        removal: the last owner cannot be removed
        (the store's `last_owner`), a non-member is
        its `not_a_member`, and the witness is the
        store's. The answer names the removal."""
        identity = self._caller(header, required=True)
        self._require_profile_scope(identity, "write")
        user = identity.user
        assert user is not None
        found_org = self._org(org)
        try:
            self._members.remove_member(
                user.id, found_org.id, username,
                source_ip=source_ip)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        target = self._accounts.get_by_username(username)
        return {
            "organization": found_org.name,
            "username": target.username if target else username,
            "removed": True,
        }

    # -- organizations: teams ----------------------------------
    def list_teams(self, header: object, org: object, *,
                   limit: int = DEFAULT_LIMIT) -> dict:
        """The organization's teams in the list
        envelope, in name order, filtered by
        S-187's viewer law for this caller: a
        secret team a caller may not see
        contributes no row, no name and no count.
        S-187's own viewer-filtered listing is the
        source, unchanged."""
        limit = self._check_limit(limit)
        identity = self._caller(header, required=False)
        self._require_profile_scope(identity, "read")
        found_org = self._org(org)
        viewer_id = identity.user.id if identity.user else None
        try:
            found = self._teams.list_teams_for_viewer(
                viewer_id, found_org.id)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        items = [team_to_dict(team) for team in found]
        answer = self._envelope("teams", items, limit=limit)
        return {"organization": found_org.name, **answer}

    def create_team(self, header: object, org: object,
                    payload: object, *,
                    source_ip: str | None = None) -> dict:
        """Create one team, through S-187's own
        creation: an org owner or a site admin
        creates it (and stands as its first
        member, as on the web), its slug law and
        taken-name refusal are the store's, and
        its witness is the store's. The payload
        names `name` and may name `description`,
        `privacy` (visible or secret) and `parent`
        (the slug of a team in the same
        organization, for S-188's nesting)."""
        body = self._payload(payload, _TEAM_CREATE_KEYS, required=True)
        identity = self._caller(header, required=True)
        self._require_profile_scope(identity, "write")
        user = identity.user
        assert user is not None
        found_org = self._org(org)
        parent_id = None
        if body.get("parent") is not None:
            parent = self._teams.get_team_by_name(
                found_org.id, body.get("parent"))
            if parent is None:
                raise UsersOrgsTeamsAPIError(
                    "parent_not_found", "No such parent team.")
            parent_id = parent.id
        try:
            team = self._teams.create_team(
                user.id, found_org.id, body.get("name"),
                description=body.get("description"),
                privacy=body.get("privacy", "visible"),
                parent_team_id=parent_id, source_ip=source_ip)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        return team_to_dict(team)

    def get_team(self, header: object, org: object,
                 team: object) -> dict:
        """One team as data, under S-187's viewer
        law: a secret team the caller may not see
        is `team_not_found`, exactly as a missing
        one."""
        identity = self._caller(header, required=False)
        self._require_profile_scope(identity, "read")
        found_org = self._org(org)
        found = self._team_for_viewer(identity, found_org, team)
        return team_to_dict(found)

    def update_team(self, header: object, org: object,
                    team: object, payload: object, *,
                    source_ip: str | None = None) -> dict:
        """Change one team, through S-187's own
        update: the payload may name `description`
        and `privacy`; a named field is set
        through the store (an empty description
        clears it, as the web's form does), an
        unnamed one is carried over untouched.
        The store's owner-or-admin law judges the
        act exactly as on the web. A team's name
        is its slug and address, and the web
        offers no rename, so none is offered
        here."""
        body = self._payload(payload, _TEAM_PATCH_KEYS, required=True)
        if not body:
            raise UsersOrgsTeamsAPIError(
                "payload_invalid",
                "This call names no field to update.")
        identity = self._caller(header, required=True)
        self._require_profile_scope(identity, "write")
        user = identity.user
        assert user is not None
        found_org = self._org(org)
        current = self._team(found_org, team)
        try:
            updated = self._teams.update_team(
                user.id, found_org.id, current.id,
                description=(body["description"]
                             if "description" in body
                             else current.description),
                privacy=(body["privacy"]
                         if "privacy" in body else None),
                source_ip=source_ip)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        return team_to_dict(updated)

    # -- teams: members ------------------------------------------
    def list_team_members(self, header: object, org: object,
                          team: object, *,
                          limit: int = DEFAULT_LIMIT) -> dict:
        """One team's members in the list envelope,
        in name order: S-187's own listing, behind
        its viewer law -- a secret team the caller
        may not see is `team_not_found` before any
        member is named."""
        limit = self._check_limit(limit)
        identity = self._caller(header, required=False)
        self._require_profile_scope(identity, "read")
        found_org = self._org(org)
        found = self._team_for_viewer(identity, found_org, team)
        try:
            members = self._teams.list_members(found_org.id, found.id)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        items = [team_member_to_dict(member) for member in members]
        answer = self._envelope("members", items, limit=limit)
        return {"organization": found_org.name,
                "team": found.name_lower, **answer}

    def add_team_member(self, header: object, org: object,
                        team: object, payload: object, *,
                        source_ip: str | None = None) -> dict:
        """Add one member to one team, through
        S-187's own door: the target must already
        be a member of the organization (the
        store's `not_org_member` otherwise), and
        already standing in the team is its
        `already_team_member`. The payload names
        `username`."""
        body = self._payload(
            payload, _TEAM_MEMBER_ADD_KEYS, required=True)
        identity = self._caller(header, required=True)
        self._require_profile_scope(identity, "write")
        user = identity.user
        assert user is not None
        found_org = self._org(org)
        found = self._team(found_org, team)
        try:
            member = self._teams.add_member(
                user.id, found_org.id, found.id,
                body.get("username"), source_ip=source_ip)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        return team_member_to_dict(member)

    def remove_team_member(self, header: object, org: object,
                           team: object, username: object, *,
                           source_ip: str | None = None) -> dict:
        """Remove one member from one team, through
        S-187's own removal: a person not standing
        in the team is its `not_team_member`. The
        answer names the removal."""
        identity = self._caller(header, required=True)
        self._require_profile_scope(identity, "write")
        user = identity.user
        assert user is not None
        found_org = self._org(org)
        found = self._team(found_org, team)
        try:
            self._teams.remove_member(
                user.id, found_org.id, found.id, username,
                source_ip=source_ip)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        target = self._accounts.get_by_username(username)
        return {
            "organization": found_org.name,
            "team": found.name_lower,
            "username": target.username if target else username,
            "removed": True,
        }

    # -- teams: repository permissions ---------------------------
    def list_team_repositories(self, header: object, org: object,
                               team: object, *,
                               limit: int = DEFAULT_LIMIT) -> dict:
        """One team's direct repository permissions
        in the list envelope, in repository order:
        S-189's own auditable listing. This is
        administration data, so the caller must
        stand as an org owner or a site admin --
        the gate the web's team-permissions
        settings stand behind."""
        limit = self._check_limit(limit)
        identity = self._caller(header, required=True)
        self._require_profile_scope(identity, "read")
        found_org = self._org(org)
        self._require_org_admin(identity, found_org)
        found = self._team(found_org, team)
        try:
            perms = self._team_perms.list_permissions(
                found_org.id, found.id)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        items = [team_permission_to_dict(perm) for perm in perms]
        answer = self._envelope("repositories", items, limit=limit)
        return {"organization": found_org.name,
                "team": found.name_lower, **answer}

    def link_team_repository(self, header: object, org: object,
                             team: object, payload: object, *,
                             source_ip: str | None = None) -> dict:
        """Link one of the organization's
        repositories to one team, through S-187's
        own link, and -- when the payload names
        `permission` -- grade it in the same call
        through S-189's own setter, so a script
        stands a team's grant up in one act. A
        repository outside the organization is
        the store's `repo_not_in_org`; a missing
        one is `repo_not_found`. The payload names
        `repository` (its name inside the
        organization)."""
        body = self._payload(
            payload, _TEAM_REPO_ADD_KEYS, required=True)
        identity = self._caller(header, required=True)
        self._require_profile_scope(identity, "write")
        user = identity.user
        assert user is not None
        found_org = self._org(org)
        found = self._team(found_org, team)
        repo = self._repos.get_repository(
            found_org.name, body.get("repository"))
        if repo is None:
            raise UsersOrgsTeamsAPIError(
                "repo_not_found", "No such repository.")
        try:
            link = self._teams.link_repo(
                user.id, found_org.id, found.id, repo.id,
                source_ip=source_ip)
            if "permission" in body:
                graded = self._team_perms.set_permission(
                    user.id, found_org.id, found.id, repo.id,
                    body.get("permission"), source_ip=source_ip)
                return team_permission_to_dict(graded)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        return {
            "repository": f"{link.owner}/{link.name}",
            "permission": link.permission,
        }

    def update_team_repository(self, header: object, org: object,
                               team: object, repo: object,
                               payload: object, *,
                               source_ip: str | None = None) -> dict:
        """Set one linked team's ladder role in one
        repository, through S-189's own setter:
        the role is validated by the store, the
        team must already be linked (its
        `not_linked` otherwise), and S-200's
        last-admin guardrail rides inside the
        store exactly as on the web. The payload
        names `permission`."""
        body = self._payload(
            payload, _TEAM_REPO_PATCH_KEYS, required=True)
        if "permission" not in body:
            raise UsersOrgsTeamsAPIError(
                "payload_invalid",
                "This call names no field to update.")
        identity = self._caller(header, required=True)
        self._require_profile_scope(identity, "write")
        user = identity.user
        assert user is not None
        found_org = self._org(org)
        found = self._team(found_org, team)
        found_repo = self._repos.get_repository(found_org.name, repo)
        if found_repo is None:
            raise UsersOrgsTeamsAPIError(
                "repo_not_found", "No such repository.")
        try:
            graded = self._team_perms.set_permission(
                user.id, found_org.id, found.id, found_repo.id,
                body.get("permission"), source_ip=source_ip)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        return team_permission_to_dict(graded)

    def unlink_team_repository(self, header: object, org: object,
                               team: object, repo: object, *,
                               source_ip: str | None = None) -> dict:
        """Unlink one repository from one team,
        through S-187's own unlink: a repository
        not linked is its `not_linked`. The answer
        names the removal."""
        identity = self._caller(header, required=True)
        self._require_profile_scope(identity, "write")
        user = identity.user
        assert user is not None
        found_org = self._org(org)
        found = self._team(found_org, team)
        found_repo = self._repos.get_repository(found_org.name, repo)
        if found_repo is None:
            raise UsersOrgsTeamsAPIError(
                "repo_not_found", "No such repository.")
        try:
            self._teams.unlink_repo(
                user.id, found_org.id, found.id, found_repo.id,
                source_ip=source_ip)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        return {
            "organization": found_org.name,
            "team": found.name_lower,
            "repository": found_repo.full_name,
            "removed": True,
        }

    # -- organizations: the default permission -------------------
    def get_default_permission(self, header: object,
                               org: object) -> dict:
        """The organization's default repository
        permission, as S-192 reads it: the role
        every member holds at least, and whether
        an owner ever set it. Administration data:
        an org owner or a site admin reads it."""
        identity = self._caller(header, required=True)
        self._require_profile_scope(identity, "read")
        found_org = self._org(org)
        self._require_org_admin(identity, found_org)
        try:
            default = self._defaults.get_default(found_org.id)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        return default_permission_to_dict(default)

    def update_default_permission(self, header: object,
                                  org: object, payload: object, *,
                                  source_ip: str | None = None) -> dict:
        """Set the organization's default repository
        permission, through S-192's own setter: a
        ladder rung, or `none` to clear it; setting
        the value already in effect is the store's
        no-op success. The payload names `role`."""
        body = self._payload(
            payload, _DEFAULT_PATCH_KEYS, required=True)
        if "role" not in body:
            raise UsersOrgsTeamsAPIError(
                "payload_invalid",
                "This call names no field to update.")
        identity = self._caller(header, required=True)
        self._require_profile_scope(identity, "write")
        user = identity.user
        assert user is not None
        found_org = self._org(org)
        try:
            default = self._defaults.set_default(
                user.id, found_org.id, body.get("role"),
                source_ip=source_ip)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        return default_permission_to_dict(default)

    # -- repositories: outside collaborators ----------------------
    def list_collaborators(self, header: object, owner: object,
                           repo: object, *,
                           limit: int = DEFAULT_LIMIT) -> dict:
        """One repository's outside collaborators
        in the list envelope, in username order:
        S-191's own auditable listing. Judged
        through S-190 at the admin rung -- the
        same standing the web's collaborator
        settings ask -- so a missing or
        unadministrable repository is the one
        `repo_not_found`."""
        limit = self._check_limit(limit)
        _identity, auth = self._repo_admin(header, owner, repo)
        try:
            grants = self._collabs.list_for_repo(auth.repository.id)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        items = [collaborator_to_dict(grant) for grant in grants]
        answer = self._envelope("collaborators", items, limit=limit)
        return {"repository": auth.repository.full_name, **answer}

    def add_collaborator(self, header: object, owner: object,
                         repo: object, payload: object, *,
                         source_ip: str | None = None) -> dict:
        """Grant one outside collaborator a ladder
        role on one repository, through S-191's
        own grant: the grantee must stand outside
        the owning world (the store's
        `already_owner` / `already_member` /
        `already_collaborator` name why not), and
        its `repo.collaborator.add` witness is the
        store's. Judged through S-190 at the admin
        rung. The payload names `username` and
        `role`."""
        body = self._payload(
            payload, _COLLABORATOR_ADD_KEYS, required=True)
        identity, auth = self._repo_admin(header, owner, repo)
        user = identity.user
        assert user is not None
        try:
            grant = self._collabs.grant(
                user.id, auth.repository.id, body.get("username"),
                body.get("role"), source_ip=source_ip)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        return collaborator_to_dict(grant)

    def update_collaborator(self, header: object, owner: object,
                            repo: object, username: object,
                            payload: object, *,
                            source_ip: str | None = None) -> dict:
        """Move one outside grant up or down the
        ladder, through S-191's own role change,
        with S-200's last-admin guardrail riding
        inside it as on the web: no grant here is
        the store's `not_collaborator`. The
        payload names `role`."""
        body = self._payload(
            payload, _COLLABORATOR_PATCH_KEYS, required=True)
        if "role" not in body:
            raise UsersOrgsTeamsAPIError(
                "payload_invalid",
                "This call names no field to update.")
        identity, auth = self._repo_admin(header, owner, repo)
        user = identity.user
        assert user is not None
        try:
            grant = self._collabs.set_role(
                user.id, auth.repository.id, username,
                body.get("role"), source_ip=source_ip)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        return collaborator_to_dict(grant)

    def remove_collaborator(self, header: object, owner: object,
                            repo: object, username: object, *,
                            source_ip: str | None = None) -> dict:
        """Revoke one outside grant, through
        S-191's own revocation: the answer is the
        grant that was removed, as data, so a
        script can record exactly what it took
        away."""
        identity, auth = self._repo_admin(header, owner, repo)
        user = identity.user
        assert user is not None
        try:
            removed = self._collabs.revoke(
                user.id, auth.repository.id, username,
                source_ip=source_ip)
        except _STORE_ERRORS as exc:
            raise self._store_error(exc) from None
        return collaborator_to_dict(removed)

    # -- the wire forms -------------------------------------------
    def get_user_json(self, header: object, username: object) -> str:
        return to_json(self.get_user(header, username))

    def list_organizations_json(self, header: object, **kwargs) -> str:
        return to_json(self.list_organizations(header, **kwargs))

    def get_organization_json(self, header: object, org: object) -> str:
        return to_json(self.get_organization(header, org))

    def list_teams_json(self, header: object, org: object,
                        **kwargs) -> str:
        return to_json(self.list_teams(header, org, **kwargs))


def render_users_orgs_teams_api_page() -> str:
    """The users, orgs and teams API, in plain
    words, where a script's author finds it: one
    person's profile; an organization's profile,
    members, teams, team members, team repository
    permissions and default permission; and a
    repository's outside collaborators -- each
    the programmatic face of a capability the web
    already has, judged by the same law, so
    membership and permission administration is
    automatable end-to-end. Every value escaped
    through S-010."""
    parts = [
        "<h1>Users, organizations and teams API</h1>",
        "<p>Scripts work with people and "
        "organizations under /api/v1: GET a user "
        "to read their public profile; GET and "
        "POST the orgs collection to list "
        "organizations and create one; GET and "
        "PATCH one org to read and administer its "
        "profile; GET and POST its members, and "
        "GET, PATCH and DELETE one member, to run "
        "its membership; GET and POST its teams, "
        "and GET and PATCH one team; GET and POST "
        "a team's members and DELETE one; GET and "
        "POST a team's repository links, and PATCH "
        "or DELETE one link to grade or remove its "
        "permission; GET and PATCH the org's "
        "default repository permission; and GET "
        "and POST a repository's outside "
        "collaborators, with PATCH and DELETE on "
        "one grant -- so membership and permission "
        "administration is automatable "
        "end-to-end.</p>",
        "<p>Every call is judged exactly as the "
        "web judges the same act: authentication "
        "resolves through the API door (S-238), "
        "repository administration through the "
        "one permission engine (S-190) at the "
        "admin rung, organization administration "
        "through the membership record the engine "
        "itself reads, a token's scope stands as "
        "a ceiling over it all (the profile family "
        "for this surface), and the act itself "
        "runs through the same store the pages "
        "use -- the last owner cannot be removed "
        "or demoted, a secret team answers exactly "
        "as a missing one, and what the web has "
        "no writer for (a team deletion, an "
        "organization rename) the API does not "
        "invent.</p>",
        "<p>Refusals carry a machine-branchable "
        "reason in the one problem format: "
        "authentication_required when no "
        "credential was sent, credentials_invalid "
        "when one was sent and failed, "
        "insufficient_scope when a token lacks "
        "the scope for the call, org_not_found "
        "for a missing organization, "
        "team_not_found for a missing or invisible "
        "team, no_such_user for a missing account, "
        "and the web stores' own reasons for the "
        "acts they refuse.</p>",
    ]
    return "\n".join(parts)
