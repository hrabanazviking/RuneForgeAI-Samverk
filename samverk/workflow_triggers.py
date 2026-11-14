"""Triggers -- what fires a workflow (S-314).

S-313 decided the shape and named the trigger
vocabulary; this slice owns each trigger's
semantics and firing law, as a complete slice:
the ``on`` value of a workflow document is parsed
into an exact trigger set, an event arriving at
the forge is judged against that set by a pure
function, cron expressions are validated and
their next firing computed, and a manual
dispatch's inputs are resolved against their
declarations -- before any job exists (S-315),
any runner speaks (S-316) or any schedule is kept
by a daemon (S-326).

- **The five triggers, each with its own law.**
  ``push`` fires on a branch push and may filter
  by branches and paths. ``tag`` is Samverk's own separate event
  (GitHub folds tag creation into ``push``; the
  S-313 vocabulary names it apart, so the law is
  apart): creating a tag fires it, filtered by
  tag-name patterns. ``pull_request`` fires on a
  pull request action -- opened, synchronize and
  reopened by default, ``types`` when the author
  says otherwise -- filtered by the base branch
  and paths. ``schedule`` carries one or more
  five-field cron expressions and fires by the
  clock, read from the default branch only
  (S-313's invariant; the keeping of the clock is
  S-326's). ``workflow_dispatch`` fires by hand
  and declares its inputs: name, description,
  whether required, a default, and a type --
  string, number, boolean or choice with its
  closed option list.
- **Filters are patterns, judged in order.** A
  branches/tags/paths list is glob patterns --
  ``*`` inside one path segment, ``**`` across
  segments, ``?`` one character -- evaluated in
  document order, where a ``!`` pattern un-matches
  what an earlier pattern matched (the GitHub
  reading, kept because authors arrive knowing
  it). The ``-ignore`` twin of a filter excludes
  on any plain match and may not be combined with
  the filter itself: saying both is refused
  (``trigger_filters_conflict``) rather than
  silently preferring one. Unknown trigger names
  and unknown filter keys are refused by name
  (``trigger_event_unknown`` /
  ``trigger_key_unknown``), exactly as S-313
  refuses unknown keys in the document.
- **Cron is the classic five fields**, minute
  hour day-of-month month day-of-week, with
  ``*``, lists, ranges and steps, month and
  weekday names, day-of-week 0 and 7 both Sunday.
  When both day fields are restricted the classic
  cron rule applies -- either matching fires --
  and it is stated here because it surprises.
  ``next_cron_after`` searches eight years, so a
  February 29 schedule always answers; an
  expression that can never fire (February 31)
  answers None in words, never an exception.
- **Dispatch inputs are resolved, not trusted.**
  A provided value is checked against its
  declared type (a boolean accepts only a boolean
  or the words true/false; a number must be
  numeric; a choice must be one of its options),
  an undeclared input is refused
  (``dispatch_input_unknown``), a missing
  required input with no default is refused
  (``dispatch_input_required``), and defaults are
  themselves validated when the trigger is
  parsed, so a workflow cannot declare a default
  its own type forbids.
- **A pure judgement, like S-313.** This module
  holds no store, writes no row, audits nothing
  and keeps no clock: deciding whether an event
  fires a workflow changes nothing by being
  judged. No migration (schema stays 128), no
  taxonomy event (135 stand: 33 auth / 89 repo /
  13 admin). No workflow-run table, workflow
  schedule table or workflow trigger column
  exists yet; the audit below proves that
  absence against the live instance, and the
  battery plants a workflow-trigger table to
  prove the audit would catch one arriving
  ahead of its slice. The audit is scoped to
  workflow surfaces on purpose: the bare words
  trigger and scheduled lawfully exist already
  in other slices' machinery (the advisory
  refresh trigger, the deletion schedules) and
  are not this slice's to police. S-315
  builds jobs under these triggers, S-320 puts
  fork safety in the scheduler that consults
  them, and S-326 keeps the clock they describe.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import taxonomy
from .escaping import escape_html_text
from .workflow_format import TRIGGER_EVENTS

__all__ = [
    "CRON_SEARCH_YEARS", "DEFAULT_PR_TYPES",
    "INPUT_TYPES", "CronSchedule", "DispatchInput",
    "RepoEvent", "TriggerAudit", "TriggerDecision",
    "TriggerError", "TriggerSet", "TriggerSpec",
    "audit_workflow_triggers", "cron_matches",
    "decide_trigger", "match_patterns", "next_cron_after",
    "parse_cron", "parse_triggers",
    "render_workflow_triggers_page",
    "resolve_dispatch_inputs",
]

EVENTS = tuple(TRIGGER_EVENTS)
INPUT_TYPES = ("string", "number", "boolean", "choice")
DEFAULT_PR_TYPES = ("opened", "synchronize", "reopened")
PR_TYPES = frozenset({
    "opened", "synchronize", "reopened", "closed",
    "edited", "labeled", "unlabeled", "assigned",
    "unassigned", "review_requested", "ready_for_review",
    "converted_to_draft", "locked", "unlocked"})
_REF_KEYS = frozenset({
    "branches", "branches-ignore", "paths",
    "paths-ignore"})
_EVENT_KEYS = {
    "push": _REF_KEYS,
    "tag": frozenset({"tags", "tags-ignore"}),
    "pull_request": _REF_KEYS | {"types"},
    "schedule": frozenset(),
    "workflow_dispatch": frozenset({"inputs"}),
}
_INPUT_KEYS = frozenset({
    "description", "required", "default", "type", "options"})
CRON_SEARCH_YEARS = 8
_MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10,
    "nov": 11, "dec": 12}
_DOW_NAMES = {
    "sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4,
    "fri": 5, "sat": 6}
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class TriggerError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def _invalid(message: str) -> TriggerError:
    return TriggerError("trigger_invalid", message)


def _cron_invalid(message: str) -> TriggerError:
    return TriggerError("trigger_cron_invalid", message)


# ------------------------------------------------------------------
# Cron: the classic five fields.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class CronSchedule:
    """One validated cron expression: the original
    text and the exact value set of each field."""
    expression: str
    minutes: frozenset
    hours: frozenset
    days_of_month: frozenset
    months: frozenset
    days_of_week: frozenset
    dom_restricted: bool
    dow_restricted: bool


def _cron_atom(token: str, names: dict, lo: int,
              hi: int, field: str) -> int:
    text = token.strip().lower()
    if text in names:
        return names[text]
    if not re.fullmatch(r"[0-9]+", text):
        raise _cron_invalid(
            f"cron {field}: {token!r} is not a number"
            " or a known name.")
    value = int(text)
    if value < lo or value > hi:
        raise _cron_invalid(
            f"cron {field}: {value} is outside"
            f" {lo}-{hi}.")
    return value


def _cron_field(text: str, names: dict, lo: int,
                hi: int, field: str,
                sunday7: bool = False) -> frozenset:
    values: set = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            raise _cron_invalid(
                f"cron {field}: an empty list entry.")
        base, slash, step_text = part.partition("/")
        step = 1
        if slash:
            if not re.fullmatch(r"[0-9]+", step_text):
                raise _cron_invalid(
                    f"cron {field}: the step in"
                    f" {part!r} is not a number.")
            step = int(step_text)
            if step < 1:
                raise _cron_invalid(
                    f"cron {field}: a step is at"
                    " least 1.")
        if base == "*":
            start, end = lo, hi
        elif "-" in base:
            first, _, last = base.partition("-")
            start = _cron_atom(first, names, lo, hi, field)
            end = _cron_atom(last, names, lo, hi, field)
            if end < start:
                raise _cron_invalid(
                    f"cron {field}: the range"
                    f" {base!r} runs backwards.")
        else:
            start = end = _cron_atom(
                base, names, lo, hi, field)
            if slash:
                end = hi
        for value in range(start, end + 1, step):
            values.add(0 if (sunday7 and value == 7)
                       else value)
    return frozenset(values)


def parse_cron(expression: object) -> CronSchedule:
    """Validate one five-field cron expression.
    Every refusal names the field and the fault."""
    if not isinstance(expression, str) or not expression.strip():
        raise _cron_invalid(
            "A cron expression is non-empty text.")
    fields = expression.split()
    if len(fields) != 5:
        raise _cron_invalid(
            "A cron expression has five fields:"
            " minute hour day-of-month month"
            f" day-of-week; got {len(fields)}.")
    minutes = _cron_field(fields[0], {}, 0, 59, "minute")
    hours = _cron_field(fields[1], {}, 0, 23, "hour")
    dom = _cron_field(fields[2], {}, 1, 31, "day-of-month")
    months = _cron_field(
        fields[3], _MONTH_NAMES, 1, 12, "month")
    dow = _cron_field(
        fields[4], _DOW_NAMES, 0, 7, "day-of-week",
        sunday7=True)
    return CronSchedule(
        expression=" ".join(fields), minutes=minutes,
        hours=hours, days_of_month=dom, months=months,
        days_of_week=dow,
        dom_restricted=fields[2] != "*",
        dow_restricted=fields[4] != "*")


def _day_matches(schedule: CronSchedule, moment) -> bool:
    if moment.month not in schedule.months:
        return False
    dom_ok = moment.day in schedule.days_of_month
    cron_dow = (moment.weekday() + 1) % 7
    dow_ok = cron_dow in schedule.days_of_week
    if schedule.dom_restricted and schedule.dow_restricted:
        return dom_ok or dow_ok
    if schedule.dom_restricted:
        return dom_ok
    if schedule.dow_restricted:
        return dow_ok
    return True


def cron_matches(schedule: CronSchedule, moment) -> bool:
    """True when ``moment`` (to the minute) is one
    of the schedule's firing times."""
    return (moment.minute in schedule.minutes
            and moment.hour in schedule.hours
            and _day_matches(schedule, moment))


def next_cron_after(schedule: CronSchedule,
                    moment: datetime):
    """The first firing strictly after ``moment``,
    or None when none occurs within the search
    horizon (eight years, so February 29 always
    answers and February 31 answers None)."""
    day = moment.date()
    horizon = day + timedelta(
        days=366 * CRON_SEARCH_YEARS + 2)
    hours = sorted(schedule.hours)
    minutes = sorted(schedule.minutes)
    while day <= horizon:
        probe = datetime(
            day.year, day.month, day.day,
            tzinfo=moment.tzinfo)
        if _day_matches(schedule, probe):
            for hour in hours:
                for minute in minutes:
                    candidate = probe.replace(
                        hour=hour, minute=minute)
                    if candidate > moment:
                        return candidate
        day += timedelta(days=1)
    return None


# ------------------------------------------------------------------
# Patterns: glob filters judged in document order.
# ------------------------------------------------------------------

def _glob_regex(pattern: str) -> str:
    out: list = []
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == "*":
            if pattern[i:i + 2] == "**":
                if pattern[i:i + 3] == "**/":
                    out.append("(?:.*/)?")
                    i += 3
                else:
                    out.append(".*")
                    i += 2
            else:
                out.append("[^/]*")
                i += 1
        elif char == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(char))
            i += 1
    return "".join(out)


def _one_pattern(pattern: str, value: str) -> bool:
    return re.fullmatch(_glob_regex(pattern), value) is not None


def match_patterns(patterns, value: object) -> bool:
    """Judge ``value`` against an ordered pattern
    list: a plain pattern that matches includes,
    a ``!`` pattern that matches un-includes, and
    the last word wins. An empty list includes
    everything (no filter was stated)."""
    if not isinstance(value, str):
        return False
    included = not patterns
    for pattern in patterns or ():
        if pattern.startswith("!"):
            if _one_pattern(pattern[1:], value):
                included = False
        elif _one_pattern(pattern, value):
            included = True
    return included if patterns else True


def _ignore_match(patterns, value: object) -> bool:
    if not isinstance(value, str):
        return False
    return any(_one_pattern(p, value) for p in patterns or ())


def _paths_match(include, ignore, paths) -> bool:
    """A paths filter fires when at least one
    changed path survives it; with no changed
    paths known, a stated filter cannot be
    satisfied and the trigger does not fire."""
    if not include and not ignore:
        return True
    for path in paths or ():
        if _ignore_match(ignore, path):
            continue
        if match_patterns(include, path):
            return True
    return False


# ------------------------------------------------------------------
# Trigger specs: the parsed `on` value.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class DispatchInput:
    """One declared workflow_dispatch input."""
    name: str
    description: str
    required: bool
    default: object
    type: str
    options: tuple


@dataclass(frozen=True)
class TriggerSpec:
    """One event's trigger law: its filters, its
    cron schedules (schedule only) and its declared
    inputs (workflow_dispatch only)."""
    event: str
    branches: tuple = ()
    branches_ignore: tuple = ()
    tags: tuple = ()
    tags_ignore: tuple = ()
    paths: tuple = ()
    paths_ignore: tuple = ()
    types: tuple = ()
    crons: tuple = ()
    inputs: tuple = ()


@dataclass(frozen=True)
class TriggerSet:
    """A workflow's whole trigger set, in document
    order."""
    specs: tuple

    @property
    def events(self) -> tuple:
        return tuple(spec.event for spec in self.specs)

    def for_event(self, event: object):
        for spec in self.specs:
            if spec.event == event:
                return spec
        return None


def _pattern_list(value: object, where: str,
                  ignore: bool = False) -> tuple:
    if isinstance(value, str):
        items = (value,)
    elif isinstance(value, (list, tuple)):
        items = tuple(value)
    else:
        raise _invalid(
            f"{where}: a filter is a pattern or a"
            " list of patterns.")
    for item in items:
        if not isinstance(item, str) or not item:
            raise _invalid(
                f"{where}: every pattern is"
                " non-empty text.")
        if ignore and item.startswith("!"):
            raise _invalid(
                f"{where}: an -ignore pattern may"
                " not be negated; it already"
                " excludes.")
    return tuple(items)


def _check_conflicts(spec: TriggerSpec) -> None:
    for include, ignore, label in (
            (spec.branches, spec.branches_ignore, "branches"),
            (spec.tags, spec.tags_ignore, "tags"),
            (spec.paths, spec.paths_ignore, "paths")):
        if include and ignore:
            raise TriggerError(
                "trigger_filters_conflict",
                f"{spec.event}: {label} and"
                f" {label}-ignore are both stated;"
                " say one or the other.")


def _coerce_input(spec: DispatchInput, value: object,
                  where: str):
    """Check one value against its declared type;
    returns the resolved value."""
    if spec.type == "string":
        if not isinstance(value, str):
            raise TriggerError(
                "dispatch_input_invalid",
                f"{where}: a string input is text.")
        return value
    if spec.type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in (
                "true", "false"):
            return value.lower() == "true"
        raise TriggerError(
            "dispatch_input_invalid",
            f"{where}: a boolean input is true or"
            " false.")
    if spec.type == "number":
        if isinstance(value, bool):
            raise TriggerError(
                "dispatch_input_invalid",
                f"{where}: a boolean is not a number.")
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            try:
                number = float(value)
            except ValueError:
                number = None
            if number is not None:
                return int(number) if number.is_integer() else number
        raise TriggerError(
            "dispatch_input_invalid",
            f"{where}: a number input is numeric.")
    if spec.type == "choice":
        if isinstance(value, str) and value in spec.options:
            return value
        raise TriggerError(
            "dispatch_input_invalid",
            f"{where}: a choice input is one of:"
            f" {', '.join(spec.options)}.")
    raise _invalid(f"{where}: unknown input type.")


def _parse_inputs(value: object) -> tuple:
    if value is None:
        return ()
    if not isinstance(value, dict):
        raise _invalid(
            "workflow_dispatch: inputs is a mapping"
            " of input names to declarations.")
    inputs: list = []
    for name, declaration in value.items():
        where = f"workflow_dispatch input {name!r}"
        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise _invalid(
                "workflow_dispatch: every input name"
                " is a plain identifier.")
        if declaration is None:
            declaration = {}
        if not isinstance(declaration, dict):
            raise _invalid(
                f"{where}: a declaration is a mapping.")
        unknown = sorted(set(declaration) - _INPUT_KEYS)
        if unknown:
            raise TriggerError(
                "trigger_key_unknown",
                f"{where}: unknown key(s):"
                f" {', '.join(unknown)}. An input"
                " carries: description, required,"
                " default, type, options.")
        description = declaration.get("description", "")
        if not isinstance(description, str):
            raise _invalid(f"{where}: description is text.")
        required = declaration.get("required", False)
        if not isinstance(required, bool):
            raise _invalid(f"{where}: required is a boolean.")
        input_type = declaration.get("type", "string")
        if input_type not in INPUT_TYPES:
            raise _invalid(
                f"{where}: type is one of:"
                f" {', '.join(INPUT_TYPES)}.")
        options_value = declaration.get("options")
        if input_type == "choice":
            if not isinstance(options_value, (list, tuple)) \
                    or not options_value:
                raise _invalid(
                    f"{where}: a choice input names"
                    " its options.")
            options = tuple(options_value)
            for option in options:
                if not isinstance(option, str) or not option:
                    raise _invalid(
                        f"{where}: every option is"
                        " non-empty text.")
        else:
            if options_value is not None:
                raise _invalid(
                    f"{where}: options belong to a"
                    " choice input only.")
            options = ()
        spec = DispatchInput(
            name=name, description=description,
            required=required, default=None,
            type=input_type, options=options)
        default = declaration.get("default")
        if default is not None:
            default = _coerce_input(spec, default, where)
            spec = DispatchInput(
                name=name, description=description,
                required=required, default=default,
                type=input_type, options=options)
        inputs.append(spec)
    return tuple(inputs)


def _parse_spec(event: str, config: object) -> TriggerSpec:
    if event == "schedule":
        if not isinstance(config, (list, tuple)) or not config:
            raise _invalid(
                "schedule: a non-empty list of cron"
                " entries is required, each a mapping"
                " with one cron: key.")
        crons: list = []
        for entry in config:
            if not isinstance(entry, dict) \
                    or set(entry) != {"cron"}:
                raise _invalid(
                    "schedule: every entry is a"
                    " mapping with one cron: key.")
            crons.append(parse_cron(entry["cron"]))
        return TriggerSpec(event=event, crons=tuple(crons))
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise _invalid(
            f"{event}: a trigger's filters form a"
            " mapping (schedule alone takes a list).")
    unknown = sorted(set(config) - _EVENT_KEYS[event])
    if unknown:
        raise TriggerError(
            "trigger_key_unknown",
            f"{event}: unknown key(s):"
            f" {', '.join(unknown)}. This trigger"
            f" carries: {', '.join(sorted(_EVENT_KEYS[event]))}.")
    spec = TriggerSpec(
        event=event,
        branches=_pattern_list(
            config["branches"], f"{event} branches")
        if "branches" in config else (),
        branches_ignore=_pattern_list(
            config["branches-ignore"],
            f"{event} branches-ignore", ignore=True)
        if "branches-ignore" in config else (),
        tags=_pattern_list(
            config["tags"], f"{event} tags")
        if "tags" in config else (),
        tags_ignore=_pattern_list(
            config["tags-ignore"],
            f"{event} tags-ignore", ignore=True)
        if "tags-ignore" in config else (),
        paths=_pattern_list(
            config["paths"], f"{event} paths")
        if "paths" in config else (),
        paths_ignore=_pattern_list(
            config["paths-ignore"],
            f"{event} paths-ignore", ignore=True)
        if "paths-ignore" in config else (),
        inputs=_parse_inputs(config.get("inputs"))
        if event == "workflow_dispatch" else ())
    if event == "pull_request" and "types" in config:
        raw = config["types"]
        if isinstance(raw, str):
            raw = (raw,)
        if not isinstance(raw, (list, tuple)) or not raw:
            raise _invalid(
                "pull_request: types is a list of"
                " action names.")
        for item in raw:
            if item not in PR_TYPES:
                raise _invalid(
                    "pull_request: unknown action"
                    f" {item!r}; the actions are:"
                    f" {', '.join(sorted(PR_TYPES))}.")
        spec = TriggerSpec(
            event=event, branches=spec.branches,
            branches_ignore=spec.branches_ignore,
            tags=spec.tags, tags_ignore=spec.tags_ignore,
            paths=spec.paths, paths_ignore=spec.paths_ignore,
            types=tuple(raw), inputs=spec.inputs)
    if event == "tag" and (
            spec.branches or spec.branches_ignore
            or spec.paths or spec.paths_ignore):
        raise _invalid(
            "tag: a tag trigger filters by tags"
            " only; branches and paths do not"
            " apply to a tag's creation.")
    _check_conflicts(spec)
    return spec


def parse_triggers(on_value: object) -> TriggerSet:
    """Parse a workflow document's ``on`` value --
    a name, a list of names, or a mapping of names
    to their filter mappings -- into the exact
    trigger set S-314 judges by. S-313's validator
    owns the document's shape; this owns the
    triggers' own law, so a mapping form the
    shape admits is judged here in full."""
    if isinstance(on_value, bool) or on_value is None:
        raise _invalid(
            "on: the triggers are a name, a list of"
            " names or a mapping -- never a boolean"
            " (the YAML 1.1 reading of the word on).")
    if isinstance(on_value, str):
        pairs = ((on_value, None),)
    elif isinstance(on_value, (list, tuple)):
        if not on_value:
            raise _invalid("on: at least one trigger is named.")
        pairs = tuple((item, None) for item in on_value)
    elif isinstance(on_value, dict):
        if not on_value:
            raise _invalid("on: at least one trigger is named.")
        pairs = tuple(on_value.items())
    else:
        raise _invalid(
            "on: the triggers are a name, a list of"
            " names or a mapping.")
    specs: list = []
    seen: set = set()
    for event, config in pairs:
        if not isinstance(event, str) or event not in EVENTS:
            raise TriggerError(
                "trigger_event_unknown",
                f"Unknown trigger {event!r}; the"
                f" triggers are: {', '.join(EVENTS)}.")
        if event in seen:
            raise _invalid(f"on: {event} is named twice.")
        seen.add(event)
        specs.append(_parse_spec(event, config))
    return TriggerSet(specs=tuple(specs))


# ------------------------------------------------------------------
# The firing judgement.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class RepoEvent:
    """One thing that happened in a repository, as
    the trigger judge needs to see it: its kind,
    the branch or tag it concerns, the paths it
    changed, and its action (pull requests)."""
    kind: str
    branch: str = ""
    tag: str = ""
    paths: tuple = ()
    action: str = ""


@dataclass(frozen=True)
class TriggerDecision:
    """The judge's answer, in words: whether the
    workflow fires, for which event, and why --
    a filter refusal names the filter."""
    fires: bool
    event: str
    reason: str


def decide_trigger(triggers: TriggerSet,
                   event: RepoEvent) -> TriggerDecision:
    """Judge one repository event against a
    workflow's trigger set. Pure: the same event
    and set always answer the same, and nothing is
    recorded by the judging."""
    if event.kind not in EVENTS:
        raise TriggerError(
            "trigger_event_unknown",
            f"Unknown event kind {event.kind!r};"
            f" the triggers are: {', '.join(EVENTS)}.")
    spec = triggers.for_event(event.kind)
    if spec is None:
        return TriggerDecision(
            False, event.kind, "event_not_configured")
    if event.kind in ("schedule", "workflow_dispatch"):
        return TriggerDecision(
            False, event.kind, "not_an_event_trigger")
    if event.kind == "push":
        if event.tag:
            return TriggerDecision(
                False, event.kind, "tag_push_is_tag_event")
        if _ignore_match(spec.branches_ignore, event.branch) \
                or not match_patterns(spec.branches, event.branch):
            return TriggerDecision(
                False, event.kind, "branch_filtered")
        if not _paths_match(spec.paths, spec.paths_ignore,
                            event.paths):
            return TriggerDecision(
                False, event.kind, "path_filtered")
        return TriggerDecision(True, event.kind, "matched")
    if event.kind == "tag":
        if _ignore_match(spec.tags_ignore, event.tag) \
                or not match_patterns(spec.tags, event.tag):
            return TriggerDecision(
                False, event.kind, "tag_filtered")
        return TriggerDecision(True, event.kind, "matched")
    # pull_request: branches judge the base branch.
    types = spec.types or DEFAULT_PR_TYPES
    if event.action not in types:
        return TriggerDecision(
            False, event.kind, "type_filtered")
    if _ignore_match(spec.branches_ignore, event.branch) \
            or not match_patterns(spec.branches, event.branch):
        return TriggerDecision(
            False, event.kind, "branch_filtered")
    if not _paths_match(spec.paths, spec.paths_ignore,
                        event.paths):
        return TriggerDecision(
            False, event.kind, "path_filtered")
    return TriggerDecision(True, event.kind, "matched")


def resolve_dispatch_inputs(triggers: TriggerSet,
                            provided: object) -> dict:
    """Resolve a manual dispatch: the values the
    run would carry, defaults filled, every value
    checked against its declaration, in declaration
    order. Refusals name the input."""
    spec = triggers.for_event("workflow_dispatch")
    if spec is None:
        raise TriggerError(
            "trigger_event_unknown",
            "This workflow declares no"
            " workflow_dispatch trigger.")
    if provided is None:
        provided = {}
    if not isinstance(provided, dict):
        raise _invalid(
            "workflow_dispatch: the provided inputs"
            " form a mapping.")
    declared = {item.name: item for item in spec.inputs}
    for key in provided:
        if key not in declared:
            raise TriggerError(
                "dispatch_input_unknown",
                f"workflow_dispatch: no input named"
                f" {key!r} is declared.")
    resolved: dict = {}
    for item in spec.inputs:
        where = f"workflow_dispatch input {item.name!r}"
        if item.name in provided:
            resolved[item.name] = _coerce_input(
                item, provided[item.name], where)
        elif item.default is not None:
            resolved[item.name] = item.default
        elif item.required:
            raise TriggerError(
                "dispatch_input_required",
                f"{where}: a required input was"
                " not provided and declares no"
                " default.")
    return resolved


# ------------------------------------------------------------------
# The audit: the trigger law checked against the live instance.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class TriggerAudit:
    """The trigger law checked against one live
    instance: the vocabulary's own integrity, how
    much schema was inspected, and every
    workflow-trigger-shaped name found in it. The
    law stands cleanly only while no table, column
    or audit event carries a workflow trigger,
    schedule, cron, dispatch or run surface yet
    -- S-315 and later slices mint theirs when
    they land. Names are workflow-scoped: other
    slices lawfully own a bare trigger column or
    a scheduled_at, and this audit does not claim
    them."""
    events_ok: bool
    tables_scanned: int
    columns_scanned: int
    events_scanned: int
    offending_tables: tuple
    offending_columns: tuple
    offending_events: tuple

    @property
    def stands_cleanly(self) -> bool:
        return (self.events_ok
                and not self.offending_tables
                and not self.offending_columns
                and not self.offending_events)


_WORDS = ("trigger", "schedule", "cron", "dispatch", "run")


def _workflow_surface(name: str) -> bool:
    text = name.lower()
    return "workflow" in text and any(
        word in text for word in _WORDS)


def audit_workflow_triggers(conn: sqlite3.Connection) -> TriggerAudit:
    """Check the trigger law against the live
    instance: the vocabulary is exactly S-313's
    five events, and no table, column or audit
    event carries a workflow trigger surface --
    one arriving ahead of its slice would be the
    law broken by a back door. Pure read."""
    events_ok = tuple(EVENTS) == tuple(TRIGGER_EVENTS) \
        and len(set(EVENTS)) == 5
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master"
        " WHERE type = 'table' ORDER BY name").fetchall()]
    offending_tables: list = []
    offending_columns: list = []
    columns_scanned = 0
    for table in tables:
        if _workflow_surface(table):
            offending_tables.append(table)
        safe = table.replace('"', '""')
        for row in conn.execute(
                f'PRAGMA table_info("{safe}")').fetchall():
            columns_scanned += 1
            if _workflow_surface(str(row[1])):
                offending_columns.append(f"{table}.{row[1]}")
    events = sorted(taxonomy.AUDIT_EVENTS)
    offending_events = [
        e for e in events if _workflow_surface(e)]
    return TriggerAudit(
        events_ok=events_ok,
        tables_scanned=len(tables),
        columns_scanned=columns_scanned,
        events_scanned=len(events),
        offending_tables=tuple(offending_tables),
        offending_columns=tuple(offending_columns),
        offending_events=tuple(offending_events))


def render_workflow_triggers_page(
        audit: TriggerAudit | None = None) -> str:
    """The trigger law, rendered: the five triggers
    and their filters said in words, the cron and
    dispatch rules, and the checked proof when an
    audit rides along -- every value escaped, the
    state said in words, never colour-only."""
    parts = [
        "<h1>Workflow triggers (S-314)</h1>",
        "<p>A workflow fires when its trigger says"
        " so: <strong>push</strong> on a branch push,"
        " <strong>tag</strong> on a tag's creation,"
        " <strong>pull_request</strong> on a pull"
        " request action, <strong>schedule</strong>"
        " by the clock, and"
        " <strong>workflow_dispatch</strong> by"
        " hand, with its declared inputs. Filters"
        " are glob patterns judged in order;"
        " a filter and its -ignore twin are never"
        " both stated.</p>",
        "<h2>Cron</h2>",
        "<p>Five fields -- minute, hour,"
        " day-of-month, month, day-of-week -- with"
        " lists, ranges, steps and names. When both"
        " day fields are restricted, either matching"
        " fires: the classic cron rule, stated"
        " because it surprises.</p>",
        "<h2>Dispatch inputs</h2>",
        "<p>Each input declares a type -- string,"
        " number, boolean or choice -- whether it"
        " is required, and a default the type"
        " itself must admit. A dispatch carrying an"
        " undeclared input, or missing a required"
        " one, is refused in words.</p>",
    ]
    if audit is not None:
        state = ("stands cleanly" if audit.stands_cleanly
                 else "does NOT stand cleanly")
        parts.append("<h2>Checked against this instance</h2>")
        parts.append(
            f"<p>The trigger law {escape_html_text(state)}: "
            f"{audit.tables_scanned} tables and "
            f"{audit.columns_scanned} columns scanned, "
            f"{audit.events_scanned} audit events scanned; "
            f"offending tables: "
            f"{escape_html_text(', '.join(audit.offending_tables) or 'none')}; "
            f"offending columns: "
            f"{escape_html_text(', '.join(audit.offending_columns) or 'none')}; "
            f"offending events: "
            f"{escape_html_text(', '.join(audit.offending_events) or 'none')}.</p>")
    return "\n".join(parts)
