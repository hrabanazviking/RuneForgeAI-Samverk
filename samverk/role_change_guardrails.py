"""Role change guardrails (S-200).

Demoting the last admin of a repo is refused with
the reason stated.

- **Who counts as an admin of a repository.** The
  guardrail judges the admins a role change can
  actually take away: the people who hold ``admin``
  in the repository through a *grant* — an outside
  collaborator grant at the admin rung (S-191), a
  team grant whose effective permission is admin
  (S-189 over S-188's nesting, members judged by
  S-188's effective membership), or the owning
  organization's default repository permission at
  the admin rung, which floors every plain member
  at admin (S-192). ``admin_holders`` is that list,
  each holder named with the source (or sources)
  that grant it. Three further admin sources are
  intrinsic and are *not* counted, because no role
  change anywhere can demote them: the repository's
  personal owner (admin by ownership, S-054), the
  owners of the owning organization (admin by org
  ownership, S-190 — and demoting one is already
  refused by S-186's ``last_owner`` law at the org
  granularity, which is the stronger guard), and
  site admins (admin by instance flag). A repository
  whose only admins are intrinsic therefore shows
  no grant-holders here, and its administration is
  guarded by those slices, not this one.
- **The rule.** A role change that would leave a
  repository with no grant-admin at all — the last
  holder's admin grant demoted below admin, or
  revoked — is refused with reason ``last_admin``
  and a plain sentence saying why, in the house
  style S-186 set for ``last_owner``. The judgement
  is the pure ``decide_last_admin`` over the holder
  sets *before* and *after the change as it would
  actually land*: the guard recomputes the holders
  with the one grant hypothetically moved, so a
  demotion that removes nobody's last admin path —
  the person also holds admin through a team, a
  second admin stands beside them, the team's
  ancestor still grants admin, an empty team holds
  the grant — is allowed, exactly as before.
  Promotions, lateral and lower-rung changes, and
  same-role no-op sets are never guarded.
- **The doors wired.** Every per-repository role
  change that can demote an admin grant passes the
  guard before it writes: S-191's
  ``OutsideCollaboratorStore.set_role`` (demotion)
  and ``revoke`` (the removal path — revoking the
  last admin grant, even by the holder leaving, is
  refused the same way), and S-189's
  ``TeamPermissionStore.set_permission``
  (demotion of a team's admin grant). Both stores
  raise the guard's refusal before writing, so a
  refused change changes nothing and audits
  nothing, exactly like every neighbouring refusal.
- **Considered and not wired, with reasons.**
  S-186's org role changes (owner to member) are
  the intrinsic-admin door and are already guarded
  by ``last_owner`` itself. S-192's ``set_default``
  sets an organization policy floor, not a person's
  role; it is not a demotion door. S-187's
  ``unlink_repo`` detaches a team from a repository
  wholesale — detachment, not demotion — and its
  banked battery proves the permission leaves with
  the link; team membership removal is likewise a
  membership act (S-187), its cascade previewed by
  S-194. Ownership transfer is not a role change.
  These exclusions are the slice's honest scope:
  the title promises demotion guardrails, and the
  demotion doors are the ones wired.
- **The guard is a pure read.** It writes nothing
  and audits nothing, claims no migration of its
  own (schema 78 stands) and no taxonomy event
  (122 stand); successful changes keep riding the
  events their own doors already used. Storage
  stays where the earlier slices put it: grants
  (S-191, migration 73), the ladder on the team
  link (S-189, migration 72), team membership and
  nesting (S-187/S-188), and the org default
  (S-192, migration 74) are only read here.
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore
from .audit import AuditLog
from .escaping import escape_html_text
from .organizations import OrganizationError, OrganizationStore
from .repositories import Repository
from .team_nesting import ancestor_ids
from .team_permissions import ROLE_RANK

__all__ = [
    "AdminHolder", "RoleChangeGuardStore",
    "decide_last_admin", "render_role_guardrails_page",
    "source_word",
]

_SOURCE_WORDS = {
    "collaborator": "Collaborator grant",
    "team": "Team grant",
    "org_default": "Organization default",
}

_DEMOTE_MESSAGE = (
    "The last admin cannot be demoted: a repository "
    "must always keep at least one admin.")
_REMOVE_MESSAGE = (
    "The last admin cannot be removed: a repository "
    "must always keep at least one admin.")


def source_word(source: str) -> str:
    """The source of a granted admin, said in words
    a person reads — never a colour or an icon."""
    return _SOURCE_WORDS.get(source, source)


def decide_last_admin(
    *, current_role: str | None, new_role: str | None,
    holders_before: set[int], holders_after: set[int],
) -> str | None:
    """Pure last-admin rule: the refusal reason, or
    None when the change may proceed. Only a change
    that moves a grant *from* admin to below admin
    (``new_role`` a lower rung) or removes it
    (``new_role`` None) can be refused, and only
    when a grant-admin holder stands before the
    change and none stands after it. Everything
    else — promotions, changes below admin, a holder
    set already empty, a holder set still standing
    — passes."""
    if current_role != "admin":
        return None
    if new_role is not None and (
            ROLE_RANK[new_role] >= ROLE_RANK["admin"]):
        return None
    if holders_before and not holders_after:
        return "last_admin"
    return None


@dataclass(frozen=True)
class AdminHolder:
    """One person holding admin in one repository
    through a grant, with every source that grants
    it named."""
    user_id: int
    username: str
    sources: tuple[str, ...]


class RoleChangeGuardStore:
    """The guardrail itself: compute a repository's
    grant-admin holders from the landed stores, and
    judge a proposed role change against the holder
    set as it would stand after the change. Reads
    only."""

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

    # -- holder computation ---------------------------
    def _require_repo_row(self, repo_id: int) -> sqlite3.Row:
        row = self._conn.execute(
            "SELECT * FROM repositories WHERE id = ?",
            (repo_id,)).fetchone()
        if row is None:
            raise OrganizationError(
                "repo_not_found", "No such repository.")
        return row

    def _holder_map(
        self, repo_row: sqlite3.Row, *,
        collab_override: dict[int, str | None] | None = None,
        team_override: dict[int, str] | None = None,
    ) -> dict[int, set[str]]:
        """user_id -> grant sources at the admin rung,
        with at most one door's change hypothetically
        applied (``collab_override`` maps a person to
        their would-be grant role, None for revoked;
        ``team_override`` maps a team to its would-be
        direct permission)."""
        repo_id = repo_row["id"]
        holders: dict[int, set[str]] = {}

        def add(user_id: int, source: str):
            holders.setdefault(user_id, set()).add(source)

        overrides = collab_override or {}
        try:
            grant_rows = self._conn.execute(
                "SELECT user_id, role FROM outside_collaborators"
                " WHERE repo_id = ?", (repo_id,)).fetchall()
        except sqlite3.OperationalError:
            grant_rows = []
        for row in grant_rows:
            role = overrides.get(row["user_id"], row["role"])
            if role == "admin":
                add(row["user_id"], "collaborator")
        org = self._orgs.get_by_name(repo_row["owner"])
        if org is not None:
            try:
                default_row = self._conn.execute(
                    "SELECT role FROM org_default_permissions"
                    " WHERE org_id = ?", (org.id,)).fetchone()
            except sqlite3.OperationalError:
                default_row = None
            if default_row is not None and (
                    default_row["role"] == "admin"):
                for row in self._conn.execute(
                        "SELECT user_id FROM organization_members"
                        " WHERE org_id = ? AND role = 'member'",
                        (org.id,)).fetchall():
                    add(row["user_id"], "org_default")
            team_rows = self._conn.execute(
                "SELECT id, parent_team_id FROM teams"
                " WHERE org_id = ?", (org.id,)).fetchall()
            parent_of = {
                row["id"]: row["parent_team_id"]
                for row in team_rows}
            direct: dict[int, str] = {}
            for row in self._conn.execute(
                    "SELECT team_id, permission"
                    " FROM team_repositories WHERE repo_id = ?",
                    (repo_id,)).fetchall():
                role = row["permission"] or "read"
                if team_override and (
                        row["team_id"] in team_override):
                    role = team_override[row["team_id"]]
                direct[row["team_id"]] = role
            members: dict[int, set[int]] = {}
            for row in self._conn.execute(
                    "SELECT team_id, user_id FROM team_members"
                    ).fetchall():
                members.setdefault(
                    row["team_id"], set()).add(row["user_id"])
            for team_row in team_rows:
                team_id = team_row["id"]
                chain = [team_id] + ancestor_ids(
                    parent_of, team_id)
                best: str | None = None
                for holder_id in chain:
                    role = direct.get(holder_id)
                    if role is not None and (
                            best is None
                            or ROLE_RANK[role] > ROLE_RANK[best]):
                        best = role
                if best != "admin":
                    continue
                effective: set[int] = set()
                for holder_id in chain:
                    effective.update(members.get(holder_id, set()))
                for user_id in effective:
                    add(user_id, "team")
        return holders

    def admin_holders(self, repo_id: int) -> list[AdminHolder]:
        """Every person holding admin in the repository
        through a grant, with the sources named,
        ordered by username. A plain read."""
        repo_row = self._require_repo_row(repo_id)
        found = self._holder_map(repo_row)
        holders: list[AdminHolder] = []
        for user_id, sources in found.items():
            user = self._accounts.get_by_id(user_id)
            if user is None:
                continue
            holders.append(AdminHolder(
                user_id=user_id, username=user.username,
                sources=tuple(sorted(sources))))
        holders.sort(key=lambda h: h.username.lower())
        return holders

    # -- the guard, one check per wired door ----------
    def check_collaborator_role_change(
        self, repo_id: int, target_user_id: int,
        current_role: str, new_role: str | None,
    ) -> None:
        """Judge an S-191 role change (``new_role``
        None judges a revocation): raise ``last_admin``
        when moving this grant would leave the
        repository with no grant-admin at all."""
        repo_row = self._require_repo_row(repo_id)
        before = self._holder_map(repo_row)
        after = self._holder_map(
            repo_row,
            collab_override={target_user_id: new_role})
        refusal = decide_last_admin(
            current_role=current_role, new_role=new_role,
            holders_before=set(before), holders_after=set(after))
        if refusal is not None:
            raise OrganizationError(
                refusal,
                _REMOVE_MESSAGE if new_role is None
                else _DEMOTE_MESSAGE)

    def check_team_permission_change(
        self, repo_id: int, team_id: int,
        current_role: str, new_role: str,
    ) -> None:
        """Judge an S-189 permission change: raise
        ``last_admin`` when demoting this team's grant
        would leave the repository with no grant-admin
        at all (the team's effective holders judged
        with the new direct permission in place)."""
        repo_row = self._require_repo_row(repo_id)
        before = self._holder_map(repo_row)
        after = self._holder_map(
            repo_row, team_override={team_id: new_role})
        refusal = decide_last_admin(
            current_role=current_role, new_role=new_role,
            holders_before=set(before), holders_after=set(after))
        if refusal is not None:
            raise OrganizationError(refusal, _DEMOTE_MESSAGE)


def render_role_guardrails_page(
    repo: Repository, holders: list[AdminHolder],
) -> str:
    """The repository's role-change guardrails page:
    the last-admin rule said in plain words, then
    every grant-admin holder with the source that
    grants it — every value escaped through S-010."""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Admins — "
        f"{escape_html_text(repo.full_name)} — "
        f"Samverk</title></head>",
        "<body>",
        f"<h1>Admins of "
        f"{escape_html_text(repo.full_name)}</h1>",
        "<p>A repository must always keep at least one "
        "admin: demoting or removing the last admin is "
        "refused, with the reason stated (S-200). The "
        "admins a role change can take away are the "
        "ones a grant gave — a collaborator grant, a "
        "team grant, or the organization's default "
        "permission. The repository's owner, the "
        "owners of the owning organization, and site "
        "admins hold admin by who they are, not by a "
        "grant, and no role change demotes them.</p>",
    ]
    if holders:
        parts.append("<ul>")
        for holder in holders:
            sources = ", ".join(
                source_word(s) for s in holder.sources)
            parts.append(
                f"<li>{escape_html_text(holder.username)} — "
                f"Admin — {escape_html_text(sources)}</li>")
        parts.append("</ul>")
    else:
        parts.append(
            "<p>No one holds admin in this repository "
            "through a grant; its administration rests "
            "with its owner.</p>")
    parts.append("</body></html>")
    return "\n".join(parts)
