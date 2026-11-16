"""Skip markers -- [skip ci] and kin (S-325).

Skip markers -- `[skip ci]` and kin honoured for
push/PR triggers; required checks treat skipped
as *not passed*, never as passed (the known trap,
named in the study file).

S-314 built the trigger judge: an event arriving
at the forge is judged against a workflow's
trigger set by the pure `decide_trigger`. What
no slice built is the author's own off switch --
the marker a pusher writes in a commit message
(or a pull request's title) to say *do not run CI
for this*. This slice is that switch, and the
guard on the trap that comes with it:

- **The marker set is GitHub's, word for word.**
  Five markers, matched case-insensitively as
  whole bracketed tokens in the text handed:
  ``[skip ci]``, ``[ci skip]``, ``[no ci]``,
  ``[skip actions]`` and ``[actions skip]``.
  The bare words `skip ci` without brackets are
  prose, not a marker; a half-bracket is not a
  marker. `find_skip_markers` answers the markers
  found in order of first appearance across the
  texts it is handed, each named once, in the
  canonical lower-case spelling.
- **Honoured for push and pull_request only.**
  `decide_firing` judges the event through
  S-314's own `decide_trigger` first (its
  refusals ride verbatim), then applies the
  marker: a push or pull_request event carrying
  a marker does not fire, whatever its filters
  said -- the author's word is the reason, and
  the trigger's own reason is kept on the
  decision as `trigger_reason` so a filtered
  event is not misreported as a firing one.
  A marker on any other event (tag, schedule,
  workflow_dispatch) is recorded but NOT
  honoured: a tag's creation, the clock and a
  maintainer's hand are not a pusher's message
  to suppress, and a dispatch is how a skipped
  workflow is run anyway.
- **Skipped is not passed -- the trap, closed.**
  A workflow suppressed by a marker never runs,
  so it lands no check (S-321's standing law: a
  job that never runs sends no conclusion). The
  known trap is the other road: a system that
  lands a check run with conclusion `skipped`
  and folds it onto the panel as `passed`
  (S-246's fold does exactly that for a job that
  ran and was skipped by its own steps) would
  let a required check be satisfied by a run
  that never happened. `judge_required_checks`
  is the required-checks judge for a skipped
  run: handed the required contexts, the panel
  rows standing on the head commit, and the
  contexts the skipped workflow would have
  produced (named by S-321's `check_name_for`
  through `contexts_for_run`), it answers one
  verdict per required context -- and a skipped
  context is `skipped`, which counts as NOT
  passed, whatever state a row on the panel
  claims for it, even `passed`. Every other
  context is judged exactly as S-174 judges:
  `passed` satisfies, `failed` fails, `pending`
  pends, and no row is `missing`, which blocks.
  The gate is satisfied only when every required
  context counts as passed, so a skipped
  required check blocks the merge until the
  workflow is run for real (a dispatch, or a
  push without the marker) and its checks land
  passed on the new head.
- **A pure judgement, like S-314 and S-320.**
  This module holds no store, writes no row,
  audits nothing and runs nothing: honouring a
  marker changes nothing by being judged, and
  the verdict is data (`verdict_to_dict` carries
  contexts, states and reasons, nothing else).
  No migration (schema stays 131), no taxonomy
  event (135 stand: 33 auth / 89 repo / 13
  admin). No skip-marker table, column or audit
  event exists; the audit below proves that
  absence against the live instance, and the
  battery plants a skip-marker table to prove
  the audit would catch one arriving ahead of
  its slice. S-324 owns re-run and cancel (the
  road that runs a skipped workflow again),
  S-326 the schedule clock, S-327 the run pages
  that will render these decisions in the UI.

Honest limits, stated plainly: the marker is
judged in the texts the caller hands -- for a
push, the head commit's message (the GitHub
reading; an earlier commit's marker does not
suppress a push its head does not repeat); for
a pull request, the title and the head commit's
message. This slice judges no git object and
fetches no message itself; the caller that
knows the head names its texts. A job-level
`skipped` conclusion (S-316's aggregate, landed
by S-321) is a different word with a different
law -- that job ran -- and this slice does not
rewrite S-246's or S-321's fold for it; the
guard here binds the trigger-level skip, where
nothing ran at all.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from . import taxonomy
from .check_reporting import check_name_for
from .escaping import escape_html_text
from .pull_request_checks import CHECK_STATES
from .workflow_triggers import (
    RepoEvent, TriggerDecision, TriggerSet, decide_trigger)

__all__ = [
    "SKIP_MARKERS", "SKIPPABLE_EVENTS",
    "ContextVerdict", "RequiredChecksVerdict",
    "SkipAudit", "SkipDecision", "SkipMarkerError",
    "audit_skip_markers", "contexts_for_run",
    "decide_firing", "find_skip_markers",
    "judge_required_checks",
    "render_skip_markers_page", "verdict_to_dict",
]

#: The marker set, GitHub's five, in canonical
#: lower-case spelling. Matched case-insensitively
#: as whole bracketed tokens.
SKIP_MARKERS = (
    "[skip ci]", "[ci skip]", "[no ci]",
    "[skip actions]", "[actions skip]")

#: The events a marker may suppress: the two a
#: pusher's or author's message can ride.
SKIPPABLE_EVENTS = ("push", "pull_request")

#: The panel state a skipped required context is
#: judged at: never passed, never failed -- the
#: run simply did not happen.
SKIPPED_STATE = "skipped"

_SURFACE_WORDS = ("skip_marker", "ci_skip")


class SkipMarkerError(ValueError):
    """One refused skip-marker call: a
    machine-branchable reason with its human
    detail, in the house shape."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


# ------------------------------------------------------------------
# The markers themselves.
# ------------------------------------------------------------------

def find_skip_markers(*texts: object) -> tuple:
    """The skip markers standing in the handed
    texts, in order of first appearance across
    the texts in argument order, each named once
    in canonical spelling. A text is a commit
    message or a pull-request title; None reads
    as no text. Matching is case-insensitive and
    the brackets are part of the marker. Pure."""
    found: list = []
    for text in texts:
        if text is None:
            continue
        if not isinstance(text, str):
            raise SkipMarkerError(
                "skip_text_invalid",
                "skip_text_invalid -- a skip marker "
                "is judged in text: a commit message "
                "or a pull-request title. Nothing "
                "was judged.")
        lowered = text.lower()
        hits = sorted(
            (lowered.find(marker), marker)
            for marker in SKIP_MARKERS
            if marker in lowered)
        for _at, marker in hits:
            if marker not in found:
                found.append(marker)
    return tuple(found)


# ------------------------------------------------------------------
# The firing judgement: S-314's judge, marker applied.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class SkipDecision:
    """The firing answer with the marker applied:
    whether the workflow fires, whether a marker
    suppressed it, the markers found, the reason
    this judgement gives, and S-314's own reason
    kept beside it."""
    fires: bool
    event: str
    skipped: bool
    markers: tuple
    reason: str
    trigger_reason: str

    @property
    def words(self) -> str:
        if self.skipped:
            return (
                f"{self.event} suppressed by skip "
                f"marker(s) {', '.join(self.markers)} "
                f"-- the workflow does not run.")
        if self.fires:
            return f"{self.event} fires -- matched."
        return (
            f"{self.event} does not fire -- "
            f"{self.trigger_reason}.")


def decide_firing(triggers: TriggerSet,
                  event: RepoEvent,
                  *texts: object) -> SkipDecision:
    """Judge one repository event against a
    workflow's trigger set with the skip markers
    in the handed texts applied. S-314 judges
    first (its refusals ride verbatim); a marker
    on a push or pull_request event then
    suppresses the firing whatever the filters
    said, with the trigger's reason preserved.
    A marker on any other event is recorded on
    the decision but does not suppress. Pure."""
    markers = find_skip_markers(*texts)
    base: TriggerDecision = decide_trigger(triggers, event)
    if markers and event.kind in SKIPPABLE_EVENTS:
        return SkipDecision(
            fires=False, event=event.kind, skipped=True,
            markers=markers, reason="skip_marker",
            trigger_reason=base.reason)
    return SkipDecision(
        fires=base.fires, event=event.kind, skipped=False,
        markers=markers, reason=base.reason,
        trigger_reason=base.reason)


# ------------------------------------------------------------------
# Required checks: skipped is not passed.
# ------------------------------------------------------------------

def contexts_for_run(workflow: object,
                     job_ids: object) -> tuple:
    """The check contexts one run of a workflow
    would produce: one S-321 name per job,
    ``<workflow> / <job>``, in the order handed.
    A skipped run produces these contexts and
    lands none of them. Pure."""
    if isinstance(job_ids, (str, bytes)) \
            or not isinstance(job_ids, (list, tuple)):
        raise SkipMarkerError(
            "skip_jobs_invalid",
            "skip_jobs_invalid -- a run's jobs are "
            "a list of job names. Nothing was "
            "judged.")
    return tuple(
        check_name_for(workflow, job) for job in job_ids)


@dataclass(frozen=True)
class ContextVerdict:
    """One required context judged: its state for
    gate purposes (`passed`, `failed`, `pending`,
    `missing` or `skipped`), the state a panel row
    recorded for it (empty when no row stands),
    and whether it counts as passed. A `skipped`
    context never counts as passed."""
    context: str
    state: str
    recorded_state: str
    counts_as_passed: bool


@dataclass(frozen=True)
class RequiredChecksVerdict:
    """Every required context judged at once, in
    requirement order: satisfied only when every
    one counts as passed; blockers names every
    context that does not, skipped included."""
    verdicts: tuple
    satisfied: bool
    blockers: tuple

    @property
    def words(self) -> str:
        passed = sum(
            1 for v in self.verdicts if v.counts_as_passed)
        text = (
            f"{passed} of {len(self.verdicts)} required "
            f"checks count as passed")
        if self.blockers:
            text += (
                f"; blocked by: {', '.join(self.blockers)}")
        return text + "."


def _result_pair(result: object):
    """One panel result as a (context, state)
    pair: a PullRequestCheck-shaped object, a
    mapping, or a two-item pair."""
    if hasattr(result, "context") and hasattr(result, "state"):
        return str(result.context), result.state
    if isinstance(result, dict):
        return str(result.get("context")), result.get("state")
    if isinstance(result, (list, tuple)) and len(result) == 2:
        return str(result[0]), result[1]
    raise SkipMarkerError(
        "skip_result_invalid",
        "skip_result_invalid -- a check result is "
        "a panel row, a mapping, or a (context, "
        "state) pair. Nothing was judged.")


def judge_required_checks(required: object,
                          results: object,
                          skipped_contexts: object = ()
                          ) -> RequiredChecksVerdict:
    """Judge the required checks on one head
    commit, with the trigger-level skip applied.
    `required` is the contexts a branch rule
    requires, in order; `results` is the panel
    rows standing on the head (the latest row
    for a context stands, as S-157's record
    updates in place); `skipped_contexts` is the
    contexts a marker-skipped workflow would
    have produced. A skipped context answers
    `skipped` and counts as NOT passed whatever
    its recorded state -- even `passed`, the
    trap's exact shape. Every other context is
    judged as S-174 judges. Pure."""
    if isinstance(required, (str, bytes)) \
            or not isinstance(required, (list, tuple)):
        raise SkipMarkerError(
            "skip_required_invalid",
            "skip_required_invalid -- the required "
            "checks are a list of context names. "
            "Nothing was judged.")
    contexts: list = []
    for item in required:
        if not isinstance(item, str) or not item.strip():
            raise SkipMarkerError(
                "skip_required_invalid",
                "skip_required_invalid -- every "
                "required check names its context. "
                "Nothing was judged.")
        contexts.append(item.strip())
    skipped = {str(name) for name in (skipped_contexts or ())}
    recorded: dict = {}
    for result in results or ():
        context, state = _result_pair(result)
        if state not in CHECK_STATES:
            raise SkipMarkerError(
                "skip_result_invalid",
                f"skip_result_invalid -- {state!r} "
                "is not a check state: a state is "
                "pending, failed or passed. Nothing "
                "was judged.")
        recorded[context] = state
    verdicts: list = []
    for context in contexts:
        state = recorded.get(context, "")
        if context in skipped:
            verdicts.append(ContextVerdict(
                context=context, state=SKIPPED_STATE,
                recorded_state=state, counts_as_passed=False))
        elif not state:
            verdicts.append(ContextVerdict(
                context=context, state="missing",
                recorded_state="", counts_as_passed=False))
        else:
            verdicts.append(ContextVerdict(
                context=context, state=state,
                recorded_state=state,
                counts_as_passed=state == "passed"))
    blockers = tuple(
        v.context for v in verdicts if not v.counts_as_passed)
    return RequiredChecksVerdict(
        verdicts=tuple(verdicts),
        satisfied=not blockers, blockers=blockers)


def verdict_to_dict(verdict: RequiredChecksVerdict) -> dict:
    """One verdict as JSON-safe data: contexts,
    gate states, recorded states and the pass
    flags -- nothing else."""
    return {
        "satisfied": verdict.satisfied,
        "blockers": list(verdict.blockers),
        "checks": [{
            "context": v.context,
            "state": v.state,
            "recorded_state": v.recorded_state,
            "counts_as_passed": v.counts_as_passed,
        } for v in verdict.verdicts],
    }


# ------------------------------------------------------------------
# The audit: the skip law checked against the live instance.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class SkipAudit:
    """The skip law checked against one live
    instance: the marker set is exactly the five,
    the skippable events are S-314 push and
    pull_request triggers, the schema unmoved at
    131 (this slice mints no migration -- the
    judgement is code, not data), the taxonomy
    unmoved at 135, and no table, column or audit
    event carries a skip-marker surface of its
    own."""
    markers_ok: bool
    events_ok: bool
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
            self.markers_ok and self.events_ok
            and self.schema_ok and self.taxonomy_ok
            and not self.offending_tables
            and not self.offending_columns
            and not self.offending_events)


def _surface(name: str) -> bool:
    text = name.lower()
    return any(word in text for word in _SURFACE_WORDS)


def audit_skip_markers(conn: sqlite3.Connection) -> SkipAudit:
    """Check the skip law against the live
    instance: the markers and skippable events
    are exact, the schema is exactly 131, the
    taxonomy is exactly the standing 135, and no
    skip-marker surface hides in the schema or
    the taxonomy. Pure read."""
    from .db import schema_version as _schema_version
    from .workflow_format import TRIGGER_EVENTS
    version = _schema_version(conn)
    markers_ok = (
        SKIP_MARKERS == (
            "[skip ci]", "[ci skip]", "[no ci]",
            "[skip actions]", "[actions skip]")
        and find_skip_markers("x [SKIP CI] y") == ("[skip ci]",)
        and find_skip_markers("no markers here") == ())
    events_ok = (
        SKIPPABLE_EVENTS == ("push", "pull_request")
        and all(e in TRIGGER_EVENTS for e in SKIPPABLE_EVENTS))
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
    return SkipAudit(
        markers_ok=markers_ok, events_ok=events_ok,
        schema_version=version, schema_ok=version == 131,
        events_scanned=len(events), taxonomy_ok=taxonomy_ok,
        tables_scanned=len(tables),
        columns_scanned=columns_scanned,
        offending_tables=tuple(offending_tables),
        offending_columns=tuple(offending_columns),
        offending_events=tuple(offending_events))


def render_skip_markers_page(
        decision: SkipDecision | None = None,
        verdict: RequiredChecksVerdict | None = None,
        audit: SkipAudit | None = None) -> str:
    """Skip markers, in plain words, where a
    workflow's author finds them: the five
    markers, the two events they bind, and the
    required-checks law -- a skipped check has
    not passed and blocks until the workflow
    runs for real -- plus one decision's words,
    one verdict's words and the checked proof
    when they ride along. Every value escaped
    through S-010; standing is said in words,
    never a colour alone."""
    parts = [
        "<h1>Skip markers</h1>",
        "<p>Write <code>[skip ci]</code> -- or "
        "<code>[ci skip]</code>, <code>[no ci]</code>, "
        "<code>[skip actions]</code> or "
        "<code>[actions skip]</code> -- in a push's "
        "head commit message or a pull request's "
        "title, and the workflows that push or pull "
        "request would have fired do not run. The "
        "markers bind push and pull request only: "
        "a tag, the schedule clock and a manual "
        "dispatch are not suppressed, and a manual "
        "dispatch is how a skipped workflow is run "
        "anyway.</p>",
        "<p>A skipped workflow lands no checks, and "
        "a required check it would have produced "
        "counts as <strong>not passed</strong> -- "
        "never as passed. It blocks the merge until "
        "the workflow runs for real and its checks "
        "land passed on the head commit.</p>",
    ]
    if decision is not None:
        parts.append(
            f"<p>{escape_html_text(decision.words)}</p>")
    if verdict is not None:
        parts.append(
            f"<p>{escape_html_text(verdict.words)}</p>")
    if audit is not None:
        state = ("stands cleanly" if audit.stands_cleanly
                 else "does not stand cleanly")
        parts.append(
            f"<p>Checked against this instance: "
            f"the skip law {escape_html_text(state)} "
            f"(schema {audit.schema_version}, "
            f"{audit.events_scanned} audit events, "
            f"{audit.tables_scanned} tables "
            f"scanned).</p>")
    return "\n".join(parts)
