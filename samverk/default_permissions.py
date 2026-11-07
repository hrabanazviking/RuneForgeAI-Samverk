"""Default repository permission (S-192).

The org-wide base role for members, settable, shown
in effect on the matrix page.

- **One default per organization.** Every member of
  an organization holds at least the organization's
  default repository permission in every repository
  the organization owns — no rung at all until it is
  set. The unset default is ``none``: organization
  membership alone grants nothing, exactly as S-190
  judged before this slice landed, and setting the
  default to ``none`` restores that answer. The
  judgement of what a stored default means is the
  pure ``decide_default_change`` / the contribution
  S-190's engine builds from it; the value itself is
  judged by ``validate_default_role``.
- **The ladder is S-189's, plus ``none``.** A default
  is one rung of ``read`` / ``triage`` / ``write`` /
  ``maintain`` / ``admin``, or ``none`` — no role.
  Ladder rungs are judged only by S-189's rank
  helpers, imported, never re-derived; anything
  outside the ladder and ``none`` is refused
  ``role_invalid`` — loudly, never silently ignored.
- **It is a floor for members, never a ceiling and
  never a grant to anyone else.** S-190's engine adds
  the default as one contribution (source
  ``org_default``) for a plain member of the owning
  organization, and the highest contribution still
  wins: a team grant, a collaborator grant or
  ownership above the default decides the answer, and
  a lower team grant never pulls a member below the
  default. Non-members gain nothing from it, an
  anonymous visitor gains nothing, and it never
  applies to a personally owned repository.
- **Only stewardship sets it.** Setting the default
  is an organization owner / site admin act (the
  S-186/S-189 guard, mirrored; ``not_org_owner``
  otherwise, ``org_not_found`` for an organization
  that does not exist, ``no_such_user`` for an actor
  that does not). Setting the value already in effect
  is a no-op success that writes nothing and audits
  nothing (the same-value law every neighbour slice
  keeps).
- **Shown in effect.** ``render_default_permission_
  page`` states the current default in words — the
  role, who it reaches, and what it does not do — and
  S-190's ``render_matrix_page`` shows it in effect:
  a member whose winning contribution is the default
  is listed with the source said in words,
  "Organization default", never colour-only.
- **Audit:** a successful change rides the existing
  ``auth.organization.update`` event (no new taxonomy
  event — 122 stand: 31 auth / 79 repo / 12 admin)
  with detail ``{"fields": "default_permission",
  "action": "set_default", "from": ..., "to": ...}``,
  targeted at the organization. Refusals and no-op
  sets write nothing and audit nothing.
- **Storage** is migration 74's
  ``org_default_permissions`` table (schema 73 to
  74): one row per organization that has a default
  set, with its role, its setter and its times; no
  row means ``none``. Organizations and memberships
  stay S-185/S-186 ground and are only read here.
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
from .organizations import OrganizationError
from .team_permissions import ROLES, role_word, validate_role

__all__ = [
    "NO_DEFAULT", "ROLES", "DefaultPermission",
    "DefaultPermissionStore", "decide_default_change",
    "render_default_permission_page",
    "validate_default_role",
]

NO_DEFAULT = "none"


def validate_default_role(role: object) -> str:
    """Return the canonical default: a ladder rung,
    judged by S-189's validator, or ``none``. Written
    as text, judged trimmed and case-insensitively;
    anything else is refused ``role_invalid``."""
    if isinstance(role, str) and role.strip().lower() == NO_DEFAULT:
        return NO_DEFAULT
    try:
        return validate_role(role)
    except OrganizationError:
        raise OrganizationError(
            "role_invalid",
            "A default repository permission is one of: "
            "none, read, triage, write, maintain, admin.")


def decide_default_change(current: str, new: str) -> str | None:
    """Pure set rule over already-validated values:
    the refusal-free outcome — ``"noop"`` when the new
    value is the value already in effect, else
    ``"set"``."""
    if current == new:
        return "noop"
    return "set"


@dataclass(frozen=True)
class DefaultPermission:
    """One organization's default repository
    permission: the role every member holds at least,
    whether it was ever set, who set it and when. An
    unset default reads as role ``none``."""
    org_id: int
    org_name: str
    org_name_lower: str
    role: str
    is_set: bool
    set_by: int | None
    set_by_username: str | None
    created_at: int | None
    updated_at: int | None

    def role_word(self) -> str:
        """The default said in a word a person reads;
        ``none`` is said in words too."""
        if self.role == NO_DEFAULT:
            return "No permission"
        return role_word(self.role)


_SELECT = (
    "SELECT d.org_id AS org_id,"
    " o.name AS org_name, o.name_lower AS org_name_lower,"
    " d.role AS role, d.set_by AS set_by,"
    " u.username AS set_by_username,"
    " d.created_at AS created_at, d.updated_at AS updated_at"
    " FROM org_default_permissions d"
    " JOIN organizations o ON o.id = d.org_id"
    " LEFT JOIN users u ON u.id = d.set_by")


def _row_to_default(row: sqlite3.Row) -> DefaultPermission:
    return DefaultPermission(
        org_id=row["org_id"], org_name=row["org_name"],
        org_name_lower=row["org_name_lower"], role=row["role"],
        is_set=True, set_by=row["set_by"],
        set_by_username=row["set_by_username"],
        created_at=row["created_at"], updated_at=row["updated_at"])


class DefaultPermissionStore:
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

    # -- guards --------------------------------------
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
                "can set this organization's default "
                "repository permission.")
        return actor

    def _stored_row(self, org_id: int):
        return self._conn.execute(
            _SELECT + " WHERE d.org_id = ?", (org_id,)).fetchone()

    # -- reads ----------------------------------------
    def get_default(self, org_id: int) -> DefaultPermission:
        """The organization's default, whole: an
        organization that never set one reads as role
        ``none``, not set. An unknown organization is
        ``org_not_found``."""
        org_row = self._require_org_row(org_id)
        row = self._stored_row(org_id)
        if row is None:
            return DefaultPermission(
                org_id=org_id, org_name=org_row["name"],
                org_name_lower=org_row["name_lower"],
                role=NO_DEFAULT, is_set=False, set_by=None,
                set_by_username=None, created_at=None,
                updated_at=None)
        return _row_to_default(row)

    def role_for_org(self, org_id: int) -> str:
        """Just the stored rung (or ``none``): the
        value S-190's engine contributes for a plain
        member of this organization."""
        return self.get_default(org_id).role

    # -- writes ---------------------------------------
    def set_default(
        self, actor_id: int, org_id: int, role: object,
        source_ip: str | None = None,
    ) -> DefaultPermission:
        """Set the org-wide base role for members.
        Stewardship only. ``none`` clears the row, so
        no row ever stores it. Setting the value
        already in effect is a no-op success: nothing
        is written, nothing is audited."""
        org_row = self._require_org_row(org_id)
        actor = self._require_owner_or_admin(actor_id, org_row)
        clean = validate_default_role(role)
        current = self.get_default(org_id)
        if decide_default_change(current.role, clean) == "noop":
            return current
        now = int(self._now())
        with self._conn:
            if clean == NO_DEFAULT:
                self._conn.execute(
                    "DELETE FROM org_default_permissions"
                    " WHERE org_id = ?", (org_id,))
            elif current.is_set:
                self._conn.execute(
                    "UPDATE org_default_permissions"
                    " SET role = ?, set_by = ?, updated_at = ?"
                    " WHERE org_id = ?",
                    (clean, actor.id, now, org_id))
            else:
                self._conn.execute(
                    "INSERT INTO org_default_permissions"
                    " (org_id, role, set_by, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (org_id, clean, actor.id, now, now))
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="auth.organization.update",
                target_kind="organization",
                target_id=org_row["name_lower"],
                outcome="success", source_ip=source_ip,
                detail={"fields": "default_permission",
                        "action": "set_default",
                        "from": current.role, "to": clean})
        return self.get_default(org_id)


def render_default_permission_page(
        default: DefaultPermission) -> str:
    """The default, shown in effect: the current value
    in words, who it reaches (every member, in every
    repository the organization owns), and what it
    does not do (it never lowers a higher grant and
    never reaches a non-member) — every value escaped
    through S-010, the state said in text, never
    colour-only."""
    ladder = " / ".join(role_word(r) for r in ROLES)
    if default.is_set:
        state = (f"The default repository permission for "
                 f"{default.org_name} is "
                 f"{default.role_word()}.")
        setter = default.set_by_username or "an organization owner"
        effect = (f"Every member of {default.org_name} holds at "
                  f"least {default.role_word()} in every repository "
                  f"the organization owns, set by {setter}. A higher "
                  f"grant — ownership, a team grant or a collaborator "
                  f"grant — still decides above it, and a lower grant "
                  f"never pulls a member below it. It reaches members "
                  f"only: non-members and anonymous visitors gain "
                  f"nothing from it.")
    else:
        state = (f"{default.org_name} has no default repository "
                 f"permission set: the default is No permission.")
        effect = (f"Membership of {default.org_name} alone grants "
                  f"no role in its repositories; a member's role "
                  f"comes from ownership, team grants and "
                  f"collaborator grants only.")
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Default repository permission — "
        f"{escape_html_text(default.org_name)} — "
        f"Samverk</title></head>",
        "<body>",
        f"<h1>Default repository permission — "
        f"{escape_html_text(default.org_name)}</h1>",
        f"<p>{escape_html_text(state)}</p>",
        f"<p>{escape_html_text(effect)}</p>",
        f"<p>The permission ladder (S-189) is: "
        f"{escape_html_text(ladder)}, and a default may also be "
        f"No permission. Read may look; triage may manage issues "
        f"and pull requests without writing code; write may push; "
        f"maintain may manage non-destructive repository "
        f"settings; admin is full control.</p>",
        "<p>Only an organization owner or a site admin can set "
        "the default. On the permission matrix (S-190) a member "
        "whose role comes from this default is shown with the "
        "source Organization default.</p>",
        "</body></html>",
    ]
    return "\n".join(parts)
