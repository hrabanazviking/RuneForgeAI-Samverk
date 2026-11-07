"""Outside collaborators (S-191).

Per-repo grants to non-members, listed in one
auditable place, revocable in one click.

- **An outside collaborator is a person with a
  grant on one repository who is not a member of
  the world that owns it.** For a repository owned
  by an organization, the grantee must not be a
  member of that organization (S-186's roles); a
  member's access flows through teams (S-187 to
  S-189) and, from S-192, the default repository
  permission, never through this store — granting a
  member here is refused ``already_member``. For a
  personally owned repository, anyone but the owner
  is outside. Granting the repository's own owner
  is refused ``already_owner``: the owner already
  holds admin (S-054's law) and a grant would be a
  lie in the list. The judgement is the pure
  ``decide_grant``, proven as a rule and as lived
  behaviour.
- **The ladder is S-189's, imported, never
  re-derived.** A grant is one rung of ``read`` /
  ``triage`` / ``write`` / ``maintain`` / ``admin``,
  judged only by S-189's rank helpers; a role
  outside the ladder is refused ``role_invalid``
  by ``validate_collaborator_role`` — loudly, never
  silently ignored. The grant lives on exactly one
  repository: it opens no other repository, no
  organization, and no team.
- **Only stewardship manages.** Granting, changing
  and revoking another person's grant are acts for
  the repository's owner, an owner of the owning
  organization, or a site admin (``not_repo_admin``
  otherwise) — a collaborator, even an admin
  collaborator, cannot grant access to anyone else.
  The one exception is leaving: a collaborator may
  revoke their own grant (``revoke`` with actor and
  target the same person), because walking away
  needs no one's permission.
- **One auditable place.** ``list_for_repo`` is a
  repository's grant list; ``list_for_owner`` is
  every outside grant across every repository one
  owner (a person or an organization) holds, in one
  ordered list, and ``render_owner_collaborators_
  page`` renders that list as the single page a
  steward audits. Nothing about a grant is hidden
  in a second place: the row, its role, who granted
  it and when are all on the record.
- **Revocable in one click.** ``revoke`` is the
  whole act: one call removes the row, and the
  person's role through this store is gone from
  that moment — S-190's engine, which reads this
  store, answers accordingly on its next call.
  Revoking a grant that does not exist is refused
  ``not_collaborator``; granting over an existing
  grant is refused ``already_collaborator`` (change
  it with ``set_role`` instead). Setting the role a
  grant already holds is a no-op success that
  writes nothing and audits nothing (S-186's /
  S-189's same-role law, mirrored).
- **S-190 reads this store.** The permission
  engine's ``resolve`` takes its collaborator
  contribution from ``role_for`` here when the
  caller passes no explicit role; an explicit
  ``collaborator_role`` still wins for that call,
  so S-190's answers for caller-supplied grants do
  not change, and stored grants answer exactly as
  caller-supplied ones did.
- **S-200 guardrail:** demoting or revoking an
  admin grant is judged by
  ``samverk/role_change_guardrails.py`` before it
  writes: a change that would leave the repository
  with no grant-admin at all is refused
  ``last_admin`` (see that module for who counts).
- **Audit:** successful changes ride the existing
  ``repo.collaborator.add`` /
  ``repo.collaborator.remove`` /
  ``repo.collaborator.role_change`` events (in the
  taxonomy since S-008 — no new event, 122 stand:
  31 auth / 79 repo / 12 admin) with the detail
  shapes docs/AUDIT_TAXONOMY.md has always
  promised for them (``{"user": ..., "role":
  ...}`` on add, ``{"user": ...}`` on remove,
  ``{"user": ..., "from": ..., "to": ...}`` on
  role change), targeted at the repository.
  Refusals and no-op sets write nothing and audit
  nothing.
- **Storage** is migration 73's
  ``outside_collaborators`` table (schema 72 to
  73): one row per (repository, person) pair, with
  its ladder role, its granter and its times.
  Repositories, organizations and memberships stay
  S-049/S-185/S-186 ground and are only read here.
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
from .organizations import Organization, OrganizationError, OrganizationStore
from .repositories import Repository
from .team_permissions import ROLES, role_word

__all__ = [
    "ROLES", "OutsideCollaborator", "OutsideCollaboratorStore",
    "decide_grant", "decide_revoke", "is_outside",
    "render_outside_collaborators_page",
    "render_owner_collaborators_page",
    "validate_collaborator_role",
]

_ROLE_SET = frozenset(ROLES)


def validate_collaborator_role(role: object) -> str:
    """Return the canonical S-189 ladder role or
    refuse plainly: the role must be one of ROLES,
    written as text, judged trimmed and
    case-insensitively (S-189's law, restated for
    collaborators so the refusal names this grant)."""
    if isinstance(role, str) and role.strip().lower() in _ROLE_SET:
        return role.strip().lower()
    raise OrganizationError(
        "role_invalid",
        "A collaborator's role is one of: "
        "read, triage, write, maintain, admin.")


def is_outside(*, is_repo_owner: bool, org_owned: bool,
               org_role: str | None) -> bool:
    """Pure outsideness: the repository's owner is
    never outside their own repository, and a member
    of the owning organization is never outside an
    organization repository. Everyone else is."""
    if is_repo_owner:
        return False
    if org_owned and org_role is not None:
        return False
    return True


def decide_grant(*, is_repo_owner: bool, org_owned: bool,
                 org_role: str | None,
                 existing_role: str | None) -> str | None:
    """Pure grant rule: the refusal reason, or None
    when the grant may be made. The owner is refused
    first (their admin needs no grant), then a member
    of the owning organization, then a duplicate."""
    if is_repo_owner:
        return "already_owner"
    if org_owned and org_role is not None:
        return "already_member"
    if existing_role is not None:
        return "already_collaborator"
    return None


def decide_revoke(*, existing_role: str | None,
                  is_manager: bool,
                  is_self: bool) -> str | None:
    """Pure revoke rule: the refusal reason, or None
    when the revocation may proceed. There must be a
    grant to revoke, and the actor must steward the
    repository or be revoking their own grant."""
    if existing_role is None:
        return "not_collaborator"
    if not (is_manager or is_self):
        return "not_repo_admin"
    return None


@dataclass(frozen=True)
class OutsideCollaborator:
    """One outside grant: one person, one repository,
    one ladder role, its granter and its times."""
    repo_id: int
    user_id: int
    username: str
    username_lower: str
    owner: str
    name: str
    role: str
    granted_by: int | None
    granted_by_username: str | None
    created_at: int
    updated_at: int

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"

    def role_word(self) -> str:
        """The role said in a word a person reads."""
        return role_word(self.role)


_GRANT_SELECT = (
    "SELECT c.repo_id AS repo_id, c.user_id AS user_id,"
    " u.username AS username,"
    " u.username_lower AS username_lower,"
    " r.owner AS owner, r.name AS name,"
    " c.role AS role, c.granted_by AS granted_by,"
    " g.username AS granted_by_username,"
    " c.created_at AS created_at,"
    " c.updated_at AS updated_at"
    " FROM outside_collaborators c"
    " JOIN users u ON u.id = c.user_id"
    " JOIN repositories r ON r.id = c.repo_id"
    " LEFT JOIN users g ON g.id = c.granted_by")


def _row_to_grant(row: sqlite3.Row) -> OutsideCollaborator:
    return OutsideCollaborator(
        repo_id=row["repo_id"], user_id=row["user_id"],
        username=row["username"],
        username_lower=row["username_lower"],
        owner=row["owner"], name=row["name"],
        role=row["role"], granted_by=row["granted_by"],
        granted_by_username=row["granted_by_username"],
        created_at=row["created_at"],
        updated_at=row["updated_at"])


class OutsideCollaboratorStore:
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

    # -- guards --------------------------------------
    def _require_repo_row(self, repo_id: int) -> sqlite3.Row:
        row = self._conn.execute(
            "SELECT * FROM repositories WHERE id = ?",
            (repo_id,)).fetchone()
        if row is None:
            raise OrganizationError(
                "repo_not_found", "No such repository.")
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

    def _org_for(self, repo_row: sqlite3.Row) -> Organization | None:
        """The organization that owns this repository,
        or None for a personally owned repository (the
        S-185 shared namespace: an owner name is a
        person or an organization, never both)."""
        return self._orgs.get_by_name(repo_row["owner"])

    def _org_role(self, user_id: int,
                  org: Organization | None) -> str | None:
        if org is None:
            return None
        return self._org_members.role_for(user_id, org.id)

    def _is_manager(self, actor: User, repo_row: sqlite3.Row,
                    org: Organization | None) -> bool:
        """Stewardship of one repository: its personal
        owner, an owner of its owning organization,
        or a site admin."""
        if actor.is_admin:
            return True
        if actor.username_lower == repo_row["owner_lower"]:
            return True
        return self._org_role(actor.id, org) == "owner"

    def _require_manager(self, actor_id: int,
                         repo_row: sqlite3.Row,
                         org: Organization | None) -> User:
        actor = self._require_user(actor_id)
        if not self._is_manager(actor, repo_row, org):
            raise OrganizationError(
                "not_repo_admin",
                "Only the repository owner, an owner of "
                "the owning organization, or a site admin "
                "can manage this repository's outside "
                "collaborators.")
        return actor

    def _grant_row(self, repo_id: int, user_id: int):
        return self._conn.execute(
            _GRANT_SELECT
            + " WHERE c.repo_id = ? AND c.user_id = ?",
            (repo_id, user_id)).fetchone()

    # -- audit (existing repo.collaborator.* events) --
    def _audit_event(self, actor: User, repo_row: sqlite3.Row,
               action: str, detail: dict,
               source_ip: str | None = None):
        if self._audit is None:
            return
        self._audit.append(
            actor_kind="user", actor_id=actor.id,
            action=action, target_kind="repo",
            target_id=f"{repo_row['owner']}/{repo_row['name']}",
            outcome="success", source_ip=source_ip,
            detail=detail)

    # -- writes --------------------------------------
    def grant(
        self, actor_id: int, repo_id: int, target: object,
        role: object, source_ip: str | None = None,
    ) -> OutsideCollaborator:
        """Grant *target* (an account id or a username)
        a ladder role on one repository as an outside
        collaborator. Stewardship only; the grantee
        must be outside the owning world and hold no
        grant here yet — the pure ``decide_grant``
        names every refusal (``already_owner`` /
        ``already_member`` / ``already_collaborator``)."""
        repo_row = self._require_repo_row(repo_id)
        org = self._org_for(repo_row)
        actor = self._require_manager(actor_id, repo_row, org)
        grantee = self._resolve_target(target)
        clean_role = validate_collaborator_role(role)
        existing = self._grant_row(repo_id, grantee.id)
        refusal = decide_grant(
            is_repo_owner=(grantee.username_lower
                           == repo_row["owner_lower"]),
            org_owned=org is not None,
            org_role=self._org_role(grantee.id, org),
            existing_role=existing["role"] if existing else None)
        if refusal == "already_owner":
            raise OrganizationError(
                "already_owner",
                "The repository's owner already holds "
                "admin; an owner needs no grant.")
        if refusal == "already_member":
            raise OrganizationError(
                "already_member",
                "That person is a member of the owning "
                "organization; members are not outside "
                "collaborators.")
        if refusal == "already_collaborator":
            raise OrganizationError(
                "already_collaborator",
                "That person already holds a grant on "
                "this repository; change its role "
                "instead of granting again.")
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "INSERT INTO outside_collaborators"
                " (repo_id, user_id, role, granted_by,"
                " created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (repo_id, grantee.id, clean_role,
                 actor.id, now, now))
        self._audit_event(actor, repo_row, "repo.collaborator.add",
                    {"user": grantee.username_lower,
                     "role": clean_role},
                    source_ip=source_ip)
        result = self.get_grant(repo_id, grantee.id)
        assert result is not None
        return result

    def set_role(
        self, actor_id: int, repo_id: int, target: object,
        role: object, source_ip: str | None = None,
    ) -> OutsideCollaborator:
        """Move an existing grant up or down the
        ladder. Stewardship only; no grant here is
        ``not_collaborator``. Setting the role already
        held is a no-op success: nothing is written,
        nothing is audited."""
        repo_row = self._require_repo_row(repo_id)
        org = self._org_for(repo_row)
        actor = self._require_manager(actor_id, repo_row, org)
        grantee = self._resolve_target(target)
        clean_role = validate_collaborator_role(role)
        existing = self._grant_row(repo_id, grantee.id)
        if existing is None:
            raise OrganizationError(
                "not_collaborator",
                "That person holds no grant on this "
                "repository; grant one first.")
        current = existing["role"]
        if current == clean_role:
            return _row_to_grant(existing)
        if current == "admin" and clean_role != "admin":
            # S-200 guardrail (local import for
            # symmetry with the team door).
            from .role_change_guardrails import (
                RoleChangeGuardStore)
            RoleChangeGuardStore(
                self._conn, self._accounts,
                time_fn=self._now).check_collaborator_role_change(
                    repo_id, grantee.id, current, clean_role)
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "UPDATE outside_collaborators SET role = ?,"
                " updated_at = ?"
                " WHERE repo_id = ? AND user_id = ?",
                (clean_role, now, repo_id, grantee.id))
        self._audit_event(actor, repo_row,
                    "repo.collaborator.role_change",
                    {"user": grantee.username_lower,
                     "from": current, "to": clean_role},
                    source_ip=source_ip)
        result = self.get_grant(repo_id, grantee.id)
        assert result is not None
        return result

    def revoke(
        self, actor_id: int, repo_id: int, target: object,
        source_ip: str | None = None,
    ) -> OutsideCollaborator:
        """Revoke a grant in one click: this one call
        removes the row and the role it carried, and
        returns the grant that was removed. A steward
        may revoke anyone's grant; a collaborator may
        revoke their own (leaving needs no permission).
        No grant here is ``not_collaborator``."""
        repo_row = self._require_repo_row(repo_id)
        org = self._org_for(repo_row)
        actor = self._require_user(actor_id)
        grantee = self._resolve_target(target)
        existing = self._grant_row(repo_id, grantee.id)
        refusal = decide_revoke(
            existing_role=existing["role"] if existing else None,
            is_manager=self._is_manager(actor, repo_row, org),
            is_self=actor.id == grantee.id)
        if refusal == "not_collaborator":
            raise OrganizationError(
                "not_collaborator",
                "That person holds no grant on this "
                "repository, so there is nothing to revoke.")
        if refusal == "not_repo_admin":
            raise OrganizationError(
                "not_repo_admin",
                "Only the repository owner, an owner of "
                "the owning organization, or a site admin "
                "can revoke another person's grant.")
        if existing["role"] == "admin":
            # S-200 guardrail: revoking the last
            # admin grant is refused like demoting it.
            from .role_change_guardrails import (
                RoleChangeGuardStore)
            RoleChangeGuardStore(
                self._conn, self._accounts,
                time_fn=self._now).check_collaborator_role_change(
                    repo_id, grantee.id, "admin", None)
        removed = _row_to_grant(existing)
        with self._conn:
            self._conn.execute(
                "DELETE FROM outside_collaborators"
                " WHERE repo_id = ? AND user_id = ?",
                (repo_id, grantee.id))
        self._audit_event(actor, repo_row,
                    "repo.collaborator.remove",
                    {"user": grantee.username_lower},
                    source_ip=source_ip)
        return removed

    # -- reads: the one auditable place ---------------
    def get_grant(self, repo_id: int,
                  user_id: int) -> OutsideCollaborator | None:
        """One person's grant on one repository, or
        None when they hold none here. A plain read."""
        row = self._grant_row(repo_id, user_id)
        return _row_to_grant(row) if row else None

    def role_for(self, user_id: int, repo_id: int) -> str | None:
        """The ladder role a stored grant gives one
        person on one repository, or None — the seam
        S-190's permission engine reads. A plain read:
        an unknown repository or person simply holds
        no grant."""
        row = self._conn.execute(
            "SELECT role FROM outside_collaborators"
            " WHERE repo_id = ? AND user_id = ?",
            (repo_id, user_id)).fetchone()
        return row["role"] if row else None

    def list_for_repo(self, repo_id: int) -> list[OutsideCollaborator]:
        """Every outside grant on one repository — the
        repository's auditable list — ordered by
        username. An unknown repository is
        ``repo_not_found``."""
        self._require_repo_row(repo_id)
        rows = self._conn.execute(
            _GRANT_SELECT + " WHERE c.repo_id = ?"
            " ORDER BY u.username_lower", (repo_id,)).fetchall()
        return [_row_to_grant(r) for r in rows]

    def list_for_user(self, user_id: int) -> list[OutsideCollaborator]:
        """Every outside grant one person holds, across
        all repositories, ordered by repository. An
        unknown account is ``no_such_user``."""
        self._require_user(user_id)
        rows = self._conn.execute(
            _GRANT_SELECT + " WHERE c.user_id = ?"
            " ORDER BY r.owner_lower, r.name_lower",
            (user_id,)).fetchall()
        return [_row_to_grant(r) for r in rows]

    def list_for_owner(self, owner: object) -> list[OutsideCollaborator]:
        """Every outside grant across every repository
        one owner holds — the one auditable place for
        a person or an organization — ordered by
        repository, then username."""
        if not isinstance(owner, str):
            return []
        rows = self._conn.execute(
            _GRANT_SELECT + " WHERE r.owner_lower = ?"
            " ORDER BY r.name_lower, u.username_lower",
            (owner.strip().lower(),)).fetchall()
        return [_row_to_grant(r) for r in rows]

    def count_for_repo(self, repo_id: int) -> int:
        """How many outside grants one repository
        carries. A plain read."""
        row = self._conn.execute(
            "SELECT COUNT(*) c FROM outside_collaborators"
            " WHERE repo_id = ?", (repo_id,)).fetchone()
        return int(row["c"])


def render_outside_collaborators_page(
    repo: Repository, grants: list[OutsideCollaborator],
) -> str:
    """One repository's outside collaborators page:
    the ladder said in plain words, then every grant
    with its role, its granter and its one-click
    revocation said in words — every value escaped
    through S-010."""
    ladder = " / ".join(role_word(r) for r in ROLES)
    label = f"{repo.owner}/{repo.name}"
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Outside collaborators — "
        f"{escape_html_text(label)} — Samverk</title></head>",
        "<body>",
        f"<h1>Outside collaborators — "
        f"{escape_html_text(label)}</h1>",
        "<p>An outside collaborator holds a grant on "
        "this one repository without belonging to the "
        "world that owns it: for an organization "
        "repository they are not a member of the "
        "organization, and for a personal repository "
        "they are not its owner. This list is the one "
        "auditable place for those grants: every grant "
        "is here, with its role and who granted it.</p>",
        f"<p>The permission ladder (S-189) is: "
        f"{escape_html_text(ladder)}. Read may look; "
        "triage may manage issues and pull requests "
        "without writing code; write may push; maintain "
        "may manage non-destructive repository settings; "
        "admin is full control of this repository only. "
        "A grant opens no other repository.</p>",
        "<h2>Grants</h2>",
    ]
    if grants:
        parts.append("<ul>")
        for grant in grants:
            granter = grant.granted_by_username or "a steward"
            parts.append(
                f"<li>{escape_html_text(grant.username)} — "
                f"{escape_html_text(grant.role_word())} — "
                f"granted by {escape_html_text(granter)} — "
                "Revoke: one click removes this grant at "
                "once, and the removal is audit-logged "
                "(repo.collaborator.remove).</li>")
        parts.append("</ul>")
    else:
        parts.append(
            "<p>This repository has no outside "
            "collaborators.</p>")
    parts.append(
        "<p>Grants, role changes and revocations are "
        "audit-logged as repo.collaborator.add, "
        "repo.collaborator.role_change and "
        "repo.collaborator.remove (S-191). Only the "
        "repository owner, an owner of the owning "
        "organization, or a site admin may grant, "
        "change or revoke another person's grant; a "
        "collaborator may revoke their own.</p>")
    parts.append("</body></html>")
    return "\n".join(parts)


def render_owner_collaborators_page(
    owner: str, grants: list[OutsideCollaborator],
) -> str:
    """The one auditable place for an owner: every
    outside grant across every repository the owner
    holds, each with its repository, person and role
    said in words — every value escaped through
    S-010."""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Outside collaborators — "
        f"{escape_html_text(owner)} — Samverk</title></head>",
        "<body>",
        f"<h1>Outside collaborators — "
        f"{escape_html_text(owner)}</h1>",
        "<p>Every outside grant on every repository "
        "this owner holds, in one place (S-191): if a "
        "grant is not listed here, it does not exist. "
        "Each grant is revocable in one click from its "
        "repository's list, and every change is "
        "audit-logged.</p>",
    ]
    if grants:
        parts.append("<ul>")
        for grant in grants:
            parts.append(
                f"<li>{escape_html_text(grant.full_name)} — "
                f"{escape_html_text(grant.username)} — "
                f"{escape_html_text(grant.role_word())}</li>")
        parts.append("</ul>")
    else:
        parts.append(
            "<p>No outside collaborators on any "
            "repository this owner holds.</p>")
    parts.append("</body></html>")
    return "\n".join(parts)
