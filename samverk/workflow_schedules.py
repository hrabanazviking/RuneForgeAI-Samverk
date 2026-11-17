"""Scheduled workflows -- the schedule clock's
law (S-326).

Scheduled workflows -- cron on the default
branch only; drift and missed-run behaviour
stated honestly.

S-313 decided the format law -- schedules read
the default branch only -- and S-314 built the
cron law itself: five fields, validated, with
`next_cron_after` answering the next firing or
honestly answering None. What neither slice
built is the clock-keeping judgement: which
branch's schedules count at all, what a
scheduler tick owes the firings that came due
since the last tick, and what it must say --
not hide -- about the firings it was late for
or missed outright. This slice is that
judgement:

- **The default branch only, judged, not
  assumed.** `decide_schedule_source` answers
  whether one branch's workflow files may
  source scheduled runs at all: the branch
  whose name equals the repository's default
  branch, and no other. `collect_schedules`
  applies that answer to a branch's workflow
  definitions whole: on the default branch it
  gathers every schedule entry every workflow
  declares; on any other branch it gathers
  nothing, and the workflows there that did
  declare schedules are named on the
  collection as `ignored_workflows` -- a
  schedule written on a feature branch is not
  a silent no-op the author cannot discover;
  it is a stated non-source, and it starts
  counting only when it lands on the default
  branch, exactly as S-313's invariant says.
  A workflow that declares no schedule trigger
  contributes no entry on any branch.
- **A tick owes the window (last_tick, now].**
  The scheduler that keeps the clock wakes
  when it wakes; this slice judges one wake
  against the window since the last one.
  `firings_between` enumerates one cron's
  firing times in that window through S-314's
  own `next_cron_after` -- the start excluded,
  the end included, so two honest ticks never
  double-fire a boundary and never skip it.
  A window so wide it holds more than
  `MAX_WINDOW_FIRINGS` firings of one cron is
  refused whole (`schedule_window_too_large`)
  rather than judged from a truncated list:
  the caller resets its last tick and says so.
- **Drift is stated, never smoothed over.** A
  scheduled run never fires early: a firing
  after `now` is not due, whatever the
  scheduler hopes. A firing that is due fires
  at the tick that finds it, which is at or
  after its cron time -- late by exactly
  `drift_seconds`, the whole distance between
  the due time and the tick, downtime
  included. The judgement carries the due
  time, the tick time and the drift as data,
  so the run page (S-327) can say "due at
  02:00, fired at 05:00, three hours late"
  instead of pretending the run ran at 02:00.
- **Missed runs are skipped, not replayed --
  and never hidden.** When more than one
  firing of one cron came due in the window
  (the forge was down, the scheduler stalled),
  at most one run fires at the tick: the one
  for the latest due firing. Every earlier
  due firing is `missed`: counted, named by
  its due time on the judgement, and never
  queued for a catch-up burst -- a forge that
  was down for a week does not fire seven
  nightlies in a minute and call the week
  kept. The schedule then resumes from the
  tick: `next_due` is the first firing after
  `now`, never a rewound one. A cron that can
  never fire (February 31) is stated as
  `never_fires` with `next_due` None, in
  S-314's honest None, not as an error and
  not as a run that is merely late.
- **A pure judgement, like S-314, S-320 and
  S-325.** This module holds no store, writes
  no row, audits nothing and keeps no clock of
  its own: it judges the window it is handed,
  and the stamps it judges are carried on
  every judgement it answers, so a scheduler
  that misstates its last tick misstates it
  on the record the run page reads. No
  migration (schema stays 131), no taxonomy
  event (135 stand: 33 auth / 89 repo / 13
  admin). No workflow-schedule table, column
  or audit event exists; the audit below
  proves that absence against the live
  instance, and the battery plants a
  schedule-shaped table to prove the audit
  would catch one arriving ahead of its
  slice. The daemon that wakes and calls this
  judgement, and the dispatch it hands the
  firing to (S-316's poll seam, judged for
  fork safety by S-320 -- a schedule is never
  a fork run, reading the base repository's
  default branch), are operations around this
  law, not this slice.

Honest limits, stated plainly: cron fields are
judged exactly as S-314 judges them -- the
wall-clock fields of the moments handed, with
no timezone conversion of this slice's own; an
instance that wants schedules in a named zone
hands moments in that zone. The window is
only as honest as the last tick handed: this
slice cannot detect a scheduler that never
woke and never asked, only state, on every
judgement, the window it was given.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from . import taxonomy
from .escaping import escape_html_text
from .workflow_triggers import (
    CronSchedule, TriggerSet, next_cron_after)

__all__ = [
    "MAX_WINDOW_FIRINGS", "DueJudgement",
    "ScheduleAudit", "ScheduleCollection",
    "ScheduleError", "ScheduleTick",
    "ScheduledEntry", "SourceDecision",
    "audit_workflow_schedules",
    "collect_schedules", "decide_schedule_source",
    "firings_between", "judge_due", "judge_tick",
    "render_workflow_schedules_page",
    "scheduled_entries", "tick_to_dict",
]

#: The most firings of one cron one window may
#: hold before the window is refused whole: a
#: per-minute cron over a week is 10080, so a
#: scheduler ticking at any sane cadence never
#: meets this; a window past it is a scheduler
#: that slept far too long to judge honestly
#: from a list.
MAX_WINDOW_FIRINGS = 10_000

_SURFACE_WORDS = (
    "workflow_schedule", "scheduled_workflow",
    "schedule_tick", "missed_run")


class ScheduleError(ValueError):
    """One refused schedule call: a
    machine-branchable reason with its human
    detail, in the house shape."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def _branch(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ScheduleError(
            "schedule_branch_invalid",
            f"schedule_branch_invalid -- {where} "
            "names a branch. Nothing was judged.")
    return value.strip()


def _moment(value: object, where: str) -> datetime:
    if not isinstance(value, datetime):
        raise ScheduleError(
            "schedule_time_invalid",
            f"schedule_time_invalid -- {where} is "
            "a date and time. Nothing was judged.")
    return value


# ------------------------------------------------------------------
# The source law: the default branch only.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class SourceDecision:
    """Whether one branch's workflow files may
    source scheduled runs: only the default
    branch may, and the answer names both
    branches it judged."""
    branch: str
    default_branch: str
    is_default: bool
    reason: str

    @property
    def words(self) -> str:
        if self.is_default:
            return (
                f"{self.branch} is the default "
                "branch -- its schedules count.")
        return (
            f"{self.branch} is not the default "
            f"branch ({self.default_branch}) -- "
            "its schedules do not count.")


def decide_schedule_source(branch: object,
                           default_branch: object
                           ) -> SourceDecision:
    """Judge one branch as a schedule source:
    the default branch, and only the default
    branch, sources scheduled runs (S-313's
    invariant, judged here). Pure."""
    branch = _branch(branch, "a schedule source")
    default = _branch(
        default_branch, "the default branch")
    is_default = branch == default
    return SourceDecision(
        branch=branch, default_branch=default,
        is_default=is_default,
        reason=("default_branch" if is_default
                else "not_default_branch"))


@dataclass(frozen=True)
class ScheduledEntry:
    """One cron one workflow declares: the
    workflow's name and S-314's validated
    schedule for it. One workflow with two
    cron entries is two entries."""
    workflow: str
    cron: CronSchedule

    @property
    def expression(self) -> str:
        return self.cron.expression


def scheduled_entries(workflow: object,
                      triggers: object) -> tuple:
    """The schedule entries one workflow's
    trigger set declares: one per cron on its
    schedule trigger, in declaration order;
    empty when the workflow declares no
    schedule trigger. The trigger set is
    S-314's own parsed shape. Pure."""
    if not isinstance(workflow, str) or not workflow.strip():
        raise ScheduleError(
            "schedule_workflow_invalid",
            "schedule_workflow_invalid -- a "
            "scheduled workflow names itself. "
            "Nothing was judged.")
    if not isinstance(triggers, TriggerSet):
        raise ScheduleError(
            "schedule_triggers_invalid",
            "schedule_triggers_invalid -- a "
            "workflow's triggers are S-314's "
            "parsed trigger set. Nothing was "
            "judged.")
    spec = triggers.for_event("schedule")
    if spec is None:
        return ()
    return tuple(
        ScheduledEntry(workflow.strip(), cron)
        for cron in spec.crons)


@dataclass(frozen=True)
class ScheduleCollection:
    """One branch's schedules, judged whole:
    the source decision, the entries that count
    (the default branch's only), the workflows
    handed, and -- on any other branch -- the
    handed workflows that declared schedules
    and are ignored for it, named."""
    source: SourceDecision
    entries: tuple
    declared_workflows: tuple
    ignored_workflows: tuple

    @property
    def words(self) -> str:
        if not self.source.is_default:
            ignored = (
                ", ".join(self.ignored_workflows)
                or "none")
            return (
                f"{self.source.words} Scheduled "
                f"workflows ignored here: {ignored}.")
        return (
            f"{self.source.words} "
            f"{len(self.entries)} schedule "
            f"entr{'y' if len(self.entries) == 1 else 'ies'} "
            f"from {len(self.declared_workflows)} "
            "workflow(s) count.")


def collect_schedules(definitions: object,
                      branch: object,
                      default_branch: object
                      ) -> ScheduleCollection:
    """Collect the schedules that count from
    one branch's workflow definitions:
    `definitions` is (workflow name, S-314
    trigger set) pairs in file order. Only the
    default branch's entries count; on any
    other branch the collection is empty and
    the schedule-declaring workflows are named
    as ignored. Pure."""
    source = decide_schedule_source(branch, default_branch)
    if isinstance(definitions, (str, bytes)) \
            or not isinstance(definitions, (list, tuple)):
        raise ScheduleError(
            "schedule_definitions_invalid",
            "schedule_definitions_invalid -- a "
            "branch's workflows are a list of "
            "(name, trigger set) pairs. Nothing "
            "was judged.")
    entries: list = []
    declared: list = []
    ignored: list = []
    for pair in definitions:
        if not isinstance(pair, (list, tuple)) \
                or len(pair) != 2:
            raise ScheduleError(
                "schedule_definitions_invalid",
                "schedule_definitions_invalid -- "
                "every workflow is a (name, "
                "trigger set) pair. Nothing was "
                "judged.")
        name, triggers = pair
        found = scheduled_entries(name, triggers)
        declared.append(str(name).strip())
        if source.is_default:
            entries.extend(found)
        elif found:
            ignored.append(str(name).strip())
    return ScheduleCollection(
        source=source, entries=tuple(entries),
        declared_workflows=tuple(declared),
        ignored_workflows=tuple(ignored))


# ------------------------------------------------------------------
# The tick judgement: due, drift and missed.
# ------------------------------------------------------------------

def firings_between(cron: CronSchedule,
                    start: object,
                    end: object) -> tuple:
    """One cron's firing times in the window
    (start, end]: the start excluded, the end
    included, in firing order, through S-314's
    `next_cron_after`. An empty or backwards
    window is refused; a window holding more
    than MAX_WINDOW_FIRINGS firings is refused
    whole rather than truncated. Pure."""
    if not isinstance(cron, CronSchedule):
        raise ScheduleError(
            "schedule_cron_invalid",
            "schedule_cron_invalid -- firings are "
            "judged for one of S-314's validated "
            "cron schedules. Nothing was judged.")
    start = _moment(start, "the window's start")
    end = _moment(end, "the window's end")
    if end <= start:
        raise ScheduleError(
            "schedule_window_invalid",
            "schedule_window_invalid -- a tick "
            "window runs from the last tick to "
            "now, in that order. Nothing was "
            "judged.")
    found: list = []
    cursor = start
    while True:
        nxt = next_cron_after(cron, cursor)
        if nxt is None or nxt > end:
            return tuple(found)
        found.append(nxt)
        if len(found) > MAX_WINDOW_FIRINGS:
            raise ScheduleError(
                "schedule_window_too_large",
                "schedule_window_too_large -- the "
                "window holds more firings of one "
                f"cron than the {MAX_WINDOW_FIRINGS} "
                "that can be judged honestly; "
                "reset the last tick and say so. "
                "Nothing was judged.")
        cursor = nxt


@dataclass(frozen=True)
class DueJudgement:
    """One schedule entry judged at one tick:
    every firing due in the window, the one
    that fires (the latest due, or none), the
    earlier ones missed and never replayed,
    the drift the firing carries, and the next
    firing after the tick. The window's own
    stamps ride along: the record states the
    window it was judged over."""
    workflow: str
    expression: str
    window_start: datetime
    window_end: datetime
    due: tuple
    fires: bool
    fire_due: datetime | None
    missed: tuple
    drift_seconds: int | None
    next_due: datetime | None
    reason: str

    @property
    def missed_count(self) -> int:
        return len(self.missed)

    @property
    def words(self) -> str:
        if self.reason == "never_fires":
            return (
                f"{self.workflow} ({self.expression}): "
                "this cron never fires -- no run "
                "is due, and none is late.")
        if not self.fires:
            return (
                f"{self.workflow} ({self.expression}): "
                "nothing due; next firing "
                f"{self.next_due.isoformat() if self.next_due else 'never'}.")
        text = (
            f"{self.workflow} ({self.expression}): "
            f"due {self.fire_due.isoformat()}, "
            f"fires at {self.window_end.isoformat()} "
            f"-- {self.drift_seconds} seconds late "
            "(drift is stated, never hidden)")
        if self.missed:
            text += (
                f"; {len(self.missed)} earlier "
                "firing(s) missed and not replayed: "
                + ", ".join(
                    m.isoformat() for m in self.missed))
        return text + "."


def judge_due(entry: object,
              last_tick: object,
              now: object) -> DueJudgement:
    """Judge one schedule entry at one tick:
    the firings due in (last_tick, now] are
    enumerated; the latest fires, late by its
    drift; every earlier one is missed and
    never replayed; a firing after `now` never
    fires early. An empty window (the tick is
    the last tick) judges not-due. Pure."""
    if not isinstance(entry, ScheduledEntry):
        raise ScheduleError(
            "schedule_entry_invalid",
            "schedule_entry_invalid -- a tick "
            "judges schedule entries. Nothing "
            "was judged.")
    start = _moment(last_tick, "the last tick")
    end = _moment(now, "the tick")
    if end < start:
        raise ScheduleError(
            "schedule_window_invalid",
            "schedule_window_invalid -- a tick "
            "window runs from the last tick to "
            "now, in that order. Nothing was "
            "judged.")
    next_due = next_cron_after(entry.cron, end)
    if end == start:
        due: tuple = ()
    else:
        due = firings_between(entry.cron, start, end)
    if not due:
        return DueJudgement(
            workflow=entry.workflow,
            expression=entry.expression,
            window_start=start, window_end=end,
            due=(), fires=False, fire_due=None,
            missed=(), drift_seconds=None,
            next_due=next_due,
            reason=("never_fires" if next_due is None
                    else "not_due"))
    fire_due = due[-1]
    return DueJudgement(
        workflow=entry.workflow,
        expression=entry.expression,
        window_start=start, window_end=end,
        due=due, fires=True, fire_due=fire_due,
        missed=due[:-1],
        drift_seconds=int(
            (end - fire_due).total_seconds()),
        next_due=next_due,
        reason=("due_with_missed" if len(due) > 1
                else "due"))


@dataclass(frozen=True)
class ScheduleTick:
    """One tick judged whole: every entry's
    judgement in entry order, and the tick's
    totals -- runs that fire, firings missed
    across all entries."""
    judgements: tuple
    window_start: datetime
    window_end: datetime

    @property
    def fires_count(self) -> int:
        return sum(1 for j in self.judgements if j.fires)

    @property
    def missed_count(self) -> int:
        return sum(j.missed_count for j in self.judgements)

    @property
    def words(self) -> str:
        return (
            f"Tick {self.window_end.isoformat()}: "
            f"{self.fires_count} scheduled run(s) "
            f"fire, {self.missed_count} firing(s) "
            "missed and not replayed, over the "
            f"window from {self.window_start.isoformat()}.")


def judge_tick(entries: object,
               last_tick: object,
               now: object) -> ScheduleTick:
    """Judge every collected schedule entry at
    one tick, in entry order. The window is
    validated once, whole, before any entry is
    judged. Pure."""
    if isinstance(entries, (str, bytes)) \
            or not isinstance(entries, (list, tuple)):
        raise ScheduleError(
            "schedule_entry_invalid",
            "schedule_entry_invalid -- a tick "
            "judges a list of schedule entries. "
            "Nothing was judged.")
    start = _moment(last_tick, "the last tick")
    end = _moment(now, "the tick")
    if end < start:
        raise ScheduleError(
            "schedule_window_invalid",
            "schedule_window_invalid -- a tick "
            "window runs from the last tick to "
            "now, in that order. Nothing was "
            "judged.")
    judgements = tuple(
        judge_due(entry, start, end) for entry in entries)
    return ScheduleTick(
        judgements=judgements,
        window_start=start, window_end=end)


def tick_to_dict(tick: ScheduleTick) -> dict:
    """One tick as JSON-safe data: the window,
    the totals, and per entry the due times,
    the firing, its drift, the missed times
    and the next due -- nothing else."""
    def _stamp(moment):
        return moment.isoformat() if moment else None
    return {
        "window_start": _stamp(tick.window_start),
        "window_end": _stamp(tick.window_end),
        "fires": tick.fires_count,
        "missed": tick.missed_count,
        "entries": [{
            "workflow": j.workflow,
            "expression": j.expression,
            "reason": j.reason,
            "due": [_stamp(d) for d in j.due],
            "fires": j.fires,
            "fire_due": _stamp(j.fire_due),
            "drift_seconds": j.drift_seconds,
            "missed": [_stamp(m) for m in j.missed],
            "next_due": _stamp(j.next_due),
        } for j in tick.judgements],
    }


# ------------------------------------------------------------------
# The audit: the schedule law checked against the live instance.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class ScheduleAudit:
    """The schedule law checked against one
    live instance: the source law judges as
    stated, the schema unmoved at 131 (this
    slice mints no migration -- the judgement
    is code, not data), the taxonomy unmoved
    at 135, and no table, column or audit
    event carries a workflow-schedule surface
    of its own."""
    source_ok: bool
    schema_version: int
    schema_ok: bool
    events_scanned: int
    taxonomy_ok: bool
    tables_scanned: int
    columns_scanned: int
    offending_tables: tuple
    offending_columns: tuple
    offending_events: tuple

    @property
    def stands_cleanly(self) -> bool:
        return (
            self.source_ok and self.schema_ok
            and self.taxonomy_ok
            and not self.offending_tables
            and not self.offending_columns
            and not self.offending_events)


def _surface(name: str) -> bool:
    text = name.lower()
    return any(word in text for word in _SURFACE_WORDS)


def audit_workflow_schedules(conn: sqlite3.Connection) -> ScheduleAudit:
    """Check the schedule law against the live
    instance: the default-branch source law is
    exact, the schema is exactly 131, the
    taxonomy is exactly the standing 135, and
    no workflow-schedule surface hides in the
    schema or the taxonomy. Pure read."""
    from .db import schema_version as _schema_version
    from .workflow_triggers import parse_triggers
    version = _schema_version(conn)
    source_ok = (
        decide_schedule_source("main", "main").is_default
        and not decide_schedule_source(
            "feature", "main").is_default
        and len(scheduled_entries(
            "ci", parse_triggers(
                {"schedule": [{"cron": "0 2 * * *"}]}))) == 1
        and scheduled_entries(
            "ci", parse_triggers("push")) == ())
    taxonomy_ok = (
        len(taxonomy.AUDIT_EVENTS) == 135
        and len(taxonomy.AUTH_EVENTS) == 33
        and len(taxonomy.REPO_EVENTS) == 89
        and len(taxonomy.ADMIN_EVENTS) == 13)
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master"
        " WHERE type = 'table' ORDER BY name").fetchall()]
    offending_tables: list = []
    offending_columns: list = []
    columns_scanned = 0
    for table in tables:
        if _surface(table):
            offending_tables.append(table)
        safe = table.replace('"', '""')
        for row in conn.execute(
                f'PRAGMA table_info("{safe}")').fetchall():
            columns_scanned += 1
            if _surface(str(row[1])):
                offending_columns.append(f"{table}.{row[1]}")
    events = sorted(taxonomy.AUDIT_EVENTS)
    offending_events = [e for e in events if _surface(e)]
    return ScheduleAudit(
        source_ok=source_ok,
        schema_version=version, schema_ok=version == 131,
        events_scanned=len(events), taxonomy_ok=taxonomy_ok,
        tables_scanned=len(tables),
        columns_scanned=columns_scanned,
        offending_tables=tuple(offending_tables),
        offending_columns=tuple(offending_columns),
        offending_events=tuple(offending_events))


def render_workflow_schedules_page(
        collection: ScheduleCollection | None = None,
        tick: ScheduleTick | None = None,
        audit: ScheduleAudit | None = None) -> str:
    """Scheduled workflows, in plain words,
    where a workflow's author finds them: the
    default-branch-only source law, the drift
    law and the missed-run law, plus one
    collection's words, one tick's words and
    the checked proof when they ride along.
    Every value escaped through S-010; standing
    is said in words, never a colour alone."""
    parts = [
        "<h1>Scheduled workflows</h1>",
        "<p>A workflow's <code>schedule</code> "
        "triggers are read from the "
        "<strong>default branch only</strong>. "
        "A schedule written on any other branch "
        "does not run and is named as ignored; "
        "it starts counting when it lands on "
        "the default branch.</p>",
        "<p>A scheduled run never fires early. "
        "It fires at the first scheduler tick "
        "at or after its cron time, late by "
        "exactly that distance -- its "
        "<strong>drift</strong>, stated on the "
        "run, never hidden.</p>",
        "<p>Firings the scheduler missed while "
        "it was down are <strong>skipped, not "
        "replayed</strong>: at most one run per "
        "schedule fires at a tick, for the "
        "latest due firing, and every earlier "
        "missed firing is counted and named -- "
        "never silently dropped and never "
        "fired in a catch-up burst.</p>",
    ]
    if collection is not None:
        parts.append(
            f"<p>{escape_html_text(collection.words)}</p>")
    if tick is not None:
        parts.append(
            f"<p>{escape_html_text(tick.words)}</p>")
        for judgement in tick.judgements:
            parts.append(
                f"<p>{escape_html_text(judgement.words)}</p>")
    if audit is not None:
        state = ("stands cleanly" if audit.stands_cleanly
                 else "does not stand cleanly")
        parts.append(
            f"<p>Checked against this instance: "
            f"the schedule law {escape_html_text(state)} "
            f"(schema {audit.schema_version}, "
            f"{audit.events_scanned} audit events, "
            f"{audit.tables_scanned} tables "
            f"scanned).</p>")
    return "\n".join(parts)
