"""Audit log UI (S-309).

Roadmap S-309: Audit log UI -- repo, org, and
instance views over S-007's chain, filterable,
exportable, with chain verification status shown.

S-007 built the witness: an append-only,
hash-chained audit log with `verify_chain`
recomputing the whole chain from genesis. S-198
gave one organization its own owner-read page
over that log. This slice is the general face:
the same chain read at three scopes -- one
repository, one organization, and the whole
instance -- behind the door each scope deserves,
with the filters a reader needs, an export in
JSON or CSV, and the chain's own verification
status standing on every view, computed fresh
from S-007's `verify_chain` at the moment of
the read.

- **Belonging is exact, per scope.** A row
  belongs to a repository when its target names
  that repository: `target_kind` is `repo` and
  the repository part of `target_id` (before any
  `#<number>` suffix, S-221's shape) is the
  repository's canonical full name, compared
  lowercased as a whole -- repo `crew/api` never
  claims `crew/api2`. A row belongs to an
  organization exactly as S-198 judged it: the
  organization itself, or a repository under the
  organization's own first path segment. The
  instance scope is every row in the chain.
- **The three doors.** The repository view is
  readable exactly where S-054's `can_read`
  opens the repository; a repository that does
  not stand, or does not open to this viewer,
  answers the uniform `repo_not_found` -- a
  private repository's audit history is as
  private as the repository. The organization
  view is readable by the organization's members
  and owners under S-186's membership (judged by
  pure read, the founding owner honoured without
  writing S-186's seed row) and by site admins;
  anyone else, and anyone asking after an
  organization that does not stand, hears the
  uniform `org_not_found`. The instance view is
  readable by **site admins only**; anyone else
  hears the uniform `audit_not_found`.
- **Filters are judged purely.**
  `decide_filter_match` decides one row against
  the filter from the row alone: action (an
  exact taxonomy event -- an unknown action name
  is refused `filter_invalid`, never silently
  an empty page), outcome (exact), actor (exact
  account id), target kind (exact), a time
  window (`since` / `until` epoch seconds,
  inclusive at both ends, `since` after `until`
  refused), and a plain-text `query` matched
  case-insensitively across the action, target,
  actor name and recorded detail. An entry
  limit, when given, must stand between 1 and
  1000. Filtering never widens a scope: it only
  keeps rows the scope already held.
- **Chain verification status is shown, always.**
  Every view carries a `ChainStatus` recomputed
  by S-007's `verify_chain` over the *whole*
  chain (the chain is one chain; a scope is a
  window onto it, and the status says so): the
  status in words -- verified, with the number
  of entries checked, or broken, naming the
  first broken sequence number. The status
  stands in the view's data, in its headline
  words, and on the rendered page -- never
  colour alone.
- **Exportable.** `export_audit_view` renders
  one view as JSON (the view's own `to_dict`)
  or as CSV (one row per entry, the recorded
  fields in chain order, the detail as its
  canonical JSON text). Export goes through
  the same doors and the same filters as the
  view itself -- the store's `export_*` methods
  build the view first, so there is no second,
  wider road out. An unknown format is refused
  `export_format_invalid`.
- **Plain words first.** Every entry carries a
  plain-words summary from the pure
  `event_summary` helper (the recorded action
  humanised, its target named, its actor
  named); the recorded action name rides
  second, never first and never alone, and the
  page states its counts in text.
- **No migration, no new taxonomy event.** The
  UI stores nothing (schema 127 stands) and
  audits nothing (135 events stand: 33 auth /
  89 repo / 13 admin): reading the witness is
  not an act the witness records. The honesty
  re-proof is `audit_audit_log_ui`: every row's
  action stands in the taxonomy, sequence
  numbers run unbroken from 1, every row
  carries both hashes, and every named actor
  stands as an account.

Storage: none of its own. This slice adds **no
migration** (schema 127 stands) and moves no
standing pin; it reads the audit chain, the
accounts, the organizations, memberships and
repositories tables as they already stand.
"""
from __future__ import annotations

import csv
import io
import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import verify_chain
from .escaping import escape_html_text
from .event_store import repository_of
from .permissions import can_read
from .repositories import RepositoryError, RepositoryStore
from .taxonomy import is_known_event

__all__ = [
    "AUDIT_SCOPES", "EXPORT_FORMATS", "LIMIT_MAX",
    "AuditEntry", "AuditLogUIError", "AuditLogUIStore",
    "AuditView", "ChainStatus", "audit_audit_log_ui",
    "decide_chain_status", "decide_filter_match",
    "decide_scope_belongs", "event_summary",
    "export_audit_view", "render_audit_log_page",
]

AUDIT_SCOPES = ("repo", "org", "instance")
EXPORT_FORMATS = ("json", "csv")
LIMIT_MAX = 1000


class AuditLogUIError(RepositoryError):
    """An audit-log-UI error: a RepositoryError
    carrying `.reason`, in the house shape."""


# ---------------------------------------------------------------------
# The pure judgements
# ---------------------------------------------------------------------

def decide_scope_belongs(scope: str, scope_key: str | None,
                         target_kind: str,
                         target_id: str | None) -> bool:
    """Pure belonging law: whether one audit row
    belongs to a scope, judged only from the
    scope, its key, and the row's recorded target.

    The instance scope holds every row. The repo
    scope holds a row whose target names exactly
    that repository (S-221's repository-of shape:
    the part before any `#` suffix, whole segments
    only). The org scope holds the organization
    itself and repositories under its own first
    path segment, exactly as S-198 judged. An
    unknown scope holds nothing -- fail closed.
    """
    if scope == "instance":
        return True
    if scope_key is None or target_id is None:
        return False
    key = scope_key.lower()
    if scope == "repo":
        if target_kind != "repo":
            return False
        repo_name = repository_of(target_id)
        return repo_name is not None and repo_name.lower() == key
    if scope == "org":
        if target_kind == "organization":
            return target_id.lower() == key
        if target_kind == "repo":
            return target_id.lower().startswith(key + "/")
        return False
    return False


def _validate_filters(action, outcome, actor_id, target_kind,
                      since, until, query, limit) -> dict:
    """The filter law, validated once: an action
    filter must name a standing taxonomy event, a
    time window must not run backwards, and a
    limit must stand in range -- anything else is
    refused by name rather than answered with a
    silently wrong page."""
    if action is not None and not (
            isinstance(action, str) and is_known_event(action)):
        raise AuditLogUIError(
            "filter_invalid",
            f"No such audit event to filter by: {action!r}.")
    if outcome is not None and not (
            isinstance(outcome, str) and outcome.strip()):
        raise AuditLogUIError(
            "filter_invalid", "An outcome filter must name an outcome.")
    if actor_id is not None and not (
            isinstance(actor_id, int) and actor_id >= 1):
        raise AuditLogUIError(
            "filter_invalid", "An actor filter must name an account.")
    if target_kind is not None and not (
            isinstance(target_kind, str) and target_kind.strip()):
        raise AuditLogUIError(
            "filter_invalid",
            "A target-kind filter must name a target kind.")
    for name, value in (("since", since), ("until", until)):
        if value is not None and not isinstance(value, int):
            raise AuditLogUIError(
                "filter_invalid",
                f"The {name} filter must be epoch seconds.")
    if since is not None and until is not None and since > until:
        raise AuditLogUIError(
            "filter_invalid",
            "The time window runs backwards: since is after until.")
    if query is not None and not isinstance(query, str):
        raise AuditLogUIError(
            "filter_invalid", "A query filter must be text.")
    if limit is not None and not (
            isinstance(limit, int) and 1 <= limit <= LIMIT_MAX):
        raise AuditLogUIError(
            "filter_invalid",
            f"An entry limit must stand between 1 and {LIMIT_MAX}.")
    return {
        "action": action, "outcome": outcome,
        "actor_id": actor_id, "target_kind": target_kind,
        "since": since, "until": until,
        "query": query.strip() if isinstance(query, str) else None,
        "limit": limit,
    }


def decide_filter_match(*, action: str, outcome: str,
                        actor_id: int | None,
                        actor_username: str | None,
                        target_kind: str, target_id: str | None,
                        detail_text: str, ts: int,
                        filters: dict) -> bool:
    """Pure filter law: whether one row survives
    the filter, judged only from the row and the
    (already validated) filter. Every named
    condition must hold; the query looks across
    the action, the target, the actor's name and
    the recorded detail text, case-insensitively.
    """
    if filters.get("action") is not None \
            and action != filters["action"]:
        return False
    if filters.get("outcome") is not None \
            and outcome != filters["outcome"]:
        return False
    if filters.get("actor_id") is not None \
            and actor_id != filters["actor_id"]:
        return False
    if filters.get("target_kind") is not None \
            and target_kind != filters["target_kind"]:
        return False
    if filters.get("since") is not None and ts < filters["since"]:
        return False
    if filters.get("until") is not None and ts > filters["until"]:
        return False
    query = filters.get("query")
    if query:
        haystack = " ".join(part for part in (
            action, target_id or "", actor_username or "",
            detail_text or "") if part).lower()
        if query.lower() not in haystack:
            return False
    return True


def decide_chain_status(ok: object, first_bad_seq,
                        entries_checked) -> str:
    """The chain's standing in one word, pure:
    ``verified`` when S-007's recompute found no
    break, ``broken`` when it named one. A verdict
    that is not a plain boolean is refused by
    name rather than dressed up."""
    if not isinstance(ok, bool):
        raise AuditLogUIError(
            "chain_status_invalid",
            "A chain verdict must be true or false.")
    return "verified" if ok else "broken"


# ---------------------------------------------------------------------
# The records
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class ChainStatus:
    """The whole chain's verification standing at
    the moment of a read, from S-007's
    `verify_chain`: whether it verified, the
    first broken sequence number when it did
    not, and how many entries were checked."""
    ok: bool
    first_bad_seq: int | None
    entries_checked: int

    @property
    def status(self) -> str:
        return decide_chain_status(
            self.ok, self.first_bad_seq, self.entries_checked)

    def words(self) -> str:
        if self.ok:
            return (
                f"Chain verified: {self.entries_checked} "
                f"{'entry' if self.entries_checked == 1 else 'entries'} "
                "checked, no break found.")
        return (
            f"Chain broken at entry {self.first_bad_seq}: "
            f"{self.entries_checked} entries checked before "
            "the break. The audit record cannot be trusted "
            "past that entry until it is investigated.")

    def to_dict(self) -> dict:
        return {
            "status": self.status, "ok": self.ok,
            "first_bad_seq": self.first_bad_seq,
            "entries_checked": self.entries_checked,
            "words": self.words(),
        }


def _humanise(code: str) -> str:
    return code.replace("_", " ").replace(".", " ").strip()


def event_summary(action: str, target_kind: str,
                  target_id: str | None,
                  actor_username: str | None,
                  outcome: str) -> str:
    """One event in plain words, built only from
    what the audit row records: who acted, what
    was done (the action humanised), on what
    target, and how it ended. Nothing is inferred
    beyond the row."""
    who = actor_username or "an unnamed actor"
    what = _humanise(action or "unknown action")
    where = target_id or f"an unnamed {target_kind or 'target'}"
    return f"{who} -- {what} -- on {where} ({outcome})."


@dataclass(frozen=True)
class AuditEntry:
    """One audit row, read and explained: the
    recorded fields as they stand in S-007's
    chain, the actor's name resolved at read
    time, the detail parsed back into a dict
    (empty when the row recorded none), and the
    event in plain words."""
    seq: int
    ts: int
    actor_kind: str
    actor_id: int | None
    actor_username: str | None
    action: str
    target_kind: str
    target_id: str | None
    source_ip: str | None
    outcome: str
    detail: dict
    prev_hash: str
    entry_hash: str
    summary: str

    @property
    def words(self) -> str:
        return self.summary

    @property
    def detail_text(self) -> str:
        if not self.detail:
            return ""
        return json.dumps(
            self.detail, sort_keys=True, separators=(",", ":"))

    def to_dict(self) -> dict:
        return {
            "seq": self.seq, "ts": self.ts,
            "actor_kind": self.actor_kind,
            "actor_id": self.actor_id,
            "actor_username": self.actor_username,
            "action": self.action,
            "target_kind": self.target_kind,
            "target_id": self.target_id,
            "source_ip": self.source_ip,
            "outcome": self.outcome,
            "detail": dict(self.detail),
            "prev_hash": self.prev_hash,
            "entry_hash": self.entry_hash,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class AuditView:
    """One scope's audit view: the scope and its
    name, the entries that survived the filter in
    chain order, how many rows the scope held
    before filtering, the filter as applied, and
    the whole chain's verification status."""
    scope: str
    scope_name: str
    entries: tuple
    total_in_scope: int
    filters: dict
    chain: ChainStatus

    @property
    def shown(self) -> int:
        return len(self.entries)

    @property
    def headline_words(self) -> str:
        noun = "entry" if self.shown == 1 else "entries"
        base = (
            f"{self.shown} audit {noun} shown of "
            f"{self.total_in_scope} recorded for "
            f"{self.scope_name}.")
        return base + " " + self.chain.words()

    def to_dict(self) -> dict:
        return {
            "scope": self.scope,
            "scope_name": self.scope_name,
            "shown": self.shown,
            "total_in_scope": self.total_in_scope,
            "filters": {
                key: self.filters.get(key) for key in (
                    "action", "outcome", "actor_id",
                    "target_kind", "since", "until", "query")},
            "chain": self.chain.to_dict(),
            "headline": self.headline_words,
            "entries": [e.to_dict() for e in self.entries],
        }


# ---------------------------------------------------------------------
# The store: the gathered read over S-007's chain
# ---------------------------------------------------------------------

class AuditLogUIStore:
    """The audit log's three faces: repository,
    organization and instance views over S-007's
    chain, behind the doors the module docstring
    decides. It writes nothing and audits nothing;
    S-007's log remains the only witness."""

    def __init__(self, conn: sqlite3.Connection,
                 repositories: RepositoryStore,
                 accounts: AccountStore,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._time = time_fn

    # -- the doors --------------------------------------------------

    def _resolve_repo(self, viewer: User | None, owner, repo):
        """The repository, through S-054's door: a
        missing repository answers `repo_not_found`;
        so does one `can_read` does not open."""
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise AuditLogUIError(
                "repo_not_found", "No such repository.")
        return current

    def _org_role(self, viewer: User | None, org_row) -> str | None:
        """The viewer's standing in the organization,
        judged by pure read exactly as S-308 judged
        it: a site admin stands as ``site_admin``; a
        standing membership row gives its S-186 role;
        and where the organization has no membership
        rows at all its creator stands as founding
        ``owner`` -- judged here without writing the
        seed, because this surface writes nothing."""
        if viewer is None:
            return None
        if viewer.is_admin:
            return "site_admin"
        row = self._conn.execute(
            "SELECT role FROM organization_members"
            " WHERE org_id = ? AND user_id = ?",
            (org_row["id"], viewer.id)).fetchone()
        if row is not None:
            return row["role"]
        if viewer.id == org_row["created_by"]:
            count = self._conn.execute(
                "SELECT COUNT(*) AS n FROM"
                " organization_members WHERE org_id = ?",
                (org_row["id"],)).fetchone()["n"]
            if int(count) == 0:
                return "owner"
        return None

    def _resolve_org(self, viewer: User | None, org_name):
        """The organization row, through the org door:
        a missing organization answers
        ``org_not_found``; so does one this viewer
        neither belongs to nor administers."""
        if not isinstance(org_name, str) or not org_name.strip():
            raise AuditLogUIError(
                "org_not_found", "No such organization.")
        row = self._conn.execute(
            "SELECT * FROM organizations WHERE name_lower = ?",
            (org_name.strip().lower(),)).fetchone()
        if row is None or self._org_role(viewer, row) is None:
            raise AuditLogUIError(
                "org_not_found", "No such organization.")
        return row

    # -- gathering ----------------------------------------------------

    def _chain_status(self) -> ChainStatus:
        ok, first_bad, checked = verify_chain(self._conn)
        return ChainStatus(
            ok=bool(ok), first_bad_seq=first_bad,
            entries_checked=int(checked))

    def _build(self, scope: str, scope_name: str,
               scope_key: str | None, filters: dict) -> AuditView:
        rows = self._conn.execute(
            "SELECT seq, ts, actor_kind, actor_id, action,"
            " target_kind, target_id, source_ip, outcome,"
            " detail, prev_hash, entry_hash FROM audit_log"
            " ORDER BY seq").fetchall()
        entries: list = []
        total = 0
        limit = filters.get("limit")
        for row in rows:
            if not decide_scope_belongs(
                    scope, scope_key, row["target_kind"],
                    row["target_id"]):
                continue
            total += 1
            detail = _parse_detail(row["detail"])
            username = None
            if row["actor_id"] is not None:
                account = self._accounts.get_by_id(row["actor_id"])
                if account is not None:
                    username = account.username
            if not decide_filter_match(
                    action=row["action"], outcome=row["outcome"],
                    actor_id=row["actor_id"],
                    actor_username=username,
                    target_kind=row["target_kind"],
                    target_id=row["target_id"],
                    detail_text=row["detail"] or "",
                    ts=int(row["ts"]), filters=filters):
                continue
            if limit is not None and len(entries) >= limit:
                continue
            entries.append(AuditEntry(
                seq=int(row["seq"]), ts=int(row["ts"]),
                actor_kind=row["actor_kind"],
                actor_id=row["actor_id"],
                actor_username=username,
                action=row["action"],
                target_kind=row["target_kind"],
                target_id=row["target_id"],
                source_ip=row["source_ip"],
                outcome=row["outcome"], detail=detail,
                prev_hash=row["prev_hash"],
                entry_hash=row["entry_hash"],
                summary=event_summary(
                    row["action"], row["target_kind"],
                    row["target_id"], username, row["outcome"])))
        return AuditView(
            scope=scope, scope_name=scope_name,
            entries=tuple(entries), total_in_scope=total,
            filters=filters, chain=self._chain_status())

    def _filters(self, action, outcome, actor_id, target_kind,
                 since, until, query, limit) -> dict:
        return _validate_filters(
            action, outcome, actor_id, target_kind,
            since, until, query, limit)

    # -- the reads -----------------------------------------------------

    def repo_view(self, viewer: User | None, owner, repo, *,
                  action=None, outcome=None, actor_id=None,
                  target_kind=None, since=None, until=None,
                  query=None, limit=None) -> AuditView:
        """One repository's audit view: the rows
        whose target names this repository, for a
        viewer S-054's `can_read` opens it to."""
        filters = self._filters(
            action, outcome, actor_id, target_kind,
            since, until, query, limit)
        current = self._resolve_repo(viewer, owner, repo)
        return self._build(
            "repo", current.full_name,
            current.full_name, filters)

    def org_view(self, viewer: User | None, org_name, *,
                 action=None, outcome=None, actor_id=None,
                 target_kind=None, since=None, until=None,
                 query=None, limit=None) -> AuditView:
        """One organization's audit view: the rows
        belonging to the organization and its
        repositories (S-198's belonging), for its
        members and owners and for site admins."""
        filters = self._filters(
            action, outcome, actor_id, target_kind,
            since, until, query, limit)
        org_row = self._resolve_org(viewer, org_name)
        return self._build(
            "org", org_row["name"], org_row["name_lower"], filters)

    def instance_view(self, viewer: User | None, *,
                      action=None, outcome=None, actor_id=None,
                      target_kind=None, since=None, until=None,
                      query=None, limit=None) -> AuditView:
        """The instance audit view: every row in
        the chain, for site admins only."""
        filters = self._filters(
            action, outcome, actor_id, target_kind,
            since, until, query, limit)
        if viewer is None or not viewer.is_admin:
            raise AuditLogUIError(
                "audit_not_found", "No such audit log.")
        return self._build("instance", "the instance", None, filters)

    # -- export: the same doors, the same filters ----------------------

    def export_repo(self, viewer: User | None, owner, repo,
                    fmt: str = "json", **filters) -> str:
        return export_audit_view(
            self.repo_view(viewer, owner, repo, **filters), fmt)

    def export_org(self, viewer: User | None, org_name,
                   fmt: str = "json", **filters) -> str:
        return export_audit_view(
            self.org_view(viewer, org_name, **filters), fmt)

    def export_instance(self, viewer: User | None,
                        fmt: str = "json", **filters) -> str:
        return export_audit_view(
            self.instance_view(viewer, **filters), fmt)


def _parse_detail(raw: object) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


# ---------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------

_CSV_FIELDS = (
    "seq", "ts", "actor_kind", "actor_id", "actor_username",
    "action", "target_kind", "target_id", "source_ip",
    "outcome", "detail", "prev_hash", "entry_hash")


def export_audit_view(view: AuditView, fmt: str = "json") -> str:
    """One view as a portable record: JSON (the
    view's own dict, chain status included) or
    CSV (one row per shown entry, in chain
    order, the detail as its canonical JSON
    text). An unknown format is refused by
    name -- an export is a copy of the record
    and its shape is never guessed."""
    if fmt not in EXPORT_FORMATS:
        raise AuditLogUIError(
            "export_format_invalid",
            f"An audit export is one of: {', '.join(EXPORT_FORMATS)}.")
    if fmt == "json":
        return json.dumps(view.to_dict(), indent=2, sort_keys=True)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CSV_FIELDS)
    for entry in view.entries:
        writer.writerow([
            entry.seq, entry.ts, entry.actor_kind,
            "" if entry.actor_id is None else entry.actor_id,
            entry.actor_username or "", entry.action,
            entry.target_kind, entry.target_id or "",
            entry.source_ip or "", entry.outcome,
            entry.detail_text, entry.prev_hash, entry.entry_hash])
    return buffer.getvalue()


# ---------------------------------------------------------------------
# Rendering (S-010 escaped; the chain status stands on the page)
# ---------------------------------------------------------------------

def _stamp(ts: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(ts))


def render_audit_log_page(view: AuditView,
                          title: str = "Audit log") -> str:
    """The view's face: its name, its headline in
    words (counts plus the chain's verification
    status, in text -- never colour alone), the
    filter as applied stated plainly, and every
    shown entry in plain words first with its
    recorded action second. Every value reaches
    HTML through S-010."""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{escape_html_text(title)} \u2014 "
        f"{escape_html_text(view.scope_name)} \u2014 Samverk</title></head>",
        "<body>",
        f"<h1>{escape_html_text(title)} for "
        f"{escape_html_text(view.scope_name)}</h1>",
        f"<p>{escape_html_text(view.headline_words)}</p>",
        f"<p>Chain verification: "
        f"{escape_html_text(view.chain.words())}</p>",
        "<p>This page can only show events that were "
        "recorded in the audit log. An event no slice "
        "recorded cannot appear here. The chain "
        "verification status covers the whole audit "
        "chain; this view is one scope's window onto "
        "it.</p>",
    ]
    applied = [
        f"{key}={view.filters[key]}" for key in (
            "action", "outcome", "actor_id", "target_kind",
            "since", "until", "query", "limit")
        if view.filters.get(key) is not None]
    if applied:
        parts.append(
            "<p>Filters applied: "
            + escape_html_text(", ".join(applied)) + ".</p>")
    else:
        parts.append("<p>No filters applied.</p>")
    if not view.entries:
        parts.append(
            '<p class="empty">No audit entries match '
            "this view.</p>")
    for entry in view.entries:
        parts.append('<div class="audit-entry">')
        parts.append(
            f"<p>{escape_html_text(_stamp(entry.ts))} \u2014 "
            f"{escape_html_text(entry.summary)}</p>")
        parts.append(
            f"<p>Recorded as "
            f"{escape_html_text(entry.action)} \u00b7 "
            f"{escape_html_text(entry.outcome)} \u00b7 "
            f"audit entry {entry.seq}.</p>")
        parts.append("</div>")
    parts.append("</body></html>")
    return "\n".join(parts)


# ---------------------------------------------------------------------
# Audit: the honesty invariant over the chain's rows
# ---------------------------------------------------------------------

def audit_audit_log_ui(conn: sqlite3.Connection) -> list[str]:
    """Re-prove what the UI claims of the standing
    rows: every row's action stands in the
    taxonomy, sequence numbers run unbroken from
    1, every row carries both of its hashes, and
    every named actor stands as an account. The
    UI reads rows as they stand -- this is where
    a row that cannot stand is said."""
    problems: list[str] = []
    user_ids = {int(row["id"]) for row in conn.execute(
        "SELECT id FROM users").fetchall()}
    rows = conn.execute(
        "SELECT seq, actor_id, action, prev_hash, entry_hash"
        " FROM audit_log ORDER BY seq").fetchall()
    expected = 1
    for row in rows:
        if int(row["seq"]) != expected:
            problems.append(
                f"audit entry sequence breaks: expected "
                f"{expected}, found {row['seq']}")
            expected = int(row["seq"])
        expected += 1
        if not is_known_event(row["action"]):
            problems.append(
                f"audit entry {row['seq']} carries action "
                f"{row['action']!r} outside the taxonomy")
        if not row["prev_hash"] or not row["entry_hash"]:
            problems.append(
                f"audit entry {row['seq']} is missing "
                "one of its chain hashes")
        if row["actor_id"] is not None \
                and int(row["actor_id"]) not in user_ids:
            problems.append(
                f"audit entry {row['seq']} names actor "
                f"{row['actor_id']}, who does not stand")
    return problems
