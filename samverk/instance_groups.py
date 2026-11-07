"""Instance-wide groups seam (S-203).

Site-level groups share the team machinery (used by
admin policy in Part XVIII).

- **A group is a team at instance scope.** S-187
  built the team inside one organization; a group
  here is the same shape — a named, described,
  ``visible`` / ``secret`` body of members with
  repositories linked to it — lifted to the whole
  instance: it lives in no organization, its slug
  is unique across the instance rather than inside
  one organization, its members are any accounts on
  the instance (there is no organization membership
  to require first), and its repository links may
  name any repository on the instance, whichever
  owner it belongs to. Those scope changes are the
  whole difference; everything else is shared, not
  re-invented (next point).
- **The machinery is S-187/S-188/S-189's own.**
  Names are judged by ``teams.validate_team_name``
  and slugged by ``teams.team_slug``, privacy by
  ``teams.validate_privacy`` and judged for a viewer
  by ``teams.decide_team_visibility`` (a secret
  group is *not there* to anyone but its members
  and site admins — reads answer the uniform
  ``group_not_found``, exactly a secret team's
  ``team_not_found`` law, so existence never leaks),
  descriptions are cleaned by S-187's text law, the
  parent tree is judged by ``team_nesting``'s pure
  ``ancestor_ids`` / ``descendant_ids`` /
  ``would_create_cycle``, and repository grants
  stand on ``team_permissions``' ladder (``ROLES``,
  ``validate_role``, ``higher_role``): a fresh link
  starts at ``read``, a group's *effective*
  permission in a repository is the highest grant
  in its ancestor chain with the granting group
  named, and inheritance flows down, never up —
  S-188's law, word for word, because it is the
  same code judging it.
- **Only site admins manage.** Creating a group,
  changing its description or privacy, managing
  its members, linking repositories, moving ladder
  rungs and setting parents are site-admin acts
  (``not_site_admin`` otherwise; an unknown actor
  is ``no_such_user``). There is no organization
  owner at instance scope to share the guard with:
  the instance's stewards are its admins, and
  Part XVIII's admin policy is built by them. The
  creator is recorded as the group's first member,
  so a fresh group is never an empty shell its
  maker cannot see.
- **The seam Part XVIII builds on.** Admin policy
  never re-derives group membership or grants: it
  asks this module. ``is_effective_member`` answers
  whether a person belongs to a group counting
  inheritance (a direct member of any ancestor is
  an effective member of the group);
  ``effective_groups_for_user`` names every group a
  person effectively belongs to (their direct
  groups plus every descendant of those groups);
  and ``group_role_for_user`` resolves the one
  group-derived ladder role a person holds in a
  repository — the highest effective permission
  across their effective groups, naming the group
  they act through and the group whose grant
  decided it, or ``None`` when no group grants
  them anything there. Policy in Part XVIII names
  groups as subjects through exactly these three
  answers.
- **Audit:** successful changes ride the existing
  ``admin.settings.change`` event (the instance-
  settings door S-0xx's two-factor policy already
  uses; no new taxonomy event — 122 stand: 31 auth
  / 79 repo / 12 admin) with target kind
  ``instance``, the group's slug as target, and
  detail ``{"fields": "instance_groups", "action":
  ...}``; refusals and no-op permission sets write
  nothing and audit nothing.
- **Storage** is migration 79's ``instance_groups``
  (plus its ``parent_group_id`` for nesting),
  ``instance_group_members`` and
  ``instance_group_repositories`` tables (schema 78
  to 79), shaped column-for-column on migration
  70's team tables minus ``org_id``. Teams,
  organizations, accounts and repositories stay
  S-187/S-185/S-025 ground and are only read here.
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .organizations import OrganizationError
from .team_nesting import ancestor_ids, descendant_ids, would_create_cycle
from .team_permissions import ROLES, higher_role, role_word, validate_role
from .teams import (
    PRIVACIES, decide_team_visibility, privacy_word, team_slug,
    validate_privacy, validate_team_name)
from .teams import _clean_description

__all__ = [
    "PRIVACIES", "ROLES", "EffectiveGroupPermission",
    "GroupNestingPreview", "GroupRepoRole", "InstanceGroup",
    "InstanceGroupMembership", "InstanceGroupRepository",
    "InstanceGroupStore", "group_slug",
    "render_group_nesting_preview", "render_group_page",
    "render_group_tree_page", "render_groups_page",
]

# The slug a group name is judged by is a team's slug:
# one canonicalisation for every named body of people.
group_slug = team_slug

_PERMISSION_WORDS = {"read": "Read", "triage": "Triage",
                     "write": "Write", "maintain": "Maintain",
                     "admin": "Admin"}  # S-189 ladder words


@dataclass(frozen=True)
class InstanceGroup:
    id: int
    name: str              # display case
    name_lower: str        # the slug, canonical
    description: str | None
    privacy: str           # visible | secret
    created_by: int
    created_at: int
    updated_at: int
    parent_group_id: int | None = None


@dataclass(frozen=True)
class InstanceGroupMembership:
    group_id: int
    user_id: int
    username: str
    username_lower: str
    added_by: int | None
    created_at: int


@dataclass(frozen=True)
class InstanceGroupRepository:
    group_id: int
    repo_id: int
    owner: str
    name: str
    description: str
    visibility: str
    permission: str = "read"  # the S-189 ladder role on this link


@dataclass(frozen=True)
class EffectiveGroupPermission:
    """One group's effective permission in one
    repository: the highest direct grant in its
    ancestor chain (itself first), and the group
    whose grant decided it — S-189's effective team
    permission, at instance scope."""
    group_id: int
    repo_id: int
    owner: str
    name: str
    permission: str
    granted_by_group_id: int
    granted_by_group_name: str


@dataclass(frozen=True)
class GroupRepoRole:
    """The seam's answer for one person in one
    repository: the ladder role their groups grant
    them, the group they act through, and the group
    whose grant decided it."""
    user_id: int
    repo_id: int
    owner: str
    name: str
    role: str
    via_group_id: int
    via_group_name: str
    granted_by_group_id: int
    granted_by_group_name: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass(frozen=True)
class GroupNestingPreview:
    """The effect of a proposed parent change,
    computed before anything is saved — S-188's
    nesting preview, at instance scope."""
    group_id: int
    group_name: str
    current_parent_id: int | None
    proposed_parent_id: int | None
    allowed: bool
    reason: str | None          # refusal reason when not allowed
    message: str                # the law said in plain words
    ancestors_after: tuple[str, ...]     # group names, nearest first
    inherited_members: tuple[str, ...]   # usernames gained via ancestors
    inherited_repos: tuple[str, ...]     # "owner/name" gained via ancestors
    lost_members: tuple[str, ...]        # usernames no longer inherited
    lost_repos: tuple[str, ...]          # "owner/name" no longer inherited


def _row_to_group(row: sqlite3.Row) -> InstanceGroup:
    return InstanceGroup(
        id=row["id"], name=row["name"],
        name_lower=row["name_lower"],
        description=row["description"], privacy=row["privacy"],
        created_by=row["created_by"], created_at=row["created_at"],
        updated_at=row["updated_at"],
        parent_group_id=row["parent_group_id"])


_MEMBER_SELECT = (
    "SELECT m.group_id AS group_id, m.user_id AS user_id,"
    " u.username AS username,"
    " u.username_lower AS username_lower,"
    " m.added_by AS added_by, m.created_at AS created_at"
    " FROM instance_group_members m JOIN users u ON u.id = m.user_id")

_REPO_SELECT = (
    "SELECT l.group_id AS group_id, r.id AS repo_id,"
    " r.owner AS owner, r.name AS name,"
    " r.description AS description, r.visibility AS visibility,"
    " l.permission AS permission"
    " FROM instance_group_repositories l"
    " JOIN repositories r ON r.id = l.repo_id")


class InstanceGroupStore:
    def __init__(
        self, conn: sqlite3.Connection, accounts: AccountStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._audit = audit
        self._now = time_fn

    # -- guards -----------------------------------------
    def _require_user(self, user_id: int) -> User:
        user = self._accounts.get_by_id(user_id)
        if user is None:
            raise OrganizationError(
                "no_such_user", "No such account.")
        return user

    def _require_admin(self, actor_id: int) -> User:
        actor = self._require_user(actor_id)
        if not actor.is_admin:
            raise OrganizationError(
                "not_site_admin",
                "Only a site admin can manage "
                "instance-wide groups.")
        return actor

    def _resolve_target(self, target: object) -> User:
        user: User | None = None
        if isinstance(target, int):
            user = self._accounts.get_by_id(target)
        elif isinstance(target, str):
            user = self._accounts.get_by_username(target)
        if user is None:
            raise OrganizationError(
                "no_such_user", "No such account.")
        return user

    def _require_group(self, group_id: int) -> InstanceGroup:
        row = self._conn.execute(
            "SELECT * FROM instance_groups WHERE id = ?",
            (group_id,)).fetchone()
        if row is None:
            raise OrganizationError(
                "group_not_found", "No such group.")
        return _row_to_group(row)

    def _require_repo_row(self, repo_id: int) -> sqlite3.Row:
        repo = self._conn.execute(
            "SELECT * FROM repositories WHERE id = ?",
            (repo_id,)).fetchone()
        if repo is None:
            raise OrganizationError(
                "repo_not_found", "No such repository.")
        return repo

    def _audit_change(self, actor: User, action: str,
                      group: InstanceGroup,
                      extra: dict | None = None,
                      source_ip: str | None = None):
        if self._audit is None:
            return
        detail: dict = {"fields": "instance_groups",
                        "action": action,
                        "group": group.name_lower}
        if extra:
            detail.update(extra)
        self._audit.append(
            actor_kind="user", actor_id=actor.id,
            action="admin.settings.change",
            target_kind="instance",
            target_id=group.name_lower,
            outcome="success", source_ip=source_ip,
            detail=detail)

    # -- creation and profile -----------------------------
    def create_group(
        self, actor_id: int, name: object, *,
        description: object = None, privacy: object = "visible",
        parent_group_id: int | None = None,
        source_ip: str | None = None,
    ) -> InstanceGroup:
        actor = self._require_admin(actor_id)
        display, slug = validate_team_name(name)
        clean_privacy = validate_privacy(privacy)
        clean_desc = _clean_description(description)
        if parent_group_id is not None:
            self._require_group(parent_group_id)
        clash = self._conn.execute(
            "SELECT id FROM instance_groups WHERE name_lower = ?",
            (slug,)).fetchone()
        if clash is not None:
            raise OrganizationError(
                "group_taken",
                f"{display} is already a group on this instance.")
        now = int(self._now())
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO instance_groups (name, name_lower,"
                " description, privacy, parent_group_id,"
                " created_by, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (display, slug, clean_desc, clean_privacy,
                 parent_group_id, actor.id, now, now))
            group_id = int(cur.lastrowid)
            self._conn.execute(
                "INSERT INTO instance_group_members (group_id,"
                " user_id, added_by, created_at)"
                " VALUES (?, ?, ?, ?)",
                (group_id, actor.id, actor.id, now))
        group = self._require_group(group_id)
        self._audit_change(actor, "create", group,
                           source_ip=source_ip)
        return group

    def update_group(
        self, actor_id: int, group_id: int, *,
        description: object = None, privacy: object = None,
        source_ip: str | None = None,
    ) -> InstanceGroup:
        """Set the description (a submitted empty value
        clears it, S-187's profile law) and, when a
        privacy is given, the privacy. Site admin only."""
        actor = self._require_admin(actor_id)
        group = self._require_group(group_id)
        clean_desc = _clean_description(description)
        clean_privacy = (group.privacy if privacy is None
                         else validate_privacy(privacy))
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "UPDATE instance_groups SET description = ?,"
                " privacy = ?, updated_at = ? WHERE id = ?",
                (clean_desc, clean_privacy, now, group.id))
        updated = self._require_group(group_id)
        self._audit_change(actor, "update", updated,
                           source_ip=source_ip)
        return updated

    # -- reads --------------------------------------------
    def get_group(self, group_id: int) -> InstanceGroup:
        return self._require_group(group_id)

    def get_group_by_name(self, name: object) -> InstanceGroup | None:
        if not isinstance(name, str):
            return None
        row = self._conn.execute(
            "SELECT * FROM instance_groups WHERE name_lower = ?",
            (team_slug(name),)).fetchone()
        return _row_to_group(row) if row else None

    def list_groups(self) -> list[InstanceGroup]:
        rows = self._conn.execute(
            "SELECT * FROM instance_groups"
            " ORDER BY name_lower").fetchall()
        return [_row_to_group(r) for r in rows]

    def is_group_member(self, user_id: int, group_id: int) -> bool:
        row = self._conn.execute(
            "SELECT user_id FROM instance_group_members"
            " WHERE group_id = ? AND user_id = ?",
            (group_id, user_id)).fetchone()
        return row is not None

    def _viewer_may_see(self, viewer_id: int | None,
                        group: InstanceGroup) -> bool:
        if group.privacy == "visible":
            return True
        if viewer_id is None:
            return False
        viewer = self._accounts.get_by_id(viewer_id)
        is_admin = bool(viewer is not None and viewer.is_admin)
        return decide_team_visibility(
            group.privacy, self.is_group_member(viewer_id, group.id),
            is_admin)

    def get_group_for_viewer(self, viewer_id: int | None,
                             group_id: int) -> InstanceGroup:
        """The group as this viewer may know it: a secret
        group the viewer may not see is group_not_found,
        exactly as if it did not exist."""
        group = self.get_group(group_id)
        if not self._viewer_may_see(viewer_id, group):
            raise OrganizationError(
                "group_not_found", "No such group.")
        return group

    def list_groups_for_viewer(
            self, viewer_id: int | None) -> list[InstanceGroup]:
        return [g for g in self.list_groups()
                if self._viewer_may_see(viewer_id, g)]

    # -- group members --------------------------------------
    def add_member(
        self, actor_id: int, group_id: int,
        target: object, source_ip: str | None = None,
    ) -> InstanceGroupMembership:
        actor = self._require_admin(actor_id)
        group = self._require_group(group_id)
        target_user = self._resolve_target(target)
        if self.is_group_member(target_user.id, group.id):
            raise OrganizationError(
                "already_group_member",
                "That person is already a member of this group.")
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "INSERT INTO instance_group_members (group_id,"
                " user_id, added_by, created_at)"
                " VALUES (?, ?, ?, ?)",
                (group.id, target_user.id, actor.id, now))
        self._audit_change(
            actor, "add_member", group,
            extra={"target": target_user.username_lower},
            source_ip=source_ip)
        result = self.get_membership(group.id, target_user.id)
        assert result is not None
        return result

    def remove_member(
        self, actor_id: int, group_id: int,
        target: object, source_ip: str | None = None,
    ) -> None:
        actor = self._require_admin(actor_id)
        group = self._require_group(group_id)
        target_user = self._resolve_target(target)
        if not self.is_group_member(target_user.id, group.id):
            raise OrganizationError(
                "not_group_member",
                "That person is not a member of this group.")
        with self._conn:
            self._conn.execute(
                "DELETE FROM instance_group_members"
                " WHERE group_id = ? AND user_id = ?",
                (group.id, target_user.id))
        self._audit_change(
            actor, "remove_member", group,
            extra={"target": target_user.username_lower},
            source_ip=source_ip)

    def get_membership(self, group_id: int,
                       user_id: int) -> InstanceGroupMembership | None:
        row = self._conn.execute(
            _MEMBER_SELECT + " WHERE m.group_id = ? AND m.user_id = ?",
            (group_id, user_id)).fetchone()
        if row is None:
            return None
        return InstanceGroupMembership(
            group_id=row["group_id"], user_id=row["user_id"],
            username=row["username"],
            username_lower=row["username_lower"],
            added_by=row["added_by"], created_at=row["created_at"])

    def list_members(self, group_id: int) -> list[InstanceGroupMembership]:
        self._require_group(group_id)
        rows = self._conn.execute(
            _MEMBER_SELECT + " WHERE m.group_id = ?"
            " ORDER BY u.username_lower", (group_id,)).fetchall()
        return [
            InstanceGroupMembership(
                group_id=r["group_id"], user_id=r["user_id"],
                username=r["username"],
                username_lower=r["username_lower"],
                added_by=r["added_by"], created_at=r["created_at"])
            for r in rows]

    def groups_for_user(self, user_id: int) -> list[InstanceGroup]:
        """The groups the person is a *direct* member of,
        in slug order. Effective membership (counting
        inheritance) is ``effective_groups_for_user``."""
        self._require_user(user_id)
        rows = self._conn.execute(
            "SELECT g.* FROM instance_groups g"
            " JOIN instance_group_members m ON m.group_id = g.id"
            " WHERE m.user_id = ? ORDER BY g.name_lower",
            (user_id,)).fetchall()
        return [_row_to_group(r) for r in rows]

    # -- linked repositories ----------------------------------
    def link_repo(
        self, actor_id: int, group_id: int,
        repo_id: int, source_ip: str | None = None,
    ) -> InstanceGroupRepository:
        actor = self._require_admin(actor_id)
        group = self._require_group(group_id)
        repo = self._require_repo_row(repo_id)
        clash = self._conn.execute(
            "SELECT group_id FROM instance_group_repositories"
            " WHERE group_id = ? AND repo_id = ?",
            (group.id, repo_id)).fetchone()
        if clash is not None:
            raise OrganizationError(
                "already_linked",
                "That repository is already linked to this group.")
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "INSERT INTO instance_group_repositories (group_id,"
                " repo_id, added_by, created_at)"
                " VALUES (?, ?, ?, ?)",
                (group.id, repo_id, actor.id, now))
        self._audit_change(
            actor, "link_repo", group,
            extra={"repo": f"{repo['owner_lower']}/{repo['name_lower']}"},
            source_ip=source_ip)
        result = self.get_link(group.id, repo_id)
        assert result is not None
        return result

    def unlink_repo(
        self, actor_id: int, group_id: int,
        repo_id: int, source_ip: str | None = None,
    ) -> None:
        actor = self._require_admin(actor_id)
        group = self._require_group(group_id)
        self._require_repo_row(repo_id)
        if self.get_link(group.id, repo_id) is None:
            raise OrganizationError(
                "not_linked",
                "That repository is not linked to this group.")
        with self._conn:
            self._conn.execute(
                "DELETE FROM instance_group_repositories"
                " WHERE group_id = ? AND repo_id = ?",
                (group.id, repo_id))
        self._audit_change(
            actor, "unlink_repo", group, source_ip=source_ip)

    def get_link(self, group_id: int,
                 repo_id: int) -> InstanceGroupRepository | None:
        row = self._conn.execute(
            _REPO_SELECT + " WHERE l.group_id = ? AND l.repo_id = ?",
            (group_id, repo_id)).fetchone()
        if row is None:
            return None
        return InstanceGroupRepository(
            group_id=row["group_id"], repo_id=row["repo_id"],
            owner=row["owner"], name=row["name"],
            description=row["description"],
            visibility=row["visibility"],
            permission=row["permission"] or "read")

    def list_repos(self, group_id: int) -> list[InstanceGroupRepository]:
        self._require_group(group_id)
        rows = self._conn.execute(
            _REPO_SELECT + " WHERE l.group_id = ?"
            " ORDER BY r.name_lower", (group_id,)).fetchall()
        return [
            InstanceGroupRepository(
                group_id=r["group_id"], repo_id=r["repo_id"],
                owner=r["owner"], name=r["name"],
                description=r["description"],
                visibility=r["visibility"],
                permission=r["permission"] or "read")
            for r in rows]

    def set_permission(
        self, actor_id: int, group_id: int, repo_id: int,
        role: object, source_ip: str | None = None,
    ) -> InstanceGroupRepository:
        """Move one linked group's rung on S-189's ladder
        for one repository. Setting the rung already held
        is a no-op success that writes nothing and audits
        nothing (S-189's law, shared)."""
        actor = self._require_admin(actor_id)
        group = self._require_group(group_id)
        repo = self._require_repo_row(repo_id)
        clean_role = validate_role(role)
        link = self.get_link(group.id, repo_id)
        if link is None:
            raise OrganizationError(
                "not_linked",
                "That repository is not linked to this group.")
        if link.permission == clean_role:
            return link
        with self._conn:
            self._conn.execute(
                "UPDATE instance_group_repositories"
                " SET permission = ?"
                " WHERE group_id = ? AND repo_id = ?",
                (clean_role, group.id, repo_id))
        self._audit_change(
            actor, "set_permission", group,
            extra={"repo": f"{repo['owner_lower']}/{repo['name_lower']}",
                   "role": clean_role},
            source_ip=source_ip)
        result = self.get_link(group.id, repo_id)
        assert result is not None
        return result

    # -- nesting (S-188's tree, at instance scope) ------------
    def _parent_map(self) -> dict[int, int | None]:
        rows = self._conn.execute(
            "SELECT id, parent_group_id FROM instance_groups").fetchall()
        return {r["id"]: r["parent_group_id"] for r in rows}

    def _judge_parent(self, group: InstanceGroup,
                      parent_id: int | None) -> InstanceGroup | None:
        """Raise on an unlawful parent; return the parent
        group (or None for a root) when lawful. The cycle
        law itself is team_nesting.would_create_cycle."""
        if parent_id is None:
            return None
        if parent_id == group.id:
            raise OrganizationError(
                "group_parent_is_self",
                "A group cannot be its own parent.")
        row = self._conn.execute(
            "SELECT * FROM instance_groups WHERE id = ?",
            (parent_id,)).fetchone()
        if row is None:
            raise OrganizationError(
                "parent_not_found", "No such parent group.")
        if would_create_cycle(self._parent_map(), group.id, parent_id):
            raise OrganizationError(
                "group_parent_cycle",
                "That parent would make the group its own "
                "ancestor; nested groups cannot form a cycle.")
        return _row_to_group(row)

    def get_parent(self, group_id: int) -> InstanceGroup | None:
        group = self._require_group(group_id)
        if group.parent_group_id is None:
            return None
        return self._require_group(group.parent_group_id)

    def list_children(self, group_id: int) -> list[InstanceGroup]:
        self._require_group(group_id)
        return [g for g in self.list_groups()
                if g.parent_group_id == group_id]

    def ancestors(self, group_id: int) -> list[InstanceGroup]:
        self._require_group(group_id)
        parent_of = self._parent_map()
        by_id = {g.id: g for g in self.list_groups()}
        return [by_id[i] for i in ancestor_ids(parent_of, group_id)
                if i in by_id]

    def descendants(self, group_id: int) -> list[InstanceGroup]:
        self._require_group(group_id)
        parent_of = self._parent_map()
        by_id = {g.id: g for g in self.list_groups()}
        return [by_id[i] for i in descendant_ids(parent_of, group_id)
                if i in by_id]

    def _effective(self, group_id: int,
                   parent_of: dict[int, int | None]):
        """(members, repos) over a stated parent map: the
        group's own first, then each ancestor's, nearest
        first, each entry named once — S-188's effective
        set, judged over groups."""
        chain = [group_id] + ancestor_ids(parent_of, group_id)
        members: list[InstanceGroupMembership] = []
        seen_users: set[int] = set()
        repos: list[InstanceGroupRepository] = []
        seen_repos: set[int] = set()
        for gid in chain:
            for m in self.list_members(gid):
                if m.user_id not in seen_users:
                    seen_users.add(m.user_id)
                    members.append(m)
            for r in self.list_repos(gid):
                if r.repo_id not in seen_repos:
                    seen_repos.add(r.repo_id)
                    repos.append(r)
        return members, repos

    def effective_members(
            self, group_id: int) -> list[InstanceGroupMembership]:
        self._require_group(group_id)
        members, _ = self._effective(group_id, self._parent_map())
        return members

    def effective_repos(
            self, group_id: int) -> list[InstanceGroupRepository]:
        self._require_group(group_id)
        _, repos = self._effective(group_id, self._parent_map())
        return repos

    def preview_parent_change(
        self, group_id: int, parent_id: int | None,
    ) -> GroupNestingPreview:
        """The whole effect of a proposed parent change,
        computed as a pure read: nothing is written and
        nothing is audited. An unlawful proposal is
        reported in the preview, not raised."""
        group = self._require_group(group_id)
        current_map = self._parent_map()
        cur_members, cur_repos = self._effective(group_id, current_map)
        cur_member_names = {m.username for m in cur_members}
        cur_repo_names = {f"{r.owner}/{r.name}" for r in cur_repos}
        own_member_names = {m.username for m in self.list_members(group_id)}
        own_repo_names = {f"{r.owner}/{r.name}"
                          for r in self.list_repos(group_id)}
        try:
            self._judge_parent(group, parent_id)
        except OrganizationError as exc:
            return GroupNestingPreview(
                group_id=group.id, group_name=group.name,
                current_parent_id=group.parent_group_id,
                proposed_parent_id=parent_id,
                allowed=False, reason=exc.reason,
                message=str(exc),
                ancestors_after=(), inherited_members=(),
                inherited_repos=(), lost_members=(),
                lost_repos=())
        proposed_map = dict(current_map)
        proposed_map[group_id] = parent_id
        new_members, new_repos = self._effective(group_id, proposed_map)
        new_member_names = {m.username for m in new_members}
        new_repo_names = {f"{r.owner}/{r.name}" for r in new_repos}
        by_id = {g.id: g for g in self.list_groups()}
        ancestors_after = tuple(
            by_id[i].name for i in ancestor_ids(proposed_map, group_id)
            if i in by_id)
        if parent_id is None:
            message = ("The group would become a root group and "
                       "inherit nothing.")
        else:
            parent = by_id[parent_id]
            message = (f"The group would sit under {parent.name} and "
                       "inherit its members and repository links, "
                       "and those of every ancestor above it.")
        return GroupNestingPreview(
            group_id=group.id, group_name=group.name,
            current_parent_id=group.parent_group_id,
            proposed_parent_id=parent_id,
            allowed=True, reason=None, message=message,
            ancestors_after=ancestors_after,
            inherited_members=tuple(sorted(
                new_member_names - own_member_names)),
            inherited_repos=tuple(sorted(
                new_repo_names - own_repo_names)),
            lost_members=tuple(sorted(
                (cur_member_names - own_member_names)
                - new_member_names)),
            lost_repos=tuple(sorted(
                (cur_repo_names - own_repo_names)
                - new_repo_names)))

    def set_parent(
        self, actor_id: int, group_id: int,
        parent_id: int | None, source_ip: str | None = None,
    ) -> InstanceGroup:
        """Set (or, with None, clear) a group's parent.
        Site admin only; the cycle and self-parent laws
        are re-judged here, so a stale preview can never
        save an unlawful tree."""
        actor = self._require_admin(actor_id)
        group = self._require_group(group_id)
        parent = self._judge_parent(group, parent_id)
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "UPDATE instance_groups SET parent_group_id = ?,"
                " updated_at = ? WHERE id = ?",
                (parent_id, now, group.id))
        updated = self._require_group(group_id)
        self._audit_change(
            actor,
            "clear_parent" if parent_id is None else "set_parent",
            updated,
            extra={"parent": parent.name_lower if parent else None},
            source_ip=source_ip)
        return updated

    # -- effective permission (S-189's ladder over the tree) ---
    def effective_permission(
        self, group_id: int, repo_id: int,
    ) -> EffectiveGroupPermission | None:
        """The group's effective ladder role in one
        repository: the highest direct grant in its
        ancestor chain, its own grant winning a tie,
        and the granting group named. None when no
        group in the chain is linked to the repository."""
        self._require_group(group_id)
        repo = self._require_repo_row(repo_id)
        chain = [group_id] + ancestor_ids(self._parent_map(), group_id)
        best: EffectiveGroupPermission | None = None
        for gid in chain:
            link = self.get_link(gid, repo_id)
            if link is None:
                continue
            if best is None or higher_role(
                    best.permission, link.permission) == link.permission \
                    and link.permission != best.permission:
                granter = self._require_group(gid)
                best = EffectiveGroupPermission(
                    group_id=group_id, repo_id=repo_id,
                    owner=repo["owner"], name=repo["name"],
                    permission=link.permission,
                    granted_by_group_id=gid,
                    granted_by_group_name=granter.name)
        return best

    # -- the seam for Part XVIII (admin policy) ------------
    def is_effective_member(self, user_id: int,
                            group_id: int) -> bool:
        """Whether the person belongs to the group
        counting inheritance: a direct member of the
        group or of any ancestor above it is an
        effective member of the group."""
        self._require_user(user_id)
        self._require_group(group_id)
        return any(m.user_id == user_id
                   for m in self.effective_members(group_id))

    def effective_groups_for_user(
            self, user_id: int) -> list[InstanceGroup]:
        """Every group the person effectively belongs
        to: their direct groups plus every descendant
        of those groups, in slug order, each named
        once."""
        self._require_user(user_id)
        parent_of = self._parent_map()
        found: set[int] = set()
        for group in self.groups_for_user(user_id):
            found.add(group.id)
            found.update(descendant_ids(parent_of, group.id))
        return [g for g in self.list_groups() if g.id in found]

    def group_role_for_user(
        self, user_id: int, repo_id: int,
    ) -> GroupRepoRole | None:
        """The one group-derived ladder role the person
        holds in the repository: the highest effective
        permission across their effective groups, naming
        the group they act through and the group whose
        grant decided it; on a tie the first group in
        slug order stands. None when no group grants
        them anything there."""
        self._require_user(user_id)
        repo = self._require_repo_row(repo_id)
        best: GroupRepoRole | None = None
        for group in self.effective_groups_for_user(user_id):
            eff = self.effective_permission(group.id, repo_id)
            if eff is None:
                continue
            if best is None or higher_role(
                    best.role, eff.permission) == eff.permission \
                    and eff.permission != best.role:
                best = GroupRepoRole(
                    user_id=user_id, repo_id=repo_id,
                    owner=repo["owner"], name=repo["name"],
                    role=eff.permission,
                    via_group_id=group.id,
                    via_group_name=group.name,
                    granted_by_group_id=eff.granted_by_group_id,
                    granted_by_group_name=eff.granted_by_group_name)
        return best


def render_group_page(group: InstanceGroup,
                      members: list[InstanceGroupMembership],
                      repos: list[InstanceGroupRepository]) -> str:
    """The group page: name, description and privacy
    in words, then the members and the linked
    repositories, each with its S-189 permission —
    every value escaped through S-010."""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{escape_html_text(group.name)} — Samverk</title></head>",
        "<body>",
        f"<h1>{escape_html_text(group.name)}</h1>",
        '<p class="group-scope">An instance-wide group on '
        "this Samverk instance</p>",
    ]
    if group.description:
        desc = escape_html_text(group.description).replace(
            "\n", "<br>\n")
        parts.append(f'<p class="description">{desc}</p>')
    if group.privacy == "secret":
        parts.append(
            "<p>Privacy: Secret — only this group's members "
            "can see this group.</p>")
    else:
        parts.append(
            "<p>Privacy: Visible — anyone can see this group.</p>")
    parts.append("<h2>Members</h2>")
    if members:
        parts.append("<ul>")
        for member in members:
            parts.append(
                f"<li>{escape_html_text(member.username)}</li>")
        parts.append("</ul>")
    else:
        parts.append("<p>No members yet.</p>")
    parts.append("<h2>Repositories</h2>")
    if repos:
        parts.append("<ul>")
        for repo in repos:
            label = escape_html_text(f"{repo.owner}/{repo.name}")
            word = _PERMISSION_WORDS.get(repo.permission,
                                         repo.permission)
            parts.append(
                f"<li>{label} — {escape_html_text(word)}</li>")
        parts.append("</ul>")
    else:
        parts.append(
            "<p>No repositories are linked to this group "
            "yet.</p>")
    parts.append(
        "<p>Repository permissions follow the S-189 ladder "
        "— read / triage / write / maintain / admin — "
        "applied per repository per group; a fresh link "
        "starts at Read.</p>")
    parts.append("</body></html>")
    return "\n".join(parts)


def render_groups_page(groups: list[InstanceGroup]) -> str:
    """The instance-wide groups page: every group the
    caller was given (already viewer-filtered by the
    store), with its privacy in a word and its
    description, escaped through S-010."""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        "<title>Groups — Samverk</title></head>",
        "<body>",
        "<h1>Instance-wide groups</h1>",
    ]
    if groups:
        parts.append("<ul>")
        for group in groups:
            line = (f"{escape_html_text(group.name)} — "
                    f"{escape_html_text(privacy_word(group.privacy))}")
            if group.description:
                line += f" — {escape_html_text(group.description)}"
            parts.append(f"<li>{line}</li>")
        parts.append("</ul>")
    else:
        parts.append("<p>No groups yet.</p>")
    parts.append("</body></html>")
    return "\n".join(parts)


def render_group_nesting_preview(preview: GroupNestingPreview) -> str:
    """The before-saving page: the proposed parent, the
    ancestor chain it would create, and exactly which
    members and repositories would be inherited or
    lost — every value escaped through S-010."""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        "<title>Nested groups — preview — Samverk</title></head>",
        "<body>",
        f"<h1>Before you save: {escape_html_text(preview.group_name)}</h1>",
        f"<p>{escape_html_text(preview.message)}</p>",
    ]
    if not preview.allowed:
        parts.append(
            "<p>This change cannot be saved: "
            f"{escape_html_text(preview.message)}</p>")
        parts.append("</body></html>")
        return "\n".join(parts)
    parts.append("<h2>Ancestors after this change</h2>")
    if preview.ancestors_after:
        parts.append("<ul>")
        for name in preview.ancestors_after:
            parts.append(f"<li>{escape_html_text(name)}</li>")
        parts.append("</ul>")
    else:
        parts.append("<p>None — the group would be a root group.</p>")
    parts.append("<h2>Members inherited</h2>")
    if preview.inherited_members:
        parts.append("<ul>")
        for name in preview.inherited_members:
            parts.append(f"<li>{escape_html_text(name)}</li>")
        parts.append("</ul>")
    else:
        parts.append("<p>No members would be inherited.</p>")
    parts.append("<h2>Repositories inherited</h2>")
    if preview.inherited_repos:
        parts.append("<ul>")
        for name in preview.inherited_repos:
            parts.append(f"<li>{escape_html_text(name)}</li>")
        parts.append("</ul>")
    else:
        parts.append("<p>No repositories would be inherited.</p>")
    if preview.lost_members or preview.lost_repos:
        parts.append("<h2>No longer inherited</h2>")
        parts.append("<ul>")
        for name in preview.lost_members + preview.lost_repos:
            parts.append(f"<li>{escape_html_text(name)}</li>")
        parts.append("</ul>")
    parts.append(
        "<p>Nothing has been saved yet. This preview shows "
        "the inheritance exactly as saving would apply it: "
        "members and repository links flow down from "
        "ancestors, never up.</p>")
    parts.append("</body></html>")
    return "\n".join(parts)


def render_group_tree_page(groups: list[InstanceGroup]) -> str:
    """The instance's group tree: roots first, each
    child indented under its parent, with the
    inheritance law stated in plain words — every
    value escaped through S-010."""
    by_id = {g.id: g for g in groups}
    children: dict[int, list[InstanceGroup]] = {}
    roots: list[InstanceGroup] = []
    for group in groups:
        if group.parent_group_id is not None and group.parent_group_id in by_id:
            children.setdefault(group.parent_group_id, []).append(group)
        else:
            roots.append(group)
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        "<title>Group tree — Samverk</title></head>",
        "<body>",
        "<h1>Group tree</h1>",
        "<p>A child group inherits the members and "
        "repository links of every ancestor above it. "
        "Inheritance flows down, never up.</p>",
    ]

    def _walk(group: InstanceGroup, depth: int, seen: set[int]):
        if group.id in seen:
            return
        seen.add(group.id)
        indent = "&nbsp;&nbsp;" * depth
        parts.append(
            f"<p>{indent}{escape_html_text(group.name)}</p>")
        for child in sorted(children.get(group.id, []),
                            key=lambda g: g.name_lower):
            _walk(child, depth + 1, seen)

    if roots:
        for root in sorted(roots, key=lambda g: g.name_lower):
            _walk(root, 0, set())
    else:
        parts.append("<p>No groups yet.</p>")
    parts.append("</body></html>")
    return "\n".join(parts)
