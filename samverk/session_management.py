"""Session management (S-040) — the owner's view of their
own sign-ins.

The anti-Forgejo test applied to sessions: from the settings
home the owner reaches **Security and sessions** in one
click (S-034's settings home already links it) and sees
every session their account holds — which device, from
which address, when it began, when it was last active, and
an honest status word (Active / Revoked / Expired — text,
never colour alone).

- **Revoke any:** one call tombstones one session
  (owner-scoped in the S-006 store's query itself), and the
  acceptance is the store's own law — a revoked session's
  next `authenticate` answers None, on the very next request.
- **Revoke all:** the "someone may be in my account" remedy,
  with the owner's current session optionally spared so the
  remedy does not lock out the person wielding it.
- Every revocation that actually lands is audited
  `auth.session.revoke` with its scope (`one` / `all`) — the
  event has waited in the frozen taxonomy since S-008.
- Device labels are user-facing recognition aids and are
  treated as hostile text here as everywhere: the page
  renders only through S-010's escaping seam.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore
from .audit import AuditLog
from .escaping import escape_html_attr, escape_html_text
from .sessions import SessionStore

SESSIONS_PATH = "/settings/security"
REVOKE_PATH = "/settings/security/revoke"
REVOKE_ALL_PATH = "/settings/security/revoke-all"


@dataclass(frozen=True)
class SessionSummary:
    id: int
    device_label: str        # "Unknown device" when unlabelled
    source_ip: str | None
    created_at: int
    last_seen_at: int
    status: str              # "Active" | "Revoked" | "Expired"
    current: bool            # the session asking, when known

    @property
    def live(self) -> bool:
        return self.status == "Active"


class SessionManagement:
    def __init__(
        self,
        conn: sqlite3.Connection,
        accounts: AccountStore,
        sessions: SessionStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._accounts = accounts
        self._sessions = sessions
        self._audit = audit
        self._now = time_fn

    def _status(self, info, now: int) -> str:
        if info.revoked:
            return "Revoked"
        if now >= info.absolute_expires_at or \
                now - info.last_seen_at > self._sessions.idle_ttl:
            return "Expired"
        return "Active"

    def list_sessions(
        self, user_id: int, current_token: str | None = None,
    ) -> list[SessionSummary]:
        user = self._accounts.get_by_id(user_id)
        if user is None:
            raise ValueError("no such account")
        now = int(self._now())
        current_id = (self._sessions.id_for_token(current_token)
                      if current_token else None)
        return [SessionSummary(
            id=info.id,
            device_label=info.device_label or "Unknown device",
            source_ip=info.source_ip,
            created_at=info.created_at,
            last_seen_at=info.last_seen_at,
            status=self._status(info, now),
            current=info.id == current_id)
            for info in self._sessions.list_for_user(user_id)]

    def revoke_one(
        self, user_id: int, session_id: object,
        source_ip: str | None = None,
    ) -> bool:
        """Revoke a single session. Owner-only (enforced in
        the store's query); audits only a revocation that
        actually landed."""
        if not isinstance(session_id, int) \
                or isinstance(session_id, bool):
            return False
        revoked = self._sessions.revoke_by_id(user_id, session_id)
        if revoked and self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user_id,
                action="auth.session.revoke", target_kind="user",
                target_id=str(user_id), outcome="success",
                source_ip=source_ip, detail={"scope": "one"})
        return revoked

    def revoke_all(
        self, user_id: int, keep_token: str | None = None,
        source_ip: str | None = None,
    ) -> int:
        """Revoke every live session of the account, sparing
        the session that presents `keep_token` when given.
        Returns how many sessions died; audits the sweep when
        at least one did."""
        keep_id = (self._sessions.id_for_token(keep_token)
                   if keep_token else None)
        count = self._sessions.revoke_all(user_id, except_id=keep_id)
        if count and self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=user_id,
                action="auth.session.revoke", target_kind="user",
                target_id=str(user_id), outcome="success",
                source_ip=source_ip, detail={"scope": "all"})
        return count


def _stamp(ts: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(ts))


def render_sessions_page(
    username: str, summaries: list[SessionSummary],
    csrf_token: str = "",
) -> str:
    """The sessions page: one block per session with its
    governing facts, a *this session* marker in words, and a
    revoke form for every live session but the current one
    (revoking the current session is what Logout is for)."""
    who = escape_html_text(username)
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Security and sessions — {who} — Samverk</title></head>",
        "<body>",
        "<h1>Security and sessions</h1>",
        '<p><a href="/settings">Back to settings</a></p>',
    ]
    if not summaries:
        parts.append(
            '<p class="empty">No sessions yet. When you sign in, '
            "each device appears here, and you can end any "
            "session that is not yours.</p>")
    for s in summaries:
        where = (f" · from {escape_html_text(s.source_ip)}"
                 if s.source_ip else "")
        current = " · this session" if s.current else ""
        parts.append('<div class="session">')
        parts.append(
            f"<h2>{escape_html_text(s.device_label)}</h2>")
        parts.append(
            f"<p>Signed in {_stamp(s.created_at)} · "
            f"last active {_stamp(s.last_seen_at)}{where}</p>")
        parts.append(
            f"<p>Status: {escape_html_text(s.status)}{current}</p>")
        if s.live and not s.current:
            parts.append(
                f'<form method="post" action="{REVOKE_PATH}">'
                f'<input type="hidden" name="session_id" '
                f'value="{s.id}">'
                f'<input type="hidden" name="csrf_token" '
                f'value="{escape_html_attr(csrf_token)}">'
                '<button type="submit">Revoke this session</button>'
                "</form>")
        parts.append("</div>")
    if any(s.live and not s.current for s in summaries):
        parts.append(
            f'<form method="post" action="{REVOKE_ALL_PATH}">'
            f'<input type="hidden" name="csrf_token" '
            f'value="{escape_html_attr(csrf_token)}">'
            '<button type="submit">Revoke all other sessions</button>'
            "</form>")
    parts.append("</body></html>")
    return "\n".join(parts)
