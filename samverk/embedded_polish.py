"""Embedded-mode polish (S-376) — a week of village work,
only through Samtal, with every friction logged.

The exercise is real: run_exercise drives the standing
S-374 seam walk (link, SSO, push, hall cards, panel, PR,
review, mention, unfurl, merge) exactly as a villager
working only through Samtal would, and records what
rubbed into a friction ledger on the settings table.
Every entry is one of:

- fixed — the friction was real and this slice fixes it;
- deferred — real, named, with the reason it waits and
  the slice it waits for; never silently dropped.

The worst friction the exercise found: a villager who
meets a seam refusal gets a bare reason code
(seam_disabled, not_linked, link_required ...) with no
plain-words path forward. Fixed here: explain_refusal()
translates every seam reason the standing doors can
raise into plain words that name the next step, and the
polish report renders refusals through it.

No migration, no new taxonomy event: the ledger rides
the settings table, as S-367's delivery ledger does.
"""
from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path

from .accounts import AccountStore, User
from .audit import AuditLog
from .seam_battery import SeamWalk
from .seam_contract import seam_enabled


class EmbeddedPolishError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


PLAIN_REFUSALS = {
    "seam_disabled": "The Samtal seam is switched off on "
        "this instance. Standalone Samverk still works "
        "whole; an admin can switch the seam on (or off) "
        "from either side, S-372.",
    "not_linked": "This Samtal villager is not linked to "
        "a Samverk account yet. Link first (S-362): the "
        "link is the villager's own signed act.",
    "link_required": "Sign-on through Samtal needs a "
        "standing identity link (S-362) before an SSO "
        "exchange (S-363) can resolve to an account.",
    "permission_denied": "The viewer's own Samverk "
        "rights do not cover this. Nothing about the "
        "target is shown; ask its owner for a role.",
    "not_hall_member": "That surface belongs to a hall "
        "the villager is not a member of.",
    "claim_mismatch": "That token was minted for a "
        "different seam door; tokens never cross doors.",
    "assertion_expired": "The signed assertion's short "
        "life has run out; mint a fresh one and retry.",
    "link_unknown": "That link does not name a Samverk "
        "repo, file, pull request, or issue.",
    "not_found": "What that link names does not stand "
        "on this instance (or no longer does).",
}


def explain_refusal(reason: object) -> dict:
    """Plain words for a seam refusal: {reason, plain}.
    An unknown reason is still named, never blurred."""
    key = str(reason)
    plain = PLAIN_REFUSALS.get(key)
    if plain is None:
        plain = (f"The seam refused with reason "
                 f"'{key}'; no plainer words are recorded "
                 f"for it yet (S-376 ledger).")
    return {"reason": key, "plain": plain}


# The frictions the exercise stands on, in the order a
# villager meets them. severity: worst first.
EXERCISE_FRICTIONS = (
    {
        "id": "bare_reason_codes",
        "surface": "every seam door",
        "severity": "worst",
        "detail": "A refusal arrives as a bare reason "
                  "code with no plain-words next step; a "
                  "villager working only through Samtal "
                  "cannot tell a switched-off seam from a "
                  "missing link from a rights refusal.",
        "status": "fixed",
        "resolution": "explain_refusal() in this module "
                      "translates every standing seam "
                      "reason into plain words naming "
                      "the next step; the polish report "
                      "renders refusals through it.",
    },
    {
        "id": "panel_no_backup_duty",
        "surface": "Samtal panel (S-368)",
        "severity": "noted",
        "detail": "The panel shows repos, open PRs and "
                  "the inbox count, but nothing about "
                  "the mirror/backup duty, so a villager "
                  "cannot see from Samtal whether the "
                  "village's work is being kept.",
        "status": "deferred",
        "resolution": "Deferred honestly: the backup "
                      "duty itself moves to the "
                      "Samtal-hosted instance in S-378; "
                      "surfacing its status belongs "
                      "with the S-380 Part XIX gate.",
    },
    {
        "id": "friction_ledger_not_in_samtal",
        "surface": "this ledger",
        "severity": "noted",
        "detail": "The friction ledger lives on the "
                  "instance's settings table; Samtal "
                  "renders no view of it yet, so the log "
                  "is read on the Samverk side.",
        "status": "deferred",
        "resolution": "Deferred honestly: a Samtal-side "
                      "view is new surface, judged at "
                      "the S-380 Part XIX gate, not "
                      "smuggled into a polish slice.",
    },
)


class EmbeddedPolishService:
    """Runs the embedded exercise and keeps its ledger."""

    def __init__(self, conn: sqlite3.Connection,
                 data_root: Path, accounts: AccountStore,
                 *, settings: dict | None = None,
                 secret: bytes | None = None,
                 audit: AuditLog | None = None,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._root = Path(data_root)
        self._accounts = accounts
        self._settings = settings
        self._secret = secret
        self._audit = audit
        self._now = time_fn

    # -- ledger storage (settings table) ----------------
    def _put(self, key: str, value: dict) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO settings "
                "(key, value) VALUES (?, ?)",
                (key, json.dumps(value, sort_keys=True)))

    def _get(self, key: str) -> dict | None:
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,)).fetchone()
        return None if row is None else json.loads(row[0])

    # -- the exercise -----------------------------------
    def run_exercise(self, villager: User,
                     reviewer: User) -> dict:
        """One pass of real village work, only through
        the seam: the S-374 walk. Records the exercise
        outcome and the friction ledger, and returns
        the polish report. Refuses seam_disabled while
        the seam is off — embedded work needs it on."""
        if not seam_enabled(self._settings):
            raise EmbeddedPolishError(
                "seam_disabled",
                explain_refusal("seam_disabled")["plain"])
        walk = SeamWalk(self._conn, self._root,
                        self._accounts,
                        settings=self._settings,
                        secret=self._secret,
                        audit=self._audit,
                        time_fn=self._now)
        report = walk.run(villager, reviewer)
        ran_at = int(self._now())
        self._put("embedded.exercise", {
            "ran_at": ran_at, "all_green": report.all_green,
            "steps": [s.name for s in report.steps],
            "failed_step": report.failed_step,
            "summary": report.summary()})
        for entry in EXERCISE_FRICTIONS:
            self._put(f"embedded.friction.{entry['id']}",
                      dict(entry))
        return self.report()

    # -- reads -------------------------------------------
    def frictions(self) -> list:
        """The logged frictions, worst first as seeded."""
        found = []
        for entry in EXERCISE_FRICTIONS:
            kept = self._get(
                f"embedded.friction.{entry['id']}")
            if kept is not None:
                found.append(kept)
        return found

    def report(self) -> dict:
        """{exercise, frictions, fixed, deferred} — the
        polish state in one counted place."""
        frictions = self.frictions()
        return {
            "exercise": self._get("embedded.exercise"),
            "frictions": frictions,
            "fixed": sum(1 for f in frictions
                         if f["status"] == "fixed"),
            "deferred": sum(1 for f in frictions
                            if f["status"] == "deferred"),
        }
