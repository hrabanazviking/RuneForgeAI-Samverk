"""Org deletion (S-199).

Owner-only, sudo mode, inventory + grace as S-043;
repos must be transferred or deleted explicitly first.

Deletion is the most irreversible act an organization
can take, so it is built as a process, not a button
(the S-043 shape, restated for organizations):

- **Owner-only.** Only an organization owner (S-186's
  role, judged through S-186's store, which seeds the
  founding owner exactly as everywhere else) may
  request or cancel a deletion. A plain member, a
  stranger, and a site admin who is not an owner are
  all refused ``not_org_owner`` -- the roadmap says
  owner-only and means it. An unknown organization
  is ``org_not_found`` and an unknown actor is
  ``no_such_user``.
- **Inventory first.** ``inventory(org_id)`` counts
  everything the organization holds across every
  store -- repositories, members, teams and their
  members and repository links, invitations,
  outside-collaborator grants in its repositories,
  team-mention notifications, and its policy and
  default-permission rows -- plus the repository
  names themselves and the owner count, so the
  person sees, in numbers, exactly what the act
  will destroy *before* they confirm.
- **Repositories are never swept away.** While the
  organization still owns repositories a request is
  refused ``repos_remaining``: every repository
  must be transferred (S-057) or deleted (S-056)
  explicitly first, by its own process. Execution
  re-judges the same law: a repository that arrived
  during grace blocks ``finalize`` (it answers
  False, the pending record stays, nothing is
  destroyed) until it too is dealt with explicitly.
- **Typed confirmation.** The request must type the
  organization's own name; anything else is refused
  ``confirmation_mismatch`` and schedules nothing
  (S-043's law: strip, case-insensitive, against
  the canonical name).
- **Sudo gate.** The request requires fresh
  re-authentication through the same fail-closed
  seam S-030/S-035 consume (S-036 supplies the real
  verifier); no verifier, no deletion -- the
  refusal is ``sudo_required``.
- **Grace period.** A request records the pending
  deletion and schedules execution ``GRACE_SECONDS``
  (7 days, as S-043) later. Inside grace nothing has
  been destroyed yet and ``cancel`` (owner-only)
  removes the record whole. A second request while
  one is pending is refused ``already_pending``.
- **Execution is the irreversible step**, and only
  it: after grace, ``finalize`` / ``execute_due``
  deletes, in one transaction, the organization's
  mention notifications, invitations, policy and
  default-permission rows, its teams' repository
  links and memberships, its teams, its memberships,
  the pending record, and the organization row
  itself. The audit log is *not* deleted -- it is
  the instance's witness (study 35) -- and the
  request / cancel / execute steps are all audited
  under the existing ``auth.organization.update``
  event with detail ``{"fields": "danger",
  "action": ...}`` (no new taxonomy event -- 122
  events stand: 31 auth, 79 repo, 12 admin).
- **Storage** is migration 78's ``org_deletions``
  table (schema 77 to 78): one pending request per
  organization.
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore
from .audit import AuditLog
from .escaping import escape_html_text
from .organization_members import OrgMembershipStore
from .organizations import (
    Organization, OrganizationError, OrganizationStore)

__all__ = [
    "GRACE_SECONDS", "OrgDeletion", "OrgDeletionInventory",
    "OrgDeletionStore", "PendingOrgDeletion",
    "decide_execution", "decide_request",
    "render_org_deletion_page",
]

GRACE_SECONDS = 7 * 24 * 3600

# Every org-held row execution must clear, judged by
# the inventory. The audit log is deliberately absent
# (see above); repositories are absent too -- they
# block deletion instead of being swept (see above).
_COUNT_QUERIES = (
    ("organization_members",
     "SELECT COUNT(*) c FROM organization_members"
     " WHERE org_id = ?"),
    ("teams",
     "SELECT COUNT(*) c FROM teams WHERE org_id = ?"),
    ("team_members",
     "SELECT COUNT(*) c FROM team_members WHERE team_id IN"
     " (SELECT id FROM teams WHERE org_id = ?)"),
    ("team_repositories",
     "SELECT COUNT(*) c FROM team_repositories WHERE team_id IN"
     " (SELECT id FROM teams WHERE org_id = ?)"),
    ("org_invitations",
     "SELECT COUNT(*) c FROM org_invitations WHERE org_id = ?"),
    ("team_mention_notifications",
     "SELECT COUNT(*) c FROM team_mention_notifications"
     " WHERE org_id = ?"),
    ("org_repo_policies",
     "SELECT COUNT(*) c FROM org_repo_policies WHERE org_id = ?"),
    ("org_default_permissions",
     "SELECT COUNT(*) c FROM org_default_permissions"
     " WHERE org_id = ?"),
)


def decide_request(actor_role: str | None,
                   already_pending: bool,
                   repository_count: int,
                   confirmation_ok: bool,
                   sudo_ok: bool) -> str | None:
    """Pure request judgement: the refusal reason, or
    None when this request may be recorded. The
    order is the order a person meets the refusals:
    ownership, an existing schedule, the repositories
    that must be dealt with explicitly first, the
    typed confirmation, then the sudo gate."""
    if actor_role != "owner":
        return "not_org_owner"
    if already_pending:
        return "already_pending"
    if repository_count > 0:
        return "repos_remaining"
    if not confirmation_ok:
        return "confirmation_mismatch"
    if not sudo_ok:
        return "sudo_required"
    return None


def decide_execution(has_pending: bool, now: int,
                     scheduled_at: int | None,
                     repository_count: int) -> bool:
    """Pure execution judgement: True only when a
    pending deletion exists, its grace has run out,
    and no repository has arrived to block it."""
    if not has_pending or scheduled_at is None:
        return False
    if now < scheduled_at:
        return False
    return repository_count <= 0


@dataclass(frozen=True)
class OrgDeletionInventory:
    org_id: int
    org_name: str
    name_lower: str
    counts: dict[str, int]
    repositories: int
    repository_names: tuple[str, ...]
    owners: int
    pending_invitations: int

    @property
    def total(self) -> int:
        return self.repositories + sum(self.counts.values())


@dataclass(frozen=True)
class PendingOrgDeletion:
    org_id: int
    requested_by: int
    requested_at: int
    scheduled_at: int


class OrgDeletionStore:
    def __init__(
        self, conn: sqlite3.Connection, accounts: AccountStore,
        audit: AuditLog | None = None,
        grace_seconds: int = GRACE_SECONDS,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._audit = audit
        self._grace = grace_seconds
        self._now = time_fn
        self._orgs = OrganizationStore(
            conn, accounts, audit, time_fn=time_fn)
        self._members = OrgMembershipStore(
            conn, accounts, audit, time_fn=time_fn)

    # -- guards --------------------------------------
    def _require_org(self, org_id: int) -> Organization:
        org = self._orgs.get_by_id(org_id)
        if org is None:
            raise OrganizationError(
                "org_not_found", "No such organization.")
        return org

    def _require_user(self, user_id: int):
        user = self._accounts.get_by_id(user_id)
        if user is None:
            raise OrganizationError(
                "no_such_user", "No such account.")
        return user

    def _require_owner(self, actor_id: int,
                       org: Organization):
        actor = self._require_user(actor_id)
        # role_for seeds the founding owner (S-186).
        role = self._members.role_for(actor.id, org.id)
        if role != "owner":
            raise OrganizationError(
                "not_org_owner",
                "Only an organization owner can delete "
                "this organization.")
        return actor

    def _audit_event(self, actor_id: int, org: Organization,
               action: str, source_ip: str | None,
               detail_extra: dict | None = None):
        if self._audit is None:
            return
        detail: dict = {"fields": "danger", "action": action}
        if detail_extra:
            detail.update(detail_extra)
        self._audit.append(
            actor_kind="user", actor_id=actor_id,
            action="auth.organization.update",
            target_kind="organization",
            target_id=org.name_lower, outcome="success",
            source_ip=source_ip, detail=detail)

    # -- inventory -----------------------------------
    def _repo_rows(self, org: Organization):
        return self._conn.execute(
            "SELECT name FROM repositories"
            " WHERE owner_lower = ? ORDER BY name_lower",
            (org.name_lower,)).fetchall()

    def inventory(self, org_id: int) -> OrgDeletionInventory:
        org = self._require_org(org_id)
        counts: dict[str, int] = {}
        for key, query in _COUNT_QUERIES:
            row = self._conn.execute(query, (org.id,)).fetchone()
            counts[key] = int(row["c"])
        repo_rows = self._repo_rows(org)
        outside = self._conn.execute(
            "SELECT COUNT(*) c FROM outside_collaborators"
            " WHERE repo_id IN (SELECT id FROM repositories"
            " WHERE owner_lower = ?)",
            (org.name_lower,)).fetchone()
        counts["outside_collaborators"] = int(outside["c"])
        owners = self._conn.execute(
            "SELECT COUNT(*) c FROM organization_members"
            " WHERE org_id = ? AND role = 'owner'",
            (org.id,)).fetchone()
        pending_inv = self._conn.execute(
            "SELECT COUNT(*) c FROM org_invitations"
            " WHERE org_id = ? AND status = 'pending'",
            (org.id,)).fetchone()
        return OrgDeletionInventory(
            org_id=org.id, org_name=org.name,
            name_lower=org.name_lower, counts=counts,
            repositories=len(repo_rows),
            repository_names=tuple(
                str(r["name"]) for r in repo_rows),
            owners=int(owners["c"]),
            pending_invitations=int(pending_inv["c"]))

    # -- pending record ------------------------------
    def pending_for(self, org_id: int) -> PendingOrgDeletion | None:
        row = self._conn.execute(
            "SELECT * FROM org_deletions WHERE org_id = ?",
            (org_id,)).fetchone()
        if row is None:
            return None
        return PendingOrgDeletion(
            org_id=row["org_id"],
            requested_by=row["requested_by"],
            requested_at=row["requested_at"],
            scheduled_at=row["scheduled_at"])

    def is_pending(self, org_id: int) -> bool:
        return self.pending_for(org_id) is not None

    # -- the process ---------------------------------
    def request(
        self, actor_id: int, org_id: int,
        typed_confirmation: object,
        reauth_verifier: Callable[[int], bool] | None = None,
        *, source_ip: str | None = None,
    ) -> PendingOrgDeletion:
        org = self._require_org(org_id)
        actor = self._require_user(actor_id)
        role = self._members.role_for(actor.id, org.id)
        inv = self.inventory(org.id)
        confirmation_ok = (
            isinstance(typed_confirmation, str)
            and typed_confirmation.strip().lower()
            == org.name_lower)
        sudo_ok = bool(
            reauth_verifier is not None
            and reauth_verifier(actor.id))
        refusal = decide_request(
            role, self.pending_for(org.id) is not None,
            inv.repositories, confirmation_ok, sudo_ok)
        if refusal == "not_org_owner":
            raise OrganizationError(
                "not_org_owner",
                "Only an organization owner can delete "
                "this organization.")
        if refusal == "already_pending":
            raise OrganizationError(
                "already_pending",
                "Deletion is already scheduled for "
                "this organization.")
        if refusal == "repos_remaining":
            raise OrganizationError(
                "repos_remaining",
                "This organization still owns "
                f"{inv.repositories} "
                f"{'repository' if inv.repositories == 1 else 'repositories'}"
                " (" + ", ".join(inv.repository_names) + "). "
                "Transfer or delete each repository "
                "explicitly first; organization deletion "
                "never sweeps a repository away.")
        if refusal == "confirmation_mismatch":
            raise OrganizationError(
                "confirmation_mismatch",
                "Type the organization's name exactly "
                "to confirm deletion.")
        if refusal == "sudo_required":
            raise OrganizationError(
                "sudo_required",
                "Deletion needs a fresh password "
                "confirmation; confirm and try again.")
        now = int(self._now())
        scheduled = now + self._grace
        pending = PendingOrgDeletion(
            org.id, actor.id, now, scheduled)
        with self._conn:
            self._conn.execute(
                "INSERT INTO org_deletions"
                " (org_id, requested_by, requested_at,"
                " scheduled_at) VALUES (?, ?, ?, ?)",
                (pending.org_id, pending.requested_by,
                 pending.requested_at, pending.scheduled_at))
        self._audit_event(actor.id, org, "request_deletion",
                    source_ip, {"scheduled_at": scheduled})
        return pending

    def cancel(self, actor_id: int, org_id: int,
               *, source_ip: str | None = None) -> bool:
        org = self._require_org(org_id)
        actor = self._require_owner(actor_id, org)
        if self.pending_for(org.id) is None:
            return False
        with self._conn:
            self._conn.execute(
                "DELETE FROM org_deletions WHERE org_id = ?",
                (org.id,))
        self._audit_event(actor.id, org, "cancel_deletion", source_ip)
        return True

    def finalize(self, org_id: int,
                 *, source_ip: str | None = None) -> bool:
        """Execute one pending deletion whose grace
        has run out. Not due, not pending, or blocked
        by a repository that arrived during grace
        answers False and destroys nothing."""
        pending = self.pending_for(org_id)
        if pending is None:
            return False
        org = self._orgs.get_by_id(org_id)
        if org is None:
            with self._conn:
                self._conn.execute(
                    "DELETE FROM org_deletions WHERE org_id = ?",
                    (org_id,))
            return False
        repo_count = len(self._repo_rows(org))
        if not decide_execution(
                True, int(self._now()), pending.scheduled_at,
                repo_count):
            return False
        with self._conn:
            self._conn.execute(
                "DELETE FROM team_mention_notifications"
                " WHERE org_id = ?", (org.id,))
            self._conn.execute(
                "DELETE FROM org_invitations WHERE org_id = ?",
                (org.id,))
            self._conn.execute(
                "DELETE FROM org_repo_policies WHERE org_id = ?",
                (org.id,))
            self._conn.execute(
                "DELETE FROM org_default_permissions"
                " WHERE org_id = ?", (org.id,))
            self._conn.execute(
                "DELETE FROM team_repositories WHERE team_id IN"
                " (SELECT id FROM teams WHERE org_id = ?)",
                (org.id,))
            self._conn.execute(
                "DELETE FROM team_members WHERE team_id IN"
                " (SELECT id FROM teams WHERE org_id = ?)",
                (org.id,))
            self._conn.execute(
                "DELETE FROM teams WHERE org_id = ?", (org.id,))
            self._conn.execute(
                "DELETE FROM organization_members"
                " WHERE org_id = ?", (org.id,))
            self._conn.execute(
                "DELETE FROM org_deletions WHERE org_id = ?",
                (org.id,))
            self._conn.execute(
                "DELETE FROM organizations WHERE id = ?",
                (org.id,))
        self._audit_event(pending.requested_by, org,
                    "execute_deletion", source_ip,
                    {"org": org.name_lower})
        return True

    def execute_due(self) -> list[int]:
        rows = self._conn.execute(
            "SELECT org_id FROM org_deletions"
            " WHERE scheduled_at <= ? ORDER BY org_id",
            (int(self._now()),)).fetchall()
        return [int(r["org_id"]) for r in rows
                if self.finalize(int(r["org_id"]))]


# The S-043/S-056 class-name shape, as an alias.
OrgDeletion = OrgDeletionStore


def _stamp(ts: int) -> str:
    return time.strftime(
        "%Y-%m-%d %H:%M UTC", time.gmtime(ts))


def render_org_deletion_page(
        org: Organization, inventory: OrgDeletionInventory,
        pending: PendingOrgDeletion | None = None) -> str:
    """The danger-zone page: the inventory in numbers
    and words, the repository block stated plainly,
    and the grace law. Every value the organization
    controls reaches HTML only through S-010."""
    name = escape_html_text(org.effective_display_name())
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Delete organization \u2014 {name}"
        " \u2014 Samverk</title></head>",
        "<body>",
        f"<h1>Delete {name}</h1>",
        "<p>Deleting an organization is permanent. "
        "Only an organization owner can do it, it "
        "needs a fresh password confirmation, and "
        "typing the organization's name confirms it.</p>",
        "<p>What this organization holds now:</p>",
        "<ul>",
        f"<li>{inventory.repositories} "
        f"{'repository' if inventory.repositories == 1 else 'repositories'}</li>",
        f"<li>{inventory.counts.get('organization_members', 0)} members "
        f"({inventory.owners} "
        f"{'owner' if inventory.owners == 1 else 'owners'})</li>",
        f"<li>{inventory.counts.get('teams', 0)} teams, "
        f"{inventory.counts.get('team_members', 0)} team memberships, "
        f"{inventory.counts.get('team_repositories', 0)} team repository links</li>",
        f"<li>{inventory.counts.get('org_invitations', 0)} invitations "
        f"({inventory.pending_invitations} pending)</li>",
        f"<li>{inventory.counts.get('outside_collaborators', 0)} "
        "outside collaborator grants in its repositories</li>",
        f"<li>{inventory.counts.get('team_mention_notifications', 0)} "
        "team mention notifications</li>",
        "</ul>",
    ]
    if inventory.repositories:
        repo_list = ", ".join(
            escape_html_text(n) for n in inventory.repository_names)
        parts.append(
            "<p>This organization still owns repositories: "
            f"{repo_list}. Transfer or delete each "
            "repository explicitly first; organization "
            "deletion never sweeps a repository away.</p>")
    if pending is not None:
        parts.append(
            "<p>Deletion is scheduled for "
            f"{escape_html_text(_stamp(pending.scheduled_at))}. "
            "Until then nothing has been destroyed and "
            "an owner can cancel it whole.</p>")
    else:
        parts.append(
            "<p>A deletion request starts a 7-day grace "
            "period. Inside grace nothing is destroyed "
            "and an owner can cancel the request whole; "
            "after grace the organization and everything "
            "in the inventory above are deleted for good. "
            "The audit log is kept: it is the "
            "instance's witness.</p>")
    parts.append("</body></html>")
    return "\n".join(parts)
