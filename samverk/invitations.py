"""Organization invitations (S-193).

Invite by username or email, expiring,
rescindable; acceptance creates membership and
audit events on both sides.

- **One target, two forms.** An invitation names
  exactly one target: a username, resolved through
  ``AccountStore.get_by_username`` (an unknown name
  is refused ``no_such_user``), or an email address,
  judged by ``samverk.accounts.validate_email`` (a
  malformed address is refused ``email_invalid``).
  Both forms given, or neither, is refused
  ``invitation_target_invalid``. When the email
  matches an existing account the invitation is
  linked to that account; otherwise the email alone
  is stored (``invitee_user_id`` NULL) for an
  account a future registration may claim.
- **Roles are S-186 membership roles.** An
  invitation carries an ``owner`` / ``member``
  role, judged by
  ``organization_members.validate_role``
  (``role_invalid`` otherwise); the default is
  ``member``. Acceptance creates the membership
  with exactly this role.
- **Only stewardship invites and rescinds.**
  Inviting and rescinding are organization owner /
  site admin acts (``not_org_owner`` otherwise,
  ``org_not_found`` for an organization that does
  not exist, ``no_such_user`` for an actor that
  does not).
- **No duplicates, no members.** Inviting someone
  already a member is refused ``already_member``
  (judged through S-186's store); inviting someone
  with a live pending invitation to the same
  organization is refused ``already_invited`` — a
  pending invitation past its expiry does not
  block a fresh invite.
- **Expiry is judged, never rewritten.** An
  invitation lives ``INVITATION_TTL_SECONDS``
  (seven days) from its creation. The pure
  ``decide_invitation_state`` judges a stored row
  as ``pending`` / ``expired`` / ``accepted`` /
  ``rescinded`` and ``state_word`` says it in
  words; an expired row keeps its stored
  ``pending`` status — expiry is a judgement, not
  a silent rewrite. Accepting or rescinding an
  expired invitation is refused
  ``invitation_expired``; one whose stored status
  is not pending is refused
  ``invitation_not_pending``.
- **Acceptance is the invitee's alone.** The
  accepting account must be the invitee — its id
  matches ``invitee_user_id``, or, for an
  email-only invitation, its email matches
  ``invitee_email`` case-insensitively — anyone
  else is refused ``invitation_not_for_you``. An
  unknown invitation is ``invitation_not_found``
  and an invitee who has since become a member is
  refused ``already_member``. Acceptance creates
  the membership (``added_by`` is the inviter,
  after ensuring the founding owner exactly as
  S-186's store does) and marks the invitation
  accepted in one transaction.
- **Audit on both sides.** Acceptance writes TWO
  ``auth.organization.update`` events — one
  targeted at the organization (detail
  ``{"fields": "invitations", "action":
  "accept", "target": <invitee>}``) and one
  targeted at the user (detail ``{"fields":
  "invitations", "action": "accept", "org":
  <org>}``) — the actor of both is the accepting
  user. Inviting and rescinding each write ONE
  org-targeted event (actions ``invite`` /
  ``rescind``). No new taxonomy event — 122 stand:
  31 auth / 79 repo / 12 admin. Refusals write
  nothing and audit nothing; writes commit before
  answering.
- **Storage** is migration 75's ``org_invitations``
  table (schema 74 to 75): one row per invitation,
  its target, role, inviter, status and times.
  Organizations, accounts and memberships stay
  S-185/S-025/S-186 ground and are only read here.
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, RegistrationError, User, validate_email
from .audit import AuditLog
from .escaping import escape_html_text
from .organization_members import OrgMembershipStore, role_word, validate_role
from .organizations import OrganizationError

__all__ = [
    "INVITATION_TTL_SECONDS", "Invitation",
    "InvitationStore", "decide_invitation_state",
    "render_invitations_page", "state_word",
]

INVITATION_TTL_SECONDS = 7 * 24 * 3600

_STATE_WORDS = {
    "pending": "Pending", "expired": "Expired",
    "accepted": "Accepted", "rescinded": "Rescinded",
}


def state_word(state: str) -> str:
    """An invitation state said in a word a person
    reads."""
    return _STATE_WORDS.get(state, state)


def decide_invitation_state(status: str, expires_at: int,
                            now: int) -> str:
    """Pure state judgement: a stored ``accepted``
    or ``rescinded`` row stays itself at any time; a
    stored ``pending`` row is ``expired`` once
    ``now`` reaches ``expires_at``, else
    ``pending``. Expiry is judged here, never
    written back over the stored status."""
    if status != "pending":
        return status
    if now >= expires_at:
        return "expired"
    return "pending"


@dataclass(frozen=True)
class Invitation:
    """One invitation: its organization, its target
    (an account, an email, or an email already linked
    to an account), the role it carries, who sent it,
    its stored status and its times."""
    id: int
    org_id: int
    org_name: str
    org_name_lower: str
    invitee_user_id: int | None
    invitee_username: str | None
    invitee_username_lower: str | None
    invitee_email: str | None
    invitee_email_lower: str | None
    role: str
    invited_by: int
    invited_by_username: str | None
    status: str
    created_at: int
    expires_at: int
    resolved_at: int | None

    def state(self, now: int) -> str:
        """This invitation's judged state at ``now``."""
        return decide_invitation_state(
            self.status, self.expires_at, now)

    def target_label(self) -> str:
        """The invitee as one label: the username when
        the invitation is linked to an account, else
        the email it was sent to."""
        return self.invitee_username or self.invitee_email or ""

    def audit_target(self) -> str:
        """The canonical audit target for this
        invitation: the invitee's username_lower, or
        the email_lower for an email-only invite."""
        return (self.invitee_username_lower
                or self.invitee_email_lower or "")


_SELECT = (
    "SELECT i.id AS id, i.org_id AS org_id,"
    " o.name AS org_name, o.name_lower AS org_name_lower,"
    " i.invitee_user_id AS invitee_user_id,"
    " u.username AS invitee_username,"
    " u.username_lower AS invitee_username_lower,"
    " i.invitee_email AS invitee_email,"
    " i.invitee_email_lower AS invitee_email_lower,"
    " i.role AS role, i.invited_by AS invited_by,"
    " b.username AS invited_by_username,"
    " i.status AS status, i.created_at AS created_at,"
    " i.expires_at AS expires_at,"
    " i.resolved_at AS resolved_at"
    " FROM org_invitations i"
    " JOIN organizations o ON o.id = i.org_id"
    " LEFT JOIN users u ON u.id = i.invitee_user_id"
    " LEFT JOIN users b ON b.id = i.invited_by")


def _row_to_invitation(row: sqlite3.Row) -> Invitation:
    return Invitation(
        id=row["id"], org_id=row["org_id"],
        org_name=row["org_name"],
        org_name_lower=row["org_name_lower"],
        invitee_user_id=row["invitee_user_id"],
        invitee_username=row["invitee_username"],
        invitee_username_lower=row["invitee_username_lower"],
        invitee_email=row["invitee_email"],
        invitee_email_lower=row["invitee_email_lower"],
        role=row["role"], invited_by=row["invited_by"],
        invited_by_username=row["invited_by_username"],
        status=row["status"], created_at=row["created_at"],
        expires_at=row["expires_at"],
        resolved_at=row["resolved_at"])


class InvitationStore:
    def __init__(
        self, conn: sqlite3.Connection, accounts: AccountStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._audit = audit
        self._now = time_fn
        self._members = OrgMembershipStore(
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
        if self._members.role_for(actor.id, org_row["id"]) != "owner":
            raise OrganizationError(
                "not_org_owner",
                "Only an organization owner or a site admin "
                "can manage this organization's invitations.")
        return actor

    def _require_invitation(self, invitation_id: int) -> Invitation:
        invitation = self.get_invitation(invitation_id)
        if invitation is None:
            raise OrganizationError(
                "invitation_not_found", "No such invitation.")
        return invitation

    def _require_live_pending(self, invitation: Invitation,
                              now: int) -> None:
        """Refuse a stored non-pending invitation, then
        a pending one past its expiry — in that order."""
        if invitation.status != "pending":
            raise OrganizationError(
                "invitation_not_pending",
                "That invitation has already been resolved.")
        if decide_invitation_state(
                invitation.status, invitation.expires_at,
                now) == "expired":
            raise OrganizationError(
                "invitation_expired",
                "That invitation has expired.")

    def _audit_org(self, actor: User, org_name_lower: str,
                   action: str, target: str,
                   source_ip: str | None = None):
        if self._audit is None:
            return
        self._audit.append(
            actor_kind="user", actor_id=actor.id,
            action="auth.organization.update",
            target_kind="organization",
            target_id=org_name_lower,
            outcome="success", source_ip=source_ip,
            detail={"fields": "invitations", "action": action,
                    "target": target})

    # -- reads ----------------------------------------
    def get_invitation(self, invitation_id: int) -> Invitation | None:
        row = self._conn.execute(
            _SELECT + " WHERE i.id = ?",
            (invitation_id,)).fetchone()
        return _row_to_invitation(row) if row else None

    def list_invitations(self, org_id: int) -> list[Invitation]:
        """Every invitation of one organization, in
        creation order. An unknown organization is
        ``org_not_found``."""
        self._require_org_row(org_id)
        rows = self._conn.execute(
            _SELECT + " WHERE i.org_id = ?"
            " ORDER BY i.created_at, i.id", (org_id,)).fetchall()
        return [_row_to_invitation(r) for r in rows]

    def list_for_user(self, user_id: int) -> list[Invitation]:
        """The live pending invitations addressed to
        one account — by its id, or by its email for
        invitations sent before it registered — in
        creation order. An unknown account is
        ``no_such_user``."""
        user = self._accounts.get_by_id(user_id)
        if user is None:
            raise OrganizationError(
                "no_such_user", "No such account.")
        email_lower = user.email.lower() if user.email else None
        rows = self._conn.execute(
            _SELECT + " WHERE i.invitee_user_id = ?"
            " OR (? IS NOT NULL AND i.invitee_email_lower = ?)"
            " ORDER BY i.created_at, i.id",
            (user_id, email_lower, email_lower)).fetchall()
        now = int(self._now())
        return [inv for inv in
                (_row_to_invitation(r) for r in rows)
                if inv.state(now) == "pending"]

    # -- writes ---------------------------------------
    def invite(
        self, actor_id: int, org_id: int,
        username: object = None, email: object = None,
        role: object = "member",
        source_ip: str | None = None,
    ) -> Invitation:
        """Invite one person to the organization, by
        username or by email — exactly one form.
        Stewardship only; the invitation expires
        ``INVITATION_TTL_SECONDS`` after creation."""
        org_row = self._require_org_row(org_id)
        actor = self._require_owner_or_admin(actor_id, org_row)
        clean_role = validate_role(role)
        has_username = isinstance(username, str) and bool(username.strip())
        has_email = isinstance(email, str) and bool(email.strip())
        if has_username == has_email:
            raise OrganizationError(
                "invitation_target_invalid",
                "Invite by a username or by an email "
                "address — exactly one of the two.")
        invitee_user_id: int | None = None
        invitee_email: str | None = None
        invitee_email_lower: str | None = None
        if has_username:
            target = self._accounts.get_by_username(username)  # type: ignore[arg-type]
            if target is None:
                raise OrganizationError(
                    "no_such_user", "No such account.")
            invitee_user_id = target.id
        else:
            try:
                clean_email = validate_email(email)
            except RegistrationError:
                raise OrganizationError(
                    "email_invalid",
                    "That email address is not valid.") from None
            if clean_email is None:
                raise OrganizationError(
                    "email_invalid",
                    "That email address is not valid.")
            invitee_email = clean_email
            invitee_email_lower = clean_email.lower()
            existing = self._accounts.get_by_email(clean_email)
            if existing is not None:
                invitee_user_id = existing.id
        if (invitee_user_id is not None
                and self._members.role_for(
                    invitee_user_id, org_id) is not None):
            raise OrganizationError(
                "already_member",
                "That person is already a member of "
                "this organization.")
        now = int(self._now())
        rows = self._conn.execute(
            "SELECT status, expires_at FROM org_invitations"
            " WHERE org_id = ? AND ((? IS NOT NULL"
            " AND invitee_user_id = ?) OR (? IS NOT NULL"
            " AND invitee_email_lower = ?))",
            (org_id, invitee_user_id, invitee_user_id,
             invitee_email_lower, invitee_email_lower)).fetchall()
        for row in rows:
            if decide_invitation_state(
                    row["status"], row["expires_at"],
                    now) == "pending":
                raise OrganizationError(
                    "already_invited",
                    "That person already has a pending "
                    "invitation to this organization.")
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO org_invitations"
                " (org_id, invitee_user_id, invitee_email,"
                " invitee_email_lower, role, invited_by,"
                " status, created_at, expires_at, resolved_at)"
                " VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, NULL)",
                (org_id, invitee_user_id, invitee_email,
                 invitee_email_lower, clean_role, actor.id,
                 now, now + INVITATION_TTL_SECONDS))
        invitation = self.get_invitation(int(cur.lastrowid))
        assert invitation is not None
        self._audit_org(actor, org_row["name_lower"], "invite",
                        invitation.audit_target(),
                        source_ip=source_ip)
        return invitation

    def rescind(self, actor_id: int, invitation_id: int,
                source_ip: str | None = None) -> Invitation:
        """Rescind one live pending invitation.
        Stewardship only; the row is kept, marked
        rescinded, as the record of the act."""
        invitation = self._require_invitation(invitation_id)
        org_row = self._require_org_row(invitation.org_id)
        actor = self._require_owner_or_admin(actor_id, org_row)
        now = int(self._now())
        self._require_live_pending(invitation, now)
        with self._conn:
            self._conn.execute(
                "UPDATE org_invitations SET status = 'rescinded',"
                " resolved_at = ? WHERE id = ?", (now, invitation.id))
        self._audit_org(actor, org_row["name_lower"], "rescind",
                        invitation.audit_target(),
                        source_ip=source_ip)
        result = self.get_invitation(invitation.id)
        assert result is not None
        return result

    def accept(self, user_id: int, invitation_id: int,
               source_ip: str | None = None) -> Invitation:
        """Accept an invitation: the invitee alone may.
        Creates the membership with the invitation's
        role and marks the invitation accepted, in one
        transaction, then audits on both sides."""
        invitation = self._require_invitation(invitation_id)
        user = self._accounts.get_by_id(user_id)
        if user is None:
            raise OrganizationError(
                "no_such_user", "No such account.")
        now = int(self._now())
        self._require_live_pending(invitation, now)
        if invitation.invitee_user_id is not None:
            if invitation.invitee_user_id != user.id:
                raise OrganizationError(
                    "invitation_not_for_you",
                    "That invitation was sent to someone else.")
        elif (not user.email or not invitation.invitee_email_lower
                or user.email.lower()
                != invitation.invitee_email_lower):
            raise OrganizationError(
                "invitation_not_for_you",
                "That invitation was sent to a different "
                "email address.")
        org_row = self._require_org_row(invitation.org_id)
        if self._members.role_for(user.id, invitation.org_id) is not None:
            raise OrganizationError(
                "already_member",
                "You are already a member of this organization.")
        with self._conn:
            self._conn.execute(
                "INSERT INTO organization_members"
                " (org_id, user_id, role, added_by,"
                " created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (invitation.org_id, user.id, invitation.role,
                 invitation.invited_by, now, now))
            self._conn.execute(
                "UPDATE org_invitations SET status = 'accepted',"
                " resolved_at = ? WHERE id = ?",
                (now, invitation.id))
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user.id,
                action="auth.organization.update",
                target_kind="organization",
                target_id=org_row["name_lower"],
                outcome="success", source_ip=source_ip,
                detail={"fields": "invitations",
                        "action": "accept",
                        "target": user.username_lower})
            self._audit.append(
                actor_kind="user", actor_id=user.id,
                action="auth.organization.update",
                target_kind="user", target_id=user.username_lower,
                outcome="success", source_ip=source_ip,
                detail={"fields": "invitations",
                        "action": "accept",
                        "org": org_row["name_lower"]})
        result = self.get_invitation(invitation.id)
        assert result is not None
        return result


def render_invitations_page(invitations: list[Invitation],
                            now: int) -> str:
    """The invitations page: every invitation's
    target, role and state said in words — Pending,
    Expired, Accepted, Rescinded — with the seven-day
    expiry stated plainly; every value escaped
    through S-010, the state in text, never
    colour-only."""
    org_name = invitations[0].org_name if invitations else ""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Invitations — {escape_html_text(org_name)} "
        f"— Samverk</title></head>",
        "<body>",
        f"<h1>Invitations — {escape_html_text(org_name)}</h1>",
        "<p>An invitation expires seven days after it is "
        "sent; an expired invitation can no longer be "
        "accepted, and a fresh one may be sent in its "
        "place. Only an organization owner or a site "
        "admin can invite or rescind.</p>",
        "<ul>",
    ]
    for invitation in invitations:
        target = escape_html_text(invitation.target_label())
        word = escape_html_text(
            state_word(invitation.state(now)))
        role = escape_html_text(role_word(invitation.role))
        parts.append(
            f"<li>{target} — {role} — {word}</li>")
    parts.append("</ul></body></html>")
    return "\n".join(parts)
