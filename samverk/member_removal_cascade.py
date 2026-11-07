"""Member removal cascade (S-194).

What happens to assignments, reviews, and
ownerships on removal is computed and shown
*before* confirming.

- **A pure preview, like S-188's.** ``preview_removal``
  computes the whole cascade of removing one member
  from one organization — as structured data, as a
  plain-words summary, and as a page a person reads
  *before* confirming — and writes nothing, audits
  nothing, and removes nobody. Removal itself stays
  S-186's act, through ``OrgMembershipStore``'s
  existing doors; this slice builds no second door
  and deletes no row of any kind.
- **Refusals are reported, not raised.** A target
  who is not a member, and the last owner (S-186's
  invariant, judged by S-186's own ``decide_removal``),
  come back in the preview's ``allowed`` flag and
  ``reason`` — ``not_a_member`` / ``last_owner`` —
  with the law said in plain words in ``message``,
  so the page can show exactly why a removal cannot
  proceed. Only a missing organization
  (``org_not_found``) or a missing account
  (``no_such_user``) raises, exactly as the
  neighbouring stores' reads raise. The pure
  ``decide_cascade`` is the whole refusal law.
- **The cascade, category by category** — every
  fact read from the landed stores and tables, all
  scoped to repositories the organization owns
  unless a category says otherwise:
  (a) the member's organization role, the owner
  count behind it, and the S-192 default repository
  permission their membership currently floors them
  at in every organization repository;
  (b) team memberships — the teams they belong to
  directly, and the teams they belong to only by
  S-188 inheritance (an ancestor's membership flows
  down into them) — plus the repository links, with
  their S-189 permissions, carried by the teams they
  belong to directly;
  (c) issue and pull request assignments in the
  organization's repositories (S-126's rows), which
  removal leaves pointing at a non-member until
  someone reassigns the work;
  (d) review requests still standing against them
  in the organization's repositories (S-151/S-152's
  rows, requested and dismissed said apart), and
  the reviews they have submitted and have pending
  there (S-148's rows) — submitted reviews stay on
  the record; what ends is the standing to answer
  new requests as a member;
  (e) ownerships: the organization's repositories
  (access through membership, teams and the default
  ends for all of them), any outside-collaborator
  grant they hold in an organization repository
  (S-191's table — a member needs none, so a row
  here is a leftover the preview surfaces rather
  than hides), and their own personally owned
  repositories, which removal does not touch;
  (f) pending invitations they sent to this
  organization (S-193), which stay sent — rescinding
  one stays the sender's or a steward's separate
  act — and the open issues and pull requests they
  authored in the organization's repositories, whose
  authorship likewise stays on the record. Whether
  the member founded the organization is stated,
  because a founder who is not its last owner can
  still be removed, and the page should say so
  plainly rather than let anyone guess.
- **No migration, no new taxonomy event.** The
  preview stores nothing of its own (schema stays
  75) and audits nothing (122 events stand:
  31 auth / 79 repo / 12 admin); organizations,
  memberships, teams, assignments, reviews, grants
  and invitations stay S-185/S-186/S-187/S-188/
  S-126/S-148/S-151/S-152/S-191/S-192/S-193 ground
  and are only read here.
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .default_permissions import DefaultPermissionStore
from .escaping import escape_html_text
from .invitations import InvitationStore
from .organization_members import (
    OrgMembershipStore, decide_removal, role_word)
from .organizations import Organization, OrganizationError
from .outside_collaborators import OutsideCollaboratorStore
from .team_nesting import NestedTeamStore
from .teams import TeamStore

__all__ = [
    "AssignmentRef", "CascadeStore", "GrantRef",
    "InvitationRef", "ItemRef", "RemovalCascade",
    "RepoRef", "ReviewRef", "ReviewRequestRef",
    "TeamRef", "TeamRepoRef", "decide_cascade",
    "render_removal_cascade_page",
]


def decide_cascade(member_role: str | None,
                   owner_count: int) -> str | None:
    """Pure removal-cascade law: the refusal reason,
    or None when the removal may proceed. A
    non-member has nothing to remove
    (``not_a_member``); S-186's last-owner rule is
    judged by S-186's own ``decide_removal``."""
    if member_role is None:
        return "not_a_member"
    return decide_removal(member_role, owner_count)


@dataclass(frozen=True)
class TeamRef:
    """One team the member belongs to, and how:
    ``direct``, or ``inherited`` through an
    ancestor team (S-188)."""
    team_id: int
    name: str
    via: str                     # 'direct' | 'inherited'

    @property
    def words(self) -> str:
        if self.via == "inherited":
            return f"{self.name} (through an ancestor team)"
        return self.name


@dataclass(frozen=True)
class TeamRepoRef:
    """One repository link carried by a team the
    member belongs to directly, with the S-189
    permission the link carries."""
    team_name: str
    repo: str                    # "owner/name"
    permission: str

    @property
    def words(self) -> str:
        return f"{self.repo} via {self.team_name} ({self.permission})"


@dataclass(frozen=True)
class AssignmentRef:
    """One assignment of the member in an
    organization repository (S-126)."""
    repo: str                    # "owner/name"
    number: int
    kind: str                    # 'issue' | 'pull_request'
    title: str
    state: str                   # 'open' | 'closed'

    @property
    def words(self) -> str:
        kind = "pull request" if self.kind == "pull_request" else "issue"
        return (f"{self.repo} {kind} #{self.number} "
                f"\"{self.title}\" ({self.state})")


@dataclass(frozen=True)
class ReviewRequestRef:
    """One review request recorded against the
    member in an organization repository
    (S-151/S-152)."""
    repo: str                    # "owner/name"
    number: int
    owner_ref: str
    source: str                  # 'manual' | 'codeowners'
    state: str                   # 'requested' | 'dismissed'

    @property
    def words(self) -> str:
        return (f"{self.repo} pull request #{self.number} — "
                f"{self.owner_ref} ({self.source}, {self.state})")


@dataclass(frozen=True)
class ReviewRef:
    """One review by the member in an organization
    repository (S-148): submitted, or still a
    pending draft when ``pending`` is true."""
    repo: str                    # "owner/name"
    number: int
    verdict: str                 # stored verdict word; '' while unchosen
    pending: bool

    @property
    def words(self) -> str:
        if self.pending:
            verdict = self.verdict or "no verdict chosen yet"
            return (f"{self.repo} pull request #{self.number} — "
                    f"pending draft ({verdict})")
        return (f"{self.repo} pull request #{self.number} — "
                f"{self.verdict}")


@dataclass(frozen=True)
class GrantRef:
    """One outside-collaborator grant the member
    holds in an organization repository (S-191)."""
    repo: str                    # "owner/name"
    role: str

    @property
    def words(self) -> str:
        return f"{self.repo} ({self.role})"


@dataclass(frozen=True)
class InvitationRef:
    """One pending invitation the member sent to
    this organization (S-193)."""
    target: str                  # username or email label
    role: str

    @property
    def words(self) -> str:
        return f"{self.target} (as {self.role})"


@dataclass(frozen=True)
class RepoRef:
    """One repository named by the cascade."""
    full_name: str               # "owner/name"
    visibility: str

    @property
    def words(self) -> str:
        return f"{self.full_name} ({self.visibility})"


@dataclass(frozen=True)
class ItemRef:
    """One open item the member authored in an
    organization repository; authorship stays on
    the record after removal."""
    repo: str                    # "owner/name"
    number: int
    kind: str                    # 'issue' | 'pull_request'
    title: str

    @property
    def words(self) -> str:
        kind = "pull request" if self.kind == "pull_request" else "issue"
        return f"{self.repo} {kind} #{self.number} \"{self.title}\""


@dataclass(frozen=True)
class RemovalCascade:
    """The whole effect of removing one member from
    one organization, computed before anything is
    confirmed. ``allowed`` is False exactly when
    ``reason`` names a refusal."""
    org_id: int
    org_name: str
    user_id: int
    username: str
    is_member: bool
    role: str | None             # 'owner' | 'member' | None
    owner_count: int
    allowed: bool
    reason: str | None           # 'not_a_member' | 'last_owner' | None
    message: str                 # the position in plain words
    is_org_creator: bool
    default_permission: str      # S-192 rung, or 'none'
    direct_teams: tuple = ()         # of TeamRef
    inherited_teams: tuple = ()      # of TeamRef
    team_repos: tuple = ()           # of TeamRepoRef
    assignments: tuple = ()          # of AssignmentRef
    review_requests: tuple = ()      # of ReviewRequestRef
    submitted_reviews: tuple = ()    # of ReviewRef, pending=False
    pending_reviews: tuple = ()      # of ReviewRef, pending=True
    collaborator_grants: tuple = ()  # of GrantRef
    invitations_sent: tuple = ()     # of InvitationRef, pending only
    org_repositories: tuple = ()     # of RepoRef
    personal_repositories: tuple = ()  # of RepoRef
    authored_open: tuple = ()        # of ItemRef

    @property
    def is_last_owner(self) -> bool:
        return self.reason == "last_owner"

    @property
    def standing_review_requests(self) -> tuple:
        """The review requests still awaiting the
        member: recorded, and not dismissed."""
        return tuple(r for r in self.review_requests
                     if r.state == "requested")

    @property
    def ending_count(self) -> int:
        """How many ties removal itself ends: team
        memberships (direct and inherited), team
        repository links, assignments, standing
        review requests, and collaborator grants."""
        return (len(self.direct_teams) + len(self.inherited_teams)
                + len(self.team_repos) + len(self.assignments)
                + len(self.standing_review_requests)
                + len(self.collaborator_grants))

    def summary(self) -> str:
        """The cascade in one plain sentence (the
        fuller account is ``message`` and the page)."""
        if self.reason == "not_a_member":
            return (f"{self.username} is not a member of "
                    f"{self.org_name}, so there is nothing "
                    f"to remove.")
        if self.reason == "last_owner":
            return (f"{self.username} is the last owner of "
                    f"{self.org_name}: removal is refused.")
        if self.ending_count == 0:
            return (f"Removing {self.username} from "
                    f"{self.org_name} would end nothing else: "
                    f"no teams, assignments, standing review "
                    f"requests or grants are tied to the "
                    f"membership.")
        return (f"Removing {self.username} from {self.org_name} "
                f"would end {self.ending_count} tie(s): "
                f"{len(self.direct_teams) + len(self.inherited_teams)} "
                f"team membership(s), {len(self.assignments)} "
                f"assignment(s), "
                f"{len(self.standing_review_requests)} standing "
                f"review request(s) and "
                f"{len(self.collaborator_grants)} collaborator "
                f"grant(s).")


class CascadeStore:
    """The removal-cascade preview: a pure read over
    the landed membership, team, assignment, review,
    grant, permission and invitation records. The
    ``audit`` argument is accepted for signature
    parity with the neighbouring stores and is never
    used — a preview audits nothing."""

    def __init__(
        self, conn: sqlite3.Connection, accounts: AccountStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._now = time_fn
        self._members = OrgMembershipStore(
            conn, accounts, audit=None, time_fn=time_fn)
        self._teams = TeamStore(
            conn, accounts, audit=None, time_fn=time_fn)
        self._nesting = NestedTeamStore(
            conn, accounts, audit=None, time_fn=time_fn)
        self._defaults = DefaultPermissionStore(
            conn, accounts, audit=None, time_fn=time_fn)
        self._grants = OutsideCollaboratorStore(
            conn, accounts, audit=None, time_fn=time_fn)
        self._invites = InvitationStore(
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

    # -- the preview -----------------------------------
    def preview_removal(self, org_id: int,
                        target: object) -> RemovalCascade:
        """Compute the whole cascade of removing
        ``target`` (an account id or a username) from
        the organization, as a pure read: nothing is
        written, nothing is audited, nobody is
        removed. A non-member and the last owner are
        reported in the result, not raised."""
        org_row = self._require_org_row(org_id)
        org_name = org_row["name"]
        org_lower = org_row["name_lower"]
        user = self._resolve_target(target)
        membership = self._members.get_membership(user.id, org_id)
        role = membership.role if membership else None
        owner_count = self._members.count_owners(org_id)
        reason = decide_cascade(role, owner_count)
        base = dict(
            org_id=org_id, org_name=org_name,
            user_id=user.id, username=user.username,
            is_member=membership is not None, role=role,
            owner_count=owner_count,
            allowed=reason is None, reason=reason,
            is_org_creator=org_row["created_by"] == user.id,
            default_permission=self._defaults.role_for_org(org_id))
        if membership is None:
            return RemovalCascade(
                **base,
                message=(f"{user.username} is not a member of "
                         f"{org_name}, so there is nothing "
                         f"to remove."))
        if reason == "last_owner":
            message = (
                f"{user.username} is the last owner of "
                f"{org_name}: removal is refused — an "
                f"organization must always keep at least "
                f"one owner. The cascade below is what a "
                f"removal would touch once another owner "
                f"stands in place.")
        else:
            message = (
                f"{user.username} is a {role_word(role).lower()} "
                f"of {org_name}. Nothing has been removed "
                f"yet: this preview is the whole effect, "
                f"computed before confirming.")
        direct, inherited, team_repos = self._teams_cascade(
            org_id, user.id)
        return RemovalCascade(
            **base, message=message,
            direct_teams=direct, inherited_teams=inherited,
            team_repos=team_repos,
            assignments=tuple(self._assignments(org_lower, user.id)),
            review_requests=tuple(
                self._review_requests(org_lower, user.id)),
            submitted_reviews=tuple(
                self._reviews(org_lower, user.id, pending=False)),
            pending_reviews=tuple(
                self._reviews(org_lower, user.id, pending=True)),
            collaborator_grants=tuple(
                self._grants_cascade(org_lower, user.id)),
            invitations_sent=tuple(
                self._invitations_sent(org_id, user.id)),
            org_repositories=tuple(self._repos(org_lower)),
            personal_repositories=tuple(
                self._repos(user.username_lower)),
            authored_open=tuple(
                self._authored_open(org_lower, user.id)))

    # -- category reads --------------------------------
    def _teams_cascade(self, org_id: int, user_id: int):
        direct: list[TeamRef] = []
        inherited: list[TeamRef] = []
        team_repos: list[TeamRepoRef] = []
        seen_repos: set[tuple[str, int]] = set()
        for team in self._teams.list_teams(org_id):
            direct_ids = {m.user_id for m in
                          self._teams.list_members(org_id, team.id)}
            if user_id in direct_ids:
                direct.append(TeamRef(
                    team_id=team.id, name=team.name, via="direct"))
                for link in self._teams.list_repos(org_id, team.id):
                    key = (team.name, link.repo_id)
                    if key in seen_repos:
                        continue
                    seen_repos.add(key)
                    team_repos.append(TeamRepoRef(
                        team_name=team.name,
                        repo=f"{link.owner}/{link.name}",
                        permission=link.permission))
                continue
            effective_ids = {m.user_id for m in
                             self._nesting.effective_members(
                                 org_id, team.id)}
            if user_id in effective_ids:
                inherited.append(TeamRef(
                    team_id=team.id, name=team.name,
                    via="inherited"))
        direct.sort(key=lambda t: t.name.lower())
        inherited.sort(key=lambda t: t.name.lower())
        team_repos.sort(key=lambda r: (r.repo.lower(),
                                       r.team_name.lower()))
        return tuple(direct), tuple(inherited), tuple(team_repos)

    def _assignments(self, org_lower: str,
                     user_id: int) -> list[AssignmentRef]:
        rows = self._conn.execute(
            "SELECT r.owner AS owner, r.name AS name,"
            " i.number AS number, i.kind AS kind,"
            " i.title AS title, i.state AS state"
            " FROM issue_assignees a"
            " JOIN issues i ON i.id = a.issue_id"
            " JOIN repositories r ON r.id = i.repo_id"
            " WHERE a.user_id = ? AND r.owner_lower = ?"
            " ORDER BY r.name_lower, i.number",
            (user_id, org_lower)).fetchall()
        return [AssignmentRef(
            repo=f"{r['owner']}/{r['name']}", number=r["number"],
            kind=r["kind"], title=r["title"], state=r["state"])
            for r in rows]

    def _review_requests(self, org_lower: str,
                         user_id: int) -> list[ReviewRequestRef]:
        rows = self._conn.execute(
            "SELECT r.owner AS owner, r.name AS name,"
            " i.number AS number, q.owner_ref AS owner_ref,"
            " q.source AS source, q.state AS state"
            " FROM pull_request_review_requests q"
            " JOIN pull_requests p ON p.id = q.pull_request_id"
            " JOIN issues i ON i.id = p.issue_id"
            " JOIN repositories r ON r.id = p.repo_id"
            " WHERE q.user_id = ? AND r.owner_lower = ?"
            " ORDER BY r.name_lower, i.number, q.id",
            (user_id, org_lower)).fetchall()
        return [ReviewRequestRef(
            repo=f"{r['owner']}/{r['name']}", number=r["number"],
            owner_ref=r["owner_ref"], source=r["source"],
            state=r["state"]) for r in rows]

    def _reviews(self, org_lower: str, user_id: int,
                 *, pending: bool) -> list[ReviewRef]:
        if pending:
            sql = (
                "SELECT r.owner AS owner, r.name AS name,"
                " i.number AS number, v.verdict AS verdict"
                " FROM pull_request_pending_reviews v"
                " JOIN pull_requests p"
                " ON p.id = v.pull_request_id"
                " JOIN issues i ON i.id = p.issue_id"
                " JOIN repositories r ON r.id = p.repo_id"
                " WHERE v.reviewer_id = ? AND r.owner_lower = ?"
                " ORDER BY r.name_lower, i.number")
        else:
            sql = (
                "SELECT r.owner AS owner, r.name AS name,"
                " i.number AS number, v.verdict AS verdict"
                " FROM pull_request_reviews v"
                " JOIN pull_requests p"
                " ON p.id = v.pull_request_id"
                " JOIN issues i ON i.id = p.issue_id"
                " JOIN repositories r ON r.id = p.repo_id"
                " WHERE v.reviewer_id = ? AND r.owner_lower = ?"
                " ORDER BY r.name_lower, i.number, v.id")
        rows = self._conn.execute(sql, (user_id, org_lower)).fetchall()
        return [ReviewRef(
            repo=f"{r['owner']}/{r['name']}", number=r["number"],
            verdict=r["verdict"], pending=pending) for r in rows]

    def _grants_cascade(self, org_lower: str,
                        user_id: int) -> list[GrantRef]:
        return [GrantRef(repo=g.full_name, role=g.role)
                for g in self._grants.list_for_user(user_id)
                if g.owner.lower() == org_lower]

    def _invitations_sent(self, org_id: int,
                          user_id: int) -> list[InvitationRef]:
        now = int(self._now())
        return [InvitationRef(target=inv.target_label(),
                              role=inv.role)
                for inv in self._invites.list_invitations(org_id)
                if inv.invited_by == user_id
                and inv.state(now) == "pending"]

    def _repos(self, owner_lower: str) -> list[RepoRef]:
        rows = self._conn.execute(
            "SELECT owner, name, visibility FROM repositories"
            " WHERE owner_lower = ? ORDER BY name_lower",
            (owner_lower,)).fetchall()
        return [RepoRef(full_name=f"{r['owner']}/{r['name']}",
                        visibility=r["visibility"]) for r in rows]

    def _authored_open(self, org_lower: str,
                       user_id: int) -> list[ItemRef]:
        rows = self._conn.execute(
            "SELECT r.owner AS owner, r.name AS name,"
            " i.number AS number, i.kind AS kind,"
            " i.title AS title"
            " FROM issues i"
            " JOIN repositories r ON r.id = i.repo_id"
            " WHERE i.author_id = ? AND r.owner_lower = ?"
            " AND i.state = 'open'"
            " ORDER BY r.name_lower, i.number",
            (user_id, org_lower)).fetchall()
        return [ItemRef(
            repo=f"{r['owner']}/{r['name']}", number=r["number"],
            kind=r["kind"], title=r["title"]) for r in rows]


def _section(parts: list[str], heading: str, items,
             empty_sentence: str):
    parts.append(f"<h2>{escape_html_text(heading)}</h2>")
    if items:
        parts.append("<ul>")
        for item in items:
            parts.append(
                f"<li>{escape_html_text(item.words)}</li>")
        parts.append("</ul>")
    else:
        parts.append(f"<p>{escape_html_text(empty_sentence)}</p>")


def render_removal_cascade_page(org: Organization,
                                cascade: RemovalCascade) -> str:
    """The before-confirming page: whether the removal
    may proceed and why, then every category the
    cascade touches, each item in words — every value
    escaped through S-010, the position in text,
    never colour-only."""
    name = escape_html_text(cascade.username)
    org_name = escape_html_text(org.name)
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Remove {name} — {org_name} — Samverk</title></head>",
        "<body>",
        f"<h1>Before you remove {name} from "
        f"{escape_html_text(org.effective_display_name())}</h1>",
        f"<p>{escape_html_text(cascade.message)}</p>",
        f"<p>{escape_html_text(cascade.summary())}</p>",
    ]
    if cascade.is_member:
        role_line = (
            f"{cascade.username} is a "
            f"{role_word(cascade.role or '').lower()} of this "
            f"organization (one of {cascade.owner_count} "
            f"owner(s)).")
        if cascade.default_permission != "none":
            role_line += (
                f" The organization's default repository "
                f"permission floors members at "
                f"{cascade.default_permission} in its "
                f"repositories; that floor ends with the "
                f"membership.")
        parts.append(f"<p>{escape_html_text(role_line)}</p>")
        if cascade.is_org_creator:
            parts.append(
                "<p>This member founded the organization. "
                "Founding is a fact of the record, not a "
                "shield: only being its last owner refuses "
                "removal.</p>")
    _section(parts, "Team memberships that would end",
             cascade.direct_teams + cascade.inherited_teams,
             "No team memberships are tied to this member.")
    _section(parts, "Repository access through those teams",
             cascade.team_repos,
             "No team repository links are tied to this member.")
    _section(parts, "Assignments that would need a new owner",
             cascade.assignments,
             "No assignments in this organization's "
             "repositories are tied to this member.")
    _section(parts, "Review requests recorded against them",
             cascade.review_requests,
             "No review requests are recorded against "
             "this member.")
    _section(parts, "Reviews they have submitted (they stay on the record)",
             cascade.submitted_reviews,
             "No submitted reviews are recorded for this member.")
    _section(parts, "Review drafts still pending",
             cascade.pending_reviews,
             "No pending review drafts are recorded for this member.")
    _section(parts, "Outside-collaborator grants in organization repositories",
             cascade.collaborator_grants,
             "No outside-collaborator grants are held in "
             "this organization's repositories.")
    _section(parts, "Repositories of this organization",
             cascade.org_repositories,
             "This organization owns no repositories.")
    _section(parts, "Pending invitations they sent (they stay sent)",
             cascade.invitations_sent,
             "No pending invitations from this member are standing.")
    _section(parts, "Open work they authored (authorship stays)",
             cascade.authored_open,
             "No open authored work is recorded for this member.")
    _section(parts, "Their own repositories (not touched by removal)",
             cascade.personal_repositories,
             "They own no repositories of their own.")
    parts.append(
        "<p>Nothing has been removed yet. This preview is "
        "a pure read: it wrote nothing and audited "
        "nothing. Removal itself happens through the "
        "organization's membership controls, and the "
        "last owner can never be removed.</p>")
    parts.append("</body></html>")
    return "\n".join(parts)
