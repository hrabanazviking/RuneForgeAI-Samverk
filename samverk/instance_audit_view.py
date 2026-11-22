"""Instance audit view (S-356).

Roadmap S-356: Instance audit view -- S-309 at
instance scope, chain-verified.

S-309 built the general audit-log face: repo,
org, and instance scopes over S-007's hash
chain, behind their doors, filterable and
exportable, with chain verification shown.
This slice is the dedicated instance face an
operator actually works from: the whole
instance's witness on one page, for site
admins only, windowed honestly over a chain
that may be long, with the shape of what was
found stated in counts (by actor, by action,
by target kind, by outcome) and S-007's chain
verification recomputed fresh on every read
and shown in words -- verified with the count
checked, or broken naming the first broken
entry. A broken chain is never dressed as
green: the status rides in the data, in the
headline, and on the rendered page.

- **Admin only.** The door is S-309's instance
door, unchanged: a viewer who is not a site
admin (or no viewer at all) hears the uniform
``audit_not_found`` -- the instance's whole
history is the instance's most sensitive read.
- **Filters are S-309's.** Action (a standing
taxonomy event, unknown names refused
``filter_invalid``), outcome, actor, target
kind, time window, plain-text query, judged by
S-309's pure law. Filtering only narrows.
- **Windowing is honest.** A page is a window
(offset + limit, limit 1..1000, default 50)
over the *filtered* rows in chain order. The
page states the filtered total, the window's
place in it, and whether more rows stand
before or after -- a window never pretends to
be the whole. An offset past the end is an
empty window, stated as such, not an error;
a malformed window is refused
``window_invalid``.
- **Breakdowns count what was found.** The
breakdowns count the filtered rows (before
windowing, so they describe the find, not the
page) by actor name, by action, by target
kind, and by outcome -- pure counts over the
rows, nothing inferred.
- **Chain verification is the whole chain.**
S-007's ``verify_chain`` recomputes from
genesis over every entry, whatever the filter
or window: a filter can hide a break from the
list but never from the verdict.
- **No migration, no new taxonomy event.**
This face stores nothing (schema 140 stands,
moved by S-355 after this face was built)
and audits nothing (142 events stand:
34 auth / 92 repo / 16 admin). The honesty
re-proof is ``audit_instance_audit_view``:
S-309's row proofs, plus the standing pins.
"""
from __future__ import annotations

import sqlite3
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit_log_ui import (
    AuditLogUIError, AuditLogUIStore, AuditView, ChainStatus,
    audit_audit_log_ui, render_audit_log_page)
from .escaping import escape_html_text
from .repositories import RepositoryStore

__all__ = [
    "WINDOW_DEFAULT", "WINDOW_MAX",
    "InstanceAuditPage", "InstanceAuditViewError",
    "InstanceAuditViewStore", "audit_instance_audit_view",
    "decide_window", "render_instance_audit_page",
    "summarise_breakdowns",
]

WINDOW_DEFAULT = 50
WINDOW_MAX = 1000


class InstanceAuditViewError(AuditLogUIError):
    """An instance-audit-view error, in the
    house shape (a RepositoryError with
    ``.reason``). S-309's errors ride through
    unchanged -- this class only adds the
    window law's own refusal."""


def decide_window(offset, limit, total: int) -> dict:
    """Pure window law: judge one window over
    ``total`` filtered rows. ``offset`` must be
    a non-negative integer and ``limit`` must
    stand between 1 and WINDOW_MAX; anything
    else is refused ``window_invalid`` rather
    than silently clamped. The judgement names
    the slice bounds and whether rows stand
    before or after the window."""
    if not isinstance(offset, int) or isinstance(offset, bool) \
            or offset < 0:
        raise InstanceAuditViewError(
            "window_invalid",
            "A window offset must be zero or more.")
    if limit is None:
        limit = WINDOW_DEFAULT
    if not isinstance(limit, int) or isinstance(limit, bool) \
            or not 1 <= limit <= WINDOW_MAX:
        raise InstanceAuditViewError(
            "window_invalid",
            f"A window limit must stand between 1 and {WINDOW_MAX}.")
    start = min(offset, total)
    end = min(offset + limit, total)
    return {
        "offset": offset, "limit": limit, "total": total,
        "start": start, "end": end,
        "shown": end - start,
        "has_before": start > 0,
        "has_after": end < total,
    }


def summarise_breakdowns(entries) -> dict:
    """Pure counts over rows: by actor name
    (unnamed actors counted as such), by action,
    by target kind, and by outcome. Counts are
    plain dicts sorted by name for a stable
    reading; nothing is inferred beyond the
    rows given."""
    return {
        "by_actor": dict(sorted(Counter(
            e.actor_username or "an unnamed actor"
            for e in entries).items())),
        "by_action": dict(sorted(Counter(
            e.action for e in entries).items())),
        "by_target_kind": dict(sorted(Counter(
            e.target_kind for e in entries).items())),
        "by_outcome": dict(sorted(Counter(
            e.outcome for e in entries).items())),
    }


@dataclass(frozen=True)
class InstanceAuditPage:
    """One window over the instance view: the
    windowed entries, the filtered total, the
    window judgement, the breakdowns over the
    filtered rows, the applied filters, and the
    whole chain's verification status."""
    entries: tuple
    total_filtered: int
    total_in_scope: int
    window: dict
    breakdowns: dict
    filters: dict
    chain: ChainStatus

    @property
    def shown(self) -> int:
        return len(self.entries)

    @property
    def headline_words(self) -> str:
        w = self.window
        if self.total_filtered == 0:
            base = "No audit entries match this view of the instance."
        elif w["shown"] == 0:
            base = (f"This window is empty: {self.total_filtered} "
                    "audit entries match, none at this offset.")
        else:
            base = (f"Audit entries {w['start'] + 1} to {w['end']} "
                    f"of {self.total_filtered} matching, "
                    f"of {self.total_in_scope} recorded for "
                    "the instance.")
        return base + " " + self.chain.words()

    def to_dict(self) -> dict:
        return {
            "scope": "instance",
            "scope_name": "the instance",
            "shown": self.shown,
            "total_filtered": self.total_filtered,
            "total_in_scope": self.total_in_scope,
            "window": dict(self.window),
            "breakdowns": self.breakdowns,
            "filters": {
                key: self.filters.get(key) for key in (
                    "action", "outcome", "actor_id",
                    "target_kind", "since", "until", "query")},
            "chain": self.chain.to_dict(),
            "headline": self.headline_words,
            "entries": [e.to_dict() for e in self.entries],
        }


class InstanceAuditViewStore:
    """The dedicated instance face over S-309:
    the same door, the same filter law, the
    same whole-chain verification -- plus the
    window and the breakdowns. It writes
    nothing and audits nothing."""

    def __init__(self, conn: sqlite3.Connection,
                 repositories: RepositoryStore,
                 accounts: AccountStore,
                 time_fn: Callable[[], float] = time.time):
        self._ui = AuditLogUIStore(
            conn, repositories, accounts, time_fn=time_fn)

    def page(self, viewer: User | None, *,
             action=None, outcome=None, actor_id=None,
             target_kind=None, since=None, until=None,
             query=None, offset=0,
             limit=WINDOW_DEFAULT) -> InstanceAuditPage:
        """One window over the instance's audit
        view. The full filtered view is gathered
        through S-309's admin door first (so the
        door and the filters judge before any
        window is cut), then the pure window law
        cuts the page and the breakdowns count
        the filtered rows."""
        view: AuditView = self._ui.instance_view(
            viewer, action=action, outcome=outcome,
            actor_id=actor_id, target_kind=target_kind,
            since=since, until=until, query=query, limit=None)
        filtered = view.entries
        window = decide_window(offset, limit, len(filtered))
        return InstanceAuditPage(
            entries=tuple(filtered[window["start"]:window["end"]]),
            total_filtered=len(filtered),
            total_in_scope=view.total_in_scope,
            window=window,
            breakdowns=summarise_breakdowns(filtered),
            filters=view.filters, chain=view.chain)

    def verification(self, viewer: User | None) -> ChainStatus:
        """The chain's standing alone, through
        the same admin door: verified with the
        count, or broken naming the entry."""
        view = self._ui.instance_view(viewer, limit=1)
        return view.chain

    def export(self, viewer: User | None, fmt: str = "json",
               **filters) -> str:
        """The whole filtered instance view as
        JSON or CSV, through S-309's export --
        the same door, the same filters, no
        second road out."""
        return self._ui.export_instance(viewer, fmt=fmt, **filters)


def render_instance_audit_page(page: InstanceAuditPage,
                               title: str = "Instance audit") -> str:
    """The page's face: S-309's renderer over a
    one-window view (headline, chain status in
    words, entries in plain words first), with
    the instance page's own window statement
    and breakdown counts stated in text before
    it. Every value reaches HTML through
    S-010."""
    view = AuditView(
        scope="instance", scope_name="the instance",
        entries=page.entries,
        total_in_scope=page.total_in_scope,
        filters=page.filters, chain=page.chain)
    body = render_audit_log_page(view, title=title)
    w = page.window
    lines = [
        f"<p>{escape_html_text(page.headline_words)}</p>",
        "<p>Window: entries "
        f"{w['start'] + 1 if w['shown'] else 0} to {w['end']} "
        f"of {page.total_filtered} matching; "
        + ("more entries stand after this window. "
           if w["has_after"] else "no entries stand after this window. ")
        + ("Entries stand before this window."
           if w["has_before"] else "No entries stand before this window.")
        + "</p>",
    ]
    for name, key in (("By outcome", "by_outcome"),
                      ("By target kind", "by_target_kind"),
                      ("By actor", "by_actor"),
                      ("By action", "by_action")):
        counts = page.breakdowns.get(key) or {}
        if counts:
            text = ", ".join(f"{k}: {v}" for k, v in counts.items())
            lines.append(
                f"<p>{name}: {escape_html_text(text)}.</p>")
    marker = "</body></html>"
    return body.replace(marker, "\n".join(lines) + "\n" + marker)


def audit_instance_audit_view(conn: sqlite3.Connection) -> list[str]:
    """Re-prove what this face claims: S-309's
    row proofs over the chain, the standing
    schema pin (140), the standing taxonomy pin
    (142: 34 auth / 92 repo / 16 admin), and no
    instance-audit surface of its own in the
    schema -- this face stores nothing."""
    from . import taxonomy
    from .db import schema_version
    problems = list(audit_audit_log_ui(conn))
    version = schema_version(conn)
    if version != 140:
        problems.append(
            f"schema version is {version}, expected 140")
    counts = (len(taxonomy.AUTH_EVENTS), len(taxonomy.REPO_EVENTS),
              len(taxonomy.ADMIN_EVENTS), len(taxonomy.AUDIT_EVENTS))
    if counts != (34, 92, 16, 142):
        problems.append(
            f"taxonomy counts are {counts}, expected (34, 92, 16, 142)")
    for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
        if "instance_audit" in str(row["name"]):
            problems.append(
                f"unexpected instance-audit table {row['name']!r}: "
                "the instance audit view stores nothing")
    return problems
