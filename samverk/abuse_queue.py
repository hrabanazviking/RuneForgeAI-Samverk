"""Abuse queue (S-355) -- one admin queue for user reports.

Part XVIII. Before this slice a user who found abusive
content or an abusive account had no door: comment
moderation (S-138) lets a moderator hide a comment they
themselves found, and suspension (S-044) lets an admin act
on an account they already know about, but nothing carried
a *report* from a signed-in user to the admins. This slice
is that door, and its laws are plain:

- **Any signed-in, active user may report** a repository,
  an issue, an issue comment, or an account, with a reason
  in plain words (required, bounded). The target must
  exist; reporting your own account is refused.
- **One queue.** Every report lands in the single
  `abuse_reports` table (migration 140) in state `open`.
  Admins work that one queue: acknowledge, resolve, or
  dismiss -- each with the acting admin recorded, resolve
  and dismiss requiring a reason in words. Terminal states
  (resolved, dismissed) never move again.
- **Audit context attached.** At filing time the report
  captures the audit entries that concern its target (by
  target kind/id, the standing AuditLog seams) as a list of
  sequence references. The references ride on the report;
  the chain itself is never copied or mutated, and the
  queue view resolves the references live and reports
  whether the chain still verifies (S-007's verify_chain).
- **Admins only see the queue.** A non-admin asking for
  the queue is refused. A reporter can always see their
  own reports and each one's state in plain words -- and
  nobody else's.
- **Duplicates follow the standing one-open-matter shape:**
  a second live (open or acknowledged) report by the same
  reporter on the same target is refused as a duplicate
  naming the standing report; a different reporter, or a
  fresh report after the earlier one closed, is fine.
- **Every act is audit-logged** under S-355's taxonomy
  additions: auth.abuse_report.filed (the filing, a user
  act) and admin.abuse_report.acknowledged / .resolved /
  .dismissed (the queue work, admin acts) -- taxonomy
  138 -> 142.
"""
from __future__ import annotations

import html
import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .accounts import AccountStore
from .audit import AuditLog, verify_chain

REASON_MAX = 1000
RESOLUTION_MAX = 1000

TARGET_REPOSITORY = "repository"
TARGET_ISSUE = "issue"
TARGET_COMMENT = "comment"
TARGET_ACCOUNT = "account"
TARGET_KINDS = (TARGET_REPOSITORY, TARGET_ISSUE,
                TARGET_COMMENT, TARGET_ACCOUNT)

STATE_OPEN = "open"
STATE_ACKNOWLEDGED = "acknowledged"
STATE_RESOLVED = "resolved"
STATE_DISMISSED = "dismissed"
STATES = (STATE_OPEN, STATE_ACKNOWLEDGED, STATE_RESOLVED,
          STATE_DISMISSED)
LIVE_STATES = (STATE_OPEN, STATE_ACKNOWLEDGED)
TERMINAL_STATES = (STATE_RESOLVED, STATE_DISMISSED)

_STATE_WORDS = {
    STATE_OPEN: "Waiting for an admin to look at it.",
    STATE_ACKNOWLEDGED: "An admin has seen it and is looking into it.",
    STATE_RESOLVED: "An admin looked into it and acted on it.",
    STATE_DISMISSED: "An admin looked into it and decided no action was needed.",
}

# Audit target_kind spellings each report target gathers
# context under (the seams as they stand in the log today).
_CONTEXT_KINDS = {
    TARGET_REPOSITORY: ("repo", "repository"),
    TARGET_ISSUE: ("issue", "repo"),
    TARGET_COMMENT: ("comment", "issue_comment"),
    TARGET_ACCOUNT: ("user", "account"),
}


class AbuseReportError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def state_words(state: str) -> str:
    """One report state, in plain words for its reporter."""
    return _STATE_WORDS.get(state, "Unknown state.")


def validate_report(target_kind: object, target_id: object,
                    reason: object) -> tuple:
    """Pure judgement: every way a report as handed is
    not fileable, named. Empty tuple means fileable in
    shape (existence is the service's check)."""
    problems = []
    if target_kind not in TARGET_KINDS:
        problems.append(
            f"target kind must be one of {', '.join(TARGET_KINDS)}")
    if target_id is None or not str(target_id).strip():
        problems.append("a report needs a target")
    if not isinstance(reason, str) or not reason.strip():
        problems.append("a report needs a reason in plain words")
    elif len(reason.strip()) > REASON_MAX:
        problems.append("that reason is too long")
    return tuple(problems)


def decide_transition(state: str, action: str) -> str | None:
    """Pure judgement: the state `action` moves a report
    in `state` to, or None when the move is not lawful."""
    if action == "acknowledge":
        return STATE_ACKNOWLEDGED if state == STATE_OPEN else None
    if action == "resolve":
        return STATE_RESOLVED if state in LIVE_STATES else None
    if action == "dismiss":
        return STATE_DISMISSED if state in LIVE_STATES else None
    return None


def is_duplicate(existing_states: list) -> bool:
    """Pure judgement: a reporter/target pair is a
    duplicate while any earlier report on it is live."""
    return any(s in LIVE_STATES for s in existing_states)


@dataclass(frozen=True)
class AbuseReport:
    id: int
    reporter_id: int
    target_kind: str
    target_id: str
    reason: str
    state: str
    audit_context: tuple = ()
    resolution_reason: str | None = None
    handled_by: int | None = None
    created_at: int = 0
    updated_at: int = 0

    @property
    def state_in_words(self) -> str:
        return state_words(self.state)


@dataclass(frozen=True)
class AuditContextEntry:
    seq: int
    ts: int
    actor_kind: str
    actor_id: int | None
    action: str
    outcome: str


@dataclass(frozen=True)
class QueueEntry:
    report: AbuseReport
    context: tuple = ()
    chain_ok: bool = True


def _row_to_report(row) -> AbuseReport:
    try:
        ctx = tuple(json.loads(row["audit_context"] or "[]"))
    except (ValueError, TypeError):
        ctx = ()
    return AbuseReport(
        id=row["id"], reporter_id=row["reporter_id"],
        target_kind=row["target_kind"], target_id=row["target_id"],
        reason=row["reason"], state=row["state"],
        audit_context=ctx,
        resolution_reason=row["resolution_reason"],
        handled_by=row["handled_by"],
        created_at=row["created_at"], updated_at=row["updated_at"])


class AbuseQueue:
    def __init__(self, conn: sqlite3.Connection,
                 accounts: AccountStore,
                 audit: AuditLog | None = None,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._accounts = accounts
        self._audit = audit
        self._now = time_fn

    # -- guards ----------------------------------------------
    def _require_admin(self, admin_id: int):
        admin = self._accounts.get_by_id(admin_id)
        if admin is None or not admin.is_admin:
            raise AbuseReportError(
                "not_admin", "Only an instance admin can do that.")
        return admin

    def _require_reporter(self, reporter_id: int):
        user = self._accounts.get_by_id(reporter_id)
        if user is None:
            raise AbuseReportError(
                "no_such_user", "No such account.")
        if user.status != "active":
            raise AbuseReportError(
                "not_active", "Only an active account can file a report.")
        return user

    def _target_exists(self, target_kind: str, target_id: str) -> bool:
        try:
            numeric = int(target_id)
        except (TypeError, ValueError):
            return False
        table = {TARGET_REPOSITORY: "repositories",
                 TARGET_ISSUE: "issues",
                 TARGET_COMMENT: "issue_comments",
                 TARGET_ACCOUNT: "users"}[target_kind]
        row = self._conn.execute(
            f"SELECT id FROM {table} WHERE id = ?", (numeric,)).fetchone()
        return row is not None

    def _gather_context(self, target_kind: str,
                        target_id: str) -> tuple:
        kinds = _CONTEXT_KINDS[target_kind]
        marks = ",".join("?" for _ in kinds)
        rows = self._conn.execute(
            f"SELECT seq FROM audit_log WHERE target_id = ?"
            f" AND target_kind IN ({marks}) ORDER BY seq",
            (target_id, *kinds)).fetchall()
        return tuple(int(r["seq"]) for r in rows)

    # -- filing -----------------------------------------------
    def file_report(self, reporter_id: int, target_kind: object,
                    target_id: object, reason: object,
                    *, source_ip: str | None = None) -> AbuseReport:
        self._require_reporter(reporter_id)
        problems = validate_report(target_kind, target_id, reason)
        if problems:
            raise AbuseReportError(
                "invalid_report", "; ".join(problems) + ".")
        kind = str(target_kind)
        tid = str(target_id).strip()
        if kind == TARGET_ACCOUNT and tid == str(reporter_id):
            raise AbuseReportError(
                "cannot_report_self",
                "You cannot report your own account.")
        if not self._target_exists(kind, tid):
            raise AbuseReportError(
                "no_such_target", "That report target does not exist.")
        prior = self._conn.execute(
            "SELECT state FROM abuse_reports WHERE reporter_id = ?"
            " AND target_kind = ? AND target_id = ?",
            (reporter_id, kind, tid)).fetchall()
        if is_duplicate([r["state"] for r in prior]):
            raise AbuseReportError(
                "duplicate",
                "You already have a live report on this; "
                "it is in the admin queue.")
        context = self._gather_context(kind, tid)
        now = int(self._now())
        text = str(reason).strip()
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO abuse_reports (reporter_id, target_kind,"
                " target_id, reason, state, audit_context, created_at,"
                " updated_at) VALUES (?, ?, ?, ?, 'open', ?, ?, ?)",
                (reporter_id, kind, tid, text,
                 json.dumps(list(context)), now, now))
            report_id = int(cur.lastrowid)
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=reporter_id,
                action="auth.abuse_report.filed", target_kind=kind,
                target_id=tid, outcome="success", source_ip=source_ip,
                detail={"report_id": report_id, "reason": text,
                        "audit_context": list(context)})
        return self.get_report(report_id)

    # -- reading ------------------------------------------------
    def get_report(self, report_id: int) -> AbuseReport:
        row = self._conn.execute(
            "SELECT * FROM abuse_reports WHERE id = ?",
            (report_id,)).fetchone()
        if row is None:
            raise AbuseReportError(
                "no_such_report", "No such report.")
        return _row_to_report(row)

    def context_for(self, report: AbuseReport) -> QueueEntry:
        """Resolve a report's attached audit references live
        and say whether the chain still verifies whole."""
        entries = []
        for seq in report.audit_context:
            row = self._conn.execute(
                "SELECT seq, ts, actor_kind, actor_id, action, outcome"
                " FROM audit_log WHERE seq = ?", (seq,)).fetchone()
            if row is not None:
                entries.append(AuditContextEntry(
                    seq=row["seq"], ts=row["ts"],
                    actor_kind=row["actor_kind"],
                    actor_id=row["actor_id"], action=row["action"],
                    outcome=row["outcome"]))
        ok, _bad, _n = verify_chain(self._conn)
        return QueueEntry(report=report, context=tuple(entries),
                          chain_ok=ok)

    def queue(self, admin_id: int) -> list:
        """The one admin queue: live reports first (oldest
        first), then closed ones, each with its context."""
        self._require_admin(admin_id)
        rows = self._conn.execute(
            "SELECT * FROM abuse_reports ORDER BY"
            " CASE WHEN state IN ('open','acknowledged') THEN 0 ELSE 1 END,"
            " created_at, id").fetchall()
        return [self.context_for(_row_to_report(r)) for r in rows]

    def my_reports(self, reporter_id: int) -> list:
        self._require_reporter(reporter_id)
        rows = self._conn.execute(
            "SELECT * FROM abuse_reports WHERE reporter_id = ?"
            " ORDER BY created_at, id", (reporter_id,)).fetchall()
        return [_row_to_report(r) for r in rows]

    def my_report(self, reporter_id: int, report_id: int) -> AbuseReport:
        report = self.get_report(report_id)
        if report.reporter_id != reporter_id:
            raise AbuseReportError(
                "not_yours", "That report is not yours to see.")
        return report

    # -- working the queue --------------------------------------
    def _work(self, admin_id: int, report_id: int, action: str,
              reason: object, *, source_ip: str | None = None) -> AbuseReport:
        self._require_admin(admin_id)
        report = self.get_report(report_id)
        new_state = decide_transition(report.state, action)
        if new_state is None:
            raise AbuseReportError(
                "bad_transition",
                f"A report that is {report.state} cannot be "
                f"{action}d from here.")
        text = None
        if action in ("resolve", "dismiss"):
            if not isinstance(reason, str) or not reason.strip():
                raise AbuseReportError(
                    "reason_required",
                    "Closing a report needs a reason in plain words.")
            text = reason.strip()
            if len(text) > RESOLUTION_MAX:
                raise AbuseReportError(
                    "reason_too_long", "That reason is too long.")
        now = int(self._now())
        with self._conn:
            self._conn.execute(
                "UPDATE abuse_reports SET state = ?, resolution_reason = ?,"
                " handled_by = ?, updated_at = ? WHERE id = ?",
                (new_state, text if text else report.resolution_reason,
                 admin_id, now, report_id))
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=admin_id,
                action=f"admin.abuse_report.{new_state}",
                target_kind=report.target_kind,
                target_id=report.target_id, outcome="success",
                source_ip=source_ip,
                detail={"report_id": report_id,
                        **({"reason": text} if text else {})})
        return self.get_report(report_id)

    def acknowledge(self, admin_id: int, report_id: int,
                    *, source_ip: str | None = None) -> AbuseReport:
        return self._work(admin_id, report_id, "acknowledge", None,
                          source_ip=source_ip)

    def resolve(self, admin_id: int, report_id: int, reason: object,
                *, source_ip: str | None = None) -> AbuseReport:
        return self._work(admin_id, report_id, "resolve", reason,
                          source_ip=source_ip)

    def dismiss(self, admin_id: int, report_id: int, reason: object,
                *, source_ip: str | None = None) -> AbuseReport:
        return self._work(admin_id, report_id, "dismiss", reason,
                          source_ip=source_ip)


# -- rendering ----------------------------------------------------

def render_queue(entries) -> str:
    """The admin queue page: every report with its reason
    and its attached audit context, all escaped."""
    parts = ["<h1>Abuse queue</h1>"]
    if not entries:
        parts.append("<p>No reports. The queue is empty.</p>")
    for entry in entries:
        r = entry.report
        parts.append("<section class='abuse-report'>")
        parts.append(
            f"<h2>Report {r.id}: {html.escape(r.target_kind)} "
            f"{html.escape(r.target_id)}</h2>")
        parts.append(f"<p>State: {html.escape(r.state)} -- "
                     f"{html.escape(r.state_in_words)}</p>")
        parts.append(f"<p>Reason: {html.escape(r.reason)}</p>")
        parts.append(f"<p>Reported by user {r.reporter_id}.</p>")
        if r.resolution_reason:
            parts.append("<p>Resolution: "
                         f"{html.escape(r.resolution_reason)}</p>")
        parts.append("<p>Audit chain: "
                     + ("intact" if entry.chain_ok else "BROKEN")
                     + "</p>")
        if entry.context:
            parts.append("<ul>")
            for c in entry.context:
                parts.append(
                    f"<li>#{c.seq} {html.escape(c.action)} "
                    f"({html.escape(c.outcome)})</li>")
            parts.append("</ul>")
        else:
            parts.append("<p>No audit context attached.</p>")
        parts.append("</section>")
    return "\n".join(parts)


def render_my_reports(reports) -> str:
    parts = ["<h1>Your reports</h1>"]
    if not reports:
        parts.append("<p>You have not filed any reports.</p>")
    for r in reports:
        parts.append(
            f"<p>Report {r.id} on {html.escape(r.target_kind)} "
            f"{html.escape(r.target_id)}: {html.escape(r.state_in_words)}</p>")
    return "\n".join(parts)
