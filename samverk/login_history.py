"""Login history (S-047).

The user-visible record of sign-ins and security events on
an account. Its source is the audit log itself (S-007) —
the same hash-chained witness the instance keeps — read
from the owner's side:

- **Whose events:** rows where the account is the actor, or
  where the account is the target of an admin act, plus
  failed logins attempted under the account's name (their
  `detail.attempted_user`, study 35 §4's caveat — an
  attempted name is shown to its owner as an attempt, never
  presented as the owner's own act).
- **Owner-only:** `history_for` is keyed by account id and
  returns only that account's rows; there is no cross-account
  view in this seam (admin audit access is a later part's
  governed surface).
- **Rendering** passes every value through S-010's escaping
  seam (source addresses and detail are data, not markup)
  and states times in UTC words.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass

from .accounts import AccountStore
from .escaping import escape_html_text

SIGNIN_ACTIONS = frozenset({
    "auth.login.success", "auth.login.failure", "auth.logout",
    "auth.signin.notify",
})


@dataclass(frozen=True)
class HistoryEntry:
    seq: int
    ts: int
    action: str
    outcome: str
    source_ip: str | None
    detail: dict | None

    @property
    def is_signin_event(self) -> bool:
        return self.action in SIGNIN_ACTIONS


class LoginHistory:
    def __init__(self, conn: sqlite3.Connection,
                 accounts: AccountStore):
        self._conn = conn
        self._accounts = accounts

    def history_for(self, user_id: int, *,
                    limit: int = 100,
                    signins_only: bool = False) -> list[HistoryEntry]:
        """Newest first, at most `limit` entries (limit is
        clamped to 1..500 so a surface cannot page the whole
        chain by accident)."""
        user = self._accounts.get_by_id(user_id)
        if user is None:
            return []
        limit = max(1, min(int(limit), 500))
        rows = self._conn.execute(
            "SELECT seq, ts, action, target_kind, target_id,"
            " actor_id, source_ip, outcome, detail FROM audit_log"
            " ORDER BY seq DESC").fetchall()
        out: list[HistoryEntry] = []
        for r in rows:
            detail = None
            if r["detail"]:
                try:
                    detail = json.loads(r["detail"])
                except (ValueError, TypeError):
                    detail = None
            owned = (
                r["actor_id"] == user_id
                or (r["target_kind"] == "user"
                    and r["target_id"] == str(user_id))
                or (r["action"] == "auth.login.failure"
                    and isinstance(detail, dict)
                    and str(detail.get("attempted_user", "")).lower()
                    == user.username_lower))
            if not owned:
                continue
            entry = HistoryEntry(
                seq=r["seq"], ts=r["ts"], action=r["action"],
                outcome=r["outcome"], source_ip=r["source_ip"],
                detail=detail)
            if signins_only and not entry.is_signin_event:
                continue
            out.append(entry)
            if len(out) >= limit:
                break
        return out


def _stamp(ts: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(ts))


def render_history_page(username: str,
                        entries: list[HistoryEntry]) -> str:
    who = escape_html_text(username)
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Sign-in and security history — {who} — Samverk</title>"
        "</head>",
        "<body>",
        "<h1>Sign-in and security history</h1>",
        '<p><a href="/settings">Back to settings</a></p>',
    ]
    if not entries:
        parts.append(
            '<p class="empty">No events yet. Sign-ins and '
            "security changes on your account will appear here.</p>")
    for e in entries:
        where = (f" from {escape_html_text(e.source_ip)}"
                 if e.source_ip else "")
        parts.append(
            f"<p>{_stamp(e.ts)} · {escape_html_text(e.action)} · "
            f"{escape_html_text(e.outcome)}{where}</p>")
    parts.append("</body></html>")
    return "\n".join(parts)
