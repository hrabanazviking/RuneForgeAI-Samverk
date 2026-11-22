"""Maintenance mode (S-353).

Roadmap S-353: **Maintenance mode -- read-only banner
with reason and expected return; transports refuse
pushes with the message; admins retain access.**

When an operator must take the forge down for real work
(a migration, a disk swap, a restore), the honest shape
is not a silent outage or a half-working instance: it is
a stated, temporary read-only posture, in the operator's
own words, with the moment service is expected back.

- **The state lives in the founding settings table.**
  S-002's ``settings`` key/value table already carries
  instance facts (S-068 quotas, two-factor policy), so
  the mode needs no migration (schema 139 stands) and
  no new table. Keys: ``maintenance.enabled``,
  ``maintenance.reason``, ``maintenance.expected_return``,
  ``maintenance.set_by``, ``maintenance.set_at``.
- **Mode changes are admin-only and witnessed.** Only a
  site admin may enable or disable the mode; a non-admin
  attempt is refused ``admin_required`` and changes
  nothing. Every change appends the standing taxonomy
  event ``admin.settings.change`` (target ``maintenance``)
  -- no new event is claimed (taxonomy 138 stands).
  Enabling requires both a reason and an expected return,
  in plain words: a banner that cannot say why, or until
  when, is not the banner this slice promises.
- **Reads keep working; pushes refuse with the message.**
  While the mode is on, the pure ``decide_access``
  judgement allows every read and refuses every push by
  a non-admin, carrying the operator's message (reason +
  expected return). The refusal stands at every push
  door, in the S-334 shape: smart HTTP
  (``SmartHttpService._resolve``, the write leg, before
  any pack byte moves), the SSH door
  (``SshServeService.serve``, ``git-receive-pack`` only),
  and the S-089 pre-receive gate as a protection-stage
  plug-in (``gate_plugin``). Upload legs are untouched:
  maintenance is read-only, not unreadable.
- **Admins retain access.** An admin's pushes are not
  refused by this mode, and the admin doors -- enabling,
  disabling, and judging the mode -- answer exactly as
  before, so the operator who turned the mode on can
  always turn it off and can still repair by push.
- **The banner.** ``render_maintenance_banner`` is the
  fragment every page chrome can carry: while the mode
  is on it states, in words (never colour-only), that
  the instance is read-only for maintenance, the reason,
  and the expected return, escaped through S-010; while
  off it renders nothing. ``render_maintenance_page`` is
  the standalone page stating the same facts whole.
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .escaping import escape_html_text
from .receive_gate import GateVeto

__all__ = [
    "REASON_MAINTENANCE_MODE", "AccessDecision",
    "MaintenanceError", "MaintenanceMode", "MaintenanceState",
    "decide_access", "maintenance_state_from_rows",
    "push_refusal_message", "read_state", "render_maintenance_banner",
    "render_maintenance_page", "state_to_dict",
]

REASON_MAINTENANCE_MODE = "maintenance_mode"

_KEY_ON = "maintenance.enabled"
_KEY_REASON = "maintenance.reason"
_KEY_RETURN = "maintenance.expected_return"
_KEY_BY = "maintenance.set_by"
_KEY_AT = "maintenance.set_at"
_KEYS = (_KEY_ON, _KEY_REASON, _KEY_RETURN, _KEY_BY, _KEY_AT)


class MaintenanceError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class MaintenanceState:
    enabled: bool
    reason: str = ""
    expected_return: str = ""
    set_by: str | None = None
    set_at: int | None = None


OFF_STATE = MaintenanceState(enabled=False)


def maintenance_state_from_rows(rows: dict[str, str]) -> MaintenanceState:
    """Pure: build the state from settings rows. A missing
    or non-``1`` enabled flag is off -- the mode is opt-in
    and an unreadable flag never invents an outage."""
    if rows.get(_KEY_ON) != "1":
        return OFF_STATE
    at = rows.get(_KEY_AT)
    return MaintenanceState(
        enabled=True,
        reason=rows.get(_KEY_REASON, ""),
        expected_return=rows.get(_KEY_RETURN, ""),
        set_by=rows.get(_KEY_BY) or None,
        set_at=int(at) if at and at.isdigit() else None)


def read_state(conn: sqlite3.Connection) -> MaintenanceState:
    """The transports' fast read: the current mode straight
    from the settings table, no service built."""
    marks = ",".join("?" for _ in _KEYS)
    rows = {r[0]: r[1] for r in conn.execute(
        f"SELECT key, value FROM settings WHERE key IN ({marks})",
        _KEYS)}
    return maintenance_state_from_rows(rows)


def push_refusal_message(state: MaintenanceState) -> str:
    """The one refusal sentence, the same at every door:
    the mode, the operator's reason, and the expected
    return."""
    return (
        "Samverk is in maintenance mode and is read-only: "
        f"{state.reason} Expected return: {state.expected_return}. "
        "Pushes are refused until maintenance ends; reads still work.")


def banner_message(state: MaintenanceState) -> str:
    """The banner's words: same facts as the refusal,
    addressed to a reader instead of a pusher."""
    return (
        "Maintenance mode: this instance is read-only. "
        f"Reason: {state.reason} "
        f"Expected return: {state.expected_return}.")


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    reason: str           # "ok" | "maintenance_mode"
    message: str
    is_admin: bool
    write: bool


def decide_access(state: MaintenanceState, *, is_admin: bool,
                  write: bool) -> AccessDecision:
    """Pure: judge one access under the mode.

    Mode off: everything is judged by the standing
    permissions, so this judgement allows. Mode on:
    reads allow for everyone; pushes allow only for
    admins (admins retain access); every other push is
    refused carrying the operator's message."""
    if not state.enabled or not write:
        return AccessDecision(
            allowed=True, reason="ok", is_admin=is_admin, write=write,
            message=("Maintenance mode is off." if not state.enabled
                     else "Reads are not refused by maintenance mode."))
    if is_admin:
        return AccessDecision(
            allowed=True, reason="ok", is_admin=True, write=True,
            message="Admins retain access during maintenance mode.")
    return AccessDecision(
        allowed=False, reason=REASON_MAINTENANCE_MODE,
        is_admin=False, write=True,
        message=push_refusal_message(state))


def state_to_dict(state: MaintenanceState) -> dict:
    return {
        "enabled": state.enabled, "reason": state.reason,
        "expected_return": state.expected_return,
        "set_by": state.set_by, "set_at": state.set_at,
    }


class MaintenanceMode:
    """The mode's service: read the state, change it as
    an admin, judge access, and plug the push gate."""

    def __init__(self, conn: sqlite3.Connection,
                 accounts: AccountStore, audit=None,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._accounts = accounts
        self._audit = audit
        self._now = time_fn

    def current(self) -> MaintenanceState:
        return read_state(self._conn)

    # -- admin-only changes ----------------------------------
    def _require_admin(self, actor: User | None) -> User:
        if actor is None or not actor.is_admin:
            raise MaintenanceError(
                "admin_required",
                "Only a site admin may change maintenance mode.")
        return actor

    def _record(self, actor: User, enabled: bool,
                state: MaintenanceState) -> None:
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="admin.settings.change", target_kind="instance",
                target_id="maintenance", outcome="success",
                detail={"key": _KEY_ON,
                        "to": "1" if enabled else "0",
                        "reason": state.reason,
                        "expected_return": state.expected_return})

    def enable(self, actor: User | None, reason: object,
               expected_return: object) -> MaintenanceState:
        """Turn the mode on. Admin-only; both the reason
        and the expected return are required, in words."""
        admin = self._require_admin(actor)
        if not isinstance(reason, str) or not reason.strip():
            raise MaintenanceError(
                "reason_required",
                "Maintenance mode needs a reason, in plain words.")
        if not isinstance(expected_return, str) \
                or not expected_return.strip():
            raise MaintenanceError(
                "expected_return_required",
                "Maintenance mode needs an expected return, "
                "in plain words.")
        now = int(self._now())
        rows = [(_KEY_ON, "1"), (_KEY_REASON, reason.strip()),
                (_KEY_RETURN, expected_return.strip()),
                (_KEY_BY, admin.username), (_KEY_AT, str(now))]
        with self._conn:
            self._conn.executemany(
                "INSERT INTO settings (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                rows)
        state = self.current()
        self._record(admin, True, state)
        return state

    def disable(self, actor: User | None) -> MaintenanceState:
        """Turn the mode off. Admin-only; the operator's
        words stay recorded until the next enabling."""
        admin = self._require_admin(actor)
        before = self.current()
        with self._conn:
            self._conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, '0')"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (_KEY_ON,))
        state = self.current()
        self._record(admin, False, before)
        return state

    # -- judgements -------------------------------------------
    def judge(self, actor: User | None, *, write: bool) -> AccessDecision:
        return decide_access(
            self.current(),
            is_admin=bool(actor is not None and actor.is_admin),
            write=write)

    def gate_plugin(self, context) -> bool:
        """The S-089 protection-stage plug-in: refuse a
        push under maintenance with the operator's
        message, through the gate's own veto. The actor
        is the context's username; an admin username
        retains access, anyone else (including a deploy
        key, which is not an admin) is refused."""
        actor = None
        if context.actor:
            actor = self._accounts.get_by_username(context.actor)
        decision = self.judge(actor, write=True)
        if not decision.allowed:
            raise GateVeto(decision.message)
        return True


def render_maintenance_banner(state: MaintenanceState) -> str:
    """The banner fragment for any page: while the mode
    is on, the read-only fact, the reason and the
    expected return, in words; while off, nothing."""
    if not state.enabled:
        return ""
    return (
        '<div class="maintenance-banner" role="status">'
        f"<p>{escape_html_text(banner_message(state))}</p></div>")


def render_maintenance_page(state: MaintenanceState) -> str:
    """The standalone maintenance page: the mode's state
    stated whole. Every operator value escaped (S-010)."""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        "<title>Maintenance mode -- Samverk</title></head>",
        "<body>",
        "<h1>Maintenance mode</h1>",
    ]
    if state.enabled:
        parts.append(render_maintenance_banner(state))
        parts.append(
            "<p>Pushes are refused with the maintenance "
            "message until the mode is turned off. Reads "
            "keep working, and site admins retain access.</p>")
        if state.set_by:
            parts.append(
                f"<p>Set by: {escape_html_text(state.set_by)}</p>")
    else:
        parts.append(
            "<p>Maintenance mode is off. The instance is "
            "writable on the standing permissions.</p>")
    parts.append("</body></html>")
    return "\n".join(parts)
