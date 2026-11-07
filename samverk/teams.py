"""Teams (S-187).

Teams inside an organization: create, describe,
privacy (visible/secret), team pages listing members
and repos.

- **A team lives inside one organization.** Its name
  is written as a person writes it and judged by its
  slug (``team_slug``: lowercased, spaces and
  underscores folded to hyphens, only letters, digits
  and hyphens survive): the slug is unique inside the
  organization, case-insensitively, and the same name
  in another organization is no collision. The
  description is plain text under the S-029 caps
  restated here (500, control characters refused,
  empty clears).
- **Privacy is a word with a rule.** A team is
  ``visible`` or ``secret`` (``PRIVACIES``), decided
  by the pure ``validate_privacy`` and judged for any
  viewer by the pure ``decide_team_visibility``: a
  visible team is readable by anyone who can read at
  all; a secret team is readable only by its own
  members and by site admins. To everyone else a
  secret team is *not there*: reads through
  ``get_team_for_viewer`` /
  ``list_teams_for_viewer`` answer the uniform
  ``team_not_found``, the same refusal a missing
  team gets, so a secret team's existence never
  leaks through a distinguishable error.
- **Only stewardship manages.** Creating a team,
  changing its description or privacy, managing its
  members and linking its repositories are acts for
  an organization owner or a site admin only (the
  S-186 guard, mirrored); anyone else is refused
  ``not_org_owner``. The creator is recorded as the
  team's first member, so a fresh team is never an
  empty shell its maker cannot see.
- **Team members are organization members.** Adding
  a person who is not a member of the organization
  is refused ``not_org_member`` — a team never
  smuggles an outsider into an organization.
  Membership itself (owners, the last-owner law) is
  S-186's ground and is only read here.
- **Repositories are linked, not yet permissioned.**
  A team page lists the repositories linked to the
  team (``link_repo`` / ``unlink_repo`` over the
  ``team_repositories`` table). A repository may
  only be linked when it belongs to the team's
  organization (``repo_not_in_org`` otherwise).
  What a team may *do* in a linked repository — the
  read / triage / write / maintain / admin ladder —
  is S-189's slice; until it lands the page says so
  plainly and an unlinked team shows an honest empty
  section, never a pretend permission.
- **Nested teams are S-188's slice** and are not
  built here: teams today are flat inside their
  organization.
- **Audit:** successful changes ride the existing
  ``auth.organization.update`` event (no new
  taxonomy event — 122 events stand) with detail
  ``{"fields": "teams", "action": ...}``; refusals
  write nothing and audit nothing.
- **Storage** is migration 70's ``teams``,
  ``team_members`` and ``team_repositories`` tables
  (schema 69 to 70).
"""
from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .organization_members import OrgMembershipStore
from .organizations import Organization, OrganizationError

__all__ = [
    "DESCRIPTION_MAX", "NAME_MAX", "PRIVACIES",
    "Team", "TeamMembership", "TeamRepository", "TeamStore",
    "decide_team_visibility", "privacy_word", "render_team_page",
    "render_teams_page", "team_slug", "validate_privacy",
    "validate_team_name",
]

NAME_MAX = 50
DESCRIPTION_MAX = 500
PRIVACIES = frozenset({"visible", "secret"})

_PRIVACY_WORDS = {"visible": "Visible", "secret": "Secret"}
_SLUG_RUN = re.compile(r"[^a-z0-9]+")


def team_slug(name: str) -> str:
    """The canonical slug a team name is judged by:
    lowercased, every run of non-slug characters
    folded to one hyphen, hyphens trimmed from the
    ends. An all-punctuation name slugs to empty."""
    return _SLUG_RUN.sub("-", name.strip().lower()).strip("-")


def validate_team_name(name: object) -> tuple[str, str]:
    """Return (display name, slug) or refuse plainly:
    the name must be text of at most NAME_MAX
    characters, carry no control characters, and
    leave a non-empty slug."""
    if not isinstance(name, str):
        raise OrganizationError(
            "team_invalid", "That team name is not valid.")
    display = name.strip()
    if not display:
        raise OrganizationError(
            "team_invalid", "A team needs a name.")
    if len(display) > NAME_MAX:
        raise OrganizationError(
            "team_too_long",
            f"That team name is too long (at most {NAME_MAX} characters).")
    for ch in display:
        if ord(ch) == 0x7F or ord(ch) < 0x20:
            raise OrganizationError(
                "team_invalid",
                "That team name contains characters that cannot be shown.")
    slug = team_slug(display)
    if not slug:
        raise OrganizationError(
            "team_invalid", "That team name is not valid.")
    return display, slug


def validate_privacy(privacy: object) -> str:
    """Return the canonical privacy or refuse plainly."""
    if isinstance(privacy, str) and privacy.strip().lower() in PRIVACIES:
        return privacy.strip().lower()
    raise OrganizationError(
        "privacy_invalid",
        "A team's privacy is visible or secret.")


def privacy_word(privacy: str) -> str:
    """The privacy said in a word a person reads."""
    return _PRIVACY_WORDS.get(privacy, privacy)


def decide_team_visibility(privacy: str, is_team_member: bool,
                           is_site_admin: bool) -> bool:
    """Pure viewing rule: a visible team is readable
    by anyone; a secret team only by its own members
    and by site admins."""
    if privacy == "visible":
        return True
    return bool(is_team_member or is_site_admin)


def _clean_description(value: object) -> str | None:
    """S-029's text law for the description: strip;
    empty clears; over the cap or carrying controls
    (newlines and tabs allowed) is refused."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise OrganizationError(
            "description_invalid", "That description is not valid.")
    text = value.strip()
    if not text:
        return None
    if len(text) > DESCRIPTION_MAX:
        raise OrganizationError(
            "description_too_long",
            f"That description is too long "
            f"(at most {DESCRIPTION_MAX} characters).")
    for ch in text:
        if ord(ch) == 0x7F or (ord(ch) < 0x20 and ch not in "\n\t"):
            raise OrganizationError(
                "description_invalid",
                "That description contains characters "
                "that cannot be shown.")
    return text


@dataclass(frozen=True)
class Team:
    id: int
    org_id: int
    name: str              # display case
    name_lower: str        # the slug, canonical
    description: str | None
    privacy: str           # visible | secret
    created_by: int
    created_at: int
    updated_at: int


@dataclass(frozen=True)
class TeamMembership:
    team_id: int
    user_id: int
    username: str
    username_lower: str
    added_by: int | None
    created_at: int


@dataclass(frozen=True)
class TeamRepository:
    team_id: int
    repo_id: int
    owner: str
    name: str
    description: str
    visibility: str


def _row_to_team(row: sqlite3.Row) -> Team:
    return Team(
        id=row["id"], org_id=row["org_id"], name=row["name"],
        name_lower=row["name_lower"],
        description=row["description"], privacy=row["privacy"],
        created_by=row["created_by"], created_at=row["created_at"],
        updated_at=row["updated_at"])


_MEMBER_SELECT = (
    "SELECT m.team_id AS team_id, m.user_id AS user_id,"
    " u.username AS username,"
    " u.username_lower AS username_lower,"
    " m.added_by AS added_by, m.created_at AS created_at"
    " FROM team_members m JOIN users u ON u.id = m.user_id")

_REPO_SELECT = (
    "SELECT l.team_id AS team_id, r.id AS repo_id,"
    " r.owner AS owner, r.name AS name,"
    " r.description AS description, r.visibility AS visibility"
    " FROM team_repositories l"
    " JOIN repositories r ON r.id = l.repo_id")


class TeamStore:
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

    # -- guards -----------------------------------------
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

    def _require_owner_or_admin(self, actor_id: int,
                                org_row: sqlite3.Row) -> User:
        actor = self._require_user(actor_id)
        if actor.is_admin:
            return actor
        if self._org_members.role_for(actor.id, org_row["id"]) != "owner":
            raise OrganizationError(
                "not_org_owner",
                "Only an organization owner or a site admin "
                "can manage this organization's teams.")
        return actor

    def _require_team(self, org_id: int, team_id: int) -> Team:
        row = self._conn.execute(
            "SELECT * FROM teams WHERE org_id = ? AND id = ?",
            (org_id, team_id)).fetchone()
        if row is None:
            raise OrganizationError(
                "team_not_found", "No such team.")
        return _row_to_team(row)

    def _audit_change(self, actor: User, org_row: sqlite3.Row,
                      action: str, team: Team,
                      extra: dict | None = None,
                      source_ip: str | None = None):
        if self._audit is None:
            return
        detail: dict = {"fields": "teams", "action": action,
                        "team": team.name_lower}
        if extra:
            detail.update(extra)
        self._audit.append(
            actor_kind="user", actor_id=actor.id,
            action="auth.organization.update",
            target_kind="organization",
            target_id=org_row["name_lower"],
            outcome="success", source_ip=source_ip,
            detail=detail)

    # -- creation and profile -----------------------------
    def create_team(
        self, actor_id: int, org_id: int, name: object, *,
        description: object = None, privacy: object = "visible",
        source_ip: str | None = None,
    ) -> Team:
        org_row = self._require_org_row(org_id)
        actor = self._require_owner_or_admin(actor_id, org_row)
        display, slug = validate_team_name(name)
        clean_privacy = validate_privacy(privacy)
        clean_desc = _clean_description(description)
        clash = self._conn.execute(
            "SELECT id FROM teams WHERE org_id = ? AND name_lower = ?",
            (org_id, slug)).fetchone()
        if clash is not None:
            raise OrganizationError(
                "team_taken",
                f"{display} is already a team in this organization.")
        now = int(self._now())
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO teams (org_id, name, name_lower,"
                " description, privacy, created_by, created_at,"
                " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (org_id, display, slug, clean_desc, clean_privacy,
                 actor.id, now, now))
            team_id = int(cur.lastrowid)
            self._conn.execute(
                "INSERT INTO team_members (team_id, user_id,"
                " added_by, created_at) VALUES (?, ?, ?, ?)",
                (team_id, actor.id, actor.id, now))
        team = self._require_team(org_id, team_id)
        self._audit_change(actor, org_row, "create", team,
                           source_ip=source_ip)
        return team

    def update_team(
        self, actor_id: int, org_id: int, team_id: int, *,
        description: object = None, privacy: object = None,
        source_ip: str | None = None,
    ) -> Team:
        """Set the description (a submitted empty value
        clears it, S-185's profile law) and, when a
        privacy is given, the privacy. Owner/admin only."""
        org_row = self._require_org_row(org_id)
        actor = self._require_owner_or_admin(actor_id, org_row)
        team = self._require_team(org_id, team_id)
        clean_desc = _clean_description(description)
        clean_privacy = (team.privacy if privacy is None
                         else validate_privacy(privacy))
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "UPDATE teams SET description = ?, privacy = ?,"
                " updated_at = ? WHERE id = ?",
                (clean_desc, clean_privacy, now, team.id))
        updated = self._require_team(org_id, team_id)
        self._audit_change(actor, org_row, "update", updated,
                           source_ip=source_ip)
        return updated

    # -- reads --------------------------------------------
    def get_team(self, org_id: int, team_id: int) -> Team:
        self._require_org_row(org_id)
        return self._require_team(org_id, team_id)

    def get_team_by_name(self, org_id: int,
                         name: object) -> Team | None:
        self._require_org_row(org_id)
        if not isinstance(name, str):
            return None
        row = self._conn.execute(
            "SELECT * FROM teams WHERE org_id = ? AND name_lower = ?",
            (org_id, team_slug(name))).fetchone()
        return _row_to_team(row) if row else None

    def list_teams(self, org_id: int) -> list[Team]:
        self._require_org_row(org_id)
        rows = self._conn.execute(
            "SELECT * FROM teams WHERE org_id = ?"
            " ORDER BY name_lower", (org_id,)).fetchall()
        return [_row_to_team(r) for r in rows]

    def is_team_member(self, user_id: int, team_id: int) -> bool:
        row = self._conn.execute(
            "SELECT user_id FROM team_members"
            " WHERE team_id = ? AND user_id = ?",
            (team_id, user_id)).fetchone()
        return row is not None

    def _viewer_may_see(self, viewer_id: int | None,
                        team: Team) -> bool:
        if team.privacy == "visible":
            return True
        if viewer_id is None:
            return False
        viewer = self._accounts.get_by_id(viewer_id)
        is_admin = bool(viewer is not None and viewer.is_admin)
        return decide_team_visibility(
            team.privacy, self.is_team_member(viewer_id, team.id),
            is_admin)

    def get_team_for_viewer(self, viewer_id: int | None, org_id: int,
                            team_id: int) -> Team:
        """The team as this viewer may know it: a secret
        team the viewer may not see is team_not_found,
        exactly as if it did not exist."""
        team = self.get_team(org_id, team_id)
        if not self._viewer_may_see(viewer_id, team):
            raise OrganizationError(
                "team_not_found", "No such team.")
        return team

    def list_teams_for_viewer(self, viewer_id: int | None,
                              org_id: int) -> list[Team]:
        return [t for t in self.list_teams(org_id)
                if self._viewer_may_see(viewer_id, t)]

    # -- team members ---------------------------------------
    def add_member(
        self, actor_id: int, org_id: int, team_id: int,
        target: object, source_ip: str | None = None,
    ) -> TeamMembership:
        org_row = self._require_org_row(org_id)
        actor = self._require_owner_or_admin(actor_id, org_row)
        team = self._require_team(org_id, team_id)
        target_user = self._resolve_target(target)
        if self._org_members.role_for(target_user.id, org_id) is None:
            raise OrganizationError(
                "not_org_member",
                "Teams can only include members of the organization: "
                "add that person to the organization first.")
        if self.is_team_member(target_user.id, team.id):
            raise OrganizationError(
                "already_team_member",
                "That person is already a member of this team.")
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "INSERT INTO team_members (team_id, user_id,"
                " added_by, created_at) VALUES (?, ?, ?, ?)",
                (team.id, target_user.id, actor.id, now))
        self._audit_change(
            actor, org_row, "add_member", team,
            extra={"target": target_user.username_lower},
            source_ip=source_ip)
        result = self.get_membership(team.id, target_user.id)
        assert result is not None
        return result

    def remove_member(
        self, actor_id: int, org_id: int, team_id: int,
        target: object, source_ip: str | None = None,
    ) -> None:
        org_row = self._require_org_row(org_id)
        actor = self._require_owner_or_admin(actor_id, org_row)
        team = self._require_team(org_id, team_id)
        target_user = self._resolve_target(target)
        if not self.is_team_member(target_user.id, team.id):
            raise OrganizationError(
                "not_team_member",
                "That person is not a member of this team.")
        with self._conn:
            self._conn.execute(
                "DELETE FROM team_members"
                " WHERE team_id = ? AND user_id = ?",
                (team.id, target_user.id))
        self._audit_change(
            actor, org_row, "remove_member", team,
            extra={"target": target_user.username_lower},
            source_ip=source_ip)

    def get_membership(self, team_id: int,
                       user_id: int) -> TeamMembership | None:
        row = self._conn.execute(
            _MEMBER_SELECT + " WHERE m.team_id = ? AND m.user_id = ?",
            (team_id, user_id)).fetchone()
        if row is None:
            return None
        return TeamMembership(
            team_id=row["team_id"], user_id=row["user_id"],
            username=row["username"],
            username_lower=row["username_lower"],
            added_by=row["added_by"], created_at=row["created_at"])

    def list_members(self, org_id: int,
                     team_id: int) -> list[TeamMembership]:
        self._require_team(org_id, team_id)
        rows = self._conn.execute(
            _MEMBER_SELECT + " WHERE m.team_id = ?"
            " ORDER BY u.username_lower", (team_id,)).fetchall()
        return [
            TeamMembership(
                team_id=r["team_id"], user_id=r["user_id"],
                username=r["username"],
                username_lower=r["username_lower"],
                added_by=r["added_by"], created_at=r["created_at"])
            for r in rows]

    # -- linked repositories ----------------------------------
    def link_repo(
        self, actor_id: int, org_id: int, team_id: int,
        repo_id: int, source_ip: str | None = None,
    ) -> TeamRepository:
        org_row = self._require_org_row(org_id)
        actor = self._require_owner_or_admin(actor_id, org_row)
        team = self._require_team(org_id, team_id)
        repo = self._conn.execute(
            "SELECT * FROM repositories WHERE id = ?",
            (repo_id,)).fetchone()
        if repo is None:
            raise OrganizationError(
                "repo_not_found", "No such repository.")
        if repo["owner_lower"] != org_row["name_lower"]:
            raise OrganizationError(
                "repo_not_in_org",
                "A team can only be linked to repositories "
                "that belong to its organization.")
        clash = self._conn.execute(
            "SELECT team_id FROM team_repositories"
            " WHERE team_id = ? AND repo_id = ?",
            (team.id, repo_id)).fetchone()
        if clash is not None:
            raise OrganizationError(
                "already_linked",
                "That repository is already linked to this team.")
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "INSERT INTO team_repositories (team_id, repo_id,"
                " added_by, created_at) VALUES (?, ?, ?, ?)",
                (team.id, repo_id, actor.id, now))
        self._audit_change(
            actor, org_row, "link_repo", team,
            extra={"repo": f"{repo['owner_lower']}/{repo['name_lower']}"},
            source_ip=source_ip)
        result = self.get_link(team.id, repo_id)
        assert result is not None
        return result

    def unlink_repo(
        self, actor_id: int, org_id: int, team_id: int,
        repo_id: int, source_ip: str | None = None,
    ) -> None:
        org_row = self._require_org_row(org_id)
        actor = self._require_owner_or_admin(actor_id, org_row)
        team = self._require_team(org_id, team_id)
        if self.get_link(team.id, repo_id) is None:
            raise OrganizationError(
                "not_linked",
                "That repository is not linked to this team.")
        with self._conn:
            self._conn.execute(
                "DELETE FROM team_repositories"
                " WHERE team_id = ? AND repo_id = ?",
                (team.id, repo_id))
        self._audit_change(
            actor, org_row, "unlink_repo", team,
            source_ip=source_ip)

    def get_link(self, team_id: int,
                 repo_id: int) -> TeamRepository | None:
        row = self._conn.execute(
            _REPO_SELECT + " WHERE l.team_id = ? AND l.repo_id = ?",
            (team_id, repo_id)).fetchone()
        if row is None:
            return None
        return TeamRepository(
            team_id=row["team_id"], repo_id=row["repo_id"],
            owner=row["owner"], name=row["name"],
            description=row["description"],
            visibility=row["visibility"])

    def list_repos(self, org_id: int,
                   team_id: int) -> list[TeamRepository]:
        self._require_team(org_id, team_id)
        rows = self._conn.execute(
            _REPO_SELECT + " WHERE l.team_id = ?"
            " ORDER BY r.name_lower", (team_id,)).fetchall()
        return [
            TeamRepository(
                team_id=r["team_id"], repo_id=r["repo_id"],
                owner=r["owner"], name=r["name"],
                description=r["description"],
                visibility=r["visibility"])
            for r in rows]


def render_team_page(org: Organization, team: Team,
                     members: list[TeamMembership],
                     repos: list[TeamRepository]) -> str:
    """The team page: name, description and privacy in
    words, then the members and the linked
    repositories — every value escaped through S-010,
    and the not-yet-built permission ladder (S-189)
    stated plainly instead of implied."""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{escape_html_text(team.name)} — "
        f"{escape_html_text(org.name)} — Samverk</title></head>",
        "<body>",
        f"<h1>{escape_html_text(team.name)}</h1>",
        f'<p class="org-name">A team in '
        f"{escape_html_text(org.effective_display_name())}</p>",
    ]
    if team.description:
        desc = escape_html_text(team.description).replace(
            "\n", "<br>\n")
        parts.append(f'<p class="description">{desc}</p>')
    if team.privacy == "secret":
        parts.append(
            "<p>Privacy: Secret — only this team's members "
            "can see this team.</p>")
    else:
        parts.append(
            "<p>Privacy: Visible — anyone can see this team.</p>")
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
            parts.append(f"<li>{label}</li>")
        parts.append("</ul>")
    else:
        parts.append(
            "<p>No repositories are linked to this team yet. "
            "What a team may do in a repository — the "
            "permission ladder — lands with S-189.</p>")
    parts.append(
        "<p>Repository permissions for teams land with "
        "S-189; this page lists the linked repositories "
        "until then.</p>")
    parts.append("</body></html>")
    return "\n".join(parts)


def render_teams_page(org: Organization,
                      teams: list[Team]) -> str:
    """The organization's teams page: every team the
    caller was given (already viewer-filtered by the
    store), with its privacy in a word and its
    description, escaped through S-010."""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Teams — {escape_html_text(org.name)} — Samverk</title></head>",
        "<body>",
        f"<h1>Teams in {escape_html_text(org.effective_display_name())}</h1>",
    ]
    if teams:
        parts.append("<ul>")
        for team in teams:
            line = (f"{escape_html_text(team.name)} — "
                    f"{escape_html_text(privacy_word(team.privacy))}")
            if team.description:
                line += f" — {escape_html_text(team.description)}"
            parts.append(f"<li>{line}</li>")
        parts.append("</ul>")
    else:
        parts.append("<p>No teams yet.</p>")
    parts.append("</body></html>")
    return "\n".join(parts)
