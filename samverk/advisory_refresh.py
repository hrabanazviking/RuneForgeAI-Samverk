"""Advisory refresh (S-300).

Roadmap S-300: Advisory refresh -- the snapshot
updates by operator action or scheduled fetch
where the instance has network; offline instances
show staleness honestly.

S-298 bundled a dated snapshot of public
vulnerability data and ruled that its age is
displayed wherever alerts are shown; S-299 joined
that snapshot to the dependency graph. A bundled
snapshot only gets older. This slice is the road
by which it is replaced -- and the honesty law
that governs the instances where it cannot be:

- **One refresh path, two triggers.** An operator
  action and the scheduled fetch land through the
  same ``AdvisoryRefreshStore.refresh`` -- the
  same validation, the same replacement, the same
  provenance record. ``refresh_by_operator`` and
  ``refresh_scheduled`` are thin named doors onto
  it, differing only in the trigger and actor they
  record. There is no second, weaker road for the
  scheduler to take.
- **The fetch is a seam, never a call made from
  inside the judgement.** This module ships no
  network call of its own at load, at store
  construction, or anywhere but inside a fetcher
  an operator has wired: a *fetcher* is a callable
  handed to a refresh -- ``fetcher()`` answering
  the candidate snapshot (text, bytes or a decoded
  mapping) -- or the candidate is handed in
  directly as ``raw``. ``make_url_fetcher`` builds
  a fetcher over an operator-supplied URL with the
  standard library, its import and its request
  both lazy inside the call. With no fetcher and
  nothing handed in -- the offline instance, the
  ordinary case -- a refresh answers honestly
  ``fetch_unavailable`` and changes nothing.
- **A candidate is validated with S-298's own
  strictness before it replaces anything.** Every
  candidate passes through ``parse_snapshot``
  itself, against the refresh's clock: a malformed,
  undated, future-dated, empty or otherwise broken
  snapshot is refused *by that validator's own
  reason name* (``snapshot_malformed``,
  ``snapshot_date_in_future``, ...), the standing
  snapshot stands exactly as it stood, and the
  refusal is what the provenance record carries.
  A candidate dated *older* than the standing
  snapshot is refused ``snapshot_older_than_standing``:
  a refresh may not quietly move the instance's
  vulnerability data backwards and call the older
  data fresh. A candidate dated the same day as
  the standing snapshot is recorded ``unchanged``
  and replaces nothing.
- **Replacement is atomic, and the standing
  snapshot survives restarts.** A successful
  refresh writes migration 122's singleton
  ``advisory_snapshot_state`` row (the canonical
  snapshot text, its date, source and count, when
  it landed, by which trigger and actor) and its
  provenance row in one transaction, so the
  instance never stands half-refreshed. Where no
  refresh has ever landed, the standing snapshot
  is S-298's bundled one, read through
  ``AdvisoryStore.bundled`` exactly as before --
  S-299's alerts read the standing snapshot
  through ``current_store`` and lose nothing.
- **Offline instances show staleness honestly.**
  Nothing in this module touches the standing
  snapshot's date, so S-298's age law runs on
  reality: past ``STALE_AFTER_DAYS`` the standing
  snapshot's freshness is ``stale`` and every
  surface says so, however many refreshes have
  been attempted and failed. A failed or refused
  refresh is recorded as one; it never dresses
  the snapshot up as fresh, and the refresh page
  shows the standing age beside the attempt
  history.
- **Every attempt stands on the provenance
  record.** Migration 122's ``advisory_refreshes``
  carries one row per attempt, landed or not:
  when (the store's clock), by whom (the actor
  the trigger names -- an operator's own name, or
  the scheduler's standing label), by what
  trigger (``operator`` / ``scheduled``), the
  standing date before the attempt, the
  candidate's date where one was validated (else
  the standing date -- no date is invented for a
  snapshot that never parsed), the result
  (``refreshed`` / ``unchanged`` / ``refused`` /
  ``failed``), the named reason where the attempt
  did not land, and a plain detail sentence.
- **Unwitnessed in the audit taxonomy -- said
  plainly.** No new taxonomy event: 134 stand
  (33 auth / 88 repo / 13 admin), and the battery
  proves the audit log does not move across a
  landed refresh, a refusal and a failure. A
  refresh changes no code, lands no push and lets
  nothing in; it is an operator act over instance
  data whose witness is its own provenance record,
  complete and in-transaction, as S-296's checks
  stand on theirs.

Storage is migration 122's ``advisory_snapshot_state``
and ``advisory_refreshes`` tables (schema 121 ->
122 on the banked line; the suite's standing
schema pins moved in-slice, as prior slices did).
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone

from .advisory_data import (
    AdvisorySnapshot, AdvisoryStore, SnapshotInfo, parse_snapshot,
    render_advisory_banner)
from .escaping import escape_html_text
from .repositories import RepositoryError

__all__ = [
    "ACTOR_REQUIRED", "FETCH_FAILED", "FETCH_UNAVAILABLE",
    "RESULT_FAILED", "RESULT_REFRESHED", "RESULT_REFUSED",
    "RESULT_UNCHANGED", "SCHEDULED_ACTOR",
    "SNAPSHOT_OLDER_THAN_STANDING", "TRIGGER_INVALID",
    "TRIGGER_OPERATOR", "TRIGGER_SCHEDULED", "TRIGGERS",
    "AdvisoryRefreshError", "AdvisoryRefreshStore",
    "RefreshRecord", "judge_refresh", "make_url_fetcher",
    "render_refresh_history", "render_refresh_page",
]

#: The two triggers a refresh may stand under.
#: Both land through the one refresh path.
TRIGGER_OPERATOR = "operator"
TRIGGER_SCHEDULED = "scheduled"
TRIGGERS = frozenset({TRIGGER_OPERATOR, TRIGGER_SCHEDULED})

#: The actor a scheduled refresh records when the
#: caller names none: a label, not an account.
SCHEDULED_ACTOR = "samverk-scheduler"

#: The results an attempt may stand under.
RESULT_REFRESHED = "refreshed"
RESULT_UNCHANGED = "unchanged"
RESULT_REFUSED = "refused"
RESULT_FAILED = "failed"

FETCH_UNAVAILABLE = "fetch_unavailable"
FETCH_FAILED = "fetch_failed"
SNAPSHOT_OLDER_THAN_STANDING = "snapshot_older_than_standing"
TRIGGER_INVALID = "trigger_invalid"
ACTOR_REQUIRED = "actor_required"

_MAX_DETAIL_CHARS = 500


class AdvisoryRefreshError(RepositoryError):
    """An advisory-refresh error: a RepositoryError
    carrying `.reason`, in the house shape. Raised
    only for caller faults (an unknown trigger, a
    missing actor) -- a refresh that merely fails
    or is refused is a recorded outcome, returned,
    never raised, so a scheduler survives it."""


def _fail(reason: str, message: str) -> AdvisoryRefreshError:
    return AdvisoryRefreshError(reason, message)


def _today_of(now: object, time_fn) -> date:
    """The refresh's day from its `now` or its
    clock, for comparing snapshot dates."""
    if now is None:
        return datetime.fromtimestamp(
            time_fn(), timezone.utc).date()
    if isinstance(now, datetime):
        return now.date()
    if isinstance(now, date):
        return now
    if isinstance(now, (int, float)):
        return datetime.fromtimestamp(now, timezone.utc).date()
    return date.fromisoformat(str(now))


def judge_refresh(standing_date: date,
                  candidate_date: date) -> tuple:
    """The pure replacement judgement: a candidate
    dated after the standing snapshot *replaces*
    it; the same day is *unchanged*; an older
    candidate is *backwards* and refused -- a
    refresh never moves vulnerability data
    backwards and calls it fresh. Returns
    (action, reason): reason is "" unless the
    action is "backwards". Pure: writes nothing."""
    if candidate_date > standing_date:
        return ("replace", "")
    if candidate_date == standing_date:
        return ("unchanged", "")
    return ("backwards", SNAPSHOT_OLDER_THAN_STANDING)


@dataclass(frozen=True)
class RefreshRecord:
    """One refresh attempt as the provenance
    record stands it: when, by whom, by what
    trigger, the standing date before the attempt,
    the candidate's date where one was validated
    (else the standing date), the result, the
    named reason where it did not land, and a
    plain detail sentence."""
    id: int | None
    trigger: str
    actor: str
    old_snapshot_date: str
    new_snapshot_date: str
    result: str
    reason: str
    detail: str
    advisory_count: int | None
    created_at: int

    @property
    def landed(self) -> bool:
        return self.result == RESULT_REFRESHED

    def words(self) -> str:
        base = (self.trigger + " refresh by " + self.actor
                + ": snapshot " + self.old_snapshot_date
                + " -> " + self.new_snapshot_date
                + " -- " + self.result)
        if self.reason:
            base += " (" + self.reason + ")"
        return base

    def to_dict(self) -> dict:
        return {
            "id": self.id, "trigger": self.trigger,
            "actor": self.actor,
            "old_snapshot_date": self.old_snapshot_date,
            "new_snapshot_date": self.new_snapshot_date,
            "result": self.result, "reason": self.reason,
            "detail": self.detail,
            "advisory_count": self.advisory_count,
            "created_at": self.created_at,
        }


def _snapshot_text(snapshot: AdvisorySnapshot) -> str:
    """The canonical stored text of a validated
    snapshot: exactly what parse_snapshot reads
    back, field for field."""
    return json.dumps({
        "snapshot_format": 1,
        "source": snapshot.source,
        "snapshot_date": snapshot.snapshot_date.isoformat(),
        "advisories": [{
            "id": a.id, "ecosystem": a.ecosystem,
            "package": a.package, "severity": a.severity,
            "affected": a.affected,
            "fixed_version": a.fixed_version,
            "summary": a.summary, "published": a.published,
            "references": list(a.references),
        } for a in snapshot.advisories],
    }, sort_keys=True)


def make_url_fetcher(url: str, *, timeout: float = 30.0):
    """A fetcher over an operator-supplied URL.
    Lazy by construction: building it imports
    nothing and requests nothing; the standard
    library's urllib is imported and called only
    when the fetcher itself is called, inside a
    refresh an operator or the scheduler chose to
    run. This is the scheduled-fetch road where
    the instance has network; no URL is built in,
    because which mirror an instance trusts is the
    operator's word, not this module's."""
    def fetch():
        import urllib.request
        request = urllib.request.Request(
            str(url), headers={"Accept": "application/json"})
        with urllib.request.urlopen(
                request, timeout=timeout) as response:
            return response.read()
    return fetch


def _row_to_record(row) -> RefreshRecord:
    return RefreshRecord(
        id=int(row["id"]), trigger=row["trigger"],
        actor=row["actor"],
        old_snapshot_date=row["old_snapshot_date"],
        new_snapshot_date=row["new_snapshot_date"],
        result=row["result"], reason=row["reason"],
        detail=row["detail"],
        advisory_count=(int(row["advisory_count"])
                        if row["advisory_count"] is not None
                        else None),
        created_at=int(row["created_at"]))


class AdvisoryRefreshStore:
    """The standing advisory snapshot and its
    refresh road. The store holds the instance's
    database connection; where migration 122's
    state row stands, that snapshot is the
    standing one; where none stands, S-298's
    bundled snapshot is. Refreshing replaces the
    standing snapshot only through parse_snapshot's
    own validation, atomically with its provenance
    row."""

    def __init__(self, conn: sqlite3.Connection,
                 *, time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._now = time_fn

    # -- the standing snapshot ----------------------

    def _state_row(self):
        return self._conn.execute(
            "SELECT * FROM advisory_snapshot_state"
            " WHERE id = 1").fetchone()

    def standing_snapshot(self,
                          now: object = None) -> AdvisorySnapshot:
        """The snapshot the instance stands on: the
        last landed refresh's, or the bundled one
        where no refresh has ever landed."""
        row = self._state_row()
        if row is None:
            return AdvisoryStore.bundled(now=now).snapshot
        return parse_snapshot(row["snapshot_text"], now=now)

    def current_store(self, now: object = None) -> AdvisoryStore:
        """An AdvisoryStore over the standing
        snapshot -- the seam S-299's alerts and any
        alert surface read through, so a landed
        refresh is what the alerts join against."""
        return AdvisoryStore(self.standing_snapshot(now=now))

    def snapshot_info(self, now: object = None) -> SnapshotInfo:
        """Date, age and freshness of the standing
        snapshot, computed from its real date:
        an old standing snapshot reads stale here
        however the refresh history stands."""
        return self.current_store(now=now).snapshot_info(now)

    # -- the one refresh path -------------------------

    def refresh(self, *, trigger: str, actor: str,
                raw: object = None,
                fetcher: Callable | None = None,
                now: object = None) -> RefreshRecord:
        """Run one refresh attempt and record it.
        Caller faults (an unknown trigger, a missing
        actor) raise by name before anything is
        recorded; every other outcome -- landed,
        unchanged, refused, failed -- is recorded
        on advisory_refreshes and returned, so an
        operator surface and a scheduler both read
        the same honest record."""
        if trigger not in TRIGGERS:
            raise _fail(
                TRIGGER_INVALID,
                "unknown refresh trigger: " + repr(trigger)
                + "; a refresh is an operator action or a"
                " scheduled fetch")
        if not isinstance(actor, str) or not actor.strip():
            raise _fail(
                ACTOR_REQUIRED,
                "a refresh records who or what ran it; an"
                " attempt with no actor is an unaccountable"
                " act, and this slice records none")
        actor = actor.strip()
        standing = self.standing_snapshot(now=now)
        old_date = standing.snapshot_date
        created = int(self._now())

        def record(result, reason, detail, new_date,
                   count):
            rec = RefreshRecord(
                id=None, trigger=trigger, actor=actor,
                old_snapshot_date=old_date.isoformat(),
                new_snapshot_date=new_date.isoformat(),
                result=result, reason=reason, detail=detail,
                advisory_count=count, created_at=created)
            with self._conn:
                cur = self._conn.execute(
                    "INSERT INTO advisory_refreshes ("
                    " trigger, actor, old_snapshot_date,"
                    " new_snapshot_date, result, reason,"
                    " detail, advisory_count, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (rec.trigger, rec.actor,
                     rec.old_snapshot_date,
                     rec.new_snapshot_date, rec.result,
                     rec.reason, rec.detail,
                     rec.advisory_count, rec.created_at))
            return RefreshRecord(
                id=int(cur.lastrowid), trigger=rec.trigger,
                actor=rec.actor,
                old_snapshot_date=rec.old_snapshot_date,
                new_snapshot_date=rec.new_snapshot_date,
                result=rec.result, reason=rec.reason,
                detail=rec.detail,
                advisory_count=rec.advisory_count,
                created_at=rec.created_at)

        # Obtain the candidate: handed in, fetched
        # through the seam, or honestly unavailable.
        candidate_raw = raw
        if candidate_raw is None and fetcher is not None:
            try:
                candidate_raw = fetcher()
            except Exception as exc:  # a failed fetch is an outcome
                return record(
                    RESULT_FAILED, FETCH_FAILED,
                    ("the fetch failed: "
                     + str(exc))[:_MAX_DETAIL_CHARS],
                    old_date, len(standing.advisories))
            if candidate_raw is None:
                return record(
                    RESULT_FAILED, FETCH_UNAVAILABLE,
                    "the fetcher returned no snapshot; the"
                    " standing snapshot stands",
                    old_date, len(standing.advisories))
        if candidate_raw is None:
            return record(
                RESULT_FAILED, FETCH_UNAVAILABLE,
                "no snapshot was handed in and no fetcher"
                " is configured; this instance has no"
                " network road for a refresh, so the"
                " standing snapshot stands and its age"
                " is shown as it is",
                old_date, len(standing.advisories))

        # Validate with S-298's own strictness.
        from .advisory_data import AdvisoryError
        try:
            candidate = parse_snapshot(candidate_raw, now=now)
        except AdvisoryError as exc:
            return record(
                RESULT_REFUSED, exc.reason,
                str(exc)[:_MAX_DETAIL_CHARS],
                old_date, len(standing.advisories))

        action, reason = judge_refresh(
            old_date, candidate.snapshot_date)
        if action == "backwards":
            return record(
                RESULT_REFUSED, reason,
                "candidate snapshot dated "
                + candidate.snapshot_date.isoformat()
                + " is older than the standing snapshot"
                " dated " + old_date.isoformat()
                + "; a refresh never moves vulnerability"
                " data backwards",
                candidate.snapshot_date,
                len(candidate.advisories))
        if action == "unchanged":
            return record(
                RESULT_UNCHANGED, "",
                "the fetched snapshot is dated the same"
                " day as the standing snapshot; nothing"
                " to replace",
                candidate.snapshot_date,
                len(candidate.advisories))

        # Land it: state and provenance in one
        # transaction, so the instance never stands
        # half-refreshed.
        text = _snapshot_text(candidate)
        rec = RefreshRecord(
            id=None, trigger=trigger, actor=actor,
            old_snapshot_date=old_date.isoformat(),
            new_snapshot_date=candidate.snapshot_date.isoformat(),
            result=RESULT_REFRESHED, reason="",
            detail=("snapshot refreshed from "
                    + old_date.isoformat() + " to "
                    + candidate.snapshot_date.isoformat()
                    + " (" + str(len(candidate.advisories))
                    + " advisories)"),
            advisory_count=len(candidate.advisories),
            created_at=created)
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO"
                " advisory_snapshot_state ("
                " id, snapshot_text, snapshot_date, source,"
                " advisory_count, refreshed_at, trigger,"
                " actor) VALUES (1, ?, ?, ?, ?, ?, ?, ?)",
                (text, candidate.snapshot_date.isoformat(),
                 candidate.source, len(candidate.advisories),
                 created, trigger, actor))
            cur = self._conn.execute(
                "INSERT INTO advisory_refreshes ("
                " trigger, actor, old_snapshot_date,"
                " new_snapshot_date, result, reason,"
                " detail, advisory_count, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (rec.trigger, rec.actor,
                 rec.old_snapshot_date,
                 rec.new_snapshot_date, rec.result,
                 rec.reason, rec.detail,
                 rec.advisory_count, rec.created_at))
        return RefreshRecord(
            id=int(cur.lastrowid), trigger=rec.trigger,
            actor=rec.actor,
            old_snapshot_date=rec.old_snapshot_date,
            new_snapshot_date=rec.new_snapshot_date,
            result=rec.result, reason=rec.reason,
            detail=rec.detail,
            advisory_count=rec.advisory_count,
            created_at=rec.created_at)

    def refresh_by_operator(self, actor: str, *,
                            raw: object = None,
                            fetcher: Callable | None = None,
                            now: object = None) -> RefreshRecord:
        """The operator door onto the one refresh
        path: trigger `operator`, the operator's own
        name on the record."""
        return self.refresh(trigger=TRIGGER_OPERATOR,
                            actor=actor, raw=raw,
                            fetcher=fetcher, now=now)

    def refresh_scheduled(self, *,
                          fetcher: Callable | None = None,
                          raw: object = None,
                          actor: str = SCHEDULED_ACTOR,
                          now: object = None) -> RefreshRecord:
        """The scheduled door onto the same path:
        trigger `scheduled`, the scheduler's standing
        label on the record unless the caller names
        its fetcher's own. No fetcher configured is
        the offline instance: the attempt is recorded
        failed / fetch_unavailable and the standing
        snapshot's staleness stands as it is."""
        return self.refresh(trigger=TRIGGER_SCHEDULED,
                            actor=actor, raw=raw,
                            fetcher=fetcher, now=now)

    # -- the provenance record -------------------------

    def history(self, limit: int | None = None) -> tuple:
        """Every recorded attempt, oldest first --
        landed, unchanged, refused and failed alike,
        unedited."""
        sql = ("SELECT * FROM advisory_refreshes"
               " ORDER BY id")
        params: tuple = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (int(limit),)
        rows = self._conn.execute(sql, params).fetchall()
        return tuple(_row_to_record(r) for r in rows)

    def latest(self) -> RefreshRecord | None:
        row = self._conn.execute(
            "SELECT * FROM advisory_refreshes"
            " ORDER BY id DESC LIMIT 1").fetchone()
        return _row_to_record(row) if row is not None else None


# --- render surfaces (S-010 escaped) ----------------
#
# The refresh page carries S-298's banner first --
# the standing snapshot's real date and age -- and
# the attempt history under it. A failed history
# never moves the banner's words.


def render_refresh_history(records) -> str:
    rows = ""
    for rec in records:
        rows += ("<li>" + escape_html_text(rec.words())
                 + " -- " + escape_html_text(rec.detail)
                 + "</li>")
    if not rows:
        rows = "<li>No refresh has been attempted.</li>"
    return "<ul>" + rows + "</ul>"


def render_refresh_page(store: AdvisoryRefreshStore,
                        now: object = None,
                        title: str = "Advisory refresh") -> str:
    """The refresh face: the standing snapshot's
    date and age first (the banner every alert
    surface carries), then the provenance of every
    attempt -- so an instance whose refreshes keep
    failing shows its stale snapshot *and* its
    failed attempts, in the open."""
    info = store.snapshot_info(now)
    body = ("<h1>" + escape_html_text(title) + "</h1>"
            + render_advisory_banner(info)
            + "<p>Standing snapshot dated "
            + escape_html_text(
                info.snapshot_date.isoformat()
                if info.snapshot_date else "unknown")
            + ".</p>"
            + render_refresh_history(store.history()))
    return ("<!DOCTYPE html><html><head><title>"
            + escape_html_text(title)
            + "</title></head><body>" + body + "</body></html>")
