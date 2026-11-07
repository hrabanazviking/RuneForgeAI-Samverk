"""Org audit log (S-198).

Membership, permission, and repo events for the
org, readable by owners (storage is S-007's log).

- **A pure read over S-007's log.** This slice
  stores nothing of its own: it reads the
  hash-chained `audit_log` table S-007 built and
  picks out the rows that belong to one
  organization. Reading writes nothing and audits
  nothing — the witness is never its own reader's
  side effect.
- **Belonging is exact.** A row belongs to the
  organization when it is targeted at the
  organization itself (`target_kind` is
  `organization` and `target_id` is the org's
  canonical name), or at a repository under the
  organization (`target_kind` is `repo` and the
  lowercased `target_id` starts with the org's
  canonical name plus `/` — a whole path segment,
  so org `crew` never claims `crew2/repo`).
- **Categories are judged purely.**
  `classify_event` sorts each row into
  `membership`, `permission`, `repository` or
  `organization` from the recorded action, target
  kind and detail alone: membership-shaped org
  updates (detail fields `members`, `invitations`
  or `teams`), permission-shaped events
  (`repo.protection.*` and `repo.collaborator.*`
  actions, detail fields `team_permissions`,
  `default_permissions` / `default_permission` or
  `repositories`, and `set_permission` /
  `set_policy` / `set_default` changes), any other
  repository event, and the remaining
  organization events (creation, profile, avatar).
- **Owners read; the site steward may.** The
  roadmap gives this log to owners; a site admin
  may also read it (the house stewardship road,
  S-054/S-190). A plain member or a stranger is
  refused `not_org_owner`, an unknown organization
  is `org_not_found`, an unknown viewer is
  `no_such_user`, and an unknown category filter
  is `category_invalid`. Roles are judged by
  S-186's `OrgMembershipStore.role_for`, so the
  founding owner is seeded exactly as everywhere
  else in the house.
- **Plain words first.** Every entry carries a
  plain-words summary from the pure
  `event_summary` helper; the recorded action
  name rides second, never first and never alone,
  and the page states its category counts in text
  — never colour-only — and says honestly that an
  event no slice recorded in S-007's log cannot
  appear here.
- **No migration, no new taxonomy event.** The
  log stores nothing (schema stays 77) and audits
  nothing (122 events stand: 31 auth / 79 repo /
  12 admin); organizations, memberships and the
  audit chain stay S-185/S-186/S-007 ground and
  are only read here.
"""
from __future__ import annotations

import json
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
    "CATEGORIES", "OrgAuditEntry", "OrgAuditLogStore",
    "classify_event", "event_summary",
    "render_org_audit_page",
]

CATEGORIES = ("membership", "permission", "repository",
              "organization")

_MEMBERSHIP_FIELDS = frozenset({"members", "invitations", "teams"})
_PERMISSION_FIELDS = frozenset({
    "team_permissions", "default_permissions",
    "default_permission", "repositories"})
_MEMBERSHIP_SUBACTIONS = frozenset({
    "add", "remove", "leave", "role_change",
    "invite", "rescind", "accept",
    "add_member", "remove_member"})
_PERMISSION_SUBACTIONS = frozenset({
    "set_permission", "set_policy", "set_default"})


def _detail_fields(detail: dict | None) -> str | None:
    if not isinstance(detail, dict):
        return None
    value = detail.get("fields")
    return value if isinstance(value, str) else None


def _detail_action(detail: dict | None) -> str | None:
    if not isinstance(detail, dict):
        return None
    value = detail.get("action")
    return value if isinstance(value, str) else None


def classify_event(action: str, target_kind: str,
                   detail: dict | None) -> str:
    """Pure category law: which of the four kinds
    one recorded event is, judged only from its
    action, its target kind and its detail.

    Permission is judged before membership because
    S-189's team-permission changes ride the
    `teams` detail fields with the sub-action
    `set_permission` — the sub-action, not the
    fields word, is what makes them permission
    events. Repository is the fall-through for
    repo-targeted rows nothing sharper claimed,
    and organization is what remains."""
    if isinstance(action, str) and (
            action.startswith("repo.protection.")
            or action.startswith("repo.collaborator.")):
        return "permission"
    fields = _detail_fields(detail)
    sub = _detail_action(detail)
    if fields in _PERMISSION_FIELDS:
        return "permission"
    if sub in _PERMISSION_SUBACTIONS:
        return "permission"
    if fields in _MEMBERSHIP_FIELDS:
        return "membership"
    if target_kind == "organization" and sub in _MEMBERSHIP_SUBACTIONS:
        return "membership"
    if target_kind == "repo":
        return "repository"
    return "organization"


def _humanise(code: str) -> str:
    return code.replace("_", " ").replace(".", " ").strip()


_REPO_ACTION_WORDS = {
    "repo.create": "was created",
    "repo.delete": "was deleted",
    "repo.transfer": "was transferred",
    "repo.visibility.change": "had its visibility changed",
    "repo.push": "was pushed to",
    "repo.settings.change": "had its settings changed",
}


def event_summary(action: str, target_kind: str,
                  target_id: str | None,
                  detail: dict | None,
                  category: str | None = None) -> str:
    """One event in plain words, built only from
    what the audit row records: its category, its
    target, and the detail keys the emitters
    actually write (fields, action, target, role).
    Nothing is inferred beyond the row."""
    cat = category if category in CATEGORIES else classify_event(
        action, target_kind, detail)
    where = target_id or "an unnamed target"
    sub = _detail_action(detail)
    who = None
    if isinstance(detail, dict):
        named = detail.get("target")
        if isinstance(named, str) and named.strip():
            who = named.strip()
    if action == "auth.organization.create":
        return f"The organization {where} was created."
    if cat == "membership":
        if sub == "add" and who:
            return f"{who} was added as a member of {where}."
        if sub == "remove" and who:
            return f"{who} was removed from {where}."
        if sub == "leave" and who:
            return f"{who} left {where}."
        if sub == "role_change" and who:
            return f"The role of {who} in {where} was changed."
        if sub == "invite" and who:
            return f"{who} was invited to join {where}."
        if sub == "rescind" and who:
            return (f"The invitation for {who} to join "
                    f"{where} was withdrawn.")
        if sub == "accept" and who:
            return f"{who} accepted an invitation to join {where}."
        return f"Membership of {where} changed."
    if cat == "permission":
        if isinstance(action, str) and action.startswith(
                "repo.protection."):
            return f"Protection settings for {where} changed."
        if isinstance(action, str) and action.startswith(
                "repo.collaborator."):
            return f"Collaborator access for {where} changed."
        if sub == "set_permission":
            return (f"A team's repository permission in "
                    f"{where} was set.")
        if sub == "set_policy":
            return (f"The repository creation policy for "
                    f"{where} was set.")
        if sub == "set_default":
            return (f"The default repository permission "
                    f"for members of {where} was set.")
        return f"Permission settings for {where} changed."
    if cat == "repository":
        words = _REPO_ACTION_WORDS.get(action)
        if words is not None:
            return f"The repository {where} {words}."
        return (f"A repository event for {where}: "
                f"{_humanise(action or 'unknown action')}.")
    if sub == "set_policy":
        return f"Settings for {where} changed."
    return f"The organization {where} was updated."


@dataclass(frozen=True)
class OrgAuditEntry:
    """One audit row that belongs to the
    organization, read and explained. `detail` is
    the recorded detail parsed back into a dict
    (empty when the row recorded none); `summary`
    is the event in plain words."""
    seq: int
    ts: int
    actor_id: int | None
    actor_username: str | None
    action: str
    target_kind: str
    target_id: str | None
    outcome: str
    detail: dict
    category: str
    summary: str

    @property
    def words(self) -> str:
        return self.summary


def _belongs(target_kind: str, target_id: str | None,
             org_name_lower: str) -> bool:
    """The belonging law, exactly: the org itself,
    or a repository under the org's own first path
    segment — never a longer name that merely
    starts with the same letters."""
    if target_id is None:
        return False
    if target_kind == "organization":
        return target_id == org_name_lower
    if target_kind == "repo":
        return target_id.lower().startswith(org_name_lower + "/")
    return False


def _parse_detail(raw: object) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


class OrgAuditLogStore:
    """Reads one organization's events from the
    audit trail. Pure read: no writes, no audit."""

    def __init__(self, conn: sqlite3.Connection,
                 accounts: AccountStore,
                 audit: AuditLog | None = None,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._accounts = accounts
        self._audit = audit
        self._now = time_fn
        self._orgs = OrganizationStore(
            conn, accounts, audit, time_fn=time_fn)
        self._members = OrgMembershipStore(
            conn, accounts, audit, time_fn=time_fn)

    def list_events(self, viewer_id: int, org_id: int,
                    category: str | None = None) -> list[OrgAuditEntry]:
        """The organization's events in audit order
        (sequence ascending), optionally kept to one
        category. Owners and site admins only."""
        org = self._orgs.get_by_id(org_id)
        if org is None:
            raise OrganizationError(
                "org_not_found", "No such organization.")
        viewer = self._accounts.get_by_id(viewer_id)
        if viewer is None:
            raise OrganizationError(
                "no_such_user", "No such account.")
        if category is not None and category not in CATEGORIES:
            raise OrganizationError(
                "category_invalid",
                "An audit category is membership, permission, "
                "repository or organization.")
        if not viewer.is_admin:
            role = self._members.role_for(viewer_id, org_id)
            if role != "owner":
                raise OrganizationError(
                    "not_org_owner",
                    "Only an organization owner or a site admin "
                    "can read this organization's audit log.")
        rows = self._conn.execute(
            "SELECT seq, ts, actor_id, action, target_kind,"
            " target_id, outcome, detail FROM audit_log"
            " ORDER BY seq").fetchall()
        entries: list[OrgAuditEntry] = []
        for row in rows:
            if not _belongs(row["target_kind"], row["target_id"],
                            org.name_lower):
                continue
            detail = _parse_detail(row["detail"])
            cat = classify_event(
                row["action"], row["target_kind"], detail)
            if category is not None and cat != category:
                continue
            username = None
            if row["actor_id"] is not None:
                account = self._accounts.get_by_id(row["actor_id"])
                if account is not None:
                    username = account.username
            entries.append(OrgAuditEntry(
                seq=row["seq"], ts=row["ts"],
                actor_id=row["actor_id"],
                actor_username=username,
                action=row["action"],
                target_kind=row["target_kind"],
                target_id=row["target_id"],
                outcome=row["outcome"], detail=detail,
                category=cat,
                summary=event_summary(
                    row["action"], row["target_kind"],
                    row["target_id"], detail, cat)))
        return entries


def _stamp(ts: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(ts))


_CATEGORY_WORDS = {
    "membership": "membership",
    "permission": "permission",
    "repository": "repository",
    "organization": "organization",
}


def render_org_audit_page(org: Organization,
                          entries) -> str:
    """The org audit log page: every entry in plain
    words first with its recorded action second,
    the category counts stated in text, and the
    honest limit of the record stated plainly.
    Every value reaches HTML through S-010."""
    entries = list(entries)
    counts = {key: 0 for key in CATEGORIES}
    for entry in entries:
        if entry.category in counts:
            counts[entry.category] += 1
    name = escape_html_text(org.effective_display_name())
    total = len(entries)
    counts_text = (
        f"This log holds {total} "
        f"{'event' if total == 1 else 'events'}: "
        f"{counts['membership']} membership, "
        f"{counts['permission']} permission, "
        f"{counts['repository']} repository, "
        f"{counts['organization']} organization.")
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Audit log \u2014 {name} \u2014 Samverk</title></head>",
        "<body>",
        f"<h1>Audit log for {name}</h1>",
        "<p>Membership, permission and repository "
        "events for this organization, in the order "
        "they were recorded.</p>",
        "<p>This page can only show events that were "
        "recorded in the audit log. An event no slice "
        "recorded cannot appear here.</p>",
        f"<p>{escape_html_text(counts_text)}</p>",
    ]
    if not entries:
        parts.append(
            '<p class="empty">No events have been '
            "recorded for this organization yet.</p>")
    for entry in entries:
        who = (f" by {entry.actor_username}"
               if entry.actor_username else " by an unnamed actor")
        category_word = _CATEGORY_WORDS.get(
            entry.category, entry.category)
        parts.append('<div class="audit-entry">')
        parts.append(
            f"<p>{escape_html_text(_stamp(entry.ts))} \u2014 "
            f"{escape_html_text(entry.summary)} "
            f"The event was made{escape_html_text(who)}. "
            f"Category: {escape_html_text(category_word)}.</p>")
        parts.append(
            f"<p>Recorded as "
            f"{escape_html_text(entry.action)} \u00b7 "
            f"{escape_html_text(entry.outcome)} \u00b7 "
            f"audit entry {entry.seq}.</p>")
        parts.append("</div>")
    parts.append("</body></html>")
    return "\n".join(parts)
