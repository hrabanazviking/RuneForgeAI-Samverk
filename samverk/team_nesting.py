"""Nested teams (S-188).

Parent/child teams with permission inheritance
documented and visualised before saving.

- **One parent, same organization.** A team has at
  most one parent team (migration 71's
  ``teams.parent_team_id``); a team with no parent is
  a root. The parent must be a team in the same
  organization (``parent_not_in_org`` otherwise, and
  ``parent_not_found`` when no such team exists at
  all). A team can never be its own parent
  (``team_parent_is_self``) and no change may close a
  cycle (``team_parent_cycle``): the pure
  ``would_create_cycle`` walks the proposed parent's
  ancestor chain, and if the team itself stands in
  that chain the change is refused and nothing is
  written. Reparenting a team moves its whole subtree
  with it — children keep pointing at it, so their
  ancestor chains simply grow or shrink.
- **Inheritance flows down, never up.** A child team
  inherits from every ancestor, nearest first:
  (a) *repository links* — ``effective_repos`` is the
  team's own S-187 links plus every ancestor's links,
  each repository named once, the team's own link
  winning; when S-189's permission ladder lands, the
  permission a team holds in a repository is judged
  over exactly this effective set; and
  (b) *members* — ``effective_members`` is the team's
  direct members plus every ancestor's direct
  members, each person named once. A child's members
  and links never flow upward to its parent, and one
  sibling inherits nothing from another. This is the
  whole inheritance law; there is no other hidden
  flow.
- **Visualised before saving.** No parent change is
  a surprise: ``preview_parent_change`` computes the
  exact effect — the ancestor chain after the change,
  the members and repositories the team would
  inherit, and the members and repositories it would
  stop inheriting — as a pure read that writes
  nothing, and ``render_nesting_preview`` renders
  that preview as a page a person confirms *before*
  ``set_parent`` is called. A preview of an unlawful
  change (cycle, self-parent, cross-organization)
  says so in its ``allowed`` flag and refusal reason
  instead of raising, so the page can show the reason
  in words. ``set_parent`` re-judges the same rules
  and raises on refusal; the preview never grants
  anything by itself.
- **Only stewardship manages.** Setting or clearing
  a parent is an organization owner / site admin act
  (the S-186/S-187 guard, mirrored;
  ``not_org_owner`` otherwise).
- **Audit:** successful changes ride the existing
  ``auth.organization.update`` event (no new
  taxonomy event — 122 events stand) with detail
  ``{"fields": "teams", "action": "set_parent" /
  "clear_parent", ...}``; refusals and previews
  write nothing and audit nothing.
- **Storage** is migration 71's ``parent_team_id``
  column on S-187's ``teams`` table (schema 70 to
  71). Teams themselves, their members and their
  repository links stay S-187's ground and are only
  read here.
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
from .organizations import Organization, OrganizationError
from .teams import Team, TeamMembership, TeamRepository, TeamStore

__all__ = [
    "NestingPreview", "NestedTeamStore", "ancestor_ids",
    "descendant_ids", "render_nesting_preview",
    "render_team_tree_page", "would_create_cycle",
]


def ancestor_ids(parent_of: dict[int, int | None],
                 team_id: int) -> list[int]:
    """The ancestor chain of a team, nearest parent
    first, judged purely over a {team_id: parent_id}
    map. A team standing in its own chain (corrupt
    data) ends the walk instead of looping forever."""
    chain: list[int] = []
    seen = {team_id}
    current = parent_of.get(team_id)
    while current is not None and current not in seen:
        chain.append(current)
        seen.add(current)
        current = parent_of.get(current)
    return chain


def descendant_ids(parent_of: dict[int, int | None],
                   team_id: int) -> list[int]:
    """Every team below this one in the tree, judged
    purely over a {team_id: parent_id} map, ordered
    by team id for determinism."""
    children: dict[int, list[int]] = {}
    for child, parent in parent_of.items():
        if parent is not None:
            children.setdefault(parent, []).append(child)
    found: list[int] = []
    seen = {team_id}
    queue = [team_id]
    while queue:
        current = queue.pop(0)
        for child in sorted(children.get(current, [])):
            if child in seen:
                continue
            seen.add(child)
            found.append(child)
            queue.append(child)
    return sorted(found)


def would_create_cycle(parent_of: dict[int, int | None],
                       team_id: int,
                       parent_id: int | None) -> bool:
    """Pure cycle law: giving ``team_id`` the parent
    ``parent_id`` closes a cycle exactly when the
    team is the proposed parent itself or already
    stands in the proposed parent's ancestor chain.
    Clearing a parent (None) can never cycle."""
    if parent_id is None:
        return False
    if parent_id == team_id:
        return True
    return team_id in ancestor_ids(parent_of, parent_id)


@dataclass(frozen=True)
class NestingPreview:
    """The effect of a proposed parent change, computed
    before anything is saved."""
    team_id: int
    team_name: str
    current_parent_id: int | None
    proposed_parent_id: int | None
    allowed: bool
    reason: str | None          # refusal reason when not allowed
    message: str                # the law said in plain words
    ancestors_after: tuple[str, ...]     # team names, nearest first
    inherited_members: tuple[str, ...]   # usernames gained via ancestors
    inherited_repos: tuple[str, ...]     # "owner/name" gained via ancestors
    lost_members: tuple[str, ...]        # usernames no longer inherited
    lost_repos: tuple[str, ...]          # "owner/name" no longer inherited


class NestedTeamStore:
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
        self._teams = TeamStore(conn, accounts, audit=None,
                                time_fn=time_fn)

    # -- guards (S-187's, mirrored) ----------------------
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
                "can manage this organization's teams.")
        return actor

    def _parent_map(self, org_id: int) -> dict[int, int | None]:
        rows = self._conn.execute(
            "SELECT id, parent_team_id FROM teams WHERE org_id = ?",
            (org_id,)).fetchall()
        return {r["id"]: r["parent_team_id"] for r in rows}

    def _resolve_parent(self, org_id: int,
                        parent_id: int) -> Team:
        """The proposed parent judged: it must exist,
        and it must live in this organization."""
        row = self._conn.execute(
            "SELECT org_id FROM teams WHERE id = ?",
            (parent_id,)).fetchone()
        if row is None:
            raise OrganizationError(
                "parent_not_found", "No such parent team.")
        if row["org_id"] != org_id:
            raise OrganizationError(
                "parent_not_in_org",
                "A team's parent must be a team in the "
                "same organization.")
        return self._teams.get_team(org_id, parent_id)

    def _judge(self, org_id: int, team: Team,
               parent_id: int | None) -> Team | None:
        """Raise on an unlawful parent; return the
        parent team (or None for a root) when lawful."""
        if parent_id is None:
            return None
        if parent_id == team.id:
            raise OrganizationError(
                "team_parent_is_self",
                "A team cannot be its own parent.")
        parent = self._resolve_parent(org_id, parent_id)
        if would_create_cycle(self._parent_map(org_id),
                              team.id, parent_id):
            raise OrganizationError(
                "team_parent_cycle",
                "That parent would make the team its own "
                "ancestor; nested teams cannot form a cycle.")
        return parent

    def _audit_change(self, actor: User, org_row: sqlite3.Row,
                      action: str, team: Team,
                      parent: Team | None,
                      source_ip: str | None = None):
        if self._audit is None:
            return
        detail: dict = {"fields": "teams", "action": action,
                        "team": team.name_lower,
                        "parent": parent.name_lower if parent else None}
        self._audit.append(
            actor_kind="user", actor_id=actor.id,
            action="auth.organization.update",
            target_kind="organization",
            target_id=org_row["name_lower"],
            outcome="success", source_ip=source_ip,
            detail=detail)

    # -- reads -------------------------------------------
    def get_parent(self, org_id: int,
                   team_id: int) -> Team | None:
        team = self._teams.get_team(org_id, team_id)
        if team.parent_team_id is None:
            return None
        return self._teams.get_team(org_id, team.parent_team_id)

    def list_children(self, org_id: int,
                      team_id: int) -> list[Team]:
        self._teams.get_team(org_id, team_id)
        return [t for t in self._teams.list_teams(org_id)
                if t.parent_team_id == team_id]

    def ancestors(self, org_id: int, team_id: int) -> list[Team]:
        self._teams.get_team(org_id, team_id)
        parent_of = self._parent_map(org_id)
        by_id = {t.id: t for t in self._teams.list_teams(org_id)}
        return [by_id[i] for i in ancestor_ids(parent_of, team_id)
                if i in by_id]

    def descendants(self, org_id: int, team_id: int) -> list[Team]:
        self._teams.get_team(org_id, team_id)
        parent_of = self._parent_map(org_id)
        by_id = {t.id: t for t in self._teams.list_teams(org_id)}
        return [by_id[i] for i in descendant_ids(parent_of, team_id)
                if i in by_id]

    def _effective(self, org_id: int, team_id: int,
                   parent_of: dict[int, int | None]):
        """(members, repos) over a stated parent map:
        the team's own first, then each ancestor's,
        nearest first, each entry named once."""
        chain = [team_id] + ancestor_ids(parent_of, team_id)
        members: list[TeamMembership] = []
        seen_users: set[int] = set()
        repos: list[TeamRepository] = []
        seen_repos: set[int] = set()
        for tid in chain:
            for m in self._teams.list_members(org_id, tid):
                if m.user_id not in seen_users:
                    seen_users.add(m.user_id)
                    members.append(m)
            for r in self._teams.list_repos(org_id, tid):
                if r.repo_id not in seen_repos:
                    seen_repos.add(r.repo_id)
                    repos.append(r)
        return members, repos

    def effective_members(self, org_id: int,
                          team_id: int) -> list[TeamMembership]:
        self._teams.get_team(org_id, team_id)
        members, _ = self._effective(
            org_id, team_id, self._parent_map(org_id))
        return members

    def effective_repos(self, org_id: int,
                        team_id: int) -> list[TeamRepository]:
        self._teams.get_team(org_id, team_id)
        _, repos = self._effective(
            org_id, team_id, self._parent_map(org_id))
        return repos

    # -- preview before saving -----------------------------
    def preview_parent_change(
        self, org_id: int, team_id: int,
        parent_id: int | None,
    ) -> NestingPreview:
        """The whole effect of a proposed parent change,
        computed as a pure read: nothing is written and
        nothing is audited. An unlawful proposal is
        reported in the preview, not raised."""
        team = self._teams.get_team(org_id, team_id)
        current_map = self._parent_map(org_id)
        cur_members, cur_repos = self._effective(
            org_id, team_id, current_map)
        cur_member_names = {m.username for m in cur_members}
        cur_repo_names = {f"{r.owner}/{r.name}" for r in cur_repos}
        own_member_names = {m.username for m in
                            self._teams.list_members(org_id, team_id)}
        own_repo_names = {f"{r.owner}/{r.name}" for r in
                          self._teams.list_repos(org_id, team_id)}
        try:
            self._judge(org_id, team, parent_id)
        except OrganizationError as exc:
            return NestingPreview(
                team_id=team.id, team_name=team.name,
                current_parent_id=team.parent_team_id,
                proposed_parent_id=parent_id,
                allowed=False, reason=exc.reason,
                message=str(exc),
                ancestors_after=(), inherited_members=(),
                inherited_repos=(), lost_members=(),
                lost_repos=())
        proposed_map = dict(current_map)
        proposed_map[team_id] = parent_id
        new_members, new_repos = self._effective(
            org_id, team_id, proposed_map)
        new_member_names = {m.username for m in new_members}
        new_repo_names = {f"{r.owner}/{r.name}" for r in new_repos}
        by_id = {t.id: t for t in self._teams.list_teams(org_id)}
        ancestors_after = tuple(
            by_id[i].name for i in ancestor_ids(proposed_map, team_id)
            if i in by_id)
        if parent_id is None:
            message = ("The team would become a root team and "
                       "inherit nothing.")
        else:
            parent = by_id[parent_id]
            message = (f"The team would sit under {parent.name} and "
                       "inherit its members and repository links, "
                       "and those of every ancestor above it.")
        return NestingPreview(
            team_id=team.id, team_name=team.name,
            current_parent_id=team.parent_team_id,
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

    # -- changes -------------------------------------------
    def set_parent(
        self, actor_id: int, org_id: int, team_id: int,
        parent_id: int | None, source_ip: str | None = None,
    ) -> Team:
        """Set (or, with None, clear) a team's parent.
        Owner/admin only; the cycle, self-parent and
        same-organization laws are re-judged here, so a
        stale preview can never save an unlawful tree."""
        org_row = self._require_org_row(org_id)
        actor = self._require_owner_or_admin(actor_id, org_row)
        team = self._teams.get_team(org_id, team_id)
        parent = self._judge(org_id, team, parent_id)
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "UPDATE teams SET parent_team_id = ?,"
                " updated_at = ? WHERE id = ?",
                (parent_id, now, team.id))
        updated = self._teams.get_team(org_id, team_id)
        self._audit_change(
            actor, org_row,
            "clear_parent" if parent_id is None else "set_parent",
            updated, parent, source_ip=source_ip)
        return updated


def render_nesting_preview(org: Organization,
                           preview: NestingPreview) -> str:
    """The before-saving page: the proposed parent, the
    ancestor chain it would create, and exactly which
    members and repositories would be inherited or
    lost — every value escaped through S-010."""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Nested teams — preview — "
        f"{escape_html_text(org.name)} — Samverk</title></head>",
        "<body>",
        f"<h1>Before you save: {escape_html_text(preview.team_name)}</h1>",
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
        parts.append("<p>None — the team would be a root team.</p>")
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


def render_team_tree_page(org: Organization,
                          teams: list[Team]) -> str:
    """The organization's team tree: roots first, each
    child indented under its parent, with the
    inheritance law stated in plain words — every
    value escaped through S-010."""
    by_id = {t.id: t for t in teams}
    children: dict[int, list[Team]] = {}
    roots: list[Team] = []
    for team in teams:
        if team.parent_team_id is not None and team.parent_team_id in by_id:
            children.setdefault(team.parent_team_id, []).append(team)
        else:
            roots.append(team)
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Team tree — {escape_html_text(org.name)}"
        " — Samverk</title></head>",
        "<body>",
        f"<h1>Team tree in "
        f"{escape_html_text(org.effective_display_name())}</h1>",
        "<p>A child team inherits the members and "
        "repository links of every ancestor above it. "
        "Inheritance flows down, never up.</p>",
    ]

    def _walk(team: Team, depth: int, seen: set[int]):
        if team.id in seen:
            return
        seen.add(team.id)
        indent = "&nbsp;&nbsp;" * depth
        parts.append(
            f"<p>{indent}{escape_html_text(team.name)}</p>")
        for child in sorted(children.get(team.id, []),
                            key=lambda t: t.name_lower):
            _walk(child, depth + 1, seen)

    if roots:
        for root in sorted(roots, key=lambda t: t.name_lower):
            _walk(root, 0, set())
    else:
        parts.append("<p>No teams yet.</p>")
    parts.append("</body></html>")
    return "\n".join(parts)
