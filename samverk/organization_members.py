"""Org membership (S-186).

Owners and members of an organization; the last
owner cannot leave or be removed.

- **Two roles only.** An organization member is an
  ``owner`` or a ``member`` (``ROLES``); anything
  else is refused ``role_invalid`` by the pure
  ``validate_role``. The creator is the founding
  owner: the first membership touch on an
  organization with no membership rows yet seeds
  ``created_by`` as owner, idempotently, so S-185
  organizations gain their founding owner here and
  never twice.
- **The last-owner invariant is the headline law.**
  Removing the last owner, the last owner leaving,
  and demoting the last owner are all refused with
  reason ``last_owner`` and change nothing. The
  invariant is decided by the pure helpers
  ``decide_removal`` / ``decide_role_change`` (a
  refusal reason or ``None``) as well as enforced
  through the store, so it is proven as a pure rule
  and as lived behaviour.
- **Who may change membership.** Only an org owner
  or a site admin may add, remove, or set a role;
  any other actor is refused ``not_org_owner``. A
  member may leave on their own behalf. The target
  of an add must be a real account (an id or a
  username both resolve); an unknown org is
  ``org_not_found`` and an unknown actor or target
  account is ``no_such_user``. Adding someone who
  is already a member is ``already_member``;
  removing, leaving, or re-roling a non-member is
  ``not_a_member``.
- **Setting a role to the role already held** is a
  no-op success: nothing changes and nothing is
  audited (there was no change to witness).
- **Audit:** successful changes ride the existing
  ``auth.organization.update`` event (no new
  taxonomy event — 122 events stand) with detail
  ``{"fields": "members", "action": ...}``;
  refusals write nothing and audit nothing.
- **Storage** is migration 69's
  ``organization_members`` table (schema 68 to 69):
  one row per (organization, user) pair.
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .organizations import Organization, OrganizationError

__all__ = [
    "ROLES", "OrgMembership", "OrgMembershipStore",
    "decide_removal", "decide_role_change",
    "render_members_page", "role_word", "validate_role",
]

ROLES = frozenset({"owner", "member"})

_ROLE_WORDS = {"owner": "Owner", "member": "Member"}


def validate_role(role: object) -> str:
    """Return the canonical role or refuse plainly."""
    if isinstance(role, str) and role.strip().lower() in ROLES:
        return role.strip().lower()
    raise OrganizationError(
        "role_invalid",
        "A member's role is owner or member.")


def role_word(role: str) -> str:
    """The role said in a word a person reads."""
    return _ROLE_WORDS.get(role, role)


def decide_removal(member_role: str | None,
                   owner_count: int) -> str | None:
    """Pure last-owner rule for removals and leaves:
    the refusal reason, or None when allowed."""
    if member_role == "owner" and owner_count <= 1:
        return "last_owner"
    return None


def decide_role_change(current_role: str | None,
                       new_role: str,
                       owner_count: int) -> str | None:
    """Pure last-owner rule for role changes: demoting
    the last owner is refused; everything else passes."""
    if (current_role == "owner" and new_role == "member"
            and owner_count <= 1):
        return "last_owner"
    return None


@dataclass(frozen=True)
class OrgMembership:
    org_id: int
    user_id: int
    username: str
    username_lower: str
    role: str
    added_by: int | None
    created_at: int
    updated_at: int


def _row_to_membership(row: sqlite3.Row) -> OrgMembership:
    return OrgMembership(
        org_id=row["org_id"], user_id=row["user_id"],
        username=row["username"],
        username_lower=row["username_lower"],
        role=row["role"], added_by=row["added_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"])

_MEMBER_SELECT = (
    "SELECT m.org_id AS org_id, m.user_id AS user_id,"
    " u.username AS username,"
    " u.username_lower AS username_lower,"
    " m.role AS role, m.added_by AS added_by,"
    " m.created_at AS created_at,"
    " m.updated_at AS updated_at"
    " FROM organization_members m"
    " JOIN users u ON u.id = m.user_id")


class OrgMembershipStore:
    def __init__(
        self, conn: sqlite3.Connection, accounts: AccountStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._audit = audit
        self._now = time_fn

    # -- org / user guards -----------------------------
    def _require_org_row(self, org_id: int) -> sqlite3.Row:
        row = self._conn.execute(
            "SELECT * FROM organizations WHERE id = ?",
            (org_id,)).fetchone()
        if row is None:
            raise OrganizationError(
                "org_not_found", "No such organization.")
        return row

    def _require_user(self, user_id: int) -> User:
        user = self._accounts.get_by_id(user_id)
        if user is None:
            raise OrganizationError(
                "no_such_user", "No such account.")
        return user

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

    # -- founding owner --------------------------------
    def _ensure_founding_owner(self, org_row: sqlite3.Row):
        """Seed the creator as owner when the org has
        no membership rows yet. Idempotent: once any
        row exists this writes nothing."""
        count = self._conn.execute(
            "SELECT COUNT(*) c FROM organization_members"
            " WHERE org_id = ?", (org_row["id"],)).fetchone()["c"]
        if int(count) > 0:
            return
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO organization_members"
                " (org_id, user_id, role, added_by,"
                " created_at, updated_at)"
                " VALUES (?, ?, 'owner', ?, ?, ?)",
                (org_row["id"], org_row["created_by"],
                 org_row["created_by"], now, now))

    def _raw_role(self, user_id: int, org_id: int) -> str | None:
        row = self._conn.execute(
            "SELECT role FROM organization_members"
            " WHERE org_id = ? AND user_id = ?",
            (org_id, user_id)).fetchone()
        return row["role"] if row else None

    def _require_owner_or_admin(self, actor_id: int,
                                org_row: sqlite3.Row) -> User:
        actor = self._require_user(actor_id)
        if actor.is_admin:
            return actor
        if self._raw_role(actor.id, org_row["id"]) != "owner":
            raise OrganizationError(
                "not_org_owner",
                "Only an organization owner or a site admin "
                "can change this organization's membership.")
        return actor

    def _audit_change(self, actor: User, org_row: sqlite3.Row,
                      action: str, target: User,
                      role: str | None = None,
                      source_ip: str | None = None):
        if self._audit is None:
            return
        detail: dict = {"fields": "members", "action": action,
                        "target": target.username_lower}
        if role is not None:
            detail["role"] = role
        self._audit.append(
            actor_kind="user", actor_id=actor.id,
            action="auth.organization.update",
            target_kind="organization",
            target_id=org_row["name_lower"],
            outcome="success", source_ip=source_ip,
            detail=detail)

    # -- reads ------------------------------------------
    def role_for(self, user_id: int, org_id: int) -> str | None:
        org_row = self._require_org_row(org_id)
        self._ensure_founding_owner(org_row)
        return self._raw_role(user_id, org_id)

    def is_owner(self, user_id: int, org_id: int) -> bool:
        return self.role_for(user_id, org_id) == "owner"

    def is_member(self, user_id: int, org_id: int) -> bool:
        return self.role_for(user_id, org_id) is not None

    def count_owners(self, org_id: int) -> int:
        org_row = self._require_org_row(org_id)
        self._ensure_founding_owner(org_row)
        row = self._conn.execute(
            "SELECT COUNT(*) c FROM organization_members"
            " WHERE org_id = ? AND role = 'owner'",
            (org_id,)).fetchone()
        return int(row["c"])

    def list_members(self, org_id: int) -> list[OrgMembership]:
        org_row = self._require_org_row(org_id)
        self._ensure_founding_owner(org_row)
        rows = self._conn.execute(
            _MEMBER_SELECT + " WHERE m.org_id = ?"
            " ORDER BY CASE m.role WHEN 'owner' THEN 0"
            " ELSE 1 END, u.username_lower",
            (org_id,)).fetchall()
        return [_row_to_membership(r) for r in rows]

    def get_membership(self, user_id: int,
                       org_id: int) -> OrgMembership | None:
        org_row = self._require_org_row(org_id)
        self._ensure_founding_owner(org_row)
        row = self._conn.execute(
            _MEMBER_SELECT + " WHERE m.org_id = ? AND m.user_id = ?",
            (org_id, user_id)).fetchone()
        return _row_to_membership(row) if row else None

    # -- changes ----------------------------------------
    def add_member(self, actor_id: int, org_id: int,
                   target: object, role: object = "member",
                   source_ip: str | None = None) -> OrgMembership:
        org_row = self._require_org_row(org_id)
        self._ensure_founding_owner(org_row)
        actor = self._require_owner_or_admin(actor_id, org_row)
        clean_role = validate_role(role)
        target_user = self._resolve_target(target)
        if self._raw_role(target_user.id, org_id) is not None:
            raise OrganizationError(
                "already_member",
                "That person is already a member of this organization.")
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "INSERT INTO organization_members"
                " (org_id, user_id, role, added_by,"
                " created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (org_id, target_user.id, clean_role,
                 actor.id, now, now))
        self._audit_change(actor, org_row, "add", target_user,
                           role=clean_role, source_ip=source_ip)
        result = self.get_membership(target_user.id, org_id)
        assert result is not None
        return result

    def remove_member(self, actor_id: int, org_id: int,
                      target: object,
                      source_ip: str | None = None) -> None:
        org_row = self._require_org_row(org_id)
        self._ensure_founding_owner(org_row)
        actor = self._require_owner_or_admin(actor_id, org_row)
        target_user = self._resolve_target(target)
        current = self._raw_role(target_user.id, org_id)
        if current is None:
            raise OrganizationError(
                "not_a_member",
                "That person is not a member of this organization.")
        refusal = decide_removal(current, self.count_owners(org_id))
        if refusal is not None:
            raise OrganizationError(
                refusal,
                "The last owner cannot be removed: an organization "
                "must always keep at least one owner.")
        with self._conn:
            self._conn.execute(
                "DELETE FROM organization_members"
                " WHERE org_id = ? AND user_id = ?",
                (org_id, target_user.id))
        self._audit_change(actor, org_row, "remove", target_user,
                           source_ip=source_ip)

    def leave_organization(self, user_id: int, org_id: int,
                           source_ip: str | None = None) -> None:
        org_row = self._require_org_row(org_id)
        self._ensure_founding_owner(org_row)
        user = self._require_user(user_id)
        current = self._raw_role(user.id, org_id)
        if current is None:
            raise OrganizationError(
                "not_a_member",
                "You are not a member of this organization.")
        refusal = decide_removal(current, self.count_owners(org_id))
        if refusal is not None:
            raise OrganizationError(
                refusal,
                "The last owner cannot leave: an organization "
                "must always keep at least one owner.")
        with self._conn:
            self._conn.execute(
                "DELETE FROM organization_members"
                " WHERE org_id = ? AND user_id = ?",
                (org_id, user.id))
        self._audit_change(user, org_row, "leave", user,
                           source_ip=source_ip)

    def set_role(self, actor_id: int, org_id: int,
                 target: object, new_role: object,
                 source_ip: str | None = None) -> OrgMembership:
        org_row = self._require_org_row(org_id)
        self._ensure_founding_owner(org_row)
        actor = self._require_owner_or_admin(actor_id, org_row)
        clean_role = validate_role(new_role)
        target_user = self._resolve_target(target)
        current = self._raw_role(target_user.id, org_id)
        if current is None:
            raise OrganizationError(
                "not_a_member",
                "That person is not a member of this organization.")
        if current == clean_role:
            result = self.get_membership(target_user.id, org_id)
            assert result is not None
            return result
        refusal = decide_role_change(
            current, clean_role, self.count_owners(org_id))
        if refusal is not None:
            raise OrganizationError(
                refusal,
                "The last owner cannot be demoted: an organization "
                "must always keep at least one owner.")
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "UPDATE organization_members SET role = ?,"
                " updated_at = ? WHERE org_id = ? AND user_id = ?",
                (clean_role, now, org_id, target_user.id))
        self._audit_change(actor, org_row, "role_change", target_user,
                           role=clean_role, source_ip=source_ip)
        result = self.get_membership(target_user.id, org_id)
        assert result is not None
        return result


def render_members_page(org: Organization,
                        members: list[OrgMembership]) -> str:
    """The members page: every member's username and
    role in words, escaped through S-010, and the
    last-owner rule stated in a plain sentence."""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Members — {escape_html_text(org.name)} — Samverk</title></head>",
        "<body>",
        f"<h1>Members of {escape_html_text(org.effective_display_name())}</h1>",
        "<p>An organization must always keep at least one owner: "
        "the last owner cannot leave or be removed.</p>",
        "<ul>",
    ]
    for member in members:
        username = escape_html_text(member.username)
        word = escape_html_text(role_word(member.role))
        parts.append(f"<li>{username} — {word}</li>")
    parts.append("</ul></body></html>")
    return "\n".join(parts)
