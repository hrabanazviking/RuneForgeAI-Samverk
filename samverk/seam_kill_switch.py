"""Kill switch (S-372).

The seam disables cleanly from either side's admin —
the S-361 contract's sovereignty section, made real.
One call from a Samverk admin or a Samtal admin (the
side is named in the call and recorded) flips the one
switch every seam service already judges by
(``seam.samtal.enabled``, read through S-361's
seam_enabled): from that moment the panel, the unfurl,
the mentions bridge, the backup bundle and every other
seam door refuse with their standing seam_disabled
reason — cleanly, by their own guards, never by a
crash or a half-state.

Both applications continue whole: the switch touches
nothing else. Samverk's standalone doors (accounts,
repositories, notifications, Git) never read the seam
setting and are untouched; Samtal's side likewise keeps
its own halls and talk — only the crossing stops.

The disablement is audit-logged on both sides. On the
Samverk side it enters the standing audit chain as
``admin.settings.change`` (target seam) naming the
side and the actor. On the Samtal side the record is
kept in the seam ledger (settings table, key
``seam.kill_switch.samtal_log``) — the entry Samtal's
own log carries; no Samtal codebase stands on this
seat, so the ledger is the honest shared record of
that side's logging, never a claim about Samtal's
internals (the S-361 honesty pattern).

Re-enabling is the same door in reverse, likewise
admin-only and logged on both sides: a kill switch
that cannot be deliberately undone by an admin would
be a trap, not a switch. Guards: a site admin is
required (permission_denied — the seam has no other
admin concept on this side, and a Samtal-side call
arrives already judged by Samtal's admin, named by
its principal); the side must be one of the two
(side_invalid); disabling a seam that is already off
refuses (already_disabled) and enabling one that is
already on refuses (already_enabled), so the log
never records a change that did not happen. No
migration, no new taxonomy event: the switch is the
standing setting, the logs are the standing doors.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .seam_contract import seam_enabled

SIDES = ("samtal", "samverk")
SETTING_KEY = "seam.samtal.enabled"
LEDGER_KEY = "seam.kill_switch"
SAMTAL_LOG_KEY = "seam.kill_switch.samtal_log"


class SeamKillSwitchError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class SwitchRecord:
    enabled: bool
    side: str
    actor: str
    at: int
    samverk_audit_seq: int | None

    @property
    def headline(self) -> str:
        state = "enabled" if self.enabled else "disabled"
        return f"seam {state} from the {self.side} side by {self.actor}"


class SeamKillSwitchService:
    def __init__(self, conn, accounts: AccountStore,
                 *, settings: dict, audit: AuditLog | None = None,
                 time_fn=None):
        self._conn = conn
        self._accounts = accounts
        self._settings = settings
        self._audit = audit
        self._now = time_fn or (lambda: 0)

    def _judge(self, actor: User | None, side: object) -> str:
        if actor is None or self._accounts.get_by_id(actor.id) is None \
                or not actor.is_admin:
            raise SeamKillSwitchError(
                "permission_denied",
                "The kill switch is for either side's admin.")
        if side not in SIDES:
            raise SeamKillSwitchError(
                "side_invalid", "The seam has exactly two sides.")
        return str(side)

    def _flip(self, actor: User, side: str, *, enabled: bool) -> SwitchRecord:
        at = int(self._now())
        self._settings[SETTING_KEY] = enabled
        record = {"enabled": enabled, "side": side,
                  "actor": actor.username, "at": at}
        samtal_log = self._read(SAMTAL_LOG_KEY, [])
        samtal_log.append(dict(record))
        with self._conn:
            for key, value in ((LEDGER_KEY, record),
                               (SAMTAL_LOG_KEY, samtal_log),
                               (SETTING_KEY, enabled)):
                self._conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?)"
                    " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, json.dumps(value, sort_keys=True)))
        seq = None
        if self._audit is not None:
            seq = self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="admin.settings.change",
                target_kind="instance", target_id="seam",
                outcome="success",
                detail={"keys": [SETTING_KEY], "enabled": enabled,
                        "side": side, "via": "kill_switch"})
        return SwitchRecord(enabled=enabled, side=side,
                            actor=actor.username, at=at,
                            samverk_audit_seq=seq)

    def _read(self, key: str, default):
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return default if row is None else json.loads(row["value"])

    def disable(self, actor: User | None, *, side: object) -> SwitchRecord:
        """Disable the seam from either side's admin, logged both sides."""
        side = self._judge(actor, side)
        if not seam_enabled(self._settings):
            raise SeamKillSwitchError(
                "already_disabled", "The seam is already disabled.")
        return self._flip(actor, side, enabled=False)

    def enable(self, actor: User | None, *, side: object) -> SwitchRecord:
        """Re-enable the seam from either side's admin, logged both sides."""
        side = self._judge(actor, side)
        if seam_enabled(self._settings):
            raise SeamKillSwitchError(
                "already_enabled", "The seam is already enabled.")
        return self._flip(actor, side, enabled=True)

    def standing(self) -> dict | None:
        """The last switch record, or None if the switch never flipped."""
        return self._read(LEDGER_KEY, None)

    def samtal_log(self) -> list:
        """Samtal-side log entries for every flip, in order."""
        return self._read(SAMTAL_LOG_KEY, [])
